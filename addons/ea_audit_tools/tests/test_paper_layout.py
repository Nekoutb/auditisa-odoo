"""The working-paper layout of 2026-11-17 on a real engagement: the depth set by the engagement's
complexity, the tool hooks (card, done in the tool, checked by the tool, warnings), review notes on a
task, the attachment references and the very simple sign-off chain."""
import base64

from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestPaperLayout(ToolsCase):
    def setUp(self):
        super().setUp()
        self.set_phase(self.engagement, "planning")
        for code in ("S4.1", "S4.2", "E6.3", "P3.1", "P6.1", "P6.2", "S1.1", "S1.2", "S1.3", "S1.4", "S3.1"):
            self.engagement.sudo()._ea_ensure_task(code)

    def payload(self, code, user=None):
        return self.item(self.engagement, code).with_user(user or self.partner).get_paper_payload()

    def paper(self, code):
        return self.item(self.engagement, code)._ea_paper()

    def save(self, user, code, values):
        return self.paper(code).with_user(user).save_answers(values)

    def test_depth_follows_the_engagement_complexity(self):
        self.assertEqual(self.payload("S4.2")["layout"]["depth"], "complex")
        self.engagement.sudo().complexity = "non_complex"
        payload = self.payload("S4.2")
        self.assertEqual((payload["layout"]["converted"], payload["layout"]["depth"]), (True, "non_complex"))
        self.assertTrue(payload["tool_card"]["title"])
        self.assertTrue([tool for tool in payload["tools"] if tool["action"]])
        self.assertEqual([link["label"] for link in payload["isa"]], ["ISA 570 (Revised 2024)"])
        self.assertIn("E6.3", [task["code"] for task in payload["linked_tasks"]])
        # a "No" sends the paper back to full documentation
        self.save(self.senior, "S4.2", {"q_none": "no", "q_none_x": "Arrears to the tax authority."})
        self.assertEqual(self.payload("S4.2")["layout"]["depth_reason"], "no_answer")

    def test_an_older_paper_reads_in_full_whatever_the_profile(self):
        self.engagement.sudo().complexity = "very_simple"
        payload = self.payload("P3.1")
        self.assertEqual((payload["layout"]["converted"], payload["layout"]["depth"]), (False, "complex"))
        self.assertFalse(payload["tool_card"])

    def test_materiality_card_and_tasks_done_in_the_tool(self):
        self.approve()
        payload = self.payload("P6.1")
        self.assertEqual(len(payload["tool_card"]["facts"]), 6)
        self.assertTrue(payload["tool_done"]["benchmark"]["done"])
        self.assertTrue(payload["tool_done"]["trivial"]["result"])
        self.assertIs(payload["checks"]["stable"]["ok"], True)
        procs = {p["key"]: p for s in payload["definition"]["sections"] if s["kind"] == "proc" for p in s["procs"]}
        self.assertEqual(procs["benchmark"]["_mode"], "tool")
        self.assertNotIn("p_benchmark", payload["missing"])
        self.assertIn("p_users", payload["missing"])

    def test_significance_and_scot_cards_read_the_tools(self):
        self.import_tb()
        self.approve()
        self.as_staff.create_scot("Ventes", applications="Sage 100")
        for code in ("P6.2", "S1.1", "S1.2", "S1.3", "S1.4", "S3.1"):
            with self.subTest(code=code):
                card = self.payload(code)["tool_card"]
                self.assertTrue(card["title"])
                self.assertTrue(card["action"], code)
        self.assertEqual(self.payload("S1.1")["tool_card"]["rows"][0][0], "Ventes")
        self.assertTrue(self.payload("S1.1")["tool_done"]["apps"]["done"])

    def test_a_warning_forces_full_documentation_and_closes_no_exceptions(self):
        self.engagement.sudo().complexity = "non_complex"
        Paper = type(self.env["ea.audit.paper"])
        self.patch(Paper, "_ea_hook_card_going_concern", lambda _self: {"title": "x", "warnings": ["Equity below half."]})
        payload = self.payload("S4.2")
        self.assertEqual((payload["layout"]["depth"], payload["layout"]["depth_reason"]), ("complex", "warning"))
        self.assertEqual(payload["warnings"], ["Equity below half."])
        self.assertCode("exception-blocked", self.save, self.senior, "S4.2", {"p_capital_m": "nx", "p_capital": "Fine."})

    def test_no_exceptions_noted_needs_its_source_and_is_counted(self):
        self.engagement.sudo().complexity = "non_complex"
        self.save(self.senior, "S4.2", {"p_indicators_m": "nx", "p_indicators": "Financial indicators reviewed; no exceptions noted."})
        payload = self.payload("S4.2")
        self.assertIn("p_indicators_src", payload["missing"])
        self.assertEqual(payload["layout"]["by_exception"], 1)
        self.save(self.senior, "S4.2", {"p_indicators_src": "A2"})
        self.assertNotIn("p_indicators_src", self.payload("S4.2")["missing"])

    def test_a_statement_the_tool_contradicts_refuses_yes(self):
        Paper = type(self.env["ea.audit.paper"])
        self.patch(Paper, "_ea_hook_check_significance_screen", lambda _self: {"ok": False, "note": "E"})
        self.assertCode("autocheck-contradicts", self.save, self.senior, "P6.2", {"q_above_pm": "yes"})
        self.save(self.senior, "P6.2", {"q_above_pm": "no", "q_above_pm_x": "E excluded: see note."})
        self.assertEqual(self.paper("P6.2")._ea_values()["q_above_pm"], "no")

    def test_review_notes_on_a_task_and_attachment_references(self):
        item = self.item(self.engagement, "S4.2")
        item.with_user(self.manager).add_review_note("Document the current ratio trend.", "indicators")
        item.with_user(self.manager).add_review_note("Tighten the conclusion.")
        notes = self.payload("S4.2")["notes"]
        self.assertEqual(sorted(note["task_key"] for note in notes), ["", "indicators"])
        encode = lambda b: base64.b64encode(b).decode()  # noqa: E731
        item.with_user(self.staff).upload_attachment("first.txt", encode(b"one"))
        item.with_user(self.staff).upload_attachment("second.txt", encode(b"two"))
        live = self.payload("S4.2")["attachments"]["live"]
        self.assertEqual([(row["ref"], row["name"]) for row in live], [("A1", "first.txt"), ("A2", "second.txt")])

    def test_very_simple_ticks_a_summary_and_preparer_then_partner(self):
        self.engagement.sudo().complexity = "very_simple"
        payload = self.payload("S4.2")
        self.assertEqual(payload["layout"]["depth"], "very_simple")
        self.assertIn("partner", [chip["role"] for chip in payload["signing"]["chips"]])
        statements = [i["key"] for s in payload["definition"]["sections"] if s["kind"] == "yn" for i in s["items"]]
        self.assertEqual(statements, ["none", "assessment"])
        procs = [p["key"] for s in payload["definition"]["sections"] if s["kind"] == "proc" for p in s["procs"]]
        values = {"p_%s_m" % key: "tick" for key in procs}
        values.update({"q_none": "yes", "q_assessment": "yes", "summary": "Met the owner-manager; no doubt.", "conclusion": "No doubt at this stage."})
        self.save(self.senior, "S4.2", values)
        self.assertEqual(self.payload("S4.2")["missing"], [])
        self.assertEqual(self.sign(self.senior, self.engagement, "S4.2", "preparer"), "preparer")
        self.assertEqual(self.sign(self.partner, self.engagement, "S4.2", "partner"), "partner")
        self.assertEqual(self.item(self.engagement, "S4.2").state, "signed")

    def test_a_signed_paper_keeps_the_wording_it_was_signed_on(self):
        Def = self.env["ea.audit.paper.def"]
        old = Def._ea_current("P3.1")
        self.env["ea.audit.signoff"].sudo().create({
            "file_item_id": self.item(self.engagement, "P3.1").id, "role": "preparer", "user_id": self.senior.id,
        })
        Def._ea_load_one("P3.1", dict(old.definition, reqEn=["A new requirement."]))
        paper = self.paper("P3.1")
        self.assertEqual(paper._ea_unresolved(), old.definition)
        paper.signoff_ids.sudo().write({"voided_at": "2026-11-17 10:00:00"})
        paper.invalidate_recordset()
        self.assertEqual(paper._ea_unresolved()["reqEn"], ["A new requirement."])
