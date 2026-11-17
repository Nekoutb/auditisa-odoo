"""The user manual is built in: its client action, the top bar's "? Help" button, and the pages it opens."""
import json

from odoo.modules.module import get_manifest
from odoo.tests import tagged
from odoo.tools import file_open

from odoo.addons.ea_audit_core.tests.common import EaAuditCase


def _read(path):
    with file_open(path) as handle:
        return handle.read()


@tagged("post_install", "-at_install")
class TestHelp(EaAuditCase):
    def test_the_client_action_is_declared(self):
        action = self.env.ref("ea_audit_ui.action_help")
        self.assertEqual(action._name, "ir.actions.client")
        self.assertEqual(action.tag, "ea_audit_ui.help")
        self.assertEqual(action.name, "User manual")
        script = _read("ea_audit_ui/static/src/js/help.js")
        self.assertIn('registry.category("actions").add("ea_audit_ui.help", EaHelp)', script)
        self.assertIn('static template = "ea_audit_ui.Help"', script)
        self.assertIn('t-name="ea_audit_ui.Help"', _read("ea_audit_ui/static/src/xml/help.xml"))
        assets = get_manifest("ea_audit_ui")["assets"]["web.assets_backend"]
        for path in ("ea_audit_ui/static/src/js/**/*", "ea_audit_ui/static/src/xml/**/*", "ea_audit_ui/static/src/scss/help.scss"):
            self.assertIn(path, assets)

    def test_the_top_bar_has_the_help_button(self):
        template = _read("ea_audit_ui/static/src/xml/shell.xml")
        bar = template.split('t-name="ea_audit_ui.TopBar"')[1].split("</header>")[0]
        self.assertIn('data-ea="help"', bar)
        self.assertIn('t-on-click="openHelp"', bar)
        script = _read("ea_audit_ui/static/src/js/top_bar.js")
        self.assertIn('tag: "ea_audit_ui.help"', script)
        self.assertIn("helpKeys(controller)", script)

    def test_every_page_of_the_index_ships_in_both_languages(self):
        index = json.loads(_read("ea_audit_ui/static/manual/index.json"))
        self.assertGreater(len(index["pages"]), 40)
        for page in index["pages"]:
            for lang in ("en", "fr"):
                self.assertIn('data-id="%s"' % page["id"], _read("ea_audit_ui/static/manual/%s/%s.html" % (lang, page["id"])))

    def test_a_tool_board_names_its_view_for_the_help(self):
        engagement = self.make_engagement(2025, partner=self.partner, nature="statutory_audit")
        action = engagement.with_user(self.partner).action_tool_materiality()
        self.assertEqual(action["context"]["ea_help_view"], "ea_audit_tools.view_engagement_materiality_board")
        self.assertEqual(action["context"]["ea_engagement_id"], engagement.id)
        index = json.loads(_read("ea_audit_ui/static/manual/index.json"))
        pages = [p["id"] for p in index["pages"] if "view:ea_audit_tools.view_engagement_materiality_board" in p["screens"]]
        self.assertEqual(pages, ["materiality"])
