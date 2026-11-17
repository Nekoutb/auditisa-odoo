"""Journal entry testing (ISA 240, owner's mock-up approved 18/11): one screen, the selection read
set-based from the ledger, the test of each entry, findings and adjustments through the existing
paths, E3.1 and S5.4 done in the tool, and the reviews recorded before still readable."""
import io

from openpyxl import load_workbook

from odoo.tests import tagged

from ..services.je_testing import entry_facts
from .common import ToolsCase, to_bytes
from .test_je_selection import LEDGER, MAPPING

LINES = [
    {"heading": "revenue", "label": "Cash sale reversed", "debit": "500", "credit": ""},
    {"heading": "current_assets", "label": "Cash sale reversed", "debit": "", "credit": "500"},
]
ALL_YES = {"attr_document": "yes", "attr_approval": "yes", "attr_reason": "na", "attr_recording": "yes"}


@tagged("post_install", "-at_install")
class TestJeTesting(ToolsCase):
    def setUp(self):
        super().setUp()
        for code in ("E3.1", "S5.4"):
            self.engagement.sudo()._ea_ensure_task(code)
        self.dataset = self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(LEDGER), mapping=MAPPING)["datasetId"]
        self.as_staff.gl_build_projection(self.dataset)

    def page(self, actor=None):
        return (actor or self.as_staff).ea_jet_page()

    def row(self, page, je):
        return next(row for row in page["rows"] if row["je"] == je)

    def count(self, page, key):
        return next(c["count"] for g in page["groups"] for c in g["criteria"] if c["key"] == key)

    def paper(self, code):
        return self.item(self.engagement, code).with_user(self.partner).get_paper_payload()

    @staticmethod
    def done(payload, key):
        return bool((payload["tool_done"].get(key) or {}).get("done"))

    def test_the_tool_is_renamed_and_opens_its_one_screen(self):
        tile = self.env.ref("ea_audit_tools.tile_je_selection")
        self.assertEqual(tile.name, "Journal entry testing")
        action = self.as_staff.action_tool_je()
        self.assertEqual((action["tag"], action["name"]), ("ea_audit_tools.je_page", "Journal entry testing"))

    def test_the_selection_is_every_entry_found_by_a_criterion(self):
        page = self.page()
        self.assertTrue(page["ledger"]["ready"])
        self.assertEqual(page["ledger"]["entries"], "9")
        self.assertEqual(self.count(page, "saturday"), 2)  # VE001 and BQ002
        self.assertEqual(self.count(page, "holiday"), 1)  # HO001, 1 January
        self.assertEqual(self.count(page, "year-end"), 1)  # YE001
        self.assertEqual(self.count(page, "same-person"), 1)  # AP001, Eve approved her own entry
        self.assertEqual(self.count(page, "sunday"), 0)  # a criterion that finds nothing still counts
        self.assertIn("revenue-cash", self.row(page, "VE001")["reasons"])
        self.assertIn("vague", self.row(page, "NO001")["reasons"])
        self.assertIn("vague", self.row(page, "OD001")["reasons"])
        self.assertNotIn("RO001", [row["je"] for row in page["rows"]])  # 200 000 is not a round million
        self.assertEqual(page["totals"]["selected"], len(page["rows"]))
        self.assertEqual({row["test"] for row in page["rows"]}, {"to_test"})

    def test_the_ledger_is_read_set_based_like_the_pure_facts(self):
        engagement = self.engagement.sudo()
        dataset = self.env["ea.audit.dataset"].sudo().browse(self.dataset)
        self.env.cr.execute(
            "SELECT je_number, to_char(journal_date, 'YYYY-MM-DD') AS journal_date, journal_code, je_description, line_description, "
            "preparer, approver, reviewer, account, debit, credit FROM ea_audit_gl_line WHERE dataset_id = %s", [dataset.id],
        )
        columns = [c[0] for c in self.env.cr.description]
        pure = entry_facts([dict(zip(columns, row)) for row in self.env.cr.fetchall()])
        sql = sorted(engagement._ea_jet_facts(dataset), key=lambda e: e["je"])
        self.assertEqual(sql, pure)

    def test_the_settings_are_set_once_for_the_engagement(self):
        self.as_staff.ea_jet_save_settings({"roundStep": 100000, "holidays": [{"date": "2025-03-12", "label": "Day off"}]})
        page = self.page()
        self.assertIn("round", self.row(page, "RO001")["reasons"])
        self.assertIn("holiday", self.row(page, "RO001")["reasons"])
        self.assertEqual(self.count(page, "holiday"), 1)  # the list replaced the calendar: 1 January is no longer one
        self.assertEqual(page["settings"]["roundStep"], 100000)
        self.assertCode("not-on-this-engagement", self.as_outsider.ea_jet_save_settings, {"roundStep": 1})

    def test_a_test_concludes_the_entry(self):
        page = self.as_staff.ea_jet_save_test("HO001", {"attr_document": "yes"}, "Invoice seen [A1]")
        self.assertEqual(self.row(page, "HO001")["test"], "to_test")
        page = self.as_staff.ea_jet_save_test("HO001", ALL_YES, "Invoice seen [A1], approved by the director")
        self.assertEqual(self.row(page, "HO001")["test"], "no_exception")
        self.assertEqual(page["tests"]["HO001"]["work"], "Invoice seen [A1], approved by the director")
        page = self.as_staff.ea_jet_save_test("HO001", dict(ALL_YES, attr_approval="no"))
        self.assertEqual(self.row(page, "HO001")["test"], "exception")
        self.assertEqual(page["totals"]["exceptions"], 1)
        review = self.env["ea.audit.je.review"].sudo().search([("je_number", "=", "HO001")])
        self.assertEqual(review.status, "problem")
        self.assertCode("invalid-value", self.as_staff.ea_jet_save_test, "HO001", {"attr_document": "maybe"})
        self.assertCode("not-found", self.as_staff.ea_jet_save_test, "NOPE", ALL_YES)

    def test_a_review_recorded_before_stays_readable(self):
        self.env["ea.audit.je.review"].sudo().create({
            "engagement_id": self.engagement.id, "dataset_id": self.dataset, "je_number": "VE001", "status": "cleared", "note": "Seen",
        })
        self.env["ea.audit.je.review"].sudo().create({
            "engagement_id": self.engagement.id, "dataset_id": self.dataset, "je_number": "BQ002", "status": "problem", "note": "Wrong",
        })
        page = self.page()
        self.assertEqual(self.row(page, "VE001")["test"], "no_exception")
        self.assertEqual(self.row(page, "BQ002")["test"], "exception")
        self.assertEqual(page["tests"]["VE001"]["work"], "Seen")

    def test_a_finding_reaches_the_findings_tool_linked_to_the_entry_and_e31(self):
        page = self.as_staff.ea_jet_finding("AP001", "Entry approved by its own preparer", "deficiency")
        finding = self.env["ea.audit.finding"].sudo().search([("source_model", "=", "ea.audit.je.review")])
        self.assertEqual(len(finding), 1)
        self.assertEqual(finding.file_item_id.code, "E3.1")
        self.assertEqual(page["findings"][0]["entry"], "AP001")
        rows = self.as_staff.ea_findings_page()["findings"]
        self.assertIn(finding.id, [row["id"] for row in rows])
        self.assertEqual(page["tests"]["AP001"]["finding"], finding.reference)

    def test_an_adjustment_reaches_the_summary_of_audit_differences_waiting_for_the_reviewer(self):
        page = self.as_staff.ea_jet_adjustment_start("VE001")
        adjustment = page["tests"]["VE001"]["adjustment"]
        self.assertTrue(adjustment)
        page = self.as_staff.ea_jet_adjust("VE001", LINES, "factual")
        review = self.env["ea.audit.je.review"].sudo().search([("je_number", "=", "VE001")])
        finding = review.adjustment_finding_id
        self.assertEqual(finding.route, "b5")
        entries = self.env["ea.audit.sad.entry"].sudo().search([("misstatement_id", "=", finding.misstatement_id.id)])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries._ea_review_status(), "to_review")
        self.assertEqual(entries.dr_amount, 500)
        self.assertEqual(page["adjustments"][0]["entry"], "VE001")
        self.assertEqual(page["adjustments"][0]["amount"], "500")
        # a second click does not raise a second misstatement
        self.as_staff.ea_jet_adjustment_start("VE001")
        self.assertEqual(review.adjustment_finding_id, finding)

    def test_e31_and_s54_are_done_in_the_tool(self):
        e31 = self.paper("E3.1")
        self.assertTrue(e31["tool_card"]["action"])
        self.assertTrue(self.done(e31, "population"))
        self.assertTrue(self.done(e31, "criteria"))
        self.assertFalse(self.done(e31, "test_items"))
        s54 = self.paper("S5.4")
        self.assertTrue(self.done(s54, "criteria"))
        self.assertTrue(self.done(s54, "thresholds"))
        for row in self.page()["rows"]:
            self.as_staff.ea_jet_save_test(row["key"], ALL_YES)
        self.assertTrue(self.done(self.paper("E3.1"), "test_items"))

    def test_the_export_for_the_client_follows_the_ticked_criteria(self):
        action = self.as_staff.ea_jet_export_action(["holiday"])
        kind = action["url"].split("/")[-2]
        name, content = self.as_staff.ea_export_xlsx(kind)
        self.assertTrue(name.endswith(".xlsx"))
        sheet = load_workbook(io.BytesIO(content)).worksheets[0]
        values = [cell.value for row in sheet.iter_rows() for cell in row]
        self.assertIn("HO001", values)
        self.assertNotIn("VE001", values)
        name, content = self.as_staff.ea_export_xlsx(self.as_staff.ea_jet_export_action([])["url"].split("/")[-2])
        values = [cell.value for row in load_workbook(io.BytesIO(content)).worksheets[0].iter_rows() for cell in row]
        self.assertIn("VE001", values)

    def test_a_reader_reads_but_does_not_change(self):
        page = self.page(self.as_eqr)
        self.assertTrue(page["readonly"])
        with self.assertRaises(Exception):
            self.as_eqr.ea_jet_save_test("HO001", ALL_YES)
