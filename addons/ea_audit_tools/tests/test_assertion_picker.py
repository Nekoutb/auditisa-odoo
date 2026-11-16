import re

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAssertionPicker(TransactionCase):
    """Owner's mock-up of 2026-11-16: assertions are ticked from a list with their full name
    and what they mean; the field then shows the codes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.env["ir.module.module"].search([("name", "=", "ea_audit_tools")])._update_translations(["fr_FR"], overwrite=True)

    def test_every_assertion_says_what_it_means_in_both_languages(self):
        tags = self.env["ea.audit.assertion"].search([])
        self.assertEqual(set(tags.mapped("code")), {"C", "E", "A", "V", "P", "RO"})
        english = {tag.code: tag.description for tag in tags}
        self.assertTrue(all(english.values()))
        french = {tag.code: tag.description for tag in tags.with_context(lang="fr_FR")}
        self.assertTrue(all(french[code] and french[code] != english[code] for code in english))

    def test_every_assertion_field_on_screen_uses_the_picker(self):
        views = self.env["ir.ui.view"].search([("type", "in", ("form", "list")), ("arch_db", "ilike", "assertion_ids")])
        self.assertTrue(views)
        for view in views:
            for tag in re.findall(r'<field name="assertion_ids"[^>]*>', view.arch_db):
                self.assertIn('widget="ea_assertion_picker"', tag, view.xml_id)
