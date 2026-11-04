from odoo.tests import tagged

from odoo.addons.ea_audit_core.services.errors import MESSAGES, rule_error

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestFrench(EaAuditCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.env["ir.module.module"].search([("name", "=", "ea_audit_core")])._update_translations(["fr_FR"], overwrite=True)
        cls.fr = cls.env(context=dict(cls.env.context, lang="fr_FR"))

    def test_every_refusal_is_translated_with_its_code_kept(self):
        untranslated = []
        for code in MESSAGES:
            params = {"domains": "eca.com"} if code == "email-domain-not-allowed" else {"gates": "x"} if code == "gates-failed" else {}
            en = rule_error(self.env, code, **params).args[0]
            fr = rule_error(self.fr, code, **params).args[0]
            self.assertTrue(fr.endswith("[%s]" % code), code)
            if fr == en:
                untranslated.append(code)
        self.assertEqual(untranslated, [])

    def test_a_refusal_reaches_the_french_user_in_french(self):
        self.assertIn("préparateur", rule_error(self.fr, "self-review").args[0])

    def test_task_titles(self):
        template = self.env.ref("ea_audit_core.task_C2_1")
        self.assertEqual(template.with_env(self.fr).title, "Revue finale globale des états financiers (ISA 520)")
        self.assertEqual(template.title, "Final Overall Financial Statement Review (ISA 520)")

    def test_labels_and_selections(self):
        engagement = self.fr["ea.audit.engagement"]
        self.assertEqual(engagement.fields_get(["fiscal_year"])["fiscal_year"]["string"], "Exercice")
        phases = dict(engagement.fields_get(["phase"])["phase"]["selection"])
        self.assertEqual(phases["acceptance"], "Acceptation")
