"""The owner's settings rulings of 2026-11-07: the sign-off matrix edited on screen in place of the
per-task rules screen, the file index in the order of the audit, and no API key for anyone."""
import datetime

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import EaAuditCase

PHASES = ["1_acceptance", "2_planning", "3_execution", "4_conclusion"]


@tagged("post_install", "-at_install")
class TestSignoffMatrixOnScreen(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.Template = self.env["ea.audit.task.template"]
        self.e43 = self.Template.search([("code", "=", "E4.3")])
        self.p11 = self.Template.search([("code", "=", "P1.1")])

    def test_the_per_task_screen_is_gone_and_the_rules_stay(self):
        self.assertFalse(self.env.ref("ea_audit_core.menu_signoff_rules", raise_if_not_found=False))
        self.assertFalse(self.env.ref("ea_audit_core.action_signoff_task_rule", raise_if_not_found=False))
        self.assertIn("ea.audit.signoff.task.rule", self.env)
        self.assertTrue(self.env.ref("ea_audit_core.menu_signoff_matrix"))

    def test_a_partner_edits_the_firm_s_columns_on_screen(self):
        before = self.env["ea.audit.activity"].sudo().search_count([("code", "=", "E4.3")])
        row = self.e43.with_user(self.partner)
        # the list's own save: web_save, under the partner, who has no right on the file index
        row.web_save({"firm_min_preparer": "senior", "firm_partner_required": "yes"}, {"code": {}})
        rule = self.TaskRule.sudo().search([("code", "=", "E4.3")])
        self.assertEqual((rule.min_preparer, rule.min_reviewer, rule.partner_required), ("senior", False, "yes"))
        fresh = self.e43.with_user(self.partner)
        self.assertEqual((fresh.firm_min_preparer, fresh.firm_partner_required), ("senior", "yes"))
        self.assertEqual(fresh.matrix_min_preparer, "senior")
        self.assertTrue(fresh.matrix_partner)
        self.assertTrue(fresh.matrix_firm_rule)
        # through save_task_rules: the audit log has the change
        self.assertEqual(self.env["ea.audit.activity"].sudo().search_count([("code", "=", "E4.3")]), before + 1)
        # one column changed keeps the others
        row.write({"firm_min_reviewer": "manager"})
        self.assertEqual((rule.min_preparer, rule.min_reviewer, rule.partner_required), ("senior", "manager", "yes"))
        # back to the firm default everywhere: the rule goes
        row.write({"firm_min_preparer": False, "firm_min_reviewer": False, "firm_partner_required": "default"})
        self.assertFalse(self.TaskRule.sudo().search([("code", "=", "E4.3")]))
        self.assertFalse(self.e43.with_user(self.partner).matrix_firm_rule)

    def test_lifting_a_default_partner_signature_stays_possible(self):
        self.assertTrue(self.p11.with_user(self.admin).matrix_partner)
        self.p11.with_user(self.admin).write({"firm_partner_required": "no"})
        self.assertFalse(self.p11.with_user(self.admin).matrix_partner)

    def test_only_partners_and_the_firm_admin_edit_it(self):
        for user in (self.manager, self.senior, self.staff, self.reader):
            with self.assertRaises(Exception):
                self.e43.with_user(user).write({"firm_min_preparer": "manager"})
        self.assertFalse(self.TaskRule.sudo().search([("code", "=", "E4.3")]))
        self.assertCode("invalid-team-role", self.e43.with_user(self.partner).write, {"firm_min_preparer": "eqr_reviewer"})

    def test_the_file_index_itself_stays_read_only(self):
        with mute_logger("odoo.models", "odoo.addons.base.models.ir_model"), self.assertRaises(AccessError):
            self.e43.with_user(self.partner).write({"title": "Changé"})
        with mute_logger("odoo.models", "odoo.addons.base.models.ir_model"), self.assertRaises(AccessError):
            self.e43.with_user(self.admin).write({"firm_min_preparer": "senior", "phase": "acceptance"})

    def test_the_matrix_view_is_editable_for_a_partner_on_the_firm_columns_only(self):
        arch = self.Template.with_user(self.partner).get_view(self.env.ref("ea_audit_core.view_signoff_matrix_list").id, "list")["arch"]
        self.assertIn('editable="bottom"', arch)
        self.assertNotIn('edit="False"', arch)
        for name in ("firm_min_preparer", "firm_min_reviewer", "firm_partner_required"):
            self.assertIn('name="%s"' % name, arch)

    def test_excel_export_and_import_are_still_there(self):
        filename, content = self.TaskRule.with_user(self.partner)._ea_matrix_workbook()
        self.assertTrue(filename.endswith(".xlsx") and content)
        self.assertEqual(self.env.ref("ea_audit_core.action_signoff_matrix_import").res_model, "ea.audit.signoff.matrix.import")


@tagged("post_install", "-at_install")
class TestFileIndexOrder(EaAuditCase):
    def test_numbered_in_the_order_of_the_audit(self):
        Template = self.env["ea.audit.task.template"]
        rows = Template.search([], order="chrono_no")
        self.assertEqual(rows.mapped("chrono_no"), list(range(1, len(rows) + 1)))
        self.assertEqual(rows, Template.search([], order="matrix_order, id"))
        steps = rows.mapped("phase_step")
        self.assertEqual(steps, sorted(steps))
        self.assertEqual(rows[0].phase, "acceptance")
        self.assertEqual(rows[-1].phase, "conclusion")
        # P1.2 before P1.10-like gaps: the number, not the text, orders a code
        codes = [code for code in rows.mapped("code") if code.startswith("E4.")]
        self.assertEqual(codes, sorted(codes, key=lambda c: int(c.split(".")[1])))

    def test_the_list_opens_in_that_order_and_groups_phases_in_that_order(self):
        Template = self.env["ea.audit.task.template"].with_user(self.staff)
        arch = Template.get_view(self.env.ref("ea_audit_core.view_task_template_list").id, "list")["arch"]
        self.assertIn('default_order="matrix_order"', arch)
        self.assertIn('name="chrono_no"', arch)
        groups = Template.formatted_read_group([], ["phase_step"], ["__count"])
        self.assertEqual([g["phase_step"] for g in groups], PHASES)
        # sorting the Phase column is chronological too, unlike the plain phase
        self.assertEqual(Template.search([], order="phase_step, chrono_no").mapped("phase_step")[0], PHASES[0])
        self.assertEqual(Template.search([], order="phase_step desc, chrono_no")[:1].phase, "conclusion")
        action = self.env.ref("ea_audit_core.action_task_template")
        self.assertEqual(action.search_view_id, self.env.ref("ea_audit_core.view_task_template_search"))

    def test_french_and_english_labels(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"].search([("name", "=", "ea_audit_core")])._update_translations(["fr_FR"], overwrite=True)
        fr = self.env["ea.audit.task.template"].with_context(lang="fr_FR")
        en = self.env["ea.audit.task.template"].with_context(lang="en_US")
        self.assertEqual(dict(fr.fields_get(["phase_step"])["phase_step"]["selection"])["1_acceptance"], "Acceptation")
        self.assertEqual(dict(en.fields_get(["phase_step"])["phase_step"]["selection"])["4_conclusion"], "Conclusion")
        self.assertEqual(fr.fields_get(["chrono_no"])["chrono_no"]["string"], "Ordre")
        self.assertEqual(en.fields_get(["chrono_no"])["chrono_no"]["string"], "Order")
        self.assertEqual(fr.fields_get(["firm_min_preparer"])["firm_min_preparer"]["string"], "Préparateur minimum du cabinet")


@tagged("post_install", "-at_install")
class TestNoApiKeys(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.system = self.env.ref("base.user_admin")
        self.assertTrue(self.system.has_group("base.group_system"))

    def test_nobody_creates_a_key(self):
        for user in (self.admin, self.system, self.partner, self.staff):
            Keys = self.env["res.users.apikeys"].with_user(user)
            with self.assertRaises(AccessError):
                Keys._generate(None, "integration", False)
            with self.assertRaises(AccessError):
                Keys.sudo()._generate("rpc", "integration", False)
            with self.assertRaises(AccessError):
                self.env["res.users.apikeys.description"].with_user(user).create({"name": "integration", "duration": "1"})
            with self.assertRaises(AccessError):
                self.env["res.users.apikeys.description"].with_user(user).make_key()
            with self.assertRaises(AccessError):
                user.with_user(user).api_key_wizard()
        # nor the superuser
        with self.assertRaises(AccessError):
            self.env["res.users.apikeys"]._generate(None, "root", False)
        self.env.flush_all()
        self.env.cr.execute("SELECT count(*) FROM res_users_apikeys")
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_the_screens_no_longer_offer_one(self):
        Users = self.env["res.users"].with_user(self.system)
        for xmlid in ("base.view_users_form_simple_modif", "base.view_users_form"):
            arch = Users.get_view(self.env.ref(xmlid).id, "form")["arch"]
            start = arch.index('name="api_keys"')
            tag = arch[arch.rindex("<", 0, start):arch.index(">", start)]
            self.assertIn('invisible="1"', tag, xmlid)

    def test_two_factor_trusted_devices_are_not_api_keys(self):
        if "auth_totp.device" not in self.env:
            return
        expires = datetime.datetime.now() + datetime.timedelta(days=30)
        key = self.env["auth_totp.device"].with_user(self.staff).sudo()._generate("browser", "Chrome", expires)
        self.assertTrue(key)
