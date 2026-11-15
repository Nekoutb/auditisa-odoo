"""Significant accounts (owner's request of 2026-11-15): the general ledger's transactions,
preparers and reviewers per lead index, and a change of status kept with its reason."""
import io
import json
import time

from openpyxl import load_workbook

from odoo.addons.ea_audit_core.services.activity_summary import parse_body, translate_summary
from odoo.tests import tagged

from .common import ToolsCase, to_bytes

LEDGER = """Compte;N° écriture;Libellé;Date;Débit;Crédit;Saisi par;Approuvé par
411000;VE001;Facture 1;15/01/2025;1 000,00;;Awa;Paul
701000;VE001;Facture 1;15/01/2025;;1 000,00;Awa;Paul
411000;VE002;Facture 2;16/01/2025;500,00;;BEN  ;
706100;VE002;Facture 2;16/01/2025;;500,00;ben;
521000;BQ001;Encaissement;31/12/2025;1 000,00;;Awa;Marie
411000;BQ001;Encaissement;31/12/2025;;1 000,00;Awa;Marie
"""
MAPPING = {
    "account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date",
    "debit": "Débit", "credit": "Crédit", "recordedBy": "Saisi par", "approvedBy": "Approuvé par",
}
NO_PEOPLE = {key: value for key, value in MAPPING.items() if key not in ("recordedBy", "approvedBy")}


@tagged("post_install", "-at_install")
class TestSignificanceActivity(ToolsCase):
    def rows(self):
        self.engagement.sudo()._ea_sync_significance(activity=False)
        records = self.env["ea.audit.significance"].with_user(self.staff).search([("engagement_id", "=", self.engagement.id)])
        records.invalidate_recordset()
        return {record.index_code: record for record in records}

    def import_ledger(self, mapping=MAPPING, timing="pre_audit", content=LEDGER):
        return self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(content), mapping=mapping, timing=timing)["datasetId"]

    def stored(self, record):
        self.env.cr.execute(
            "SELECT activity_dataset, tx_count, preparer_count, reviewer_count FROM ea_audit_significance WHERE id = %s",
            [record.id],
        )
        return self.env.cr.fetchone()

    def test_without_a_ledger_the_columns_are_empty(self):
        self.import_tb()
        row = self.rows()["E"]
        self.assertEqual(row.activity_dataset, 0)
        self.assertFalse(row.preparer_known)
        self.assertFalse(row.reviewer_known)

    def test_entries_and_people_of_the_ledger_in_use(self):
        self.import_tb()
        dataset_id = self.import_ledger()
        rows = self.rows()
        # E (clients): VE001, VE002, BQ001; two people recorded them, two approved
        self.assertEqual((rows["E"].activity_dataset, rows["E"].tx_count), (dataset_id, 3))
        self.assertEqual((rows["E"].preparer_count, rows["E"].reviewer_count), (2, 2))
        self.assertTrue(rows["E"].preparer_known and rows["E"].reviewer_known)
        self.assertEqual((rows["UA"].tx_count, rows["UA"].preparer_count, rows["UA"].reviewer_count), (2, 2, 1))
        self.assertEqual((rows["C"].tx_count, rows["C"].preparer_count, rows["C"].reviewer_count), (1, 1, 1))
        # an index the ledger does not reach: 0 entries, from a ledger that is in use
        self.assertEqual((rows["K"].activity_dataset, rows["K"].tx_count), (dataset_id, 0))

    def test_a_column_not_matched_leaves_its_count_empty(self):
        self.import_tb()
        self.import_ledger(mapping=NO_PEOPLE)
        row = self.rows()["E"]
        self.assertEqual(row.tx_count, 3)
        self.assertFalse(row.preparer_known)
        self.assertFalse(row.reviewer_known)

    def test_the_counts_follow_the_ledger_in_use(self):
        self.import_tb()
        first = self.import_ledger(mapping=NO_PEOPLE)
        second = self.import_ledger(content="\n".join(LEDGER.splitlines()[:3]) + "\n")
        row = self.rows()["E"]
        self.assertEqual((row.activity_dataset, row.tx_count, row.preparer_count), (second, 1, 1))
        # the one before takes over when the one in use is deleted
        self.as_staff.delete_dataset(second)
        row = self.rows()["E"]
        self.assertEqual((row.activity_dataset, row.tx_count), (first, 3))
        self.assertFalse(row.preparer_known)
        self.as_staff.delete_dataset(first)
        row = self.rows()["E"]
        self.assertEqual(row.activity_dataset, 0)

    def test_the_trial_balance_mapping_moves_the_account(self):
        self.import_tb()
        self.import_ledger()
        self.as_staff.save_lead_index_override("5210", "E")
        rows = self.rows()
        self.assertEqual(rows["E"].tx_count, 3)
        self.assertNotIn("C", rows)

    def test_opening_the_list_counts_rows_never_counted_and_nothing_else(self):
        self.import_tb()
        self.import_ledger()
        row = self.rows()["E"]
        # as after the upgrade: the columns are empty on an open file
        self.env.cr.execute(
            "UPDATE ea_audit_significance SET activity_dataset = NULL, tx_count = NULL WHERE engagement_id = %s", [self.engagement.id],
        )
        self.env.invalidate_all()
        self.engagement.with_user(self.staff).action_tool_significance()
        self.assertEqual(self.stored(row)[1], 3)
        # counted from the ledger in use already: opening the list again counts nothing
        self.env.cr.execute("UPDATE ea_audit_significance SET tx_count = 99 WHERE id = %s", [row.id])
        self.env.invalidate_all()
        self.engagement.with_user(self.staff).action_tool_significance()
        self.assertEqual(self.stored(row)[1], 99)

    def test_an_archived_file_keeps_its_rows_as_they_are(self):
        self.import_tb()
        self.import_ledger()
        row = self.rows()["E"]
        self.env.cr.execute("UPDATE ea_audit_significance SET activity_dataset = NULL WHERE id = %s", [row.id])
        self.engagement.sudo().phase = "archived"
        self.env.invalidate_all()
        self.engagement.sudo()._ea_refresh_significance_activity()
        self.engagement.sudo()._ea_sync_significance()
        self.assertIsNone(self.stored(row)[0])

    def test_a_large_ledger_is_counted_in_reasonable_time(self):
        """186,000 lines, the size of a real client's ledger, written straight to the table."""
        self.import_tb()
        dataset_id = self.import_ledger()
        accounts = ["411000", "701000", "521000", "401000", "601000", "231000"]
        lines = 186000
        datas = [json.dumps({
            "Compte": accounts[n % len(accounts)], "N° écriture": "J%d" % (n // 2),
            "Saisi par": "u%d" % (n % 11), "Approuvé par": "v%d" % (n % 5),
        }) for n in range(lines)]
        self.env.cr.execute("DELETE FROM ea_audit_dataset_row WHERE dataset_id = %s", [dataset_id])
        self.env.cr.execute(
            """INSERT INTO ea_audit_dataset_row (engagement_id, dataset_id, row_no, data)
               SELECT %s, %s, r, d::jsonb FROM unnest(%s::int[], %s::text[]) AS t(r, d)""",
            [self.engagement.id, dataset_id, list(range(1, lines + 1)), datas],
        )
        started = time.perf_counter()
        self.engagement.sudo()._ea_refresh_significance_activity()
        elapsed = time.perf_counter() - started
        print("SIGNIFICANCE-TIMING %d lines counted and stored in %.2f s" % (lines, elapsed))
        row = self.rows()["E"]
        self.assertEqual(row.tx_count, lines // len(accounts))
        self.assertEqual((row.preparer_count, row.reviewer_count), (11, 5))
        self.assertLess(elapsed, 60)

    def test_the_excel_export_carries_the_counts(self):
        self.import_tb()
        self.import_ledger(mapping=dict(NO_PEOPLE, recordedBy="Saisi par"))
        self.rows()
        _filename, content = self.as_staff.ea_export_xlsx("significance")
        sheet = load_workbook(io.BytesIO(content)).active
        head = [cell.value for cell in sheet[1]]
        line = {row[0].value: [cell.value for cell in row] for row in sheet.iter_rows(min_row=2)}["E"]
        self.assertEqual(line[head.index("transactions")], 3)
        self.assertEqual(line[head.index("preparers")], 2)
        self.assertIn(line[head.index("reviewers")], (None, ""))


@tagged("post_install", "-at_install")
class TestSignificanceChange(ToolsCase):
    def row(self, code="E"):
        self.engagement.sudo()._ea_sync_significance(activity=False)
        record = self.env["ea.audit.significance"].with_user(self.staff).search([
            ("engagement_id", "=", self.engagement.id), ("index_code", "=", code),
        ])
        record.invalidate_recordset()
        return record

    def trail(self):
        bodies = self.engagement.sudo().message_ids.mapped("body")
        return [parsed for parsed in map(parse_body, bodies) if parsed and parsed[0] == "significance_changed"]

    def test_a_departure_needs_its_reason_and_is_on_the_trail(self):
        self.import_tb()
        row = self.row()
        self.assertEqual(row.default_status, "not_significant")
        self.assertCode("significance-reason-required", row.write, {"status": "significant"})
        self.assertCode("significance-reason-required", row.write, {"status": "significant", "justification": "   "})
        self.assertFalse(self.trail())
        row.write({"status": "significant", "justification": "Covenant  ratio\naccount"})
        row = self.row()
        self.assertEqual(row.status, "significant")
        self.assertFalse(row.unjustified)
        (action, summary), = self.trail()
        self.env["res.lang"]._ea_setup_languages()
        self.assertEqual(summary, "Significance of E changed from Not significant to Significant by %s: Covenant ratio account" % self.staff.name)
        french = translate_summary(action, summary, "fr_FR")
        self.assertEqual(french, "Statut de E changé de Non significatif à Significatif par %s : Covenant ratio account" % self.staff.name)
        # clearing the reason of a departure is refused too
        self.assertCode("significance-reason-required", row.write, {"justification": ""})

    def test_back_to_the_default_needs_no_reason(self):
        self.import_tb()
        row = self.row()
        row.write({"status": "significant", "justification": "Key"})
        row.write({"status": "not_significant", "justification": ""})
        row = self.row()
        self.assertEqual(row.status, "not_significant")
        self.assertFalse(row.overridden)
        self.assertEqual(len(self.trail()), 2)
        self.assertTrue(self.trail()[0][1].startswith("Significance of E changed from Significant to Not significant by "))

    def test_the_refusal_reads_in_french(self):
        self.import_tb()
        self.env["res.lang"]._ea_setup_languages()
        row = self.row().with_context(lang="fr_FR")
        with self.assertRaises(Exception) as caught:
            row.write({"status": "significant"})
        text = str(caught.exception)
        self.assertIn("E : ce statut s'écarte du statut par défaut", text)
        self.assertIn("[significance-reason-required]", text)

    def test_an_old_departure_without_reason_stays_until_its_status_or_reason_is_edited(self):
        self.import_tb()
        row = self.row()
        row.sudo().write({"decision": "significant"})
        row = self.row()
        self.assertTrue(row.unjustified)
        tags = self.env["ea.audit.assertion"]._ea_from_codes(["E"])
        row.write({"assertion_ids": [(6, 0, tags.ids)]})
        # the Excel round trip of the unchanged row is not a change
        count = self.as_staff.ea_import_xlsx("significance", "s.csv", b"index;status;justification\nE;significant;\n")
        self.assertEqual(count, 1)
        self.assertTrue(self.row().unjustified)
        # a new departure in the workbook, without its reason, is refused like one on the screen
        self.assertCode("significance-reason-required", self.as_staff.ea_import_xlsx, "significance", "s.csv",
                        b"index;status;justification\nT;significant;\n")

    def test_the_change_status_window(self):
        self.import_tb()
        row = self.row()
        action = row.action_change_status()
        self.assertEqual(action["res_model"], "ea.audit.significance.wizard")
        self.assertEqual(action["context"]["default_new_status"], "significant")
        Wizard = self.env["ea.audit.significance.wizard"].with_user(self.staff).with_context(**action["context"])
        wizard = Wizard.create({})
        self.assertTrue(wizard.needs_reason)
        self.assertCode("significance-reason-required", wizard.action_apply)
        wizard.reason = "Low transaction volumes but key covenant"
        wizard.action_apply()
        self.assertEqual(self.row().status, "significant")
        self.assertEqual(self.row().justification, "Low transaction volumes but key covenant")
        # a reader cannot change it
        self.assertCode("read-only-role", row.with_user(self.reader).write, {"status": "significant", "justification": "x"})


@tagged("post_install", "-at_install")
class TestSignificanceRisks(ToolsCase):
    """Owner's rulings of 2026-11-15: risks picked from the register on the list; any live risk
    locks the row at Significant; the presumed revenue-fraud risk sits on revenue until its
    rebuttal is approved by the engagement partner."""

    def row(self, code):
        self.engagement.sudo()._ea_sync_significance(activity=False)
        record = self.env["ea.audit.significance"].with_user(self.staff).search([
            ("engagement_id", "=", self.engagement.id), ("index_code", "=", code),
        ])
        record.invalidate_recordset()
        return record

    def risk(self, kind):
        return self.env["ea.audit.risk"].sudo().search([
            ("engagement_id", "=", self.engagement.id), ("presumed_type", "=", kind),
        ])

    def trail(self, action):
        bodies = self.engagement.sudo().message_ids.mapped("body")
        return [parsed[1] for parsed in map(parse_body, bodies) if parsed and parsed[0] == action]

    def test_revenue_carries_the_presumed_fraud_risk_and_is_locked(self):
        self.import_tb()
        revenue = self.row("UA")
        self.assertEqual(revenue.risk_ids, self.risk("revenue_fraud"))
        self.assertEqual(revenue.status, "significant")
        self.assertIn("Presumed fraud risk in revenue recognition", revenue.lock_note)
        self.assertCode("significance-locked-by-risk", revenue.write, {"status": "not_significant", "justification": "Small"})
        self.assertCode("revenue-fraud-link-locked", revenue.write, {"risk_ids": [(3, self.risk("revenue_fraud").id)]})
        action = revenue.action_change_status()
        self.assertEqual(action["tag"], "display_notification")
        # management override stays pervasive: on no account
        self.assertFalse(self.env["ea.audit.risk.index"].sudo().search([("risk_id", "=", self.risk("mgmt_override").id)]))

    def test_a_risk_picked_on_the_list_is_the_registers_link_and_locks_the_row(self):
        self.import_tb()
        risk = self.as_staff.add_risk("Doubtful receivables")
        receivables = self.row("E")
        self.assertEqual(receivables.status, "not_significant")
        receivables.write({"risk_ids": [(4, risk.id)]})
        receivables = self.row("E")
        self.assertEqual(receivables.risk_ids, risk)
        self.assertEqual(receivables.status, "significant")
        self.assertEqual(risk.sudo().index_link_ids.mapped("index_code"), ["E"])
        self.assertEqual(self.trail("risk_linked"), ["Risk linked to E from the significant accounts: Doubtful receivables"])
        # unpicked: the link goes, the row follows its default again
        receivables.write({"risk_ids": [(6, 0, [])]})
        receivables = self.row("E")
        self.assertFalse(risk.sudo().index_link_ids)
        self.assertEqual(receivables.status, "not_significant")
        self.assertEqual(len(self.trail("risk_unlinked")), 1)
        # a risk of another file, or a rebutted one, cannot be picked
        other = self.make_engagement(year=2024)
        foreign = self.env["ea.audit.risk"].sudo().create({"engagement_id": other.id, "description": "Another file's risk"})
        self.assertCode("not-found", receivables.write, {"risk_ids": [(4, foreign.id)]})

    def test_an_old_not_significant_decision_is_dormant_while_a_risk_is_linked(self):
        self.import_tb()
        risk = self.as_staff.add_risk("Cut-off")
        receivables = self.row("E")
        receivables.write({"status": "not_significant"})
        receivables.write({"risk_ids": [(4, risk.id)]})
        receivables = self.row("E")
        self.assertEqual(receivables.status, "significant")
        self.assertEqual(receivables.sudo().decision, "not_significant")
        self.assertFalse(receivables.unjustified)

    def test_an_approved_rebuttal_frees_revenue(self):
        self.import_tb()
        fraud = self.risk("revenue_fraud")
        fraud.with_user(self.manager).propose_rebuttal("Fixed-fee contracts, no bonus on revenue.")
        self.assertEqual(self.row("UA").status, "significant")
        fraud.with_user(self.partner).approve_rebuttal()
        revenue = self.row("UA")
        self.assertFalse(revenue.risk_ids)
        self.assertEqual(revenue.status, revenue.default_status)
        # the sync does not put a rebutted risk back on revenue
        self.engagement.sudo()._ea_sync_significance()
        self.assertFalse(self.row("UA").risk_ids)
        lines = self.trail("rebuttal_proposed") + self.trail("risk_rebutted")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("Rebuttal of the presumed revenue-fraud risk approved by"))

    def test_an_open_file_without_the_link_gets_it_and_an_archived_one_is_left_alone(self):
        self.import_tb()
        link = self.env["ea.audit.risk.index"].sudo().search([("risk_id", "=", self.risk("revenue_fraud").id)])
        link.unlink()
        self.assertTrue(self.engagement.sudo()._ea_link_revenue_fraud())
        self.assertFalse(self.engagement.sudo()._ea_link_revenue_fraud())
        self.env["ea.audit.risk.index"].sudo().search([("risk_id", "=", self.risk("revenue_fraud").id)]).unlink()
        self.engagement.sudo().phase = "archived"
        self.assertFalse(self.engagement.sudo()._ea_link_revenue_fraud())
