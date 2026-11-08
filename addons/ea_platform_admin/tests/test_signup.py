"""The control room has no public sign-up: its accounts are made by its administrator."""
from odoo.tests import HttpCase, tagged
from odoo.tools import convert_file


@tagged("post_install", "-at_install")
class TestNoPublicSignup(HttpCase):
    def test_sign_up_is_by_invitation_only(self):
        scope = self.env["ir.config_parameter"].sudo().get_param("auth_signup.invitation_scope")
        self.assertEqual(scope, "b2b")
        self.assertEqual(self.url_open("/web/signup", allow_redirects=False).status_code, 404)

    def test_an_update_closes_it_again(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("auth_signup.invitation_scope", "b2c")
        # what an update of the addon runs
        convert_file(self.env, "ea_platform_admin", "data/auth_signup.xml", {}, mode="update", noupdate=False)
        self.assertEqual(params.get_param("auth_signup.invitation_scope"), "b2b")
