from odoo.tests import tagged

from ..rules import MESSAGES, rule_error
from .common import ReportsCase


@tagged("post_install", "-at_install")
class TestFrench(ReportsCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.env["ir.module.module"].search([("name", "in", ("ea_audit_core", "ea_audit_tools", "ea_audit_reports"))])._update_translations(["fr_FR"])
        cls.fr = cls.env(context=dict(cls.env.context, lang="fr_FR"))

    def test_every_refusal_is_translated_with_its_code_kept(self):
        untranslated = []
        for code in MESSAGES:
            english = rule_error(self.env, code).args[0]
            french = rule_error(self.fr, code).args[0]
            self.assertTrue(french.endswith("[%s]" % code), code)
            if french == english:
                untranslated.append(code)
        self.assertEqual(untranslated, [])

    def test_a_letter_comes_in_the_report_language(self):
        document = self.engagement.with_user(self.senior).with_context(lang="fr_FR").generate_letter("engagement")
        self.assertEqual(document.title, "Lettre de mission")
        self.assertEqual(document.language, "fr")

    def test_the_gates_read_in_french(self):
        html = self.engagement.with_user(self.partner).with_context(lang="fr_FR").completion_gates_html
        self.assertIn("Conclusion générale de l", str(html))

    def test_french_dates_on_the_report(self):
        self.green_completion()
        text = self.text_of(self.engagement.with_user(self.partner).with_context(lang="fr_FR").issue_report_from_form(report_date="2026-03-31"))
        self.assertIn("Fait le 31/03/2026", text)

    def test_a_field_label_reads_in_french(self):
        labels = self.fr["ea.audit.legal.hold"].fields_get(["reason"])
        self.assertTrue(labels)
        selection = self.fr["ea.audit.engagement"].fields_get(["opinion"])["opinion"]["selection"]
        self.assertIn(("unmodified", "Sans réserve"), selection)
