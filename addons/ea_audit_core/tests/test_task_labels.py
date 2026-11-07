from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTaskLabels(TransactionCase):
    """The sign-off policy screens show each task's description beside its code."""

    def setUp(self):
        super().setUp()
        Template = self.env["ea.audit.task.template"]
        self.task = Template.search([("code", "=", "C1.1")], limit=1) or Template.search([], limit=1)
        self.assertTrue(self.task, "the audit file index is loaded")

    def test_code_alone_by_default(self):
        self.assertEqual(self.task.display_name, self.task.code)

    def test_code_and_description_on_policy_screens(self):
        shown = self.task.with_context(ea_task_with_title=True).display_name
        self.assertEqual(shown, "%s - %s" % (self.task.code, self.task.title))

    def test_description_in_french(self):
        task = self.task.with_context(lang="fr_FR", ea_task_with_title=True)
        if not self.env["res.lang"]._lang_get("fr_FR"):
            self.skipTest("French is not installed")
        self.assertEqual(task.display_name, "%s - %s" % (task.code, task.title))

    def test_search_by_description(self):
        words = (self.task.title or "").split()
        word = max(words, key=len)
        found = self.env["ea.audit.task.template"].name_search(word, limit=500)
        self.assertIn(self.task.id, [row[0] for row in found])

    def test_policy_form_lists_code_description_and_phase(self):
        arch = self.env.ref("ea_audit_core.view_signoff_policy_form").arch
        self.assertIn("ea_task_with_title", arch)
        self.assertNotIn("many2many_tags", arch)
