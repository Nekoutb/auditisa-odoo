"""One look for figures on every screen of the firm (owner, 2026-11-15)."""
import re

from odoo.modules.module import get_manifest
from odoo.tests import TransactionCase, tagged
from odoo.tools import file_open


@tagged("post_install", "-at_install")
class TestGridLook(TransactionCase):
    def test_one_stylesheet_gives_every_table_the_grid(self):
        self.assertIn("ea_audit_ui/static/src/scss/grid.scss", get_manifest("ea_audit_ui")["assets"]["web.assets_backend"])
        with file_open("ea_audit_ui/static/src/scss/grid.scss") as handle:
            style = handle.read()
        for needle in ("#dfe3e6", "#f3f5f6", "#e6f2ed", "tabular-nums", "o_group_header", ".o_ea_table", ".ea-ts-grid", ".ea-table"):
            self.assertIn(needle, style)
        self.assertIn("$ea-grid-figure-size: 13px;", style)
        self.assertNotIn("monospace", style)

    def test_no_screen_sets_its_own_font_on_figures(self):
        for path in ("ea_audit_tools/static/src/scss/tools.scss", "ea_audit_timesheet/static/src/scss/timesheet.scss"):
            with file_open(path) as handle:
                style = handle.read()
            self.assertFalse(re.search(r"\.o_ea_table th \{[^}]*font-size", style), path)
            self.assertNotIn("monospace", style.split("o_ea_tile_code")[0], path)

    def test_amount_widget_is_on_fcfa_amounts(self):
        arch = self.env.ref("ea_audit_tools.view_tb_version_list").arch
        self.assertIn('name="total_debit" widget="ea_amount"', arch)
