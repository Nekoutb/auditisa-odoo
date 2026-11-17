"""Data quality (IPE): the checks run on upload, the references, the signatures a new upload
voids, the tile that replaces substantive analytics, and the reviewer's warning that is
recorded without blocking (owner's ruling of 2026-11-17)."""
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.ea_audit_core.models.file_item import FileItem as CoreFileItem

from .common import to_bytes
from .test_gl import LEDGER, GlCase


@tagged("post_install", "-at_install")
class TestIpe(GlCase):
    def record(self, kind="journal_entries", timing="pre_audit"):
        return self.env["ea.audit.ipe"].sudo().search([
            ("engagement_id", "=", self.engagement.id), ("kind", "=", kind), ("timing", "=", timing),
        ])

    def cell(self, page, ref):
        return next(cell for row in page["rows"] for cell in row["cells"] if cell["ref"] == ref)

    def explain_all(self, actor=None, kind="journal_entries", timing="pre_audit"):
        actor = actor or self.as_staff
        page = actor.ea_ipe_page(kind, timing)
        for check in page["detail"]["checks"]:
            if check["needsExplanation"]:
                page = actor.ea_ipe_explain(kind, timing, check["code"], "Seen with the accountant: no effect on our work.")
        return page

    def trail(self, action):
        return self.env["ea.audit.activity"].sudo().search([("engagement_id", "=", self.engagement.id), ("action", "=", action)])

    # ------------------------------------------------------------------

    def test_the_substantive_analytics_tile_gives_way_to_data_quality(self):
        Tile = self.env["ea.audit.tool.tile"].with_user(self.staff)
        hub = Tile.search([("section", "=", "hub")]).mapped("code")
        self.assertNotIn("sap", hub)
        self.assertIn("ipe", hub)
        self.assertIn("an-ipe", Tile.search([("section", "=", "analyzers")]).mapped("code"))
        tile = self.env.ref("ea_audit_tools.tile_ipe").with_user(self.staff)
        action = tile.with_context(ea_engagement_id=self.engagement.id).action_open_tool()
        self.assertEqual(action["tag"], "ea_audit_tools.ipe_page")
        self.assertFalse(self.env.ref("ea_audit_tools.menu_sap_thresholds").active)
        # the procedures recorded before stay readable
        self.assertFalse(self.env["ea.audit.sap.procedure"].with_user(self.staff).search([]))

    def test_an_upload_runs_the_checks_and_keeps_the_file_lines(self):
        self.import_ledger()
        record = self.record()
        self.assertEqual(record.reference, "IPE-GL-PRE")
        self.assertTrue(record.checked_at)
        self.assertEqual(record.source_filename, "ledger.csv")
        checks = {check.code: check for check in record.check_ids}
        self.assertEqual(len(checks), 15)
        self.assertEqual(checks["GL-08"].status, "passed")
        self.assertEqual(checks["GL-09"].status, "passed")
        # the line with no entry number, line 6 of the file
        self.assertEqual(checks["GL-01"].status, "exceptions")
        self.assertEqual(checks["GL-01"].line_ids.mapped("file_row"), [6])
        self.assertIn(6, checks["GL-02"].line_ids.mapped("file_row"))
        self.assertEqual(checks["GL-13"].status, "na")
        page = self.as_staff.ea_ipe_page("journal_entries", "pre_audit")
        self.assertEqual(self.cell(page, "IPE-GL-PRE")["state"], "to_explain")
        self.assertEqual(self.cell(page, "IPE-FA-PRE")["state"], "not_uploaded")
        self.assertEqual(page["detail"]["file"], "ledger.csv")
        self.assertEqual(page["detail"]["entries"], 2)
        self.assertTrue(page["detail"]["exportUrl"])
        self.assertIn("E3.1", [paper["code"] for paper in page["detail"]["papers"]])

    def test_an_extraction_date_checks_the_ledger_again(self):
        self.import_ledger()
        self.as_staff.ea_ipe_save("journal_entries", "pre_audit", {"extraction_date": "2025-12-15", "system_name": "Sage 100"})
        record = self.record()
        self.assertEqual(record.system_name, "Sage 100")
        check = record.check_ids.filtered(lambda c: c.code == "GL-13")
        self.assertEqual(check.status, "exceptions")
        self.assertEqual(check.exception_count, 2)

    def test_the_trial_balance_is_checked_on_import(self):
        self.import_tb()
        record = self.record("trial_balance", "pre_audit")
        self.assertEqual(record.reference, "IPE-TB-PRE")
        checks = {check.code: check.status for check in record.check_ids}
        self.assertEqual(len(checks), 11)
        self.assertEqual(checks["TB-05"], "passed")
        self.assertEqual(checks["TB-07"], "passed")
        self.import_tb(timing="prior_year")
        self.assertEqual(self.record("trial_balance", "prior_year").reference, "IPE-TB-PY")

    def test_reliable_needs_every_explanation(self):
        self.import_ledger()
        self.assertCode("ipe-explanation-required", self.as_staff.ea_ipe_conclude, "journal_entries", "pre_audit", "reliable")
        self.as_staff.ea_ipe_conclude("journal_entries", "pre_audit", "not_reliable")
        self.explain_all()
        page = self.as_staff.ea_ipe_conclude("journal_entries", "pre_audit", "reliable")
        self.assertEqual(self.cell(page, "IPE-GL-PRE")["state"], "reliable")
        self.assertTrue(self.cell(page, "IPE-GL-PRE")["text"].startswith("Reliable · "))

    def test_signing_no_self_review_and_a_new_upload_voids_the_signatures(self):
        self.import_ledger()
        self.explain_all()
        self.assertCode("ipe-conclusion-required", self.as_staff.ea_ipe_sign, "journal_entries", "pre_audit", "preparer")
        self.as_staff.ea_ipe_conclude("journal_entries", "pre_audit", "reliable")
        self.assertCode("ipe-preparer-first", self.as_manager.ea_ipe_sign, "journal_entries", "pre_audit", "reviewer")
        self.as_manager.ea_ipe_sign("journal_entries", "pre_audit", "preparer")
        self.assertCode("ipe-self-review", self.as_manager.ea_ipe_sign, "journal_entries", "pre_audit", "reviewer")
        self.assertCode("requires-senior", self.as_staff.ea_ipe_sign, "journal_entries", "pre_audit", "reviewer")
        self.engagement.with_user(self.senior).ea_ipe_sign("journal_entries", "pre_audit", "reviewer")
        record = self.record()
        self.assertEqual(record.preparer_id, self.manager)
        self.assertEqual(record.reviewer_id, self.senior)
        self.import_ledger(LEDGER.replace("Facture 1", "Facture une"))
        record.invalidate_recordset()
        self.assertFalse(record.preparer_id)
        self.assertFalse(record.reviewer_id)
        self.assertFalse(record.conclusion)
        self.assertTrue(all(not check.explanation for check in record.check_ids))
        self.assertTrue(self.trail("ipe_voided"))
        self.assertTrue(record.checked_at)

    def test_a_reader_cannot_change_anything(self):
        self.import_ledger()
        page = self.as_reader.ea_ipe_page("journal_entries", "pre_audit")
        self.assertTrue(page["readonly"])
        self.assertCode("read-only-role", self.as_reader.ea_ipe_save, "journal_entries", "pre_audit", {"system_name": "x"})

    def test_a_dataset_delete_checks_what_is_in_use_again(self):
        first = self.import_ledger()["datasetId"]
        second = self.import_ledger(LEDGER.replace("Awa", "Paul"))["datasetId"]
        self.assertEqual(self.record().dataset_id.id, second)
        self.as_staff.delete_dataset(second)
        self.assertEqual(self.record().dataset_id.id, first)

    def test_the_exceptions_download(self):
        self.import_ledger()
        name, content = self.as_staff.ea_export_xlsx("ipe_%d" % self.record().id)
        self.assertIn("IPE-GL-PRE", name)
        self.assertTrue(content)

    def test_a_reviewer_is_warned_not_blocked_and_the_warning_is_recorded(self):
        self.import_ledger()
        self.as_staff.ea_ipe_conclude("journal_entries", "pre_audit", "not_reliable")
        warning = self.engagement.with_user(self.senior)._ea_ipe_paper_warning("E3.1", "en")
        self.assertIn("marked Not reliable in IPE", warning)
        self.assertIn("ledger.csv", warning)
        self.assertFalse(self.engagement.with_user(self.senior)._ea_ipe_paper_warning("C3.1", "en"))
        item = self.item(self.engagement, "E3.1")
        paper = item._ea_paper()
        if paper:
            relied = paper.with_user(self.senior)._ea_data_relied()
            self.assertEqual(relied["rows"][0]["ref"], "IPE-GL-PRE")
            self.assertEqual(relied["rows"][0]["state"], "not_reliable")
            self.assertTrue(relied["warning"])
        # the sign-off rules of the core are not what this test is about: they let the signature through
        with patch.object(CoreFileItem, "action_sign", lambda self, requested: requested):
            role = item.with_user(self.senior).action_sign("reviewer")
        self.assertEqual(role, "reviewer")
        line = self.trail("ipe_warning_signed")
        self.assertEqual(len(line), 1)
        self.assertIn("E3.1 signed as reviewer", line.summary)
        self.assertIn("IPE-GL-PRE", line.summary)
        # a preparer's signature, or a dry run, records nothing
        with patch.object(CoreFileItem, "action_sign", lambda self, requested: requested):
            item.with_user(self.staff).action_sign("preparer")
            item.with_user(self.senior).with_context(ea_sign_dry_run=True).action_sign("reviewer")
        self.assertEqual(len(self.trail("ipe_warning_signed")), 1)

    def test_the_payable_reference_and_a_kind_with_no_upload(self):
        content = "Fournisseur;Raison sociale;Référence;Date;Montant\nF1;Sodeco;FA1;15/12/2025;100\n"
        self.as_staff.create_dataset("ap_open_items", "ap.csv", to_bytes(content), mapping={
            "party": "Fournisseur", "partyName": "Raison sociale", "reference": "Référence", "date": "Date", "amount": "Montant",
        }, timing="post_audit")
        self.assertEqual(self.record("ap_open_items", "post_audit").reference, "IPE-AP-POST")
        page = self.as_staff.ea_ipe_page("ap_open_items", "post_audit")
        self.assertIn("E4.2", [paper["code"] for paper in page["detail"]["papers"]])
        self.assertCode("ipe-no-file", self.as_staff.ea_ipe_rerun, "bank_statement", "pre_audit")
