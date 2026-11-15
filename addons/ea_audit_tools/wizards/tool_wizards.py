import base64

from odoo import api, fields, models

from ..models.finding import LIKELIHOOD_SELECTION, MAGNITUDE_SELECTION, MTYPE_SELECTION, SEVERITY_SELECTION
from ..models.materiality import BENCHMARK_SELECTION
from ..models.risk import CATEGORY_SELECTION, LEVEL_SELECTION, RATING_SELECTION
from ..rules import rule_error
from ..services.deficiency_model import suggested_grade
from ..services.materiality import midpoint

_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}


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
        [("rebut", "Rebuttal"), ("reject_rebuttal", "Rejected rebuttal"), ("dismiss", "Dismissal"), ("clear", "Clearing")],
        required=True, readonly=True,
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
            "rebut": ("ea.audit.risk", "propose_rebuttal"),
            "reject_rebuttal": ("ea.audit.risk", "reject_rebuttal"),
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

    def _ea_context_engagement(self, read=False):
        engagement = self.env["ea.audit.engagement"].browse(self.env.context.get("ea_engagement_id"))
        if not engagement:
            raise rule_error(self.env, "not-found")
        # an export only reads: the firm administrator's look-only mode allows it
        if read:
            engagement._ea_require_read()
        else:
            engagement._ea_require_access()
        return engagement

    def action_list_export(self):
        return self._ea_context_engagement(read=True)._ea_export_action(self._ea_export_kind())

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


class SignificanceWizard(models.TransientModel):
    """The row's Change status button (owner's request of 2026-11-15): Significant or Not significant,
    with the reason a departure from the default needs."""

    _name = "ea.audit.significance.wizard"
    _description = "Change the status of a significant account"

    significance_id = fields.Many2one("ea.audit.significance", required=True, ondelete="cascade")
    index_code = fields.Selection(related="significance_id.index_code", string="Lead index")
    closing = fields.Float(related="significance_id.closing", digits=(18, 0))
    current_status = fields.Selection(related="significance_id.status", string="Current status")
    default_status = fields.Selection(related="significance_id.default_status", string="Default")
    new_status = fields.Selection(
        [("significant", "Significant"), ("not_significant", "Not significant")], string="New status", required=True,
    )
    reason = fields.Text()
    needs_reason = fields.Boolean(compute="_compute_needs_reason")

    @api.depends("new_status", "default_status")
    def _compute_needs_reason(self):
        for wizard in self:
            wizard.needs_reason = bool(wizard.new_status and wizard.new_status != wizard.default_status)

    def action_apply(self):
        self.ensure_one()
        self.significance_id.write({"status": self.new_status, "justification": self.reason or ""})
        return _RELOAD
