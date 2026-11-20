from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import AR_CSV, AR_MAPPING, ToolsCase, to_bytes

LEDGER = """Compte;Intitulé;N° écriture;Libellé;Date;Débit;Crédit;Référence;Journal;Saisi par
411000;Clients;VE001;Facture 1;15/01/2025;1 000,00;;F1;VE;Awa
701000;Ventes;VE001;Facture 1;15/01/2025;;1 000,00;F1;VE;Awa
521000;Banque;BQ001;Encaissement;31/12/2025;1 000,00;;C1;BQ;Awa
411000;Clients;BQ001;Encaissement;31/12/2025;;1 000,00;C1;BQ;Awa
601000;Achats;;Sans numero;03/03/2025;50,00;;;OD;Awa
"""

MAPPING = {
    "account": "Compte", "accountName": "Intitulé", "jeNumber": "N° écriture", "jeDescription": "Libellé",
    "journalDate": "Date", "debit": "Débit", "credit": "Crédit", "reference": "Référence", "journalCode": "Journal",
    "preparedBy": "Saisi par",
}


class GlCase(ToolsCase):
    def import_ledger(self, content=LEDGER, mapping=None, actor=None):
        return (actor or self.as_staff).create_dataset(
            "journal_entries", "ledger.csv", to_bytes(content), mapping=mapping or MAPPING,
        )

    def built(self, content=LEDGER):
        dataset_id = self.import_ledger(content)["datasetId"]
        self.as_staff.gl_build_projection(dataset_id)
        return dataset_id


@tagged("post_install", "-at_install")
class TestDataset(GlCase):
    def test_preview_guesses_the_mapping_and_writes_nothing(self):
        preview = self.as_staff.preview_dataset_file("journal_entries", "ledger.csv", to_bytes(LEDGER))
        self.assertEqual(preview["rowCount"], 5)
        self.assertEqual(preview["mapping"]["account"], "Compte")
        self.assertFalse(self.env["ea.audit.dataset"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))

    def test_a_new_upload_supersedes_the_previous_one_and_keeps_it(self):
        """Owner's ruling of 2026-11-15: an upload is a version, no longer deleted by the next one."""
        first = self.env["ea.audit.dataset"].sudo().browse(self.import_ledger()["datasetId"])
        second = self.env["ea.audit.dataset"].sudo().browse(self.import_ledger()["datasetId"])
        self.assertTrue(first.exists())
        self.assertTrue(first.superseded_at)
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)
        for dataset in (first, second):
            rows = self.env["ea.audit.dataset.row"].sudo().search([("dataset_id", "=", dataset.id)])
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[0].data["Compte"], "411000")

    def test_the_pair_amount_is_debit_minus_credit(self):
        dataset = self.env["ea.audit.dataset"].sudo().browse(self.import_ledger()["datasetId"])
        self.assertTrue(dataset.has_total)
        self.assertEqual(dataset.total_amount, 50)

    def test_refusals_keep_their_codes(self):
        with self.assertRaisesRegex(Exception, "read-only-role"):
            self.as_reader.create_dataset("journal_entries", "l.csv", to_bytes(LEDGER))
        with self.assertRaisesRegex(Exception, "fields-required"):
            self.as_staff.create_dataset("nonsense", "l.csv", to_bytes(LEDGER))
        with self.assertRaisesRegex(Exception, "unsupported-file"):
            self.as_staff.create_dataset("journal_entries", "l.pdf", to_bytes(LEDGER))
        with self.assertRaisesRegex(Exception, "eqr-read-only"):
            self.as_eqr.create_dataset("journal_entries", "l.csv", to_bytes(LEDGER))

    def test_plain_orm_entry_points_are_closed(self):
        dataset_id = self.import_ledger()["datasetId"]
        with self.assertRaises(Exception):
            self.env["ea.audit.dataset"].with_user(self.staff).browse(dataset_id).write({"name": "x"})
        with self.assertRaises(Exception):
            self.env["ea.audit.dataset"].with_user(self.staff).browse(dataset_id).unlink()

    def test_an_outsider_reads_nothing(self):
        dataset_id = self.built()
        for model in ("ea.audit.dataset", "ea.audit.dataset.row", "ea.audit.gl.line"):
            records = self.env[model].with_user(self.outsider).search([])
            self.assertFalse(records, model)
        with self.assertRaises(AccessError):
            self.env["ea.audit.dataset"].with_user(self.outsider).browse(dataset_id).read(["name"])
        with self.assertRaisesRegex(Exception, "not-on-this-engagement"):
            self.as_outsider.gl_validate_population(dataset_id)


@tagged("post_install", "-at_install")
class TestProjection(GlCase):
    def test_build_types_the_lines_and_rejects_those_without_identity(self):
        dataset_id = self.import_ledger()["datasetId"]
        # the upload builds it (owner's ruling of 2026-11-20): asking again reuses it
        dataset = self.env["ea.audit.dataset"].sudo().browse(dataset_id)
        self.assertEqual((dataset.gl_line_count, dataset.gl_rejected), (4, 1))
        result = self.as_staff.gl_build_projection(dataset_id)
        self.assertEqual(result["build"], {"lines": 4, "rejected": 0, "reused": True})
        lines = self.env["ea.audit.gl.line"].sudo().search([("dataset_id", "=", dataset_id)])
        self.assertEqual(lines[0].account, "411000")
        self.assertEqual(lines[0].signed, 1000)
        self.assertEqual(lines[1].signed, -1000)
        self.assertEqual(str(lines[0].journal_date), "2025-01-15")
        self.assertEqual(lines[0].preparer, "Awa")

    def test_build_is_idempotent(self):
        dataset_id = self.built()
        result = self.as_staff.gl_build_projection(dataset_id)
        self.assertEqual(result["build"], {"lines": 4, "rejected": 0, "reused": True})

    def test_population_checks(self):
        dataset_id = self.built()
        validation = self.as_staff.gl_validate_population(dataset_id)
        status = {check["key"]: check["status"] for check in validation["checks"]}
        self.assertEqual(len(status), 11)
        self.assertEqual(status["mandatory-mapped"], "passed")
        self.assertEqual(status["entries-balance"], "passed")
        self.assertEqual(status["debit-credit-reconcile"], "passed")
        self.assertEqual(status["row-count"], "warning")
        self.assertEqual(validation["status"], "warning")
        dataset = self.env["ea.audit.dataset"].sudo().browse(dataset_id)
        self.assertIn("table", str(dataset.population_html))

    def test_an_unbalanced_ledger_is_refused_and_out_of_period_is_caught(self):
        """Owner's ruling of 2026-11-15: an unbalanced general ledger is not imported."""
        unbalanced = LEDGER + "411000;Clients;VE009;Hors periode;15/01/2024;10,00;;;VE;Awa\n"
        self.assertCode("import-refused", self.import_ledger, unbalanced)
        self.assertFalse(self.env["ea.audit.dataset"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))
        balanced = unbalanced + "701000;Ventes;VE009;Hors periode;15/01/2024;;10,00;;VE;Awa\n"
        dataset_id = self.built(balanced)
        status = {c["key"]: c["status"] for c in self.as_staff.gl_validate_population(dataset_id)["checks"]}
        self.assertEqual(status["entries-balance"], "passed")
        self.assertEqual(status["debit-credit-reconcile"], "passed")
        self.assertEqual(status["dates-in-period"], "warning")

    def test_a_ledger_stored_unbalanced_before_the_ruling_still_says_so(self):
        """Ledgers imported before 2026-11-15 are left as they are: their checks still read them."""
        dataset_id = self.built()
        line = self.env["ea.audit.gl.line"].sudo().search([("dataset_id", "=", dataset_id)], limit=1)
        line.write({"debit": line.debit + 10, "signed": line.signed + 10})
        self.env.flush_all()
        status = {c["key"]: c["status"] for c in self.as_staff.gl_validate_population(dataset_id)["checks"]}
        self.assertEqual(status["entries-balance"], "failed")
        self.assertEqual(status["debit-credit-reconcile"], "failed")

    def test_incomplete_mapping_is_refused(self):
        """At the import now, and still at the build for a ledger imported before the matching was mandatory."""
        with self.assertRaisesRegex(Exception, "mapping-incomplete"):
            self.import_ledger(mapping={"account": "Compte"})
        self.assertFalse(self.env["ea.audit.dataset"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))
        dataset_id = self.import_ledger()["datasetId"]
        # an old upload: no projection yet, and a matching from before it was mandatory
        self.env.cr.execute("DELETE FROM ea_audit_gl_line WHERE dataset_id = %s", [dataset_id])
        self.env["ea.audit.dataset"].sudo().browse(dataset_id).write({"mapping": {"account": "Compte"}, "gl_built_at": False})
        with self.assertRaisesRegex(Exception, "mapping-incomplete"):
            self.as_staff.gl_build_projection(dataset_id)

    def test_only_a_ledger_of_this_file(self):
        with self.assertRaisesRegex(Exception, "no-dataset"):
            self.as_staff.gl_build_projection(999999)
        other = self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(AR_CSV), mapping=AR_MAPPING)
        with self.assertRaisesRegex(Exception, "no-dataset"):
            self.as_staff.gl_build_projection(other["datasetId"])

    def test_build_is_refused_on_an_archived_file_while_reads_answer(self):
        dataset_id = self.built()
        self.engagement.sudo().write({"archived_at": "2026-01-01 00:00:00"})
        self.env.invalidate_all()
        with self.assertRaisesRegex(Exception, "archived"):
            self.as_staff.create_dataset("journal_entries", "l.csv", to_bytes(LEDGER), mapping=MAPPING)
        self.assertEqual(self.as_staff.gl_validate_population(dataset_id)["lines"], 4)

    def test_the_tile_opens_the_ledgers(self):
        action = self.env.ref("ea_audit_tools.tile_an_gl").with_user(self.staff).with_context(ea_engagement_id=self.engagement.id).action_open_tool()
        self.assertEqual(action["res_model"], "ea.audit.dataset")
