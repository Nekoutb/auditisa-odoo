from markupsafe import Markup

from odoo import fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import can_partner_signoff

from ..rules import rule_error
from ..services.materiality import (
    BENCHMARK_RANGES,
    compute_materiality,
    materiality_deviations,
    midpoint,
    tb_benchmark_amounts,
    validate_version,
)
from ..services.materiality_model import PERFORMANCE_PCT_RANGE, TRIVIAL_PCT_RANGE, benchmark_label, uncorrected_misstatement_threshold
from .tool_record import fcfa, french_date, grouped, is_french

BENCHMARK_SELECTION = [
    ("pbt", "Profit before tax"),
    ("revenue", "Revenue"),
    ("total_assets", "Total assets"),
    ("equity", "Equity"),
    ("expenses", "Total expenses"),
]


class Materiality(models.Model):
    """Versioned. A draft never supersedes an approved version; only the latest can be approved.
    The ranges bind new versions only: a stored figure outside them keeps displaying."""

    _name = "ea.audit.materiality"
    _inherit = ["ea.audit.tool.record"]
    _description = "Materiality version"
    _order = "version_no desc"
    _rec_name = "version_no"

    version_no = fields.Integer(string="Version", required=True)
    benchmark = fields.Selection(BENCHMARK_SELECTION, required=True)
    benchmark_amount = fields.Float(string="Base amount", digits=(18, 2), required=True)
    percentage = fields.Float(string="Percentage", digits=(5, 2), required=True)
    justification = fields.Text(required=True)
    performance_pct = fields.Float(string="Performance %", digits=(5, 2), required=True, default=75)
    performance_justification = fields.Text()
    trivial_pct = fields.Float(string="Clearly trivial %", digits=(5, 2), required=True, default=5)
    overall = fields.Float(string="Overall materiality", digits=(18, 0), required=True)
    performance = fields.Float(string="Performance materiality", digits=(18, 0), required=True)
    trivial = fields.Float(string="Clearly trivial threshold", digits=(18, 0), required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"), ("superseded", "Superseded")],
        string="Status", default="draft", required=True, index=True,
    )
    approved_by_id = fields.Many2one("res.users", string="Approved by", ondelete="restrict")
    approved_at = fields.Datetime()
    created_by_id = fields.Many2one("res.users", string="Created by", ondelete="restrict")
    is_latest = fields.Boolean(compute="_compute_is_latest", compute_sudo=True)

    _version_uniq = models.Constraint("UNIQUE(engagement_id, version_no)", "A version number is used once per engagement.")
    _one_approved = models.UniqueIndex(
        "(engagement_id) WHERE state = 'approved'", "Two materiality versions can never both be approved.",
    )

    def _compute_is_latest(self):
        for version in self:
            latest = self.sudo().search([("engagement_id", "=", version.engagement_id.id)], order="version_no desc", limit=1)
            version.is_latest = latest == version.sudo()

    def action_approve(self):
        """approveMateriality: requires-partner, then stale-version, then not-found."""
        self.ensure_one()
        engagement = self.sudo().engagement_id.with_env(self.env)
        engagement._ea_tool_guard()
        if not can_partner_signoff(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "requires-partner")
        engagement._ea_lock()
        as_root = self.sudo()
        Materiality = self.env["ea.audit.materiality"].sudo()
        latest = Materiality.search([("engagement_id", "=", as_root.engagement_id.id)], order="version_no desc", limit=1)
        if latest != as_root:
            raise rule_error(self.env, "stale-version")
        if as_root.state != "draft":
            raise rule_error(self.env, "not-found")
        Materiality.search([
            ("engagement_id", "=", as_root.engagement_id.id), ("state", "=", "approved"), ("id", "!=", as_root.id),
        ]).write({"state": "superseded"})
        as_root.write({"state": "approved", "approved_by_id": self.env.user.id, "approved_at": fields.Datetime.now()})
        engagement._ea_log("materiality.approved", "Materiality v%d approved" % as_root.version_no)
        engagement._ea_reflag_misstatements()
        engagement._ea_sync_significance()
        return True


class EngagementMateriality(models.Model):
    _inherit = "ea.audit.engagement"

    materiality_ids = fields.One2many("ea.audit.materiality", "engagement_id", string="Materiality versions")
    mat_overall_label = fields.Char(string="Overall materiality", compute="_compute_mat_cards", compute_sudo=True)
    mat_basis_label = fields.Char(compute="_compute_mat_cards", compute_sudo=True)
    mat_overall_note = fields.Char(compute="_compute_mat_cards", compute_sudo=True)
    mat_performance_label = fields.Char(string="Performance materiality", compute="_compute_mat_cards", compute_sudo=True)
    mat_performance_note = fields.Char(compute="_compute_mat_cards", compute_sudo=True)
    mat_trivial_label = fields.Char(string="Clearly trivial", compute="_compute_mat_cards", compute_sudo=True)
    mat_trivial_note = fields.Char(compute="_compute_mat_cards", compute_sudo=True)
    mat_umt_label = fields.Char(string="Uncorrected misstatement threshold", compute="_compute_mat_cards", compute_sudo=True)
    mat_status_label = fields.Char(string="Materiality status", compute="_compute_mat_cards", compute_sudo=True)
    mat_version_label = fields.Char(string="Version in force", compute="_compute_mat_cards", compute_sudo=True)
    mat_justification = fields.Text(string="Justification", compute="_compute_mat_cards", compute_sudo=True)
    mat_draft_pending = fields.Boolean(compute="_compute_mat_cards", compute_sudo=True)
    mat_bases_html = fields.Html(string="Bases", compute="_compute_mat_bases", compute_sudo=True, sanitize=False)
    mat_user_may_approve = fields.Boolean(compute="_compute_mat_user_may_approve")

    def _ea_approved_materiality(self):
        """The latest partner-approved thresholds: what the papers may cite."""
        self.ensure_one()
        return self.env["ea.audit.materiality"].sudo().search(
            [("engagement_id", "=", self.id), ("state", "=", "approved")], order="version_no desc", limit=1,
        )

    def _ea_materiality_dict(self):
        approved = self._ea_approved_materiality()
        if not approved:
            return None
        return {"overall": approved.overall, "performance": approved.performance, "trivial": approved.trivial}

    def _ea_tb_bases(self):
        return tb_benchmark_amounts(self._ea_tb_balances())

    def _compute_mat_cards(self):
        fr = is_french(self.env)
        for engagement in self:
            approved = engagement._ea_approved_materiality()
            latest = engagement.materiality_ids.sorted("version_no", reverse=True)[:1]
            shown = approved or latest
            engagement.mat_draft_pending = bool(latest and latest.state == "draft")
            engagement.mat_overall_label = fcfa(shown.overall) if shown else "—"
            engagement.mat_performance_label = fcfa(shown.performance) if shown else "—"
            engagement.mat_trivial_label = fcfa(shown.trivial) if shown else "—"
            engagement.mat_umt_label = fcfa(uncorrected_misstatement_threshold(
                {"overall": shown.overall, "performance": shown.performance},
            )) if shown else "—"
            engagement.mat_justification = shown.justification if shown else False
            if not shown:
                engagement.mat_overall_note = engagement.mat_performance_note = engagement.mat_trivial_note = self.env._("No materiality set yet (P6.1)")
                engagement.mat_basis_label = ""
                engagement.mat_status_label = self.env._("No version yet")
                engagement.mat_version_label = ""
                continue
            of_overall = self.env._("of overall materiality")
            # the base actually chosen: the total-assets label only beside a total-assets base (F013)
            engagement.mat_basis_label = (
                engagement.bilan_label if shown.benchmark == "total_assets" else benchmark_label(shown.benchmark, fr)
            )
            engagement.mat_overall_note = "%s %% %s" % (
                ("%g" % shown.percentage), benchmark_label(shown.benchmark, fr),
            )
            engagement.mat_performance_note = "%g %% %s (%d–%d %%)" % (
                shown.performance_pct, of_overall, PERFORMANCE_PCT_RANGE["min"], PERFORMANCE_PCT_RANGE["max"],
            )
            engagement.mat_trivial_note = "%g %% %s (%d–%d %%)" % (
                shown.trivial_pct, of_overall, TRIVIAL_PCT_RANGE["min"], TRIVIAL_PCT_RANGE["max"],
            )
            engagement.mat_version_label = "Version %d" % shown.version_no
            if approved:
                engagement.mat_status_label = self.env._("Approved, %(who)s, %(date)s", who=approved.approved_by_id.name, date=french_date(approved.approved_at))
            else:
                engagement.mat_status_label = self.env._("Awaiting partner approval")

    def _compute_mat_bases(self):
        fr = is_french(self.env)
        for engagement in self:
            bases = engagement._ea_tb_bases()
            if not bases:
                engagement.mat_bases_html = False
                continue
            approved = engagement._ea_approved_materiality() or engagement.materiality_ids.sorted("version_no", reverse=True)[:1]
            rows = []
            for code, _label in BENCHMARK_SELECTION:
                pct = midpoint(code)
                retained = approved and approved.benchmark == code
                if retained:
                    pct = approved.percentage
                threshold = compute_materiality(max(bases[code], 0), pct, 75, 5)["overall"]
                rows.append(Markup(
                    "<tr><td>{label}</td><td class='text-end'>{amount}</td><td class='text-end'>{pct}</td>"
                    "<td class='text-end'>{range}</td><td class='text-end'>{threshold}</td><td>{chip}</td></tr>"
                ).format(
                    label=benchmark_label(code, fr),
                    amount=grouped(bases[code]),
                    pct="%g" % pct,
                    range="%g–%g" % (BENCHMARK_RANGES[code]["min"], BENCHMARK_RANGES[code]["max"]),
                    threshold=grouped(threshold),
                    chip=Markup("<span class='o_ea_chip o_ea_chip_good'>{}</span>").format(self.env._("Retained")) if retained else "",
                ))
            engagement.mat_bases_html = Markup(
                "<table class='table o_ea_table'><thead><tr><th>{b}</th><th class='text-end'>{a}</th><th class='text-end'>%</th>"
                "<th class='text-end'>{r}</th><th class='text-end'>{t}</th><th>{k}</th></tr></thead><tbody>{rows}</tbody></table>"
            ).format(
                b=self.env._("Base"), a=self.env._("Amount"), r=self.env._("Range %"), t=self.env._("Threshold"),
                k=self.env._("Retained"), rows=Markup("").join(rows),
            )

    def _compute_mat_user_may_approve(self):
        allowed = can_partner_signoff(self.env.user._ea_firm_role())
        for engagement in self:
            engagement.mat_user_may_approve = allowed and engagement.sudo().mat_draft_pending

    def create_materiality_version(
        self, benchmark, benchmark_amount, percentage, justification, performance_pct=75,
        performance_justification=None, trivial_pct=5, override_justification=None,
    ):
        """createMaterialityVersion. No boilerplate default: a justification is written or refused."""
        self.ensure_one()
        self._ea_tool_guard()
        if benchmark not in BENCHMARK_RANGES:
            raise rule_error(self.env, "invalid-materiality")
        if not (justification or "").strip():
            raise rule_error(self.env, "justification-required")
        refusal = validate_version(benchmark_amount, percentage, performance_pct, trivial_pct)
        if refusal:
            raise rule_error(self.env, refusal)
        performance_reason = (performance_justification or "").strip()
        if performance_pct != PERFORMANCE_PCT_RANGE["default"] and not performance_reason:
            raise rule_error(self.env, "performance-justification-required")
        deviation = materiality_deviations(benchmark, benchmark_amount, percentage, self._ea_tb_bases())
        override = (override_justification or "").strip()
        if not override:
            if deviation["outOfRange"]:
                raise rule_error(self.env, "materiality-out-of-range")
            if deviation["basisMismatch"]:
                raise rule_error(self.env, "materiality-basis-mismatch")
        figures = compute_materiality(benchmark_amount, percentage, performance_pct, trivial_pct)
        self._ea_lock()
        Materiality = self.env["ea.audit.materiality"].sudo()
        last = Materiality.search([("engagement_id", "=", self.id)], order="version_no desc", limit=1)
        version_no = last.version_no + 1
        version = Materiality.create({
            "engagement_id": self.id,
            "version_no": version_no,
            "benchmark": benchmark,
            "benchmark_amount": benchmark_amount,
            "percentage": percentage,
            "justification": justification,
            "performance_pct": performance_pct,
            "performance_justification": " — ".join(part for part in (performance_reason, override) if part) or False,
            "trivial_pct": trivial_pct,
            "created_by_id": self.env.user.id,
            **figures,
        })
        approved_exists = bool(self._ea_approved_materiality())
        # The first version is created, not revised (UAT B121). A revision tells the
        # partner that what was computed under the prior figure needs review.
        self._ea_log(
            "materiality.created" if version_no == 1 else "materiality.revised",
            "Materiality v%d: overall %s, performance %s, trivial %s%s" % (
                version_no, figures["overall"], figures["performance"], figures["trivial"],
                " — items computed under the prior figure need review, and the new version needs approval" if approved_exists else "",
            ),
        )
        return version.with_env(self.env)

    def _ea_reflag_misstatements(self):
        """reflagMisstatements: the classification follows the new threshold, the evidence does not."""
        self.ensure_one()
        approved = self._ea_approved_materiality()
        if not approved:
            return {"nowReportable": 0, "nowTrivial": 0}
        items = self.env["ea.audit.misstatement"].sudo().search([("engagement_id", "=", self.id)])
        now_reportable = items.filtered(lambda m: m.trivial and abs(m.amount) >= approved.trivial)
        now_trivial = items.filtered(lambda m: not m.trivial and abs(m.amount) < approved.trivial)
        now_reportable.write({"trivial": False})
        now_trivial.write({"trivial": True})
        counts = {"nowReportable": len(now_reportable), "nowTrivial": len(now_trivial)}
        if now_reportable or now_trivial:
            self._ea_log(
                "materiality.reflagged",
                "Materiality revised: %d misstatement(s) became reportable, %d became clearly trivial" % (len(now_reportable), len(now_trivial)),
            )
        return counts

    def action_approve_latest_materiality(self):
        self.ensure_one()
        latest = self.env["ea.audit.materiality"].sudo().search(
            [("engagement_id", "=", self.id)], order="version_no desc", limit=1,
        )
        if not latest:
            raise rule_error(self.env, "not-found")
        latest.with_env(self.env).action_approve()
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_tool_materiality(self):
        return self._ea_board("ea_audit_tools.view_engagement_materiality_board", self.env._("Materiality"))

    def action_open_materiality_wizard(self):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Generate a materiality version"),
            "res_model": "ea.audit.materiality.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_engagement_id": self.id},
        }

    def action_export_materiality(self):
        return self._ea_export_action("materiality")

