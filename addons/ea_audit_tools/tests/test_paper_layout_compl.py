"""The completion papers in the layout of 2026-11-17 on a real engagement (group compl): the card of
C1.1 read from the summary of audit differences, the ISA 265 deficiencies behind C5.11, the open review
notes read by C4.1 and C6.2, and the going concern card on C2.2."""
from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestPaperLayoutCompl(ToolsCase):
    def setUp(self):
        super().setUp()
        self.set_phase(self.engagement, "planning")
        for code in ("S4.2", "C1.1", "C2.2", "C4.1", "C5.11", "C6.2"):
            self.engagement.sudo()._ea_ensure_task(code)

    def payload(self, code, user=None):
        return self.item(self.engagement, code).with_user(user or self.partner).get_paper_payload()

    def test_c11_card_reads_the_summary_of_audit_differences(self):
        self.approve()  # overall 112, performance 84: the threshold for uncorrected misstatements is 28
        payload = self.payload("C1.1")
        card = payload["tool_card"]
        self.assertTrue(card["title"])
        self.assertTrue(card["action"])
        self.assertEqual(card["facts"][0]["value"], "0 / 0")
        self.assertIs(payload["checks"]["immaterial"]["ok"], True)
        self.assertFalse(payload["tool_done"]["accumulate"]["done"])
        self.assertIn("p_accumulate", payload["missing"])
        # C1.1 is never documented by exception, whatever the engagement
        self.engagement.sudo().complexity = "very_simple"
        self.assertEqual(self.payload("C1.1")["layout"]["depth_reason"], "never_light")
        self.b5("Cut-off", amount=50)
        payload = self.payload("C1.1")
        self.assertEqual(payload["tool_card"]["facts"][0]["value"], "0 / 1")
        self.assertIs(payload["checks"]["immaterial"]["ok"], False)
        self.assertTrue(payload["checks"]["immaterial"]["note"])

    def test_c511_card_and_checks_read_the_deficiencies(self):
        payload = self.payload("C5.11")
        self.assertEqual(payload["tool_card"]["facts"][0]["value"], "0")
        self.assertIs(payload["checks"]["graded"]["ok"], True)
        self.assertIs(payload["checks"]["sig_written"]["ok"], True)
        self.as_staff.route_finding("c1", "Purchases not segregated", severity="deficiency")
        payload = self.payload("C5.11")
        self.assertEqual(payload["tool_card"]["facts"][0]["value"], "1")
        self.assertIs(payload["checks"]["graded"]["ok"], False)

    def test_open_review_notes_answer_c41_and_c62(self):
        self.assertIs(self.payload("C4.1")["checks"]["cleared"]["ok"], True)
        self.item(self.engagement, "S4.2").with_user(self.manager).add_review_note("Document the current ratio trend.")
        for code, key in (("C4.1", "cleared"), ("C6.2", "nothing_open")):
            check = self.payload(code)["checks"][key]
            self.assertIs(check["ok"], False, code)
            self.assertIn("S4.2", check["note"], code)

    def test_c22_shows_the_going_concern_card_and_documents_by_exception(self):
        self.engagement.sudo().complexity = "non_complex"
        payload = self.payload("C2.2")
        self.assertTrue(payload["tool_card"]["title"])
        self.assertEqual((payload["layout"]["converted"], payload["layout"]["depth"]), (True, "non_complex"))
        procs = {p["key"]: p for s in payload["definition"]["sections"] if s["kind"] == "proc" for p in s["procs"]}
        self.assertEqual(procs["extend"]["_mode"], "exception")
        self.assertEqual(procs["gc_conclude"]["_mode"], "full")
