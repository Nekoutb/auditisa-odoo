import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import PaperCase

_PK_OOXML = b"PK\x03\x04 fake [Content_Types].xml"


@tagged("post_install", "-at_install")
class TestReviewNotes(PaperCase):
    def raise_note(self, user=None, code="P3.1", body="Tighten this."):
        return self.Note.browse(self.item(self.engagement, code).with_user(user or self.senior).add_review_note(body))

    def test_a_note_needs_a_body_and_a_member_on_an_open_file(self):
        item = self.item(self.engagement, "P3.1")
        self.assertCode("body-required", item.with_user(self.senior).add_review_note, "  ")
        # uat3 B01: a task of another engagement is out of reach
        self.assertCode("not-on-this-engagement", item.with_user(self.outsider).add_review_note, "x")
        self.engagement.sudo().phase = "archived"
        self.assertCode("archived", item.with_user(self.senior).add_review_note, "x")

    def test_addressed_to_the_active_preparer_else_the_owner(self):
        item = self.item(self.engagement, "P3.1")
        item.with_user(self.manager).assign_tasks(self.senior.id, "preparer")
        self.assertEqual(self.raise_note(self.manager).assignee_id, self.senior)
        self.complete(self.staff, "P3.1")
        self.sign(self.staff, self.engagement, "P3.1", "preparer")
        self.assertEqual(self.raise_note(self.manager).assignee_id, self.staff)

    def test_the_eqr_raises_notes_on_the_teams_work(self):
        self.seat(self.engagement, self.eqr, "eqr_reviewer")
        self.assertEqual(self.raise_note(self.eqr).author_id, self.eqr)

    def test_the_preparer_replies_and_the_reviewer_clears(self):
        # UAT B19
        self.complete(self.manager, "P3.1")
        self.sign(self.manager, self.engagement, "P3.1", "preparer")
        note = self.raise_note(self.senior)
        note.with_user(self.manager).respond("Expanded.")
        self.assertEqual(note.state, "open")
        self.assertIn("Expanded.", note.response)
        self.assertCode("response-required", note.with_user(self.manager).respond, " ")
        self.assertCode("not-preparer-clears", note.with_user(self.manager).clear, "Done")
        self.assertEqual(note.state, "open")

    def test_who_may_clear(self):
        note = self.raise_note(self.senior)
        self.assertCode("requires-manager-or-author", note.with_user(self.staff).clear)
        self.assertCode("not-on-this-engagement", note.with_user(self.outsider).clear)
        self.assertCode("read-only-role", note.with_user(self.reader).clear)
        # the author may always withdraw their own
        note.with_user(self.senior).clear()
        self.assertEqual(note.state, "cleared")
        self.assertEqual(note.cleared_by_id, self.senior)
        other = self.raise_note(self.staff)
        other.with_user(self.manager).clear("Point resolved.")
        self.assertEqual(other.state, "cleared")
        self.assertIn("Point resolved.", other.response)

    def test_notes_are_never_deleted_or_written_directly(self):
        note = self.raise_note(self.senior)
        with self.assertRaises(AccessError):
            note.with_user(self.manager).unlink()
        with self.assertRaises(AccessError):
            note.with_user(self.manager).write({"state": "cleared"})

    def test_open_notes_feed_the_gates(self):
        self.raise_note(self.senior, "P1.1")
        self.raise_note(self.senior, "P3.1")
        engagement = self.engagement.sudo()
        self.assertEqual(engagement._ea_open_review_notes(["P1.%"]), (1, ["P1.1"]))
        self.assertEqual(engagement._ea_open_review_notes([]), (2, ["P1.1", "P3.1"]))
        gate = next(g for g in engagement._ea_acceptance_gates() if g["key"] == "review_notes_cleared")
        self.assertFalse(gate["ok"])

    def test_the_team_reads_notes_and_outsiders_do_not(self):
        note = self.raise_note(self.senior)
        self.assertEqual(note.with_user(self.staff).body, "Tighten this.")
        with self.assertRaises(AccessError):
            note.with_user(self.outsider).read(["body"])


@tagged("post_install", "-at_install")
class TestSectionConclusion(PaperCase):
    def setUp(self):
        super().setUp()
        self.e41 = self.item(self.engagement, "E4.1")

    def row(self):
        return self.Conclusion.sudo().search([("file_item_id", "=", self.e41.id)])

    def test_saves_on_execution_tasks_only_with_a_conclusion(self):
        staff = self.e41.with_user(self.staff)
        self.assertCode("conclusion-required", staff.save_section_conclusion, "  ")
        self.assertCode("not-found", self.item(self.engagement, "P3.1").with_user(self.staff).save_section_conclusion, "x")
        staff.save_section_conclusion("Concluded.", False)
        self.assertEqual(self.row().prepared_by_id, self.staff)

    def test_refused_while_planning_is_open(self):
        self.set_phase(self.engagement, "planning")
        self.assertCode("planning-open", self.e41.with_user(self.staff).save_section_conclusion, "x")

    def test_objectives_achieved_needs_procedures_or_a_rationale(self):
        # UAT B45
        staff = self.e41.with_user(self.staff)
        self.assertCode("no-procedures-rationale-required", staff.save_section_conclusion, "x", True)
        staff.save_section_conclusion("x", True, "No procedure: immaterial balance.")
        self.assertEqual(self.row().no_procedures_rationale, "No procedure: immaterial balance.")
        self.patch(
            type(self.env["ea.audit.file.item"]), "_ea_program_step_counts",
            lambda _self: {"retained": 2, "open": 1},
        )
        self.assertCode("steps-open", staff.save_section_conclusion, "x", True)
        # the review signs over the same evidence rule
        self.assertCode("steps-open", self.e41.with_user(self.senior).review_section_conclusion)

    def test_review_rules(self):
        self.e41.with_user(self.senior).save_section_conclusion("x", False)
        self.assertCode("self-review", self.e41.with_user(self.senior).review_section_conclusion)
        self.assertCode("requires-senior", self.e41.with_user(self.staff).review_section_conclusion)
        self.assertCode("not-on-team-to-sign", self.e41.with_user(self.partner2).review_section_conclusion)
        self.assertCode("forbidden", self.e41.with_user(self.manager).review_section_conclusion, True)
        self.e41.with_user(self.manager).review_section_conclusion()
        self.assertEqual(self.row().reviewed_by_id, self.manager)
        self.e41.with_user(self.partner).review_section_conclusion(True)
        self.assertEqual(self.row().partner_reviewed_by_id, self.partner)

    def test_the_reviewer_signs_only_after_the_conclusion_is_reviewed(self):
        # UAT B149
        self.outputs_exist()
        self.e41.with_user(self.staff).save_section_conclusion("x", False)
        self.sign(self.staff, self.engagement, "E4.1", "preparer")
        self.assertCode("review-conclusion-first", self.sign, self.senior, self.engagement, "E4.1", "reviewer")
        self.e41.with_user(self.senior).review_section_conclusion()
        self.assertEqual(self.sign(self.senior, self.engagement, "E4.1", "reviewer"), "reviewer")

    def test_rewriting_it_clears_reviews_and_voids_signatures(self):
        self.outputs_exist()
        self.e41.with_user(self.staff).save_section_conclusion("First text", False)
        self.e41.with_user(self.senior).review_section_conclusion()
        self.sign(self.staff, self.engagement, "E4.1", "preparer")
        self.sign(self.senior, self.engagement, "E4.1", "reviewer")
        self.e41.with_user(self.staff).save_section_conclusion("Second text", False)
        self.assertFalse(self.row().reviewed_by_id)
        self.assertFalse(self.active("E4.1"))

    def test_eqr_is_read_only_here(self):
        self.seat(self.engagement, self.eqr, "eqr_reviewer")
        self.assertCode("eqr-read-only", self.e41.with_user(self.eqr).save_section_conclusion, "x")


@tagged("post_install", "-at_install")
class TestEvidence(PaperCase):
    def row(self, row_id):
        return self.Attachment.sudo().browse(row_id)

    def test_evidence_uploaded_after_p_and_r_voids_both_and_is_on_the_trail(self):
        # uat2 B10
        self.signed_paper()
        self.upload(self.staff, "P3.1", "late-addition.txt", b"late")
        self.assertFalse(self.active())
        bodies = self.engagement.sudo().message_ids.mapped("body")
        self.assertTrue(any("attachment_uploaded" in b for b in bodies))

    def test_rename_remove_and_restore_void_too(self):
        row = self.upload(self.staff, "P3.1")
        self.signed_paper()
        self.row(row).with_user(self.staff).rename("renamed")
        self.assertFalse(self.active())
        self.assertEqual(self.row(row).name, "renamed.txt")

    def test_versions_by_name_and_numbering_climbs_past_a_removed_chain(self):
        first = self.upload(self.staff, "P3.1")
        second = self.upload(self.staff, "P3.1", content=b"second")
        self.assertEqual((self.row(first).version, self.row(second).version), (1, 2))
        self.row(second).with_user(self.manager).remove()
        third = self.upload(self.staff, "P3.1", content=b"third")
        self.assertEqual(self.row(third).version, 3)
        live = self.Attachment._ea_payload(self.item(self.engagement, "P3.1"))["live"]
        self.assertEqual([(r["version"], len(r["history"])) for r in live], [(3, 0)])

    def test_unsafe_uploads_are_refused(self):
        staff = self.item(self.engagement, "P3.1").with_user(self.staff)
        encode = lambda b: base64.b64encode(b).decode()  # noqa: E731
        self.assertCode("executable-refused", staff.upload_attachment, "virus.exe", encode(b"MZ"))
        self.assertCode("extension-not-allowed", staff.upload_attachment, "archive.zip", encode(b"PK\x03\x04"))
        self.assertCode("no-extension", staff.upload_attachment, "README", encode(b"x"))
        self.assertCode("empty-file", staff.upload_attachment, "a.txt", "")
        self.assertCode("content-mismatch", staff.upload_attachment, "a.pdf", encode(b"not a pdf"))
        self.assertCode("not-an-office-file", staff.upload_attachment, "a.xlsx", encode(b"PK\x03\x04 plain"))
        self.assertCode("content-mismatch", staff.upload_attachment, "a.txt", "not base64!")

    def test_the_mime_comes_from_the_bytes_not_the_uploader(self):
        row = self.row(self.upload(self.staff, "P3.1", "book.xlsx", _PK_OOXML))
        self.assertEqual(row.mime, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(row.attachment_id.mimetype, row.mime)
        self.assertEqual(row.attachment_id.res_model, "ea.audit.task.attachment")
        self.assertEqual(row.attachment_id.res_id, row.id)

    def test_too_large_is_refused(self):
        from odoo.addons.ea_audit_papers.models import file_item

        self.patch(file_item, "MAX_BYTES", 4)
        self.assertCode("file-too-large", self.upload, self.staff, "P3.1", "a.txt", b"12345")

    def test_who_may_touch_evidence(self):
        self.seat(self.engagement, self.reader, "staff")
        self.assertCode("not-on-this-engagement", self.upload, self.outsider, "P3.1")
        self.assertCode("forbidden", self.upload, self.reader, "P3.1")
        row = self.row(self.upload(self.staff, "P3.1"))
        self.assertCode("forbidden", row.with_user(self.staff).remove)
        self.assertCode("forbidden", row.with_user(self.senior).remove)
        self.engagement.sudo().phase = "archived"
        self.assertCode("archived", self.upload, self.staff, "P3.1")

    def test_the_eqr_files_evidence_on_c42_only(self):
        self.seat(self.engagement, self.eqr, "eqr_reviewer")
        self.engagement.sudo()._ea_ensure_task("C4.2")
        self.assertCode("eqr-read-only", self.upload, self.eqr, "P3.1")
        self.assertTrue(self.upload(self.eqr, "C4.2"))

    def test_the_bytes_follow_the_team_rule_and_a_removed_file_is_gone(self):
        row = self.row(self.upload(self.staff, "P3.1", content=b"secret"))
        stored = row.attachment_id
        self.assertEqual(stored.with_user(self.senior).raw, b"secret")
        with self.assertRaises(AccessError):
            stored.with_user(self.outsider).read(["raw"])
        with self.assertRaises(AccessError):
            stored.with_user(self.staff).write({"raw": b"forged"})
        row.with_user(self.manager).remove()
        with self.assertRaises(AccessError):
            stored.with_user(self.senior).read(["raw"])
        row.with_user(self.manager).restore()
        self.assertEqual(stored.with_user(self.senior).raw, b"secret")

    def test_restore_window(self):
        row = self.row(self.upload(self.staff, "P3.1"))
        row.with_user(self.manager).remove()
        row.write({"deleted_at": fields.Datetime.now() - timedelta(days=31)})
        self.assertCode("restore-window-expired", row.with_user(self.manager).restore)
        self.assertFalse(self.Attachment._ea_payload(self.item(self.engagement, "P3.1"))["removed"])

    def test_rename_rules(self):
        one = self.row(self.upload(self.staff, "P3.1", "one.txt"))
        self.upload(self.staff, "P3.1", "two.txt")
        self.assertCode("name-required", one.with_user(self.staff).rename, " /:* ")
        self.assertCode("name-taken", one.with_user(self.staff).rename, "two")
        self.assertEqual(one.with_user(self.staff).rename("three"), "three.txt")


@tagged("post_install", "-at_install")
class TestTaskHeader(PaperCase):
    def test_the_client_action_a_task_row_opens(self):
        item = self.item(self.engagement, "P3.1").with_user(self.staff)
        action = item.action_open_paper()
        self.assertEqual((action["type"], action["tag"]), ("ir.actions.client", "ea_audit_paper"))
        self.assertEqual(action["params"]["file_item_id"], item.id)
        self.assertEqual(action["context"]["active_id"], item.id)

    def test_the_payload_a_renderer_needs(self):
        self.save(self.staff, "P3.1", {"key_findings": "Text"})
        payload = self.item(self.engagement, "P3.1").with_user(self.staff).get_paper_payload()
        for key in ("definition", "values", "digests", "version", "progress", "missing", "missing_parts", "readonly",
                    "locked_keys", "auto_values", "signing", "linked_tasks", "assignment", "notes", "attachments"):
            self.assertIn(key, payload)
        self.assertEqual(payload["values"]["key_findings"], "Text")
        self.assertFalse(payload["readonly"])
        self.assertTrue(payload["saved_at"])
        self.assertNotIn("eqr_reviewer", [o["role"] for o in payload["assignment"]["options"]])

    def test_payload_read_only_for_the_right_people(self):
        self.seat(self.engagement, self.reader, "staff")
        self.assertTrue(self.paper("P3.1").with_user(self.reader).get_payload()["readonly"])
        self.seat(self.engagement, self.eqr, "eqr_reviewer")
        self.assertTrue(self.paper("P3.1").with_user(self.eqr).get_payload()["readonly"])
        self.engagement.sudo().phase = "archived"
        payload = self.paper("P3.1").with_user(self.staff).get_payload()
        self.assertTrue(payload["readonly"])
        self.assertFalse(payload["assignment"]["can_assign"])

    def test_tool_and_linked_tasks(self):
        payload = self.paper("E4.1").with_user(self.staff).get_payload()
        self.assertEqual([t["code"] for t in payload["linked_tasks"]][:3], ["S3.1", "C1.1", "E6.9"])
        self.assertEqual(payload["tool_links"][0]["fr"], "Feuilles maîtresses")
        self.assertLessEqual(len(payload["linked_tasks"]), 6)

    def test_not_applicable_needs_a_reason(self):
        item = self.item(self.engagement, "P3.1")
        self.assertCode("rationale-required", item.with_user(self.senior).set_not_applicable, " ")
        self.assertCode("forbidden", item.with_user(self.staff).set_not_applicable, "Because")
        item.with_user(self.senior).set_not_applicable("x" * 600)
        self.assertTrue(item.not_applicable)
        self.assertEqual(len(item.na_reason), 500)
        self.assertEqual(item.na_by_id, self.senior)
        item.with_user(self.senior).set_not_applicable(clear=True)
        self.assertFalse(item.not_applicable)
        self.assertFalse(item.na_reason)
        self.seat(self.engagement, self.eqr, "eqr_reviewer")
        self.assertCode("eqr-read-only", item.with_user(self.eqr).set_not_applicable, "x")
