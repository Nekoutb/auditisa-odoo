"""Port of tests/lib/batch1-governance.test.ts (the F002 matrix, F004, F005)."""
import json
from datetime import date

from odoo.tests import tagged
from odoo.tools.misc import file_open

from odoo.addons.ea_audit_core.services.errors import MESSAGES
from odoo.addons.ea_audit_core.services.signoff_rules import (
    PARTNER_GATED,
    PARTNER_ONLY_APPROVAL,
    default_policy,
    default_require_partner_on,
    effective_task_rule,
    team_rank,
)
from odoo.addons.ea_audit_core.services.tool_fed import is_tool_fed_paper, tool_outputs_for

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestDefaultMatrix(EaAuditCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.codes = cls.env["ea.audit.task.template"].search([]).mapped("code")
        cls.policy = default_policy(cls.codes)
        with file_open("ea_audit_core/tests/data/default_matrix.json") as handle:
            cls.golden = json.load(handle)

    def rule(self, code):
        return effective_task_rule(self.policy, {}, code)

    def pr(self, code):
        rule = self.rule(code)
        return [rule["min_preparer"], rule["min_reviewer"], rule["partner_required"]]

    def test_every_code_matches_the_typescript_matrix(self):
        """default_matrix.json is effectiveTaskRule run over the 118 codes in Node."""
        self.assertEqual(sorted(self.golden["matrix"]), sorted(self.codes))
        for code, want in self.golden["matrix"].items():
            self.assertEqual(self.pr(code), [want["minPreparer"], want["minReviewer"], want["partnerRequired"]], code)
        self.assertEqual(self.policy["min_reviewer_role"], self.golden["minReviewerRole"])
        self.assertEqual(sorted(self.policy["require_partner_on"]), sorted(self.golden["requirePartnerOn"]))

    def test_each_family(self):
        for code in ("P1.3", "P2.1"):
            self.assertEqual(self.pr(code), ["manager", "partner", False])
        for code in ("P3.1", "P6.1", "S1.1", "S5.5", "C2.2", "C3.1", "E3.1", "E6.3", "E6.10"):
            self.assertEqual(self.pr(code), ["senior", "manager", False], code)
        for code in ("E1.2", "E4.20", "E6.9"):
            self.assertEqual(self.pr(code), ["staff", "senior", False], code)
        self.assertEqual(self.pr("C6.1"), ["manager", "partner", False])

    def test_partner_list(self):
        c5 = [c for c in self.codes if c.startswith("C5.")]
        self.assertTrue(c5)
        for code in c5:
            self.assertEqual(self.pr(code), ["manager", "partner", True], code)
        self.assertEqual(self.pr("P1.1"), ["manager", "partner", True])
        self.assertEqual(self.pr("S3.1"), ["senior", "manager", True])
        self.assertEqual(self.pr("C1.1"), ["senior", "manager", True])
        self.assertEqual(self.pr("C6.2"), ["manager", "partner", True])
        self.assertFalse(self.rule("C4.2")["partner_required"])
        required = default_require_partner_on(self.codes)
        for code in PARTNER_GATED | PARTNER_ONLY_APPROVAL:
            self.assertIn(code, required)
            self.assertTrue(self.rule(code)["partner_required"])

    def test_reviewer_never_below_preparer(self):
        for code in self.codes:
            rule = self.rule(code)
            self.assertGreaterEqual(team_rank(rule["min_reviewer"]), team_rank(rule["min_preparer"]), code)
        rules = {"E4.1": {"min_preparer": "manager", "min_reviewer": "senior", "partner_required": None}}
        self.assertEqual(effective_task_rule(self.policy, rules, "E4.1")["min_reviewer"], "manager")

    def test_policy_is_a_floor_and_an_addition_a_task_rule_the_override(self):
        policy = dict(self.policy, min_reviewer_role="director", require_partner_on=["E4.1"])
        self.assertEqual(effective_task_rule(policy, {}, "E4.1"), {
            "min_preparer": "staff", "min_reviewer": "director", "partner_required": True,
        })
        self.assertEqual(effective_task_rule(policy, {}, "P1.3")["min_reviewer"], "partner")
        emptied = dict(self.policy, require_partner_on=[])
        self.assertTrue(effective_task_rule(emptied, {}, "C5.2")["partner_required"])
        lifted = {"C5.2": {"min_preparer": None, "min_reviewer": None, "partner_required": False}}
        self.assertFalse(effective_task_rule(self.policy, lifted, "C5.2")["partner_required"])

    def test_tool_fed_mapping(self):
        self.assertEqual(tool_outputs_for("P6.1"), ("materiality",))
        self.assertEqual(tool_outputs_for("P6.2"), ("tb", "materiality"))
        self.assertEqual(tool_outputs_for("C1.1"), ("tb", "materiality", "sad"))
        self.assertEqual(tool_outputs_for("E4.1"), ("tb",))
        self.assertEqual(tool_outputs_for("E4.34"), ("tb",))
        for code in ("E4.35", "E4.36", "P3.1", "C4.2"):
            self.assertFalse(is_tool_fed_paper(code), code)

    def test_every_refusal_has_a_message(self):
        for code in (
            "tool-output-missing-materiality", "tool-output-missing-tb", "tool-output-missing-sad",
            "self-review", "last-partner", "one-engagement-partner", "partner-role-requires-partner-rank",
            "eqr-rank", "eqr-on-team", "eqr-cooling-off", "eqr-declaration-required", "preparer-equals-approver",
            "email-domain-not-allowed", "engagement-partner-required", "not-on-this-engagement",
            "role-below-task-minimum-staff", "role-below-task-minimum-senior", "role-below-task-minimum-manager",
            "role-below-task-minimum-senior-manager", "role-below-task-minimum-director",
            "role-below-task-minimum-partner", "designate-engagement-partner-first", "not-engagement-partner",
        ):
            self.assertIn(code, MESSAGES)


@tagged("post_install", "-at_install")
class TestMatrixEnforced(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement()
        self.set_phase(self.engagement, "execution")
        for user, role in ((self.manager, "manager"), (self.senior, "senior"), (self.staff, "staff")):
            self.seat(self.engagement, user, role)

    def test_the_fraud_paper(self):
        self.assertCode("role-below-task-minimum-senior", self.sign, self.staff, self.engagement, "E3.1", "preparer")
        self.sign(self.senior, self.engagement, "E3.1", "preparer")
        self.assertCode("role-below-task-minimum-manager", self.sign, self.senior, self.engagement, "E3.1", "reviewer")

    def test_the_ohada_papers(self):
        self.assertCode("role-below-task-minimum-manager", self.sign, self.senior, self.engagement, "C5.2", "preparer")
        self.sign(self.manager, self.engagement, "C5.2", "preparer")
        self.assertCode("role-below-task-minimum-partner", self.sign, self.manager, self.engagement, "C5.2", "reviewer")

    def _with_outputs(self, present):
        self.patch(
            type(self.env["ea.audit.file.item"]), "_ea_tool_output_present",
            lambda _self, output: output in present,
        )

    def test_tool_fed_papers_wait_for_their_tool(self):
        self.assertCode("tool-output-missing-tb", self.sign, self.senior, self.engagement, "P6.2", "preparer")
        self._with_outputs({"tb"})
        self.assertCode("tool-output-missing-materiality", self.sign, self.senior, self.engagement, "P6.2", "preparer")
        self._with_outputs(set())
        self.assertCode("tool-output-missing-materiality", self.sign, self.senior, self.engagement, "P6.1", "preparer")
        self.assertEqual(self.item(self.engagement, "P6.1").tool_outputs_missing, "tool-output-missing-materiality")
        self._with_outputs({"tb", "materiality"})
        self.assertCode("tool-output-missing-sad", self.sign, self.manager, self.engagement, "C1.1", "preparer")
        self._with_outputs({"tb", "materiality", "sad"})
        self.assertFalse(self.item(self.engagement, "C1.1").tool_outputs_missing)

    def test_the_lead_schedule_refuses_every_tier_without_a_tb(self):
        self._with_outputs({"tb"})
        self.assertEqual(self.sign(self.staff, self.engagement, "E4.1", "preparer"), "preparer")
        self._with_outputs(set())
        self.assertCode("tool-output-missing-tb", self.sign, self.senior, self.engagement, "E4.1", "reviewer")
        self.assertCode("tool-output-missing-tb", self.sign, self.partner, self.engagement, "E4.1", "partner")


@tagged("post_install", "-at_install")
class TestEqrEligibility(EaAuditCase):
    def setUp(self):
        super().setUp()
        for year, partner in ((2024, self.partner2), (2023, self.partner3), (2022, self.partner4)):
            self.make_engagement(year, partner=partner)
        self.engagement = self.make_engagement(2025)
        self.as_partner = self.engagement.with_user(self.partner)

    def appoint(self, user, declaration=False):
        return self.attempt(self.as_partner.assign_team_member, user.id, "eqr_reviewer", declaration)

    def test_requires_partner_rank_or_the_firm_role(self):
        self.assertEqual(self.appoint(self.outsider, True), "eqr-rank")
        self.assertEqual(self.appoint(self.admin), "eqr-declaration-required")

    def test_refuses_an_account_the_team_page_would_provision(self):
        code = self.attempt(self.as_partner.invite_team_member, "unknown-eqr@gov.example.com", "eqr_reviewer", None, True)
        self.assertEqual(code, "eqr-rank")
        self.assertFalse(self.env["res.users"].search([("login", "=", "unknown-eqr@gov.example.com")]))

    def test_refuses_a_member_of_the_team_in_another_role(self):
        self.assertEqual(self.appoint(self.partner, True), "eqr-on-team")
        self.seat(self.engagement, self.eqr, "eqr_reviewer")
        self.assertEqual(self.attempt(self.as_partner.assign_team_member, self.eqr.id, "staff"), "eqr-on-team")

    def test_refuses_the_partners_delegate(self):
        self.seat(self.engagement, self.admin, "director")
        self.as_partner.set_partner_delegate(self.admin.id)
        self.engagement.sudo()._ea_member(self.admin).unlink()
        self.assertEqual(self.appoint(self.admin, True), "eqr-on-team")

    def test_the_two_year_cooling_off(self):
        # partner on the 2024 file, and on the 2023 file (exactly two years: inclusive)
        self.assertEqual(self.appoint(self.partner2, True), "eqr-cooling-off")
        self.assertEqual(self.appoint(self.partner3, True), "eqr-cooling-off")
        # the 2022 file is outside the two years
        self.assertEqual(self.appoint(self.partner4), "eqr-declaration-required")

    def test_cooling_off_is_per_client(self):
        other_client = self.env["ea.audit.client"].create({"name": "Other SA"})
        other = self.make_engagement(2025, client=other_client)
        code = self.attempt(other.with_user(self.partner).assign_team_member, self.partner2.id, "eqr_reviewer", True)
        self.assertEqual(code, "ok")

    def test_an_invited_partner_on_the_prior_file_does_not_count(self):
        prior = self.env["ea.audit.team.member"].sudo().search([("user_id", "=", self.partner2.id)])
        prior.write({"state": "invited"})
        self.assertEqual(self.appoint(self.partner2, True), "ok")

    def test_needs_the_declaration_then_records_who_and_when(self):
        self.assertEqual(self.appoint(self.eqr), "eqr-declaration-required")
        self.assertEqual(self.appoint(self.eqr, False), "eqr-declaration-required")
        self.assertEqual(self.appoint(self.eqr, True), "ok")
        member = self.engagement.sudo()._ea_member(self.eqr)
        self.assertEqual(member.team_role, "eqr_reviewer")
        self.assertTrue(member.eqr_declared_at)
        self.assertEqual(member.eqr_declared_by_id, self.partner)

    def test_the_same_rules_bind_a_direct_create(self):
        members = self.env["ea.audit.team.member"].with_user(self.partner)
        self.assertCode(
            "eqr-declaration-required", members.create,
            {"engagement_id": self.engagement.id, "user_id": self.eqr.id, "team_role": "eqr_reviewer"},
        )
        member = members.create({
            "engagement_id": self.engagement.id, "user_id": self.eqr.id,
            "team_role": "eqr_reviewer", "eqr_declaration": True,
        })
        self.assertEqual(member.state, "invited")
        self.assertEqual(member.eqr_declared_by_id, self.partner)

    def test_the_eqr_signs_c42_alone_and_nothing_else(self):
        self.outputs_exist()
        self.set_phase(self.engagement, "execution")
        self.appoint(self.eqr, True)
        self.assertEqual(self.sign(self.eqr, self.engagement, "C4.2", "eqr"), "eqr")
        self.assertCode("forbidden", self.sign, self.eqr, self.engagement, "C4.2", "preparer")
        self.assertCode("forbidden", self.sign, self.eqr, self.engagement, "E4.1", "eqr")
        self.assertCode("eqr-own-paper", self.sign, self.partner, self.engagement, "C4.2", "eqr")
        item = self.item(self.engagement, "E4.1").with_user(self.eqr)
        self.assertCode("eqr-read-only", item.write, {"due_date": date(2026, 1, 1)})
        self.assertCode("eqr-read-only", item.assign_tasks, self.partner.id, "assignee")
        self.item(self.engagement, "C4.2").with_user(self.eqr).write({"due_date": date(2026, 1, 1)})
