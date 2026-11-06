from odoo.tests import tagged

from odoo.addons.ea_audit_tools.rules import MESSAGES, rule_error

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestFrench(ToolsCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.env["ir.module.module"].search([("name", "in", ("ea_audit_core", "ea_audit_tools"))])._update_translations(["fr_FR"], overwrite=True)
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

    def test_a_refusal_reaches_the_user_in_french(self):
        as_french = self.as_reader.with_context(lang="fr_FR")
        with self.assertRaises(Exception) as caught:
            as_french.import_trial_balance("b.csv", b"x")
        self.assertIn("read-only-role", str(caught.exception))
        self.assertIn("modifier", str(caught.exception))
        message = rule_error(self.fr, "stale-version").args[0]
        self.assertIn("Seule la dernière version", message)

    def test_the_hub_reads_as_m7(self):
        tile = self.env.ref("ea_audit_tools.tile_materiality").with_env(self.fr)
        self.assertEqual(tile.name, "Seuil de signification")
        self.assertEqual(tile.description, "Global, de travail, manifestement négligeable, avec approbation.")
        self.assertEqual(self.env.ref("ea_audit_tools.tile_sad").with_env(self.fr).name, "Écarts d'audit")

    def test_field_labels_and_choices(self):
        Materiality = self.env["ea.audit.materiality"].with_env(self.fr)
        fields = Materiality.fields_get(["overall", "state"])
        self.assertEqual(fields["overall"]["string"], "Seuil global")
        self.assertIn(("approved", "Approuvé"), fields["state"]["selection"])
        cell = self.env["ea.audit.cra.assessment"].with_env(self.fr).fields_get(["ir"])
        self.assertEqual(cell["ir"]["string"], "Risque inhérent")

    def test_the_boards_static_text(self):
        view = self.env.ref("ea_audit_tools.view_engagement_materiality_board").with_env(self.fr)
        self.assertIn("Historique des versions", view.arch)
        self.assertIn("Papiers alimentés", view.arch)
        self.assertIn("Exhaustivité", self.env.ref("ea_audit_tools.view_engagement_cra_board").with_env(self.fr).arch)

    def test_computed_labels_follow_the_language(self):
        self.import_tb()
        board = self.engagement.sudo().with_context(lang="fr_FR")
        board.invalidate_recordset()
        self.assertIn("balance v1", board.bilan_label)
        version = board._ea_current_tb_version().with_context(lang="fr_FR")
        self.assertIn("Débits égaux aux crédits", version.checks_text)
        self.assertIn("Aucune version", board.mat_status_label)

    def test_a_lead_alert_reads_as_a_sentence(self):
        self.import_tb("Compte;Libellé;Mouvement débit;Mouvement crédit\n201000;Frais;100;0\n701000;Ventes;0;100\n")
        schedule = self.env["ea.audit.lead.schedule"].sudo().with_context(lang="fr_FR").search([
            ("engagement_id", "=", self.engagement.id), ("index_code", "=", "L"),
        ])
        self.assertIn("La classe 20", schedule.alerts_label)
