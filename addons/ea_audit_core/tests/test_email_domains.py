"""Port of tests/lib/f070-email-domains.test.ts."""


from odoo.tests import TransactionCase, tagged

from odoo.addons.ea_audit_core.services.email_domains import (
    InvalidDomainError,
    email_domain,
    email_domain_allowed,
    parse_domain_list,
)

from odoo.addons.ea_audit_core.services.errors import AuditRuleError

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestDomainRule(TransactionCase):
    def test_parses_lower_cased_and_de_duplicated(self):
        self.assertEqual(parse_domain_list("ECA.com\n@eca-cm.com, eca.com"), ["eca-cm.com", "eca.com"])
        self.assertEqual(parse_domain_list("  "), [])
        with self.assertRaises(InvalidDomainError):
            parse_domain_list("not a domain!")

    def test_matches_exactly_and_ignores_case(self):
        allowed = ["eca.com", "eca-cm.com"]
        self.assertEqual(email_domain("A.B@Eca.Com"), "eca.com")
        self.assertTrue(email_domain_allowed("someone@ECA.COM", allowed))
        self.assertTrue(email_domain_allowed("someone@eca-cm.com", allowed))
        self.assertFalse(email_domain_allowed("someone@audit.eca.com", allowed))
        self.assertFalse(email_domain_allowed("someone@eca.com.attacker.net", allowed))
        self.assertFalse(email_domain_allowed("someone@gmail.com", allowed))
        self.assertTrue(email_domain_allowed("someone@gmail.com", []))


@tagged("post_install", "-at_install")
class TestInvitations(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement(partner=self.partner)
        self.as_partner = self.engagement.with_user(self.partner)
        self.Company = self.env["res.company"]

    def _domains(self, raw):
        return self.Company.with_user(self.admin).ea_set_allowed_domains(raw)

    def test_the_list_is_the_firm_administrators(self):
        self.assertCode("forbidden", self.Company.with_user(self.partner).ea_set_allowed_domains, "eca.com")
        self.assertEqual(self.Company._ea_allowed_domains(), [])
        self.assertCode("invalid-email-domain", self._domains, "not a domain!")

    def _colleague(self, email, group="group_staff"):
        """The firm administrator adds people to the firm first (Users screen)."""
        return self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Colleague", "login": email, "email": email,
            "group_ids": [(6, 0, [self.env.ref("ea_audit_core.%s" % group).id])],
        })

    def test_an_empty_list_lets_any_domain_be_invited(self):
        self._colleague("free@any-domain.org")
        member = self.as_partner.invite_team_member("free@any-domain.org", "staff")
        self.assertEqual(member.sudo().state, "invited")

    def test_refuses_an_address_outside_the_list_provisioning_nothing(self):
        self.assertEqual(self._domains("eca.com\neca-cm.com"), ["eca-cm.com", "eca.com"])
        self.assertCode("email-domain-not-allowed", self.as_partner.invite_team_member, "intruder@gmail.com", "staff")
        self.assertCode("email-domain-not-allowed", self.as_partner.invite_team_member, "x@audit.eca.com", "staff")
        self.assertFalse(self.env["res.users"].search([("login", "in", ["intruder@gmail.com", "x@audit.eca.com"])]))

    def test_refuses_an_existing_firm_user_on_the_other_team_paths(self):
        self._domains("eca.com")
        off_domain = self.staff.id
        self.assertCode("email-domain-not-allowed", self.as_partner.assign_team_member, off_domain, "staff")
        self.assertCode("email-domain-not-allowed", self.as_partner._ea_invite_user, self.staff, "staff")
        self.assertCode("email-domain-not-allowed", self.as_partner.transfer_engagement_partner, self.partner2.id, "director")

    def test_re_roling_a_member_does_not_re_check(self):
        self.seat(self.engagement, self.staff, "staff")
        self._domains("eca.com")
        self.as_partner.assign_team_member(self.staff.id, "senior")
        self.assertEqual(self.engagement.sudo()._ea_member(self.staff).team_role, "senior")

    def test_an_unknown_address_is_refused_and_no_account_is_made(self):
        # owner, 2026-11-17: only the firm administrator adds people to the firm
        self._domains("eca.com")
        self.assertCode("not-in-firm-yet", self.as_partner.invite_team_member, "New.Person@ECA.com", "staff", "New Person")
        self.assertCode("not-in-firm-yet", self.as_partner.invite_team_member, "np@eca.com", "partner")
        self.assertFalse(self.env["res.users"].with_context(active_test=False).search(
            [("login", "in", ["new.person@eca.com", "np@eca.com"])]))

    def test_the_refusal_tells_who_adds_people(self):
        with self.assertRaises(AuditRuleError) as caught:
            self.as_partner.invite_team_member("nobody@eca.com", "staff")
        self.assertIn("Ask your firm administrator to add them first", str(caught.exception))

    def test_an_existing_colleague_is_still_invited(self):
        self._domains("eca.com")
        colleague = self._colleague("New.Person@eca.com")
        member = self.as_partner.invite_team_member("new.person@ECA.com", "staff").sudo()
        self.assertEqual(member.state, "invited")
        self.assertEqual(member.user_id, colleague)

    def test_an_archived_colleague_is_not_invited(self):
        colleague = self._colleague("gone@eca.com")
        colleague.active = False
        self.assertCode("not-in-firm-yet", self.as_partner.invite_team_member, "gone@eca.com", "staff")

    def test_invalid_address_and_already_on_team(self):
        self.assertCode("invalid-email", self.as_partner.invite_team_member, "not-an-email", "staff")
        self.assertCode("already-on-team", self.as_partner.invite_team_member, self.partner.login, "staff")

    def test_someone_outside_the_firm_is_never_attached(self):
        self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Stranger", "login": "stranger@x.example.com", "email": "stranger@x.example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.assertCode("not-in-firm-yet", self.as_partner.invite_team_member, "stranger@x.example.com", "staff")

    def test_the_policy_form_field_is_the_firm_administrators(self):
        policy = self.Policy.with_user(self.admin).create({"allowed_email_domains": "ECA.com"})
        self.assertEqual(policy.allowed_email_domains, "eca.com")
        as_partner = policy.with_user(self.partner)
        self.assertCode("forbidden", as_partner.write, {"allowed_email_domains": "other.com"})
