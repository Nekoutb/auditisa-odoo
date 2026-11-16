"""The completion checklist (C6.1), the assembly window and the sealed archive (C6.2): owner's
mock-ups of 2026-11-16."""
import base64
import hashlib
import io
import json
import zipfile

import psycopg2

from odoo.tests import tagged
from odoo.tools import mute_logger

from ..services.archive_seal import QUESTIONS, answer_key, note_key, verify_seal
from .common import ReportsCase


@tagged("post_install", "-at_install")
class TestCompletionChecklist(ReportsCase):
    def test_the_paper_carries_the_thirteen_questions(self):
        paper = self.engagement.sudo()._ea_checklist_paper("C6.1")
        keys = [item["key"] for section in paper._ea_unresolved()["sections"] for item in section.get("items") or []]
        for question in QUESTIONS:
            self.assertIn(question["key"], keys)
        page = self.as_senior.ea_checklist_page()
        self.assertEqual((page["questions"], page["answered"]), (13, 0))
        self.assertTrue(page["checks"])
        self.assertFalse(page["ready"])

    def test_a_note_is_required_for_every_answer(self):
        self.assertCode("note-required", self.as_senior.ea_checklist_answer, "cl01", "yes", "  ")
        self.assertCode("note-required", self.as_senior.ea_checklist_answer, "cl02", "no", "")
        self.assertCode("invalid-value", self.as_senior.ea_checklist_answer, "cl02", "maybe", "x")
        self.assertCode("invalid-key", self.as_senior.ea_checklist_answer, "zz", "yes", "x")
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).ea_checklist_answer, "cl01", "yes", "x")
        page = self.as_senior.ea_checklist_answer("cl01", "yes", "Minutes and bank statements to the report date read.")
        row = page["rows"][0]
        self.assertTrue(row["answered"] and row["ok"])
        values = self.engagement.sudo()._ea_paper_values("C6.1")
        self.assertEqual(values[answer_key("cl01")], "yes")
        self.assertTrue(values[note_key("cl01")].startswith("Minutes"))
        page = self.as_senior.ea_checklist_answer("cl02", "no", "Letter not yet signed.")
        self.assertTrue(page["rows"][1]["answered"])
        self.assertFalse(page["rows"][1]["ok"])

    def test_the_partner_signs_only_when_all_is_green(self):
        code = self.attempt(self.as_partner.ea_sign_ready)
        self.assertTrue(code.startswith("gates-failed:"))
        self.assertIn("cl01", code)
        self.ready()
        record = self.engagement.sudo()._ea_completion_record("ready_to_issue")
        self.assertTrue(record)
        self.assertEqual(record.done_by_id, self.partner)
        self.assertTrue(self.as_partner.ea_checklist_page()["signed"])

    def test_only_the_engagement_partner_signs(self):
        self.green_completion()
        self.conclude_procedures()
        self.answer_confirmations("C6.1", QUESTIONS)
        self.green_archive()
        self.assertCode("requires-partner", self.as_manager.ea_sign_ready)
        self.seat(self.engagement, self.partner2, "manager")
        self.assertCode("not-engagement-partner", self.engagement.with_user(self.partner2).ea_sign_ready)
        self.assertCode("system-key", self.as_partner.record_completion, "ready_to_issue", {})

    def test_issuing_requires_the_sign_off(self):
        self.green_completion()
        code = self.attempt(self.as_partner.issue_report, "unmodified", "2026-03-31")
        self.assertIn("ready_to_issue", code)

    def test_a_changed_answer_voids_the_sign_off(self):
        self.ready()
        self.answer("C6.1", note_key("cl05"), "A consultation is still open with the technical department.")
        page = self.as_partner.ea_checklist_page()
        self.assertTrue(page["stale"])
        self.assertFalse(page["signed"])
        self.assertIn("ready_to_issue", self.attempt(self.as_partner.issue_report, "unmodified", "2026-03-31"))


@tagged("post_install", "-at_install")
class TestAssemblyWindow(ReportsCase):
    def test_no_new_finding_after_the_report_without_a_reason(self):
        self.issued()
        create = self.env["ea.audit.finding"].sudo().create
        vals = {"engagement_id": self.engagement.id, "number": 77, "route": "c1", "title": "Late point"}
        self.assertEqual(self.attempt(create, vals), "after-report-date")
        self.assertCode("requires-manager", self.as_senior.ea_late_work_open, "Inspector's question")
        self.assertCode("reason-required", self.as_manager.ea_late_work_open, " ")
        page = self.as_manager.ea_late_work_open("The bank confirmation reply arrived after the report date.")
        self.assertTrue(page["lateOpen"])
        finding = create(vals)
        self.assertTrue(finding)
        trail = self.env["mail.message"].sudo().search([("model", "=", "ea.audit.engagement"), ("res_id", "=", self.engagement.id)])
        self.assertTrue(any("Finding recorded after the report date" in str(m.body) for m in trail))
        self.as_manager.ea_late_work_close()
        self.assertEqual(self.attempt(create, dict(vals, number=78)), "after-report-date")

    def test_the_clock_and_the_page(self):
        self.issued()
        page = self.as_partner.ea_archive_page()
        self.assertTrue(page["clock"]["overdue"])
        self.assertEqual(page["clock"]["tone"], "red")
        self.assertTrue(page["checks"][0]["ok"])  # checklist signed
        self.assertEqual(page["keptUntil"], "31/03/2036")


@tagged("post_install", "-at_install")
class TestSealedArchive(ReportsCase):
    def _archived(self):
        self.issued()
        self.green_archive()
        self.answer("E4.1", "p_work", "Done")
        item = self.item(self.engagement, "E4.1")
        attachment = self.env["ir.attachment"].sudo().create({"name": "bank.pdf", "raw": b"%PDF-1.4 bank reply"})
        self.env["ea.audit.task.attachment"].sudo().create({
            "file_item_id": item.id, "name": "bank.pdf", "version": 1, "attachment_id": attachment.id, "uploaded_by_id": self.staff.id,
        })
        self.green_archive()
        self.as_partner.ea_archive_from_page("  governance   sa ", "Inspection of the firm delayed the assembly.")
        return self.env["ea.audit.archive.seal"].sudo().search([("engagement_id", "=", self.engagement.id)])

    def test_any_team_member_archives_with_the_name_typed(self):
        self.issued()
        self.green_archive()
        self.assertCode("confirm-name-mismatch", self.as_manager.ea_archive_from_page, "Other SA", "late")
        self.assertCode("late-archive-reason", self.as_manager.ea_archive_from_page, "Governance SA", "")
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).ea_archive_from_page, "Governance SA", "late")
        page = self.as_manager.ea_archive_page()
        self.assertTrue(page["mayArchive"])
        self.assertTrue(page["canArchive"])
        self.as_manager.ea_archive_from_page("Governance SA", "Inspection of the firm delayed the assembly.")
        self.assertTrue(self.engagement.sudo().archived_at)
        manifest = self.env["ea.audit.archive.manifest"].sudo().search([("engagement_id", "=", self.engagement.id)])
        self.assertEqual(manifest.archived_by_id, self.manager)

    def test_seal_manifest_hashes_match_the_file_bytes(self):
        seal = self._archived()
        self.assertEqual(len(seal), 1)
        raw = seal.attachment_id.raw
        self.assertEqual(hashlib.sha256(raw).hexdigest(), seal.zip_sha256)
        ok, overall = verify_seal(raw)
        self.assertTrue(ok)
        self.assertEqual(overall, seal.sha256)
        self.assertEqual(self.engagement.with_user(self.reader).seal_sha256, seal.sha256)
        archive = zipfile.ZipFile(io.BytesIO(raw))
        manifest = json.loads(archive.read("manifest.json"))
        for row in manifest["files"]:
            self.assertEqual(hashlib.sha256(archive.read(row["path"])).hexdigest(), row["sha256"])
        names = archive.namelist()
        self.assertIn("evidence/E4.1/v1 bank.pdf", names)
        self.assertIn("papers/C6.1.html", names)
        self.assertIn("archive-manifest.json", names)
        self.assertTrue(any(n.startswith("documents/C2.1/") for n in names))
        self.assertEqual(manifest["papersRenderedAs"], seal.render)
        self.assertIn(seal.render, ("pdf", "html"))

    def test_download_is_team_only_and_logged(self):
        seal = self._archived()
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.outsider).download_sealed_copy)
        filename, data = self.engagement.with_user(self.reader).download_sealed_copy()
        self.assertEqual((filename, data), (seal.filename, seal.attachment_id.raw))
        log = self.env["ea.audit.archive.access"].sudo().search([("engagement_id", "=", self.engagement.id), ("kind", "=", "download")])
        self.assertEqual(log.user_id, self.reader)
        page = self.engagement.with_user(self.reader).ea_archive_page()
        self.assertTrue(page["archived"])
        self.assertTrue(any("Downloaded" in row["what"] or "téléchargée" in row["what"] for row in page["access"]))

    def test_roll_forward_from_the_archived_file_opens_the_wizard(self):
        self._archived()
        action = self.as_partner.ea_archive_page_open("method", "action_rollforward_next_year")
        self.assertEqual((action["res_model"], action["target"]), ("ea.audit.rollforward.wizard", "new"))
        self.assertEqual(action["context"]["default_source_id"], self.engagement.id)

    def test_opening_an_archived_paper_is_logged(self):
        self._archived()
        item = self.item(self.engagement, "C6.1")
        item.with_user(self.reader).get_paper_payload()
        log = self.env["ea.audit.archive.access"].sudo().search([("engagement_id", "=", self.engagement.id), ("kind", "=", "open")])
        self.assertIn("C6.1", log.mapped("what"))

    def test_addendum_after_archiving(self):
        self.issued()
        self.assertCode("not-archived", self.as_senior.add_addendum, "x")
        self._archived_again()
        self.assertCode("reason-required", self.as_senior.add_addendum, " ")
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).add_addendum, "x")
        addendum = self.as_senior.add_addendum(
            "Inspector asked for the bank reply received late", "Bank reply.pdf", base64.b64encode(b"%PDF reply").decode(),
        )
        self.assertEqual(addendum.sha256, hashlib.sha256(b"%PDF reply").hexdigest())
        self.assertEqual(addendum.attachment_id.raw, b"%PDF reply")
        self.assertCode("archived", addendum.attachment_id.unlink)
        page = self.as_partner.ea_archive_page()
        self.assertEqual(page["addenda"][0]["by"], self.senior.name)

    def _archived_again(self):
        self.green_archive()
        self.archive()

    @mute_logger("odoo.sql_db")
    def test_trigger_refuses_edits_but_takes_addenda_and_access_lines(self):
        seal = self._archived()
        addendum = self.as_senior.add_addendum("Late reply filed")
        self.engagement.with_user(self.reader).ea_archive_page()  # one opening in the access log
        self.env.flush_all()
        refused = [
            ("UPDATE ea_audit_paper_answer SET value = 'x' WHERE engagement_id = %s", self.engagement.id, "archived"),
            ("INSERT INTO ea_audit_late_work (engagement_id, reason, opened_by_id, opened_at) VALUES (%s, 'x', 1, now())", self.engagement.id, "archived"),
            ("UPDATE ea_audit_archive_addendum SET reason = 'changed' WHERE id = %s", addendum.id, "append-only"),
            ("DELETE FROM ea_audit_archive_addendum WHERE id = %s", addendum.id, "append-only"),
            ("UPDATE ea_audit_archive_seal SET sha256 = 'x' WHERE id = %s", seal.id, "append-only"),
            ("DELETE FROM ea_audit_archive_access WHERE engagement_id = %s", self.engagement.id, "append-only"),
        ]
        for sql, param, word in refused:
            with self.assertRaises(psycopg2.errors.RaiseException, msg=sql) as caught, self.cr.savepoint():
                self.cr.execute(sql, [param])
            self.assertIn(word, str(caught.exception))
        with self.cr.savepoint():
            self.cr.execute(
                "INSERT INTO ea_audit_archive_access (engagement_id, user_id, kind, what, accessed_at) VALUES (%s, %s, 'open', 'C1.1', now())",
                [self.engagement.id, self.partner.id],
            )
            self.cr.execute(
                "INSERT INTO ea_audit_archive_addendum (engagement_id, user_id, reason, added_at) VALUES (%s, %s, 'y', now())",
                [self.engagement.id, self.partner.id],
            )

    def test_legal_hold_and_retention_refuse_deletion(self):
        self._archived()
        self.assertCode("retention-not-reached", self.engagement.sudo().unlink)
        page = self.as_manager.ea_hold_from_page("Client dispute")
        self.assertTrue(page["held"])
        self.assertCode("legal-hold", self.engagement.sudo().unlink)
        self.assertCode("requires-partner", self.as_manager.ea_hold_from_page, "Settled")
        self.assertFalse(self.as_partner.ea_hold_from_page("Dispute settled")["held"])
        self.assertCode("retention-not-reached", self.engagement.sudo().unlink)
