from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestFindingAdjustment(ToolsCase):
    """Owner's mock-ups of 2026-11-16 and 2026-11-17 ("wp-finding-sad"): a misstatement carries its
    adjustment, by heading; saving it sends it to the summary of audit differences, "To review"."""

    LINES = [
        {"heading": "expenditure", "label": "Inventory shortage written off", "debit": "8400000", "credit": ""},
        {"heading": "current_assets", "label": "Inventories reduced", "debit": "", "credit": "8400000"},
    ]

    def misstatement(self, amount=8400000, **kwargs):
        return self.b5("Transformer 250 kVA: one unit short at the count", amount=amount, **kwargs)["finding"]

    def page_row(self, finding, actor=None):
        page = (actor or self.as_staff).ea_findings_page()
        return next(f for f in page["findings"] if f["id"] == finding.id)

    def entries(self, finding):
        return self.env["ea.audit.sad.entry"].sudo().search([("misstatement_id", "=", finding.sudo().misstatement_id.id)], order="id")

    def bodies(self):
        return self.engagement.sudo().message_ids.mapped("body")

    def test_the_draft_keeps_raised_accounts_as_information_only(self):
        finding = self.misstatement(dr_account="6033", cr_account="32")
        adj = self.page_row(finding)["adjustment"]
        self.assertEqual([(line["heading"], line["account"]) for line in adj["lines"]], [("", "6033"), ("", "32")])
        self.assertEqual([h["value"] for h in adj["headings"]], [
            "non_current_assets", "current_assets", "non_current_liabilities", "current_liabilities",
            "equity", "revenue", "expenditure",
        ])
        # balanced, but each line still to classify: nothing goes to the summary yet
        self.assertTrue(adj["balanced"])
        self.assertFalse(adj["canSend"])
        self.assertEqual(adj["nature"], "factual")
        self.assertEqual(adj["status"], "to_review")
        # a matter or a deficiency has no adjustment
        matter = self.as_staff.route_finding("b4", "A matter")["finding"]
        self.assertFalse(self.page_row(matter)["adjustment"])
        self.assertCode("adjustment-misstatement", matter.ea_save_adjustment, lines=self.LINES)

    def test_saving_sends_the_adjustment_to_the_summary_to_review(self):
        finding = self.misstatement(amount=100)
        source_entry = self.entries(finding)
        self.assertEqual(len(source_entry), 1)
        self.as_staff.ea_findings_page_adjust(finding.id, self.LINES, "judgmental")
        entry = self.entries(finding)
        self.assertEqual(entry, source_entry)  # updated, not duplicated
        self.assertEqual(
            (entry.dr_caption_effective, entry.dr_amount, entry.cr_caption_effective, entry.cr_amount, entry.mtype),
            ("expense", 8400000, "current_asset", 8400000, "judgmental"),
        )
        self.assertEqual(entry.prepared_by_id, self.staff)
        self.assertEqual(entry._ea_review_status(), "to_review")
        item = finding.sudo().misstatement_id
        self.assertEqual((item.amount, item.accounts, item.mtype), (8400000, "Dr Expenditure / Cr Current assets", "judgmental"))
        self.assertEqual(
            [(line.heading, line.debit, line.credit) for line in finding.sudo().adjustment_ids],
            [("expenditure", 8400000, 0), ("current_assets", 0, 8400000)],
        )
        adj = self.page_row(finding)["adjustment"]
        self.assertEqual(adj["effect"], {"profit": "(8,400,000)", "assets": "(8,400,000)", "liabilities": "—", "equity": "(8,400,000)"})
        self.assertIn("AD-01", adj["statusText"])
        self.assertTrue(adj["canSend"] and not adj["posted"])
        self.assertTrue(any("finding_adjustment_saved" in body for body in self.bodies()))
        # the line links back to the finding and keeps the finding's own source paper
        self.assertEqual(entry.source_finding_id, finding.sudo())
        # still editable while to review: saved again, the same line follows
        self.as_staff.ea_findings_page_adjust(finding.id, [
            {"heading": "expenditure", "debit": 500}, {"heading": "current_liabilities", "credit": 500},
        ], None)
        self.assertEqual((self.entries(finding).cr_caption_effective, self.entries(finding).dr_amount), ("current_liability", 500))
        # the summary still takes no typed line
        self.assertCode("sad-from-papers", self.env["ea.audit.sad.entry"].with_user(self.staff).create, {
            "engagement_id": self.engagement.id, "finding": "Typed", "dr_account": "601", "dr_amount": 1,
        })

    def test_an_entry_of_several_lines_is_one_adjustment_on_the_summary(self):
        finding = self.misstatement(amount=150)
        self.as_staff.ea_findings_page_adjust(finding.id, [
            {"heading": "expenditure", "label": "a", "debit": 100, "credit": 0},
            {"heading": "non_current_assets", "label": "b", "debit": 50, "credit": 0},
            {"heading": "current_liabilities", "label": "c", "debit": 0, "credit": 150},
        ], None)
        rows = [(e.dr_caption_effective, e.cr_caption_effective, e.dr_amount) for e in self.entries(finding)]
        self.assertEqual(rows, [("expense", "current_liability", 100), ("non_current_asset", "current_liability", 50)])
        self.assertEqual(finding.sudo().misstatement_id.amount, 150)
        self.assertEqual(self.page_row(finding)["sad"], "AD-01")
        review = self.as_staff.ea_sad_page()["review"]
        self.assertEqual(len(review["rows"]), 1)
        self.assertEqual(review["rows"][0]["no"], "AD-01")
        self.assertEqual([line["heading"] for line in review["rows"][0]["lines"]], ["Expenditure", "Non-current assets", "Current liabilities"])

    def test_the_saving_rules(self):
        finding = self.misstatement(amount=10)
        self.assertCode("adjustment-line", self.as_staff.ea_findings_page_adjust, finding.id, [
            {"heading": "expenditure", "debit": 5, "credit": 5},
        ], None)
        self.assertCode("adjustment-line", self.as_staff.ea_findings_page_adjust, finding.id, [{"heading": "expenditure", "debit": -5}], None)
        # accounts are no longer accepted as a heading
        self.assertCode("adjustment-line", self.as_staff.ea_findings_page_adjust, finding.id, [
            {"heading": "6033", "debit": 10}, {"heading": "current_assets", "credit": 10},
        ], None)
        self.assertCode("invalid-type", self.as_staff.ea_findings_page_adjust, finding.id, None, "disclosure")
        # unbalanced: refused, nothing saved
        self.assertCode("adjustment-unbalanced", self.as_staff.ea_findings_page_adjust, finding.id, [
            {"heading": "expenditure", "debit": 10}, {"heading": "current_liabilities", "credit": 9},
        ], None)
        self.assertFalse(finding.sudo().adjustment_ids)
        # a line without its heading
        self.assertCode("adjustment-line", self.as_staff.ea_findings_page_adjust, finding.id, [
            {"label": "no heading", "debit": 10}, {"heading": "current_liabilities", "credit": 10},
        ], None)
        # roles
        self.assertCode("read-only-role", self.as_reader.ea_findings_page_adjust, finding.id, self.LINES, None)

    def test_an_old_line_with_an_account_is_kept_and_reads_to_classify(self):
        """Lines typed before 2026-11-17 named an account and may have been booked: the data stays,
        the account is shown as information, the heading is empty until the team picks one."""
        finding = self.misstatement(amount=40)
        self.env["ea.audit.finding.adjustment"].sudo().create([
            {"engagement_id": self.engagement.id, "finding_id": finding.id, "sequence": 1, "account": "6033", "label": "old", "debit": 40, "booked": True},
            {"engagement_id": self.engagement.id, "finding_id": finding.id, "sequence": 2, "account": "32", "label": "old", "credit": 40, "booked": True},
        ])
        adj = self.page_row(finding)["adjustment"]
        self.assertEqual([(line["heading"], line["account"], line["headingLabel"]) for line in adj["lines"]], [("", "6033", ""), ("", "32", "")])
        self.assertFalse(adj["canSend"])
        lines = [dict(line, heading=heading) for line, heading in zip(adj["lines"], ("expenditure", "current_assets"))]
        self.as_staff.ea_findings_page_adjust(finding.id, lines, None)
        saved = finding.sudo().adjustment_ids
        self.assertEqual([(line.heading, line.account) for line in saved], [("expenditure", "6033"), ("current_assets", "32")])

    def test_the_adjustment_speaks_french(self):
        finding = self.misstatement(amount=100)
        self.as_staff.ea_findings_page_adjust(finding.id, self.LINES, None)
        french = self.engagement.with_user(self.staff).with_context(lang="fr_FR")
        row = next(f for f in french.ea_findings_page()["findings"] if f["id"] == finding.id)
        self.assertTrue(row["adjustment"]["effectText"].startswith("Résultat "))
        self.assertIn("Capitaux propres", row["adjustment"]["effectText"])
        self.assertIn("Charges", [h["label"] for h in row["adjustment"]["headings"]])
