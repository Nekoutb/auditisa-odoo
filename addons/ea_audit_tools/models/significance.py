from odoo import fields, models

from ..rules import rule_error
from ..services._js import js_round
from ..services.lead_classes import LEAD_INDEX_BY_CODE
from ..services.significant_accounts import significance_rows, specific_refusal, unjustified_count

STATUS_SELECTION = [("significant", "Significant"), ("not_significant", "Not significant")]


class Significance(models.Model):
    """P6.2: one row per lead index carrying a TB balance. The decision, its reason, the
    relevant assertions and the specific materiality are recorded; the rest is computed."""

    _name = "ea.audit.significance"
    _inherit = ["ea.audit.tool.record"]
    _description = "Significant account decision"
    _order = "sequence, id"
    _rec_name = "index_code"

    index_code = fields.Selection(selection="_lead_index_selection", string="Lead index", required=True, index=True)
    sequence = fields.Integer(default=10)
    closing = fields.Float(digits=(18, 0))
    decision = fields.Selection(STATUS_SELECTION, string="Recorded decision")
    justification = fields.Text()
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Relevant assertions")
    specific_te = fields.Float(string="Specific materiality", digits=(18, 0))

    above_te = fields.Boolean(string="Above threshold", compute="_compute_row", compute_sudo=True)
    default_status = fields.Selection(STATUS_SELECTION, string="Default", compute="_compute_row", compute_sudo=True)
    status = fields.Selection(STATUS_SELECTION, compute="_compute_row", inverse="_inverse_noop", compute_sudo=True)
    overridden = fields.Boolean(compute="_compute_row", compute_sudo=True)
    unjustified = fields.Boolean(compute="_compute_row", compute_sudo=True)
    has_risk = fields.Boolean(string="Risk linked", compute="_compute_row", compute_sudo=True)
    risk_assertions = fields.Char(string="Risk assertions", compute="_compute_row", compute_sudo=True)

    _uniq = models.Constraint("UNIQUE(engagement_id, index_code)", "One decision per lead index.")

    def _compute_row(self):
        for engagement in self.engagement_id:
            rows = {row["index"]: row for row in engagement._ea_significance_rows()}
            derived = engagement._ea_risk_derived_assertions()
            for record in self.filtered(lambda r: r.engagement_id == engagement):
                row = rows.get(record.index_code)
                record.above_te = bool(row and row["aboveTe"])
                record.default_status = row["defaultStatus"] if row else False
                record.status = row["status"] if row else record.decision
                record.overridden = bool(row and row["overridden"])
                record.unjustified = bool(row and row["overridden"] and not row["justification"].strip())
                record.has_risk = bool(row and row["hasRisk"])
                record.risk_assertions = ", ".join(sorted(derived.get(record.index_code, ())))

    def _inverse_noop(self):
        """The value arrives through _ea_user_write, never through here."""

    def _ea_user_write(self, vals):
        self._ea_only(vals, {"status", "justification", "assertion_ids", "specific_te"})
        self._ea_guard()
        for record in self.sudo():
            record.with_env(self.env)._ea_save(vals)
        self.invalidate_recordset()
        return True

    def _ea_save(self, vals):
        """saveSignificance. Refused above overall materiality, then above TE."""
        as_root = self.sudo()
        engagement = as_root.engagement_id
        if "status" in vals and vals["status"] and vals["status"] not in dict(STATUS_SELECTION):
            raise rule_error(self.env, "invalid-value")
        values = {}
        if "status" in vals:
            values["decision"] = vals["status"] or False
        if "justification" in vals:
            values["justification"] = (vals["justification"] or "").strip() or False
        if "assertion_ids" in vals:
            values["assertion_ids"] = vals["assertion_ids"]
        if "specific_te" in vals:
            amount = vals["specific_te"] or 0
            materiality = engagement._ea_materiality_dict()
            refusal = specific_refusal(
                amount, materiality and materiality["overall"], materiality and materiality["performance"],
            )
            if refusal:
                raise rule_error(self.env, refusal)
            values["specific_te"] = js_round(amount) if amount > 0 else 0
        as_root.write(values)
        return True


class EngagementSignificance(models.Model):
    _inherit = "ea.audit.engagement"

    significance_ids = fields.One2many("ea.audit.significance", "engagement_id", string="Significant accounts")
    significance_unjustified = fields.Integer(string="Unjustified departures", compute="_compute_significance_counts", compute_sudo=True)
    significance_count = fields.Integer(string="Significant accounts count", compute="_compute_significance_counts", compute_sudo=True)

    def _compute_significance_counts(self):
        for engagement in self:
            rows = engagement._ea_significance_rows()
            engagement.significance_unjustified = unjustified_count(rows)
            engagement.significance_count = len([row for row in rows if row["status"] == "significant"])

    def _ea_risk_derived_assertions(self):
        """riskDerivedAssertions: every index a live risk lands on, with the threatened assertions."""
        self.ensure_one()
        links = self.env["ea.audit.risk.index"].sudo().search([
            ("engagement_id", "=", self.id), ("risk_id.rebutted", "=", False),
        ])
        out = {}
        for link in links:
            out.setdefault(link.index_code, set()).update(link.assertion_ids.mapped("code"))
        return out

    def _ea_significance_rows(self):
        self.ensure_one()
        as_root = self.sudo()
        materiality = as_root._ea_materiality_dict()
        records = self.env["ea.audit.significance"].sudo().search([("engagement_id", "=", self.id)])
        decisions = {r.index_code: {"status": r.decision, "justification": r.justification or ""} for r in records}
        specific = {r.index_code: r.specific_te for r in records if r.specific_te > 0}
        return significance_rows(
            as_root._ea_closings_by_index(),
            materiality["performance"] if materiality else None,
            specific,
            decisions,
            as_root._ea_risk_derived_assertions(),
        )

    def _ea_sync_significance(self):
        """Derived rows follow the current TB. A row holding a decision is kept."""
        self.ensure_one()
        if self.sudo()._ea_is_archived():
            return
        Significance = self.env["ea.audit.significance"].sudo()
        closings = self.sudo()._ea_closings_by_index()
        existing = {r.index_code: r for r in Significance.search([("engagement_id", "=", self.id)])}
        order = {code: position for position, code in enumerate(LEAD_INDEX_BY_CODE)}
        for code, closing in closings.items():
            if code in existing:
                if existing[code].closing != closing:
                    existing[code].write({"closing": closing})
            else:
                Significance.create({
                    "engagement_id": self.id, "index_code": code, "closing": closing, "sequence": order.get(code, 999),
                })
        for code, record in existing.items():
            if code not in closings:
                if record.decision or record.justification or record.assertion_ids or record.specific_te:
                    record.write({"closing": 0})
                else:
                    record.unlink()
        self.env.invalidate_all()

    def action_tool_significance(self):
        self.sudo()._ea_sync_significance()
        return self._ea_list(
            "ea.audit.significance", self.env._("Significant accounts"),
            [("ea_audit_tools.view_significance_list", "list")],
        )

    def action_export_significance(self):
        return self._ea_export_action("significance")
