import base64

from odoo import api, fields, models

from ..models.finding import LIKELIHOOD_SELECTION, MAGNITUDE_SELECTION, MTYPE_SELECTION, SEVERITY_SELECTION
from ..models.materiality import BENCHMARK_SELECTION
from ..models.risk import CATEGORY_SELECTION, LEVEL_SELECTION, RATING_SELECTION
from ..models.tb import TIMING_SELECTION
from ..rules import rule_error
from ..services.deficiency_model import suggested_grade
from ..services.materiality import midpoint
from ..services.tb import ALIASES
from .tool_wizard_helpers import preview_html

MAPPING_FIELDS = tuple("map_%s" % column for column in ALIASES)

_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}


class TbImportWizard(models.TransientModel):
    """Upload, then confirm and map, then ingest: the preview writes nothing."""

    _name = "ea.audit.tb.import.wizard"
    _description = "Import a trial balance"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    file = fields.Binary(string="File (.csv, .xlsx)", required=True)
    filename = fields.Char()
    timing = fields.Selection(TIMING_SELECTION, default="pre_audit", required=True)
    header_row = fields.Boolean(string="First line is a header", default=True)
    step = fields.Selection([("upload", "Upload"), ("confirm", "Confirm")], default="upload")
    preview_html = fields.Html(sanitize=False, readonly=True)
    mapping_error = fields.Char(readonly=True)
    map_account = fields.Char(string="Account")
    map_label = fields.Char(string="Description")
    map_openingDebit = fields.Char(string="Opening debit")
    map_openingCredit = fields.Char(string="Opening credit")
    map_opening = fields.Char(string="Opening (signed)")
    map_debit = fields.Char(string="Debit")
    map_credit = fields.Char(string="Credit")
    map_closingDebit = fields.Char(string="Closing debit")
    map_closingCredit = fields.Char(string="Closing credit")
    map_closing = fields.Char(string="Closing (signed)")

    def _content(self):
        return base64.b64decode(self.file or b"")

    def _mapping(self):
        mapping = {}
        for column in ALIASES:
            value = (self["map_%s" % column] or "").strip()
            if value:
                mapping[column] = value
        return mapping

    def action_preview(self):
        self.ensure_one()
        preview = self.engagement_id.preview_trial_balance_file(self.filename, self._content(), header_row=self.header_row)
        values = {
            "step": "confirm",
            "preview_html": preview_html(preview, self.env),
            "mapping_error": rule_error(self.env, preview["mappingError"]).args[0] if preview["mappingError"] else False,
        }
        for column in ALIASES:
            values["map_%s" % column] = preview["mapping"].get(column) or False
        self.write(values)
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "target": "new", "name": self.env._("Confirm the column mapping"),
        }

    def action_import(self):
        self.ensure_one()
        self.engagement_id.import_trial_balance(
            self.filename, self._content(), mapping=self._mapping(), timing=self.timing, header_row=self.header_row,
        )
        return _RELOAD


class MaterialityWizard(models.TransientModel):
    _name = "ea.audit.materiality.wizard"
    _description = "Generate a materiality version"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    benchmark = fields.Selection(BENCHMARK_SELECTION, required=True, default="pbt")
    benchmark_amount = fields.Float(string="Base amount", digits=(18, 2))
    percentage = fields.Float(digits=(5, 2))
    justification = fields.Text(required=True)
    performance_pct = fields.Float(string="Performance %", digits=(5, 2), default=75)
    performance_justification = fields.Text()
    trivial_pct = fields.Float(string="Clearly trivial %", digits=(5, 2), default=5)
    override_justification = fields.Text(string="Why it departs from the range or the TB base")

    @api.onchange("benchmark", "engagement_id")
    def _onchange_benchmark(self):
        """Refills the amount from the TB base and the percentage from the range's midpoint."""
        if not self.benchmark or not self.engagement_id:
            return
        self.percentage = midpoint(self.benchmark)
        bases = self.engagement_id.sudo()._ea_tb_bases()
        if bases:
            self.benchmark_amount = max(bases[self.benchmark], 0)

    def action_generate(self):
        self.ensure_one()
        self.engagement_id.create_materiality_version(
            self.benchmark, self.benchmark_amount, self.percentage, self.justification,
            performance_pct=self.performance_pct, performance_justification=self.performance_justification,
            trivial_pct=self.trivial_pct, override_justification=self.override_justification,
        )
        return _RELOAD


class RiskWizard(models.TransientModel):
    _name = "ea.audit.risk.wizard"
    _description = "Add a risk"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    description = fields.Text(required=True)
    source = fields.Char(string="Where it was identified")
    category = fields.Selection(CATEGORY_SELECTION, default="business", required=True)
    level = fields.Selection(LEVEL_SELECTION, default="assertion", required=True)
    likelihood = fields.Selection(RATING_SELECTION, default="medium", required=True)
    magnitude = fields.Selection(RATING_SELECTION, default="medium", required=True)
    significant = fields.Boolean()
    index_code = fields.Selection(selection="_lead_index_selection", string="Lead index")
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")
    management_missed = fields.Char(string="Why management's process did not identify it")
    fs_note = fields.Text(string="Pervasive effect")

    @api.model
    def _lead_index_selection(self):
        return self.env["ea.audit.tool.record"]._lead_index_selection()

    def action_add(self):
        self.ensure_one()
        self.engagement_id.add_risk(
            self.description, category=self.category, level=self.level, likelihood=self.likelihood,
            magnitude=self.magnitude, significant=self.significant, index=self.index_code or None,
            assertions=self.assertion_ids.mapped("code"), source=self.source,
            management_missed=self.management_missed, fs_note=self.fs_note,
        )
        return _RELOAD


class RiskLinkWizard(models.TransientModel):
    _name = "ea.audit.risk.link.wizard"
    _description = "Link a risk to a lead index"

    risk_id = fields.Many2one("ea.audit.risk", required=True)
    index_code = fields.Selection(selection="_lead_index_selection", string="Lead index", required=True)
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")

    @api.model
    def _lead_index_selection(self):
        return self.env["ea.audit.tool.record"]._lead_index_selection()

    def action_link(self):
        self.ensure_one()
        self.risk_id.link_index(self.index_code, self.assertion_ids.mapped("code"))
        return _RELOAD


class FindingWizard(models.TransientModel):
    _name = "ea.audit.finding.wizard"
    _description = "New finding"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    route = fields.Selection(
        [("b4", "Matter for attention"), ("c1", "Control deficiency"), ("b5", "Misstatement"), ("revise", "Revise the approach")],
        default="c1", required=True,
    )
    title = fields.Char(required=True)
    detail = fields.Text()
    severity = fields.Selection(SEVERITY_SELECTION)
    recommendation = fields.Text()
    file_item_id = fields.Many2one("ea.audit.file.item", string="Paper", domain="[('engagement_id', '=', engagement_id)]")
    amount = fields.Float(digits=(18, 2))
    accounts = fields.Char()
    mtype = fields.Selection(MTYPE_SELECTION, string="Type", default="factual")
    trivial_confirmed = fields.Boolean(string="Not indicative of a pervasive issue")
    significant = fields.Boolean()

    def action_route(self):
        self.ensure_one()
        self.engagement_id.route_finding(
            self.route, self.title, detail=self.detail, severity=self.severity or None,
            recommendation=self.recommendation, file_item=self.file_item_id or None, amount=self.amount,
            accounts=self.accounts, mtype=self.mtype or "factual", trivial_confirmed=self.trivial_confirmed,
            significant=self.significant,
        )
        return _RELOAD


class DeficiencyWizard(models.TransientModel):
    _name = "ea.audit.deficiency.wizard"
    _description = "ISA 265 evaluation"

    finding_id = fields.Many2one("ea.audit.finding", required=True)
    likelihood = fields.Selection(LIKELIHOOD_SELECTION)
    magnitude = fields.Selection(MAGNITUDE_SELECTION)
    suggested = fields.Selection(SEVERITY_SELECTION, string="Suggested grade", compute="_compute_suggested")
    grade = fields.Selection(SEVERITY_SELECTION, required=True)
    accounts_assertions = fields.Text(string="Accounts and assertions exposed")
    management_aware = fields.Boolean(string="Management aware")
    indicators = fields.Text(string="ISA 265 A6-A7 indicators")
    related_finding_ids = fields.Many2many("ea.audit.finding", string="Related deficiencies")
    aggregation_note = fields.Text()
    communicated_on = fields.Date(string="Communicated in writing on")
    recipient = fields.Char()

    @api.depends("likelihood", "magnitude")
    def _compute_suggested(self):
        for wizard in self:
            wizard.suggested = suggested_grade(wizard.likelihood, wizard.magnitude) or False

    def action_save(self):
        self.ensure_one()
        self.finding_id.save_deficiency_evaluation(
            self.grade, likelihood=self.likelihood or None, magnitude=self.magnitude or None,
            accounts_assertions=self.accounts_assertions, management_aware=self.management_aware,
            indicators=self.indicators, related_ids=self.related_finding_ids.ids,
            aggregation_note=self.aggregation_note, communicated_on=self.communicated_on, recipient=self.recipient,
        )
        return _RELOAD


class ReasonWizard(models.TransientModel):
    """One written reason, for a fixed list of actions. Which action is a Selection, not a method name."""

    _name = "ea.audit.reason.wizard"
    _description = "A written reason"

    kind = fields.Selection(
        [("rebut", "Rebuttal"), ("dismiss", "Dismissal"), ("clear", "Clearing")], required=True, readonly=True,
    )
    record_id = fields.Integer(required=True)
    reason = fields.Text(required=True)

    @api.model
    def _ea_open(self, kind, record):
        record.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("A written reason"),
            "res_model": self._name,
            "view_mode": "form",
            "target": "new",
            "context": {"default_kind": kind, "default_record_id": record.id},
        }

    def action_confirm(self):
        self.ensure_one()
        model, method = {
            "rebut": ("ea.audit.risk", "rebut"),
            "dismiss": ("ea.audit.potential.risk", "dismiss"),
            "clear": ("ea.audit.finding", "clear"),
        }[self.kind]
        getattr(self.env[model].browse(self.record_id), method)(self.reason)
        return _RELOAD


class ToolImportWizard(models.TransientModel):
    _name = "ea.audit.tool.import.wizard"
    _description = "Import from Excel"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    kind = fields.Selection(
        [("cra", "Combined risk assessment"), ("significance", "Significant accounts"), ("risks", "Risks"), ("dsp", "Design of procedures"), ("pbc", "PBC requests")], required=True,
    )
    file = fields.Binary(string="File (.csv, .xlsx)", required=True)
    filename = fields.Char()

    def action_import(self):
        self.ensure_one()
        self.engagement_id.ea_import_xlsx(self.kind, self.filename, base64.b64decode(self.file or b""))
        return _RELOAD


class ToolListActions(models.AbstractModel):
    """What the list screens' always-visible header buttons call: the engagement is in the action's context."""

    _inherit = "ea.audit.tool.record"

    def _ea_context_engagement(self):
        engagement = self.env["ea.audit.engagement"].browse(self.env.context.get("ea_engagement_id"))
        if not engagement:
            raise rule_error(self.env, "not-found")
        engagement._ea_require_access()
        return engagement

    def action_list_export(self):
        return self._ea_context_engagement()._ea_export_action(self._ea_export_kind())

    def action_list_import(self):
        engagement = self._ea_context_engagement()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Import from Excel"),
            "res_model": "ea.audit.tool.import.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_engagement_id": engagement.id, "default_kind": self._ea_export_kind()},
        }

    def action_list_add_risk(self):
        engagement = self._ea_context_engagement()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Add a risk"),
            "res_model": "ea.audit.risk.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_engagement_id": engagement.id},
        }

    def _ea_export_kind(self):
        return {
            "ea.audit.significance": "significance",
            "ea.audit.risk": "risks",
            "ea.audit.cra.assessment": "cra",
            "ea.audit.lead.line": "lead",
        }.get(self._name, "")
