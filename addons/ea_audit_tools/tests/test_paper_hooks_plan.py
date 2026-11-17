"""The planning papers' hooks (paper_hooks_plan.py): P3.2 reads the analytical procedures and the
financial analysis, P4.3 the IT applications, P5.1 the fraud risks of the register."""
from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestPlanPaperHooks(ToolsCase):
    def setUp(self):
        super().setUp()
        self.set_phase(self.engagement, "planning")
        for code in ("P3.2", "P4.3", "P5.1"):
            self.engagement.sudo()._ea_ensure_task(code)

    def payload(self, code, user=None):
        return self.item(self.engagement, code).with_user(user or self.partner).get_paper_payload()

    def test_p32_card_reads_the_trial_balance(self):
        payload = self.payload("P3.2")
        self.assertTrue(payload["layout"]["converted"])
        self.assertTrue(payload["tool_card"]["empty"])
        self.assertFalse(payload["tool_done"].get("compare", {}).get("done"))
        self.import_tb()
        self.approve()
        card = self.payload("P3.2")["tool_card"]
        self.assertFalse(card["empty"])
        self.assertEqual(len(card["facts"]), 4)
        self.assertTrue(card["rows"])
        self.assertTrue(card["action"])

    def test_p43_card_lists_the_applications(self):
        self.assertTrue(self.payload("P4.3")["tool_card"]["empty"])
        self.as_staff.create_scot("Ventes", applications="Sage 100")
        card = self.payload("P4.3")["tool_card"]
        self.assertEqual(card["rows"][0][0], "Sage 100")

    def test_p51_presumed_risks_close_their_tasks(self):
        payload = self.payload("P5.1")
        self.assertEqual(payload["layout"]["depth"], "complex")
        self.assertEqual(payload["tool_card"]["facts"][0]["value"], "2")
        self.assertTrue(payload["tool_done"]["revenue"]["done"])
        self.assertTrue(payload["tool_done"]["override"]["done"])
        self.assertIs(payload["checks"]["revenue"]["ok"], True)
        self.assertIs(payload["checks"]["override"]["ok"], True)
        self.assertNotIn("p_override", payload["missing"])
        self.assertIn("p_mgmt", payload["missing"])

    def test_p51_a_pending_rebuttal_leaves_the_task_open_and_an_approved_one_flags_the_statement(self):
        fraud = self.env["ea.audit.risk"].sudo().search([
            ("engagement_id", "=", self.engagement.id), ("presumed_type", "=", "revenue_fraud"),
        ])
        fraud.with_user(self.manager).propose_rebuttal("Fixed-price contracts, no incentive.")
        payload = self.payload("P5.1")
        self.assertFalse(payload["tool_done"]["revenue"]["done"])
        self.assertIn("p_revenue", payload["missing"])
        fraud.with_user(self.partner).approve_rebuttal()
        payload = self.payload("P5.1")
        self.assertTrue(payload["tool_done"]["revenue"]["done"])
        self.assertIs(payload["checks"]["revenue"]["ok"], False)

    def test_a_reader_still_opens_the_plan_papers(self):
        for code in ("P3.2", "P4.3", "P5.1"):
            with self.subTest(code=code):
                self.assertTrue(self.payload(code, self.reader)["tool_card"]["title"])
