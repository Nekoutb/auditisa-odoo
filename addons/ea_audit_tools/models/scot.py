"""SCOT Studio (lib/scots.ts): the register, what can go wrong, the controls and their conclusions,
the walkthroughs, the close process and the S2.3 IT applications (lib/itgc.ts)."""
import re
import secrets

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.errors import rule_error as core_rule_error
from odoo.addons.ea_audit_core.services.signoff_rules import at_least, team_rank

from ..rules import rule_error
from ..services.assertions import ASSERTIONS
from ..services.cra_model import CR_DEFICIENT_BASIS
from ..services.engines import seeded_random
from ..services.itgc_model import IT_STRATEGIES, new_app_key
from ..services.scot_forms import FSCP_FIELDS, WALKTHROUGH_FIELDS
from ..services.toc_grid import toc_rows_planned, toc_rows_tested
from ..services.toc_sampling import (
    FREQUENCY_CODES, FREQUENCY_LABELS, OCCURRENCE_FREQUENCIES, draw_toc_sample, effective_frequency, frequency_code_from_text,
    frequency_label,
    seeded_rng, toc_evaluate, toc_suggested, toc_testing_started,
)
from .tool_record import french_date, is_french

TYPE_SELECTION = [("routine", "Routine"), ("non_routine", "Non-routine"), ("estimation", "Estimation")]
STRATEGY_SELECTION = [("controls", "Controls"), ("substantive", "Substantive")]
CONTROL_TYPE_SELECTION = [("manual", "Manual"), ("it_dependent", "IT-dependent manual"), ("automated", "Automated")]
FREQUENCY_SELECTION = [(code, FREQUENCY_LABELS[code][0]) for code in FREQUENCY_CODES]
RELIANCE_SELECTION = [("normal", "Normal"), ("heavy", "Heavy / significant risk")]
RESULT_SELECTION = [("effective", "Effective"), ("not_effective", "Not effective"), ("to_test", "To test")]
OBJECTIVE_SELECTION = [("prevent", "Prevent"), ("detect", "Detect")]
YES_NO = [("yes", "Yes"), ("no", "No")]
ITGC_STATE_SELECTION = [("support", "Support reliance"), ("not_support", "Do not support reliance"), ("mixed", "Mixed")]
IT_STRATEGY_SELECTION = [
    ("rely_itgc", "Rely on the IT processes: test the ITGCs"),
    ("test_direct", "Test the automated controls directly, each period"),
    ("substantive_only", "Fully substantive: no reliance on the IT controls"),
]
assert [key for key, _label in IT_STRATEGY_SELECTION] == IT_STRATEGIES

WALKTHROUGH_KEYS = [field["key"] for field in WALKTHROUGH_FIELDS]
_APP_SPLIT = re.compile(r"[,;·](?![^()]*\))")
_INDEX = re.compile(r"^[A-Z0-9]{1,4}$")


def _form_field(definition):
    """A question of the source's forms, as a field. yn and strategy answers are choices."""
    kind = definition.get("kind")
    if kind == "yn":
        return fields.Selection(YES_NO, string=definition["en"], help=definition["guideEn"])
    if kind == "strategy":
        return fields.Selection(STRATEGY_SELECTION, string=definition["en"], help=definition["guideEn"])
    return fields.Text(string=definition["en"], help=definition["guideEn"])


class Scot(models.Model):
    _name = "ea.audit.scot"
    _inherit = ["ea.audit.tool.record"]
    _description = "Significant class of transactions"
    _order = "create_date, id"

    name = fields.Char(required=True)
    description = fields.Text()
    transaction_type = fields.Selection(TYPE_SELECTION, default="routine", required=True)
    strategy = fields.Selection(STRATEGY_SELECTION, default="substantive", required=True)
    applications = fields.Char(string="IT applications")
    assignee_id = fields.Many2one("res.users", string="Assigned to", ondelete="set null")
    index_ids = fields.One2many("ea.audit.scot.index", "scot_id", string="Lead indexes")
    wcgw_ids = fields.One2many("ea.audit.wcgw", "scot_id", string="What can go wrong")
    control_ids = fields.One2many("ea.audit.scot.control", "scot_id", string="Controls")
    index_summary = fields.Char(string="Indexes", compute="_compute_summary", compute_sudo=True)
    wcgw_count = fields.Integer(string="WCGW", compute="_compute_summary", compute_sudo=True)
    control_count = fields.Integer(string="Controls", compute="_compute_summary", compute_sudo=True)
    selected_count = fields.Integer(string="Selected", compute="_compute_summary", compute_sudo=True)
    walkthrough_open = fields.Integer(string="Walkthrough answers missing", compute="_compute_summary", compute_sudo=True)

    for _definition in WALKTHROUGH_FIELDS:
        locals()[_definition["key"]] = _form_field(_definition)
    del _definition

    _engagement_name_uniq = models.Constraint("UNIQUE(engagement_id, name)", "A SCOT name is used once on a file.")

    @api.depends("index_ids.index_code", "wcgw_ids", "control_ids.selected_for_testing", *WALKTHROUGH_KEYS)
    def _compute_summary(self):
        for scot in self:
            scot.index_summary = ", ".join(scot.index_ids.mapped("index_code"))
            scot.wcgw_count = len(scot.wcgw_ids)
            scot.control_count = len(scot.control_ids)
            scot.selected_count = len(scot.control_ids.filtered("selected_for_testing"))
            scot.walkthrough_open = len([key for key in WALKTHROUGH_KEYS if not (scot[key] or "").strip()])

    def _ea_user_write(self, vals):
        """updateScot and saveWalkthrough. Each voids the signatures of the paper it reaches."""
        allowed = {"name", "description", "transaction_type", "strategy", "applications", *WALKTHROUGH_KEYS}
        self._ea_only(vals, allowed)
        for scot in self:
            scot._ea_guard()
            engagement = scot.sudo().engagement_id
            values = dict(vals)
            if "name" in values:
                name = (values["name"] or "").strip()
                if not name:
                    # coalesce(nullif(name, ''), name): an empty name keeps the old one
                    values.pop("name")
                else:
                    if self.sudo().search_count([("engagement_id", "=", engagement.id), ("name", "=", name), ("id", "!=", scot.id)]):
                        raise rule_error(self.env, "duplicate-name")
                    values["name"] = name
            for key in WALKTHROUGH_KEYS:
                if key in values and isinstance(values[key], str) and not values[key].strip():
                    values[key] = False
            scot.sudo().write(values)
            if set(vals) & set(WALKTHROUGH_KEYS):
                engagement._ea_invalidate_signoffs("S1.3")
            if set(vals) - set(WALKTHROUGH_KEYS):
                engagement._ea_invalidate_signoffs("S1.1")
        return True

    def _ea_user_unlink(self):
        """deleteScot: a senior or above. A SCOT takes its WCGWs and controls with it."""
        for scot in self:
            scot._ea_require_senior()
            engagement = scot.sudo().engagement_id
            scot.sudo().unlink()
            engagement._ea_invalidate_signoffs("S1.1")
            engagement._ea_invalidate_signoffs("S1.2")
        return True

    def assign(self, user):
        """assignScot. The assignee is told, and a failed notice never blocks the assignment."""
        self.ensure_one()
        self._ea_guard()
        as_root = self.sudo()
        as_root.assignee_id = user.id if user else False
        if user:
            as_root.engagement_id._ea_log("scot_assignment", "SCOT assigned to %s: %s" % (user.name, as_root.name))
        return True

    def link_index(self, index_code, assertions=()):
        """linkScotIndex: on conflict the assertions are replaced."""
        self.ensure_one()
        self._ea_guard()
        if not _INDEX.match(index_code or ""):
            raise rule_error(self.env, "invalid-index")
        as_root = self.sudo()
        codes = [code for code in assertions if code in ASSERTIONS]
        found = as_root.index_ids.filtered(lambda line: line.index_code == index_code)
        tags = self.env["ea.audit.assertion"]._ea_from_codes(codes)
        if found:
            found.write({"assertion_ids": [(6, 0, tags.ids)]})
        else:
            self.env["ea.audit.scot.index"].sudo().create({
                "engagement_id": as_root.engagement_id.id, "scot_id": as_root.id,
                "index_code": index_code, "assertion_ids": [(6, 0, tags.ids)],
            })
        as_root.engagement_id._ea_invalidate_signoffs("S1.1")
        return True

    def unlink_index(self, index_code):
        self.ensure_one()
        self._ea_require_senior()
        as_root = self.sudo()
        as_root.index_ids.filtered(lambda line: line.index_code == index_code).unlink()
        as_root.engagement_id._ea_invalidate_signoffs("S1.1")
        return True

    def add_wcgw(self, description, assertions):
        """addWcgw: a WCGW is a risk to an assertion; with none it feeds nothing in S3.1 (UAT B134)."""
        self.ensure_one()
        self._ea_guard()
        description = (description or "").strip()
        if not description:
            raise rule_error(self.env, "description-required")
        codes = [code for code in (assertions or ()) if code in ASSERTIONS]
        if not codes:
            raise rule_error(self.env, "assertion-required")
        as_root = self.sudo()
        last = max(as_root.wcgw_ids.mapped("sort") or [0])
        wcgw = self.env["ea.audit.wcgw"].sudo().create({
            "engagement_id": as_root.engagement_id.id, "scot_id": as_root.id, "description": description,
            "assertion_ids": [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes(codes).ids)], "sort": last + 10,
        })
        as_root.engagement_id._ea_invalidate_signoffs("S1.2")
        return wcgw.with_env(self.env)

    def add_control(self, name, owner=None, control_type=None, frequency=None, objective=None, wcgws=None,
                    reliance=None, occurrences=None, frequency_other=None):
        """addControl: an unknown type is manual, an unknown objective is prevent. A frequency of the
        fixed list is stored as its code; any other text stays as typed (read through the parser)."""
        self.ensure_one()
        self._ea_guard()
        name = (name or "").strip()
        if not name:
            raise rule_error(self.env, "name-required")
        as_root = self.sudo()
        wcgws = (wcgws or self.env["ea.audit.wcgw"]).sudo()
        if wcgws.engagement_id - as_root.engagement_id:
            raise rule_error(self.env, "not-found")
        control_type = control_type if control_type in dict(CONTROL_TYPE_SELECTION) else "manual"
        text = (frequency or "").strip()
        code = text if text in FREQUENCY_CODES else False
        occurrences = max(0, round(occurrences)) if occurrences else 0
        frequency_other = (frequency_other or "").strip()
        _check_frequency(self.env, control_type, code, frequency_other, occurrences)
        control = self.env["ea.audit.scot.control"].sudo().create({
            "engagement_id": as_root.engagement_id.id, "scot_id": as_root.id, "name": name,
            "owner": (owner or "").strip() or False,
            "control_type": control_type,
            "frequency": False if code else (text or False),
            "frequency_code": code,
            "frequency_other": frequency_other or False,
            "reliance": "heavy" if reliance == "heavy" else "normal",
            "toc_population": occurrences or False,
            "objective": "detect" if objective == "detect" else "prevent",
            "wcgw_ids": [(6, 0, wcgws.ids)],
        })
        as_root.engagement_id._ea_invalidate_signoffs("S1.2")
        return control.with_env(self.env)

    def _ea_require_senior(self):
        """requireRole("senior"), then the file's own guard."""
        self.ensure_one()
        self._ea_guard()
        if not at_least(self.env.user._ea_firm_role(), "senior"):
            raise core_rule_error(self.env, "forbidden")

    def action_list_new_scot(self):
        return self._ea_context_engagement().action_open_scot_wizard()

    def action_list_export_scots(self):
        return self._ea_context_engagement()._ea_export_action("scots")

    def action_open_control_wizard(self):
        return _wizard(self, "ea.audit.control.wizard", self.env._("Add a control"), {"default_scot_id": self.id})

    def action_open_wcgw_wizard(self):
        return _wizard(self, "ea.audit.wcgw.wizard", self.env._("Add what can go wrong"), {"default_scot_id": self.id})

    def action_open_assign(self):
        return _wizard(self, "ea.audit.scot.assign.wizard", self.env._("Assign the SCOT"), {"default_scot_id": self.id, "default_user_id": self.sudo().assignee_id.id})

    def action_open_index_wizard(self):
        return _wizard(self, "ea.audit.scot.index.wizard", self.env._("Link a lead index"), {"default_scot_id": self.id})


def _check_frequency(env, control_type, code, other_reason, occurrences):
    """The fixed list's rules: "other" says why; daily, many-times-daily and event-driven say how
    many times in the year. An automated control is tested once, whatever its frequency."""
    if control_type == "automated":
        return
    if code == "other" and len((other_reason or "").strip()) < 3:
        raise rule_error(env, "frequency-reason-required")
    if code in OCCURRENCE_FREQUENCIES and not occurrences:
        raise rule_error(env, "occurrences-required")


def _wizard(record, model, name, context):
    record.ensure_one()
    return {"type": "ir.actions.act_window", "name": name, "res_model": model, "view_mode": "form", "target": "new", "context": context}


class ScotIndex(models.Model):
    _name = "ea.audit.scot.index"
    _inherit = ["ea.audit.tool.record"]
    _description = "Lead index of a SCOT"
    _order = "index_code"
    _rec_name = "index_code"

    scot_id = fields.Many2one("ea.audit.scot", required=True, ondelete="cascade", index=True)
    index_code = fields.Char(string="Lead index", required=True, index=True)
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")

    _uniq = models.Constraint("UNIQUE(scot_id, index_code)", "A SCOT links an index once.")

    def action_unlink_index(self):
        for line in self:
            line.sudo().scot_id.with_env(self.env).unlink_index(line.sudo().index_code)
        return {"type": "ir.actions.client", "tag": "soft_reload"}


class Wcgw(models.Model):
    _name = "ea.audit.wcgw"
    _inherit = ["ea.audit.tool.record"]
    _description = "What can go wrong"
    _order = "sort, create_date"
    _rec_name = "description"

    scot_id = fields.Many2one("ea.audit.scot", required=True, ondelete="cascade", index=True)
    description = fields.Char(required=True)
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")
    sort = fields.Integer(default=10)
    control_ids = fields.Many2many(
        "ea.audit.scot.control", "ea_audit_wcgw_control_rel", "wcgw_id", "control_id", string="Controls",
    )
    answered = fields.Boolean(compute="_compute_answered", compute_sudo=True)

    @api.depends("control_ids")
    def _compute_answered(self):
        for wcgw in self:
            wcgw.answered = bool(wcgw.control_ids)

    def _ea_user_unlink(self):
        """deleteWcgw: controls left answering nothing leave the selection (UAT B45)."""
        for wcgw in self:
            wcgw.sudo().scot_id.with_env(self.env)._ea_require_senior()
            as_root = wcgw.sudo()
            engagement, controls = as_root.engagement_id, as_root.control_ids
            as_root.unlink()
            _after_unlink(engagement, controls)
        return True

    def toggle_control(self, control, linked):
        """toggleWcgwControl."""
        self.ensure_one()
        self.sudo().scot_id.with_env(self.env)._ea_require_senior()
        as_root = self.sudo()
        control = control.sudo()
        if control.engagement_id != as_root.engagement_id:
            raise rule_error(self.env, "not-found")
        if linked:
            as_root.control_ids = [(4, control.id)]
            as_root.engagement_id._ea_invalidate_signoffs("S1.2")
        else:
            as_root.control_ids = [(3, control.id)]
            _after_unlink(as_root.engagement_id, control)
        return True


def _after_unlink(engagement, controls):
    orphaned = controls.exists().filtered(lambda c: c.selected_for_testing and not c.wcgw_ids)
    if orphaned:
        orphaned.write({"selected_for_testing": False})
    for code in ("S1.2", "S2.1", "S2.2", "E1.2") if orphaned else ("S1.2",):
        engagement._ea_invalidate_signoffs(code)


class ScotControl(models.Model):
    _name = "ea.audit.scot.control"
    _inherit = ["ea.audit.tool.record"]
    _description = "Control"
    _order = "create_date, id"

    scot_id = fields.Many2one("ea.audit.scot", string="SCOT", required=True, ondelete="cascade", index=True)
    name = fields.Char(required=True)
    owner = fields.Char()
    control_type = fields.Selection(CONTROL_TYPE_SELECTION, default="manual", required=True)
    # The free text of the controls recorded before the fixed list (2026-11-16). Never rewritten:
    # an archived file keeps it as it was; the list reads it through the keyword parser.
    frequency = fields.Char(string="Frequency as first typed")
    frequency_code = fields.Selection(FREQUENCY_SELECTION, string="Frequency")
    frequency_other = fields.Char(string="Why another frequency")
    reliance = fields.Selection(RELIANCE_SELECTION, string="Reliance", default="normal",
                                help="Heavy: the audit relies heavily on this control, or it answers a significant risk.")
    frozen_size = fields.Integer(string="Size frozen at the first result", readonly=True, copy=False)
    frequency_effective = fields.Selection(FREQUENCY_SELECTION, string="Frequency (read)", compute="_compute_frequency_read")
    frequency_display = fields.Char(string="Frequency shown", compute="_compute_frequency_read")
    code = fields.Char(string="Code", compute="_compute_code")
    result_state = fields.Selection(RESULT_SELECTION, string="Result", compute="_compute_code")
    objective = fields.Selection(OBJECTIVE_SELECTION, default="prevent", required=True)
    selected_for_testing = fields.Boolean()
    test_design = fields.Text()
    design_eval = fields.Selection([("effective", "Effective"), ("ineffective", "Ineffective")], string="Design")
    implemented = fields.Selection(YES_NO)
    operating_notes = fields.Text()
    sample_size = fields.Integer()
    sample_note = fields.Char()
    operating_eval = fields.Selection([("effective", "Effective"), ("not_effective", "Not effective")], string="Operating conclusion")
    toc_population = fields.Integer(string="Population", help="Occurrences of the control in the period.")
    toc_sample_items = fields.Json()
    toc_sample_drawn_at = fields.Datetime(string="Drawn on")
    toc_grid = fields.Json()
    wcgw_ids = fields.Many2many("ea.audit.wcgw", "ea_audit_wcgw_control_rel", "control_id", "wcgw_id", string="What it answers")
    draw_ids = fields.One2many("ea.audit.toc.draw", "control_id", string="Draws")
    items_label = fields.Char(string="Occurrences to test", compute="_compute_sampling", compute_sudo=True)
    assertion_summary = fields.Char(string="Assertions", compute="_compute_sampling", compute_sudo=True)
    sole_control = fields.Boolean(string="Only control on an assertion", compute="_compute_sampling", compute_sudo=True)
    suggested_size = fields.Integer(string="Minimum sample", compute="_compute_sampling", compute_sudo=True)
    suggested_rule = fields.Char(string="Rule", compute="_compute_sampling", compute_sudo=True)
    testing_started = fields.Boolean(compute="_compute_sampling", compute_sudo=True)
    rows_tested = fields.Integer(string="Tested", compute="_compute_sampling", compute_sudo=True)
    deviations = fields.Integer(compute="_compute_sampling", compute_sudo=True)
    toc_evaluation = fields.Selection(
        [("high", "High assurance"), ("moderate", "Moderate assurance"), ("rely", "Reliance supported"), ("extend", "Extend the test to 60"), ("none", "No reliance")],
        string="Evaluation of the deviations", compute="_compute_sampling", compute_sudo=True,
    )

    @api.depends("frequency", "frequency_code", "control_type", "toc_population")
    @api.depends_context("lang")
    def _compute_frequency_read(self):
        fr = is_french(self.env)
        for control in self:
            code = effective_frequency(control.frequency_code, control.frequency)
            control.frequency_effective = code or False
            if control.control_type == "automated":
                control.frequency_display = self.env._("Automated: test of one")
            elif not code:
                control.frequency_display = self.env._("Please choose")
            elif code in OCCURRENCE_FREQUENCIES and control.toc_population:
                control.frequency_display = "%s · %d" % (frequency_label(code, fr), control.toc_population)
            else:
                control.frequency_display = frequency_label(code, fr)

    @api.depends("scot_id.control_ids", "selected_for_testing", "operating_eval")
    def _compute_code(self):
        for control in self:
            ids = control.scot_id.control_ids.ids
            control.code = "C%d" % (ids.index(control.id) + 1) if control.id in ids else "C"
            if control.operating_eval:
                control.result_state = control.operating_eval
            else:
                control.result_state = "to_test" if control.selected_for_testing else False

    @api.depends("toc_sample_items", "toc_population", "wcgw_ids", "selected_for_testing", "frequency", "frequency_code",
                 "reliance", "frozen_size", "control_type", "toc_grid")
    @api.depends_context("lang")
    def _compute_sampling(self):
        fr = is_french(self.env)
        counts = {}
        for engagement in self.engagement_id:
            counts[engagement.id] = engagement._ea_selected_assertion_counts()
        for control in self:
            covered = control._ea_assertions()
            sole = bool(control.selected_for_testing) and any(
                counts.get(control.engagement_id.id, {}).get(code, 0) == 1 for code in covered
            )
            frequency = effective_frequency(control.frequency_code, control.frequency)
            suggestion = toc_suggested(control.control_type, frequency, control.toc_population or None, sole, fr, control.reliance or "normal")
            # Once results are recorded the size stays as it was (owner's ruling of 2026-11-16); a
            # control tested before the ruling keeps its drawn size.
            frozen = control.frozen_size or (control.sample_size if toc_testing_started(control.toc_grid) else 0)
            if frozen:
                suggestion = {"size": frozen, "rule": (
                    "Figé à %d dès le premier résultat" if fr else "Frozen at %d once results were recorded"
                ) % frozen}
            control.items_label = ", ".join(str(item) for item in control.toc_sample_items or [])
            control.assertion_summary = ", ".join(covered)
            control.sole_control = sole
            control.suggested_size = suggestion["size"] if suggestion and "size" in suggestion else 0
            control.suggested_rule = suggestion["rule"] if suggestion and "rule" in suggestion else False
            control.testing_started = bool(toc_testing_started(control.toc_grid))
            control.rows_tested = toc_rows_tested(control.toc_grid)
            rows = (control.toc_grid or {}).get("rows") or []
            control.deviations = len([row for row in rows if "fail" in (row.get("results") or {}).values()])
            control.toc_evaluation = (
                toc_evaluate(control.sample_size, control.rows_tested, control.deviations) if control.sample_size and control.rows_tested else False
            )

    def _ea_assertions(self):
        codes = set(self.sudo().wcgw_ids.assertion_ids.mapped("code"))
        return [code for code in ASSERTIONS if code in codes]

    def _ea_user_write(self, vals):
        """updateControl: the screen's fields. The conclusion's consequences are in update_control."""
        self._ea_only(vals, {
            "selected_for_testing", "test_design", "design_eval", "implemented", "operating_notes",
            "sample_note", "operating_eval", "toc_population", "name", "owner", "frequency", "control_type", "objective",
            "frequency_code", "frequency_other", "reliance",
        })
        for control in self:
            control.update_control(vals)
        return True

    def _ea_user_unlink(self):
        """deleteControl."""
        for control in self:
            control.sudo().scot_id.with_env(self.env)._ea_require_senior()
            engagement = control.sudo().engagement_id
            control.sudo().unlink()
            for code in ("S1.2", "S2.1", "S2.2", "E1.2"):
                engagement._ea_invalidate_signoffs(code)
        return True

    def update_control(self, patch):
        """updateControl. The whole call rolls back on a refusal, as the source's transaction does."""
        self.ensure_one()
        self._ea_guard()
        as_root = self.sudo()
        engagement = as_root.engagement_id
        if patch.get("selected_for_testing") and not as_root.wcgw_ids:
            raise rule_error(self.env, "control-without-wcgw")  # UAT B46
        values = {key: patch[key] for key in (
            "selected_for_testing", "test_design", "design_eval", "implemented", "operating_notes", "sample_note",
            "operating_eval", "name", "owner", "frequency", "control_type", "objective",
            "frequency_code", "frequency_other", "reliance",
        ) if key in patch}
        if values.get("frequency_code") and values["frequency_code"] not in FREQUENCY_CODES:
            raise rule_error(self.env, "invalid-value")
        if "reliance" in values and values["reliance"] not in ("normal", "heavy"):
            raise rule_error(self.env, "invalid-value")
        if patch.get("sample_size") not in (None, False):
            values["sample_size"] = max(1, round(patch["sample_size"]))
        if patch.get("toc_population") not in (None, False):
            values["toc_population"] = max(0, round(patch["toc_population"]))
        if patch.get("toc_grid"):
            values["toc_grid"] = patch["toc_grid"]
        if {"frequency_code", "frequency_other", "control_type", "toc_population"} & set(values):
            after = {key: values.get(key, as_root[key]) for key in ("control_type", "frequency_code", "frequency_other", "toc_population")}
            _check_frequency(self.env, after["control_type"], after["frequency_code"], after["frequency_other"], after["toc_population"])
        as_root.write(values)
        if toc_testing_started(as_root.toc_grid):
            as_root._ea_freeze_size()
        conclusion = patch.get("operating_eval")
        if conclusion == "effective":
            # A conclusion on evidence: the planned sample tested, every attribute answered (UAT B84, B15).
            tested, planned = toc_rows_tested(as_root.toc_grid), toc_rows_planned(as_root.sample_size or None)
            if planned == 0 or tested == 0:
                raise rule_error(self.env, "toc-no-sample")
            if tested < planned:
                raise rule_error(self.env, "toc-incomplete")
            as_root._ea_lift_not_rely()
        elif conclusion == "not_effective":
            as_root._ea_stamp_not_rely()
        codes = []
        if "selected_for_testing" in patch:
            codes.append("S2.1")
        if {"test_design", "design_eval", "implemented", "sample_size", "sample_note", "frequency_code", "reliance"} & set(patch):
            codes.append("S2.2")
        if {"operating_notes", "operating_eval", "toc_population", "toc_grid"} & set(patch):
            codes.append("E1.2")
        for code in codes:
            engagement._ea_invalidate_signoffs(code)
        return True

    def _ea_answered_cells(self):
        """(index, assertion) pairs this control answers, on every index its SCOT feeds."""
        pairs = []
        for line in self.scot_id.index_ids:
            for code in self._ea_assertions():
                pairs.append((line.index_code, code))
        return pairs

    def _ea_stamp_not_rely(self):
        """A control concluded not effective cannot be relied on: S3.1 follows, on the same save,
        and what it replaces stays on the revision trail with E1.2's conclusion as the reason (UAT B136)."""
        engagement = self.engagement_id
        for index_code, assertion in self._ea_answered_cells():
            cell = engagement._ea_cra_cell(index_code, assertion)
            if cell.cr != "not_rely" and (cell.ir or cell.cr):
                self.env["ea.audit.cra.history"].create({
                    "engagement_id": engagement.id, "assessment_id": cell.id, "index_code": index_code, "assertion": assertion,
                    "ir": cell.ir, "ir_basis": cell.ir_basis, "cr": cell.cr, "cr_basis": cell.cr_basis,
                    "new_ir": cell.ir, "new_cr": "not_rely", "reason": CR_DEFICIENT_BASIS, "changed_by_id": self.env.user.id,
                })
            basis = cell.cr_basis or ""
            if "E1.2" not in basis:
                basis = "%s · %s" % (basis, CR_DEFICIENT_BASIS) if basis else CR_DEFICIENT_BASIS
            cell.write({"recorded": True, "relevant": True, "relevant_defaulted": False, "cr": "not_rely", "cr_basis": basis})

    def _ea_lift_not_rely(self):
        """The same in reverse: only E1.2's stamp is lifted, and only when no other control answering
        the pair is still concluded not effective. A not-rely reached on other grounds stands."""
        engagement = self.engagement_id
        others = self.search([
            ("engagement_id", "=", engagement.id), ("operating_eval", "=", "not_effective"), ("id", "!=", self.id),
        ])
        still_failing = set()
        for other in others:
            still_failing.update(other._ea_answered_cells())
        suffix = " · " + CR_DEFICIENT_BASIS
        for pair in self._ea_answered_cells():
            if pair in still_failing:
                continue
            cell = self.env["ea.audit.cra.assessment"].search([
                ("engagement_id", "=", engagement.id), ("index_code", "=", pair[0]), ("assertion", "=", pair[1]), ("cr", "=", "not_rely"),
            ], limit=1)
            basis = cell.cr_basis or ""
            if not cell or CR_DEFICIENT_BASIS not in basis:
                continue
            if basis == CR_DEFICIENT_BASIS:
                cell.write({"cr": False, "cr_basis": False})
            elif basis.endswith(suffix):
                cell.write({"cr_basis": basis[: -len(suffix)]})

    @api.model
    def _ea_backfill_frequency_codes(self):
        """One-off (2026-11-16): the code of the fixed list for the free text of OPEN files' controls,
        where the keyword parser reads it without doubt. Archived files are left untouched (the archive
        trigger refuses their rows), and so is anything unclear. Returns how many controls got a code."""
        self.env.flush_all()
        cr = self.env.cr
        cr.execute("""
            SELECT c.id, c.frequency
              FROM ea_audit_scot_control c
              JOIN ea_audit_engagement e ON e.id = c.engagement_id
             WHERE e.archived_at IS NULL AND COALESCE(e.phase, '') != 'archived'
               AND c.frequency_code IS NULL AND COALESCE(c.frequency, '') != ''
        """)
        by_code = {}
        for control_id, text in cr.fetchall():
            code = frequency_code_from_text(text)
            if code:
                by_code.setdefault(code, []).append(control_id)
        for code, ids in by_code.items():
            cr.execute("UPDATE ea_audit_scot_control SET frequency_code = %s WHERE id = ANY(%s) AND frequency_code IS NULL", [code, ids])
        self.invalidate_model(["frequency_code"])
        return sum(len(ids) for ids in by_code.values())

    def _ea_suggested_for(self, population):
        """The suggested size for a draw over ``population``: the frozen size once results exist."""
        self.ensure_one()
        control = self.sudo()
        frozen = control.frozen_size or (control.sample_size if toc_testing_started(control.toc_grid) else 0)
        if frozen:
            return frozen
        found = toc_suggested(
            control.control_type, effective_frequency(control.frequency_code, control.frequency), population or None,
            control.sole_control, False, control.reliance or "normal",
        )
        return found.get("size", 0) if found else 0

    def _ea_freeze_size(self):
        """The size in force when the first result is recorded: the drawn size, else the table's.
        It no longer follows the table or the frequency afterwards."""
        for control in self.sudo():
            if not control.frozen_size:
                size = control.sample_size or control.suggested_size
                if size:
                    control.frozen_size = size

    def draw_toc_sample(self, population, sample_size, rule=None, reason=None, below_reason=None):
        """drawTocSampleForControl (F061): the server draws from a stored seed and keeps every draw.
        The first draw needs no reason; a redraw does, and once testing started a manager's rank.
        A size below the suggested one needs its own written reason (owner's ruling of 2026-11-16)."""
        self.ensure_one()
        self._ea_guard()
        try:
            population, size = int(population), int(sample_size)
        except (TypeError, ValueError):
            raise rule_error(self.env, "toc-population-required") from None
        if population < 1:
            raise rule_error(self.env, "toc-population-required")
        if size < 1:
            raise rule_error(self.env, "toc-size-invalid")
        reason = (reason or "").strip()
        below_reason = (below_reason or "").strip()
        self.env.cr.execute("SELECT id FROM ea_audit_scot_control WHERE id = %s FOR UPDATE", [self.id])
        as_root = self.sudo()
        suggested = as_root._ea_suggested_for(population)
        below = bool(suggested) and size < suggested
        if below and len(below_reason) < 3:
            raise rule_error(self.env, "below-suggestion-reason-required")
        if below:
            rule = "%s · %s" % (rule, below_reason) if rule else below_reason
        engagement = as_root.engagement_id
        Draw = self.env["ea.audit.toc.draw"].sudo()
        draw_no = Draw.search_count([("control_id", "=", self.id)]) + 1
        if draw_no > 1:
            if len(reason) < 3:
                raise rule_error(self.env, "redraw-reason-required")
            if toc_testing_started(as_root.toc_grid):
                member = engagement._ea_member(self.env.user)
                role = member.team_role if member.state == "accepted" else None
                if team_rank(role) < team_rank("manager"):
                    raise rule_error(self.env, "redraw-after-testing-manager-only")
        seed = secrets.token_hex(16)
        items = draw_toc_sample(population, size, seeded_rng(seed, seeded_random))
        draw = Draw.create({
            "engagement_id": engagement.id, "control_id": self.id, "draw_no": draw_no, "seed": seed, "population": population,
            "sample_size": size, "items": items, "rule": rule or False, "reason": reason or False, "drawn_by_id": self.env.user.id,
        })
        values = {"toc_population": population, "sample_size": size, "toc_sample_items": items, "toc_sample_drawn_at": fields.Datetime.now()}
        if rule:
            values["sample_note"] = rule
        as_root.write(values)
        engagement._ea_log(
            "toc_sample_drawn" if draw_no == 1 else "toc_sample_redrawn",
            "Test-of-controls sample drawn: %d of %d" % (len(items), population) if draw_no == 1 else
            "Test-of-controls sample redrawn (draw %d): %d of %d — %s" % (draw_no, len(items), population, reason),
        )
        engagement._ea_invalidate_signoffs("S2.2")
        engagement._ea_invalidate_signoffs("E1.2")
        return draw.with_env(self.env)

    def action_open_full(self):
        """The control's own page, where its selection, design, draw and tests are worked. A row of the
        SCOT's list only opens a read-only dialog."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "current",
            "views": [(self.env.ref("ea_audit_tools.view_control_form").id, "form")],
            "context": {"ea_engagement_id": self.sudo().engagement_id.id},
        }

    def action_open_draw(self):
        self.ensure_one()
        return _wizard(self, "ea.audit.toc.draw.wizard", self.env._("Draw the sample"), {"default_control_id": self.id})

    def action_open_link(self):
        self.ensure_one()
        return _wizard(self, "ea.audit.control.link.wizard", self.env._("What it answers"), {
            "default_control_id": self.id, "default_wcgw_ids": [(6, 0, self.sudo().wcgw_ids.ids)],
        })

    def action_open_grid_import(self):
        self.ensure_one()
        return _wizard(self, "ea.audit.toc.grid.wizard", self.env._("Import the test grid"), {"default_control_id": self.id})


class TocDraw(models.Model):
    """toc_sample_draw: append-only. The items can be reproduced from the seed."""

    _name = "ea.audit.toc.draw"
    _inherit = ["ea.audit.tool.record"]
    _description = "Test-of-controls sample draw"
    _order = "control_id, draw_no desc"
    _rec_name = "draw_no"

    control_id = fields.Many2one("ea.audit.scot.control", required=True, ondelete="cascade", index=True)
    draw_no = fields.Integer(string="Draw", required=True)
    seed = fields.Char(required=True)
    population = fields.Integer(required=True)
    sample_size = fields.Integer(required=True)
    items = fields.Json(required=True)
    items_label = fields.Char(string="Occurrences", compute="_compute_items_label")
    rule = fields.Char()
    reason = fields.Char()
    drawn_by_id = fields.Many2one("res.users", string="Drawn by", ondelete="restrict")

    _draw_uniq = models.Constraint("UNIQUE(control_id, draw_no)", "A draw number is used once on a control.")

    @api.depends("items")
    def _compute_items_label(self):
        for draw in self:
            draw.items_label = ", ".join(str(item) for item in draw.items or [])


class Fscp(models.Model):
    """S1.4: the financial statement close process is one process per engagement."""

    _name = "ea.audit.fscp"
    _inherit = ["ea.audit.tool.record"]
    _description = "Financial statement close process"
    _rec_name = "engagement_id"

    for _definition in FSCP_FIELDS:
        locals()[_definition["key"]] = _form_field(_definition)
    del _definition

    _engagement_uniq = models.Constraint("UNIQUE(engagement_id)", "An engagement has one close process.")

    def _ea_user_write(self, vals):
        self._ea_only(vals, {field["key"] for field in FSCP_FIELDS})
        for record in self:
            record._ea_guard()
            record.sudo().write(vals)
            record.sudo().engagement_id._ea_invalidate_signoffs("S1.4")
        return True


class ItApplication(models.Model):
    """S2.3: the relevant IT applications and the strategy decided for each; S2.5 evaluates against
    the same record. Removing a register application is remembered, so it does not come back."""

    _name = "ea.audit.it.application"
    _inherit = ["ea.audit.tool.record"]
    _description = "IT application"
    _order = "name"

    key = fields.Char(required=True, readonly=True)
    name = fields.Char(required=True)
    layers = fields.Char(string="Layers (application, database, operating system)")
    strategy = fields.Selection(IT_STRATEGY_SELECTION)
    itgc_note = fields.Text(string="ITGC note")
    scot_names = fields.Char(string="SCOTs", readonly=True)
    removed = fields.Boolean(readonly=True)

    _key_uniq = models.Constraint("UNIQUE(engagement_id, key)", "An application key is used once on a file.")

    def _ea_user_write(self, vals):
        self._ea_only(vals, {"name", "layers", "strategy", "itgc_note"})
        if vals.get("strategy") and vals["strategy"] not in IT_STRATEGIES:
            raise rule_error(self.env, "invalid-strategy")
        for app in self:
            app._ea_guard()
            app.sudo().write(vals)
            engagement = app.sudo().engagement_id
            engagement._ea_invalidate_signoffs("S2.3")
            engagement._ea_invalidate_signoffs("S2.5")
        return True

    def action_remove(self):
        for app in self:
            app._ea_guard()
            app.sudo().write({"removed": True})
            engagement = app.sudo().engagement_id
            engagement._ea_invalidate_signoffs("S2.3")
            engagement._ea_invalidate_signoffs("S2.5")
        return {"type": "ir.actions.client", "tag": "soft_reload"}


class EngagementScot(models.Model):
    _inherit = "ea.audit.engagement"

    itgc_state = fields.Selection(ITGC_STATE_SELECTION, string="ITGC conclusion (S2.5)", copy=False)
    scot_ids = fields.One2many("ea.audit.scot", "engagement_id", string="SCOTs")
    it_application_ids = fields.One2many("ea.audit.it.application", "engagement_id", string="IT applications")
    scot_coverage_text = fields.Text(string="Coverage", compute="_compute_scot_coverage", compute_sudo=True)
    scot_uncovered_label = fields.Char(string="Significant accounts without a SCOT", compute="_compute_scot_coverage", compute_sudo=True)
    scot_unanswered_count = fields.Integer(string="WCGWs without a control", compute="_compute_scot_coverage", compute_sudo=True)
    scot_para33_count = fields.Integer(string="ISA 315 ¶33 warnings", compute="_compute_scot_coverage", compute_sudo=True)

    def _compute_scot_coverage(self):
        for engagement in self:
            view = engagement._ea_scot_studio()
            engagement.scot_uncovered_label = ", ".join(view["uncoveredIndexes"]) or "—"
            engagement.scot_unanswered_count = view["unansweredWcgws"]
            engagement.scot_para33_count = len(view["para33Violations"])
            engagement.scot_coverage_text = "\n".join(
                "%s: %s" % (row["indexCode"], row["riskDescription"]) for row in view["para33Violations"]
            )

    # ------------------------------------------------------------------
    # Reading (scotStudio, and the hooks milestone 1 left open)
    # ------------------------------------------------------------------

    def _ea_scot_studio(self):
        """Coverage strips. A ¶33 line is a rendered warning, never a constraint: an abandoned
        reliance legitimately creates a transient one the auditor must resolve."""
        self.ensure_one()
        as_root = self.sudo()
        scots = as_root.scot_ids
        covered = set(scots.index_ids.mapped("index_code"))
        selected_by_index = set()
        for scot in scots:
            if scot.control_ids.filtered("selected_for_testing"):
                selected_by_index.update(scot.index_ids.mapped("index_code"))
        significant = [row["index"] for row in self._ea_significance_rows() if row.get("status") == "significant"]
        para33 = []
        risks = self.env["ea.audit.risk"].sudo().search([
            ("engagement_id", "=", self.id), ("substantive_alone_insufficient", "=", True), ("rebutted", "=", False),
        ])
        for risk in risks:
            for code in sorted(set(risk.index_link_ids.mapped("index_code"))):
                if code not in selected_by_index:
                    para33.append({"indexCode": code, "riskDescription": risk.description})
        return {
            "uncoveredIndexes": [code for code in significant if code not in covered],
            "unansweredWcgws": len(scots.wcgw_ids.filtered(lambda w: not w.control_ids)),
            "para33Violations": para33,
        }

    def _ea_control_coverage(self, index_code, assertion):
        """Selected controls answering a WCGW with this assertion on a SCOT feeding this index. The E1.2
        conclusion is what the board reads; the raw test outcome stands in until E1.2 concludes (cra.ts)."""
        self.ensure_one()
        scots = self.env["ea.audit.scot"].sudo().search([
            ("engagement_id", "=", self.id), ("index_ids.index_code", "=", index_code),
        ])
        out = {"covering": 0, "effective": 0, "failed": 0}
        for control in scots.control_ids.filtered("selected_for_testing"):
            if assertion not in control._ea_assertions():
                continue
            out["covering"] += 1
            concluded = control._ea_concluded()
            if control.design_eval == "ineffective" or concluded == "not_effective":
                out["failed"] += 1
            elif concluded == "effective":
                out["effective"] += 1
        return out

    def _ea_itgc_state(self):
        """The S2.5 conclusion. A paper can set it through save_itgc_conclusion."""
        self.ensure_one()
        return self.sudo().itgc_state or None

    def _ea_selected_assertion_counts(self):
        self.ensure_one()
        counts = {}
        controls = self.env["ea.audit.scot.control"].sudo().search([
            ("engagement_id", "=", self.id), ("selected_for_testing", "=", True),
        ])
        for control in controls:
            for code in control._ea_assertions():
                counts[code] = counts.get(code, 0) + 1
        return counts

    def _ea_cra_cell(self, index_code, assertion):
        """A cell of S3.1, created with its row for an index the board does not list yet."""
        self.ensure_one()
        Cell = self.env["ea.audit.cra.assessment"].sudo()
        cell = Cell.search([("engagement_id", "=", self.id), ("index_code", "=", index_code), ("assertion", "=", assertion)], limit=1)
        if cell:
            return cell
        Row = self.env["ea.audit.cra.row"].sudo()
        row = Row.search([("engagement_id", "=", self.id), ("index_code", "=", index_code)], limit=1) or Row.create({
            "engagement_id": self.id, "index_code": index_code,
        })
        return Cell.create({
            "engagement_id": self.id, "row_id": row.id, "index_code": index_code, "assertion": assertion,
            "sequence": ASSERTIONS.index(assertion) if assertion in ASSERTIONS else 10,
        })

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def create_scot(self, name, transaction_type="routine", strategy="substantive", applications=None, description=None):
        """createScot: unknown types fall back as the source's do."""
        self.ensure_one()
        self._ea_tool_guard()
        name = (name or "").strip()
        if not name:
            raise rule_error(self.env, "name-required")
        Scot = self.env["ea.audit.scot"].sudo()
        if Scot.search_count([("engagement_id", "=", self.id), ("name", "=", name)]):
            raise rule_error(self.env, "duplicate-name")
        scot = Scot.create({
            "engagement_id": self.id, "name": name,
            "transaction_type": transaction_type if transaction_type in dict(TYPE_SELECTION) else "routine",
            "strategy": strategy if strategy in dict(STRATEGY_SELECTION) else "substantive",
            "applications": (applications or "").strip() or False, "description": (description or "").strip() or False,
        })
        self._ea_sync_it_applications()
        self._ea_invalidate_signoffs("S1.1")
        return scot.with_env(self.env)

    def _ea_sync_it_applications(self):
        """itAppsView's seeding: separators split only outside parentheses, a removed application stays
        removed, and SCOT names are attached. Runs as superuser on reads and writes alike."""
        self.ensure_one()
        as_root = self.sudo()
        named = {}
        for scot in as_root.scot_ids:
            for raw in _APP_SPLIT.split(scot.applications or ""):
                name = raw.strip()
                if name and scot.name not in named.setdefault(name, []):
                    named[name].append(scot.name)
        Application = self.env["ea.audit.it.application"].sudo()
        existing = {app.key: app for app in Application.search([("engagement_id", "=", self.id)])}
        keys = {}
        for name, scot_names in named.items():
            key = new_app_key(name)
            keys[key] = ", ".join(scot_names)
            if key not in existing:
                existing[key] = Application.create({"engagement_id": self.id, "key": key, "name": name})
        for key, app in existing.items():
            names = keys.get(key, False)
            if app.scot_names != names:
                app.write({"scot_names": names})

    def save_it_application(self, key, patch):
        """saveItApp: an unknown key is created."""
        self.ensure_one()
        self._ea_tool_guard()
        if not re.fullmatch(r"[a-z0-9-]{1,40}", key or ""):
            raise rule_error(self.env, "invalid-key")
        if patch.get("strategy") and patch["strategy"] not in IT_STRATEGIES:
            raise rule_error(self.env, "invalid-strategy")
        Application = self.env["ea.audit.it.application"].sudo()
        app = Application.search([("engagement_id", "=", self.id), ("key", "=", key)], limit=1)
        values = {name: patch[name] for name in ("name", "layers", "strategy", "itgc_note", "removed") if name in patch}
        if app:
            app.write(values)
        else:
            app = Application.create({"engagement_id": self.id, "key": key, "name": patch.get("name") or key, **values})
        self._ea_invalidate_signoffs("S2.3")
        self._ea_invalidate_signoffs("S2.5")
        return app.with_env(self.env)

    def save_itgc_conclusion(self, state):
        """The S2.5 conclusion that feeds the CRA."""
        self.ensure_one()
        self._ea_tool_guard()
        if state and state not in dict(ITGC_STATE_SELECTION):
            raise rule_error(self.env, "invalid-value")
        self.sudo().itgc_state = state or False
        self._ea_invalidate_signoffs("S2.5")
        self._ea_log("itgc_concluded", "S2.5 ITGC conclusion: %s" % (state or "—"))
        return True

    # ------------------------------------------------------------------
    # Screens
    # ------------------------------------------------------------------

    def action_tool_scot(self):
        return self._ea_list(
            "ea.audit.scot", self.env._("SCOTs and controls"),
            [("ea_audit_tools.view_scot_kanban", "kanban"), ("ea_audit_tools.view_scot_list", "list"), ("ea_audit_tools.view_scot_form", "form")],
            {"context": {"ea_engagement_id": self.id, "create": False}},
        )

    def action_open_scot_wizard(self):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.act_window", "name": self.env._("New SCOT"), "res_model": "ea.audit.scot.wizard",
            "view_mode": "form", "target": "new", "context": {"default_engagement_id": self.id},
        }

    def action_tool_itgc(self):
        self.ensure_one()
        self._ea_require_access()
        self._ea_sync_it_applications()
        return self._ea_board("ea_audit_tools.view_engagement_itgc_board", self.env._("IT applications and ITGC"))

    def action_tool_fscp(self):
        self.ensure_one()
        self._ea_require_access()
        Fscp = self.env["ea.audit.fscp"].sudo()
        record = Fscp.search([("engagement_id", "=", self.id)], limit=1) or Fscp.create({"engagement_id": self.id})
        return {
            "type": "ir.actions.act_window", "name": self.env._("Financial statement close process"),
            "res_model": "ea.audit.fscp", "res_id": record.id, "view_mode": "form", "target": "current",
            "context": {"ea_engagement_id": self.id},
        }

    def action_export_itgc(self):
        return self._ea_export_action("itgc")

    def action_set_itgc_conclusion(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.env._("S2.5 conclusion"), "res_model": "ea.audit.itgc.wizard",
            "view_mode": "form", "target": "new", "context": {"default_engagement_id": self.id, "default_state": self.sudo().itgc_state},
        }

    def _ea_export_itgc(self, fr):
        from ..exports import simple_workbook

        self._ea_sync_it_applications()
        apps = self.env["ea.audit.it.application"].sudo().search([("engagement_id", "=", self.id), ("removed", "=", False)])
        labels = dict(self.env["ea.audit.it.application"]._fields["strategy"]._description_selection(self.env))
        rows = [[app.name, app.layers or "", app.scot_names or "", labels.get(app.strategy, ""), app.itgc_note or ""] for app in apps]
        head = ["Application", "Couches", "SCOT", "Stratégie", "Note ITGC"] if fr else ["Application", "Layers", "SCOTs", "Strategy", "ITGC note"]
        return "itgc-%s.xlsx" % self._ea_export_slug(), simple_workbook("S2.3", head, rows)

    def _ea_export_scots(self, fr):
        from ..exports import simple_workbook

        rows = []
        for scot in self.sudo().scot_ids:
            for control in scot.control_ids or [self.env["ea.audit.scot.control"]]:
                rows.append([
                    scot.name, scot.transaction_type, scot.strategy, scot.index_summary or "",
                    control.name or "", control.control_type or "", control.frequency_display or "", control.objective or "",
                    "yes" if control.selected_for_testing else "no", control.assertion_summary or "",
                    control.sample_size or "", control.items_label or "", control.operating_eval or "",
                ])
        head = (
            ["SCOT", "Type", "Stratégie", "Indices", "Contrôle", "Nature", "Fréquence", "Objectif", "Sélectionné", "Assertions", "Échantillon", "Occurrences", "Conclusion"]
            if fr else
            ["SCOT", "Type", "Strategy", "Indexes", "Control", "Nature", "Frequency", "Objective", "Selected", "Assertions", "Sample", "Occurrences", "Conclusion"]
        )
        return "scots-%s.xlsx" % self._ea_export_slug(), simple_workbook("S1.1", head, rows, title=french_date(self.sudo().period_end))


class FileItemScot(models.Model):
    """embeddedWorkGap: what the board of an embed-only paper still lacks, as the refusal to raise."""

    _inherit = "ea.audit.file.item"

    def _ea_tool_gap(self):
        self.ensure_one()
        if self.code not in ("S1.2", "S1.3", "S2.1", "S2.2", "S2.3"):
            return super()._ea_tool_gap()
        scots = self.sudo().engagement_id.scot_ids
        controls = scots.control_ids.filtered("selected_for_testing")
        if self.code == "S1.3":
            return "walkthrough-incomplete" if any(s.walkthrough_open for s in scots) else None
        if self.code == "S1.2":
            return "wcgw-missing" if any(not s.wcgw_ids for s in scots) else None
        if self.code == "S2.1":
            unlinked = controls.filtered(lambda c: not c.wcgw_ids)
            unselected = scots.filtered(lambda s: s.strategy == "controls" and not s.control_ids.filtered("selected_for_testing"))
            return "control-selection-incomplete" if unlinked or unselected else None
        if self.code == "S2.2":
            return "test-design-missing" if controls.filtered(lambda c: not (c.test_design or "").strip()) else None
        engagement = self.sudo().engagement_id
        engagement._ea_sync_it_applications()
        apps = self.env["ea.audit.it.application"].sudo().search([("engagement_id", "=", engagement.id), ("removed", "=", False)])
        return "itapp-strategy-missing" if apps.filtered(lambda a: not a.strategy) else None
