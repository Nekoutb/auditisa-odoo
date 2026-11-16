import glob
import io
import os
from datetime import date, timedelta

import openpyxl

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import file_path

from odoo.addons.ea_audit_reports.services.articles import MARK, unmarked_articles
from odoo.addons.ea_audit_reports.services.docx_builder import docx_text
from odoo.addons.ea_audit_reports.tests.common import ReportsCase
from odoo.addons.ea_audit_tools.services.alerte import FIRST_REPLY_DAYS
from odoo.addons.ea_audit_tools.services.legal import add_days_iso, add_months_clamped

from ..services.texts import equity_conclusion_of, persons_from_headcount

TB = "Compte;Libellé;Mouvement débit;Mouvement crédit\n"
LOSS_TB = TB + "101000;Capital;0;10000000\n521000;Banque;2000000;0\n661000;Salaires;12000000;0\n701000;Ventes;0;4000000\n"
HEALTHY_TB = TB + "101000;Capital;0;10000000\n521000;Banque;9000000;0\n661000;Salaires;1000000;0\n"


class LegalCase(ReportsCase):
    def setUp(self):
        super().setUp()
        self.as_partner = self.engagement.with_user(self.partner)
        self.sarl = self.env["ea.audit.client"].create({"name": "Legal SARL", "legal_form": "SARL"})
        self.sarl_file = self.make_engagement(client=self.sarl)

    def text(self, document):
        return docx_text(document.sudo().current_version_id.attachment_id.raw)

    def today(self):
        return fields.Date.context_today(self.env.user).isoformat()


@tagged("post_install", "-at_install")
class TestDeadlines(LegalCase):
    """legal.test.ts 8.1 and the statutory date arithmetic."""

    def test_date_arithmetic(self):
        self.assertEqual(add_months_clamped("2025-12-31", 4), "2026-04-30")
        self.assertEqual(add_months_clamped("2025-12-31", 6), "2026-06-30")
        self.assertEqual(add_months_clamped("2025-01-15", 1), "2025-02-15")
        self.assertEqual(add_days_iso("2026-06-15", -45), "2026-05-01")

    def test_calendar(self):
        self.client.write({"mandate_type": "ago", "mandate_start_year": 2024})
        self.as_partner.set_legal_dates(agm_date="2026-06-15")
        rows = {row.key: row.sudo() for row in self.engagement.sudo().legal_deadline_ids}
        self.assertEqual(rows["fs_arrete"].due_date, date(2026, 4, 30))
        self.assertEqual(rows["continuing_conventions_notice"].due_date, date(2026, 1, 31))
        self.assertEqual(rows["ago"].due_date, date(2026, 6, 30))
        self.assertEqual(rows["docs_to_cac"].due_date, date(2026, 5, 1))
        self.assertEqual(rows["rapport_special_deposit"].due_date, date(2026, 5, 31))
        self.assertEqual(rows["fs_filing_rccm"].due_date, date(2026, 7, 15))
        # UAT B102: art. 704, the meeting ruling on the sixth year, not its 31 December
        self.assertEqual(rows["mandate_expiry"].due_date, date(2030, 6, 30))

    def test_every_basis_marks_its_article(self):
        self.client.write({"mandate_type": "ago", "mandate_start_year": 2024})
        self.as_partner.set_legal_dates(agm_date="2026-06-15", board_date="2026-03-15")
        rows = self.engagement.sudo().legal_deadline_ids
        self.assertIn("art715_board", rows.mapped("key"))
        for row in rows:
            self.assertEqual(unmarked_articles(row.basis), [], row.key)
        self.assertIn("Art. 72 %s" % MARK, rows.filtered(lambda r: r.key == "ago").basis)

    def test_provisional_filing_without_a_meeting(self):
        self.as_partner.generate_deadlines()
        row = self.engagement.sudo().legal_deadline_ids.filtered(lambda r: r.key == "fs_filing_rccm")
        self.assertEqual(row.due_date, date(2026, 7, 30))
        self.assertIn("provisoire", row.basis)

    def test_done_mark_survives_regeneration(self):
        self.as_partner.generate_deadlines()
        self.as_partner.mark_deadline_done("ago")
        self.as_partner.generate_deadlines()
        self.assertTrue(self.engagement.sudo().legal_deadline_ids.filtered(lambda r: r.key == "ago").done)

    def test_escalation_notifies_each_partner_once(self):
        """UAT B102: a refresh does not repeat the notification."""
        self.as_partner.generate_deadlines()
        self.engagement.sudo().legal_deadline_ids.filtered(lambda r: r.key == "fs_arrete").write(
            {"due_date": fields.Date.context_today(self.env.user) - timedelta(days=10)}
        )
        self.assertGreater(self.as_partner.escalate_overdue(), 0)
        Notice = self.env["ea.audit.notice"].sudo()
        domain = [("user_id", "=", self.partner.id), ("kind", "=", "deadline-overdue"), ("title", "like", "fs_arrete")]
        self.assertEqual(Notice.search_count(domain), 1)
        self.as_partner.escalate_overdue()
        self.assertEqual(Notice.search_count(domain), 1)

    def test_read_only_member_views_only(self):
        """UAT B10."""
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).generate_deadlines)
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).mark_deadline_done, "ago")

    def test_team_only(self):
        self.as_partner.generate_deadlines()
        row = self.engagement.sudo().legal_deadline_ids[0]
        self.assertTrue(row.with_user(self.reader).key)
        with self.assertRaises(AccessError):
            row.with_user(self.outsider).read(["key"])
        with self.assertRaises(AccessError):
            row.with_user(self.admin).read(["key"])
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.admin).generate_deadlines)

    def test_invalid_date(self):
        self.assertCode("invalid-date", self.as_partner.set_legal_dates, agm_date="15/06/2026")

    def test_cron_sends_no_email(self):
        self.as_partner.generate_deadlines()
        self.engagement.sudo().legal_deadline_ids.filtered(lambda r: r.key == "ago").write({"due_date": "2020-01-01"})
        mails = self.env["mail.mail"].sudo().search_count([])
        self.env["ea.audit.engagement"]._ea_cron_legal_deadlines()
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mails)
        self.assertTrue(self.env["ea.audit.notice"].sudo().search_count([("title", "like", "ago"), ("user_id", "=", self.partner.id)]))


@tagged("post_install", "-at_install")
class TestRegulatedAgreements(LegalCase):
    def _bail(self):
        return self.as_partner.add_convention(
            "Legal SA / Immo SCI", "M. Dupont", "director", "Bail commercial du siège",
            terms="Loyer annuel 24 000 000 FCFA", amounts_period=24_000_000, continuing=True,
        )

    def test_flags_unauthorised_on_an_sa(self):
        """art. 447"""
        bail = self._bail()
        conseil = self.as_partner.add_convention("A / B", "Mme Ndiaye", "shareholder10", "Prestations de conseil", board_auth_ref="CA du 10/03/2025")
        self.assertTrue(bail.unauthorized)
        self.assertFalse(conseil.unauthorized)

    def test_no_authorisation_needed_outside_the_sa(self):
        row = self.sarl_file.with_user(self.partner).add_convention("Legal SARL / Gérant", "Le gérant", "gerant", "Avance en compte courant")
        self.assertFalse(row.unauthorized)

    def test_refusals(self):
        self.assertCode("fields-required", self.as_partner.add_convention, " ", "x", "director", "y")
        self.assertCode("invalid-capacity", self.as_partner.add_convention, "x", "y", "stranger", "z")

    def test_special_report(self):
        self._bail()
        self.as_partner.set_legal_dates(agm_date="2026-06-15")
        document = self.as_partner.generate_rapport_special()
        self.assertEqual((document.kind, document.code), ("report", "C5.3"))
        text = self.text(document)
        self.assertIn("À l'assemblée générale ordinaire des actionnaires du 15 juin 2026.", text)
        self.assertIn("Convention 1 — Bail commercial du siège", text)
        self.assertIn("24 000 000 FCFA", text)
        self.assertIn("ATTENTION : convention non autorisée préalablement par le conseil d'administration", text)
        self.assertEqual(unmarked_articles(text), [])
        self.assertIn("art. 447 %s" % MARK, text)
        self.assertIn(self.partner.name + ", associé signataire", text)

    def test_special_report_of_a_sarl(self):
        as_partner = self.sarl_file.with_user(self.partner)
        as_partner.add_convention("A", "Le gérant", "gerant", "Avance")
        text = self.text(as_partner.generate_rapport_special())
        self.assertIn("assemblée générale ordinaire des associés", text)
        self.assertIn("Autorisation préalable non requise dans la SARL", text)

    def test_no_agreement_says_so(self):
        self.assertIn("Absence de convention", self.text(self.as_partner.generate_rapport_special()))

    def test_real_period_end(self):
        """uat2-legal B21: the engagement's own period end, never an assumed 31 December."""
        june = self.make_engagement(year=2026, period_end=date(2026, 6, 30), client=self.env["ea.audit.client"].create({"name": "June SA"}))
        as_partner = june.with_user(self.partner)
        for document in (as_partner.generate_rapport_special(), as_partner.generate_article_715_report()):
            text = self.text(document)
            self.assertIn("Exercice clos le 30 juin 2026", text)
            self.assertNotIn("31 décembre", text)


@tagged("post_install", "-at_install")
class TestArticle715(LegalCase):
    def test_pulls_live_data(self):
        Misstatement = self.env["ea.audit.misstatement"].sudo()
        Misstatement.create({"engagement_id": self.engagement.id, "description": "Provision clients sous-évaluée", "amount": 5_000_000})
        self.env["ea.audit.finding"].sudo().create({
            "engagement_id": self.engagement.id, "number": 1, "route": "c1", "title": "Séparation des tâches trésorerie", "detail": "Un seul signataire",
        })
        document = self.as_partner.generate_article_715_report()
        self.assertEqual(document.code, "C5.4")
        text = self.text(document)
        self.assertIn("au conseil d'administration", text)
        self.assertIn("art. 715 %s" % MARK, text)
        self.assertIn("Provision clients sous-évaluée — 5 000 000 FCFA.", text)
        self.assertIn("Observation sur les méthodes : Séparation des tâches trésorerie — Un seul signataire", text)
        self.assertIn("Néant.", text)
        self.assertIn("Résultat de l'exercice 2025 : n/d ; exercice 2024 : n/d.", text)

    def test_organ_follows_the_form(self):
        text = self.text(self.sarl_file.with_user(self.partner).generate_article_715_report())
        self.assertIn("au gérant", text)
        client = self.env["ea.audit.client"].create({"name": "AG SA", "legal_form": "SA_AG"})
        text = self.text(self.make_engagement(client=client).with_user(self.partner).generate_article_715_report())
        self.assertIn("à l'administrateur général", text)


@tagged("post_install", "-at_install")
class TestAlerte(LegalCase):
    def test_non_sa_flow(self):
        """request, reply, court, report, general meeting, closed."""
        as_partner = self.sarl_file.with_user(self.partner)
        as_partner.start_alerte("Trésorerie insuffisante pour 3 mois d'exploitation.")
        state = as_partner.get_alerte()
        self.assertEqual((state["variant"], state["stage"]), ("non_sa", "request_sent"))
        self.assertEqual(state["stage_deadline"].isoformat(), add_days_iso(self.today(), FIRST_REPLY_DAYS))
        self.assertTrue(as_partner.active_alerte())
        self.assertCode("alerte-open", as_partner.start_alerte, "again")
        self.assertCode("invalid-transition", as_partner.advance_alerte, "rapport_special", "skip")
        as_partner.advance_alerte("reply_recorded", "Réponse insuffisante du gérant.")
        as_partner.advance_alerte("court_informed", "Juridiction informée de la réponse.")
        as_partner.advance_alerte("rapport_special", "Continuité toujours compromise.")
        state = as_partner.get_alerte()
        self.assertEqual(state["stage"], "rapport_special")
        self.assertEqual(state["stage_deadline"].isoformat(), add_days_iso(self.today(), 8))
        as_partner.advance_alerte("ag_communicated", "Rapport communiqué aux associés.")
        as_partner.advance_alerte("closed", "Juridiction informée des résultats.")
        state = as_partner.get_alerte()
        self.assertEqual(state["stage"], "closed")
        self.assertGreaterEqual(len(state["events"]), 6)
        self.assertFalse(as_partner.active_alerte())
        letters = self.env["ea.audit.document"].sudo().search([("engagement_id", "=", self.sarl_file.id), ("code", "=", "C5.5")])
        self.assertGreaterEqual(len(letters), 3)
        self.assertEqual(letters.filtered(lambda d: "rapport spécial" in d.title).kind, "report")

    def test_sa_flow_discontinue_and_resume(self):
        as_partner = self.as_partner
        as_partner.start_alerte("Pertes récurrentes.")
        self.assertEqual(as_partner.get_alerte()["variant"], "sa")
        as_partner.advance_alerte("reply_recorded", "Plan de refinancement crédible.", satisfactory=True)
        state = as_partner.get_alerte()
        self.assertTrue(state["discontinued"])
        self.assertTrue(state["resumable_until"])
        self.assertEqual(state["next_stages"], ["resumed"])
        self.assertFalse(as_partner.active_alerte())
        self.assertCode("alerte-discontinued", as_partner.advance_alerte, "board_invited", "x")
        as_partner.resume_alerte("Le refinancement a échoué.")
        state = as_partner.get_alerte()
        self.assertFalse(state["discontinued"])
        self.assertEqual(state["stage"], "request_sent")
        as_partner.advance_alerte("reply_recorded", "Pas de réponse satisfaisante.")
        as_partner.advance_alerte("board_invited", "Conseil invité à délibérer.")
        state = as_partner.get_alerte()
        self.assertEqual(state["stage"], "board_invited")
        self.assertEqual(state["stage_deadline"].isoformat(), add_days_iso(self.today(), 15))

    def test_resume_expires_and_needs_a_discontinued_procedure(self):
        self.as_partner.start_alerte("x")
        self.assertCode("not-discontinued", self.as_partner.resume_alerte, "y")
        self.as_partner.advance_alerte("reply_recorded", "ok", satisfactory=True)
        self.as_partner.get_alerte()
        self.env["ea.audit.alerte"].sudo().search([("engagement_id", "=", self.engagement.id)]).discontinued_at = fields.Date.context_today(self.env.user) - timedelta(days=200)
        self.assertCode("resume-expired", self.as_partner.resume_alerte, "y")

    def test_event_dates_hold_their_order(self):
        """UAT run 2 B95."""
        self.as_partner.start_alerte("x", "2026-01-10")
        self.assertCode("event-date-before-previous", self.as_partner.advance_alerte, "reply_recorded", "y", False, "2026-01-05")
        self.assertCode("invalid-event-date", self.as_partner.advance_alerte, "reply_recorded", "y", False, "2099-01-01")
        self.as_partner.advance_alerte("reply_recorded", "y", False, "2026-01-20")
        self.assertEqual(self.as_partner.get_alerte()["stage_deadline"], date(2026, 2, 4))

    def test_letter_is_addressed_by_legal_form(self):
        self.as_partner.start_alerte("Faits", "2026-01-10")
        document = self.env["ea.audit.document"].sudo().search([("engagement_id", "=", self.engagement.id), ("code", "=", "C5.5")])
        text = self.text(document)
        self.assertIn("Au président du conseil d'administration ou PDG de Governance SA", text)
        self.assertIn("Fait le 10 janvier 2026.", text)
        self.assertIn("arts. 150 / 153 %s" % MARK, text)
        self.sarl_file.with_user(self.partner).start_alerte("Faits")
        document = self.env["ea.audit.document"].sudo().search([("engagement_id", "=", self.sarl_file.id), ("code", "=", "C5.5")])
        self.assertIn("Au gérant de Legal SARL", self.text(document))

    def test_stage_basis_is_marked(self):
        alerte = self.as_partner.start_alerte("x")
        self.assertEqual(unmarked_articles(alerte.stage_basis), [])
        self.assertIn("(to validate)", alerte.stage_basis)
        self.assertIn(MARK, alerte.with_context(lang="fr_FR").stage_basis)


@tagged("post_install", "-at_install")
class TestCriminalFacts(LegalCase):
    def test_partner_reveals(self):
        document = self.as_partner.reveal_fait("Détournement présumé de recettes en espèces.")
        self.assertEqual((document.kind, document.code), ("letter", "C5.6"))
        faits = self.as_partner.list_faits()
        self.assertEqual(len(faits), 1)
        self.assertEqual(faits.document_id, document)
        self.assertEqual(unmarked_articles(self.text(document)), [])

    def test_refused_below_partner(self):
        self.assertCode("forbidden", self.as_manager.reveal_fait, "x")
        self.assertCode("forbidden", self.as_senior.list_faits)
        self.assertCode("fields-required", self.as_partner.reveal_fait, "  ")

    def test_strict_access_to_the_record_and_the_letter(self):
        """spec 12.5.6: a team member below partner reaches neither."""
        document = self.as_partner.reveal_fait("Fait")
        row = self.as_partner.list_faits()
        with self.assertRaises(AccessError):
            row.with_user(self.manager).read(["description"])
        with self.assertRaises(AccessError):
            document.with_user(self.manager).read(["title"])
        with self.assertRaises(AccessError):
            document.sudo().current_version_id.with_user(self.manager).read(["sha256"])
        with self.assertRaises(AccessError):
            document.sudo().current_version_id.attachment_id.with_user(self.manager).read(["datas"])
        self.assertTrue(document.with_user(self.partner).title)
        self.assertFalse(self.env["ea.audit.document"].with_user(self.manager).search([("id", "=", document.id)]))

    def test_irregularities_letter(self):
        self.assertCode("fields-required", self.as_partner.generate_irregularities_letter, "ag", " ")
        ag = self.as_partner.generate_irregularities_letter("ag", "Comptes non tenus.")
        self.assertIn("Signalement AG", ag.title)
        self.assertIn("à la plus proche assemblée générale", self.text(ag))
        board = self.sarl_file.with_user(self.partner).generate_irregularities_letter("board", "Point")
        self.assertIn("au gérant", self.text(board))


@tagged("post_install", "-at_install")
class TestSecuritiesAttestation(LegalCase):
    def _ready(self):
        self.engagement.sudo()._ea_ensure_task("C5.7")
        self.answer("C5.7", "q_kept", "yes")
        self.answer("C5.7", "q_agrees", "yes")

    def test_refusals(self):
        """uat2-legal B21."""
        generate = self.as_partner.generate_titres_attestation
        self.assertCode("titres-inspection-date-required", generate, None, 1000)
        self.assertCode("titres-count-required", generate, "2026-09-15")
        self.assertCode("titres-count-required", generate, "2026-09-15", 0)
        self.assertCode("titres-intermediary-required", generate, "2026-09-15", 1000, True)
        self.engagement.sudo()._ea_ensure_task("C5.7")
        self.assertCode("titres-work-incomplete", generate, "2026-09-15", 1000)

    def test_task_missing_on_a_sarl(self):
        """F052: a SARL issues no registered securities; the attestation is not offered."""
        as_partner = self.sarl_file.with_user(self.partner)
        self.assertFalse(as_partner.legal_titres_available)
        self.assertCode("titres-task-missing", as_partner.generate_titres_attestation, "2026-09-15", 1000)

    def test_register(self):
        self._ready()
        self.client.share_capital = 10_000_000
        text = self.text(self.as_partner.generate_titres_attestation("2026-02-10", 1000))
        self.assertIn("Exercice clos le 31 décembre 2025", text)
        self.assertIn("10 février 2026", text)
        self.assertIn("1 000 titres inscrits", text)
        self.assertIn("s'élève à 10 000 000 FCFA", text)
        self.assertIn("art. 746-2 %s" % MARK, text)
        self.assertNotIn("intermédiaire", text)

    def test_intermediary(self):
        """F055."""
        self._ready()
        text = self.text(self.as_partner.generate_titres_attestation("2026-02-10", 1000, True, "SGI Afrique"))
        self.assertIn("SGI Afrique (art. 746-1 %s)" % MARK, text)
        self.assertIn("relevé de l'intermédiaire arrêté au 10 février 2026", text)


@tagged("post_install", "-at_install")
class TestEquity(LegalCase):
    def _import(self, content, name):
        self.as_staff.import_trial_balance(name, content.encode("utf-8"))

    def _egm(self):
        return self.engagement.sudo()._ea_egm_row()

    def test_pure_conclusion(self):
        """uat2-legal B22."""
        self.assertEqual(equity_conclusion_of(True, True, 5_000_000, False), "breach")
        self.assertEqual(equity_conclusion_of(True, True, 5_000_000, None), "unchecked-breach")
        self.assertEqual(equity_conclusion_of(False, True, 5_000_000, False), "stale")
        self.assertEqual(equity_conclusion_of(False, True, 5_000_000, True), "ok")
        self.assertEqual(equity_conclusion_of(False, True, 5_000_000, None), "ok")
        self.assertEqual(equity_conclusion_of(False, False, 5_000_000, None), "none")
        self.assertEqual(equity_conclusion_of(False, True, None, None), "none")

    def test_breach_raises_the_workflow(self):
        self._import(LOSS_TB, "tb.csv")
        self.as_partner.set_share_capital(10_000_000)
        check = self.as_partner.equity_check()
        self.assertEqual(check["equity"], 2_000_000)
        self.assertEqual(check["half_capital"], 5_000_000)
        self.assertTrue(check["breach"])
        self.assertEqual(self._egm().due_date, date(2026, 10, 30))
        self.assertEqual(unmarked_articles(self._egm().basis), [])
        self.assertTrue(self.env["ea.audit.notice"].sudo().search_count([("user_id", "=", self.partner.id), ("kind", "=", "equity-breach")]))

    def test_conclusion_follows_the_figures(self):
        conclusion = lambda: self.engagement.sudo()._ea_equity_conclusion(self.as_partner.equity_status())
        self._import(LOSS_TB, "loss.csv")
        self.as_partner.set_share_capital(10_000_000)
        self.assertEqual(conclusion(), "unchecked-breach")
        self.as_partner.equity_check()
        self.assertEqual(conclusion(), "breach")
        self._import(HEALTHY_TB, "healthy.csv")
        self.assertEqual(self.as_partner.equity_status()["equity"], 9_000_000)
        self.assertEqual(conclusion(), "stale")
        self.as_partner.equity_check()
        self.assertEqual(conclusion(), "ok")
        self.assertFalse(self._egm())
        self._import(LOSS_TB, "loss2.csv")
        self.assertEqual(self.as_partner.equity_status()["equity"], 2_000_000)
        self.assertEqual(conclusion(), "unchecked-breach")

    def test_capital_defaults_to_account_101(self):
        """F056."""
        self._import(LOSS_TB, "tb.csv")
        status = self.as_partner.equity_status()
        self.assertEqual((status["share_capital"], status["share_capital_source"]), (10_000_000, "tb_101"))
        self.as_partner.set_share_capital(8_000_000)
        status = self.as_partner.equity_status()
        self.assertEqual((status["share_capital"], status["share_capital_source"]), (8_000_000, "client"))

    def test_no_trial_balance_no_breach(self):
        status = self.as_partner.equity_status()
        self.assertFalse(status["has_tb"])
        self.assertFalse(status["breach"])

    def test_invalid_amount(self):
        self.assertCode("invalid-amount", self.as_partner.set_share_capital, 0)
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).set_share_capital, 10)


@tagged("post_install", "-at_install")
class TestJointAuditorAndArt525(LegalCase):
    def test_joint_file_reaches_the_report(self):
        self.client.co_cac = True
        self.as_partner.record_joint_auditor("worksplit", "Cycles A-C cabinet 1 ; D-F cabinet 2.", True)
        self.as_partner.record_joint_auditor("disagreement", "Divergence sur la provision clients.")
        self.assertCode("invalid-key", self.as_partner.record_joint_auditor, "other", "x")
        self.assertEqual(self.engagement.sudo()._ea_completion_data("f8_worksplit")["confirmed"], True)
        self.ready()
        text = self.text(self.as_partner.issue_report_from_form(report_date="2026-03-31", material_misstatement=True, basis="Provision."))
        self.assertIn("Divergence sur la provision clients.", text)

    def test_joint_file_optimistic_lock(self):
        self.as_partner.record_joint_auditor("crossreview", "a", False, "")
        self.assertCode("stale-edit", self.as_partner.record_joint_auditor, "crossreview", "b", False, "")

    def test_persons_from_headcount(self):
        """F058: the threshold is at 200, à valider."""
        self.assertEqual(persons_from_headcount("212 salariés au 31/12"), "ten")
        self.assertEqual(persons_from_headcount("200"), "five")
        self.assertEqual(persons_from_headcount("1 250 salariés"), "ten")
        self.assertIsNone(persons_from_headcount("beaucoup"))

    def test_art525_certification(self):
        self.engagement.sudo()._ea_ensure_task("C5.10")
        self.assertCode("art525-work-incomplete", self.as_partner.generate_art525_certification)
        self.answer("C5.10", "headcount", "212 salariés")
        self.answer("C5.10", "amount", "185 000 000 FCFA bruts")
        document = self.as_partner.generate_art525_certification()
        self.assertEqual((document.kind, document.code), ("report", "C5.10"))
        text = self.text(document)
        self.assertIn("dix personnes les mieux rémunérées", text)
        self.assertIn("185 000 000 FCFA bruts", text)
        self.assertIn("Aux actionnaires,", text)
        self.assertEqual(unmarked_articles(text), [])
        self.assertIn("article 525 %s" % MARK, text)


@tagged("post_install", "-at_install")
class TestRegister(LegalCase):
    def test_organ_cards(self):
        row = self.sarl_file.with_user(self.partner).with_context(lang="en_US")
        self.assertEqual(row.legal_form_name, "SARL")
        self.assertIn("gérant", row.legal_board_name)

    def test_screen_static_text_marks_its_articles(self):
        folder = os.path.dirname(file_path("ea_audit_legal/views/legal_views.xml"))
        for path in glob.glob(os.path.join(folder, "*.xml")):
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(unmarked_articles(handle.read()), [], path)

    def test_manifest_carries_the_registers(self):
        self.as_partner.generate_deadlines()
        extra = self.engagement.sudo()._ea_manifest_extra()
        self.assertTrue(extra["statutoryDeadlines"])
        self.assertEqual(extra["alertes"], [])

    def test_archived_file_refuses(self):
        self.engagement.sudo().write({"phase": "archived"})
        self.assertCode("archived", self.as_partner.generate_deadlines)
        self.assertCode("archived", self.as_partner.start_alerte, "x")
        self.assertCode("archived", self.as_partner.add_convention, "a", "b", "director", "c")

    def test_eqr_reads_but_does_not_change(self):
        self.assertCode("eqr-read-only", self.engagement.with_user(self.eqr).generate_deadlines)

    def test_no_plain_orm_door(self):
        row = self.as_partner.add_convention("a", "b", "director", "c").with_user(self.partner)
        self.assertCode("forbidden", row.write, {"nature": "x"})
        self.assertCode("forbidden", row.unlink)
        self.assertCode("forbidden", self.env["ea.audit.legal.deadline"].with_user(self.partner).create, {"engagement_id": self.engagement.id, "key": "x", "due_date": "2026-01-01"})


@tagged("post_install", "-at_install")
class TestEnglishDocuments(LegalCase):
    """The report language of the engagement decides, whoever generates; the reader's language
    does not change a document."""

    FRENCH = ("commissaire", "Exercice clos", "Nous ", "Rapport ", "convention", "à valider", "Fait le")

    def setUp(self):
        super().setUp()
        self.engagement.sudo().report_language = "en"
        self.as_french_reader = self.as_partner.with_context(lang="fr_FR")

    def assert_english(self, document):
        self.assertEqual(document.sudo().language, "en")
        text = self.text(document)
        for word in self.FRENCH:
            self.assertNotIn(word, text)
        return text

    def test_the_default_is_the_firm_language(self):
        self.assertEqual(self.env["ea.audit.engagement"]._ea_firm_language(), "fr")
        self.assertEqual(self.make_engagement(client=self.sarl).report_language, "fr")
        self.env.company.sudo().partner_id.lang = "en_US"
        self.assertEqual(self.env["ea.audit.engagement"]._ea_firm_language(), "en")

    def test_the_audit_report_certifies_in_english_to_validate(self):
        document = self.as_french_reader.generate_audit_report("unmodified", "2026-03-31")
        text = self.assert_english(document)
        self.assertIn("We certify that", text)
        self.assertIn("(to validate)", text)
        self.assertIn("31/03/2026", text)

    def test_legal_documents(self):
        for document in (
            self.as_french_reader.generate_rapport_special(),
            self.as_french_reader.generate_article_715_report(),
        ):
            text = self.assert_english(document)
            self.assertIn("(to validate)", text)
        self.assertIn("art. 715 (to validate)", text)

    def test_the_jurist_lifts_the_english_mark(self):
        self.env.company.sudo().ea_articles_validated = True
        self.assertNotIn("(to validate)", self.text(self.as_partner.generate_article_715_report()))

    def test_letters_and_amounts(self):
        for kind in ("engagement", "rep_affirmation", "management_letter"):
            self.assert_english(self.as_french_reader.generate_letter(kind))
        self.env["ea.audit.misstatement"].sudo().create({
            "engagement_id": self.engagement.id, "description": "x", "amount": 5_000_000,
        })
        text = self.text(self.as_partner.generate_letter("rep_affirmation"))
        self.assertIn("5,000,000 FCFA", text)

    def test_exports_follow_the_report_language(self):
        filename, content = self.as_french_reader.ea_export_xlsx("findings")
        self.assertTrue(content)
        sheet = openpyxl.load_workbook(io.BytesIO(content)).active
        header = " ".join(str(cell.value) for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value)
        self.assertNotIn("Gravité", header)
        self.engagement.sudo().report_language = "fr"
        _name, content = self.as_partner.ea_export_xlsx("findings")
        sheet = openpyxl.load_workbook(io.BytesIO(content)).active
        header = " ".join(str(cell.value) for row in sheet.iter_rows(min_row=1, max_row=3) for cell in row if cell.value)
        self.assertIn("Gravité", header)
