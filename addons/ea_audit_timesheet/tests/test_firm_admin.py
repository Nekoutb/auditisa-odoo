"""The firm administrator: what they run without the technical account, and every way
they might try to reach beyond it."""
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import TimesheetCase

MAIL = {"host": "smtp.example.com", "port": 587, "encryption": "starttls", "user": "firm@example.com", "password": "not-a-real-secret"}


class FirmAdminCase(TimesheetCase):
    def fa(self, user=None):
        return self.FirmAdmin.with_user(user or self.admin)

    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("ea_audit.staging_band", "0")


@tagged("post_install", "-at_install")
class TestUsers(FirmAdminCase):
    def test_invite_gives_a_link_and_no_password(self):
        result = self.fa().ea_fa_invite("nouveau@gov.example.com", "Nouveau", "senior")
        user = self.env["res.users"].sudo().browse(result["user_id"])
        self.assertIn("/web/signup", result["link"])
        self.assertIn("token=", result["link"])
        self.assertEqual(user._ea_firm_role(), "senior")
        self.assertTrue(self.env["hr.employee"].sudo().search_count([("user_id", "=", user.id)]))
        self.env.cr.execute("SELECT password FROM res_users WHERE id = %s", [user.id])
        self.assertFalse(self.env.cr.fetchone()[0])
        self.assertTrue(self.Log.search_count([("kind", "=", "user_invited"), ("target_id", "=", user.id)]))

    def test_invite_sends_no_mail(self):
        before = self.env["mail.mail"].sudo().search_count([])
        self.fa().ea_fa_invite("sansmail@gov.example.com", "Sans Mail", "staff")
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), before)

    def test_allowed_domains_are_respected(self):
        self.fa().ea_fa_set_domains("gov.example.com")
        self.assertCode("email-domain-not-allowed", self.fa().ea_fa_invite, "x@ailleurs.example.org", "X", "staff")
        self.assertTrue(self.fa().ea_fa_invite("y@gov.example.com", "Y", "staff")["user_id"])

    def test_bad_input(self):
        self.assertCode("fa-email-invalid", self.fa().ea_fa_invite, "pas-un-mail", "X", "staff")
        self.assertCode("fa-role-invalid", self.fa().ea_fa_invite, "z@gov.example.com", "Z", "root")
        self.assertCode("fa-user-exists", self.fa().ea_fa_invite, self.staff.login, "X", "staff")
        self.assertCode("invalid-email-domain", self.fa().ea_fa_set_domains, "pas un domaine!")

    def test_assign_a_role(self):
        self.fa().ea_fa_set_role(self.staff.id, "manager")
        self.assertEqual(self.staff._ea_firm_role(), "manager")
        self.fa().ea_fa_set_role(self.staff.id, "read_only")
        self.assertEqual(self.staff._ea_firm_role(), "read_only")
        self.fa().ea_fa_set_role(self.staff.id, "staff")
        self.assertEqual(self.staff._ea_firm_role(), "staff")
        self.assertTrue(self.staff.has_group("base.group_user"))

    def test_deactivate_and_reactivate(self):
        self.fa().ea_fa_set_active(self.outsider.id, False)
        self.assertFalse(self.outsider.active)
        self.fa().ea_fa_set_active(self.outsider.id, True)
        self.assertTrue(self.outsider.active)
        self.assertEqual(self.Log.search_count([("kind", "in", ["user_deactivated", "user_reactivated"]), ("target_id", "=", self.outsider.id)]), 2)

    def test_the_firm_keeps_an_administrator_and_nobody_locks_themselves_out(self):
        self.assertCode("fa-self", self.fa().ea_fa_set_active, self.admin.id, False)
        self.assertCode("fa-self", self.fa().ea_fa_set_role, self.admin.id, "staff")
        other = self.fa().ea_fa_invite("admin2@gov.example.com", "Admin Deux", "firm_admin")["user_id"]
        other = self.env["res.users"].sudo().browse(other)
        self.fa(other).ea_fa_set_role(self.admin.id, "partner")
        self.assertEqual(self.admin._ea_firm_role(), "partner")

    def test_an_engagement_partner_keeps_their_seat_until_they_transfer_it(self):
        self.assertCode("fa-holds-partner-seat", self.fa().ea_fa_set_active, self.partner.id, False)
        self.assertCode("fa-holds-partner-seat", self.fa().ea_fa_set_role, self.partner.id, "staff")

    def test_a_new_link_only_before_the_first_login(self):
        result = self.fa().ea_fa_invite("lien@gov.example.com", "Lien", "staff")
        self.assertIn("token=", self.fa().ea_fa_link(result["user_id"])["link"])
        user = self.env["res.users"].sudo().browse(result["user_id"])
        user.with_user(user)._update_last_login()
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertCode("fa-already-joined", self.fa().ea_fa_link, user.id)

    def test_the_screen_shows_no_secret(self):
        data = self.fa().ea_fa_users()
        self.assertTrue(data["users"])
        self.assertFalse({"password", "token", "signup_token", "api_key"} & set(data["users"][0]))


@tagged("post_install", "-at_install")
class TestEscalation(FirmAdminCase):
    def setUp(self):
        super().setUp()
        self.technical = self.env.ref("base.user_admin")

    def test_only_a_firm_admin_uses_these_methods(self):
        for user in (self.partner, self.manager, self.staff, self.reader):
            fa = self.fa(user)
            self.assertCode("fa-forbidden", fa.ea_fa_users)
            self.assertCode("fa-forbidden", fa.ea_fa_invite, "a@gov.example.com", "A", "staff")
            self.assertCode("fa-forbidden", fa.ea_fa_set_role, self.staff.id, "firm_admin")
            self.assertCode("fa-forbidden", fa.ea_fa_set_active, self.staff.id, False)
            self.assertCode("fa-forbidden", fa.ea_fa_set_domains, "example.com")
            self.assertCode("fa-forbidden", fa.ea_fm_get)
            self.assertCode("fa-forbidden", fa.ea_fm_save, MAIL)
            self.assertCode("fa-forbidden", fa.ea_fm_test)
            self.assertCode("fa-forbidden", fa.ea_fm_enable)
            self.assertCode("fa-forbidden", fa.ea_fa_project_add, "Non")

    def test_firm_admin_is_not_a_system_administrator(self):
        self.assertFalse(self.admin.has_group("base.group_system"))
        self.assertFalse(self.admin.has_group("base.group_erp_manager"))

    def test_no_role_grants_a_technical_group(self):
        self.assertCode("fa-role-invalid", self.fa().ea_fa_set_role, self.staff.id, "base.group_system")
        self.assertCode("fa-role-invalid", self.fa().ea_fa_invite, "s@gov.example.com", "S", "system")
        self.fa().ea_fa_set_role(self.staff.id, "firm_admin")
        self.assertFalse(self.staff.has_group("base.group_system"))
        self.assertFalse(self.staff.has_group("base.group_erp_manager"))

    def test_direct_writes_on_users_and_groups_are_refused(self):
        system = self.env.ref("base.group_system")
        users = self.env["res.users"].with_user(self.admin)
        with self.assertRaises(AccessError):
            self.staff.with_user(self.admin).write({"group_ids": [(4, system.id)]})
        with self.assertRaises(AccessError):
            self.admin.with_user(self.admin).write({"group_ids": [(4, system.id)]})
        with self.assertRaises(AccessError):
            users.create({"name": "X", "login": "x@gov.example.com", "group_ids": [(4, system.id)]})
        with self.assertRaises(AccessError):
            system.with_user(self.admin).write({"user_ids": [(4, self.admin.id)]})
        firm_admin_group = self.env.ref("ea_audit_core.group_firm_admin")
        with self.assertRaises(AccessError):
            firm_admin_group.with_user(self.admin).write({"implied_ids": [(4, system.id)]})

    def test_rules_and_access_rights_are_out_of_reach(self):
        rule = self.env.ref("ea_audit_core.rule_engagement_team_only").with_user(self.admin)
        with self.assertRaises(AccessError):
            rule.write({"domain_force": "[(1, '=', 1)]"})
        with self.assertRaises(AccessError):
            rule.write({"active": False})
        with self.assertRaises(AccessError):
            rule.unlink()
        with self.assertRaises(AccessError):
            self.env["ir.rule"].with_user(self.admin).create({
                "name": "x", "model_id": self.env.ref("ea_audit_core.model_ea_audit_engagement").id, "domain_force": "[]",
            })
        with self.assertRaises(AccessError):
            self.env["ir.model.access"].with_user(self.admin).create({
                "name": "x", "model_id": self.env.ref("base.model_res_users").id, "perm_write": True,
            })

    def test_system_parameters_and_mail_servers_are_out_of_reach(self):
        with self.assertRaises(AccessError):
            self.env["ir.config_parameter"].with_user(self.admin).set_param("ea_audit.staging_band", "0")
        with self.assertRaises(AccessError):
            self.env["ir.mail_server"].with_user(self.admin).create({"name": "x", "smtp_host": "smtp.example.com"})
        with self.assertRaises(AccessError):
            self.env["ir.mail_server"].with_user(self.admin).search([])

    def test_the_technical_account_cannot_be_touched_from_the_screen(self):
        self.assertCode("fa-technical-target", self.fa().ea_fa_set_role, self.technical.id, "staff")
        self.assertCode("fa-technical-target", self.fa().ea_fa_set_active, self.technical.id, False)
        self.assertCode("fa-technical-target", self.fa().ea_fa_link, self.technical.id)

    def test_superuser_and_outside_users_are_not_targets(self):
        root = self.env.ref("base.user_root")
        self.assertCode("fa-forbidden", self.fa().ea_fa_set_role, root.id, "staff")
        portal = self.env["res.users"].sudo().with_context(no_reset_password=True).create({
            "name": "Portail", "login": "portail@ailleurs.example.org",
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        self.assertCode("fa-forbidden", self.fa().ea_fa_set_role, portal.id, "firm_admin")

    def test_firm_admin_does_not_read_files_they_are_not_on_after_any_of_this(self):
        self.fa().ea_fa_set_role(self.staff.id, "manager")
        Engagement = self.env["ea.audit.engagement"].with_user(self.admin)
        self.assertFalse(Engagement.search([("id", "=", self.engagement.id)]))
        with self.assertRaises(AccessError):
            self.engagement.with_user(self.admin).read(["name"])
        for item in self.engagement.sudo().file_item_ids[:1]:
            with self.assertRaises(AccessError):
                item.with_user(self.admin).read(["code"])

    def test_the_firm_log_is_append_only(self):
        self.fa().ea_fa_set_domains("gov.example.com")
        row = self.env["ea.audit.firm.log"].with_user(self.admin).search([], limit=1)
        self.assertTrue(row)
        self.assertCode("fa-forbidden", row.write, {"detail": "effacé"})
        self.assertCode("fa-forbidden", row.unlink)
        self.assertCode("fa-forbidden", row.sudo().unlink)
        self.assertCode("fa-forbidden", self.env["ea.audit.firm.log"].with_user(self.admin).create, {
            "kind": "user_invited", "actor_id": self.admin.id, "actor_name": "x",
        })
        with self.assertRaises(AccessError):
            self.env["ea.audit.firm.log"].with_user(self.staff).search([])

    def test_use_of_the_technical_account_is_recorded(self):
        before = self.Log.search_count([("kind", "=", "support_login")])
        self.technical.with_user(self.technical)._update_last_login()
        self.assertEqual(self.Log.search_count([("kind", "=", "support_login")]), before + 1)
        row = self.Log.search([("kind", "=", "support_login")], limit=1)
        self.assertEqual(row.actor_id, self.technical)
        self.assertTrue(any(r["support"] for r in self.fa().ea_fa_users()["log"]))

    def test_an_ordinary_login_is_not_support(self):
        before = self.Log.search_count([("kind", "=", "support_login")])
        self.staff.with_user(self.staff)._update_last_login()
        self.assertEqual(self.Log.search_count([("kind", "=", "support_login")]), before)


@tagged("post_install", "-at_install")
class TestMail(FirmAdminCase):
    def probe_ok(self):
        return patch.object(type(self.env["ea.audit.firm.admin"]), "_ea_fm_probe", lambda _self, _server: None)

    def probe_fails(self):
        def refuse(_self, _server):
            raise UserError("Connexion refusée")
        return patch.object(type(self.env["ea.audit.firm.admin"]), "_ea_fm_probe", refuse)

    def server(self):
        return self.env.company.sudo().ea_mail_server_id.with_context(active_test=False)

    def test_a_saved_server_stays_off(self):
        state = self.fa().ea_fm_save(MAIL)
        self.assertEqual(state["state"], "untested")
        self.assertFalse(self.server().active)

    def test_it_cannot_be_enabled_before_a_test_passes(self):
        self.assertCode("fm-none", self.fa().ea_fm_enable)
        self.fa().ea_fm_save(MAIL)
        self.assertCode("fm-untested", self.fa().ea_fm_enable)
        with self.probe_fails():
            result = self.fa().ea_fm_test()
        self.assertFalse(result["ok"])
        self.assertCode("fm-untested", self.fa().ea_fm_enable)
        self.assertFalse(self.server().active)
        with self.probe_ok():
            self.assertTrue(self.fa().ea_fm_test()["ok"])
        self.assertEqual(self.fa().ea_fm_enable()["state"], "on")
        self.assertTrue(self.server().active)

    def test_any_change_turns_it_off_again(self):
        self.fa().ea_fm_save(MAIL)
        with self.probe_ok():
            self.fa().ea_fm_test()
        self.fa().ea_fm_enable()
        state = self.fa().ea_fm_save({**MAIL, "host": "smtp2.example.com"})
        self.assertEqual(state["state"], "untested")
        self.assertFalse(self.server().active)
        self.assertCode("fm-untested", self.fa().ea_fm_enable)

    def test_a_failed_test_turns_it_off(self):
        self.fa().ea_fm_save(MAIL)
        with self.probe_ok():
            self.fa().ea_fm_test()
        self.fa().ea_fm_enable()
        with self.probe_fails():
            self.fa().ea_fm_test()
        self.assertFalse(self.server().active)

    def test_off_on_staging_by_policy(self):
        self.fa().ea_fm_save(MAIL)
        with self.probe_ok():
            self.fa().ea_fm_test()
        self.env["ir.config_parameter"].sudo().set_param("ea_audit.staging_band", "1")
        self.assertTrue(self.fa().ea_fm_get()["staging"])
        self.assertCode("fm-staging-policy", self.fa().ea_fm_test)
        self.assertCode("fm-staging-policy", self.fa().ea_fm_enable)
        self.assertFalse(self.server().active)

    def test_the_password_never_comes_back(self):
        self.fa().ea_fm_save(MAIL)
        state = self.fa().ea_fm_get()
        self.assertTrue(state["has_password"])
        self.assertNotIn(MAIL["password"], str(state))
        self.assertEqual(self.server().smtp_pass, MAIL["password"])
        # saving without one keeps it
        self.fa().ea_fm_save({**MAIL, "password": ""})
        self.assertEqual(self.server().smtp_pass, MAIL["password"])
        log = self.Log.search([("kind", "=", "mail_saved")])
        self.assertNotIn(MAIL["password"], " ".join(log.mapped("detail")))

    def test_bad_servers_are_refused(self):
        for host in ("", "localhost", "127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "::1"):
            self.assertCode("fm-host", self.fa().ea_fm_save, {**MAIL, "host": host})
        self.assertCode("fm-port", self.fa().ea_fm_save, {**MAIL, "port": 22})
        self.assertCode("fm-port", self.fa().ea_fm_save, {**MAIL, "port": "abc"})
        self.assertCode("fm-encryption", self.fa().ea_fm_save, {**MAIL, "encryption": "rot13"})
        self.assertCode("fm-plaintext-password", self.fa().ea_fm_save, {**MAIL, "encryption": "none"})

    def test_a_name_that_resolves_to_a_private_address_is_refused_at_test_time(self):
        self.fa().ea_fm_save(MAIL)
        answer = [(2, 1, 6, "", ("10.1.2.3", 587))]
        with patch("socket.getaddrinfo", lambda *_a, **_k: answer):
            self.assertFalse(self.fa().ea_fm_test()["ok"])
        self.assertCode("fm-untested", self.fa().ea_fm_enable)

    def test_internal_projects(self):
        project_id = self.fa().ea_fa_project_add("Leave test")
        project = self.Project.browse(project_id)
        self.assertTrue(project.ea_is_internal)
        self.assertEqual(self.charge(self.staff, project=project).project_id, project)
        self.fa().ea_fa_project_active(project_id, False)
        self.assertCode("ts-project-not-chargeable", self.charge, self.staff, project=project)
        self.assertCode("ts-project-not-chargeable", self.fa().ea_fa_project_active, self.project.id, False)
        self.assertCode("fa-project-name", self.fa().ea_fa_project_add, "   ")
