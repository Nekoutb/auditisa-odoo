import os
import tempfile
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from ..models import access_log


@tagged("post_install", "-at_install")
class TestAccessLog(TransactionCase):
    def setUp(self):
        super().setUp()
        handle, self.path = tempfile.mkstemp(prefix="ea-access-")
        os.close(handle)
        self.addCleanup(os.unlink, self.path)
        patcher = patch.object(access_log, "LOG_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.model = self.env["ea.firm.access.log"]

    def _append(self, text):
        with open(self.path, "a", encoding="utf-8") as out:
            out.write(text)

    def test_new_lines_are_imported_once(self):
        self._append("2026-11-05T12:00:00Z ssh-login root 198.51.100.7\n")
        self.assertEqual(self.model._cron_import(), 1)
        self.assertEqual(self.model._cron_import(), 0)
        self._append("2026-11-05T13:00:00Z ssh-login root 198.51.100.7\n")
        self.assertEqual(self.model._cron_import(), 1)
        row = self.model.search([], limit=1)
        self.assertEqual(row.event, "ssh-login")
        self.assertEqual(row.source, "198.51.100.7")

    def test_a_line_being_written_waits_for_its_end(self):
        self._append("2026-11-05T12:00:00Z ssh-login root 198.51")
        self.assertEqual(self.model._cron_import(), 0)
        self._append(".100.7\n")
        self.assertEqual(self.model._cron_import(), 1)

    def test_malformed_lines_are_skipped(self):
        self._append("<script>alert(1)</script>\n2026-11-05T12:00:00Z ssh-login root 198.51.100.7\n")
        self.assertEqual(self.model._cron_import(), 1)

    def test_a_missing_file_is_quiet(self):
        with patch.object(access_log, "LOG_FILE", self.path + ".none"):
            self.assertEqual(self.model._cron_import(), 0)

    def test_rows_cannot_be_changed_or_removed(self):
        self._append("2026-11-05T12:00:00Z ssh-login root 198.51.100.7\n")
        self.model._cron_import()
        row = self.model.search([], limit=1)
        with self.assertRaises(AccessError):
            row.write({"event": "x"})
        with self.assertRaises(AccessError):
            row.unlink()

    def test_kept_and_collected_but_not_a_screen_of_the_firm(self):
        """Owner, 2026-11-07: no action or menu shows the log to the firm; the collection goes on."""
        self.assertFalse(self.env.ref("ea_audit_firm_agent.action_ea_firm_access_log", raise_if_not_found=False))
        self.assertFalse(self.env.ref("ea_audit_firm_agent.menu_ea_firm_access_log", raise_if_not_found=False))
        self.assertFalse(self.env["ir.actions.act_window"].search([("res_model", "=", "ea.firm.access.log")]))
        self.assertTrue(self.env.ref("ea_audit_firm_agent.cron_access_log").active)
        self._append("2026-11-05T12:00:00Z ssh-login root 198.51.100.7\n")
        self.assertEqual(self.model._cron_import(), 1)
