import re

from odoo import api, fields, models

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


class TaskTemplate(models.Model):
    """The default audit file index (lib/file-index.ts), loaded as data. The
    numbering gaps are intentional: do not normalize them."""

    _name = "ea.audit.task.template"
    _description = "Audit file index entry"
    _order = "sequence, id"
    _rec_name = "code"

    code = fields.Char(required=True, index=True)
    section = fields.Selection(SECTION_SELECTION, required=True)
    title = fields.Char(required=True, translate=True)
    short_title = fields.Char(translate=True)
    tier = fields.Selection(TIER_SELECTION, required=True, default="standard")
    conditional = fields.Boolean(help="Instantiated, but only activated when a trigger answers yes.")
    phase = fields.Selection(TASK_PHASE_SELECTION, required=True)
    sequence = fields.Integer(default=10)

    # The firm's matrix (F002): what applies to this task today, the firm's own rules included.
    matrix_order = fields.Integer(compute="_compute_matrix_order", store=True, index=True)
    matrix_min_preparer = fields.Selection(selection="_ladder_selection", string="Minimum preparer", compute="_compute_matrix")
    matrix_min_reviewer = fields.Selection(selection="_ladder_selection", string="Minimum reviewer", compute="_compute_matrix")
    matrix_partner = fields.Boolean(string="Partner sign-off", compute="_compute_matrix")
    matrix_firm_rule = fields.Boolean(string="Firm's own rule", compute="_compute_matrix")

    _code_uniq = models.Constraint("UNIQUE(code)", "This task code already exists.")

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
