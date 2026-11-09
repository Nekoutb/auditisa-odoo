import re

from odoo.tests import HttpCase, tagged
from odoo.tools.misc import file_path

from ..services import howto
from .common import PlatformMixin


@tagged("post_install", "-at_install")
class TestHowto(PlatformMixin, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_platform()
        cls.env["res.lang"]._activate_lang("fr_FR")
        # The menus' French comes from fr.po like on the console (where French is installed).
        cls.env["ir.module.module"]._load_module_terms(["ea_platform_admin"], ["fr_FR"], overwrite=True)
        cls.guide = cls.env.ref("ea_platform_admin.howto_new_firm")

    def _visible(self, user):
        return self.env["ir.ui.menu"].with_user(user)._visible_menu_ids()

    def test_the_how_to_menu_is_visible_to_operators(self):
        menu = self.env.ref("ea_platform_admin.menu_howto")
        entry = self.env.ref("ea_platform_admin.menu_howto_new_firm")
        self.assertEqual(menu.parent_id, self.env.ref("ea_platform_admin.menu_root"))
        for user in (self.operator, self.owner):
            visible = self._visible(user)
            self.assertIn(menu.id, visible)
            self.assertIn(entry.id, visible)
        self.assertNotIn(menu.id, self._visible(self.viewer))

    def test_the_menu_opens_the_guide(self):
        action = self.env.ref("ea_platform_admin.menu_howto_new_firm").action
        self.assertEqual(action.res_model, "platform.howto")
        self.assertEqual(action.res_id, self.guide.id)
        self.assertEqual(self.guide.with_user(self.operator).step_count, 8)

    def test_the_menu_reads_in_both_languages(self):
        menu = self.env.ref("ea_platform_admin.menu_howto_new_firm")
        self.assertEqual(menu.with_context(lang="en_US").name, "Provision a new firm")
        self.assertEqual(menu.with_context(lang="fr_FR").name, "Mettre en service un nouveau cabinet")
        self.assertEqual(self.env.ref("ea_platform_admin.menu_howto").with_context(lang="fr_FR").name, "Guides")

    def _body(self, lang):
        guide = self.guide.with_user(self.operator).with_context(lang=lang)
        guide.invalidate_recordset(["body", "name"])
        return str(guide.body), guide.name

    def test_the_page_renders_in_english(self):
        body, name = self._body("en_US")
        self.assertEqual(name, "Provision a new firm")
        self.assertIn("Before you start: what to collect from the client", body)
        self.assertIn("<strong>Create the server</strong>", body)
        self.assertEqual(len(re.findall(r'class="o_ea_howto_step"', body)), 8)
        self.assertIn("Step 8", body)
        self.assertIn("/ea_platform_admin/static/howto/new_firm/en/03-review.png", body)
        self.assertNotIn("/fr/", body)

    def test_the_page_renders_in_french(self):
        body, name = self._body("fr_FR")
        self.assertEqual(name, "Mettre en service un nouveau cabinet")
        self.assertIn("Avant de commencer", body)
        self.assertIn("<strong>Créer le serveur</strong>", body)
        self.assertIn("Étape 8", body)
        self.assertIn("/ea_platform_admin/static/howto/new_firm/fr/03-review.png", body)
        self.assertNotIn("/en/", body)
        self.assertNotIn("What to do", body)

    def test_every_picture_exists_and_is_served(self):
        item = howto.guide("new_firm")
        for folder in howto.LANGUAGE_FOLDERS:
            for name in howto.images(item):
                self.assertTrue(file_path(f"ea_platform_admin/static/howto/new_firm/{folder}/{name}"))
        for folder in howto.LANGUAGE_FOLDERS:
            response = self.url_open(f"/ea_platform_admin/static/howto/new_firm/{folder}/01-new-firm-empty.png")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Content-Type"], "image/png")

    def test_nothing_on_the_page_can_be_typed_into(self):
        self.assertFalse(self.env["platform.howto"].with_user(self.operator).has_access("write"))
        self.assertFalse(self.env["platform.howto"].with_user(self.owner).has_access("create"))

    def test_the_operator_opens_the_guide_in_the_browser(self):
        self.authenticate("p_operator", "p_operator")
        response = self.url_open("/odoo/action-ea_platform_admin.action_howto_new_firm")
        self.assertEqual(response.status_code, 200)
