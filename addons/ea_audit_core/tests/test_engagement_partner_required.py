"""Port of tests/lib/engagement-partner-required.test.ts."""
from datetime import date

from odoo.tests import tagged

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestPartnerRequired(EaAuditCase):
    def _count(self):
        return self.Engagement.sudo().search_count([])

    def _seats(self, engagement):
        seats = engagement.sudo().team_member_ids.filtered(lambda m: m.team_role == "partner")
        return [(m.user_id, m.state) for m in seats]

    def _vals(self, year=2030, **extra):
        return {"client_id": self.client.id, "fiscal_year": year, "period_end": date(year, 12, 31), **extra}

    def test_refuses_a_file_without_a_partner(self):
        before = self._count()
        engagements = self.Engagement.with_user(self.admin)
        self.assertCode("engagement-partner-required", engagements.create, self._vals())
        self.assertCode("engagement-partner-required", engagements.create, self._vals(engagement_partner_id=False))
        self.assertEqual(self._count(), before)

    def test_refuses_a_partner_below_rank_and_opens_nothing(self):
        before = self._count()
        engagements = self.Engagement.with_user(self.admin)
        self.assertCode(
            "partner-role-requires-partner-rank", engagements.create,
            self._vals(engagement_partner_id=self.manager.id),
        )
        # someone who is not a member of the firm holds no rank in it
        stranger = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Stranger", "login": "stranger@other.example.com", "email": "stranger@other.example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.assertCode(
            "partner-role-requires-partner-rank", engagements.create,
            self._vals(engagement_partner_id=stranger.id),
        )
        self.assertEqual(self._count(), before)

    def test_seats_one_accepted_partner_and_meets_the_gate(self):
        engagement = self.make_engagement(2031, partner=self.partner, actor=self.admin)
        self.assertEqual(self._seats(engagement), [(self.partner, "accepted")])
        self.assertTrue(self.gate(engagement, "engagement_partner_designated"))

    def test_seats_the_partner_alongside_a_manager_who_opens_the_file(self):
        engagement = self.make_engagement(2032, partner=self.partner, actor=self.manager)
        self.assertEqual(self._seats(engagement), [(self.partner, "accepted")])
        team = {m.user_id: m.team_role for m in engagement.sudo().team_member_ids}
        self.assertEqual(team, {self.manager: "manager", self.partner: "partner"})

    def test_an_administrator_opening_for_another_partner_is_not_seated(self):
        engagement = self.make_engagement(2033, partner=self.partner, actor=self.admin)
        self.assertEqual(engagement.sudo().team_member_ids.user_id, self.partner)

    def test_an_administrator_may_take_the_seat(self):
        engagement = self.make_engagement(2033, partner=self.admin, actor=self.admin)
        self.assertEqual(self._seats(engagement), [(self.admin, "accepted")])

    def test_the_read_only_role_opens_nothing(self):
        self.assertCode(
            "read-only-role", self.Engagement.with_user(self.reader).create,
            self._vals(engagement_partner_id=self.partner.id),
        )

    def test_the_wizard_opens_the_file_for_another_partner(self):
        """The whole path of the UI, with a creator who may not read the file back."""
        wizard = self.env["ea.audit.engagement.create.wizard"].with_user(self.admin).create({
            "client_id": self.client.id, "fiscal_year": 2034, "period_end": date(2034, 12, 31),
            "engagement_partner_id": self.partner.id,
        })
        action = wizard.action_create()
        engagement = self.Engagement.sudo().search([("fiscal_year", "=", 2034)])
        self.assertEqual(len(engagement), 1)
        # Owner ruling 2026-11-15: the firm administrator looks at every file but changes none,
        # so the file opens look-only instead of a "you cannot read it" notice.
        self.assertEqual((action["type"], action.get("res_id")), ("ir.actions.act_window", engagement.id))

    def test_the_wizard_opens_the_form_for_the_partner_seated(self):
        wizard = self.env["ea.audit.engagement.create.wizard"].with_user(self.partner).create({
            "client_id": self.client.id, "fiscal_year": 2035, "period_end": date(2035, 12, 31),
            "engagement_partner_id": self.partner.id,
        })
        # owner's rulings of 2026-11-15: the profile questionnaire opens right after creation
        self.assertEqual(wizard.action_create()["res_model"], "ea.audit.engagement.profile")

    def test_the_wizard_refuses_a_missing_partner(self):
        wizard = self.env["ea.audit.engagement.create.wizard"].with_user(self.admin).create({
            "client_id": self.client.id, "fiscal_year": 2036, "period_end": date(2036, 12, 31),
        })
        self.assertCode("engagement-partner-required", wizard.action_create)

    def test_rollforward_carries_the_accepted_partner(self):
        source = self.make_engagement(2034, partner=self.partner)
        target = source.with_user(self.partner).rollforward(2035)
        self.assertEqual(self._seats(target), [(self.partner, "accepted")])
        self.assertEqual(target.sudo().period_end, date(2035, 12, 31))
        self.assertTrue(self.gate(target, "engagement_partner_designated"))

    def test_rollforward_refuses_a_file_with_no_accepted_partner(self):
        source = self.make_engagement(2036, partner=self.partner)
        self.seat(source, self.admin, "director")
        as_admin = source.with_user(self.admin)
        self.env["ea.audit.team.member"].sudo().search([
            ("engagement_id", "=", source.id), ("user_id", "=", self.partner.id),
        ]).unlink()
        before = self._count()
        self.assertCode("engagement-partner-required", as_admin.rollforward, 2037)
        # an invited (not yet accepted) partner does not carry over either
        self.seat(source, self.partner, "partner", state="invited")
        self.assertCode("engagement-partner-required", as_admin.rollforward, 2037)
        self.assertEqual(self._count(), before)

    def test_rollforward_needs_a_later_year(self):
        source = self.make_engagement(2034, partner=self.partner)
        self.assertCode("invalid-year", source.with_user(self.partner).rollforward, 2034)

    def test_rollforward_refuses_someone_off_the_team(self):
        source = self.make_engagement(2034, partner=self.partner)
        self.assertCode("look-only", source.with_user(self.admin).rollforward, 2035)
