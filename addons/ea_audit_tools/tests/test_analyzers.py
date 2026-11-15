import io

from openpyxl import load_workbook

from odoo.tests import tagged

from .common import AP_MAPPING, ToolsCase, to_bytes

AR = """Client;Nom;Référence;Date;Montant;Conditions
C1;Alpha;F1;15/12/2025;600;30 jours
C1;Alpha;F2;15/10/2025;200;
C2;Beta;F3;15/07/2025;100;
C3;Gamma;F4;illisible;50;
"""
AR_MAP = {"party": "Client", "partyName": "Nom", "reference": "Référence", "date": "Date", "amount": "Montant", "paymentTerms": "Conditions"}


@tagged("post_install", "-at_install")
class TestAnalyzers(ToolsCase):
    def ar(self, content=AR):
        return self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(content), mapping=AR_MAP)["datasetId"]

    def test_aging_buckets(self):
        self.ar()
        result = self.as_staff.aging_for("ar_open_items")
        self.assertEqual(result["undated"], 1)
        self.assertEqual(result["transactionCount"], 4)
        first = result["rows"][0]
        self.assertEqual((first["party"], first["name"], first["terms"]), ("C1", "Alpha", "30 jours"))
        self.assertEqual((first["current"], first["d61_90"], first["total"]), (600, 200, 800))
        self.assertEqual(result["rows"][1]["over90"], 100)
        self.assertEqual(result["totals"]["total"], 900)
        self.assertIsNone(self.as_staff.aging_for("ap_open_items"))

    def test_the_form_shows_aging_and_agreement(self):
        dataset = self.env["ea.audit.dataset"].with_user(self.staff).browse(self.ar())
        self.import_tb()
        self.assertIn("Alpha", str(dataset.aging_html))
        self.assertIn("41", str(dataset.recon_html))
        self.assertTrue(dataset.has_recon)

    def test_the_reconciliation_is_a_run_and_above_trivial_a_finding(self):
        self.approve()
        dataset = self.ar()
        before = self.env["ea.audit.finding"].sudo().search_count([("engagement_id", "=", self.engagement.id)])
        run = self.as_staff.run_reconciliation(dataset)
        as_root = run.sudo()
        self.assertEqual(as_root.engine, "recon_subledger")
        self.assertEqual(as_root.summary["datasetTotal"], 950)
        self.assertEqual(as_root.summary["tbTotal"], 900)
        self.assertEqual(as_root.file_item_id.code, "E4.1")
        found = self.env["ea.audit.finding"].sudo().search_count([("engagement_id", "=", self.engagement.id)])
        self.assertEqual(found - before, 1 if as_root.summary["aboveTrivial"] else 0)

    def test_refusals(self):
        with self.assertRaisesRegex(Exception, "no-dataset"):
            self.as_staff.run_reconciliation(99999)
        supplier = self.as_staff.create_dataset("supplier_statements", "s.csv", to_bytes("Fournisseur;Montant\nA;10\n"))["datasetId"]
        with self.assertRaisesRegex(Exception, "unsupported-dataset"):
            self.as_staff.run_reconciliation(supplier)
        dataset = self.ar()
        with self.assertRaisesRegex(Exception, "read-only-role"):
            self.as_reader.run_reconciliation(dataset)
        with self.assertRaisesRegex(Exception, "eqr-read-only"):
            self.as_eqr.run_reconciliation(dataset)
        with self.assertRaisesRegex(Exception, "not-on-this-engagement"):
            self.as_outsider.aging_for("ar_open_items")

    def test_supplier_statements(self):
        statement = self.as_staff.create_dataset("supplier_statements", "s.csv", to_bytes("Fournisseur;Montant\nA;10\nB;5\n"))["datasetId"]
        ledger = self.as_staff.create_dataset(
            "ap_open_items", "ap.csv", to_bytes("Fournisseur;Raison sociale;Référence;Date;Montant\nA;Alpha;F1;15/12/2025;8\nB;Beta;F2;15/12/2025;5\n"), mapping=AP_MAPPING,
        )["datasetId"]
        run = self.as_staff.run_supplier_recon(statement, ledger).sudo()
        self.assertEqual(run.summary["suppliersCompared"], 2)
        self.assertEqual(run.summary["differences"], 1)

    def test_templates_and_aging_export(self):
        name, content = self.as_staff.ea_export_xlsx("template_ar_open_items")
        self.assertIn("ar_open_items", name)
        book = load_workbook(io.BytesIO(content))
        self.assertTrue(book.active.cell(1, 1).value)
        self.ar()
        name, _content = self.as_staff.ea_export_xlsx("aging_ar_open_items")
        self.assertIn("aging", name)
        with self.assertRaisesRegex(Exception, "not-found"):
            self.as_staff.ea_export_xlsx("template_nonsense")

    def test_the_analyzer_tiles_open(self):
        action = self.as_staff.action_tool_data_analytics()
        tiles = self.env["ea.audit.tool.tile"].with_user(self.staff).search(action["domain"])
        self.assertGreaterEqual(len(tiles), 7)
        for tile in tiles.filtered("method"):
            opened = tile.with_context(ea_engagement_id=self.engagement.id).action_open_tool()
            self.assertTrue(opened)
        action = self.as_staff.action_tool_ar()
        self.assertEqual(action["context"]["ea_dataset_kind"], "ar_open_items")
