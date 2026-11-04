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

    def test_paper_incomplete_names_the_part_in_french(self):
        item = self.item(self.engagement, "P3.1").with_user(self.senior).with_context(lang="fr_FR")
        message = None
        try:
            item.action_sign("preparer")
        except Exception as error:  # noqa: BLE001
            message = error.args[0]
        self.assertIn("Partie A", message)
        self.assertIn("Reste à compléter", message)
