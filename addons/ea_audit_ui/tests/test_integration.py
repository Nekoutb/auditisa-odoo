"""The addons together, with every hook real: a person walks a file from acceptance through
planning, and what the tools and papers record reaches the screens and the bell."""
from datetime import date

from odoo.tests import tagged

from odoo.addons.ea_audit_core.tests.common import EaAuditCase
from odoo.addons.ea_audit_papers.services import paper_for, required_keys
from odoo.addons.ea_audit_papers.services.planning_ras import SECTION_A, SECTION_B
from odoo.addons.ea_audit_tools.services.lead_classes import INDEX_SECTION
from odoo.addons.ea_audit_tools.tests.common import BALANCED_CSV, to_bytes


@tagged("post_install", "-at_install")
class TestIntegration(EaAuditCase):
    ea_real_paper_hooks = True

    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement(2025, partner=self.partner, nature="statutory_audit", complexity="very_simple")
        self.seat(self.engagement, self.manager, "manager")
        self.seat(self.engagement, self.senior, "senior")
        self.seat(self.engagement, self.staff, "staff")
        self.as_partner = self.engagement.with_user(self.partner)
        self.as_senior = self.engagement.with_user(self.senior)
        self.Ui = self.env["ea.audit.ui"]

    def paper(self, code):
        return self.item(self.engagement, code)._ea_paper()

    def fill(self, user, code, overrides=None):
        definition = paper_for(code, "current", self.client.legal_form)
        values = {key: "yes" if key[:2] in ("q_", "c_") else "Fait." for key in required_keys(definition)}
        values.update(overrides or {})
        self.paper(code).with_user(user).save_answers(values)

    def materiality(self):
        self.as_senior.import_trial_balance("balance.csv", to_bytes(BALANCED_CSV))
        version = self.as_senior.create_materiality_version(
            "total_assets", self.engagement.sudo()._ea_tb_bases()["total_assets"], 1, "Stable.",
        )
        version.with_user(self.partner).action_approve()
        return version

    def test_a_person_walks_from_acceptance_through_planning(self):
        engagement = self.engagement.sudo()
        self.assertCode(
            "gates-failed:d31_form_complete,d31_checks_passed,d31_partner_signed", self.as_partner.advance_to_planning,
        )
        self.fill(self.manager, "P1.1", {"engagement_type": "recurring", "auditor_change": "no", "rating": "moderate"})
        self.sign(self.manager, self.engagement, "P1.1", "preparer")
        self.sign(self.partner, self.engagement, "P1.1", "partner")
        self.as_partner.advance_to_planning()
        self.assertEqual(engagement.phase, "planning")

        failed = {gate["key"] for gate in engagement._ea_planning_close_gates() if not gate["ok"]}
        self.assertIn("materiality_approved", failed)
        self.assertIn("p72_partner_signed", failed)
        self.assertIn("significant_risks_linked", failed)

        self.materiality()
        revenue = self.env["ea.audit.risk"].sudo().search(
            [("engagement_id", "=", engagement.id), ("presumed_type", "=", "revenue_fraud")],
        )
        revenue.with_user(self.partner).rebut("Revenus simples et prévisibles.")
        for code in ("P2.2", "P5.2", "S3.1"):
            if self.item(self.engagement, code):
                self.fill(self.manager, code)
                self.sign(self.manager, self.engagement, code, "preparer")
                self.sign(self.partner, self.engagement, code, "partner")

        for item in SECTION_A:
            self.as_senior.ea_ras_save(item["key"], "na")
        for item in SECTION_B:
            self.as_partner.ea_ras_save(item["key"], "yes")
        self.as_senior.ea_ras_sign("fieldwork")
        self.engagement.with_user(self.manager).ea_ras_sign("manager")
        self.as_partner.ea_ras_sign("partner")
        self.assertTrue(engagement._ea_ras_partner_approved())

        self.as_partner.close_planning()
        self.assertEqual(engagement.phase, "execution")

    def test_the_summary_refuses_until_it_is_ready_and_ranks_its_sections(self):
        self.assertCode("ras-incomplete", self.engagement.with_user(self.manager).ea_ras_sign, "manager")
        self.assertCode("ras-incomplete", self.as_partner.ea_ras_sign, "partner")
        self.assertCode("ras-section-floor", self.as_senior.ea_ras_save, "b1", "yes")
        self.assertCode("ras-invalid-key", self.as_senior.ea_ras_save, "z9", "yes")
        self.assertCode("eqr-must-be-the-quality-reviewer", self.as_partner.ea_ras_save, "c1", "yes")
        self.as_senior.ea_ras_save("a1", "no")
        self.assertIn("a1_x", self.engagement.sudo().ea_ras_view()["tiers"][1]["gaps"])

    def test_a_tool_fed_paper_unlocks_with_its_tool(self):
        self.set_phase(self.engagement, "planning")
        self.fill(self.manager, "P6.1")
        self.assertCode("tool-output-missing-materiality", self.sign, self.manager, self.engagement, "P6.1", "preparer")
        self.materiality()
        self.assertEqual(self.sign(self.manager, self.engagement, "P6.1", "preparer"), "preparer")

    def test_the_auto_fields_and_chips_read_the_tool(self):
        self.materiality()
        paper = self.paper("P6.1").with_user(self.partner)
        payload = paper.get_payload()
        self.assertIn("v", payload["auto_values"]["benchmark"].lower())
        self.assertEqual(payload["tool_links"][0]["action"]["res_model"], "ea.audit.engagement")
        board = self.item(self.engagement, "P6.1").with_user(self.partner).ea_paper_board()
        self.assertEqual(len(board["facts"]), 5)
        self.assertTrue(board["links"])

    def test_every_board_answers(self):
        self.materiality()
        codes = ["P6.1", "P6.2", "S3.1", "C1.1"]
        code = next(
            (paper for paper in INDEX_SECTION.values() if paper and self.item(self.engagement, paper)), None,
        )
        if code:
            codes.append(code)
        for code in codes:
            item = self.item(self.engagement, code)
            if item:
                self.assertTrue(item.with_user(self.senior).ea_paper_board()["links"], code)

    def test_a_board_is_for_the_team(self):
        item = self.item(self.engagement, "P6.1")
        self.assertRaises(Exception, item.with_user(self.outsider).ea_paper_board)

    def test_a_program_step_is_part_of_the_hash(self):
        self.set_phase(self.engagement, "planning")
        before = self.paper("P3.1")._content_hash()
        self.as_senior.add_program_step(self.item(self.engagement, "P3.1"), "Nouvelle procédure")
        self.assertNotEqual(self.paper("P3.1")._content_hash(), before)

    def test_a_new_step_voids_the_signature_and_reopens_the_paper(self):
        self.set_phase(self.engagement, "planning")
        item = self.item(self.engagement, "P3.1")
        self.fill(self.senior, "P3.1")
        self.sign(self.senior, self.engagement, "P3.1", "preparer")
        self.sign(self.manager, self.engagement, "P3.1", "reviewer")
        self.assertEqual(item.state, "signed")
        self.as_senior.add_program_step(item, "Procédure ajoutée après la signature")
        self.assertEqual(item.state, "in_progress")
        self.assertFalse(self.paper("P3.1")._ea_active_signoffs())

    def test_the_tile_counts_notes_deficiencies_and_misstatements(self):
        self.materiality()
        self.set_phase(self.engagement, "execution")
        tile = lambda user: self.Ui.with_user(user).ea_ui_dashboard(self.engagement.id)["notes"]  # noqa: E731
        self.assertEqual(
            {key: tile(self.partner)[key] for key in ("for_me", "by_me", "deficiencies", "misstatements")},
            {"for_me": 0, "by_me": 0, "deficiencies": 0, "misstatements": 0},
        )
        item = self.item(self.engagement, "P3.1")
        item.with_user(self.manager).assign_tasks(self.senior.id, "preparer")
        item.with_user(self.manager).add_review_note("À compléter.")
        self.assertEqual(tile(self.manager)["by_me"], 1)
        self.assertEqual(tile(self.senior)["for_me"], 1)
        self.assertEqual(tile(self.senior)["note_item_ids"], [item.id])
        self.as_senior.route_finding("c1", "Pas de rapprochement", severity="significant_deficiency", file_item=item)
        self.as_senior.route_finding("b5", "Sous-évaluation", amount=999999)
        self.assertEqual(tile(self.partner)["deficiencies"], 1)
        self.assertEqual(tile(self.partner)["misstatements"], 1)

    def test_a_finding_rings_the_partners_bell_not_the_raisers(self):
        self.as_senior.route_finding("b4", "Saisies manuelles sans pièce")
        titles = [row["title"] for row in self.Ui.with_user(self.partner).ea_ui_notifications()["rows"]]
        self.assertTrue(any(title.startswith("Constat F-01") for title in titles))
        mine = [row["title"] for row in self.Ui.with_user(self.senior).ea_ui_notifications()["rows"]]
        self.assertFalse(any(title.startswith("Constat") for title in mine))

    def test_a_significant_deficiency_stays_on_the_partners_home_until_communicated(self):
        self.as_senior.route_finding("c1", "Pas de rapprochement", severity="significant_deficiency")
        rows = self.Ui.with_user(self.partner).ea_ui_home()["todo"]
        row = next(r for r in rows if r["title"] == "Déficience significative à communiquer")
        self.assertEqual((row["count"], row["tool"]), (1, "action_tool_deficiencies"))
        self.assertFalse([
            r for r in self.Ui.with_user(self.senior).ea_ui_home()["todo"] if r["title"].startswith("Déficience")
        ])

    def test_a_significant_risk_without_a_response_is_a_chip(self):
        self.set_phase(self.engagement, "planning")
        self.as_senior.add_risk("Risque de démonstration", significant=True)
        chips = self.Ui.with_user(self.partner).ea_ui_dashboard(self.engagement.id)["attention"]
        self.assertTrue([chip for chip in chips if chip["text"] == "sans procédure prévue"])

    def test_the_tools_hub_and_the_mission_context(self):
        action = self.as_senior.action_open_tools()
        self.assertEqual(action["context"]["ea_engagement_id"], self.engagement.id)
        self.assertEqual(
            self.Ui.with_user(self.senior).ea_ui_context("ea.audit.engagement", self.engagement.id)["id"], self.engagement.id,
        )

    def test_period_of_the_fixture(self):
        self.assertEqual(self.engagement.sudo().period_end, date(2025, 12, 31))
