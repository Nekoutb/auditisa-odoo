from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

CODE = "ea_client_addon_sample"


@tagged("post_install", "-at_install")
class TestOffHidesAndKeeps(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="sample_user", groups="base.group_user")
        cls.switches = cls.env["ea.addon.switch"]
        cls.menu = cls.env.ref(f"{CODE}.menu_note")

    def _switch(self, on):
        self.switches._sync([CODE] if on else [])
        self.env.invalidate_all()
        self.env.registry.clear_cache("groups")

    def _visible(self):
        return self.menu.id in self.env["ir.ui.menu"].with_user(self.user)._visible_menu_ids()

    def test_a_new_install_starts_off_until_someone_asks(self):
        self.switches._sync(None)
        self.assertFalse(self.switches._is_on(CODE))
        self.assertFalse(self._visible())

    def test_on_shows_the_menu_and_lets_a_user_work(self):
        self._switch(True)
        self.assertTrue(self._visible())
        note = self.env["ea.client.sample.note"].with_user(self.user).create({"name": "On"})
        note.action_mark_reviewed()
        self.assertTrue(note.reviewed)

    def test_off_hides_the_menu_and_refuses_the_model(self):
        self._switch(True)
        note = self.env["ea.client.sample.note"].with_user(self.user).create({"name": "Kept"})
        self._switch(False)
        self.assertFalse(self._visible())
        with self.assertRaises(AccessError):
            note.with_user(self.user).read(["name"])
        with self.assertRaises(UserError):
            self.env["ea.client.sample.note"].with_user(self.user).create({"name": "No"})

    def test_off_refuses_even_code_that_runs_as_superuser_but_keeps_reads(self):
        self._switch(True)
        note = self.env["ea.client.sample.note"].sudo().create({"name": "Kept"})
        self._switch(False)
        for attempt in (
            lambda: note.write({"name": "Changed"}),
            lambda: note.unlink(),
            lambda: note.action_mark_reviewed(),
            lambda: self.env["ea.client.sample.note"].sudo().create({"name": "No"}),
        ):
            with self.assertRaises(UserError):
                attempt()
        self.assertEqual(note.name, "Kept")

    def test_on_again_restores_everything_and_nothing_was_uninstalled(self):
        self._switch(True)
        note = self.env["ea.client.sample.note"].with_user(self.user).create({"name": "Kept"})
        self._switch(False)
        self.assertEqual(
            self.env["ir.module.module"].sudo().search([("name", "=", CODE)]).state, "installed",
        )
        self.env.cr.execute("SELECT name FROM ea_client_sample_note WHERE id = %s", [note.id])
        self.assertEqual(self.env.cr.fetchone()[0], "Kept")
        self._switch(True)
        self.assertEqual(note.with_user(self.user).name, "Kept")
        self.assertTrue(self._visible())

    def test_the_marker_is_what_makes_it_optional_and_the_figures_report_it(self):
        self.assertIn(CODE, self.switches._client_addons_installed())
        self._switch(True)
        self.assertEqual(self.switches._codes_on(), [CODE])
        self._switch(False)
        self.assertEqual(self.switches._codes_on(), [])

    def test_a_base_feature_is_not_a_switchable_add_on(self):
        self.assertNotIn("ea_audit_addons", self.switches._client_addons_installed())
        self.assertNotIn("ea_audit_reports", self.switches._client_addons_installed())
