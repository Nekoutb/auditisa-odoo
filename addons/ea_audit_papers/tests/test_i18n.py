from odoo.tests import tagged

from ..models.errors import MESSAGES, paper_error
from .common import PaperCase


@tagged("post_install", "-at_install")
class TestFrench(PaperCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.env["ir.module.module"].search([("name", "in", ("ea_audit_core", "ea_audit_papers"))])._update_translations(
            ["fr_FR"], overwrite=True,
        )
        cls.fr = cls.env(context=dict(cls.env.context, lang="fr_FR"))

    def test_every_refusal_of_this_addon_is_translated(self):
        untranslated = []
        for code in MESSAGES:
            en = paper_error(self.env, code).args[0]
            fr = paper_error(self.fr, code).args[0]
            self.assertTrue(fr.endswith("[%s]" % code), code)
            if fr == en:
                untranslated.append(code)
        self.assertEqual(untranslated, [])

    def test_p15_facts_and_decision_read_in_french(self):
        profile = self.engagement._ea_profile() or self.env["ea.audit.engagement.profile"].sudo().create(
            {"engagement_id": self.engagement.id}
        )
        profile.write({"q1_listed": "yes", "q3_controls_law": "no"})
        self.paper("P1.5").with_user(self.staff).save_answers({"decision": "none", "decision_why": "Politique du cabinet."})
        values = self.paper("P1.5").with_context(lang="fr_FR")._ea_auto_values()
        self.assertEqual((values["profile_listed"], values["profile_law"]), ("Oui", "Non"))
        self.assertEqual(values["profile_risks"], "Sans réponse")
        self.assertNotIn("profile_monitoring", values)
        self.assertIn("La décision reste celle du cabinet", values["decision_note"])
        self.assertIn("Pas de revue de qualité pour cette mission.", values["decision_conclusion"])
        self.assertIn("Décidé par", values["decision_conclusion"])

    def test_paper_incomplete_names_the_part_in_french(self):
        item = self.item(self.engagement, "P3.1").with_user(self.senior).with_context(lang="fr_FR")
        message = None
        try:
            item.action_sign("preparer")
        except Exception as error:  # noqa: BLE001
            message = error.args[0]
        # P3.1 is in the layout of 2026-11-17: its parts are the tasks and the conclusion
        self.assertIn("Travaux requis", message)
        self.assertIn("Reste à compléter", message)
