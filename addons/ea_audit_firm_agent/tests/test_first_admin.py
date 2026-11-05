import re
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

from ..controllers.first_admin import PARAM_EXPIRES, PARAM_HASH
from ..services.first_admin import token_hash

TOKEN = "A1b2C3d4" * 6
GOOD = "un mot de passe assez long"


@tagged("post_install", "-at_install")
class TestFirstAdmin(HttpCase):
    def setUp(self):
        super().setUp()
        self.params = self.env["ir.config_parameter"].sudo()
        self.params.set_param(PARAM_HASH, token_hash(TOKEN))
        self.params.set_param(PARAM_EXPIRES, fields.Datetime.to_string(fields.Datetime.now() + timedelta(hours=1)))
        self.url = f"/ea-firm/first-admin/{TOKEN}"

    def _post(self, password, confirmation=None, url=None):
        page = self.url_open(url or self.url)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        return self.url_open(
            url or self.url,
            data={"csrf_token": token, "password": password, "confirmation": confirmation or password},
            allow_redirects=False,
        )

    def test_the_link_shows_the_form_with_private_headers(self):
        page = self.url_open(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertIn('name="password"', page.text)
        self.assertEqual(page.headers.get("Referrer-Policy"), "no-referrer")
        self.assertEqual(page.headers.get("Cache-Control"), "no-store")

    def test_a_wrong_token_shows_no_form(self):
        page = self.url_open("/ea-firm/first-admin/" + "Z" * 48)
        self.assertNotIn('name="password"', page.text)
        self.assertIn("plus valable", page.text)

    def test_an_expired_link_shows_no_form(self):
        self.params.set_param(PARAM_EXPIRES, fields.Datetime.to_string(fields.Datetime.now() - timedelta(minutes=1)))
        self.assertNotIn('name="password"', self.url_open(self.url).text)

    def test_a_weak_password_is_refused_and_the_link_stays(self):
        answer = self._post("court")
        self.assertEqual(answer.status_code, 200)
        self.assertIn("12 caractères", answer.text)
        self.assertTrue(self.params.get_param(PARAM_HASH))

    def test_the_link_works_once_and_sets_the_password(self):
        answer = self._post(GOOD)
        self.assertIn(answer.status_code, (302, 303))
        self.assertFalse(self.params.get_param(PARAM_HASH))
        self.assertFalse(self.params.get_param(PARAM_EXPIRES))
        admin = self.env.ref("base.user_admin")
        self.env.invalidate_all()
        self.authenticate(admin.login, GOOD)
        self.assertNotIn('name="password"', self.url_open(self.url).text)

    def test_a_used_link_changes_no_password_when_posted_again(self):
        self._post(GOOD)
        page = self.url_open(self.url)
        self.assertIn("plus valable", page.text)

    def test_no_stored_hash_means_no_link_at_all(self):
        self.params.search([("key", "=", PARAM_HASH)]).unlink()
        self.assertNotIn('name="password"', self.url_open(self.url).text)
