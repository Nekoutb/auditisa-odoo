from email.message import EmailMessage
from unittest.mock import patch

from odoo.addons.base.models.ir_mail_server import IrMail_Server, MailDeliveryException
from odoo.tests import TransactionCase, tagged

from ..models.firm_agent import PARAM_MAIL_TESTED
from ..models.ir_mail_server import PARAM_MAIL_GATE, PARAM_RESET_PASSWORD


@tagged("post_install", "-at_install")
class TestMailGate(TransactionCase):
    def setUp(self):
        super().setUp()
        self.params = self.env["ir.config_parameter"].sudo()
        self.server = self.env["ir.mail_server"].sudo().create({
            "name": "Courrier du cabinet",
            "smtp_host": "smtp.example.invalid",
            "from_filter": "example.invalid",
        })

    def test_a_closed_gate_stops_every_message(self):
        self.params.set_param(PARAM_MAIL_GATE, "1")
        with self.assertRaises(MailDeliveryException):
            self.env["ir.mail_server"].send_email(EmailMessage())

    def test_a_closed_gate_opens_no_connection_but_the_test_may(self):
        self.params.set_param(PARAM_MAIL_GATE, "1")
        with patch.object(IrMail_Server, "_connect__", return_value="smtp") as connect:
            with self.assertRaises(MailDeliveryException):
                self.env["ir.mail_server"]._connect__(mail_server_id=self.server.id)
            connect.assert_not_called()
            testing = self.env["ir.mail_server"].with_context(ea_mail_gate_testing=True)
            self.assertEqual(testing._connect__(mail_server_id=self.server.id), "smtp")

    def test_a_firm_updated_from_an_older_release_loses_the_reset_link_while_closed(self):
        self.params.set_param(PARAM_MAIL_GATE, "1")
        self.params.set_param(PARAM_RESET_PASSWORD, "True")
        self.env["ea.firm.agent"]._cron_send_heartbeat()
        self.assertEqual(self.params.get_param(PARAM_RESET_PASSWORD), "False")
        self.params.set_param(PARAM_MAIL_TESTED, "1")
        self.params.set_param(PARAM_RESET_PASSWORD, "True")
        self.env["ea.firm.agent"]._cron_send_heartbeat()
        self.assertEqual(self.params.get_param(PARAM_RESET_PASSWORD), "True")

    def test_without_the_gate_nothing_changes(self):
        self.params.set_param(PARAM_MAIL_GATE, "0")
        self.assertFalse(self.server._ea_mail_gate_closed())

    def test_a_passed_test_opens_the_gate(self):
        self.params.set_param(PARAM_MAIL_GATE, "1")
        self.assertTrue(self.server._ea_mail_gate_closed())
        with patch.object(IrMail_Server, "test_smtp_connection", return_value=True):
            self.server.test_smtp_connection()
        self.assertEqual(self.params.get_param(PARAM_MAIL_TESTED), "1")
        self.assertFalse(self.server._ea_mail_gate_closed())
        self.assertEqual(self.params.get_param(PARAM_RESET_PASSWORD), "True")

    def test_a_failed_test_keeps_it_closed(self):
        self.params.set_param(PARAM_MAIL_GATE, "1")
        with patch.object(IrMail_Server, "test_smtp_connection", side_effect=ValueError("refused")), \
                self.assertRaises(ValueError):
            self.server.test_smtp_connection()
        self.assertTrue(self.server._ea_mail_gate_closed())

    def test_changing_the_settings_closes_it_again(self):
        self.params.set_param(PARAM_MAIL_GATE, "1")
        self.params.set_param(PARAM_MAIL_TESTED, "1")
        self.params.set_param(PARAM_RESET_PASSWORD, "True")
        self.server.write({"smtp_host": "other.example.invalid"})
        self.assertTrue(self.server._ea_mail_gate_closed())
        self.assertEqual(self.params.get_param(PARAM_RESET_PASSWORD), "False")

    def test_changing_the_name_keeps_it_open(self):
        self.params.set_param(PARAM_MAIL_GATE, "1")
        self.params.set_param(PARAM_MAIL_TESTED, "1")
        self.server.write({"name": "Autre nom"})
        self.assertFalse(self.server._ea_mail_gate_closed())
