"""The review of the summary of audit differences (owner's mock-up of 2026-11-17, "wp-finding-sad"):
every adjustment arrives "To review"; a reviewer posts it, or writes a review note that sends it
back to the preparer; a posted adjustment is read-only until it is unposted; the preparer never
posts their own. The effect table and the client copy read the posted lines."""
import io

from odoo.tests import tagged

from .common import ToolsCase
from .test_procedure_execution import ExecutionCase

LINES = [
    {"heading": "expenditure", "label": "Inventory shortage written off", "debit": 8400000},
    {"heading": "current_assets", "label": "Inventories reduced", "credit": 8400000},
]
DEPRECIATION = [
    {"heading": "expenditure", "label": "Depreciation under-charged", "debit": 3150000},
    {"heading": "non_current_assets", "label": "Vehicles", "credit": 3150000},
]


@tagged("post_install", "-at_install")
class TestSadReview(ToolsCase):
    def adjusted(self, title="Transformer short at the count", lines=LINES, actor=None):
        actor = actor or self.as_staff
        amount = lines[0]["debit"]
        finding = self.b5(title, amount=amount, actor=actor)["finding"]
        actor.ea_findings_page_adjust(finding.id, lines, None)
        return finding, self.entry(finding)

    def entry(self, finding):
        return self.env["ea.audit.sad.entry"].sudo().search([("misstatement_id", "=", finding.sudo().misstatement_id.id)], limit=1)

    def row(self, entry, actor=None):
        review = (actor or self.as_manager).ea_sad_page()["review"]
        return next(r for r in review["rows"] if r["id"] == entry.id)

    def bodies(self):
        return self.engagement.sudo().message_ids.mapped("body")

    def test_a_reviewer_posts_and_unposts(self):
        finding, entry = self.adjusted()
        row = self.row(entry)
        self.assertEqual((row["status"], row["no"], row["canPost"], row["canNote"]), ("to_review", "AD-01", True, True))
        # the preparer, a staff member, does not review
        self.assertCode("requires-senior", self.as_staff.ea_sad_page_review, entry.id, "post")
        self.assertFalse(self.row(entry, self.as_staff)["canPost"])
        self.as_manager.ea_sad_page_review(entry.id, "post")
        self.assertEqual((entry._ea_review_status(), entry.reviewed_by_id), ("posted", self.manager))
        self.assertTrue(entry.reviewed_at)
        row = self.row(entry)
        self.assertEqual((row["status"], row["canPost"], row["canUnpost"]), ("posted", False, True))
        self.assertIn(self.manager.name, row["postedText"])
        self.assertTrue(any("sad_line_posted" in body for body in self.bodies()))
        self.assertCode("sad-posted", self.as_manager.ea_sad_page_review, entry.id, "post")
        # posted: read-only on the paper, but "corrected by management" stays available
        self.assertCode("adjustment-posted", self.as_staff.ea_findings_page_adjust, finding.id, LINES, None)
        self.assertCode("adjustment-posted", self.as_staff.ea_findings_page_adjust, finding.id, None, "projected")
        adj = next(f for f in self.as_staff.ea_findings_page()["findings"] if f["id"] == finding.id)["adjustment"]
        self.assertTrue(adj["posted"] and not adj["canSend"])
        self.as_staff.ea_sad_page_entry_save(entry.id, {"corrected": True})
        self.assertTrue(finding.sudo().misstatement_id.corrected)
        # unposted (logged), it can change again
        self.as_manager.ea_sad_page_review(entry.id, "unpost")
        self.assertEqual(entry._ea_review_status(), "to_review")
        self.assertFalse(entry.reviewed_by_id)
        self.assertTrue(any("sad_line_unposted" in body for body in self.bodies()))
        self.assertCode("sad-not-posted", self.as_manager.ea_sad_page_review, entry.id, "unpost")
        self.as_staff.ea_findings_page_adjust(finding.id, DEPRECIATION, None)
        self.assertEqual(entry.cr_caption_effective, "non_current_asset")

    def test_no_self_review(self):
        """The senior who raised and saved the adjustment cannot post it; the manager can."""
        _finding, entry = self.adjusted(actor=self.engagement.with_user(self.senior))
        as_senior = self.engagement.with_user(self.senior)
        self.assertCode("sad-self-review", as_senior.ea_sad_page_review, entry.id, "post")
        self.assertCode("sad-self-review", as_senior.ea_sad_page_review, entry.id, "note", "Look again")
        row = self.row(entry, as_senior)
        self.assertFalse(row["canPost"])
        self.assertTrue(row["hint"])
        # whoever saves the adjustment counts as its preparer too
        finding2, entry2 = self.adjusted("Depreciation", DEPRECIATION)
        as_senior.ea_findings_page_adjust(finding2.id, LINES, None)
        self.assertCode("sad-self-review", as_senior.ea_sad_page_review, entry2.id, "post")
        self.as_manager.ea_sad_page_review(entry.id, "post")
        self.assertEqual(entry._ea_review_status(), "posted")

    def test_a_review_note_sends_it_back_to_the_preparer(self):
        finding, entry = self.adjusted()
        self.as_manager.ea_sad_page_review(entry.id, "note", "Use the rate in the depreciation policy.")
        note = entry.review_note_id
        self.assertEqual((note.state, note.author_id), ("open", self.manager))
        # on the line's paper, C1.1 when it has none
        self.assertEqual(note.file_item_id.code, entry.file_item_id.code or "C1.1")
        self.assertIn("AD-01", note.body)
        self.assertEqual(entry._ea_review_status(), "note")
        row = self.row(entry)
        self.assertEqual((row["status"], row["canPost"], row["canClear"]), ("note", False, True))
        self.assertIn("depreciation policy", row["note"]["body"])
        self.assertCode("sad-note-open", self.as_manager.ea_sad_page_review, entry.id, "post")
        # the preparer sees it on the paper and corrects the adjustment
        adj = next(f for f in self.as_staff.ea_findings_page()["findings"] if f["id"] == finding.id)["adjustment"]
        self.assertEqual(adj["status"], "note")
        self.assertIn("depreciation policy", adj["note"]["body"])
        self.as_staff.ea_findings_page_adjust(finding.id, DEPRECIATION, None)
        self.assertEqual(entry._ea_review_status(), "note")
        # the note is cleared under the review notes' own rules, then the line can be posted
        self.assertFalse(self.row(entry, self.as_staff)["canClear"])
        self.as_manager.ea_sad_page_review(entry.id, "clear")
        self.assertEqual((note.state, entry._ea_review_status()), ("cleared", "to_review"))
        self.as_manager.ea_sad_page_review(entry.id, "post")
        self.assertEqual(entry._ea_review_status(), "posted")

    def test_who_may_not_review(self):
        _finding, entry = self.adjusted()
        self.assertCode("read-only-role", self.as_reader.ea_sad_page_review, entry.id, "post")
        self.assertCode("eqr-read-only", self.as_eqr.ea_sad_page_review, entry.id, "post")
        self.assertCode("forbidden", self.as_manager.ea_sad_page_review, entry.id, "delete")
        self.assertCode("not-found", self.as_manager.ea_sad_page_review, 0, "post")

    def test_the_effect_table_and_the_client_copy_read_the_posted_lines(self):
        import openpyxl

        _f1, first = self.adjusted()
        _f2, second = self.adjusted("Depreciation under-charged", DEPRECIATION)
        self.as_manager.ea_sad_page_review(second.id, "post")
        review = self.as_manager.ea_sad_page()["review"]
        self.assertEqual(review["counts"], {"all": 2, "to_review": 1, "note": 0, "posted": 1})
        effect = {row["heading"]: (row["all"], row["posted"]) for row in review["effect"]}
        self.assertEqual(effect["Non-current assets"], ("(3,150,000)", "(3,150,000)"))
        self.assertEqual(effect["Current assets"], ("(8,400,000)", "—"))
        self.assertEqual(effect["Expenditure"], ("11,550,000", "3,150,000"))
        self.assertEqual(effect["Equity (profit for the year)"], ("(11,550,000)", "(3,150,000)"))
        self.assertEqual(len(review["effect"]), 7)
        # the uncorrected total against materiality still counts every adjustment
        self.assertEqual(self.engagement.sudo()._ea_evaluate_b5()["uncorrectedTotal"], 11550000)
        filename, content = self.as_manager.ea_export_xlsx("sad_client")
        self.assertTrue(filename.startswith("SAD-client-"))
        sheet = openpyxl.load_workbook(io.BytesIO(content)).active
        values = [cell for row in sheet.iter_rows(values_only=True) for cell in row if cell]
        self.assertIn("Depreciation under-charged", values)
        self.assertNotIn("Transformer short at the count", values)
        self.assertEqual(self.as_manager.ea_sad_page_open("action_export_sad_client")["url"], "/ea_audit_tools/export/sad_client/%d" % self.engagement.id)
        self.assertEqual(first._ea_review_status(), "to_review")


@tagged("post_install", "-at_install")
class TestFindingFromThePaper(ExecutionCase):
    """At the bottom of a procedure's paper: 1. Finding, 2. Adjustment to book. The finding is in
    the Findings tool with a link back to its paper and procedure."""

    def test_finding_and_adjustment_on_the_paper(self):
        proc = self.proc("E-M4")
        page = self.as_staff.ea_proc_finding(
            proc.id, "Allowance understated", 5000, "misstatement", True, None, None, None, None, "factual",
            "Ageing of the Douala customers: three invoices over a year old, not provided for.",
        )
        f = page["findings"][0]
        self.assertIn("Douala", f["detail"])
        self.assertEqual(f["adjustment"]["status"], "to_review")
        self.assertFalse(f["adjustment"]["canSend"])  # headings still to pick
        page = self.as_staff.ea_proc_finding_detail(proc.id, f["id"], "Seen at the Douala branch.")
        self.assertEqual(page["findings"][0]["detail"], "Seen at the Douala branch.")
        page = self.as_staff.ea_proc_adjust(proc.id, f["id"], [
            {"heading": "expenditure", "label": "Allowance", "debit": 5000},
            {"heading": "current_assets", "label": "Receivables", "credit": 5000},
        ], "judgmental")
        adj = page["findings"][0]["adjustment"]
        self.assertTrue(adj["canSend"])
        self.assertEqual((adj["status"], adj["nature"]), ("to_review", "judgmental"))
        self.assertIn("AD-01", adj["statusText"])
        row = self.as_manager.ea_sad_page()["review"]["rows"][0]
        self.assertEqual((row["paper"], row["canOpen"]), ("E-M4", True))
        action = self.as_manager.ea_sad_page_open("source", row["id"])
        self.assertEqual(action["params"]["procedure_id"], proc.id)
        # posted: read-only on the paper
        self.as_manager.ea_sad_page_review(row["id"], "post")
        self.assertTrue(self.as_staff.ea_procedure_paper(proc.id)["findings"][0]["adjustment"]["posted"])
        self.assertCode("adjustment-posted", self.as_staff.ea_proc_adjust, proc.id, f["id"], [
            {"heading": "expenditure", "debit": 1}, {"heading": "current_assets", "credit": 1},
        ], None)
        # a finding of another paper is refused here
        other = self.proc("E-M1")
        self.assertCode("not-found", self.as_staff.ea_proc_adjust, other.id, f["id"], [], None)

    def test_every_paper_finding_is_in_the_findings_tool_with_its_source(self):
        proc = self.proc("E-M4")
        self.as_staff.ea_proc_finding(proc.id, "Allowance understated", 5000, "misstatement", True)
        self.as_staff.ea_proc_finding(proc.id, "Approval missing", None, "deficiency")
        raised = self.env["ea.audit.finding"].sudo().search([
            ("source_model", "=", "ea.audit.designed.procedure"), ("source_id", "=", proc.id),
        ])
        self.assertEqual(len(raised), 2)
        rows = {r["id"]: r for r in self.as_staff.ea_findings_page()["findings"]}
        for finding in raised:
            self.assertEqual(rows[finding.id]["sourceProc"], "E-M4")
            self.assertEqual(rows[finding.id]["paper"], proc.file_item_id.code)
            action = self.as_staff.ea_findings_page_open("source", finding.id)
            self.assertEqual((action["tag"], action["params"]["procedure_id"]), ("ea_audit_tools.procedure_paper", proc.id))
        # a finding raised elsewhere has no procedure to go back to
        other = self.as_staff.route_finding("b4", "A matter")["finding"]
        self.assertEqual(rows.get(other.id, {"sourceProc": ""})["sourceProc"], "")
        self.assertCode("not-found", self.as_staff.ea_findings_page_open, "source", other.id)
