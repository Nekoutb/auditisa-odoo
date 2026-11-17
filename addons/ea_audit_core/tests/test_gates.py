"""Port of tests/lib/uat2-gates.test.ts and the gates of lib/gates.ts relevant to
acceptance and planning. P1.1 form answers, materiality, RAS, risks and the TB live
in later addons: the tests give the engine those facts through the extension points."""
from odoo.tests import tagged

from odoo.addons.ea_audit_core.services.errors import AuditRuleError
from odoo.addons.ea_audit_core.services.phases import phase_of_task, phase_still_open

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestPhaseStillOpen(EaAuditCase):
    def test_completion_papers_open_from_execution_except_post_report(self):
        self.assertIsNone(phase_still_open("conclusion", "execution", "C4.2"))
        self.assertIsNone(phase_still_open("conclusion", "execution", "C4.1"))
        self.assertEqual(phase_still_open("conclusion", "execution", "C6.2"), "execution-open")
        self.assertEqual(phase_still_open("conclusion", "planning", "C4.1"), "planning-open")
        self.assertEqual(phase_still_open("execution", "planning", "E4.1"), "planning-open")
        self.assertEqual(phase_still_open("planning", "acceptance", "P3.1"), "acceptance-open")
        self.assertIsNone(phase_still_open("acceptance", "acceptance", "P1.1"))

    def test_the_template_phase_is_phase_of_task(self):
        for template in self.env["ea.audit.task.template"].search([]):
            self.assertEqual(template.phase, phase_of_task(template.section, template.code), template.code)
        self.assertEqual(self.env.ref("ea_audit_core.task_P2_2").phase, "acceptance")
        self.assertEqual(self.env.ref("ea_audit_core.task_P3_1").phase, "planning")


class GateCase(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.outputs_exist()
        self.engagement = self.make_engagement(partner=self.partner)
        self.as_partner = self.engagement.with_user(self.partner)
        self.seat(self.engagement, self.manager, "manager")
        self.seat(self.engagement, self.senior, "senior")
        self.cls_engagement = type(self.env["ea.audit.engagement"])
        # With ea_audit_tools installed the presumed risks are really seeded and wait on a
        # programme. This fixture tests the gates' logic: each count gate patches its own hook.
        self.patch(self.cls_engagement, "_ea_unlinked_significant_risk_count", lambda _self: 0)

    def keys(self, gates):
        return [g["key"] for g in gates]

    def failed(self, gates):
        return [g["key"] for g in gates if not g["ok"]]

    def p11_form(self, complete=True, concluded=True, checks=True):
        state = {"complete": complete, "concluded_accept": concluded, "checks_passed": checks}
        self.patch(self.cls_engagement, "_ea_p11_form_state", lambda _self: state)

    def planning_inputs(self):
        self.patch(self.cls_engagement, "_ea_materiality_approved", lambda _self: True)
        self.patch(self.cls_engagement, "_ea_ras_partner_approved", lambda _self: True)


@tagged("post_install", "-at_install")
class TestAcceptanceGates(GateCase):
    def test_lists_the_gates_of_lib_gates(self):
        self.assertEqual(self.keys(self.as_partner.acceptance_gates()), [
            "d31_form_complete", "d31_checks_passed", "d31_partner_signed",
            "engagement_partner_designated", "review_notes_cleared",
        ])

    def test_no_independence_gate(self):
        keys = self.keys(self.as_partner.acceptance_gates()) + self.keys(self.as_partner.planning_close_gates())
        self.assertFalse([k for k in keys if "independence" in k])

    def test_fails_closed_until_the_papers_addon_answers(self):
        self.assertEqual(self.failed(self.as_partner.acceptance_gates()), [
            "d31_form_complete", "d31_checks_passed", "d31_partner_signed",
        ])

    def test_blocks_with_the_failed_keys_in_the_code(self):
        self.p11_form()
        self.assertCode("gates-failed:d31_partner_signed", self.as_partner.advance_to_planning)
        self.assertEqual(self.engagement.sudo().phase, "acceptance")

    def test_passes_and_logs(self):
        self.p11_form()
        self.sign(self.manager, self.engagement, "P1.1", "preparer")
        self.assertEqual(self.sign(self.partner, self.engagement, "P1.1", "reviewer"), "partner")
        self.as_partner.advance_to_planning()
        self.assertEqual(self.engagement.sudo().phase, "planning")
        self.assertIn("phase_advanced", "".join(self.engagement.sudo().message_ids.mapped("body")))
        self.assertCode("wrong-phase", self.as_partner.advance_to_planning)

    def test_a_form_concluded_decline_blocks(self):
        self.p11_form(concluded=False)
        self.assertIn("d31_form_complete", self.failed(self.as_partner.acceptance_gates()))
        self.p11_form(checks=False)
        self.assertIn("d31_checks_passed", self.failed(self.as_partner.acceptance_gates()))

    def test_a_letter_does_not_satisfy_the_gate(self):
        self.env["ea.audit.signoff"].sudo().create({
            "file_item_id": self.item(self.engagement, "P1.1").id, "kind": "letter",
            "role": "partner", "user_id": self.partner.id,
        })
        self.assertIn("d31_partner_signed", self.failed(self.as_partner.acceptance_gates()))

    def test_a_voided_signature_does_not_satisfy_the_gate(self):
        self.sign(self.manager, self.engagement, "P1.1", "preparer")
        self.sign(self.partner, self.engagement, "P1.1", "reviewer")
        self.assertNotIn("d31_partner_signed", self.failed(self.as_partner.acceptance_gates()))
        self.item(self.engagement, "P1.1").signoff_ids.filtered(lambda s: s.role == "partner").write({
            "voided_at": "2026-01-01 00:00:00",
        })
        self.assertIn("d31_partner_signed", self.failed(self.as_partner.acceptance_gates()))

    def test_a_firm_lifting_the_partner_closes_on_the_reviewer(self):
        self.TaskRule.with_user(self.partner).save_task_rules([
            {"code": "P1.1", "min_preparer": None, "min_reviewer": "manager", "partner_required": False},
        ])
        self.seat(self.engagement, self.partner2, "director")
        self.sign(self.manager, self.engagement, "P1.1", "preparer")
        self.assertEqual(self.sign(self.partner2, self.engagement, "P1.1", "reviewer"), "reviewer")
        self.assertNotIn("d31_partner_signed", self.failed(self.as_partner.acceptance_gates()))

    def test_open_notes_block_and_are_named(self):
        self.patch(self.cls_engagement, "_ea_open_review_notes", lambda _self, _patterns: (2, ["P1.1", "P1.3"]))
        gate = next(g for g in self.as_partner.acceptance_gates() if g["key"] == "review_notes_cleared")
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["detail"], "2 · P1.1, P1.3")

    def test_the_read_only_role_cannot_advance(self):
        self.seat(self.engagement, self.reader, "staff")
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).advance_to_planning)

    def test_later_work_waits_for_the_gate(self):
        self.assertCode("acceptance-open", self.sign, self.senior, self.engagement, "P3.1", "preparer")
        self.assertCode("acceptance-open", self.sign, self.senior, self.engagement, "E4.1", "preparer")
        self.sign(self.manager, self.engagement, "P1.1", "preparer")


@tagged("post_install", "-at_install")
class TestPlanningGates(GateCase):
    def setUp(self):
        super().setUp()
        self.set_phase(self.engagement, "planning")

    def _sign_gated_papers(self):
        self.planning_inputs()
        for code in ("P2.2", "P5.2", "S3.1"):
            self.sign(self.manager, self.engagement, code, "preparer")
            self.assertEqual(self.sign(self.partner, self.engagement, code, "reviewer"), "partner")

    def test_lists_the_gates_of_lib_gates(self):
        self.assertEqual(self.keys(self.as_partner.planning_close_gates()), [
            "materiality_approved", "p22_partner_signed", "p52_partner_signed", "s31_partner_signed",
            "p72_partner_signed", "cra_reliance_supported", "significant_risks_linked",
            "rebuttals_approved", "material_sections_covered", "tb_mapped", "review_notes_cleared",
        ])

    def test_does_not_demand_a_paper_the_file_does_not_hold(self):
        simple = self.make_engagement(2026, complexity="very_simple")
        self.assertFalse(self.item(simple, "P2.2"))
        keys = self.keys(simple.with_user(self.partner).planning_close_gates())
        self.assertNotIn("p22_partner_signed", keys)
        for key in ("p52_partner_signed", "s31_partner_signed", "p72_partner_signed"):
            self.assertIn(key, keys)

    def test_p72_reads_the_summary_not_a_chip(self):
        self.sign(self.senior, self.engagement, "P7.2", "preparer")
        self.assertCode("ras-not-approved", self.sign, self.partner, self.engagement, "P7.2", "partner")
        self.assertIn("p72_partner_signed", self.failed(self.as_partner.planning_close_gates()))

    def test_fails_closed_until_the_tools_addon_answers(self):
        self.assertEqual(self.failed(self.as_partner.planning_close_gates()), [
            "materiality_approved", "p22_partner_signed", "p52_partner_signed", "s31_partner_signed", "p72_partner_signed",
        ])

    def test_a_material_section_needs_planned_coverage(self):
        self.item(self.engagement, "E4.1").with_user(self.partner).write({"material": True})
        self.assertIn("material_sections_covered", self.failed(self.as_partner.planning_close_gates()))
        self.patch(self.cls_engagement, "_ea_section_has_planned_step", lambda _self, _item: True)
        self.assertNotIn("material_sections_covered", self.failed(self.as_partner.planning_close_gates()))

    def test_each_count_gate_blocks(self):
        for hook, key in (
            ("_ea_unsupported_rely_count", "cra_reliance_supported"),
            ("_ea_unlinked_significant_risk_count", "significant_risks_linked"),
            ("_ea_unapproved_rebuttal_count", "rebuttals_approved"),
            ("_ea_unmapped_tb_account_count", "tb_mapped"),
        ):
            self.patch(self.cls_engagement, hook, lambda _self: 1)
            self.assertIn(key, self.failed(self.as_partner.planning_close_gates()))

    def test_closes_with_a_snapshot_in_one_transaction(self):
        self.assertCode(
            "gates-failed:materiality_approved,p22_partner_signed,p52_partner_signed,s31_partner_signed,p72_partner_signed",
            self.as_partner.close_planning,
        )
        self._sign_gated_papers()
        self.patch(self.cls_engagement, "_ea_planning_snapshot_data", lambda _self: {"risks": []})
        self.as_partner.close_planning()
        self.assertEqual(self.engagement.sudo().phase, "execution")
        snapshots = self.env["ea.audit.planning.snapshot"].with_user(self.partner).search([("engagement_id", "=", self.engagement.id)])
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots.data, {"risks": []})
        self.assertEqual(snapshots.taken_by_id, self.partner)
        self.assertCode("wrong-phase", self.as_partner.close_planning)

    def test_a_refused_close_takes_no_snapshot(self):
        with self.assertRaises(AuditRuleError):
            self.as_partner.close_planning()
        self.assertFalse(self.env["ea.audit.planning.snapshot"].sudo().search([("engagement_id", "=", self.engagement.id)]))


@tagged("post_install", "-at_install")
class TestTasksFollowFacts(GateCase):
    def test_signs_c41_in_execution_refuses_c62(self):
        self.set_phase(self.engagement, "execution")
        self.assertEqual(self.sign(self.senior, self.engagement, "C4.1", "preparer"), "preparer")
        self.assertCode("execution-open", self.sign, self.manager, self.engagement, "C6.2", "preparer")

    def test_p12_from_a_first_year_audit_on_a_very_simple_file(self):
        plain = self.make_engagement(2026, complexity="very_simple")
        # on the file at every complexity since 2026-11-17, waiting for its fact
        self.assertTrue(self.item(plain, "P1.2").conditional)
        first = self.make_engagement(2027, complexity="very_simple", first_year=True)
        self.assertFalse(self.item(first, "P1.2").conditional)
        self.assertTrue(self.item(first, "P1.2"))
        plain.with_user(self.partner).apply_complexity("very_simple", first_audit=True)
        self.assertTrue(self.item(plain, "P1.2"))
        self.assertFalse(self.item(plain, "P1.2").conditional)

    def test_c42_follows_the_eqr_not_the_tier(self):
        simple = self.make_engagement(2026, complexity="non_complex")
        self.assertTrue(self.item(simple, "C4.2").conditional)
        simple.with_user(self.partner).assign_team_member(self.eqr.id, "eqr_reviewer", True)
        self.assertTrue(self.item(simple, "C4.2"))
        self.assertFalse(self.item(simple, "C4.2").conditional)

    def test_an_archived_file_refuses_every_write(self):
        self.engagement.sudo().write({"phase": "archived", "archived_at": "2026-01-01 00:00:00"})
        self.assertCode("archived", self.as_partner.write, {"name": "x"})
        self.assertCode("archived", self.as_partner.assign_team_member, self.staff.id, "staff")
        self.assertCode("archived", self.as_partner.remove_team_member, self.senior.id)
        self.assertCode("archived", self.as_partner.transfer_engagement_partner, self.partner2.id, "director")
        self.assertCode("archived", self.sign, self.senior, self.engagement, "E4.1", "preparer")
