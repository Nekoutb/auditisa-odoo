from odoo import api, fields, models

from ..rules import rule_error
from ..services.deficiency_model import FINDING_SEVERITIES, evaluate_b5, suggested_grade
from ..services.sad_model import SAD_TYPES
from .tool_record import fcfa

SEVERITY_SELECTION = [
    ("significant_deficiency", "Significant deficiency"),
    ("deficiency", "Deficiency"),
    ("observation", "Observation"),
]
LIKELIHOOD_SELECTION = [("remote", "Remote"), ("reasonably_possible", "Reasonably possible"), ("probable", "Probable")]
MAGNITUDE_SELECTION = [("inconsequential", "Inconsequential"), ("significant", "Significant"), ("material", "Material")]
ROUTE_SELECTION = [("b4", "Matter for attention"), ("c1", "Control deficiency"), ("b5", "Misstatement")]
MTYPE_SELECTION = [
    ("factual", "Factual"),
    ("judgmental", "Judgmental"),
    ("projected", "Projected"),
    ("classification", "Reclassification"),
    ("disclosure", "Disclosure"),
]


class Finding(models.Model):
    """The register (m14). A b5 finding is the register's line for its misstatement: the
    platform stored only the misstatement, and the mock-up lists both in one table."""

    _name = "ea.audit.finding"
    _inherit = ["ea.audit.tool.record"]
    _description = "Finding"
    _order = "number"
    _rec_name = "title"

    number = fields.Integer(string="No.", required=True, readonly=True)
    reference = fields.Char(string="Ref.", compute="_compute_reference")
    route = fields.Selection(ROUTE_SELECTION, string="Route", required=True, readonly=True)
    title = fields.Char(string="Finding", required=True, readonly=True)
    detail = fields.Text()
    severity = fields.Selection(SEVERITY_SELECTION, readonly=True)
    file_item_id = fields.Many2one("ea.audit.file.item", string="Paper", ondelete="set null", readonly=True)
    program_step_id = fields.Many2one("ea.audit.program.step", string="Program step", ondelete="set null", readonly=True)
    recommendation = fields.Text()
    management_response = fields.Text()
    status = fields.Selection([("open", "Open"), ("cleared", "Closed")], default="open", required=True, readonly=True)
    response = fields.Text(readonly=True)
    cleared_by_id = fields.Many2one("res.users", string="Cleared by", ondelete="restrict", readonly=True)
    cleared_at = fields.Datetime(readonly=True)
    created_by_id = fields.Many2one("res.users", string="Raised by", ondelete="restrict", readonly=True)
    misstatement_id = fields.Many2one("ea.audit.misstatement", ondelete="set null", readonly=True)
    amount = fields.Float(digits=(18, 0), related="misstatement_id.amount", string="Amount")
    state_label = fields.Char(string="State", compute="_compute_state_label")
    evaluation_ids = fields.One2many("ea.audit.deficiency.evaluation", "finding_id", string="ISA 265 evaluations")
    evaluation_id = fields.Many2one("ea.audit.deficiency.evaluation", compute="_compute_evaluation", compute_sudo=True, string="ISA 265 evaluation")
    communicated_on = fields.Date(compute="_compute_evaluation", compute_sudo=True, string="Communicated on")
    suggested_severity = fields.Selection(SEVERITY_SELECTION, compute="_compute_evaluation", compute_sudo=True, string="Suggested grade")

    _number_uniq = models.Constraint("UNIQUE(engagement_id, number)", "A finding number is used once per engagement.")

    @api.depends("number")
    def _compute_reference(self):
        for finding in self:
            finding.reference = "F-%02d" % finding.number

    @api.depends("status", "route", "misstatement_id.trivial")
    def _compute_state_label(self):
        for finding in self:
            if finding.route == "b5":
                finding.state_label = self.env._("Carried to C1.1")
            elif finding.status == "cleared":
                finding.state_label = self.env._("Closed")
            else:
                finding.state_label = self.env._("Open")

    @api.depends("evaluation_ids.communicated_on", "evaluation_ids.likelihood", "evaluation_ids.magnitude")
    def _compute_evaluation(self):
        for finding in self:
            evaluation = finding.evaluation_ids[:1]
            finding.evaluation_id = evaluation
            finding.communicated_on = evaluation.communicated_on
            finding.suggested_severity = evaluation.suggested_severity

    def _ea_user_write(self, vals):
        self._ea_only(vals, {"detail", "recommendation", "management_response"})
        self._ea_guard()
        self.sudo().write(vals)
        return True

    def clear(self, response):
        """clearFinding. A finding already cleared is refused, not silently ignored."""
        self.ensure_one()
        self._ea_guard()
        if not (response or "").strip():
            raise rule_error(self.env, "response-required")
        as_root = self.sudo()
        if as_root.status != "open":
            raise rule_error(self.env, "not-found")
        as_root.write({
            "status": "cleared", "response": response,
            "cleared_by_id": self.env.user.id, "cleared_at": fields.Datetime.now(),
        })
        return True

    def save_deficiency_evaluation(
        self, grade, likelihood=None, magnitude=None, accounts_assertions=None, management_aware=None,
        indicators=None, related_ids=(), aggregation_note=None, communicated_on=None, recipient=None,
    ):
        """saveDeficiencyEvaluation: the grade reached here IS the register's severity."""
        self.ensure_one()
        as_root = self.sudo()
        engagement = as_root.engagement_id.with_env(self.env)
        engagement._ea_require_write()
        if grade not in FINDING_SEVERITIES:
            raise rule_error(self.env, "invalid-severity")
        if (likelihood and likelihood not in dict(LIKELIHOOD_SELECTION)) or (magnitude and magnitude not in dict(MAGNITUDE_SELECTION)):
            raise rule_error(self.env, "invalid-severity-factor")
        try:
            communicated = fields.Date.to_date(communicated_on) if communicated_on else False
        except ValueError as error:
            raise rule_error(self.env, "invalid-date") from error
        recipient = (recipient or "").strip()
        if communicated and not recipient:
            raise rule_error(self.env, "recipient-required")
        engagement._ea_tool_guard()
        if as_root.route != "c1":
            raise rule_error(self.env, "not-found")
        related = self.browse(sorted({i for i in related_ids if i and i != as_root.id})).sudo()
        if len(related.exists()) != len(related) or any(
            f.engagement_id != as_root.engagement_id or f.route != "c1" for f in related.exists()
        ):
            raise rule_error(self.env, "related-finding-unknown")
        Evaluation = self.env["ea.audit.deficiency.evaluation"].sudo()
        found = Evaluation.search([("finding_id", "=", as_root.id)], limit=1)
        before = {"severity": as_root.severity, "grade": found.grade, "communicatedOn": found.communicated_on}
        values = {
            "likelihood": likelihood or False,
            "magnitude": magnitude or False,
            "accounts_assertions": (accounts_assertions or "").strip() or False,
            "management_aware": management_aware,
            "indicators": (indicators or "").strip() or False,
            "related_finding_ids": [(6, 0, related.ids)],
            "aggregation_note": (aggregation_note or "").strip() or False,
            "grade": grade,
            "communicated_on": communicated,
            "recipient": recipient or False,
            "updated_by_id": self.env.user.id,
        }
        if found:
            found.write(values)
        else:
            Evaluation.create({"engagement_id": as_root.engagement_id.id, "finding_id": as_root.id, **values})
        as_root.severity = grade
        engagement._ea_log(
            "deficiency_evaluated",
            "ISA 265 deficiency evaluated on C5.11: graded %s%s (was %s)" % (
                grade, ", communicated in writing on %s" % communicated if communicated else "", before["severity"],
            ),
        )
        return True

    def action_open_clear(self):
        return self.env["ea.audit.reason.wizard"]._ea_open("clear", self)

    def action_open_evaluation(self):
        self.ensure_one()
        evaluation = self.sudo().evaluation_id
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("ISA 265 evaluation"),
            "res_model": "ea.audit.deficiency.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_finding_id": self.id,
                "default_grade": evaluation.grade or self.severity,
                "default_likelihood": evaluation.likelihood,
                "default_magnitude": evaluation.magnitude,
                "default_accounts_assertions": evaluation.accounts_assertions,
                "default_management_aware": evaluation.management_aware,
                "default_indicators": evaluation.indicators,
                "default_aggregation_note": evaluation.aggregation_note,
                "default_communicated_on": evaluation.communicated_on,
                "default_recipient": evaluation.recipient,
                "default_related_finding_ids": [(6, 0, evaluation.related_finding_ids.ids)],
            },
        }


class DeficiencyEvaluation(models.Model):
    """The C5.11 grid: the severity reasoned out, and the written communication dated."""

    _name = "ea.audit.deficiency.evaluation"
    _inherit = ["ea.audit.tool.record"]
    _description = "ISA 265 deficiency evaluation"
    _rec_name = "finding_id"

    finding_id = fields.Many2one("ea.audit.finding", required=True, ondelete="cascade", index=True)
    likelihood = fields.Selection(LIKELIHOOD_SELECTION)
    magnitude = fields.Selection(MAGNITUDE_SELECTION)
    suggested_severity = fields.Selection(SEVERITY_SELECTION, compute="_compute_suggested", compute_sudo=True)
    accounts_assertions = fields.Text(string="Accounts and assertions exposed")
    management_aware = fields.Boolean(string="Management aware")
    indicators = fields.Text(string="ISA 265 A6-A7 indicators")
    related_finding_ids = fields.Many2many(
        "ea.audit.finding", "ea_audit_deficiency_related", "evaluation_id", "finding_id", string="Related deficiencies",
    )
    aggregation_note = fields.Text()
    grade = fields.Selection(SEVERITY_SELECTION, required=True)
    communicated_on = fields.Date()
    recipient = fields.Char()
    updated_by_id = fields.Many2one("res.users", string="Updated by", ondelete="restrict")

    _finding_uniq = models.Constraint("UNIQUE(finding_id)", "A deficiency has one evaluation.")

    @api.depends("likelihood", "magnitude")
    def _compute_suggested(self):
        for evaluation in self:
            evaluation.suggested_severity = suggested_grade(evaluation.likelihood, evaluation.magnitude) or False


class Misstatement(models.Model):
    """The C1.1 schedule: what the SAD and the b5 route post, and what the gates evaluate.
    The amount, description and accounts are evidence; a materiality change moves only ``trivial``."""

    _name = "ea.audit.misstatement"
    _inherit = ["ea.audit.tool.record"]
    _description = "Misstatement"
    _order = "id"
    _rec_name = "description"

    file_item_id = fields.Many2one("ea.audit.file.item", string="Paper", ondelete="set null", readonly=True)
    program_step_id = fields.Many2one("ea.audit.program.step", ondelete="set null", readonly=True)
    description = fields.Char(required=True, readonly=True)
    accounts = fields.Char(readonly=True)
    amount = fields.Float(digits=(18, 2), required=True, readonly=True)
    mtype = fields.Selection(MTYPE_SELECTION, string="Type", default="factual", required=True, readonly=True)
    corrected = fields.Boolean()
    trivial = fields.Boolean(string="Clearly trivial", readonly=True)
    created_by_id = fields.Many2one("res.users", string="Created by", ondelete="restrict", readonly=True)

    def _ea_user_write(self, vals):
        """setMisstatementCorrected: what the C1.1 evaluation turns on, so it is on the trail."""
        self._ea_only(vals, {"corrected"})
        self._ea_guard()
        for item in self.sudo():
            if item.corrected != bool(vals["corrected"]):
                item.corrected = bool(vals["corrected"])
                item.engagement_id._ea_log(
                    "misstatement.%s" % ("corrected" if vals["corrected"] else "uncorrected"), item.description,
                )
        return True


class EngagementFinding(models.Model):
    _inherit = "ea.audit.engagement"

    finding_ids = fields.One2many("ea.audit.finding", "engagement_id", string="Findings")
    misstatement_ids = fields.One2many("ea.audit.misstatement", "engagement_id", string="Misstatements")
    b5_uncorrected_label = fields.Char(string="Uncorrected misstatements", compute="_compute_finding_cards", compute_sudo=True)
    b5_uncorrected_note = fields.Char(compute="_compute_finding_cards", compute_sudo=True)
    b5_exceeds = fields.Boolean(compute="_compute_finding_cards", compute_sudo=True)
    finding_significant_count = fields.Integer(string="Significant deficiencies", compute="_compute_finding_cards", compute_sudo=True)
    finding_uncommunicated_count = fields.Integer(compute="_compute_finding_cards", compute_sudo=True)
    finding_open_count = fields.Integer(string="Open findings", compute="_compute_finding_cards", compute_sudo=True)
    finding_total_count = fields.Integer(compute="_compute_finding_cards", compute_sudo=True)

    def _ea_evaluate_b5(self):
        self.ensure_one()
        items = self.env["ea.audit.misstatement"].sudo().search([("engagement_id", "=", self.id)])
        return evaluate_b5(
            [{"amount": item.amount, "corrected": item.corrected, "trivial": item.trivial} for item in items],
            self._ea_materiality_dict(),
        )

    def _ea_uncommunicated_significant_count(self):
        """ISA 265 para 9, what the archive gate reads. Graded significant and never evaluated counts too."""
        self.ensure_one()
        findings = self.env["ea.audit.finding"].sudo().search([
            ("engagement_id", "=", self.id), ("route", "=", "c1"), ("severity", "=", "significant_deficiency"),
        ])
        return len(findings.filtered(lambda f: not f.evaluation_id.communicated_on))

    def _compute_finding_cards(self):
        for engagement in self:
            result = engagement._ea_evaluate_b5()
            engagement.b5_uncorrected_label = fcfa(result["uncorrectedTotal"])
            engagement.b5_exceeds = bool(result["exceedsMateriality"])
            if result["finalMateriality"] is None:
                engagement.b5_uncorrected_note = self.env._("Not evaluable: materiality is not approved")
            elif result["exceedsMateriality"]:
                engagement.b5_uncorrected_note = self.env._("Above the threshold (%(umt)s)", umt=fcfa(result["finalMateriality"]))
            else:
                engagement.b5_uncorrected_note = self.env._("Below the threshold (%(umt)s)", umt=fcfa(result["finalMateriality"]))
            findings = engagement.finding_ids
            engagement.finding_significant_count = len(findings.filtered(lambda f: f.severity == "significant_deficiency"))
            engagement.finding_uncommunicated_count = engagement._ea_uncommunicated_significant_count()
            engagement.finding_open_count = len(findings.filtered(lambda f: f.status == "open"))
            engagement.finding_total_count = len(findings)

    def _ea_next_finding_number(self):
        self._ea_lock()
        last = self.env["ea.audit.finding"].sudo().search([("engagement_id", "=", self.id)], order="number desc", limit=1)
        return last.number + 1

    def route_finding(
        self, route, title, detail=None, severity=None, recommendation=None, file_item=None, program_step=None,
        amount=None, accounts=None, mtype="factual", trivial_confirmed=False, significant=False,
    ):
        """routeFinding: b4, c1, b5, or revise. Returns the destination."""
        self.ensure_one()
        self._ea_tool_guard()
        title = (title or "").strip()
        if not title:
            raise rule_error(self.env, "title-required")
        if file_item and file_item.sudo().engagement_id != self.sudo():
            raise rule_error(self.env, "not-found")
        values = {
            "engagement_id": self.id,
            "title": title,
            "detail": detail or False,
            "file_item_id": file_item.id if file_item else False,
            "program_step_id": program_step.id if program_step else False,
            "created_by_id": self.env.user.id,
        }
        Finding = self.env["ea.audit.finding"].sudo()
        if route in ("b4", "c1"):
            grade = severity if severity in FINDING_SEVERITIES else False
            if route == "c1" and not grade:
                raise rule_error(self.env, "invalid-severity")
            finding = Finding.create({
                **values, "number": self._ea_next_finding_number(), "route": route, "severity": grade,
                "recommendation": (recommendation or "").strip() or False,
            })
            return {"destination": route, "finding": finding.with_env(self.env)}
        if route == "b5":
            if not amount:
                raise rule_error(self.env, "amount-required")
            if mtype not in SAD_TYPES:
                raise rule_error(self.env, "invalid-type")
            materiality = self._ea_materiality_dict()
            is_trivial = bool(materiality) and abs(amount) < materiality["trivial"]
            if is_trivial and not trivial_confirmed:
                raise rule_error(self.env, "trivial-confirm-required")
            misstatement = self.env["ea.audit.misstatement"].sudo().create({
                "engagement_id": self.id,
                "file_item_id": file_item.id if file_item else False,
                "program_step_id": program_step.id if program_step else False,
                "description": title, "accounts": accounts or False, "amount": amount, "mtype": mtype,
                "trivial": is_trivial, "created_by_id": self.env.user.id,
            })
            finding = Finding.create({
                **values, "number": self._ea_next_finding_number(), "route": "b5", "misstatement_id": misstatement.id,
            })
            self.env["ea.audit.sad.entry"].sudo().create({
                "engagement_id": self.id, "file_item_id": file_item.id if file_item else False,
                "misstatement_id": misstatement.id, "register_only": True, "finding": title,
                "dr_amount": amount, "mtype": mtype, "posted": True,
            })
            return {"destination": "b5-trivial" if is_trivial else "b5", "finding": finding.with_env(self.env)}
        if route == "revise":
            # A dated risk appended after planning, for the partner to re-approve (spec 8.4).
            risk = self.env["ea.audit.risk"].sudo().create({
                "engagement_id": self.id, "description": title, "source": "Revise-approach (execution)",
                "significant": bool(significant), "added_after_planning": True, "created_by_id": self.env.user.id,
            })
            if file_item:
                self.env["ea.audit.risk.section"].sudo().create({
                    "engagement_id": self.id, "risk_id": risk.id, "file_item_id": file_item.id,
                })
            self._ea_log("risk-addition", "Risk added during execution, approval required: %s" % (detail or title))
            return {"destination": "risk", "risk": risk.with_env(self.env)}
        raise rule_error(self.env, "invalid-value")

    def action_tool_findings(self):
        return self._ea_board("ea_audit_tools.view_engagement_findings_board", self.env._("Findings"))

    def action_tool_deficiencies(self):
        return self._ea_list(
            "ea.audit.finding", self.env._("ISA 265 deficiencies"),
            [("ea_audit_tools.view_finding_list", "list"), ("ea_audit_tools.view_finding_form", "form")],
            {"domain": [("engagement_id", "=", self.id), ("route", "=", "c1")]},
        )

    def action_open_finding_wizard(self):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("New finding"),
            "res_model": "ea.audit.finding.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_engagement_id": self.id},
        }

    def action_export_findings(self):
        return self._ea_export_action("findings")
