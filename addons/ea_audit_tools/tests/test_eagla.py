"""The Data bank and EAGLA (owner's mock-ups of 18/11/2026): the renamed tiles and their actions,
the correlations and SCOT identification read from a projected ledger."""
from odoo.tests import tagged

from odoo.addons.ea_audit_tools.services import data_bank

from .common import to_bytes
from .test_analyzers import AR, AR_MAP
from .test_gl_console import ConsoleCase


@tagged("post_install", "-at_install")
class TestDataBankAndEagla(ConsoleCase):
    def tile(self, xmlid):
        return self.env.ref("ea_audit_tools.%s" % xmlid).with_user(self.staff).with_context(ea_engagement_id=self.engagement.id)

    def test_the_tiles_are_renamed(self):
        self.assertEqual(self.tile("tile_data_analytics").name, "Data bank")
        self.assertEqual(self.tile("tile_gl_console").name, "EAGLA")
        self.assertEqual(self.tile("tile_gl_console").method, "action_tool_eagla")
        action = self.as_staff.action_tool_data_analytics()
        self.assertEqual(action["name"], "Data bank")
        tiles = self.env["ea.audit.tool.tile"].with_user(self.staff).with_context(ea_engagement_id=self.engagement.id).search(action["domain"])
        self.assertEqual(tiles.mapped("code"), [tile[0] for tile in data_bank.TILES])
        self.assertEqual(tiles.mapped("name"), [tile[2] for tile in data_bank.TILES])
        for code in ("an-bank", "an-supplier", "an-financial", "an-analytics", "an-ipe"):
            self.assertNotIn(code, tiles.mapped("code"))
        self.assertFalse(hasattr(self.engagement, "action_tool_bank") or hasattr(self.engagement, "action_tool_supplier"))

    def test_each_tile_says_what_was_uploaded(self):
        receivables = self.tile("tile_an_ar")
        self.assertEqual(receivables.upload_chip, "Not uploaded")
        self.assertFalse(receivables.uploaded)
        self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(AR), mapping=AR_MAP)
        receivables.invalidate_recordset(["upload_chip", "uploaded"])
        self.assertEqual(receivables.upload_chip, "1 file: Pre-audit")
        self.assertTrue(receivables.uploaded)
        # the general ledger of the console case is there already
        self.assertTrue(self.tile("tile_an_gl").upload_chip.startswith("1 file"))
        # a hub tile carries no chip
        self.assertFalse(self.tile("tile_materiality").upload_chip)

    def test_the_upload_choice_leaves_out_bank_and_supplier_statements(self):
        kinds = dict(self.env["ea.audit.import.wizard"]._fields["kind"]._description_selection(self.env))
        self.assertNotIn("bank_statement", kinds)
        self.assertNotIn("supplier_statements", kinds)
        self.assertIn("payroll_register", kinds)
        form = self.env["ea.audit.dataset"].with_user(self.staff).get_view(self.env.ref("ea_audit_tools.view_dataset_form").id)
        self.assertNotIn("action_open_supplier_recon", form["arch"])

    def test_eagla_opens_on_the_ledger_in_use_or_without_one(self):
        action = self.tile("tile_gl_console").action_open_tool()
        self.assertEqual((action["res_model"], action["name"]), ("ea.audit.gl.console", "EAGLA"))
        console = self.env["ea.audit.gl.console"].with_user(self.staff).browse(action["res_id"])
        self.assertEqual(console.dataset_id.id, self.dataset_id)
        self.assertEqual(console.action_eagla_financial()["res_model"], "ea.audit.fa.ratio")
        self.assertEqual(console.action_eagla_analytical()["res_model"], "ea.audit.engagement")
        self.env["ea.audit.dataset"].sudo().browse(self.dataset_id).superseded_at = "2026-01-01 00:00:00"
        empty = self.env["ea.audit.gl.console"].with_user(self.staff).browse(self.as_staff.action_tool_eagla()["res_id"])
        self.assertFalse(empty.dataset_id)
        self.assertFalse(empty.head_html)

    def test_the_left_pane_lists_thirty_two_analyses(self):
        console = self.console()
        keys = [key for key, _label in console._analytic_selection()]
        self.assertEqual(len(keys), 32)
        self.assertEqual(keys[-2:], ["two-way-correlation", "three-way-correlation"])
        view = self.env["ea.audit.gl.console"].with_user(self.staff).get_view(self.env.ref("ea_audit_tools.view_gl_console_form").id)
        for name in ("action_eagla_financial", "action_eagla_analytical", "action_scot", "action_run_two_way", "action_run_three_way"):
            self.assertIn(name, view["arch"])
        self.assertIn("EAGLA™", view["arch"])

    def test_two_way_and_three_way(self):
        result = self.as_staff.eagla_two_way(self.dataset_id, "701", "411")
        self.assertEqual((result["numerator"][0], result["denominator"][0]), (1000.0, 1000.0))
        self.assertAlmostEqual(result["ratios"][0], 100.0)
        self.assertEqual(result["denominator"][11], -200000.0)  # the customer paid in December
        console = self.console()
        console.write({"corr2_numerator": "701", "corr2_denominator": "411"})
        console.action_run_two_way()
        self.assertIn("<circle", str(console.corr2_html))
        self.assertIn("1 000", str(console.corr2_html))
        three = self.as_staff.eagla_three_way(self.dataset_id, "701", "411", "521")
        self.assertAlmostEqual(three["ratios"]["ba"][0], 100.0)
        console.write({"corr3_a": "701", "corr3_b": "411", "corr3_c": "521"})
        console.action_run_three_way()
        self.assertEqual(str(console.corr3_html).count("<circle"), 3)
        self.assertCode("invalid-accounts", self.as_staff.eagla_two_way, self.dataset_id, "70%", "411")
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.outsider).eagla_two_way, self.dataset_id, "70", "411")

    def test_a_prior_year_ledger_is_read_over_its_own_year(self):
        dataset = self.env["ea.audit.dataset"].browse(self.dataset_id)
        start, end, _keys = self.engagement._ea_eagla_year(dataset)
        dataset.sudo().timing = "prior_year"
        prior_start, prior_end, _keys = self.engagement._ea_eagla_year(dataset)
        self.assertEqual((prior_start.year, prior_end.year), (start.year - 1, end.year - 1))
        self.assertEqual((prior_start.month, prior_start.day), (start.month, start.day))

    def test_scot_identification(self):
        result = self.as_staff.eagla_scot(self.dataset_id, "revenue")
        flows = {(flow["source"], flow["target"]): flow for flow in result["flows"]}
        self.assertAlmostEqual(flows[("sales", "customers")]["amount"], 1000.0)
        self.assertAlmostEqual(flows[("customers", "bank")]["amount"], 200000.0)
        self.assertEqual(result["timing"]["entering"][0], 1000.0)
        treasury = self.as_staff.eagla_scot(self.dataset_id, "treasury")
        self.assertEqual({row["group"] for row in treasury["treasury"]}, {"customers", "other"})
        console = self.console()
        console.with_context(ea_scot_class="revenue").action_scot()
        self.assertEqual((console.pane, console.scot_class), ("scot", "revenue"))
        self.assertIn("<svg", str(console.scot_html))
        pattern = console.scot_pattern_ids.filtered(lambda line: line.journal == "VE")
        self.assertEqual(pattern.entries, 1)
        action = pattern.action_open_entries()
        self.assertEqual(action["res_model"], "ea.audit.gl.line")
        lines = self.env["ea.audit.gl.line"].with_user(self.staff).search(action["domain"])
        self.assertEqual(set(lines.mapped("je_number")), {"VE001"})
        self.assertCode("invalid-value", console.with_context(ea_scot_class="payroll").action_scot)
