"""The two gates the first port left reduced: controls_concluded and the FS tie-out."""
import base64

from odoo.tests import tagged

from ..services.fs_tieout import Closings, client_diffs, compute_cr, parse_client_fs, run_tieout
from .common import ReportsCase

TB = [
    ("101000", -50000), ("231000", 40000), ("411000", 20000), ("521000", 5000),
    ("601000", 60000), ("622000", 5000), ("661000", 10000), ("681000", 2000), ("701000", -92000),
]


@tagged("post_install", "-at_install")
class TestFsTieout(ReportsCase):
    def test_the_sig_cascade(self):
        lines, result = compute_cr(Closings(TB))
        by = {line["ref"]: line["amount"] for line in lines}
        self.assertEqual(by["XA"], 32000)
        self.assertEqual(by["XC"], 27000)
        self.assertEqual(by["XD"], 17000)
        self.assertEqual(by["XE"], 15000)
        self.assertEqual(by["XI"], 15000)
        self.assertEqual(result, 15000)

    def test_equilibrium_and_the_client(self):
        result = run_tieout(TB)
        self.assertTrue(result["pass"])
        self.assertEqual(run_tieout([("411000", 100)])["checks"][0]["key"], "tb_balanced")
        self.assertFalse(run_tieout([("411000", 100)])["pass"])
        self.assertFalse(run_tieout([])["pass"])
        self.assertEqual(parse_client_fs(b"xa;32000\nXI;nope\n;;\nXE;15000\n"), {"XA": 32000.0, "XE": 15000.0})
        cr, _ = compute_cr(Closings(TB))
        self.assertEqual(client_diffs({"XA": 31000.0, "ZZ": 1.0}, cr, 0), [{"ref": "XA", "recomputed": 32000, "client": 31000.0, "difference": 1000}])
        self.assertEqual(client_diffs({"XA": 31000.0}, cr, 1000), [])
        self.assertFalse(run_tieout(TB, 0, b"XA;31000\n")["pass"])

    def test_the_record_and_its_refusal(self):
        self.import_tb()
        self.assertCode("tieout-failed", self.as_senior.run_fs_tieout, b"XI;1\n")
        self.assertFalse(self.engagement.sudo()._ea_record_exists("fs_tieout"))
        self.as_senior.run_fs_tieout()
        self.assertTrue(self.engagement.sudo()._ea_record_exists("fs_tieout"))

    def test_the_screen_shows_the_difference_and_records_nothing(self):
        self.import_tb()
        wizard = self.env["ea.audit.tieout.wizard"].with_user(self.senior).create({
            "engagement_id": self.engagement.id, "client_file": base64.b64encode(b"XI;1\n"),
        })
        wizard.action_run()
        self.assertIn("XI", wizard.result_html)
        self.assertFalse(self.engagement.sudo()._ea_record_exists("fs_tieout"))
        self.assertIn("o_ea_tieout", self.engagement.with_user(self.senior).fs_tieout_html)

    def test_e610_refuses_yes_while_the_tieout_shows_differences(self):
        # An unbalanced file is refused and nothing of it is kept: the tie-out has no trial balance to agree to.
        unbalanced = "Compte;Libellé;Mouvement débit;Mouvement crédit\n411000;Clients;1000;0\n701000;Ventes;0;900\n"
        self.assertCode("import-refused", self.import_tb, content=unbalanced)
        self.assertTrue(self.item(self.engagement, "E6.10")._ea_paper()._ea_tieout_failed())

    def test_e610_board_fronts_the_figures(self):
        self.import_tb()
        board = self.item(self.engagement, "E6.10").with_user(self.senior).ea_paper_board()
        self.assertTrue(board["rows"])
        self.assertTrue(board["facts"])


@tagged("post_install", "-at_install")
class TestControlsConcluded(ReportsCase):
    def setUp(self):
        super().setUp()
        self.scot = self.as_staff.create_scot("Ventes", "routine", "controls")
        wcgw = self.scot.add_wcgw("Facture non enregistrée", ["C"])
        self.control = self.scot.add_control("Rapprochement", wcgws=wcgw)

    def gate(self):
        return next(gate for gate in self.as_partner.archive_gates() if gate["key"] == "controls_concluded")

    def test_nothing_selected_blocks_nothing(self):
        self.assertTrue(self.gate()["ok"])

    def test_selected_stays_open_until_designed_and_tested(self):
        self.control.update_control({"selected_for_testing": True})
        self.assertEqual(self.gate()["pending"], 1)
        self.assertEqual(self.engagement.sudo()._ea_open_control_rows(), ["Rapprochement"])
        self.control.update_control({"design_eval": "effective"})
        self.assertFalse(self.gate()["ok"])
        self.control.record_test("Janvier", "effective")
        self.assertTrue(self.gate()["ok"])

    def test_a_reversed_selection_closes_it(self):
        self.control.update_control({"selected_for_testing": True})
        self.control.update_control({"selected_for_testing": False})
        self.assertTrue(self.gate()["ok"])

    def test_the_checklist_names_it(self):
        self.control.update_control({"selected_for_testing": True})
        checklist = self.as_partner.archive_checklist("fr")
        gates = {gate["key"]: gate for group in checklist["groups"] for gate in group["gates"]}
        self.assertEqual([row["label"] for row in gates["controls_concluded"]["items"]], ["Rapprochement"])


@tagged("post_install", "-at_install")
class TestScopeAndTriggers(ReportsCase):
    def test_an_e4_task_s55_left_out_asks_for_nothing(self):
        codes = [item.code for item in self.engagement.sudo()._ea_untouched_tasks()]
        self.assertNotIn("E4.1", codes)
        self.as_staff.add_dsp_osp("E", "Confirmer les soldes", ["E"])
        codes = [item.code for item in self.engagement.sudo()._ea_untouched_tasks()]
        self.assertNotIn("E4.1", self.engagement.sudo()._ea_e4_out_of_scope().mapped("code"))

    def test_no_trigger_on_a_screens_own_tables(self):
        self.env.cr.execute("""
            SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
             WHERE t.tgname = 'ea_audit_archive_lock' AND (c.relname LIKE '%%_wizard' OR c.relname = 'ea_audit_gl_console')
        """)
        self.assertEqual(self.env.cr.fetchall(), [])
