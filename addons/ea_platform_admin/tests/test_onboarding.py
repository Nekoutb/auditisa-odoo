from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from ..services.provider import DryRunDns, DryRunProbe, DryRunProvider, ProviderError
from .common import PlatformCase, ssh_key


@tagged("post_install", "-at_install")
class TestOnboarding(PlatformCase):
    def test_the_wizard_ends_with_an_active_firm_and_a_full_step_log(self):
        firm, job = self._onboard()
        self.assertEqual(firm.state, "active")
        self.assertEqual(job.state, "done")
        self.assertTrue(firm.is_simulation)
        self.assertTrue(job.is_simulation)
        self.assertEqual(firm.platform_host, "cabinet-a.auditisa.com")
        self.assertTrue(firm.server_id.startswith("dry-server"))
        self.assertTrue(firm.server_ip.startswith("203.0.113."))
        self.assertEqual(set(job.step_ids.mapped("state")), {"done"})
        self.assertEqual(job.progress, 100.0)
        self.assertTrue(all(job.step_ids.mapped("finished_at")))
        self.assertEqual(firm.addon_release, self.release.sha)
        self.assertTrue(firm.last_heartbeat_at)

    def test_it_is_all_in_the_log_under_the_operators_name(self):
        firm, _job = self._onboard()
        actions = firm.log_ids.mapped("action")
        self.assertIn("New firm confirmed", actions)
        self.assertIn("Provisioning started", actions)
        self.assertIn("Firm went live", actions)
        confirmed = firm.log_ids.filtered(lambda row: row.action == "New firm confirmed")
        self.assertEqual(confirmed.user_id, self.operator)

    def test_preflight_shows_the_cost_and_needs_confirmation(self):
        wizard = self._wizard()
        wizard.action_next()
        wizard.action_next()
        self.assertEqual(wizard.step, "addons")
        wizard.action_next()
        self.assertEqual(wizard.step, "preflight")
        self.assertEqual(wizard.preview_total_cost, 58.0)
        self.assertIn("SIMULATION", wizard.preview_mode)
        self.assertEqual(wizard.preview_address, "cabinet-a.auditisa.com")
        with self.assertRaisesRegex(UserError, "confirmation"):
            wizard.action_confirm()
        self.assertFalse(self.env["platform.firm"].search_count([("slug", "=", "cabinet-a")]))

    def test_confirming_before_the_preflight_screen_is_refused(self):
        wizard = self._wizard()
        wizard.confirmed = True
        with self.assertRaisesRegex(UserError, "review"):
            wizard.action_confirm()

    def test_changing_anything_needs_a_new_confirmation(self):
        wizard = self._through_steps(self._wizard())
        wizard.action_back()
        self.assertFalse(wizard.confirmed)

    def test_each_screen_checks_its_own_fields(self):
        with self.assertRaisesRegex(UserError, "reserved"):
            self._wizard("www").action_next()
        with self.assertRaisesRegex(UserError, "domain"):
            self._wizard("cabinet-b", allowed_email_domains="").action_next()
        wizard = self._wizard("cabinet-c", ssh_public_key="n'importe quoi")
        wizard.action_next()
        with self.assertRaisesRegex(UserError, "ssh-ed25519"):
            wizard.action_next()

    def test_reserved_names_are_refused(self):
        for slug in ("www", "dev", "test", "status"):
            with self.assertRaisesRegex(UserError, "reserved"):
                self._wizard(slug).action_next()

    def test_a_slug_is_never_given_twice(self):
        self._onboard()
        with self.assertRaisesRegex(UserError, "already"):
            self._wizard("cabinet-a").action_next()

    def test_a_slug_stays_taken_after_archiving(self):
        firm, _job = self._onboard()
        firm.sudo().state = "archived"
        with self.assertRaisesRegex(UserError, "already"):
            self._wizard("cabinet-a").action_next()

    def test_slug_is_normalised(self):
        wizard = self._wizard(" Cabinet-Z ")
        wizard.action_next()
        self.assertEqual(wizard.slug, "cabinet-z")

    def test_a_key_cannot_serve_two_firms(self):
        key = ssh_key(200)
        self._onboard("cabinet-a", ssh_public_key=key)
        wizard = self._wizard("cabinet-b", ssh_public_key=key)
        wizard.action_next()
        with self.assertRaisesRegex(UserError, "another firm"):
            wizard.action_next()

    def test_a_private_key_is_wiped_from_the_form_and_refused(self):
        wizard = self._wizard(ssh_public_key="-----BEGIN OPENSSH PRIVATE KEY-----")
        warning = wizard._onchange_ssh_public_key()
        self.assertIn("PRIVATE", warning["warning"]["message"])
        self.assertFalse(wizard.ssh_public_key)

    def test_no_release_means_no_server(self):
        wizard = self._through_steps(self._wizard())
        wizard.release_id = False
        with self.assertRaisesRegex(UserError, "release"):
            wizard.action_confirm()

    def test_a_viewer_cannot_start_it(self):
        with self.assertRaises(Exception):
            self.env["platform.onboarding.wizard"].with_user(self.viewer).create(self._request())


@tagged("post_install", "-at_install")
class TestProvisioningJob(PlatformCase):
    def test_a_failure_cleans_up_and_is_visible(self):
        provider, _dns, _probe = self._outside_patched(
            provider=DryRunProvider(fail_on={"create_server": ProviderError("Refused by the provider")})
        )
        firm, job = self._onboard()
        self.assertEqual(job.state, "rolled_back")
        self.assertEqual(firm.state, "provisioning")
        step = job.step_ids.filtered(lambda s: s.code == "server")
        self.assertEqual(step.state, "failed")
        self.assertIn("Refused", step.message)
        self.assertFalse(provider.state["servers"])
        self.assertFalse(provider.state["ssh_keys"])
        self.assertFalse(provider.state["firewalls"])
        self.assertFalse(provider.state["storages"])
        self.assertFalse(firm.server_id)
        self.assertEqual(firm.health_color, "red")
        self.assertIn("Provisioning cancelled, full clean-up", firm.log_ids.mapped("action"))
        self.assertFalse(firm.sudo().first_admin_token)

    def test_a_server_that_cannot_be_destroyed_is_flagged_loudly(self):
        provider = DryRunProvider(fail_on={"destroy_server": ProviderError("Destruction refusée")})
        dns = DryRunDns(fail_on={"upsert_a_record": ProviderError("DNS refusé")})
        self._outside_patched(provider=provider, dns=dns)
        firm, job = self._onboard()
        self.assertEqual(job.state, "rollback_failed")
        self.assertTrue(firm.orphan_flag)
        self.assertEqual(firm.health_color, "red")
        self.assertIn("ORPHAN", firm.health_reason)
        self.assertIn(provider.state and list(provider.state["servers"])[0], job.leftovers)
        self.assertTrue(firm.needs_attention)
        self.assertIn("CLEAN-UP FAILED: resources remain", firm.log_ids.mapped("action"))

    def test_the_clean_up_can_be_run_again_once_the_provider_answers(self):
        provider = DryRunProvider(fail_on={"destroy_server": ProviderError("Destruction refusée")})
        dns = DryRunDns(fail_on={"upsert_a_record": ProviderError("DNS refusé")})
        self._outside_patched(provider=provider, dns=dns)
        firm, job = self._onboard()
        provider.fail_on.clear()
        job.action_rollback()
        self.assertEqual(job.state, "rolled_back")
        self.assertFalse(provider.state["servers"])
        self.assertFalse(firm.orphan_flag)

    def test_a_retry_after_clean_up_can_succeed(self):
        provider = DryRunProvider(fail_on={"create_server": ProviderError("Refusé")})
        self._outside_patched(provider=provider)
        firm, job = self._onboard()
        provider.fail_on.clear()
        result = job.action_retry()
        retry = self.env["platform.provision.job"].browse(result["res_id"])
        self.assertEqual(retry.state, "done")
        self.assertEqual(firm.state, "active")
        self.assertEqual(firm.last_job_id, retry)
        self.assertEqual(len(provider.state["servers"]), 1)

    def test_a_waiting_job_is_resumed_by_the_cron_and_creates_nothing_twice(self):
        provider = DryRunProvider(boot_polls=2)
        self._outside_patched(provider=provider)
        firm, job = self._onboard()
        self.assertEqual(job.state, "waiting")
        self.assertEqual(firm.state, "provisioning")
        self.assertEqual(job.step_ids.filtered(lambda s: s.code == "wait_server").state, "running")
        self.env["platform.provision.job"]._cron_run_jobs()
        self.assertEqual(job.state, "done")
        self.assertEqual(firm.state, "active")
        self.assertEqual(len(provider.state["servers"]), 1)

    def test_a_job_can_be_cancelled_while_waiting(self):
        provider = DryRunProvider(boot_polls=9)
        self._outside_patched(provider=provider)
        _firm, job = self._onboard()
        job.action_rollback()
        self.assertEqual(job.state, "rolled_back")
        self.assertFalse(provider.state["servers"])

    def test_a_failed_health_check_goes_on_retrying_then_cleans_up(self):
        provider = DryRunProvider()
        self._outside_patched(provider=provider, probe=DryRunProbe({"/web/health": 502}))
        firm, job = self._onboard()
        step = job.step_ids.filtered(lambda s: s.code == "health_check")
        self.assertEqual(job.state, "waiting")
        self.assertIn("502", step.message)
        self.assertEqual(firm.state, "provisioning")
        step.sudo().write({
            "attempts": 5,
            "started_at": fields.Datetime.now() - timedelta(hours=2),
        })
        job._run()
        self.assertEqual(job.state, "rolled_back")
        self.assertFalse(provider.state["servers"])

    def test_a_done_job_cannot_be_cancelled(self):
        _firm, job = self._onboard()
        with self.assertRaises(UserError):
            job.action_rollback()

    def test_a_server_nobody_claims_is_reported_and_left_alone(self):
        from ..services.provider import ServerSpec
        provider, _dns, _probe = self._outside_patched()
        firm, _job = self._onboard()
        stray = provider.create_server(ServerSpec(
            label="auditisa-firm-inconnu", hostname="x", region="cdg", plan="p", os_id=1, user_data="",
            ssh_key_id="k", firewall_id="f", tags=["auditisa-firm"],
        ))
        orphans = self.env["platform.firm"]._find_orphan_servers()
        self.assertEqual([server.id for server in orphans], [stray.id])
        self.assertIn(stray.id, provider.state["servers"])
        self.assertFalse(firm.orphan_flag)
        self.assertTrue(self.env["platform.log"].search_count([("action", "=", "Orphan server detected"), ("detail", "ilike", stray.id)]))
        self.env["platform.firm"]._find_orphan_servers()
        self.assertEqual(
            self.env["platform.log"].search_count([("action", "=", "Orphan server detected"), ("detail", "ilike", stray.id)]), 1,
        )


@tagged("post_install", "-at_install")
class TestFirstAdminLink(PlatformCase):
    def test_the_link_is_shown_once_and_then_gone(self):
        firm, _job = self._onboard()
        self.assertTrue(firm.first_admin_ready)
        wizard = self.env["platform.first.admin.link"].with_user(self.operator).create({"firm_id": firm.id})
        wizard.action_reveal()
        self.assertIn("https://cabinet-a.auditisa.com/ea-firm/first-admin/", wizard.link)
        self.assertFalse(firm.sudo().first_admin_token)
        firm.invalidate_recordset()
        self.assertFalse(firm.first_admin_ready)
        wizard.action_close()
        self.assertFalse(wizard.link)
        again = self.env["platform.first.admin.link"].with_user(self.operator).create({"firm_id": firm.id})
        with self.assertRaisesRegex(UserError, "no longer available"):
            again.action_reveal()

    def test_who_saw_the_link_is_logged_without_the_link(self):
        firm, _job = self._onboard()
        token = firm.sudo().first_admin_token
        wizard = self.env["platform.first.admin.link"].with_user(self.operator).create({"firm_id": firm.id})
        wizard.action_reveal()
        row = firm.log_ids.filtered(lambda r: r.action == "First administrator's link shown")
        self.assertEqual(row.user_id, self.operator)
        self.assertFalse(self.env["platform.log"].search_count([("detail", "ilike", token)]))

    def test_the_plain_link_expires_with_time(self):
        firm, _job = self._onboard()
        firm.sudo().first_admin_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self.env["platform.firm"]._cron_watch()
        self.assertFalse(firm.sudo().first_admin_token)
        firm.invalidate_recordset()
        self.assertFalse(firm.first_admin_ready)

    def test_no_password_is_ever_generated_or_mailed(self):
        before = self.env["mail.mail"].sudo().search_count([])
        firm, _job = self._onboard()
        self.assertEqual(self.env["mail.mail"].sudo().search_count([("email_to", "ilike", firm.contact_email)]), 0)
        self.assertLessEqual(self.env["mail.mail"].sudo().search_count([]) - before, 0)
        names = self.env["platform.firm"]._fields
        self.assertFalse([name for name in names if "password" in name])

    def test_the_server_gets_only_the_hash_of_the_link(self):
        firm, job = self._onboard()
        token = firm.sudo().first_admin_token
        provider = self.env["platform.services"]._outside()[0]
        text = job._user_data(provider.storage_credentials(firm.storage_id))
        self.assertNotIn(token, text)
