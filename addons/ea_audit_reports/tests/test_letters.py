from odoo.exceptions import AccessError
from odoo.tests import tagged

from ..services.articles import MARK, unmarked_articles
from ..services.letters import LETTER_KINDS, end_sentence, mandate_expiry_year
from .common import ReportsCase


@tagged("post_install", "-at_install")
class TestLetters(ReportsCase):
    def test_each_kind_goes_to_its_task(self):
        codes = {}
        for kind in LETTER_KINDS:
            document = self.as_senior.generate_letter(kind, "fr")
            codes[kind] = document.code
            self.assertEqual(document.sudo().current_version_id.attachment_id.raw[:2], b"PK")
            self.assertEqual(unmarked_articles(self.text_of(document)), [], kind)
        self.assertEqual(codes["engagement"], "P1.4")
        self.assertEqual(codes["rep_affirmation"], "C3.1")
        self.assertEqual(codes["rep_complementary"], "C3.1")
        self.assertEqual(codes["management_letter"], "C5.11")
        self.assertEqual(codes["tcwg_completion"], "C5.11")
        self.assertIn(codes["planning_tcwg"], ("P7.1", "C5.11"))

    def test_regeneration_adds_a_version(self):
        first = self.as_senior.generate_letter("engagement", "fr")
        second = self.as_senior.generate_letter("engagement", "fr")
        self.assertEqual(first, second)
        self.assertEqual(second.sudo().current_version, 2)
        self.assertEqual(len(second.sudo().version_ids), 2)

    def test_two_distinct_letters_on_c31_meet_the_gate(self):
        self.as_senior.generate_letter("rep_affirmation", "fr")
        self.assertIn("rep_letters_generated", self.failed(self.as_partner.completion_gates()))
        self.as_senior.generate_letter("rep_complementary", "fr")
        self.assertNotIn("rep_letters_generated", self.failed(self.as_partner.completion_gates()))

    def test_engagement_letter(self):
        self.client.write({"address": "Douala", "registration_number": "RC/1", "niu": "M1", "mandate_type": "ago", "mandate_start_year": 2024, "co_cac": True})
        text = self.text_of(self.as_senior.generate_letter("engagement", "fr"))
        self.assertIn("Lettre de mission", text)
        self.assertIn("Adresse : Douala · RCCM : RC/1 · NIU : M1", text)
        self.assertIn("SYSCOHADA révisé (AUDCIF)", text)
        self.assertIn("31/12/2025", text)
        self.assertIn("de 2024 à 2029", text.replace("du 2024", "de 2024"))
        self.assertIn("(art. 704 %s" % MARK, text)
        self.assertIn("art. 719 %s" % MARK, text)
        self.assertEqual(mandate_expiry_year("statutes", 2024), 2025)
        self.assertEqual(mandate_expiry_year("ago", 2024), 2029)

    def test_english_on_request(self):
        text = self.text_of(self.as_senior.generate_letter("engagement", "en"))
        self.assertIn("Engagement letter", text)
        self.assertIn("article 718 (to validate)", text)

    def test_affirmation_lists_uncorrected_misstatements_in_fcfa(self):
        Misstatement = self.env["ea.audit.misstatement"].sudo()
        Misstatement.create({"engagement_id": self.engagement.id, "description": "Provision", "amount": 5_000_000})
        Misstatement.create({"engagement_id": self.engagement.id, "description": "Cut-off", "amount": 12_500_000})
        Misstatement.create({"engagement_id": self.engagement.id, "description": "Trivial", "amount": 1, "trivial": True})
        self.answer("C3.1", "p_specific", "Le stock de sécurité existe.")
        text = self.text_of(self.as_senior.generate_letter("rep_affirmation", "fr"))
        self.assertIn("• Cut-off — 12 500 000 FCFA", text)
        self.assertIn("• Provision — 5 000 000 FCFA", text)
        self.assertLess(text.index("Cut-off"), text.index("Provision"))
        self.assertNotIn("Trivial", text)
        self.assertIn("• Le stock de sécurité existe.", text)

    def test_governance_report(self):
        Finding = self.env["ea.audit.finding"].sudo()
        Finding.create({"engagement_id": self.engagement.id, "number": 1, "route": "c1", "title": "Observation", "severity": "observation"})
        Finding.create({"engagement_id": self.engagement.id, "number": 2, "route": "c1", "title": "Séparation des tâches", "severity": "significant_deficiency", "recommendation": "Deux signataires"})
        Finding.create({"engagement_id": self.engagement.id, "number": 3, "route": "b4", "title": "Point C1.2", "detail": "Détail"})
        text = self.text_of(self.as_senior.generate_letter("tcwg_completion", "fr"))
        self.assertIn("[Déficience significative] Séparation des tâches Recommandation : Deux signataires.", text)
        self.assertLess(text.index("Séparation"), text.index("[Observation]"))
        self.assertIn("Point C1.2 — Détail. (statut : ouvert)", text)
        self.assertIn("classées en P2.1", text)

    def test_planning_letter_says_what_is_missing(self):
        text = self.text_of(self.as_senior.generate_letter("planning_tcwg", "fr"))
        self.assertIn("Associé responsable", text)
        self.assertIn("ne sont pas encore approuvés", text)
        self.with_materiality()
        text = self.text_of(self.as_senior.generate_letter("planning_tcwg", "fr"))
        self.assertIn("10 000 000 FCFA", text)

    def test_letterhead(self):
        self.env.company.write({"ea_display_name": "Cabinet Exemple", "ea_letterhead1": "BP 1 Douala", "ea_letterhead_footer": "Membre ONECCA"})
        text = self.text_of(self.as_senior.generate_letter("management_letter", "fr")).splitlines()
        self.assertEqual(text[:2], ["Cabinet Exemple", "BP 1 Douala"])
        self.assertEqual(text[-1], "Membre ONECCA")

    def test_jurist_validation_lifts_the_mark(self):
        self.env.company.ea_articles_validated = True
        self.assertNotIn(MARK, self.text_of(self.as_senior.generate_letter("engagement", "fr")))

    def test_guards(self):
        self.assertCode("invalid-letter-kind", self.as_senior.generate_letter, "other", "fr")
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).generate_letter, "engagement", "fr")
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.outsider).generate_letter, "engagement", "fr")
        self.engagement.sudo().write({"phase": "archived"})
        self.assertCode("archived", self.as_senior.generate_letter, "engagement", "fr")

    def test_generated_documents_are_team_only(self):
        document = self.as_senior.generate_letter("engagement", "fr")
        self.assertTrue(document.with_user(self.reader).title)
        with self.assertRaises(AccessError):
            document.with_user(self.outsider).read(["title"])
        with self.assertRaises(AccessError):
            document.with_user(self.admin).read(["title"])

    def test_no_plain_orm_door(self):
        document = self.as_senior.generate_letter("engagement", "fr")
        self.assertCode("forbidden", document.with_user(self.partner).write, {"title": "x"})
        self.assertCode("forbidden", document.with_user(self.partner).unlink)

    def test_end_sentence(self):
        self.assertEqual(end_sentence(" Point "), "Point.")
        self.assertEqual(end_sentence("Point !"), "Point !")
