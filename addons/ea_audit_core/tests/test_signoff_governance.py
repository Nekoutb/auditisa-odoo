"""Port of tests/lib/signoff-governance.test.ts (F001, F002, F003). The matrix
workbook half belongs to ea.audit.signoff.matrix.wizard, not in this milestone."""
from odoo.tests import tagged

from odoo.addons.ea_audit_core.services.signoff_rules import (
    below_minimum_code,
    default_policy,
    effective_task_rule,
    team_rank,
)

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestLadderAndRule(EaAuditCase):
    def test_the_six_level_ladder_keeps_the_eqr_off_it(self):
        ladder = ["staff", "senior", "manager", "senior_manager", "director", "partner"]
        self.assertEqual([team_rank(r) for r in ladder], list(range(6)))
        self.assertEqual(team_rank("eqr_reviewer"), -1)
        self.assertEqual(team_rank(None), -1)

    def test_falls_back_to_the_default_matrix(self):
        policy = self.Policy._ea_policy()
        self.assertFalse(policy["stored"])
        self.assertEqual(policy["min_reviewer_role"], "senior")
        self.assertFalse(policy["allow_sole_practitioner"])
        self.assertTrue(policy["require_distinct_preparer_approver"])
        self.assertEqual(self.Policy._ea_effective_rule("P1.1"), {
            "min_preparer": "manager", "min_reviewer": "partner", "partner_required": True,
        })
        self.assertFalse(self.Policy._ea_effective_rule("E4.1")["partner_required"])

    def test_task_rule_overrides_each_column(self):
        rules = {"E4.1": {"min_preparer": "senior", "min_reviewer": None, "partner_required": True}}
        policy = dict(default_policy(), min_reviewer_role="manager")
        self.assertEqual(effective_task_rule(policy, rules, "E4.1"), {
            "min_preparer": "senior", "min_reviewer": "manager", "partner_required": True,
        })

    def test_names_the_required_role(self):
        self.assertEqual(below_minimum_code("senior_manager"), "role-below-task-minimum-senior-manager")
        self.assertEqual(below_minimum_code("partner"), "role-below-task-minimum-partner")


class StaffedCase(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.outputs_exist()
        # the vitest fixture: the seat vacated, the administrator on the team as director
        self.engagement = self.make_engagement(partner=self.admin, actor=self.admin)
        self.other = self.make_engagement(2024, partner=self.admin, actor=self.admin)
        for engagement in (self.engagement, self.other):
            self.vacate_team(engagement)
            self.seat(engagement, self.admin, "director")
            self.set_phase(engagement, "execution")
        self.as_admin = self.engagement.with_user(self.admin)

    def staff_team(self):
        self.as_admin.assign_team_member(self.partner.id, "partner")
        self.as_admin.assign_team_member(self.manager.id, "manager")
        self.as_admin.assign_team_member(self.senior.id, "senior")
        self.as_admin.assign_team_member(self.staff.id, "staff")
        self.as_admin.assign_team_member(self.partner2.id, "director")


@tagged("post_install", "-at_install")
class TestOnePartner(StaffedCase):
    def test_keeps_the_seat_for_firm_partners_and_administrators(self):
        self.assertCode("partner-role-requires-partner-rank", self.as_admin.assign_team_member, self.manager.id, "partner")

    def test_designates_one_refuses_a_second_and_the_gate_follows(self):
        self.assertFalse(self.gate(self.engagement, "engagement_partner_designated"))
        self.as_admin.assign_team_member(self.partner.id, "partner")
        self.assertCode("one-engagement-partner", self.as_admin.assign_team_member, self.partner2.id, "partner")
        self.assertTrue(self.gate(self.engagement, "engagement_partner_designated"))

    def test_an_invited_partner_holds_the_seat_against_a_second(self):
        self.as_admin._ea_invite_user(self.partner, "partner")
        self.assertCode("one-engagement-partner", self.as_admin.assign_team_member, self.partner2.id, "partner")
        self.assertFalse(self.gate(self.engagement, "engagement_partner_designated"))

    def test_never_leaves_the_seat_empty_once_accepted(self):
        self.as_admin.assign_team_member(self.partner.id, "partner")
        self.assertCode("last-partner", self.as_admin.remove_team_member, self.partner.id)
        self.assertCode("last-partner", self.as_admin.assign_team_member, self.partner.id, "director")
        member = self.engagement.sudo()._ea_member(self.partner).with_user(self.admin)
        self.assertCode("last-partner", member.unlink)
        self.assertCode("last-partner", member.write, {"team_role": "director"})

    def test_removal_returns_tasks_and_the_delegation(self):
        self.staff_team()
        item = self.item(self.engagement, "E4.4").with_user(self.manager)
        item.assign_tasks(self.senior.id, "preparer")
        self.as_admin.remove_team_member(self.senior.id)
        self.assertFalse(item.sudo().preparer_id)
        self.engagement.with_user(self.partner).set_partner_delegate(self.partner2.id)
        self.as_admin.remove_team_member(self.partner2.id)
        self.assertFalse(self.engagement.sudo().partner_delegate_id)


@tagged("post_install", "-at_install")
class TestWhoSignsWhat(StaffedCase):
    def setUp(self):
        super().setUp()
        self.staff_team()

    def test_refuses_a_signer_who_is_not_an_accepted_member(self):
        member = self.engagement.sudo()._ea_member(self.staff)
        member.state = "invited"
        self.assertCode("not-on-this-engagement", self.sign, self.staff, self.engagement, "E4.1", "preparer")
        member.state = "declined"
        self.assertCode("not-on-this-engagement", self.sign, self.staff, self.engagement, "E4.1", "preparer")
        member.state = "accepted"
        self.assertEqual(self.sign(self.staff, self.engagement, "E4.1", "preparer"), "preparer")

    def test_never_lets_the_preparer_review_even_with_the_flag_stored(self):
        self.Policy.sudo().create({})
        self.env.flush_all()
        self.cr.execute("UPDATE ea_audit_signoff_policy SET allow_sole_practitioner = true")
        self.env.invalidate_all()
        self.assertTrue(self.Policy.sudo().search([]).allow_sole_practitioner)
        self.sign(self.senior, self.engagement, "E4.2", "preparer")
        self.assertCode("self-review", self.sign, self.senior, self.engagement, "E4.2", "reviewer")

    def test_a_partner_preparer_cannot_sign_as_partner(self):
        self.TaskRule.with_user(self.partner).save_task_rules([
            {"code": "E4.2", "min_preparer": None, "min_reviewer": None, "partner_required": True},
        ])
        self.sign(self.partner, self.engagement, "E4.2", "preparer")
        self.assertCode("self-review", self.sign, self.partner, self.engagement, "E4.2", "partner")
        self.assertCode("self-review", self.sign, self.partner, self.engagement, "E4.2", "reviewer")

    def test_the_task_minimum_reviewer_from_the_firm_rules(self):
        self.TaskRule.with_user(self.partner).save_task_rules([
            {"code": "E4.1", "min_preparer": None, "min_reviewer": "manager", "partner_required": None},
        ])
        self.sign(self.staff, self.engagement, "E4.1", "preparer")
        self.assertCode("role-below-task-minimum-manager", self.sign, self.senior, self.engagement, "E4.1", "reviewer")
        self.assertEqual(self.sign(self.manager, self.engagement, "E4.1", "reviewer"), "reviewer")
        self.assertEqual(self.item(self.engagement, "E4.1").state, "signed")

    def test_the_task_minimum_preparer(self):
        self.TaskRule.with_user(self.admin).save_task_rules([
            {"code": "E4.3", "min_preparer": "senior", "min_reviewer": None, "partner_required": None},
        ])
        self.assertCode("role-below-task-minimum-senior", self.sign, self.staff, self.engagement, "E4.3", "preparer")
        self.assertEqual(self.sign(self.senior, self.engagement, "E4.3", "preparer"), "preparer")

    def test_a_task_rule_of_three_defaults_is_deleted(self):
        rules = self.TaskRule.with_user(self.partner)
        rules.save_task_rules([{"code": "E4.3", "min_preparer": "senior", "min_reviewer": None, "partner_required": None}])
        self.assertEqual(rules.sudo().search_count([("code", "=", "E4.3")]), 1)
        rules.save_task_rules([{"code": "E4.3", "min_preparer": None, "min_reviewer": None, "partner_required": None}])
        self.assertEqual(rules.sudo().search_count([("code", "=", "E4.3")]), 0)

    def test_the_refusal_order_of_the_firm_floor(self):
        self.seat(self.engagement, self.reader, "staff")
        self.assertCode("read-only-role", self.sign, self.reader, self.engagement, "E4.1", "preparer")
        self.assertCode("requires-senior", self.sign, self.staff, self.engagement, "E4.1", "reviewer")
        self.assertCode("requires-partner", self.sign, self.manager, self.engagement, "E4.1", "partner")
        self.assertCode("forbidden", self.sign, self.staff, self.engagement, "E4.1", "boss")
        self.assertCode("preparer-first", self.sign, self.manager, self.engagement, "E4.1", "reviewer")
        self.sign(self.staff, self.engagement, "E4.1", "preparer")
        self.assertCode("already-signed", self.sign, self.staff, self.engagement, "E4.1", "preparer")
        self.sign(self.manager, self.engagement, "E4.1", "reviewer")
        self.assertCode("signed-locked", self.sign, self.partner2, self.engagement, "E4.1", "reviewer")


@tagged("post_install", "-at_install")
class TestEngagementPartnerSignature(StaffedCase):
    def setUp(self):
        super().setUp()
        self.staff_team()

    def test_holds_a_partner_required_paper_open_until_the_partner_signs(self):
        self.TaskRule.with_user(self.partner).save_task_rules([
            {"code": "E4.2", "min_preparer": None, "min_reviewer": None, "partner_required": True},
        ])
        self.sign(self.senior, self.engagement, "E4.2", "preparer")
        self.assertEqual(self.sign(self.manager, self.engagement, "E4.2", "reviewer"), "reviewer")
        self.assertNotEqual(self.item(self.engagement, "E4.2").state, "signed")
        self.assertCode("not-engagement-partner", self.sign, self.partner2, self.engagement, "E4.2", "partner")
        self.engagement.with_user(self.partner).set_partner_delegate(self.partner2.id)
        self.assertEqual(self.engagement.sudo().partner_delegate_id, self.partner2)
        self.assertEqual(self.sign(self.partner2, self.engagement, "E4.2", "partner"), "partner")
        self.assertEqual(self.item(self.engagement, "E4.2").state, "signed")

    def test_refuses_partner_sign_offs_until_a_partner_is_designated(self):
        self.seat(self.other, self.partner2, "director")
        self.assertCode("designate-engagement-partner-first", self.sign, self.partner2, self.other, "E4.1", "partner")

    def test_the_engagement_partner_pressing_r_is_recorded_as_partner(self):
        self.set_phase(self.engagement, "execution")
        self.sign(self.manager, self.engagement, "C1.1", "preparer")
        self.assertEqual(self.sign(self.partner, self.engagement, "C1.1", "reviewer"), "partner")

    def test_partner_only_approvals_refuse_anyone_else(self):
        self.sign(self.manager, self.engagement, "C1.1", "preparer")
        self.assertCode("partner-only", self.sign, self.manager, self.engagement, "C1.1", "reviewer")
        self.assertCode("not-engagement-partner", self.sign, self.partner2, self.engagement, "C1.1", "reviewer")

    def test_only_the_partner_or_an_administrator_delegates_or_transfers(self):
        as_manager = self.engagement.with_user(self.manager)
        self.assertCode("not-engagement-partner", as_manager.set_partner_delegate, False)
        self.assertCode("transfer-partner-forbidden", as_manager.transfer_engagement_partner, self.partner2.id, "director")

    def test_delegate_rules(self):
        as_partner = self.engagement.with_user(self.partner)
        self.assertCode("delegate-is-partner", as_partner.set_partner_delegate, self.partner.id)
        self.assertCode("delegate-requires-partner-rank", as_partner.set_partner_delegate, self.manager.id)
        self.assertCode("delegate-not-on-team", as_partner.set_partner_delegate, self.partner3.id)
        self.assertCode("not-engagement-partner", self.engagement.with_user(self.manager).write, {"partner_delegate_id": self.partner2.id})

    def test_transfers_the_seat_in_one_step(self):
        as_partner = self.engagement.with_user(self.partner)
        as_partner.set_partner_delegate(self.partner2.id)
        self.assertCode("partner-role-requires-partner-rank", as_partner.transfer_engagement_partner, self.manager.id, "director")
        self.assertCode("already-engagement-partner", as_partner.transfer_engagement_partner, self.partner.id, "director")
        self.assertCode("invalid-team-role", as_partner.transfer_engagement_partner, self.partner2.id, "partner")
        as_partner.transfer_engagement_partner(self.partner2.id, "director")
        engagement = self.engagement.sudo()
        self.assertEqual(engagement.engagement_partner_id, self.partner2)
        self.assertFalse(engagement.partner_delegate_id)
        self.assertEqual(engagement._ea_member(self.partner).team_role, "director")
        self.assertEqual(engagement._ea_member(self.partner2).team_role, "partner")
        self.assertIn("engagement_partner_transferred", "".join(engagement.message_ids.mapped("body")))


@tagged("post_install", "-at_install")
class TestAssignment(StaffedCase):
    def setUp(self):
        super().setUp()
        self.staff_team()
        self.e44 = self.item(self.engagement, "E4.4").with_user(self.manager)

    def test_refuses_the_same_person_as_preparer_and_approver(self):
        self.e44.assign_tasks(self.senior.id, "preparer")
        self.assertCode("preparer-equals-approver", self.e44.assign_tasks, self.senior.id, "approver")

    def test_the_same_rule_binds_a_direct_write(self):
        self.e44.write({"preparer_id": self.senior.id})
        self.assertCode("preparer-equals-approver", self.e44.write, {"approver_id": self.senior.id})
        self.assertCode("role-below-task-minimum-senior", self.e44.write, {"approver_id": self.staff.id})

    def test_refuses_an_approver_below_the_minimum_reviewer(self):
        self.e44.assign_tasks(self.senior.id, "preparer")
        self.assertCode("role-below-task-minimum-senior", self.e44.assign_tasks, self.staff.id, "approver")
        self.assertEqual(self.e44.assign_tasks(self.manager.id, "approver"), 1)
        self.TaskRule.with_user(self.admin).save_task_rules([
            {"code": "E4.3", "min_preparer": "senior", "min_reviewer": None, "partner_required": None},
        ])
        item = self.item(self.engagement, "E4.3").with_user(self.manager)
        self.assertCode("role-below-task-minimum-senior", item.assign_tasks, self.staff.id, "preparer")

    def test_a_firm_that_allows_it_has_one_person_prepare_and_approve(self):
        self.e44.assign_tasks(self.manager.id, "approver")
        self.assertCode("preparer-equals-approver", self.e44.assign_tasks, self.manager.id, "preparer")
        policy = self.Policy._ea_policy()
        self.Policy.with_user(self.admin).save_policy(policy["min_reviewer_role"], policy["require_partner_on"], False)
        self.assertEqual(self.e44.assign_tasks(self.manager.id, "preparer"), 1)

    def test_the_reviewer_is_still_refused_when_policy_allows_one_person(self):
        """Assignment may allow it; the signature never does (F001)."""
        policy = self.Policy._ea_policy()
        self.Policy.with_user(self.admin).save_policy(policy["min_reviewer_role"], policy["require_partner_on"], False)
        self.sign(self.manager, self.engagement, "E4.4", "preparer")
        self.assertCode("self-review", self.sign, self.manager, self.engagement, "E4.4", "reviewer")

    def test_refuses_someone_off_the_team_and_the_quality_reviewer(self):
        self.assertCode("not-found", self.e44.assign_tasks, self.outsider.id, "assignee")
        self.seat(self.engagement, self.eqr, "eqr_reviewer")
        self.assertCode("eqr-not-assignable", self.e44.assign_tasks, self.eqr.id, "assignee")


@tagged("post_install", "-at_install")
class TestPolicyEditors(StaffedCase):
    def test_refuses_a_manager_and_never_stores_the_exemption(self):
        rules = self.Policy.with_user(self.manager)
        self.assertCode("signoff-policy-partner-only", rules.save_policy, "staff", [], False)
        self.assertCode("signoff-policy-partner-only", rules.create, {})
        as_partner = self.Policy.with_user(self.partner2)
        as_partner.save_policy("manager", ["P1.1"], True)
        row = self.Policy.sudo().search([])
        self.assertEqual(row.min_reviewer_role, "manager")
        self.assertFalse(row.allow_sole_practitioner)
        row.with_user(self.partner2).write({"allow_sole_practitioner": True})
        self.assertFalse(row.allow_sole_practitioner)
        self.assertCode("unknown-task-code", as_partner.save_policy, "manager", ["Z9.9"], True)
        self.assertCode("invalid-team-role", as_partner.save_policy, "boss", [], True)
        self.assertCode(
            "unknown-task-code", self.TaskRule.with_user(self.partner2).save_task_rules,
            [{"code": "Z9.9", "min_preparer": None, "min_reviewer": None, "partner_required": None}],
        )
        self.assertCode(
            "invalid-team-role", self.TaskRule.with_user(self.partner2).save_task_rules,
            [{"code": "E4.1", "min_preparer": "boss", "min_reviewer": None, "partner_required": None}],
        )
