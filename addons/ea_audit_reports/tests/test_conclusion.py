from datetime import date

from odoo.tests import tagged

from ..models.engagement import assembly_deadline
from ..services.articles import MARK, mark_articles, unmarked_articles
from ..services.opinion import decide_opinion, opinion_paragraph, period_end_fr
from .common import ReportsCase


@tagged("post_install", "-at_install")
class TestOpinion(ReportsCase):
    """conclusion.test.ts 7.9: misstatement or limitation, by pervasiveness."""

    def test_decision_tree(self):
        self.assertEqual(decide_opinion(), ("unmodified", False))
        self.assertEqual(decide_opinion(material_misstatement=True)[0], "qualified")
        self.assertEqual(decide_opinion(material_misstatement=True, pervasive=True)[0], "adverse")
        self.assertEqual(decide_opinion(scope_limitation=True)[0], "qualified")
        self.assertEqual(decide_opinion(scope_limitation=True, pervasive=True)[0], "disclaimer")
        self.assertEqual(decide_opinion(going_concern_uncertainty=True), ("unmodified", True))

    def test_art_710_wording(self):
        title, body = opinion_paragraph("unmodified", "Acme SA", "30 juin 2026")
        self.assertEqual(title, "Opinion")
        self.assertTrue(body.startswith("Nous certifions que les états financiers annuels de Acme SA pour l'exercice clos le 30 juin 2026"))
        self.assertIn("réguliers et sincères et donnent une image fidèle", body)
        self.assertNotIn("À notre avis", body)
        self.assertIn("sous réserve", opinion_paragraph("qualified", "A", "x")[1])
        self.assertIn("ne sont pas réguliers", opinion_paragraph("adverse", "A", "x")[1])
        self.assertIn("pas en mesure de certifier", opinion_paragraph("disclaimer", "A", "x")[1])

    def test_french_dates(self):
        self.assertEqual(period_end_fr(date(2026, 6, 30)), "30 juin 2026")
        self.assertEqual(period_end_fr(date(2026, 3, 1)), "1er mars 2026")

    def test_article_mark(self):
        marked = mark_articles("Selon les arts. 150 / 153 et l'art. 746-2 ; Article 525, art. 710 (à valider).")
        self.assertEqual(unmarked_articles(marked), [])
        self.assertEqual(marked.count(MARK), 4)
        self.assertEqual(mark_articles("art. 710", validated=True), "art. 710")
        self.assertEqual(mark_articles("ISA 580 ¶10–11"), "ISA 580 ¶10–11")


@tagged("post_install", "-at_install")
class TestCompletionRecords(ReportsCase):
    def test_who_may_write(self):
        self.assertCode("requires-partner", self.as_staff.record_completion, "partner_conclusion", {})
        self.assertCode("requires-senior", self.as_staff.record_completion, "disclosure_checklist", {})
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).record_completion, "fs_tieout", {})
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.outsider).record_completion, "fs_tieout", {})
        self.assertCode("system-key", self.as_senior.record_completion, "archive_manifest", {})
        self.seat(self.engagement, self.partner2, "manager")
        self.assertCode("not-engagement-partner", self.engagement.with_user(self.partner2).record_completion, "partner_conclusion", {})
        self.assertEqual(self.attempt(self.as_partner.record_completion, "partner_conclusion", {"conclusion": "x"}), "ok")

    def test_optimistic_lock(self):
        """UAT B104: a form built on an older version does not overwrite a colleague's save."""
        self.assertEqual(self.as_senior.completion_record_version("points_forward"), "")
        self.as_senior.record_completion("points_forward", {"points": "a"}, "")
        token = self.as_senior.completion_record_version("points_forward")
        self.as_manager.record_completion("points_forward", {"points": "b"}, token)
        self.assertCode("stale-edit", self.as_senior.record_completion, "points_forward", {"points": "c"}, token)
        self.assertEqual(self.engagement.sudo()._ea_completion_data("points_forward"), {"points": "b"})

    def test_form_refusals(self):
        self.assertCode("checklist-incomplete", self.as_senior.record_disclosure_checklist, False)
        self.assertCode("fields-required", self.as_senior.record_subsequent_events, False)
        self.assertCode("reviewed-before-period-end", self.as_senior.record_subsequent_events, "2025-12-31")
        self.as_senior.record_subsequent_events("2026-01-15", "Néant")
        self.assertEqual(self.engagement.sudo()._ea_completion_data("subsequent_events")["reviewedTo"], "2026-01-15")

    def test_runs_need_the_trial_balance_and_a_passing_tieout(self):
        self.assertCode("no-tb", self.as_senior.run_final_analytics)
        self.assertCode("tieout-failed", self.as_senior.run_fs_tieout)
        Engagement = type(self.env["ea.audit.engagement"])
        self.patch(Engagement, "_ea_tb_balances", lambda _s: [{"account": "101000", "value": 100.0}])
        self.assertCode("tieout-failed", self.as_senior.run_fs_tieout)
        self.patch(Engagement, "_ea_tb_balances", lambda _s: [{"account": "521000", "value": 100.0}, {"account": "701000", "value": -100.0}])
        self.as_senior.run_fs_tieout()
        self.as_senior.run_final_analytics()
        self.assertTrue(self.engagement.sudo()._ea_record_exists("fs_tieout"))
        self.assertTrue(self.engagement.sudo()._ea_record_exists("final_analytical_review"))


@tagged("post_install", "-at_install")
class TestCompletionGates(ReportsCase):
    def test_fresh_file_is_red(self):
        failed = self.failed(self.as_partner.completion_gates())
        for key in ("risks_concluded", "b5_within_materiality", "final_analytical_review", "fs_tieout_passed",
                    "disclosure_checklist", "subsequent_events", "rep_letters_generated", "c43_cleared", "partner_conclusion"):
            self.assertIn(key, failed)

    def test_all_green(self):
        self.green_completion()
        self.assertEqual(self.failed(self.as_partner.completion_gates()), [])

    def test_section_needs_a_reviewed_conclusion_and_no_open_step(self):
        self.green_completion()
        step = self.env["ea.audit.program.step"].sudo().create({
            "engagement_id": self.engagement.id, "file_item_id": self.item(self.engagement, "E4.1").id,
            "description": "Confirm balances", "status": "open",
        })
        self.assertIn("sections_concluded", self.failed(self.as_partner.completion_gates()))
        step.status = "done"
        self.assertIn("sections_concluded", self.failed(self.as_partner.completion_gates()))
        conclusion = self.env["ea.audit.section.conclusion"].sudo().create({
            "file_item_id": step.file_item_id.id, "conclusion": "OK", "reviewed_by_id": self.senior.id,
        })
        self.assertNotIn("sections_concluded", self.failed(self.as_partner.completion_gates()))
        self.assertTrue(conclusion)

    def test_unapproved_mid_audit_risk_blocks(self):
        self.green_completion()
        risk = self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", self.engagement.id)], limit=1)
        risk.added_after_planning = True
        self.assertIn("risks_concluded", self.failed(self.as_partner.completion_gates()))
        risk.addition_approved_by_id = self.partner
        self.assertNotIn("risks_concluded", self.failed(self.as_partner.completion_gates()))

    def test_b5_uses_the_uncorrected_threshold(self):
        """UAT B50: the line is overall less performance, here 3 000 000."""
        self.green_completion()
        Misstatement = self.env["ea.audit.misstatement"].sudo()
        row = Misstatement.create({"engagement_id": self.engagement.id, "description": "x", "amount": 3_000_000})
        self.assertNotIn("b5_within_materiality", self.failed(self.as_partner.completion_gates()))
        row.amount = 3_000_001
        self.assertIn("b5_within_materiality", self.failed(self.as_partner.completion_gates()))
        row.corrected = True
        self.assertNotIn("b5_within_materiality", self.failed(self.as_partner.completion_gates()))

    def test_unposted_sad_entry_blocks(self):
        """UAT run 2 B12: an entry above the trivial line that never reached the register."""
        self.green_completion()
        # a line typed before 2026-11-17, as the database holds it: no code path creates one any more
        self.env.cr.execute(
            "INSERT INTO ea_audit_sad_entry (engagement_id, finding, dr_amount, cr_amount, mtype, posted, register_only)"
            " VALUES (%s, 'x', 600000, 600000, 'factual', false, false) RETURNING id", [self.engagement.id],
        )
        entry = self.env["ea.audit.sad.entry"].sudo().browse(self.env.cr.fetchone()[0])
        self.assertIn("b5_within_materiality", self.failed(self.as_partner.completion_gates()))
        entry.write({"dr_amount": 100, "cr_amount": 100})
        self.assertNotIn("b5_within_materiality", self.failed(self.as_partner.completion_gates()))

    def test_open_c12_matter_blocks(self):
        self.green_completion()
        finding = self.env["ea.audit.finding"].sudo().create({
            "engagement_id": self.engagement.id, "number": 1, "route": "b4", "title": "Point",
        })
        self.assertIn("b4_cleared", self.failed(self.as_partner.completion_gates()))
        finding.status = "cleared"
        self.assertNotIn("b4_cleared", self.failed(self.as_partner.completion_gates()))

    def test_open_note_anywhere_keeps_c43_red(self):
        """UAT run 2 B81: the answer alone is a self-declaration."""
        self.green_completion()
        note = self.env["ea.audit.review.note"].sudo().create({
            "file_item_id": self.item(self.engagement, "E4.1").id, "author_id": self.senior.id, "body": "À voir",
        })
        self.assertIn("c43_cleared", self.failed(self.as_partner.completion_gates()))
        note.state = "cleared"
        self.assertNotIn("c43_cleared", self.failed(self.as_partner.completion_gates()))

    def test_eqr_gate_takes_the_reviewers_own_signature_and_answers(self):
        """UAT run 3 B02: the team signing C4.2 does not turn the gate green."""
        self.green_completion(eqr=False)
        self.engagement.sudo()._ea_ensure_task("C4.2")
        self.assertIn("eqr_complete", self.failed(self.as_partner.completion_gates()))
        by_partner = self.signoff("C4.2", "eqr", self.partner)
        self.assertIn("eqr_complete", self.failed(self.as_partner.completion_gates()))
        by_partner.voided_at = "2026-01-01 00:00:00"
        self.env.flush_all()
        self.signoff("C4.2", "eqr", self.eqr)
        self.answer("C4.2", "q_complete", "yes", self.eqr)
        self.assertIn("eqr_complete", self.failed(self.as_partner.completion_gates()))
        self.answer("C4.2", "q_resolved", "yes", self.partner)
        self.assertIn("eqr_complete", self.failed(self.as_partner.completion_gates()))
        self.answer("C4.2", "q_resolved", "yes", self.eqr)
        self.assertNotIn("eqr_complete", self.failed(self.as_partner.completion_gates()))

    def test_no_reviewer_no_gate(self):
        """Neither P1.5 nor the team asks for a review: the gate does not stand in the way."""
        self.env["ea.audit.team.member"].sudo().search([
            ("engagement_id", "=", self.engagement.id), ("team_role", "=", "eqr_reviewer"),
        ]).unlink()
        self.assertNotIn("eqr_complete", self.failed(self.as_partner.completion_gates()))

    def test_nature_waives_its_gates(self):
        self.engagement.sudo().nature = "commissariat_apports"
        keys = [gate["key"] for gate in self.as_partner.completion_gates()]
        for waived in ("fs_tieout_passed", "disclosure_checklist", "b5_within_materiality", "final_analytical_review", "subsequent_events"):
            self.assertNotIn(waived, keys)
        self.assertIn("partner_conclusion", keys)


@tagged("post_install", "-at_install")
class TestIssuance(ReportsCase):
    def test_who_may_issue(self):
        self.assertCode("requires-partner", self.as_manager.issue_report, "unmodified", "2026-03-31")
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).issue_report, "unmodified", "2026-03-31")
        self.seat(self.engagement, self.partner2, "manager")
        self.assertCode("not-engagement-partner", self.engagement.with_user(self.partner2).issue_report, "unmodified", "2026-03-31")
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.partner3).issue_report, "unmodified", "2026-03-31")

    def test_delegate_may_issue(self):
        self.green_completion()
        self.seat(self.engagement, self.partner2, "manager")
        self.engagement.sudo().partner_delegate_id = self.partner2
        self.assertEqual(self.attempt(self.engagement.with_user(self.partner2).issue_report, "unmodified", "2026-03-31"), "ok")

    def test_requires_execution(self):
        """UAT run 2 B154."""
        self.assertCode("report-requires-execution", self.as_partner.issue_report, "unmodified", "2026-03-31")

    def test_refuses_naming_the_failed_gates(self):
        self.set_phase(self.engagement, "execution")
        code = self.attempt(self.as_partner.issue_report, "unmodified", "2026-03-31")
        self.assertTrue(code.startswith("gates-failed:"))
        self.assertIn("partner_conclusion", code)

    def test_subsequent_events_must_reach_the_report_date(self):
        """ISA 560, UAT run 2 B79."""
        self.green_completion(reviewed_to="2026-03-30")
        self.assertEqual(self.attempt(self.as_partner.issue_report, "unmodified", "2026-03-31"), "gates-failed:subsequent_events")
        self.assertEqual(self.attempt(self.as_partner.issue_report, "unmodified", "2026-03-30"), "ok")

    def test_issue_then_refuse_a_second(self):
        self.green_completion()
        document = self.as_partner.issue_report_from_form(report_date="2026-03-31")
        row = self.engagement.sudo()
        self.assertEqual((row.phase, row.report_date, row.opinion), ("conclusion", date(2026, 3, 31), "unmodified"))
        self.assertEqual((document.kind, document.code), ("report", "C2.1"))
        self.assertEqual(document.sudo().current_version_id.attachment_id.raw[:2], b"PK")
        self.assertCode("already-issued", self.as_partner.issue_report, "unmodified", "2026-04-01")
        self.assertEqual(assembly_deadline(date(2026, 3, 31)), date(2026, 5, 30))
        self.assertEqual(self.engagement.with_user(self.partner).assembly_deadline, date(2026, 5, 30))

    def test_report_text(self):
        self.green_completion()
        text = self.text_of(self.as_partner.issue_report_from_form(report_date="2026-03-31", going_concern_uncertainty=True))
        self.assertIn("Rapport du commissaire aux comptes sur les états financiers annuels", text)
        self.assertIn("Nous certifions que les états financiers annuels de Governance SA pour l'exercice clos le 31 décembre 2025", text)
        self.assertIn("Incertitude significative liée à la continuité d'exploitation", text)
        self.assertIn("Fait le 31/03/2026", text)
        self.assertIn("Vérifications et informations spécifiques", text)
        self.assertEqual(unmarked_articles(text), [])
        self.assertIn("art. 713 %s" % MARK, text)

    def test_form_rules(self):
        self.green_completion()
        self.assertCode("fields-required", self.as_partner.issue_report_from_form)
        self.assertCode("basis-required", self.as_partner.issue_report_from_form, material_misstatement=True, report_date="2026-03-31")
        self.client.listed = True
        self.assertCode("kam-required", self.as_partner.issue_report_from_form, report_date="2026-03-31")
        self.assertCode("kam-required", self.as_partner.issue_report_from_form, kam_none=True, report_date="2026-03-31")
        text = self.text_of(self.as_partner.issue_report_from_form(
            material_misstatement=True, basis="Provision insuffisante.", kam_none=True, kam_none_reason="Mission simple.", report_date="2026-03-31",
        ))
        self.assertEqual(self.engagement.sudo().opinion, "qualified")
        self.assertIn("Fondement de l'opinion avec réserves", text)
        self.assertIn("Provision insuffisante.", text)
        self.assertIn("Nous avons déterminé qu'il n'y a pas de points clés de l'audit à communiquer dans notre rapport. Mission simple.", text)

    def test_joint_report_discloses_the_divergence(self):
        """legal.test.ts 8.8: art. 719."""
        self.client.co_cac = True
        self.green_completion()
        self.record("f8_disagreement", {"text": "Divergence sur la provision clients."})
        text = self.text_of(self.as_partner.issue_report_from_form(report_date="2026-03-31"))
        self.assertIn("Divergence entre commissaires aux comptes (art. 719 %s)" % MARK, text)
        self.assertIn("Divergence sur la provision clients.", text)
        self.assertIn("rapport commun", text)

    def test_pdf_of_the_report(self):
        self.green_completion()
        document = self.as_partner.issue_report_from_form(report_date="2026-03-31")
        html = self.env["ir.actions.report"].sudo()._render_qweb_html("ea_audit_reports.report_document", document.ids)[0]
        self.assertIn("Nous certifions", html.decode())
        self.assertEqual(document.with_user(self.partner).action_print_pdf()["report_name"], "ea_audit_reports.report_document")

    def test_only_the_engine_writes(self):
        self.assertCode("forbidden", self.as_partner.write, {"report_date": "2026-01-01"})
        self.assertCode("forbidden", self.as_partner.write, {"opinion": "adverse"})
        self.assertCode("forbidden", self.as_partner.write, {"retention_until": "2099-01-01"})
