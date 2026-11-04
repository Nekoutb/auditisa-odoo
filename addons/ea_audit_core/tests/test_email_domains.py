"""Port of tests/lib/f070-email-domains.test.ts."""


from odoo.tests import TransactionCase, tagged

from odoo.addons.ea_audit_core.services.email_domains import (
    InvalidDomainError,
    email_domain,
    email_domain_allowed,
    parse_domain_list,
)

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

    def test_an_empty_list_lets_any_domain_be_invited(self):
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

    def test_an_unknown_address_on_an_allowed_domain_gets_an_account_and_an_invitation(self):
        self._domains("eca.com")
        member = self.as_partner.invite_team_member("New.Person@ECA.com", "staff", "New Person").sudo()
        self.assertEqual(member.state, "invited")
        self.assertEqual(member.user_id.login, "new.person@eca.com")
        self.assertEqual(member.user_id.name, "New Person")
        self.assertEqual(member.user_id._ea_firm_role(), "staff")

    def test_the_partner_seat_is_not_provisioned(self):
        self.assertCode("partner-role-requires-partner-rank", self.as_partner.invite_team_member, "np@eca.com", "partner")
        self.assertFalse(self.env["res.users"].search([("login", "=", "np@eca.com")]))

    def test_invalid_address_and_already_on_team(self):
        self.assertCode("invalid-email", self.as_partner.invite_team_member, "not-an-email", "staff")
        self.assertCode("already-on-team", self.as_partner.invite_team_member, self.partner.login, "staff")

    def test_someone_outside_the_firm_is_never_attached(self):
        self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Stranger", "login": "stranger@x.example.com", "email": "stranger@x.example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.assertCode("email-taken", self.as_partner.invite_team_member, "stranger@x.example.com", "staff")

    def test_the_policy_form_field_is_the_firm_administrators(self):
        policy = self.Policy.with_user(self.admin).create({"allowed_email_domains": "ECA.com"})
        self.assertEqual(policy.allowed_email_domains, "eca.com")
        as_partner = policy.with_user(self.partner)
        self.assertCode("forbidden", as_partner.write, {"allowed_email_domains": "other.com"})
