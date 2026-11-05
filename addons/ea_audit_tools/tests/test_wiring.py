"""What the separate branches left open, and the second integration tied: the tool-backed papers read
the SCOT records, S2.5 is one answer, control tests feed coverage, S5.5 scopes the E4 tasks, a step
is done with its conclusion, the last tiles open, and the firm has a screen for its SAP thresholds."""
from odoo.tests import tagged

from .common import ToolsCase


class WiringCase(ToolsCase):
    def setUp(self):
        super().setUp()
        self.engagement.sudo()._ea_ensure_task("E1.2")
        for code in ("S1.2", "S1.3", "S2.1", "S2.2", "S2.3", "S2.5"):
            self.engagement.sudo()._ea_ensure_task(code)
        self.scot = self.as_staff.create_scot("Ventes", "routine", "controls", "Sage")
        self.wcgw = self.scot.add_wcgw("Facture non enregistrée", ["C"])
        self.control = self.scot.add_control("Rapprochement", frequency="monthly", wcgws=self.wcgw)

    def gap(self, code):
        return self.item(self.engagement, code)._ea_tool_gap()


@tagged("post_install", "-at_install")
class TestToolBackedPapers(WiringCase):
    def test_s12_needs_a_wcgw_on_every_scot(self):
        self.assertIsNone(self.gap("S1.2"))
        self.as_staff.create_scot("Achats")
        self.assertEqual(self.gap("S1.2"), "wcgw-missing")

    def test_s13_needs_every_walkthrough_answered(self):
        self.assertEqual(self.gap("S1.3"), "walkthrough-incomplete")
        from ..services.scot_forms import WALKTHROUGH_FIELDS

        self.scot.write({field["key"]: "yes" if field.get("kind") == "yn" else "Décrit." for field in WALKTHROUGH_FIELDS})
        self.assertIsNone(self.gap("S1.3"))

    def test_s21_and_s22_read_the_selection_and_the_design(self):
        self.assertEqual(self.gap("S2.1"), "control-selection-incomplete")
        self.control.update_control({"selected_for_testing": True})
        self.assertIsNone(self.gap("S2.1"))
        self.assertEqual(self.gap("S2.2"), "test-design-missing")
        self.control.update_control({"test_design": "Reprendre le rapprochement."})
        self.assertIsNone(self.gap("S2.2"))

    def test_s23_needs_a_strategy_per_application(self):
        self.assertEqual(self.gap("S2.3"), "itapp-strategy-missing")
        self.engagement.sudo()._ea_sync_it_applications()
        apps = self.env["ea.audit.it.application"].sudo().search([("engagement_id", "=", self.engagement.id)])
        for app in apps:
            self.as_staff.save_it_application(app.key, {"strategy": "substantive_only"})
        self.assertIsNone(self.gap("S2.3"))

    def test_the_refusal_stops_the_signature(self):
        item = self.item(self.engagement, "S2.1")
        self.set_phase(self.engagement, "planning")
        self.patch(type(item), "_ea_paper_refusal", lambda _self, _role: _self._ea_tool_gap())
        self.assertCode("control-selection-incomplete", item.with_user(self.staff).action_sign, "preparer")


@tagged("post_install", "-at_install")
class TestItgcConclusion(WiringCase):
    def paper(self):
        return self.item(self.engagement, "S2.5")._ea_paper().with_user(self.staff)

    def test_the_paper_sets_what_the_cra_reads(self):
        self.paper().save_answers({"itgc_state": "not_support"})
        self.assertEqual(self.engagement.sudo()._ea_itgc_state(), "not_support")
        self.paper().save_answers({"itgc_state": "support"})
        self.assertEqual(self.engagement.sudo()._ea_itgc_state(), "support")

    def test_the_tool_answers_on_the_paper(self):
        self.as_staff.save_itgc_conclusion("mixed")
        self.assertEqual(self.paper().sudo()._ea_values().get("itgc_state"), "mixed")
        self.as_staff.save_itgc_conclusion("mixed")
        history = self.env["ea.audit.paper.answer.history"].sudo().search_count([
            ("engagement_id", "=", self.engagement.id), ("code", "=", "S2.5"), ("field_key", "=", "itgc_state"),
        ])
        self.assertEqual(history, 1)


@tagged("post_install", "-at_install")
class TestControlTests(WiringCase):
    def setUp(self):
        super().setUp()
        self.scot.link_index("E", ["C"])
        self.control.update_control({"selected_for_testing": True})

    def coverage(self):
        return self.engagement.sudo()._ea_control_coverage("E", "C")

    def test_an_untested_control_is_neither_effective_nor_failed(self):
        self.assertEqual(self.coverage(), {"covering": 1, "effective": 0, "failed": 0})

    def test_a_clean_test_counts_until_e12_concludes(self):
        self.control.record_test("Janvier", "effective")
        self.assertEqual(self.coverage()["effective"], 1)
        self.control.sudo().operating_eval = "not_effective"
        self.assertEqual(self.coverage(), {"covering": 1, "effective": 0, "failed": 1})

    def test_a_deviation_fails_the_control_and_needs_its_decision(self):
        self.assertCode("deviation-decision-required", self.control.record_test, "Mars", "deviation")
        self.assertCode("description-required", self.control.record_test, " ", "effective")
        self.control.record_test("Mars", "deviation", "extend")
        self.assertEqual(self.coverage()["failed"], 1)
        steps = self.env["ea.audit.program.step"].sudo().search([("file_item_id", "=", self.item(self.engagement, "E1.2").id)])
        self.assertIn("Extended testing", steps.description)

    def test_a_deficiency_goes_to_the_register(self):
        self.control.record_test("Avril", "deviation", "deficiency", "Pas de visa.")
        finding = self.env["ea.audit.finding"].sudo().search([("engagement_id", "=", self.engagement.id), ("route", "=", "c1")])
        self.assertIn("Avril", finding.title)
        self.assertEqual(finding.severity, "deficiency")

    def test_abandoning_reliance_stamps_the_cells(self):
        self.control.record_test("Mai", "deviation", "abandon")
        steps = self.env["ea.audit.program.step"].sudo().search([("file_item_id", "=", self.item(self.engagement, "E1.2").id)])
        self.assertIn("Reliance abandoned", steps.description)

    def test_read_only_and_outsider(self):
        self.assertCode("read-only-role", self.control.with_user(self.reader).record_test, "x", "effective")
        self.assertFalse(self.env["ea.audit.control.test"].with_user(self.outsider).search([]))

    def test_the_screen_records(self):
        wizard = self.env["ea.audit.control.test.wizard"].with_user(self.staff).create({
            "control_id": self.control.id, "description": "Juin", "result": "effective",
        })
        wizard.action_record()
        self.assertEqual(self.control.sudo().test_ids.description, "Juin")
        self.assertTrue(self.control.action_open_test()["context"]["default_control_id"])


@tagged("post_install", "-at_install")
class TestE4Scope(ToolsCase):
    def scoped_out(self):
        return self.engagement.sudo()._ea_e4_out_of_scope().mapped("code")

    def test_nothing_designed_leaves_out_what_holds_an_account(self):
        codes = self.scoped_out()
        self.assertIn("E4.1", codes)
        self.assertNotIn("E4.36", codes, "a task with no lead index always shows")

    def test_a_design_brings_the_task_back_without_writing_it(self):
        item = self.item(self.engagement, "E4.1")
        self.as_staff.add_dsp_osp("E", "Confirmer les soldes clients", ["E"])
        self.assertNotIn("E4.1", self.scoped_out())
        self.assertFalse(item.conditional)

    def test_work_already_on_a_task_keeps_it(self):
        item = self.item(self.engagement, "E4.2")
        self.as_staff.add_program_step(item, "Circulariser les fournisseurs")
        self.assertNotIn("E4.2", self.scoped_out())


@tagged("post_install", "-at_install")
class TestProgramSteps(ToolsCase):
    def setUp(self):
        super().setUp()
        self.set_phase(self.engagement, "execution")
        self.step = self.as_staff.add_program_step(self.item(self.engagement, "E4.1"), "Circulariser")

    def test_done_with_its_conclusion(self):
        self.assertCode("conclusion-required", self.step.complete, " ")
        self.step.complete("Soldes confirmés.")
        row = self.step.sudo()
        self.assertEqual((row.status, row.conclusion, row.completed_by_id), ("done", "Soldes confirmés.", self.staff))
        self.assertCode("not-found", self.step.complete, "Encore")

    def test_undone_clears_the_attribution(self):
        self.step.complete("Fait.")
        self.step.uncomplete()
        row = self.step.sudo()
        self.assertEqual((row.status, row.conclusion, row.completed_by_id.id), ("open", False, False))

    def test_not_before_execution(self):
        self.set_phase(self.engagement, "planning")
        self.assertCode("planning-open", self.step.complete, "Trop tôt")

    def test_the_screen(self):
        wizard = self.env["ea.audit.step.wizard"].with_user(self.staff).create({"step_id": self.step.id, "mode": "na", "text": "Sans objet"})
        wizard.action_save()
        self.assertEqual(self.step.sudo().status, "na")


@tagged("post_install", "-at_install")
class TestTilesAndThresholds(ToolsCase):
    def test_the_last_tiles_open(self):
        for xmlid, model in (("tile_review_notes", "ea.audit.review.note"), ("tile_forms", "ea.audit.file.item")):
            tile = self.env.ref("ea_audit_tools.%s" % xmlid).with_user(self.staff)
            self.assertTrue(tile.available)
            action = tile.with_context(ea_engagement_id=self.engagement.id).action_open_tool()
            self.assertEqual(action["res_model"], model)
            self.env[model].with_user(self.staff).search(action["domain"], limit=1)
        forms = self.env.ref("ea_audit_tools.tile_forms").with_user(self.staff).with_context(ea_engagement_id=self.engagement.id).action_open_tool()
        codes = self.env["ea.audit.file.item"].sudo().search(forms["domain"]).mapped("code")
        self.assertNotIn("E4.1", codes, "S5.5 scopes the Forms list too")

    def test_a_method_no_addon_provides_is_coming(self):
        tile = self.env.ref("ea_audit_tools.tile_forms").sudo()
        tile.method = "action_tool_not_there"
        self.assertFalse(tile.available)
        self.assertCode("tool-not-available", tile.with_context(ea_engagement_id=self.engagement.id).with_user(self.staff).action_open_tool)

    def wizard(self, user):
        return self.env["ea.audit.sap.threshold.wizard"].with_user(user)

    def test_only_a_firm_administrator_sets_the_thresholds(self):
        admin = self._user("firmadmin", "group_firm_admin")
        form = self.wizard(admin).create({"low": 60, "moderate": 40, "high": 20})
        form.action_save()
        self.assertEqual(self.env["ea.audit.sap.settings"]._ea_get(), {"low": 60, "moderate": 40, "high": 20})
        self.assertEqual(self.wizard(admin).default_get(["low", "moderate", "high"])["moderate"], 40)
        self.assertCode("sap-threshold-order", self.wizard(admin).create({"low": 10, "moderate": 40, "high": 20}).action_save)
        self.assertCode("forbidden", self.env["ea.audit.sap.settings"].with_user(self.partner).set_thresholds, 60, 40, 20)
