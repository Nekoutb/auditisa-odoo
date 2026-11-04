"""Port of tests/lib/engagement-access.test.ts: F008 through ir.rule. The rules are
exercised by real ORM reads and writes, not by asking a helper for its opinion."""
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestTeamOnly(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.assigned = self.make_engagement(2025, partner=self.partner)
        self.item_e41 = self.item(self.assigned, "E4.1")
        self.seat(self.assigned, self.senior, "senior")

    def assertOutOfFile(self, user):
        engagements = self.Engagement.with_user(user)
        self.assertNotIn(self.assigned, engagements.search([]))
        with self.assertRaises(AccessError):
            self.assigned.with_user(user).read(["fiscal_year"])
        with self.assertRaises(AccessError):
            self.item_e41.with_user(user).read(["code"])
        self.assertFalse(self.env["ea.audit.file.item"].with_user(user).search([("engagement_id", "=", self.assigned.id)]))
        self.assertFalse(self.env["ea.audit.signoff"].with_user(user).search([("engagement_id", "=", self.assigned.id)]))
        self.assertFalse(self.env["ea.audit.planning.snapshot"].with_user(user).search([("engagement_id", "=", self.assigned.id)]))
        with self.assertRaises(AccessError):
            self.assigned.with_user(user).check_access("read")
        self.assertCode("not-on-this-engagement", self.assigned.with_user(user).acceptance_gates)

    def test_lets_an_accepted_member_in(self):
        for user in (self.partner, self.senior):
            self.assertEqual(self.assigned.with_user(user).read(["fiscal_year"])[0]["fiscal_year"], 2025)
            self.assertTrue(self.item_e41.with_user(user).read(["code"]))
            self.assertIn(self.assigned, self.Engagement.with_user(user).search([]))

    def test_keeps_a_colleague_out(self):
        self.assertOutOfFile(self.outsider)

    def test_keeps_a_firm_administrator_out_no_exception(self):
        self.assertOutOfFile(self.admin)

    def test_keeps_a_system_administrator_out(self):
        self.admin.group_ids = [(4, self.env.ref("base.group_system").id)]
        self.assertTrue(self.admin.has_group("base.group_system"))
        self.assertOutOfFile(self.admin)

    def test_keeps_a_partner_out(self):
        self.assertOutOfFile(self.partner2)

    def test_opens_a_file_with_no_team_to_nobody(self):
        self.vacate_team(self.assigned)
        for user in (self.admin, self.partner, self.senior):
            self.assertOutOfFile(user)

    def test_a_task_assignment_grants_nothing_without_a_team_row(self):
        self.item_e41.write({"assignee_id": self.outsider.id, "preparer_id": self.outsider.id})
        self.assertOutOfFile(self.outsider)

    def test_excludes_someone_who_declined(self):
        self.assigned.sudo()._ea_member(self.senior).state = "declined"
        self.assertOutOfFile(self.senior)
        self.assertFalse(self.env["ea.audit.team.member"].with_user(self.senior).search([("engagement_id", "=", self.assigned.id)]))

    def test_refuses_writes_as_well_as_reads(self):
        with self.assertRaises(AccessError):
            self.assigned.with_user(self.admin).check_access("write")
        self.assertCode("not-on-this-engagement", self.assigned.with_user(self.admin).write, {"name": "x"})
        self.assertCode("not-on-this-engagement", self.item_e41.with_user(self.admin).write, {"not_applicable": True})
        self.assertCode("not-on-this-engagement", self.assigned.with_user(self.admin).assign_team_member, self.admin.id, "partner")
        self.assertCode("not-on-this-engagement", self.assigned.with_user(self.admin).transfer_engagement_partner, self.admin.id, "director")
        self.assertCode("not-on-this-engagement", self.sign_as_admin)

    def sign_as_admin(self):
        return self.item_e41.with_user(self.admin).action_sign("preparer")

    def test_the_team_list_of_another_file_is_not_readable(self):
        members = self.env["ea.audit.team.member"].with_user(self.outsider)
        self.assertFalse(members.search([("engagement_id", "=", self.assigned.id)]))
        with self.assertRaises(AccessError):
            self.assigned.sudo()._ea_member(self.partner).with_user(self.outsider).read(["team_role"])

    def test_clients_stay_firm_level(self):
        self.assertTrue(self.client.with_user(self.reader).read(["name"]))
        self.assertTrue(self.client.with_user(self.outsider).write({"sector": "trade"}))
        with self.assertRaises(AccessError):
            self.client.with_user(self.reader).write({"sector": "trade"})

    def test_read_only_sees_the_file_it_is_on_and_changes_nothing(self):
        self.seat(self.assigned, self.reader, "staff")
        self.assertTrue(self.assigned.with_user(self.reader).read(["fiscal_year"]))
        self.assertCode("read-only-role", self.assigned.with_user(self.reader).write, {"name": "x"})
        self.assertCode("read-only-role", self.item_e41.with_user(self.reader).write, {"not_applicable": True})


@tagged("post_install", "-at_install")
class TestNothingBypassesTheEngine(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement(partner=self.partner)
        self.as_partner = self.engagement.with_user(self.partner)

    def test_no_group_forges_a_signature(self):
        item = self.item(self.engagement, "P1.1")
        with self.assertRaises(AccessError):
            self.env["ea.audit.signoff"].with_user(self.partner).create({
                "file_item_id": item.id, "role": "partner", "user_id": self.partner.id,
            })

    def test_a_signature_cannot_be_changed_or_deleted(self):
        self.seat(self.engagement, self.manager, "manager")
        self.sign(self.manager, self.engagement, "P1.1", "preparer")
        signature = self.item(self.engagement, "P1.1").signoff_ids.with_user(self.partner)
        with self.assertRaises(AccessError):
            signature.write({"role": "partner"})
        with self.assertRaises(AccessError):
            signature.unlink()

    def test_the_phase_is_not_written_directly(self):
        self.assertCode("forbidden", self.as_partner.write, {"phase": "planning"})

    def test_the_task_state_is_not_written_directly(self):
        item = self.item(self.engagement, "P1.1").with_user(self.partner)
        self.assertCode("forbidden", item.write, {"state": "signed"})

    def test_context_relaxes_nothing(self):
        spoofed = self.engagement.with_user(self.manager).with_context(
            bypass=True, ea_internal=True, active_test=False,
        )
        self.assertCode("not-on-this-engagement", spoofed.write, {"name": "x"})
        self.assertFalse(self.Engagement.with_user(self.manager).with_context(ea_internal=True).search([]))


@tagged("post_install", "-at_install")
class TestInvitation(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement(partner=self.partner, name="Access SA 2025")
        self.member = self.engagement.with_user(self.partner)._ea_invite_user(self.outsider, "senior").sudo()
        self.own = self.member.with_user(self.outsider)

    def test_sees_only_the_invitation_until_accepting(self):
        self.assertEqual(self.member.state, "invited")
        with self.assertRaises(AccessError):
            self.engagement.with_user(self.outsider).read(["fiscal_year"])
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.outsider).acceptance_gates)
        self.assertFalse(self.Engagement.with_user(self.outsider).search([]))
        visible = self.env["ea.audit.team.member"].with_user(self.outsider).search([("engagement_id", "=", self.engagement.id)])
        self.assertEqual(visible, self.member)
        facts = self.own.read(["team_role", "invitation_client_name", "invitation_engagement_name", "invitation_fiscal_year"])[0]
        self.assertEqual(facts["team_role"], "senior")
        self.assertEqual(facts["invitation_client_name"], "Governance SA")
        self.assertEqual(facts["invitation_engagement_name"], "Access SA 2025")
        self.assertEqual(facts["invitation_fiscal_year"], 2025)
        self.own.action_accept()
        self.assertEqual(self.member.state, "accepted")
        self.assertTrue(self.engagement.with_user(self.outsider).read(["fiscal_year"]))

    def test_an_invited_member_cannot_accept_by_writing_the_row(self):
        self.assertCode("forbidden", self.own.write, {"state": "accepted"})
        self.assertCode("forbidden", self.own.write, {"engagement_id": self.engagement.id})
        self.assertEqual(self.member.state, "invited")

    def test_an_invited_member_cannot_change_their_own_role(self):
        with self.assertRaises(AccessError):
            self.own.write({"team_role": "partner"})
        self.assertEqual(self.member.team_role, "senior")

    def test_only_the_invitee_answers(self):
        self.assertCode("not-found", self.member.with_user(self.partner).action_accept)
        self.assertEqual(self.member.state, "invited")

    def test_a_decline_needs_its_reason_and_reaches_the_trail(self):
        self.assertCode("reason-required", self.own.action_decline, "  ")
        self.own.action_decline("conflict of interest")
        self.assertEqual(self.member.state, "declined")
        self.assertEqual(self.member.decline_reason, "conflict of interest")
        self.assertIn("conflict of interest", "".join(self.engagement.sudo().message_ids.mapped("body")))
        self.assertFalse(self.env["ea.audit.team.member"].with_user(self.outsider).search([("id", "=", self.member.id)]))

    def test_someone_who_declined_may_be_invited_again(self):
        self.own.action_decline("too busy")
        again = self.engagement.with_user(self.partner)._ea_invite_user(self.outsider, "staff")
        self.assertEqual(again.sudo().state, "invited")
        self.assertEqual(again.sudo().team_role, "staff")
        self.assertCode("already-on-team", self.engagement.with_user(self.partner)._ea_invite_user, self.outsider, "staff")

    def test_only_a_team_manager_invites(self):
        self.seat(self.engagement, self.senior, "senior")
        self.assertCode("team-manager-only", self.engagement.with_user(self.senior)._ea_invite_user, self.manager, "staff")
        self.seat(self.engagement, self.manager, "manager")
        self.assertCode("partner-only-team-role", self.engagement.with_user(self.manager).assign_team_member, self.partner2.id, "partner")
        self.assertCode("partner-only-team-role", self.engagement.with_user(self.manager).remove_team_member, self.partner.id)

    def test_a_row_from_the_team_list_is_an_invitation_whatever_it_claims(self):
        member = self.env["ea.audit.team.member"].with_user(self.partner).create({
            "engagement_id": self.engagement.id, "user_id": self.staff.id, "team_role": "staff", "state": "accepted",
        })
        self.assertEqual(member.sudo().state, "invited")
        with self.assertRaises(AccessError):
            self.engagement.with_user(self.staff).read(["fiscal_year"])
