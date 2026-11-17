"""The page an invitation or new-password link opens looks like AuditISA, not Odoo (2026-11-17)."""
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestLoginPages(HttpCase):
    def setUp(self):
        super().setUp()
        self.invited = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Invited Senior", "login": "invited.senior@pages.example.com",
            "email": "invited.senior@pages.example.com",
        })
        company = self.env.company
        self.firm_name = ("ea_display_name" in company and company.ea_display_name) or company.name

    def _open(self, signup_type):
        partner = self.invited.partner_id.sudo()
        partner.signup_prepare(signup_type=signup_type)
        url = partner._get_signup_url()
        response = self.url_open(url[url.index("/web/"):])
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_invitation_page(self):
        page = self._open("signup")
        self.assertIn("Set my password", page)
        self.assertIn("Choose your password to finish setting up your account.", page)
        self.assertIn(self.firm_name, page)
        self.assertNotIn("Powered by", page)
        self.assertNotIn("Already have an account?", page)
        self.assertNotIn("Use a Passkey", page)
        self.assertRegex(page, r'name="login"[^>]*readonly')

    def test_new_password_page(self):
        page = self._open("reset")
        self.assertIn("Save my new password", page)
        self.assertNotIn("Powered by", page)

    def test_sign_in_page(self):
        page = self.url_open("/web/login").text
        self.assertNotIn("Powered by", page)
        self.assertNotIn("Use a Passkey", page)
