import base64

from odoo import api, fields, models

from ..models.sampling import METHOD_SELECTION
from ..models.scot import (
    CONTROL_TYPE_SELECTION, ITGC_STATE_SELECTION, OBJECTIVE_SELECTION, RELIANCE_SELECTION, STRATEGY_SELECTION, TYPE_SELECTION,
)
from ..models.tool_record import is_french
from ..rules import rule_error
from ..services.errors import ServiceError
from ..services.sampling_params import ATTRIBUTE_SAMPLE_SIZES, CONFIDENCE_FACTORS
from ..services.toc_sampling import (
    FREQUENCY_CODES, OCCURRENCE_FREQUENCIES, effective_frequency, frequency_choice_sizes, frequency_label, toc_suggested,
)
from ..tabular import parse_table

_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}
_CLOSE = {"type": "ir.actions.act_window_close"}


def _codes(tags):
    return tags.mapped("code")


class ScotWizard(models.TransientModel):
    _name = "ea.audit.scot.wizard"
    _description = "New SCOT"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    name = fields.Char(required=True)
    transaction_type = fields.Selection(TYPE_SELECTION, default="routine", required=True)
    strategy = fields.Selection(STRATEGY_SELECTION, default="substantive", required=True)
    applications = fields.Char(string="IT applications", help="Separated by commas. Separators inside parentheses do not split.")
    description = fields.Text()

    def action_create(self):
        self.ensure_one()
        self.engagement_id.create_scot(self.name, self.transaction_type, self.strategy, self.applications, self.description)
        return _RELOAD


class ScotIndexWizard(models.TransientModel):
    _name = "ea.audit.scot.index.wizard"
    _description = "Link a lead index"

    scot_id = fields.Many2one("ea.audit.scot", required=True)
    index_code = fields.Selection(lambda self: self.env["ea.audit.tool.record"]._lead_index_selection(), string="Lead index", required=True)
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")

    def action_link(self):
        self.ensure_one()
        self.scot_id.link_index(self.index_code, _codes(self.assertion_ids))
        return _RELOAD


class WcgwWizard(models.TransientModel):
    _name = "ea.audit.wcgw.wizard"
    _description = "Add what can go wrong"

    scot_id = fields.Many2one("ea.audit.scot", required=True)
    description = fields.Char(required=True)
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")

    def action_add(self):
        self.ensure_one()
        self.scot_id.add_wcgw(self.description, _codes(self.assertion_ids))
        return _RELOAD


class ControlWizard(models.TransientModel):
    _name = "ea.audit.control.wizard"
    _description = "Add a control"

    scot_id = fields.Many2one("ea.audit.scot", required=True)
    name = fields.Char(required=True)
    owner = fields.Char()
    control_type = fields.Selection(CONTROL_TYPE_SELECTION, string="Control type", default="manual", required=True)
    frequency = fields.Selection(selection="_ea_frequency_choices", string="Frequency")
    frequency_other = fields.Char(string="Why another frequency")
    occurrences = fields.Integer(string="How many times in the year?")
    reliance = fields.Selection(RELIANCE_SELECTION, string="Reliance", default="normal", required=True)
    needs_occurrences = fields.Boolean(compute="_compute_suggestion")
    suggestion = fields.Char(string="Suggested test", compute="_compute_suggestion")
    objective = fields.Selection(OBJECTIVE_SELECTION, default="prevent", required=True)
    wcgw_ids = fields.Many2many("ea.audit.wcgw", string="What it answers", domain="[('scot_id', '=', scot_id)]")

    @api.model
    def _ea_frequency_choices(self):
        """The fixed list, each choice with its test sizes "normal · heavy" or what it needs."""
        fr = is_french(self.env)
        return [(code, "%s   (%s)" % (frequency_label(code, fr), frequency_choice_sizes(code, fr))) for code in FREQUENCY_CODES]

    @api.depends("control_type", "frequency", "reliance", "occurrences")
    @api.depends_context("lang")
    def _compute_suggestion(self):
        fr = is_french(self.env)
        _ = self.env._
        for wizard in self:
            wizard.needs_occurrences = wizard.control_type != "automated" and wizard.frequency in OCCURRENCE_FREQUENCIES
            found = toc_suggested(wizard.control_type, wizard.frequency or None, wizard.occurrences or None, False, fr, wizard.reliance)
            if not found:
                wizard.suggestion = _("Choose a frequency") if wizard.frequency != "other" else _("No suggestion for another frequency: the reason is required.")
            elif "size" not in found:
                wizard.suggestion = _("Say how many times in the year")
            else:
                wizard.suggestion = _("Suggested test: %(size)s (%(rule)s)", size=found["size"], rule=found["rule"])

    def action_add(self):
        self.ensure_one()
        frequency = False if self.control_type == "automated" else self.frequency
        self.scot_id.add_control(
            self.name, self.owner, self.control_type, frequency, self.objective, self.wcgw_ids,
            reliance=self.reliance, occurrences=self.occurrences, frequency_other=self.frequency_other,
        )
        return _RELOAD


class ScotAssignWizard(models.TransientModel):
    _name = "ea.audit.scot.assign.wizard"
    _description = "Assign a SCOT"

    scot_id = fields.Many2one("ea.audit.scot", required=True)
    user_id = fields.Many2one("res.users", string="Assigned to")

    def action_assign(self):
        self.ensure_one()
        self.scot_id.assign(self.user_id)
        return _RELOAD


class ControlLinkWizard(models.TransientModel):
    """toggleWcgwControl, one link at a time: a senior and above."""

    _name = "ea.audit.control.link.wizard"
    _description = "What a control answers"

    control_id = fields.Many2one("ea.audit.scot.control", required=True)
    scot_id = fields.Many2one(related="control_id.scot_id")
    wcgw_ids = fields.Many2many("ea.audit.wcgw", string="What it answers", domain="[('scot_id', '=', scot_id)]")

    def action_save(self):
        self.ensure_one()
        current = self.control_id.sudo().wcgw_ids
        for wcgw in self.wcgw_ids - current:
            wcgw.toggle_control(self.control_id, True)
        for wcgw in current - self.wcgw_ids:
            wcgw.with_env(self.env).toggle_control(self.control_id, False)
        return _RELOAD


class TocDrawWizard(models.TransientModel):
    _name = "ea.audit.toc.draw.wizard"
    _description = "Draw a test-of-controls sample"

    control_id = fields.Many2one("ea.audit.scot.control", required=True)
    population = fields.Integer(required=True)
    sample_size = fields.Integer(string="Sample size", required=True)
    suggested_rule = fields.Char(string="Rule", readonly=True)
    draw_count = fields.Integer(string="Earlier draws", readonly=True)
    reason = fields.Char(string="Reason for the redraw")
    suggested_size = fields.Integer(string="Suggested size", readonly=True)
    below_reason = fields.Char(string="Why a smaller test than suggested")

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        control = self.env["ea.audit.scot.control"].browse(values.get("control_id") or self.env.context.get("default_control_id"))
        if control:
            as_root = control.sudo()
            values.update({
                "population": as_root.toc_population, "sample_size": as_root.suggested_size or as_root.sample_size,
                "suggested_rule": as_root.suggested_rule, "draw_count": len(as_root.draw_ids),
                "suggested_size": as_root.suggested_size,
            })
        return values

    @api.onchange("population")
    def _onchange_population(self):
        """The minimum follows the population: the source's table depends on it."""
        as_root = self.control_id.sudo()
        if as_root and self.population and not as_root.frozen_size and not as_root.testing_started:
            frequency = effective_frequency(as_root.frequency_code, as_root.frequency)
            suggestion = toc_suggested(as_root.control_type, frequency, self.population, as_root.sole_control, is_french(self.env), as_root.reliance or "normal")
            if suggestion and "size" in suggestion:
                self.sample_size = suggestion["size"]
                self.suggested_size = suggestion["size"]
                self.suggested_rule = suggestion["rule"]

    def action_draw(self):
        self.ensure_one()
        self.control_id.draw_toc_sample(self.population, self.sample_size, self.suggested_rule, self.reason, self.below_reason)
        return _RELOAD


class TocGridWizard(models.TransientModel):
    """The E1.2 grid as Excel: reference, date, description, then one column per attribute (pass/fail/na)."""

    _name = "ea.audit.toc.grid.wizard"
    _description = "Import the test grid"

    control_id = fields.Many2one("ea.audit.scot.control", required=True)
    file = fields.Binary(string="File (.csv, .xlsx)", required=True)
    filename = fields.Char()

    def action_import(self):
        self.ensure_one()
        try:
            table = parse_table(self.filename, base64.b64decode(self.file or b""))
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        fixed = {"ref", "date", "desc"}
        attributes = [header for header in table["headers"] if header not in fixed]
        rows = []
        for row in table["rows"]:
            results = {}
            for attribute in attributes:
                value = (row.get(attribute) or "").strip().lower()
                if value not in ("pass", "fail", "na", ""):
                    raise rule_error(self.env, "invalid-value")
                results[attribute] = value
            rows.append({"ref": row.get("ref") or "", "date": row.get("date") or "", "desc": row.get("desc") or "", "results": results})
        self.control_id.update_control({"toc_grid": {"attributes": attributes, "rows": rows}})
        return _RELOAD


class ItgcWizard(models.TransientModel):
    _name = "ea.audit.itgc.wizard"
    _description = "S2.5 conclusion"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    state = fields.Selection(ITGC_STATE_SELECTION, string="ITGC conclusion")

    def action_save(self):
        self.ensure_one()
        self.engagement_id.save_itgc_conclusion(self.state)
        return _RELOAD


class TodWizard(models.TransientModel):
    """Side and assurance, the parameters per index, then the workbook."""

    _name = "ea.audit.tod.wizard"
    _description = "Tests of details: plan"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    side = fields.Selection([("bs", "Balance sheet"), ("is", "Income statement")], default="bs", required=True)
    assurance = fields.Selection(
        [("little", "Little"), ("some", "Some"), ("corroborative", "Corroborative"), ("persuasive", "Persuasive")],
        string="Assurance from other procedures", default="little", required=True,
    )
    preview_html = fields.Html(sanitize=False, readonly=True)

    def action_preview(self):
        self.ensure_one()
        self.preview_html = self.engagement_id.tod_preview_html(self.side, self.assurance)
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new", "name": self.env._("Tests of details: plan")}

    def action_export(self):
        self.ensure_one()
        return self.engagement_id._ea_export_action("tod_%s_%s" % (self.side, self.assurance))


class TodResultWizard(models.TransientModel):
    _name = "ea.audit.tod.result.wizard"
    _description = "Record a tests-of-details result"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    index_code = fields.Selection(lambda self: self.env["ea.audit.tool.record"]._lead_index_selection(), string="Lead index", required=True)
    sample_value = fields.Float(string="Sample value", digits=(18, 2), required=True)
    sample_misstatement = fields.Float(string="Misstatement in the sample", digits=(18, 2))
    key_misstatement = fields.Float(string="Key-item misstatement", digits=(18, 2))
    remaining_value = fields.Float(string="Remaining population", digits=(18, 2), required=True)

    def action_record(self):
        self.ensure_one()
        self.engagement_id.record_tod_result(self.index_code, self.sample_value, self.sample_misstatement, self.key_misstatement, self.remaining_value)
        return _RELOAD


class SamplingWizard(models.TransientModel):
    """runSampling on any dataset. The size is computed for MUS with a confidence level."""

    _name = "ea.audit.sampling.wizard"
    _description = "Draw a sample from a dataset"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    dataset_id = fields.Many2one("ea.audit.dataset", string="Dataset", required=True, domain="[('engagement_id', '=', engagement_id), ('superseded_at', '=', False)]")
    method = fields.Selection(METHOD_SELECTION, default="mus", required=True)
    sample_size = fields.Integer(string="Sample size", default=25, required=True)
    seed = fields.Char(help="Empty: generated and stored with the run, so the draw can be reproduced.")
    threshold = fields.Float(string="Key-item threshold", digits=(18, 2))
    confidence = fields.Selection([(str(key), "%d %%" % key) for key in sorted(CONFIDENCE_FACTORS, reverse=True)], string="Confidence")
    expected = fields.Float(string="Expected misstatement", digits=(18, 2))
    override_size = fields.Integer(string="Size typed by hand")
    override_rationale = fields.Char(string="Why the size is typed by hand")
    frequency = fields.Selection([(key, key.title()) for key in ATTRIBUTE_SAMPLE_SIZES], string="Attribute plan: frequency")
    attribute_size = fields.Integer(string="Attribute plan: minimum", compute="_compute_attribute")

    @api.depends("frequency")
    def _compute_attribute(self):
        for wizard in self:
            wizard.attribute_size = ATTRIBUTE_SAMPLE_SIZES.get(wizard.frequency, 0)

    def action_run(self):
        self.ensure_one()
        run = self.engagement_id.run_sampling(
            self.dataset_id.id, self.method, self.sample_size, seed=self.seed or None, threshold=self.threshold or None,
            confidence=int(self.confidence) if self.confidence else None, expected=self.expected or None,
            override_size=self.override_size or None, override_rationale=self.override_rationale or None,
        )
        return run.action_export() if run else _CLOSE

