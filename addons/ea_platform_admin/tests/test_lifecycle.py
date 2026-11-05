from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..services.provider import DryRunProvider, ProviderError
from .common import PlatformCase


@tagged("post_install", "-at_install")
class TestSuspend(PlatformCase):
    def _suspend(self, firm, user=None):
        wizard = self.env["platform.suspend.wizard"].with_user(user or self.operator).create(
            {"firm_id": firm.id, "reason": "Impayé"})
        wizard.action_confirm()

    def test_suspend_stops_the_server_and_resume_starts_it(self):
        firm = self._active_firm()
        provider = self.env["platform.services"]._outside()[0]
        self._suspend(firm)
        provider = self.env["platform.services"]._outside()[0]
        self.assertEqual(firm.state, "suspended")
        self.assertEqual(provider.get_server(firm.server_id).status, "stopped")
        self.assertEqual(firm.health_color, "grey")
        firm.with_user(self.operator).action_resume()
        provider = self.env["platform.services"]._outside()[0]
        self.assertEqual(firm.state, "active")
        self.assertEqual(provider.get_server(firm.server_id).status, "active")
        actions = firm.log_ids.mapped("action")
        self.assertIn("Firm suspended", actions)
        self.assertIn("Firm resumed", actions)

    def test_a_viewer_cannot_suspend(self):
        firm = self._active_firm()
        with self.assertRaises(AccessError):
            self._suspend(firm, user=self.viewer)

    def test_a_provider_failure_changes_nothing(self):
        firm = self._active_firm()
        self._outside_patched(provider=DryRunProvider(fail_on={"stop_server": ProviderError("Refused")}))
        with self.assertRaisesRegex(UserError, "Refused"):
            self._suspend(firm)
        self.assertEqual(firm.state, "active")


@tagged("post_install", "-at_install")
class TestBreakglass(PlatformCase):
    def _open(self, firm):
        self.env["platform.breakglass.wizard"].with_user(self.operator).create(
            {"firm_id": firm.id, "reason": "Disque plein", "firm_informed": True}).action_confirm()

    def test_it_is_logged_per_firm_and_cannot_be_changed(self):
        firm = self._active_firm()
        self._open(firm)
        row = firm.breakglass_ids
        self.assertEqual(row.user_id, self.operator)
        self.assertEqual(row.reason, "Disque plein")
        self.assertIn("Break-glass access opened", firm.log_ids.mapped("action"))
        with self.assertRaises(AccessError):
            row.sudo().write({"reason": "autre"})
        with self.assertRaises(AccessError):
            row.sudo().unlink()

    def test_an_ssh_login_without_an_entry_turns_the_firm_orange(self):
        firm = self._active_firm()
        firm._simulate_heartbeat(ssh_sessions_24h=1)
        self.assertEqual(firm.health_color, "amber")
        self.assertIn("no entry in the break-glass log", firm.health_reason)
        self._open(firm)
        firm._simulate_heartbeat(ssh_sessions_24h=1)
        self.assertEqual(firm.health_color, "green")

    def test_one_firms_log_does_not_cover_anothers(self):
        a, b = self._active_firm("cabinet-a"), self._active_firm("cabinet-b")
        self._open(a)
        b._simulate_heartbeat(ssh_sessions_24h=1)
        self.assertEqual(b.health_color, "amber")

    def test_the_command_names_this_firms_key_only(self):
        firm = self._active_firm()
        wizard = self.env["platform.breakglass.wizard"].with_user(self.operator).create(
            {"firm_id": firm.id, "reason": "x"})
        self.assertIn("auditisa-cabinet-a", wizard.command)
        self.assertIn("root@cabinet-a.auditisa.com", wizard.command)


@tagged("post_install", "-at_install")
class TestHealthAlerts(PlatformCase):
    def test_a_missed_backup_turns_red_and_alerts(self):
        firm = self._active_firm()
        self.assertEqual(firm.health_color, "green")
        firm.sudo().write({"last_backup_at": fields.Datetime.now() - timedelta(days=3)})
        firm._evaluate_health()
        self.assertEqual(firm.health_color, "red")
        self.assertIn("Backup missed", firm.health_reason)
        self.assertTrue(firm.needs_attention)
        self.assertIn("Alert", firm.log_ids.mapped("action"))
        self.assertTrue(firm.message_ids.filtered(lambda m: "Backup missed" in (m.body or "")))

    def test_a_missed_restore_test_turns_red(self):
        firm = self._active_firm()
        firm.sudo().write({"last_restore_test_at": fields.Datetime.now() - timedelta(days=20)})
        firm._evaluate_health()
        self.assertIn("Restore test missed", firm.health_reason)

    def test_a_silent_server_is_caught_by_the_cron(self):
        firm = self._active_firm()
        firm.sudo().write({"last_heartbeat_at": fields.Datetime.now() - timedelta(hours=5)})
        self.env["platform.firm"]._cron_watch()
        self.assertEqual(firm.health_color, "red")
        self.assertIn("No heartbeat", firm.health_reason)

    def test_an_alert_is_raised_once_per_turn_to_red(self):
        firm = self._active_firm()
        firm.sudo().write({"last_backup_at": fields.Datetime.now() - timedelta(days=3)})
        firm._evaluate_health()
        firm._evaluate_health()
        self.assertEqual(len(firm.log_ids.filtered(lambda row: row.action == "Alert")), 1)

    def test_the_attention_filter_finds_it(self):
        good = self._active_firm("cabinet-a")
        bad = self._active_firm("cabinet-b")
        bad.sudo().write({"last_backup_ok": False})
        bad._evaluate_health()
        found = self.env["platform.firm"].search([("needs_attention", "=", True)])
        self.assertIn(bad, found)
        self.assertNotIn(good, found)

    def test_the_key_escrow_reminder_clears_when_declared(self):
        firm, _job = self._onboard()
        self.assertEqual(firm.health_color, "amber")
        self.assertIn("safe", firm.health_reason)
        firm.action_confirm_key_escrow()
        self.assertEqual(firm.health_color, "green")
        self.assertEqual(firm.backup_key_escrowed_by, self.env.user)


@tagged("post_install", "-at_install")
class TestOffboarding(PlatformCase):
    def setUp(self):
        super().setUp()
        self.firm = self._active_firm()

    def _start(self, typed=None, days=90, user=None):
        wizard = self.env["platform.offboard.wizard"].with_user(user or self.owner).create({
            "firm_id": self.firm.id, "typed_slug": typed or self.firm.slug, "retention_days": days, "reason": "Fin de contrat",
        })
        wizard.action_confirm()

    def _ready_for_destruction(self):
        self._start()
        self.firm.action_simulate_export()
        self.firm.with_user(self.owner).action_confirm_export_received()
        self.firm.sudo().write({"export_at": fields.Datetime.now() - timedelta(days=91)})
        self.env.invalidate_all()

    def _destroyer(self, user=None):
        return self.env["platform.destroy.wizard"].with_user(user or self.owner).create({"firm_id": self.firm.id})

    def _destroy(self):
        wizard = self._destroyer()
        wizard.typed_slug = self.firm.slug
        wizard.action_next()
        wizard.typed_word = "DESTROY"
        return wizard.action_destroy()

    def test_a_mistyped_slug_does_nothing(self):
        with self.assertRaisesRegex(UserError, "does not match"):
            self._start(typed="cabinet-b")
        self.assertEqual(self.firm.state, "active")

    def test_retention_has_a_minimum(self):
        with self.assertRaisesRegex(UserError, "at least 30"):
            self._start(days=5)

    def test_only_the_owner_can_start_it(self):
        with self.assertRaises(AccessError):
            self._start(user=self.operator)

    def test_starting_destroys_nothing_and_asks_for_the_export(self):
        self._start()
        self.assertEqual(self.firm.state, "offboarding")
        self.assertTrue(self.firm.server_id)
        self.assertTrue(self.firm._heartbeat_answer()["export_requested"])
        self.assertTrue(self.env["platform.services"]._outside()[0].get_server(self.firm.server_id))

    def test_destruction_waits_for_the_export(self):
        self._start()
        wizard = self._destroyer()
        wizard.typed_slug = self.firm.slug
        with self.assertRaisesRegex(UserError, "export"):
            wizard.action_next()

    def test_destruction_waits_for_the_export_to_be_handed_over(self):
        self._start()
        self.firm.action_simulate_export()
        wizard = self._destroyer()
        wizard.typed_slug = self.firm.slug
        with self.assertRaisesRegex(UserError, "Handing"):
            wizard.action_next()

    def test_destruction_waits_for_the_retention_period(self):
        self._start()
        self.firm.action_simulate_export()
        self.firm.with_user(self.owner).action_confirm_export_received()
        self.assertFalse(self.firm.can_destroy)
        wizard = self._destroyer()
        wizard.typed_slug = self.firm.slug
        with self.assertRaisesRegex(UserError, "retention"):
            wizard.action_next()

    def test_both_confirmations_are_needed(self):
        self._ready_for_destruction()
        self.assertTrue(self.firm.can_destroy)
        wizard = self._destroyer()
        wizard.typed_slug = "autre-chose"
        with self.assertRaisesRegex(UserError, "does not match"):
            wizard.action_next()
        wizard.typed_slug = self.firm.slug
        with self.assertRaisesRegex(UserError, "slug confirmation"):
            wizard.action_destroy()
        wizard.action_next()
        wizard.typed_word = "destroy"
        with self.assertRaisesRegex(UserError, "DESTROY"):
            wizard.action_destroy()
        self.assertEqual(self.firm.state, "offboarding")

    def test_the_operator_cannot_destroy(self):
        self._ready_for_destruction()
        with self.assertRaises(AccessError):
            self._destroyer(user=self.operator)

    def test_destruction_removes_everything_and_keeps_the_record(self):
        server_id = self.firm.server_id
        self._ready_for_destruction()
        self._destroy()
        provider, dns, _probe = self.env["platform.services"]._outside()
        self.assertEqual(self.firm.state, "archived")
        self.assertIsNone(provider.get_server(server_id))
        self.assertIsNone(dns.find_record(self.firm.platform_host))
        self.assertFalse(provider.state["ssh_keys"])
        self.assertFalse(provider.state["firewalls"])
        self.assertFalse(provider.state["storages"])
        self.assertFalse(self.firm.sudo().heartbeat_token)
        self.assertFalse(self.firm.server_id)
        self.assertIn("Server destroyed, firm archived", self.firm.log_ids.mapped("action"))
        self.assertEqual(self.firm.health_color, "grey")

    def test_an_incomplete_destruction_is_flagged_and_keeps_the_firm_open(self):
        self._ready_for_destruction()
        provider = DryRunProvider(
            self.env["platform.services"]._dry_state()["provider"],
            fail_on={"destroy_server": ProviderError("Refused")},
        )
        self._outside_patched(provider=provider)
        result = self._destroy()
        self.assertEqual(result["params"]["type"], "danger")
        self.assertEqual(self.firm.state, "offboarding")
        self.assertTrue(self.firm.orphan_flag)
        self.assertTrue(self.firm.server_id)
        self.assertEqual(self.firm.health_color, "red")

    def test_a_firm_cannot_be_deleted(self):
        with self.assertRaisesRegex(UserError, "cannot be deleted"):
            self.firm.sudo().unlink()
