from datetime import timedelta
from email.message import EmailMessage

from odoo import fields
from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.tests import HttpCase, TransactionCase, tagged

from ..controllers.first_admin import PARAM_EXPIRES, PARAM_HASH
from ..models.ir_mail_server import PARAM_MAIL_GATE
from ..services.first_admin import token_hash

TOKEN = "A1b2C3d4" * 6


@tagged("post_install", "-at_install")
class TestFirstAdminLanguage(HttpCase):
    def setUp(self):
        super().setUp()
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"].search([("name", "=", "ea_audit_firm_agent")])._update_translations(["fr_FR"])
        params = self.env["ir.config_parameter"].sudo()
        params.set_param(PARAM_HASH, token_hash(TOKEN))
        params.set_param(PARAM_EXPIRES, fields.Datetime.to_string(fields.Datetime.now() + timedelta(hours=1)))

    def _page_as(self, lang):
        self.env.company.partner_id.sudo().lang = lang
        self.env.flush_all()
        return self.url_open(f"/ea-firm/first-admin/{TOKEN}").text

    def test_the_page_follows_the_firms_language(self):
        self.assertIn("Welcome", self._page_as("en_US"))
        self.assertIn("Bienvenue", self._page_as("fr_FR"))


@tagged("post_install", "-at_install")
class TestMailGateLanguage(TransactionCase):
    def test_the_closed_mail_message_follows_the_language(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.config_parameter"].sudo().set_param(PARAM_MAIL_GATE, "1")
        with self.assertRaisesRegex(MailDeliveryException, "Messagerie"):
            self.env["ir.mail_server"].with_context(lang="fr_FR").send_email(EmailMessage())
        with self.assertRaisesRegex(MailDeliveryException, "Mail closed"):
            self.env["ir.mail_server"].with_context(lang="en_US").send_email(EmailMessage())
