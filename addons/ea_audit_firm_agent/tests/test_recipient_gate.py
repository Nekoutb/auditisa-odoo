"""A practice space emails only the allowed addresses; with the platform address, replies go to the firm's contact."""

from odoo.tests import TransactionCase, tagged

from ..models.firm_agent import PARAM_MAIL_REPLY_TO
from ..models.ir_mail_server import PARAM_RECIPIENT_ALLOWLIST, PARAM_RECIPIENT_GATE


@tagged("post_install", "-at_install")
class TestRecipientGate(TransactionCase):
    def setUp(self):
        super().setUp()
        self.params = self.env["ir.config_parameter"].sudo()
        self.servers = self.env["ir.mail_server"].sudo()

    def _message(self, *to):
        return self.servers._build_email__("support@cab.cm-ea.com", list(to), "Subject", "Body")

    def test_a_firms_server_has_no_gate(self):
        message = self._message("anyone@exemple.cm")
        self.servers.send_email(message)
        self.assertIn("anyone@exemple.cm", message["To"])

    def test_a_practice_space_drops_and_logs_every_other_recipient(self):
        self.params.set_param(PARAM_RECIPIENT_GATE, "1")
        self.params.set_param(PARAM_RECIPIENT_ALLOWLIST, "owner@exemple.cm")
        message = self._message("owner@exemple.cm", "client@exemple.cm")
        with self.assertLogs("odoo.addons.ea_audit_firm_agent.models.ir_mail_server", "WARNING") as logs:
            self.servers.send_email(message)
        self.assertIn("owner@exemple.cm", message["To"])
        self.assertNotIn("client@exemple.cm", message["To"])
        self.assertIn("c***@exemple.cm", "\n".join(logs.output))
        self.assertNotIn("client@exemple.cm", "\n".join(logs.output))

    def test_an_empty_list_sends_nothing_at_all(self):
        self.params.set_param(PARAM_RECIPIENT_GATE, "1")
        message = self._message("owner@exemple.cm")
        with self.assertLogs("odoo.addons.ea_audit_firm_agent.models.ir_mail_server", "WARNING") as logs:
            self.servers.send_email(message)
        self.assertIsNone(message["To"])
        self.assertIn("not sent", "\n".join(logs.output))

    def test_replies_go_to_the_address_the_console_gave(self):
        self.assertEqual(self._message("a@exemple.cm")["Reply-To"], "support@cab.cm-ea.com")
        self.params.set_param(PARAM_MAIL_REPLY_TO, "awa@exemple.cm")
        self.assertEqual(self._message("a@exemple.cm")["Reply-To"], "awa@exemple.cm")
        other = self.servers._build_email__("support@cab.cm-ea.com", ["a@exemple.cm"], "S", "B", reply_to="z@exemple.cm")
        self.assertEqual(other["Reply-To"], "z@exemple.cm")

    def test_the_agent_keeps_the_reply_address_from_the_answer(self):
        agent = self.env["ea.firm.agent"]
        agent._apply_reply_to("awa@exemple.cm")
        self.assertEqual(self.params.get_param(PARAM_MAIL_REPLY_TO), "awa@exemple.cm")
        agent._apply_reply_to(None)
        self.assertEqual(self.params.get_param(PARAM_MAIL_REPLY_TO), "awa@exemple.cm", "an older console says nothing")
        agent._apply_reply_to("")
        self.assertFalse(self.params.get_param(PARAM_MAIL_REPLY_TO))
