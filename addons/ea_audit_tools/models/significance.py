from odoo import fields, models

from ..rules import rule_error
from ..services._js import js_round
from ..services.ap_schedules import index_resolver
from ..services.lead_classes import LEAD_INDEX_BY_CODE
from ..services.significance_activity import IndexActivity, line_reader, people_columns
from ..services.significant_accounts import significance_rows, specific_refusal, unjustified_count

STATUS_SELECTION = [("significant", "Significant"), ("not_significant", "Not significant")]
# The trail is written in English with the labels a reader knows (activity_summary translates them).
STATUS_LABELS = dict(STATUS_SELECTION)
# Ledger rows read per query when the activity is counted: memory stays bounded on a large ledger.
ACTIVITY_BATCH = 20000


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
    justification = fields.Text(string="Reason")
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Relevant assertions")
    specific_te = fields.Float(string="Specific materiality", digits=(18, 0))
    # Counted from the general ledger in use when it changes, and when the rows follow the TB:
    # stored, as a ledger can hold some 200,000 lines. activity_dataset is the upload counted
    # (0: no ledger in use; empty: never counted, as on an archived file).
    activity_dataset = fields.Integer(readonly=True)
    tx_count = fields.Integer(
        string="Transactions", readonly=True, aggregator=False,
        help="Journal entries of the general ledger in use with at least one line on an account of this index.",
    )
    preparer_count = fields.Integer(
        string="Preparers", readonly=True, aggregator=False,
        help="People who recorded those entries (Recorded by or Prepared by column of the general ledger).",
    )
    reviewer_count = fields.Integer(
        string="Reviewers", readonly=True, aggregator=False,
        help="People who approved or reviewed those entries (Approved by or Reviewer column of the general ledger).",
    )
    preparer_known = fields.Boolean(readonly=True)
    reviewer_known = fields.Boolean(readonly=True)

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
        before_status, before_reason = as_root.status, as_root.justification or ""
        decision = values.get("decision", as_root.decision)
        reason = values.get("justification", as_root.justification) or ""
        touched = decision != as_root.decision or reason != before_reason
        after_status = decision or as_root.default_status
        # Owner's request of 2026-11-15: a departure from the default is saved with its reason.
        # Only a change is held to it: a departure stored without one stays, shown in red.
        if touched and after_status and after_status != as_root.default_status and not reason.strip():
            raise rule_error(self.env, "significance-reason-required", index=as_root.index_code)
        as_root.write(values)
        if before_status and after_status != before_status:
            engagement.with_env(self.env)._ea_log(
                "significance_changed",
                "Significance of %s changed from %s to %s by %s%s" % (
                    as_root.index_code, STATUS_LABELS[before_status], STATUS_LABELS[after_status], self.env.user.name,
                    ": %s" % " ".join(reason.split()) if reason.strip() else "",
                ),
            )
        return True

    def action_change_status(self):
        """The row's Change status button: the status and its reason, in one small window."""
        self.ensure_one()
        record = self.sudo()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Change the status of %(index)s", index=record.index_code),
            "res_model": "ea.audit.significance.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_significance_id": record.id,
                "default_new_status": "not_significant" if record.status == "significant" else "significant",
                "default_reason": record.justification or "",
            },
        }


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

    def _ea_significance_activity(self):
        """(dataset id, preparer known, reviewer known, {index: counts}) of the general ledger in
        use, the one the rest of the ledger tools read. Dataset id 0 when there is none."""
        self.ensure_one()
        as_root = self.sudo()
        dataset = as_root._ea_current_dataset("journal_entries")
        read = line_reader(dataset.mapping) if dataset else None
        if not read:
            return 0, False, False, {}
        preparer_known, reviewer_known = people_columns(dataset.mapping)
        activity = IndexActivity(index_resolver(as_root._ea_lead_overrides()))
        cr = self.env.cr
        after = 0
        while True:
            cr.execute(
                "SELECT row_no, data FROM ea_audit_dataset_row WHERE dataset_id = %s AND row_no > %s ORDER BY row_no LIMIT %s",
                [dataset.id, after, ACTIVITY_BATCH],
            )
            batch = cr.fetchall()
            if not batch:
                break
            after = batch[-1][0]
            for _row_no, data in batch:
                account, je_number, preparer, reviewer, approver = read(data)
                activity.add(account, je_number, preparer, (reviewer, approver))
            if len(batch) < ACTIVITY_BATCH:
                break
        return dataset.id, preparer_known, reviewer_known, activity.result()

    def _ea_refresh_significance_activity(self, force=True):
        """Writes the ledger counts on the rows where they differ. Without force, only when a
        row was counted from another ledger than the one in use, or never: opening the list
        stays quick on a large ledger. An archived file is left as it is."""
        self.ensure_one()
        if self.sudo()._ea_is_archived():
            return
        Significance = self.env["ea.audit.significance"].sudo()
        records = Significance.search([("engagement_id", "=", self.id)])
        if not records:
            return
        if not force:
            current = self.sudo()._ea_current_dataset("journal_entries").id or 0
            self.env.cr.execute(
                "SELECT count(*) FROM ea_audit_significance WHERE engagement_id = %s"
                " AND (activity_dataset IS NULL OR activity_dataset != %s)",
                [self.id, current],
            )
            if not self.env.cr.fetchone()[0]:
                return
        dataset_id, preparer_known, reviewer_known, by_index = self._ea_significance_activity()
        # the ORM reads an empty integer as 0: the rows never counted, from the table itself
        self.env.cr.execute(
            "SELECT id FROM ea_audit_significance WHERE engagement_id = %s AND activity_dataset IS NULL", [self.id],
        )
        never = {row[0] for row in self.env.cr.fetchall()}
        for record in records:
            counts = by_index.get(record.index_code) or {}
            values = {
                "activity_dataset": dataset_id,
                "tx_count": counts.get("entries", 0),
                "preparer_count": counts.get("preparers", 0) if preparer_known else 0,
                "reviewer_count": counts.get("reviewers", 0) if reviewer_known else 0,
                "preparer_known": bool(dataset_id and preparer_known),
                "reviewer_known": bool(dataset_id and reviewer_known),
            }
            stored = {
                "activity_dataset": None if record.id in never else record.activity_dataset,
                "tx_count": record.tx_count, "preparer_count": record.preparer_count,
                "reviewer_count": record.reviewer_count, "preparer_known": record.preparer_known,
                "reviewer_known": record.reviewer_known,
            }
            if stored != values:
                record.write(values)

    def _ea_sync_significance(self, activity=True):
        """Derived rows follow the current TB. A row holding a decision is kept. The ledger
        counts follow too; activity=False counts only when a row was never counted from the
        ledger in use (opening the list, the Excel round trip)."""
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
        self.env.flush_all()
        self._ea_refresh_significance_activity(force=activity)
        self.env.invalidate_all()

    def action_tool_significance(self):
        self.sudo()._ea_sync_significance(activity=False)
        return self._ea_list(
            "ea.audit.significance", self.env._("Significant accounts"),
            [("ea_audit_tools.view_significance_list", "list")],
        )

    def action_export_significance(self):
        return self._ea_export_action("significance")
