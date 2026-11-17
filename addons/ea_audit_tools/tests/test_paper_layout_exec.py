"""The execution papers in the layout of 2026-11-17 on a real engagement (group "exec"): the cards
and the tasks done in the tool read the IT applications, the tests of controls, the next-year
ledger and the revisions of the combined risk assessment; E6.3 reads the going concern hooks of
S4.2; E6.10's checklist stays a set of required statements inside its task."""
from odoo.tests import tagged

from .common import ToolsCase

EXEC = ("E1.1", "E1.2", "E2.1", "E6.1", "E6.2", "E6.3", "E6.4", "E6.5", "E6.6", "E6.7", "E6.8", "E6.9", "E6.10")


@tagged("post_install", "-at_install")
class TestPaperLayoutExec(ToolsCase):
    def setUp(self):
        super().setUp()
        self.set_phase(self.engagement, "planning")
        for code in EXEC:
            self.engagement.sudo()._ea_ensure_task(code)

    def payload(self, code, user=None):
        return self.item(self.engagement, code).with_user(user or self.partner).get_paper_payload()

    def test_every_exec_paper_reads_converted(self):
        for code in EXEC:
            with self.subTest(code=code):
                payload = self.payload(code)
                self.assertTrue(payload["layout"]["converted"])
                self.assertTrue([tool for tool in payload["tools"] if tool["action"]], code)
                if code in ("E1.1", "E1.2", "E2.1", "E6.3", "E6.6", "E6.8"):
                    self.assertTrue(payload["tool_card"]["title"], code)
                    self.assertTrue(payload["tool_card"]["empty"] or payload["tool_card"]["facts"], code)

    def test_itgc_card_and_scope_done_in_the_tool(self):
        self.as_staff.create_scot("Ventes", applications="Sage 100")
        self.engagement.sudo()._ea_sync_it_applications()
        payload = self.payload("E1.1")
        self.assertEqual(payload["tool_card"]["rows"][0][0], "Sage 100")
        self.assertFalse(payload["tool_done"]["scope"]["done"])
        self.assertIs(payload["checks"]["scope"]["ok"], False)
        self.engagement.sudo().it_application_ids.write({"layers": "Sage 100 / SQL Server / Windows"})
        payload = self.payload("E1.1")
        self.assertTrue(payload["tool_done"]["scope"]["done"])
        self.assertEqual(payload["warnings"], [])
        self.engagement.sudo().itgc_state = "not_support"
        self.assertTrue(self.payload("E1.1")["warnings"])

    def test_tests_of_controls_card_and_tasks_done_in_the_tool(self):
        scot = self.as_staff.create_scot("Ventes", "routine", "controls", "Sage 100")
        wcgw = scot.add_wcgw("Facture non enregistrée", ["C"])
        control = scot.add_control("Rapprochement", control_type="manual", frequency="monthly", wcgws=wcgw)
        control.update_control({"selected_for_testing": True})
        payload = self.payload("E1.2")
        self.assertEqual(payload["tool_card"]["rows"][0][1], "Ventes")
        self.assertTrue(payload["tool_done"]["selection"]["done"])
        self.assertTrue(payload["tool_done"]["population"]["done"])
        self.assertFalse(payload["tool_done"]["execute"]["done"])
        self.assertIs(payload["checks"]["selection"]["ok"], True)
        self.assertIs(payload["checks"]["grids"]["ok"], False)
        rows = [{"ref": str(n), "date": "", "desc": "", "results": {"a": "pass"}} for n in (1, 2)]
        control.sudo().write({"sample_size": 2, "toc_grid": {"attributes": ["a"], "rows": rows}})
        control.update_control({"operating_eval": "effective"})
        payload = self.payload("E1.2")
        self.assertTrue(payload["tool_done"]["execute"]["done"])
        self.assertTrue(payload["tool_done"]["exceptions"]["done"])
        self.assertEqual(payload["warnings"], [])
        control.update_control({"operating_eval": "not_effective"})
        self.assertTrue(self.payload("E1.2")["warnings"])
        # the roll-forward reads the same card, and a failed control sends it back to full documentation
        self.engagement.sudo().complexity = "non_complex"
        layout = self.payload("E2.1")["layout"]
        self.assertEqual((layout["depth"], layout["depth_reason"]), ("complex", "warning"))

    def test_going_concern_and_its_equity_check_read_in_e6_3(self):
        payload = self.payload("E6.3")
        self.assertTrue(payload["tool_card"]["title"])
        self.assertIn("capital", [p["key"] for s in payload["definition"]["sections"] if s["kind"] == "proc" for p in s["procs"]])
        Paper = type(self.env["ea.audit.paper"])
        self.patch(Paper, "_ea_hook_card_going_concern", lambda _self: {"title": "x", "warnings": ["Equity below half."]})
        self.engagement.sudo().complexity = "non_complex"
        self.assertEqual(self.payload("E6.3")["layout"]["depth_reason"], "warning")

    def test_subsequent_and_risk_revision_cards_read_without_data(self):
        self.assertTrue(self.payload("E6.6")["tool_card"]["empty"])
        card = self.payload("E6.8")["tool_card"]
        self.assertTrue(card["empty"])
        self.assertEqual(card["facts"][0]["value"], "0")

    def test_e6_10_checklist_is_answered_inside_its_task(self):
        payload = self.payload("E6.10")
        groups = [s for s in payload["definition"]["sections"] if s.get("task") == "checklist"]
        self.assertEqual(len(groups), 12)
        self.assertIn("q_ohada_A_1", payload["missing"])
        # no trial balance yet: the tie-out has nothing to say
        self.assertIsNone(payload["checks"]["n_agrees"]["ok"])
