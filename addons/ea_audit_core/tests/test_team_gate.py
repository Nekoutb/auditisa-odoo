"""Owner, 2026-11-17: the engagement team page no longer adds people to the firm, and a
partner opening a file for another partner is told they will not be on its team."""

from odoo.tests import tagged

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestTeamGate(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement(partner=self.partner)
        self.as_partner = self.engagement.with_user(self.partner)

    def test_the_invite_wizard_refuses_someone_not_in_the_firm(self):
        wizard = self.env["ea.audit.team.invite.wizard"].with_user(self.partner).create({
            "engagement_id": self.engagement.id, "email": "new.person@gov.example.com", "team_role": "staff",
        })
        self.assertCode("not-in-firm-yet", wizard.action_invite)
        self.assertFalse(self.env["res.users"].with_context(active_test=False).search(
            [("login", "=", "new.person@gov.example.com")]))

    def test_the_invite_wizard_still_invites_a_colleague(self):
        wizard = self.env["ea.audit.team.invite.wizard"].with_user(self.partner).create({
            "engagement_id": self.engagement.id, "email": self.staff.login, "team_role": "staff",
        })
        wizard.action_invite()
        member = self.Team.search([("engagement_id", "=", self.engagement.id), ("user_id", "=", self.staff.id)])
        self.assertEqual(member.state, "invited")

    def _wizard(self, creator, engagement_partner):
        return self.env["ea.audit.engagement.create.wizard"].with_user(creator).new({
            "client_id": self.client.id, "engagement_partner_id": engagement_partner.id,
        })

    def test_a_partner_choosing_another_partner_is_warned(self):
        warning = self._wizard(self.partner, self.partner2).partner_warning
        self.assertTrue(warning)
        self.assertIn(self.partner2.name, warning)
        self.assertIn("You will not be on this engagement's team", warning)

    def test_no_warning_when_the_partner_chooses_themself(self):
        self.assertFalse(self._wizard(self.partner, self.partner).partner_warning)

    def test_no_warning_for_someone_below_partner(self):
        self.assertFalse(self._wizard(self.manager, self.partner).partner_warning)
