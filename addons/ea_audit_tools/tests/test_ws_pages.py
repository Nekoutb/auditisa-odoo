"""The journal-entry and sampling worksheets (owner's mock-ups of 2026-11-16)."""
import base64

from odoo.tests import tagged

from .common import ToolsCase, to_bytes
from .test_je_selection import LEDGER as JE_LEDGER
from .test_je_selection import MAPPING as JE_MAPPING
from .test_scot_sampling import LEDGER as TOD_LEDGER
from .test_scot_sampling import MAPPING as TOD_MAPPING


@tagged("post_install", "-at_install")
class TestJePage(ToolsCase):
    def setUp(self):
        super().setUp()
        self.dataset = self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(JE_LEDGER), mapping=JE_MAPPING)["datasetId"]
        self.as_staff.gl_build_projection(self.dataset)
        action = self.as_staff.action_tool_je()
        self.assertEqual(action["tag"], "ea_audit_tools.je_page")
        self.studio = action["params"]["studio_id"]

    def page(self, actor=None):
        return self.engagement.with_user(actor or self.staff).ea_je_page(self.studio)

    def entry(self, page, number):
        return next(entry for entry in page["entries"] if entry["je"] == number)

    def test_the_page_lists_entries_with_reasons_and_counts(self):
        page = self.page()
        self.assertFalse(page["missing"])
        self.assertEqual(page["datasetId"], self.dataset)
        self.assertEqual(page["population"]["entries"], 9)
        caught = {row["key"]: row["entries"] for row in page["criteria"]}
        self.assertEqual(caught["weekend-posting"], 2)
        self.assertEqual(caught["round-amount"], 1)
        numbers = [entry["je"] for entry in page["entries"]]
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertEqual(len(numbers), page["selectedEntries"])
        ve = self.entry(page, "VE001")
        self.assertGreaterEqual(len(ve["reasons"]), 2)
        self.assertEqual(ve["amount"], 500)
        self.assertEqual(ve["status"], "to_clear")
        self.assertEqual(page["progress"]["open"], page["selectedEntries"])

    def test_a_criterion_turned_off_catches_nothing(self):
        page = self.engagement.with_user(self.staff).ea_je_toggle(self.studio, "round-amount")
        row = next(row for row in page["criteria"] if row["key"] == "round-amount")
        self.assertFalse(row["on"])
        self.assertIsNone(row["entries"])
        self.assertNotIn("RO001", [entry["je"] for entry in page["entries"]])
        with self.assertRaisesRegex(Exception, "invalid-value"):
            self.engagement.with_user(self.staff).ea_je_toggle(self.studio, "nothing")

    def test_an_entry_is_cleared_with_a_note(self):
        as_staff = self.engagement.with_user(self.staff)
        with self.assertRaisesRegex(Exception, "je-note-required"):
            as_staff.ea_je_review(self.studio, "RO001", "cleared", "  ")
        page = as_staff.ea_je_review(self.studio, "RO001", "cleared", "Invoice seen")
        entry = self.entry(page, "RO001")
        self.assertEqual((entry["status"], entry["note"]), ("cleared", "Invoice seen"))
        self.assertEqual(page["progress"]["cleared"], 1)
        with self.assertRaisesRegex(Exception, "not-found"):
            as_staff.ea_je_review(self.studio, "ZZ999", "cleared", "x")
        with self.assertRaises(Exception):
            self.engagement.with_user(self.reader2).ea_je_review(self.studio, "RO001", "to_clear")
        with self.assertRaises(Exception):
            self.env["ea.audit.je.review"].with_user(self.staff).create({"engagement_id": self.engagement.id, "je_number": "RO001"})

    def test_a_finding_is_raised_in_place(self):
        page = self.engagement.with_user(self.staff).ea_je_finding(self.studio, "NO001", "Entry without support", "b4")
        entry = self.entry(page, "NO001")
        self.assertEqual(entry["status"], "problem")
        self.assertTrue(entry["finding"])
        finding = self.env["ea.audit.finding"].sudo().search([("engagement_id", "=", self.engagement.id), ("title", "=", "Entry without support")])
        self.assertEqual(finding.route, "b4")
        self.assertEqual(finding.file_item_id.code, "E3.1")
        review = self.env["ea.audit.je.review"].sudo().search([("je_number", "=", "NO001")])
        created = self.env["ea.audit.finding"].with_user(self.staff).ea_create_from_source(
            "ea.audit.je.review", review.id, "Overstated accrual", amount=-30, finding_type="b5", trivial_confirmed=True,
        )
        self.assertEqual(created["destination"][:2], "b5")
        with self.assertRaisesRegex(Exception, "forbidden"):
            self.env["ea.audit.finding"].with_user(self.staff).ea_create_from_source("res.partner", 1, "x")

    def test_support_is_filed_on_the_entry(self):
        content = base64.b64encode(b"supplier invoice").decode()
        page = self.engagement.with_user(self.staff).ea_je_attach(self.studio, "RO001", "invoice.txt", content)
        entry = self.entry(page, "RO001")
        self.assertEqual(entry["files"], 1)
        self.assertEqual(entry["fileList"][0]["name"], "invoice.txt")
        with self.assertRaisesRegex(Exception, "file-type"):
            self.engagement.with_user(self.staff).ea_je_attach(self.studio, "RO001", "run.exe", content)

    def test_a_vanished_studio_is_replaced(self):
        page = self.engagement.with_user(self.staff).ea_je_page(999999)
        self.assertNotEqual(page["studioId"], 999999)
        self.assertEqual(page["datasetId"], self.dataset)

    def test_without_a_ledger_the_page_says_so(self):
        other = self.make_engagement(year=2026)
        page = other.with_user(self.partner).ea_je_page(False)
        self.assertEqual(page["missing"], "ledger")
        self.assertEqual(page["entries"], [])


@tagged("post_install", "-at_install")
class TestSamplingPage(ToolsCase):
    def setUp(self):
        super().setUp()
        self.approve()
        self.dataset = self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(TOD_LEDGER), mapping=TOD_MAPPING)["datasetId"]

    def test_the_entry_point_is_the_page(self):
        action = self.as_staff.action_tool_sampling()
        self.assertEqual(action["tag"], "ea_audit_tools.sampling_page")
        page = self.as_reader.ea_sampling_page()
        self.assertEqual(page["toc"], [])
        self.assertEqual(page["tod"], [])
        self.assertTrue(page["tolerable"])

    def test_a_control_sample_is_a_card_with_its_steps(self):
        scot = self.as_staff.create_scot("Ventes", "routine", "controls", "Odoo")
        wcgw = scot.add_wcgw("Facture non enregistrée", ["C"])
        control = scot.add_control("Rapprochement", control_type="manual", frequency="monthly", wcgws=wcgw)
        control.update_control({"selected_for_testing": True})
        card = self.as_staff.ea_sampling_page()["toc"][0]
        self.assertEqual([step["state"] for step in card["steps"]], ["now", "todo", "todo", "todo", "todo"])
        control.draw_toc_sample(12, 2)
        control.sudo().write({"toc_grid": {"attributes": ["a"], "rows": [{"ref": "1", "date": "", "desc": "", "results": {"a": "pass"}}]}})
        card = self.as_staff.ea_sampling_page()["toc"][0]
        self.assertEqual([step["state"] for step in card["steps"]], ["done", "done", "done", "now", "todo"])
        self.assertEqual(card["steps"][3]["label"], "1/2")
        self.assertEqual(card["rows"][0]["result"], "agreed")

    def test_a_dataset_sample_is_tested_item_by_item_then_concluded(self):
        run = self.as_staff.run_sampling(self.dataset, "random", 2, seed="abc")
        card = next(c for c in self.as_staff.ea_sampling_page()["tod"] if c["id"] == run.id)
        self.assertEqual(card["kind"], "tod")
        self.assertEqual(len(card["rows"]), 2)
        self.assertFalse(card["allTested"])
        with self.assertRaisesRegex(Exception, "sample-not-tested"):
            run.ea_sampling_conclude()
        with self.assertRaisesRegex(Exception, "invalid-value"):
            run.ea_sampling_item(card["rows"][0]["rowNo"], {"audited": "abc"})
        with self.assertRaisesRegex(Exception, "not-found"):
            run.ea_sampling_item(99999, {"audited": "1"})
        first, second = card["rows"]
        run.ea_sampling_item(first["rowNo"], {"audited": first["book"], "how": "Invoice"})
        page = run.ea_sampling_item(second["rowNo"], {"audited": second["book"] - 10})
        card = next(c for c in page["tod"] if c["id"] == run.id)
        self.assertTrue(card["allTested"])
        self.assertEqual(card["totals"]["difference"], -10)
        self.assertEqual([row["result"] for row in card["rows"]], ["agreed", "error"])
        page = run.ea_sampling_conclude()
        card = next(c for c in page["tod"] if c["id"] == run.id)
        self.assertTrue(card["concluded"])
        self.assertIsNotNone(card["projected"])
        self.assertFalse(card["exceeds"])
        with self.assertRaisesRegex(Exception, "sample-concluded"):
            run.ea_sampling_item(first["rowNo"], {"audited": 1})
        with self.assertRaisesRegex(Exception, "sample-concluded"):
            run.ea_sampling_conclude()
        with self.assertRaises(Exception):
            run.with_user(self.reader2).ea_sampling_item(first["rowNo"], {"audited": 1})

    def test_a_tod_sample_names_its_procedure(self):
        run = self.as_staff.run_sampling(self.dataset, "random", 2, seed="abc")
        page = run.ea_sampling_purpose("  Confirm the receivables  ")
        card = next(c for c in page["tod"] if c["id"] == run.id)
        self.assertEqual(card["purpose"], "Confirm the receivables")
        self.assertEqual(run.sudo().purpose, "Confirm the receivables")

    def test_a_recorded_result_is_a_card(self):
        self.as_staff.record_tod_result("C", 1000, 0, 0, 5000)
        card = self.as_staff.ea_sampling_page()["tod"][0]
        self.assertEqual(card["kind"], "tod-result")
        self.assertEqual(card["state"], "done")

    def test_documents_are_filed_on_a_sample(self):
        run = self.as_staff.run_sampling(self.dataset, "random", 2, seed="abc")
        content = base64.b64encode(b"confirmation").decode()
        self.as_staff.ea_ws_attach("ea.audit.automation.run", run.id, "confirmation.txt", content)
        card = next(c for c in self.as_staff.ea_sampling_page()["tod"] if c["id"] == run.id)
        self.assertEqual(card["files"][0]["name"], "confirmation.txt")
        with self.assertRaisesRegex(Exception, "forbidden"):
            self.as_staff.ea_ws_attach("res.partner", 1, "a.txt", content)
        with self.assertRaises(Exception):
            self.as_reader.with_user(self.reader2).ea_ws_attach("ea.audit.automation.run", run.id, "a.txt", content)

    def test_the_page_links_are_screened(self):
        self.assertEqual(self.as_staff.ea_sampling_open("action_open_sampling_wizard")["res_model"], "ea.audit.sampling.wizard")
        with self.assertRaisesRegex(Exception, "forbidden"):
            self.as_staff.ea_sampling_open("unlink")
