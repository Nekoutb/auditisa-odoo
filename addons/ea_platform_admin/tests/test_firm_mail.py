"""Each client firm's email, set from the console (owner's ruling of 2026-11-17).

The firm's server is never reached: the settings go in the signed answer to its next heartbeat, once,
and its answer comes back as a reference and one word. The password is in no table and no log.
"""

import os
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..services import mail_handoff
from .common import PlatformCase

PASSWORD = "Mot-de-passe-du-cabinet-7f3a"
MAILBOX = {
    "mail_preset": "microsoft365",
    "mail_host": "smtp.office365.com",
    "mail_port": 587,
    "mail_encryption": "starttls",
    "mail_user": "cabinet@exemple.cm",
    "mail_sender": "cabinet@exemple.cm",
}


@tagged("post_install", "-at_install")
class TestFirmMail(PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(tempfile.mkdtemp(), "firm-mail")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.folder), ignore_errors=True)
        self.env["ir.config_parameter"].sudo().set_param(mail_handoff.FOLDER_PARAM, self.folder)

    def _files(self):
        return sorted(os.listdir(self.folder)) if os.path.isdir(self.folder) else []

    def _form(self, firm, user=None, **changes):
        values = {"firm_id": firm.id, **MAILBOX, "mail_password": PASSWORD, **changes}
        return self.env["platform.firm.mail.wizard"].with_user(user or self.operator).create(values)

    def _send(self, firm):
        """As the real console does for a real firm: no simulated answer."""
        with patch.object(type(self.env["platform.firm"]), "_mail_simulate_answer", lambda _self: None):
            self._form(firm).action_save_and_test()

    def _assert_nowhere(self, needle):
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT table_name, column_name FROM information_schema.columns
             WHERE table_schema = 'public' AND data_type IN ('text', 'character varying', 'jsonb')
               AND (table_name LIKE 'platform\\_%%' OR table_name IN ('ir_config_parameter', 'mail_message'))
        """)
        for table, column in self.env.cr.fetchall():
            self.env.cr.execute(f'SELECT count(*) FROM "{table}" WHERE "{column}"::text LIKE %s', [f"%{needle}%"])  # noqa: S608
            self.assertEqual(self.env.cr.fetchone()[0], 0, f"found in {table}.{column}")
        for name in self._files():
            with open(os.path.join(self.folder, name), "rb") as handle:
                self.assertNotIn(needle.encode(), handle.read(), name)

    def test_the_form_keeps_the_password_out_of_the_database(self):
        firm = self._active_firm()
        form = self._form(firm)
        self.assertTrue(form.mail_password_kept)
        self.assertFalse(form.mail_password)
        self.assertEqual(self._files(), [mail_handoff.form_name(form._table, form.id)])
        self._assert_nowhere(PASSWORD)
        form.unlink()
        self.assertEqual(self._files(), [])

    def test_the_settings_go_once_in_the_heartbeat_answer_then_the_answer_comes_back(self):
        firm = self._active_firm()
        self._send(firm)
        self.assertEqual(firm.mail_request_state, "waiting")
        self.assertEqual(firm.mail_request_by, self.operator)
        self.assertEqual(firm.mail_request_summary, "smtp.office365.com:587 STARTTLS, cabinet@exemple.cm")
        self.assertEqual(self._files(), [mail_handoff.firm_name(firm.slug)])
        self._assert_nowhere(PASSWORD)
        answer = firm.sudo()._heartbeat_answer()
        request = answer["mail_request"]
        self.assertEqual(request["ref"], firm.mail_request_ref)
        self.assertEqual(request["action"], "set")
        self.assertEqual(request["password"], PASSWORD)
        self.assertEqual(request["from"], "cabinet@exemple.cm")
        self.assertEqual((request["host"], request["port"], request["encryption"]), ("smtp.office365.com", 587, "starttls"))
        self.assertTrue(firm.mail_request_delivered_at)
        self.assertEqual(self._files(), [], "erased as it is handed over")
        self.assertNotIn("mail_request", firm.sudo()._heartbeat_answer(), "once only")
        # The firm's server answers with the reference and one word.
        firm._simulate_heartbeat(mail_request_ref=firm.mail_request_ref, mail_request_result="login")
        self.assertEqual(firm.mail_request_state, "login")
        self.assertIn("refused the username or the password", firm.mail_request_message)
        self.assertIn("mot de passe", firm.with_context(lang="fr_FR").mail_request_message)
        log = firm.log_ids.mapped("action")
        self.assertIn("Email settings sent to the firm's server", log)
        self.assertIn("Email: the firm's server answered", log)
        self._assert_nowhere(PASSWORD)

    def test_an_answer_under_another_reference_changes_nothing(self):
        firm = self._active_firm()
        self._send(firm)
        firm.sudo()._heartbeat_answer()
        firm._simulate_heartbeat(mail_request_ref="0" * 16, mail_request_result="on")
        self.assertEqual(firm.mail_request_state, "waiting")

    def test_a_simulation_firm_answers_at_once(self):
        firm = self._active_firm()
        self._form(firm).action_save_and_test()
        self.assertEqual(firm.mail_request_state, "on")
        self.assertTrue(firm.mail_enabled)
        self.assertEqual(self._files(), [])
        firm.with_user(self.operator).action_mail_switch_off()
        self.assertEqual(firm.mail_request_state, "off")
        self.assertFalse(firm.mail_enabled)

    def test_switching_off_asks_without_any_setting(self):
        firm = self._active_firm()
        with patch.object(type(self.env["platform.firm"]), "_mail_simulate_answer", lambda _self: None):
            firm.with_user(self.operator).action_mail_switch_off()
        self.assertEqual(firm.sudo()._heartbeat_answer()["mail_request"], {"ref": firm.mail_request_ref, "action": "off"})

    def test_settings_are_checked_in_plain_words_and_nothing_is_sent(self):
        firm = self._active_firm()
        form = self._form(firm, mail_host="10.0.0.5", mail_port=22, mail_sender="pas une adresse")
        with self.assertRaises(UserError) as caught:
            form.action_save_and_test()
        for words in ("Server:", "Port:", "Sender address:"):
            self.assertIn(words, str(caught.exception))
        self.assertEqual(firm.mail_request_state, "none")
        self.assertNotIn("mail_request", firm.sudo()._heartbeat_answer())
        with self.assertRaisesRegex(UserError, "go together"):
            self._form(firm, mail_password=False).action_save_and_test()

    def test_the_form_reopens_on_what_was_last_sent_without_the_password(self):
        firm = self._active_firm()
        self._send(firm)
        again = self.env["platform.firm.mail.wizard"].with_user(self.operator).with_context(default_firm_id=firm.id).create({})
        self.assertEqual(again.mail_host, "smtp.office365.com")
        self.assertEqual(again.mail_preset, "microsoft365")
        self.assertEqual(again.mail_user, "cabinet@exemple.cm")
        self.assertFalse(again.mail_password_kept)

    def test_settings_not_collected_in_time_are_erased(self):
        firm = self._active_firm()
        self._send(firm)
        firm.sudo().mail_request_at = fields.Datetime.now() - timedelta(hours=7)
        self.env["platform.firm"]._cron_watch()
        self.assertEqual(firm.mail_request_state, "expired")
        self.assertEqual(self._files(), [])
        self.assertNotIn("mail_request", firm.sudo()._heartbeat_answer())

    def test_a_viewer_cannot_open_the_form(self):
        firm = self._active_firm()
        with self.assertRaises(AccessError):
            self._form(firm, user=self.viewer)

    def test_the_new_firm_form_s_email_step_is_optional(self):
        wizard = self._wizard("cabinet-n")
        for _screen in range(3):
            wizard.action_next()
        self.assertEqual(wizard.step, "email")
        wizard.action_next()
        self.assertEqual(wizard.step, "preflight")
        self.assertIn("later", wizard.preview_mail)
        wizard.action_back()
        self.assertEqual(wizard.step, "email")
        wizard.action_back()
        self.assertEqual(wizard.step, "addons")

    def test_the_new_firm_form_s_email_step_sends_when_the_firm_is_live(self):
        wizard = self._wizard("cabinet-m")
        for _screen in range(3):
            wizard.action_next()
        wizard.write({**MAILBOX, "mail_port": 25, "mail_password": PASSWORD})
        wizard.action_next()
        self.assertEqual(wizard.step, "preflight")
        self.assertIn("smtp.office365.com:25", wizard.preview_mail)
        self._assert_nowhere(PASSWORD)
        wizard.confirmed = True
        result = wizard.action_confirm()
        firm = self.env["platform.provision.job"].browse(result["res_id"]).firm_id
        self.assertEqual(firm.state, "active")
        self.assertEqual(firm.mail_request_state, "waiting")
        self.assertEqual(self._files(), [mail_handoff.firm_name(firm.slug)])
        firm._simulate_heartbeat()  # collects
        firm._simulate_heartbeat()  # answers
        self.assertEqual(firm.mail_request_state, "on")
        self.assertEqual(self._files(), [])

    def test_the_new_firm_form_refuses_half_filled_settings(self):
        wizard = self._wizard("cabinet-h")
        for _screen in range(3):
            wizard.action_next()
        wizard.write({"mail_host": "smtp.office365.com"})
        with self.assertRaisesRegex(UserError, "Sender address"):
            wizard.action_next()
