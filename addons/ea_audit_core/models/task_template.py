import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services.signoff_rules import effective_task_rule

SECTION_SELECTION = [
    ("A", "Financial statements"),
    ("B", "Completion"),
    ("C", "Communication"),
    ("D", "Acceptance & planning"),
    ("E", "Execution"),
    ("F", "OHADA statutory"),
]
TIER_SELECTION = [("core", "Core"), ("standard", "Standard"), ("extended", "Extended")]
TASK_PHASE_SELECTION = [
    ("acceptance", "Acceptance"),
    ("planning", "Planning"),
    ("execution", "Execution"),
    ("conclusion", "Conclusion"),
]
# The same phases with keys that sort in the order of the audit, for a list's column and its
# grouping: sorting or grouping by ``phase`` itself is alphabetical (acceptance, conclusion, ...).
PHASE_STEP_SELECTION = [("%d_%s" % (rank, key), label) for rank, (key, label) in enumerate(TASK_PHASE_SELECTION, 1)]
# What a partner edits on the sign-off matrix: the firm's own rule, blank meaning the firm default.
FIRM_RULE_FIELDS = ("firm_min_preparer", "firm_min_reviewer", "firm_partner_required")


class TaskTemplate(models.Model):
    """The default audit file index (lib/file-index.ts), loaded as data. The
    numbering gaps are intentional: do not normalize them."""

    _name = "ea.audit.task.template"
    _description = "Audit file index entry"
    _order = "sequence, id"
    _rec_name = "code"
    _rec_names_search = ["code", "title"]

    code = fields.Char(required=True, index=True)
    section = fields.Selection(SECTION_SELECTION, required=True)
    title = fields.Char(required=True, translate=True)
    short_title = fields.Char(translate=True)
    tier = fields.Selection(TIER_SELECTION, required=True, default="standard")
    conditional = fields.Boolean(help="Instantiated, but only activated when a trigger answers yes.")
    phase = fields.Selection(TASK_PHASE_SELECTION, required=True)
    sequence = fields.Integer(default=10)

    # The firm's matrix (F002): what applies to this task today, the firm's own rules included.
    # "min": a list grouped by phase or section orders its groups by their first task, not by a sum
    matrix_order = fields.Integer(compute="_compute_matrix_order", store=True, index=True, aggregator="min")
    matrix_min_preparer = fields.Selection(selection="_ladder_selection", string="Minimum preparer", compute="_compute_matrix")
    matrix_min_reviewer = fields.Selection(selection="_ladder_selection", string="Minimum reviewer", compute="_compute_matrix")
    matrix_partner = fields.Boolean(string="Partner sign-off", compute="_compute_matrix")
    matrix_firm_rule = fields.Boolean(string="Firm's own rule", compute="_compute_matrix")
    # Edited on the matrix itself, saved through save_task_rules (its checks and its audit log).
    firm_min_preparer = fields.Selection(
        selection="_ladder_selection", string="Firm's minimum preparer", compute="_compute_firm_rule",
        inverse="_inverse_firm_rule", help="Blank: the firm default applies.",
    )
    firm_min_reviewer = fields.Selection(
        selection="_ladder_selection", string="Firm's minimum reviewer", compute="_compute_firm_rule",
        inverse="_inverse_firm_rule", help="Blank: the firm default applies.",
    )
    firm_partner_required = fields.Selection(
        selection="_partner_required_selection", string="Firm's partner sign-off", compute="_compute_firm_rule",
        inverse="_inverse_firm_rule",
    )

    # The file index in the order of the audit, acceptance to conclusion (owner, 2026-11-07).
    phase_step = fields.Selection(PHASE_STEP_SELECTION, string="Phase", compute="_compute_phase_step", store=True)
    chrono_no = fields.Integer(string="Order", readonly=True, copy=False, aggregator="min", help="Position in the audit, from acceptance to conclusion.")

    _code_uniq = models.Constraint("UNIQUE(code)", "This task code already exists.")

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        self._ea_renumber()
        return templates

    def init(self):
        # an update adds chrono_no to rows that exist already: number them once the column is there
        self.env.cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = 'chrono_no'", [self._table])
        if self.env.cr.fetchone():
            self._ea_renumber()

    @api.model
    def _ea_renumber(self):
        """chrono_no: 1, 2, 3... in matrix order, i.e. phase then code."""
        self.flush_model(["matrix_order"])
        self.env.cr.execute("""
            UPDATE ea_audit_task_template t SET chrono_no = r.n
              FROM (SELECT id, row_number() OVER (ORDER BY matrix_order, id) AS n FROM ea_audit_task_template) r
             WHERE t.id = r.id AND t.chrono_no IS DISTINCT FROM r.n
        """)
        self.invalidate_model(["chrono_no"])

    def write(self, vals):
        """The matrix's own columns go to save_task_rules, under the caller's rights: a partner
        edits the matrix without any right on the file index itself."""
        if any(key in vals for key in FIRM_RULE_FIELDS):
            firm = {key: vals[key] for key in FIRM_RULE_FIELDS if key in vals}
            vals = {key: value for key, value in vals.items() if key not in FIRM_RULE_FIELDS}
            self._ea_save_firm_rule(firm)
            if not vals:
                return True
        result = self._ea_write_index(vals)
        if {"code", "phase"} & set(vals):
            self._ea_renumber()
        return result

    def _ea_write_index(self, vals):
        """A module update rewrites every column of every row of the index. An unchanged code or
        section must not recompute what is stored from it on the files: an archived file refuses
        that, and the update would fail on any firm with one (the database's archive lock)."""
        related = {"code", "section", "phase", "sequence"} & set(vals)
        if not related:
            return super().write(vals)
        for template in self:
            kept = {key: value for key, value in vals.items() if key not in related or template[key] != value}
            if kept:
                super(TaskTemplate, template).write(kept)
        return True

    @api.depends("code", "title")
    @api.depends_context("lang", "ea_task_with_title")
    def _compute_display_name(self):
        """The code alone, as everywhere else; with the task's description where
        the context asks for it (the sign-off policy screens)."""
        with_title = self.env.context.get("ea_task_with_title")
        for template in self:
            if with_title and template.title:
                template.display_name = "%s - %s" % (template.code, template.title)
            else:
                template.display_name = template.code or ""

    @api.model
    def _ladder_selection(self):
        return self.env["ea.audit.signoff.task.rule"]._fields["min_preparer"]._description_selection(self.env)

    @api.depends("code", "phase")
    def _compute_matrix_order(self):
        """Phase, then code: P1.2 before P1.10, which the index's own order is not."""
        phases = [key for key, _label in TASK_PHASE_SELECTION]
        for template in self:
            match = re.match(r"^([A-Z])(\d+)\.(\d+)$", template.code or "")
            letter, major, minor = (match[1], int(match[2]), int(match[3])) if match else ("Z", 99, 999)
            rank = phases.index(template.phase) if template.phase in phases else len(phases)
            template.matrix_order = rank * 10**7 + (ord(letter) - 65) * 10**5 + major * 10**3 + minor

    @api.depends("phase")
    def _compute_phase_step(self):
        steps = {key.split("_", 1)[1]: key for key, _label in PHASE_STEP_SELECTION}
        for template in self:
            template.phase_step = steps.get(template.phase, False)

    @api.model
    def _partner_required_selection(self):
        return self.env["ea.audit.signoff.task.rule"]._fields["partner_required"]._description_selection(self.env)

    def _compute_firm_rule(self):
        own = self.env["ea.audit.signoff.task.rule"]._ea_rules()
        word = {True: "yes", False: "no", None: "default"}
        for template in self:
            rule = own.get(template.code) or {}
            template.firm_min_preparer = rule.get("min_preparer") or False
            template.firm_min_reviewer = rule.get("min_reviewer") or False
            template.firm_partner_required = word[rule.get("partner_required")]

    def _inverse_firm_rule(self):
        # reached only by the superuser's own writes; everyone else goes through write() above
        for template in self:
            template._ea_save_firm_rule({key: template[key] for key in FIRM_RULE_FIELDS})

    def _ea_save_firm_rule(self, changes):
        """Each task's current rule with ``changes`` applied, saved as one call to save_task_rules."""
        Rule = self.env["ea.audit.signoff.task.rule"]
        own = Rule._ea_rules(self.mapped("code"))
        tri_state = {"yes": True, "no": False, "default": None, False: None, None: None}
        rules = []
        for template in self:
            rule = dict(own.get(template.code) or {"min_preparer": None, "min_reviewer": None, "partner_required": None})
            if "firm_min_preparer" in changes:
                rule["min_preparer"] = changes["firm_min_preparer"] or None
            if "firm_min_reviewer" in changes:
                rule["min_reviewer"] = changes["firm_min_reviewer"] or None
            if "firm_partner_required" in changes:
                if changes["firm_partner_required"] not in tri_state:
                    raise UserError(self.env._("Choose Firm default, Yes or No."))
                rule["partner_required"] = tri_state[changes["firm_partner_required"]]
            rules.append(dict(rule, code=template.code))
        Rule.save_task_rules(rules)
        self.invalidate_recordset([*FIRM_RULE_FIELDS, "matrix_min_preparer", "matrix_min_reviewer", "matrix_partner", "matrix_firm_rule"])

    def _compute_matrix(self):
        Policy = self.env["ea.audit.signoff.policy"]
        policy = Policy._ea_policy()
        own = self.env["ea.audit.signoff.task.rule"]._ea_rules()
        for template in self:
            rule = effective_task_rule(policy, own, template.code)
            template.matrix_min_preparer = rule["min_preparer"]
            template.matrix_min_reviewer = rule["min_reviewer"]
            template.matrix_partner = rule["partner_required"]
            template.matrix_firm_rule = template.code in own

    def action_matrix_export(self):
        """The firm's matrix, downloaded through a one-time attachment owned by the caller."""
        filename, content = self.env["ea.audit.signoff.task.rule"]._ea_matrix_workbook()
        attachment = self.env["ir.attachment"].create({
            "name": filename,
            "raw": content,
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }

    def action_matrix_import(self):
        return self.env["ir.actions.act_window"]._for_xml_id("ea_audit_core.action_signoff_matrix_import")
