"""The firm administrator changed from the AuditISA console (owner, 2026-11-18): "add" gives the role,
"replace" also takes it from the previous administrators, who keep their account, their engagement seats
and their work. Each step is in the firm's administration log, as done by the platform."""
from odoo.tests import tagged

from .common import TimesheetCase


@tagged("post_install", "-at_install")
class TestPlatformAdminChange(TimesheetCase):
    def apply(self, action, email, name="Paul Mbida"):
        return self.FirmAdmin.sudo()._ea_fa_from_platform(action, name, email)

    def user(self, email):
        return self.env["res.users"].sudo().with_context(active_test=False).search([("login", "=", email)])

    def test_add_makes_an_account_with_the_role_and_a_one_time_link(self):
        result, link = self.apply("add", "paul@gov.example.com")
        self.assertEqual(result, "done")
        user = self.user("paul@gov.example.com")
        self.assertEqual(user.name, "Paul Mbida")
        self.assertEqual(user._ea_firm_role(), "firm_admin")
        self.assertIn("/web/signup", link)
        self.assertIn("token=", link)
        self.env.cr.execute("SELECT password FROM res_users WHERE id = %s", [user.id])
        self.assertFalse(self.env.cr.fetchone()[0])
        self.assertEqual(self.admin._ea_firm_role(), "firm_admin", "add keeps the other administrators")
        row = self.Log.search([("kind", "=", "platform_admin_added"), ("target_id", "=", user.id)])
        self.assertEqual(len(row), 1)
        self.assertEqual(row.actor_name, "AuditISA platform")
        self.assertNotIn("token", row.detail or "")

    def test_replace_takes_the_role_and_keeps_the_account_and_the_work(self):
        seat = self.seat(self.engagement, self.admin, "manager")
        result, _link = self.apply("replace", "paul@gov.example.com")
        self.assertEqual(result, "done")
        self.assertEqual(self.user("paul@gov.example.com")._ea_firm_role(), "firm_admin")
        self.admin.invalidate_recordset()
        self.assertTrue(self.admin.active)
        self.assertEqual(self.admin._ea_firm_role(), "partner")
        self.assertTrue(seat.exists())
        self.assertEqual(seat.user_id, self.admin)
        self.assertTrue(self.Log.search_count([("kind", "=", "platform_admin_removed"), ("target_id", "=", self.admin.id)]))

    def test_an_existing_user_is_reused(self):
        before = self.env["res.users"].sudo().with_context(active_test=False).search_count([])
        result, _link = self.apply("replace", self.manager.login.upper())
        self.assertEqual(result, "done")
        self.assertEqual(self.env["res.users"].sudo().with_context(active_test=False).search_count([]), before)
        self.assertEqual(self.manager._ea_firm_role(), "firm_admin")
        self.assertEqual(self.admin._ea_firm_role(), "partner")
        row = self.Log.search([("kind", "=", "platform_admin_added"), ("target_id", "=", self.manager.id)])
        self.assertIn(">", row.detail)

    def test_the_allowed_domains_are_enforced(self):
        self.env.company.sudo().ea_allowed_email_domains = "gov.example.com"
        self.assertEqual(self.apply("add", "paul@ailleurs.example.org"), ("domain", None))
        self.assertFalse(self.user("paul@ailleurs.example.org"))
        self.assertEqual(self.apply("add", "pas-une-adresse"), ("email", None))

    def test_a_client_s_portal_account_is_refused(self):
        portal = self.env["res.users"].sudo().with_context(no_reset_password=True).create({
            "name": "Client", "login": "client@gov.example.com", "email": "client@gov.example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        self.assertEqual(self.apply("replace", portal.login), ("account", None))
        self.assertEqual(self.admin._ea_firm_role(), "firm_admin", "nothing changed")

    def test_only_the_platform_s_own_call_may_do_it(self):
        self.assertCode("fa-forbidden", self.FirmAdmin.with_user(self.admin)._ea_fa_from_platform,
                        "add", "X", "x@gov.example.com")
