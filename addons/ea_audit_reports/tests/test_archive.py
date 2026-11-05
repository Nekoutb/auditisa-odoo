import hashlib
import json
import zipfile
from datetime import date

import psycopg2

from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import ReportsCase


@tagged("post_install", "-at_install")
class TestArchiveChecklist(ReportsCase):
    """archive-checklist.test.ts."""

    def test_fresh_file(self):
        checklist = self.as_partner.archive_checklist("en")
        self.assertFalse(checklist["archived_at"])
        self.assertEqual([g["key"] for g in checklist["groups"]], ["report", "completion", "papers", "review", "assembly"])
        keys = [gate["key"] for group in checklist["groups"] for gate in group["gates"]]
        self.assertNotIn("completion_gates", keys)
        for key in ("report_issued", "sections_concluded", "risks_concluded", "papers_signed", "reviews_complete",
                    "review_notes_cleared", "review_approval", "c62_checklist", "tasks_addressed", "deficiencies_communicated"):
            self.assertIn(key, keys)
        self.assertEqual(checklist["blocking"], len([g for group in checklist["groups"] for g in group["gates"] if not g["ok"]]))
        self.assertGreater(checklist["blocking"], 0)

    def test_a_red_gate_names_its_items(self):
        checklist = self.as_partner.archive_checklist("fr")
        gates = {gate["key"]: gate for group in checklist["groups"] for gate in group["gates"]}
        self.assertFalse(gates["tasks_addressed"]["ok"])
        self.assertTrue(gates["tasks_addressed"]["items"])
        self.assertEqual(gates["tasks_addressed"]["pending"], len(gates["tasks_addressed"]["items"]))
        self.assertTrue(gates["c62_checklist"]["items"][0]["label"].startswith("C6.2"))
        self.assertTrue(gates["risks_concluded"]["items"])
        self.assertEqual(gates["report_issued"]["label"], "Rapport émis et daté")

    def test_a_green_gate_lists_nothing(self):
        gates = {gate["key"]: gate for group in self.as_partner.archive_checklist("en")["groups"] for gate in group["gates"]}
        self.assertTrue(gates["review_notes_cleared"]["ok"])
        self.assertEqual(gates["review_notes_cleared"]["items"], [])

    def test_screens_render(self):
        row = self.engagement.with_user(self.partner)
        self.assertIn("o_ea_gate", row.completion_gates_html)
        self.assertIn("Report issued" if not row.env.lang or row.env.lang.startswith("en") else "Rapport", row.archive_checklist_html)
        self.assertEqual(row.action_open_conclusion()["res_id"], self.engagement.id)


@tagged("post_install", "-at_install")
class TestArchiveGates(ReportsCase):
    def _gates(self):
        return {gate["key"]: gate for gate in self.as_partner.archive_gates()}

    def test_item_based_paper_gates(self):
        """Finding C5: a task holding work and no paper does not pass because few documents exist."""
        self.answer("E4.1", "p_work", "Fait")
        gates = self._gates()
        self.assertIn("E4.1", gates["papers_signed"]["codes"])
        self.assertIn("E4.1", gates["reviews_complete"]["codes"])
        self.signoff("E4.1", "preparer")
        gates = self._gates()
        self.assertNotIn("E4.1", gates["papers_signed"]["codes"])
        self.assertIn("E4.1", gates["reviews_complete"]["codes"])
        self.signoff("E4.1", "reviewer", self.senior)
        self.assertNotIn("E4.1", self._gates()["reviews_complete"]["codes"])

    def test_voided_signature_does_not_count(self):
        self.answer("E4.1", "p_work", "Fait")
        self.signoff("E4.1", "preparer").voided_at = "2026-01-01 00:00:00"
        self.assertIn("E4.1", self._gates()["papers_signed"]["codes"])

    def test_untouched_task_needs_a_reason(self):
        """UAT B63."""
        self.assertIn("E4.1", self._gates()["tasks_addressed"]["codes"])
        self.assertLessEqual(len(self._gates()["tasks_addressed"]["codes"]), 20)
        self.env.flush_all()
        self.env.cr.execute("UPDATE ea_audit_file_item SET na_reason = 'Sans objet' WHERE id = %s", [self.item(self.engagement, "E4.1").id])
        self.env.invalidate_all()
        self.assertNotIn("E4.1", self._gates()["tasks_addressed"]["codes"])

    def test_written_communication_of_significant_deficiencies(self):
        """C5.11, ISA 265 para 9, F037: without the date the file stays open."""
        finding = self.env["ea.audit.finding"].sudo().create({
            "engagement_id": self.engagement.id, "number": 1, "route": "c1", "title": "Déficience", "severity": "significant_deficiency",
        })
        gate = self._gates()["deficiencies_communicated"]
        self.assertFalse(gate["ok"])
        self.assertEqual((gate["pending"], gate["codes"]), (1, ["C5.11"]))
        self.env["ea.audit.deficiency.evaluation"].sudo().create({
            "engagement_id": self.engagement.id, "finding_id": finding.id, "grade": "significant_deficiency",
            "communicated_on": "2026-03-01", "recipient": "Le PCA",
        })
        finding.invalidate_recordset()
        self.assertTrue(self._gates()["deficiencies_communicated"]["ok"])

    def test_c62_and_c41_read_the_real_papers(self):
        gates = self._gates()
        self.assertFalse(gates["c62_checklist"]["ok"])
        self.assertFalse(gates["review_approval"]["ok"])


@tagged("post_install", "-at_install")
class TestArchive(ReportsCase):
    def _archived(self):
        self.issued()
        self.green_archive()
        return self.as_partner.archive_engagement()

    def test_who_may_archive(self):
        self.assertCode("archive-partner-only", self.as_manager.archive_engagement)
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).archive_engagement)
        self.seat(self.engagement, self.partner2, "manager")
        self.assertCode("not-engagement-partner", self.engagement.with_user(self.partner2).archive_engagement)

    def test_refuses_naming_the_gates(self):
        self.issued()
        code = self.attempt(self.as_partner.archive_engagement)
        self.assertTrue(code.startswith("gates-failed:"))
        self.assertIn("tasks_addressed", code)

    def test_no_report_no_archive(self):
        code = self.attempt(self.as_partner.archive_engagement)
        self.assertIn("report_issued", code)

    def test_archive_stamps_and_seals(self):
        manifest = self._archived()
        row = self.engagement.sudo()
        self.assertEqual(row.phase, "archived")
        self.assertTrue(row.archived_at)
        self.assertEqual(row.retention_until, date(2036, 3, 31))
        data = json.loads(manifest.sudo().content)
        self.assertEqual(data["manifestVersion"], 2)
        self.assertEqual(data["engagement"]["reportDate"], "2026-03-31")
        self.assertEqual(data["engagement"]["retentionUntil"], "2036-03-31")
        self.assertEqual(data["archivedBy"], self.partner.name)
        self.assertTrue(isinstance(data["risks"], list) and data["risks"])
        self.assertEqual(data["counts"]["fileItems"], len(data["fileIndex"]))
        self.assertTrue(data["documents"])
        self.assertEqual(manifest.sudo().sha256, hashlib.sha256(manifest.sudo().content.encode()).hexdigest())
        self.assertEqual(hashlib.sha256(manifest.sudo().attachment_id.raw).hexdigest(), manifest.sudo().sha256)
        self.assertTrue(manifest._ea_verify())

    def test_retention_is_fixed_at_archiving(self):
        """UAT run 2 B86: a later change of the firm's period does not move a closed file."""
        self.env.company.ea_retention_years = 15
        self._archived()
        self.assertEqual(self.engagement.sudo().retention_until, date(2041, 3, 31))
        self.env.company.ea_retention_years = 10
        self.engagement.invalidate_recordset()
        self.assertEqual(self.engagement.sudo().retention_until, date(2041, 3, 31))

    def test_python_refuses_after_archive(self):
        self._archived()
        self.assertCode("already-archived", self.as_partner.archive_engagement)
        self.assertCode("archived", self.as_senior.generate_letter, "engagement", "fr")
        self.assertCode("archived", self.as_partner.record_completion, "partner_conclusion", {"conclusion": "x"})
        self.assertCode("archived", self.as_partner.write, {"name": "x"})
        self.assertCode("archived", self.sign, self.senior, self.engagement, "E4.1", "preparer")

    @mute_logger("odoo.sql_db")
    def test_database_refuses_after_archive(self):
        manifest = self._archived()
        self.env.flush_all()
        statements = [
            ("UPDATE ea_audit_engagement SET report_date = '2020-01-01' WHERE id = %s", self.engagement.id),
            ("UPDATE ea_audit_engagement SET retention_until = '2020-01-01' WHERE id = %s", self.engagement.id),
            ("UPDATE ea_audit_risk SET status = 'identified' WHERE engagement_id = %s", self.engagement.id),
            ("UPDATE ea_audit_signoff SET voided_at = now() WHERE engagement_id = %s", self.engagement.id),
            ("DELETE FROM ea_audit_paper_answer WHERE engagement_id = %s", self.engagement.id),
            ("UPDATE ea_audit_document_version SET note = 'x' WHERE engagement_id = %s", self.engagement.id),
            ("UPDATE ea_audit_archive_manifest SET sha256 = 'x' WHERE id = %s", manifest.id),
            ("DELETE FROM ea_audit_archive_manifest WHERE id = %s", manifest.id),
        ]
        for sql, param in statements:
            with self.assertRaises(psycopg2.errors.RaiseException, msg=sql) as caught, self.cr.savepoint():
                self.cr.execute(sql, [param])
            self.assertIn("archived", str(caught.exception))

    def test_sealed_bytes(self):
        manifest = self._archived()
        self.assertCode("archived", manifest.sudo().attachment_id.unlink)
        version = self.env["ea.audit.document"].sudo().search([("engagement_id", "=", self.engagement.id)], limit=1).current_version_id
        self.assertCode("archived", version.attachment_id.sudo().write, {"name": "x"})

    def test_points_forward_stay_writable_and_roll_forward(self):
        """rollforward: C6.1 points injected in next year's file."""
        self._archived()
        self.as_senior.record_completion("points_forward", {"points": "Revoir les stocks"})
        self.assertCode("invalid-year", self.as_partner.rollforward, 2025)
        target = self.as_partner.rollforward(2026)
        self.assertEqual((target.fiscal_year, target.period_end), (2026, date(2026, 12, 31)))
        self.assertEqual(target.sudo()._ea_completion_data("points_from_prior"), {"points": "Revoir les stocks"})
        self.assertEqual(target.with_user(self.partner).points_from_prior, "Revoir les stocks")

    def test_team_hears_of_it_without_email(self):
        mails = self.env["mail.mail"].sudo().search_count([])
        self._archived()
        notices = self.env["ea.audit.notice"].sudo().search([("engagement_id", "=", self.engagement.id), ("kind", "=", "engagement_archived")])
        self.assertIn(self.staff, notices.user_id)
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mails)


@tagged("post_install", "-at_install")
class TestExportBundle(ReportsCase):
    def _bundle(self, engagement=None):
        filename, handle = (engagement or self.as_partner).export_engagement_bundle()
        self.addCleanup(handle.close)
        return filename, zipfile.ZipFile(handle)

    def test_bundle_of_an_open_file(self):
        self.as_senior.generate_letter("engagement", "fr")
        self.answer("E4.1", "p_work", "Fait")
        filename, archive = self._bundle()
        self.assertTrue(filename.startswith("auditisa-export-governance-sa-FY2025-"))
        names = archive.namelist()
        for expected in ("00-index/engagement.json", "00-index/file-index-2025.xlsx", "10-working-papers/E4.1/paper.json",
                         "70-audit-trail/activity.jsonl", "80-people/team.json", "80-people/signoffs.json", "manifest.json", "SHA256SUMS"):
            self.assertIn(expected, names)
        self.assertFalse(json.loads(archive.read("00-index/engagement.json"))["complete"])
        self.assertTrue(archive.read("00-index/file-index-2025.xlsx").startswith(b"PK"))
        document = [n for n in names if n.startswith("20-documents/P1.4/") and n.endswith("v1.docx")]
        self.assertTrue(document)

    def test_hashes_hold(self):
        _name, archive = self._bundle()
        for line in archive.read("SHA256SUMS").decode().splitlines():
            digest, path = line.split("  ", 1)
            self.assertEqual(hashlib.sha256(archive.read(path)).hexdigest(), digest)

    def test_bundle_of_an_archived_file_carries_the_manifest(self):
        self.issued()
        self.green_archive()
        self.as_partner.archive_engagement()
        _name, archive = self._bundle()
        self.assertTrue(json.loads(archive.read("00-index/engagement.json"))["complete"])
        self.assertIn("60-conclusion/archive-manifest.json", archive.namelist())

    def test_team_only_and_logged(self):
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.admin).export_engagement_bundle)
        before = self.env["mail.message"].sudo().search_count([("model", "=", "ea.audit.engagement"), ("res_id", "=", self.engagement.id)])
        self._bundle(self.engagement.with_user(self.reader))
        after = self.env["mail.message"].sudo().search_count([("model", "=", "ea.audit.engagement"), ("res_id", "=", self.engagement.id)])
        self.assertEqual(after, before + 1)
