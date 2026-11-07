import json
import os
import tempfile
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models import addon_switch


@tagged("post_install", "-at_install")
class TestSwitchFile(TransactionCase):
    """What reads the approved list. The sample add-on's tests cover what it does to a feature."""

    def _apply(self, content):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "approved.json")
            if content is not None:
                with open(path, "w", encoding="ascii") as out:
                    out.write(content)
            with patch.object(addon_switch, "APPROVED_FILE", path):
                self.env["ea.addon.switch"]._cron_apply()

    def test_no_file_changes_nothing(self):
        before = self.env["ea.addon.switch"]._codes_on()
        self._apply(None)
        self.assertEqual(self.env["ea.addon.switch"]._codes_on(), before)

    def test_a_malformed_file_changes_nothing(self):
        before = self.env["ea.addon.switch"]._codes_on()
        self._apply("{not json")
        self.assertEqual(self.env["ea.addon.switch"]._codes_on(), before)

    def test_a_base_module_named_in_the_list_gets_no_switch(self):
        self._apply(json.dumps({"on": ["ea_audit_addons", "base", "ea_audit_reports"]}))
        names = self.env["ea.addon.switch"].sudo().search([]).mapped("code")
        self.assertNotIn("ea_audit_addons", names)
        self.assertNotIn("base", names)
        self.assertNotIn("ea_audit_reports", names)

    def test_an_ordinary_user_cannot_read_or_change_a_switch(self):
        model = self.env["ir.model.access"].sudo().search([("model_id.model", "=", "ea.addon.switch")])
        self.assertEqual(model.mapped("perm_write"), [False])
        self.assertEqual(model.group_id, self.env.ref("base.group_system"))
