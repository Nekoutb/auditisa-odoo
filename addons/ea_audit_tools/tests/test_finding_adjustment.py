from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestFindingAdjustment(ToolsCase):
    """Owner's mock-up of 2026-11-16 ("mock-finding-adj"): a misstatement carries its adjustment,
    booked from the finding onto the summary of audit differences."""

    LINES = [
        {"account": "6033", "label": "Shortage of one transformer", "debit": "8400000", "credit": ""},
        {"account": "32", "label": "Inventories of materials", "debit": "", "credit": "8400000"},
    ]

    def misstatement(self, amount=8400000, **kwargs):
        return self.b5("Transformer 250 kVA: one unit short at the count", amount=amount, **kwargs)["finding"]

    def page_row(self, finding, actor=None):
        page = (actor or self.as_staff).ea_findings_page()
        return next(f for f in page["findings"] if f["id"] == finding.id)

    def entries(self, finding):
        return self.env["ea.audit.sad.entry"].sudo().search([("misstatement_id", "=", finding.sudo().misstatement_id.id)], order="id")

    def test_the_draft_starts_from_the_raised_accounts_and_shows_its_effect(self):
        finding = self.misstatement(dr_account="6033", cr_account="32")
        adj = self.page_row(finding)["adjustment"]
        self.assertEqual([line["account"] for line in adj["lines"]], ["6033", "32"])
        self.assertTrue(adj["balanced"] and adj["canBook"] and not adj["booked"])
        self.assertEqual(adj["nature"], "factual")
        self.assertEqual(adj["effect"], {"profit": "(8,400,000)", "assets": "(8,400,000)", "liabilities": "—", "equity": "(8,400,000)"})
        # a matter or a deficiency has no adjustment
        matter = self.as_staff.route_finding("b4", "A matter")["finding"]
        self.assertFalse(self.page_row(matter)["adjustment"])
        self.assertCode("adjustment-misstatement", matter.ea_save_adjustment, lines=self.LINES)

    def test_booking_writes_the_summary_line_from_the_finding(self):
        finding = self.misstatement(amount=100)
        source_entry = self.entries(finding)
        self.assertEqual(len(source_entry), 1)
        self.as_staff.ea_findings_page_adjust(finding.id, self.LINES, "judgmental")
        self.assertEqual(finding.sudo().misstatement_id.mtype, "judgmental")
        self.assertFalse(finding.sudo().adjustment_booked)
        self.as_staff.ea_findings_page_book(finding.id)
        entry = self.entries(finding)
        self.assertEqual(entry, source_entry)  # updated, not duplicated
        self.assertEqual(
            (entry.dr_account, entry.dr_amount, entry.cr_account, entry.cr_amount, entry.mtype),
            ("6033", 8400000, "32", 8400000, "judgmental"),
        )
        item = finding.sudo().misstatement_id
        self.assertEqual((item.amount, item.accounts), (8400000, "Dr 6033 / Cr 32"))
        # the line links back to the finding and keeps the finding's own source paper
        self.assertEqual(entry.source_finding_id, finding.sudo())
        self.assertEqual(entry.source_label, "E4.1")
        adj = self.page_row(finding)["adjustment"]
        self.assertTrue(adj["booked"])
        self.assertIn("AD-01", adj["bookedText"])
        # locked once booked: corrections are made on the summary
        self.assertCode("adjustment-booked", self.as_staff.ea_findings_page_adjust, finding.id, self.LINES, None)
        self.assertCode("adjustment-booked", self.as_staff.ea_findings_page_book, finding.id)
        entry.with_user(self.staff).write({"corrected": True})
        self.assertTrue(item.corrected)
        # the summary still takes no typed line
        self.assertCode("sad-from-papers", self.env["ea.audit.sad.entry"].with_user(self.staff).create, {
            "engagement_id": self.engagement.id, "finding": "Typed", "dr_account": "601", "dr_amount": 1,
        })

    def test_an_entry_of_several_lines_books_one_summary_line_per_pair(self):
        finding = self.misstatement(amount=150)
        self.as_staff.ea_findings_page_adjust(finding.id, [
            {"account": "6011", "label": "a", "debit": 100, "credit": 0},
            {"account": "6033", "label": "b", "debit": 50, "credit": 0},
            {"account": "401", "label": "c", "debit": 0, "credit": 150},
        ], None)
        self.as_staff.ea_findings_page_book(finding.id)
        rows = [(e.dr_account, e.cr_account, e.dr_amount) for e in self.entries(finding)]
        self.assertEqual(rows, [("6011", "401", 100), ("6033", "401", 50)])
        self.assertEqual(finding.sudo().misstatement_id.amount, 150)
        self.assertEqual(self.page_row(finding)["sad"], "AD-01")

    def test_the_booking_rules(self):
        finding = self.misstatement(amount=10)
        self.assertCode("adjustment-line", self.as_staff.ea_findings_page_adjust, finding.id, [
            {"account": "601", "debit": 5, "credit": 5},
        ], None)
        self.assertCode("adjustment-line", self.as_staff.ea_findings_page_adjust, finding.id, [{"account": "601", "debit": -5}], None)
        self.assertCode("invalid-type", self.as_staff.ea_findings_page_adjust, finding.id, None, "disclosure")
        # unbalanced: saved as a draft, refused at booking
        self.as_staff.ea_findings_page_adjust(finding.id, [
            {"account": "601", "debit": 10}, {"account": "401", "credit": 9},
        ], None)
        adj = self.page_row(finding)["adjustment"]
        self.assertFalse(adj["balanced"] or adj["canBook"])
        self.assertCode("adjustment-unbalanced", self.as_staff.ea_findings_page_book, finding.id)
        # a line without its account
        self.as_staff.ea_findings_page_adjust(finding.id, [{"account": "", "debit": 10}, {"account": "401", "credit": 10}], None)
        self.assertCode("adjustment-line", self.as_staff.ea_findings_page_book, finding.id)
        # roles
        self.assertCode("read-only-role", self.as_reader.ea_findings_page_adjust, finding.id, self.LINES, None)
        self.assertCode("read-only-role", self.as_reader.ea_findings_page_book, finding.id)

    def test_the_adjustment_speaks_french(self):
        finding = self.misstatement(dr_account="6033", cr_account="32")
        french = self.engagement.with_user(self.staff).with_context(lang="fr_FR")
        row = next(f for f in french.ea_findings_page()["findings"] if f["id"] == finding.id)
        self.assertTrue(row["adjustment"]["effectText"].startswith("Résultat "))
        self.assertIn("Capitaux propres", row["adjustment"]["effectText"])
