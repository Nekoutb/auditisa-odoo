"""Each client firm's document-reading key, set from the console (owner's ruling of 2026-11-20).

The firm's server is never reached: the key goes in the signed answer to its next heartbeat, once, and its
answer comes back as a reference and one word. The key is in no table and no log: only its last four characters.
"""

import os
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..services import heartbeat, mail_handoff
from .common import PlatformCase

KEY = "sk-ant-api03-Cabinet-Key-For-Reading-7f3aQx9Z"


@tagged("post_install", "-at_install")
class TestFirmDocReading(PlatformCase):
    def setUp(self):
        super().setUp()
        self.folder = os.path.join(tempfile.mkdtemp(), "firm-mail")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.folder), ignore_errors=True)
        self.env["ir.config_parameter"].sudo().set_param(mail_handoff.FOLDER_PARAM, self.folder)

    def _files(self):
        return sorted(os.listdir(self.folder)) if os.path.isdir(self.folder) else []

    def _form(self, firm, user=None, key=KEY):
        return self.env["platform.firm.docr.wizard"].with_user(user or self.operator).create({"firm_id": firm.id, "docr_key": key})

    def _send(self, firm):
        with patch.object(type(self.env["platform.firm"]), "_docr_simulate_answer", lambda _self: None):
            self._form(firm).action_send()

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

    def test_the_form_keeps_the_key_out_of_the_database(self):
        firm = self._active_firm()
        form = self._form(firm)
        self.assertTrue(form.docr_key_kept)
        self.assertFalse(form.docr_key)
        self.assertEqual(self._files(), [mail_handoff.form_name(form._table, form.id)])
        self._assert_nowhere(KEY)
        form.unlink()
        self.assertEqual(self._files(), [])

    def test_the_key_goes_once_in_the_heartbeat_answer_then_the_answer_comes_back(self):
        firm = self._active_firm()
        self._send(firm)
        self.assertEqual((firm.docr_state, firm.docr_action, firm.docr_last4), ("waiting", "set", "7f3aQx9Z"[-4:]))
        self.assertEqual(self._files(), [mail_handoff.reading_name(firm.slug)])
        self._assert_nowhere(KEY)
        request = firm.sudo()._heartbeat_answer()["doc_reading_request"]
        self.assertEqual(request, {"ref": firm.docr_ref, "action": "set", "key": KEY})
        self.assertTrue(firm.docr_delivered_at)
        self.assertEqual(self._files(), [], "erased as it is handed over")
        self.assertNotIn("doc_reading_request", firm.sudo()._heartbeat_answer(), "once only")
        firm._simulate_heartbeat(doc_reading_ref=firm.docr_ref, doc_reading_result="refused")
        self.assertEqual(firm.docr_state, "refused")
        self._assert_nowhere(KEY)

    def test_an_answer_under_another_reference_changes_nothing(self):
        firm = self._active_firm()
        self._send(firm)
        firm.sudo()._heartbeat_answer()
        firm._simulate_heartbeat(doc_reading_ref="0" * 16, doc_reading_result="on")
        self.assertEqual(firm.docr_state, "waiting")

    def test_a_simulation_firm_answers_at_once_and_reports_its_use(self):
        firm = self._active_firm()
        self._form(firm).action_send()
        self.assertEqual(firm.docr_state, "on")
        firm._simulate_heartbeat(doc_reading_month="2026-11", doc_reading_documents=4, doc_reading_pages=19)
        self.assertEqual((firm.docr_month, firm.docr_documents, firm.docr_pages), ("2026-11", 4, 19))

    def test_test_and_remove_carry_no_key(self):
        firm = self._active_firm()
        self._form(firm).action_send()
        with patch.object(type(self.env["platform.firm"]), "_docr_simulate_answer", lambda _self: None):
            firm.with_user(self.operator).action_docr_test()
        self.assertEqual(firm.sudo()._heartbeat_answer()["doc_reading_request"], {"ref": firm.docr_ref, "action": "test"})
        with patch.object(type(self.env["platform.firm"]), "_docr_simulate_answer", lambda _self: None):
            firm.with_user(self.operator).action_docr_remove()
        self.assertEqual(firm.sudo()._heartbeat_answer()["doc_reading_request"]["action"], "remove")
        firm._simulate_heartbeat()
        self.assertEqual(firm.docr_state, "removed")

    def test_what_is_not_a_key_is_refused_and_nothing_is_sent(self):
        firm = self._active_firm()
        for wrong in ("short", "with spaces inside a long key value", ""):
            with self.assertRaises(UserError):
                self._form(firm, key=wrong or "x").action_send() if wrong else self.env["platform.firm.docr.wizard"].with_user(
                    self.operator).create({"firm_id": firm.id}).action_send()
        self.assertEqual(firm.docr_state, "none")

    def test_a_key_not_collected_in_time_is_erased(self):
        firm = self._active_firm()
        self._send(firm)
        firm.sudo().write({"docr_at": fields.Datetime.now() - timedelta(hours=7)})
        self.env["platform.firm"]._docr_expire()
        self.assertEqual(firm.docr_state, "expired")
        self.assertEqual(self._files(), [])

    def test_a_viewer_cannot_open_the_form(self):
        firm = self._active_firm()
        with self.assertRaises(AccessError):
            self._form(firm, user=self.viewer)

    def test_the_heartbeat_takes_the_new_figures(self):
        self.assertIn("doc_reading_result", heartbeat.FIGURES)
        self.assertTrue(heartbeat.FIGURES["doc_reading_last4"]("Qx9Z"))
        self.assertFalse(heartbeat.FIGURES["doc_reading_result"]("great"))
