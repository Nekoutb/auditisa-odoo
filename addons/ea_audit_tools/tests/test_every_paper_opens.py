"""Every paper opens on a real engagement with the tools installed, whichever hook it goes through.
P1.3 once crashed on opening, on all files, because a hook treated a text field as a selection."""
import json
import os

from odoo.modules.module import get_module_path
from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestEveryPaperOpens(ToolsCase):
    def _codes(self):
        folder = os.path.join(get_module_path("ea_audit_papers"), "data", "papers")
        names = [name for name in os.listdir(folder) if name.endswith(".json")]
        self.assertGreater(len(names), 50)
        for name in sorted(names):
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                yield json.load(handle).get("code") or name[:-5]

    def test_every_paper_opens_in_both_languages(self):
        self.approve()
        for code in self._codes():
            self.engagement.sudo()._ea_ensure_task(code)
        items = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id)])
        self.assertIn("P1.3", items.mapped("code"))
        for lang in ("en_US", "fr_FR"):
            for item in items.with_user(self.partner).with_context(lang=lang):
                with self.subTest(code=item.code, lang=lang):
                    self.assertTrue(item.get_paper_payload())

    def test_p13_shows_the_engagement_framework(self):
        self.engagement.sudo().framework = "SYSCOHADA"
        item = self.item(self.engagement, "P1.3")
        payload = item.with_user(self.partner).get_paper_payload()
        self.assertEqual(payload["auto_values"].get("framework"), "SYSCOHADA")

    def test_sampling_board_reads_on_several_engagements(self):
        other = self.make_engagement(year=2024)
        both = (self.engagement | other).sudo()
        both.invalidate_recordset()
        self.assertEqual(len(both.mapped("sampling_prerequisites_html")), 2)
