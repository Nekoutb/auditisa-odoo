"""The platform email address support@<slug>.cm-ea.com, from the New firm form to "Sending is on".

Simulation only: MailerSend and Cloudflare are the DryRun classes of services/platform_mail.py, and a test
that needs a fault gives its own. No network, no token, and the SMTP password in no table and no log.
"""

import json
import os
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from ..models.platform_services import PARAM_MAIL_PARENT, PARAM_MAIL_ZONE_ID, PARAM_PRACTICE_ALLOWLIST
from ..services import mail_handoff, platform_mail
from ..services.provider import ProviderError
from .common import PlatformCase


@tagged("post_install", "-at_install")
class TestPlatformMail(PlatformCase):
    def setUp(self):
        super().setUp()
        self.folder = os.path.join(tempfile.mkdtemp(), "firm-mail")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.folder), ignore_errors=True)
        self.params = self.env["ir.config_parameter"].sudo()
        self.params.set_param(mail_handoff.FOLDER_PARAM, self.folder)

    # ------------------------------------------------------------------ helpers

    def _apply_settings(self, **changes):
        values = {"provider": "dry_run", "base_domain": "auditisa.com", "mail_parent_domain": "cm-ea.com",
                  "mail_zone_name": "cm-ea.com", "mail_local_part": "support", "mail_reply_to_policy": "contact",
                  **changes}
        settings = self.env["platform.settings"].with_user(self.owner).create(values)
        settings.action_save()
        return settings

    def _dry(self):
        return self.env["platform.services"]._mail_dry_state()

    def _faulty(self, mailersend=None, zone=None):
        state = self._dry()
        mailersend = mailersend or platform_mail.DryRunMailerSend(state["mailersend"])
        zone = zone or platform_mail.DryRunZone(state["zone"])
        self.patch(type(self.env["platform.services"]), "_mail_outside", lambda _self, zone_id=None: (mailersend, zone))
        return mailersend, zone

    def _platform_firm(self, slug="cabinet-a"):
        self._apply_settings()
        firm, job = self._onboard(slug)
        return firm, job

    # ------------------------------------------------------------------ settings

    def test_the_settings_have_no_field_for_a_token_and_test_the_connection(self):
        settings = self._apply_settings()
        self.assertFalse([name for name in settings._fields if "token" in name or "secret" in name])
        settings.action_mail_test()
        self.assertIn("Simulation", settings.mail_check_result)
        self.assertIn("cm-ea.com", settings.mail_check_result)
        self.assertEqual(self.params.get_param(PARAM_MAIL_ZONE_ID), "zone-simulated")

    def test_the_settings_refuse_a_wrong_value_in_plain_words(self):
        with self.assertRaisesRegex(UserError, "Parent domain"):
            self._apply_settings(mail_parent_domain="not a domain")
        with self.assertRaisesRegex(UserError, "Not an email address"):
            self._apply_settings(practice_mail_allowlist="owner@exemple.cm\nnonsense")

    def test_no_real_service_can_be_built_during_tests(self):
        self.params.set_param("ea_platform.provider", "vultr")
        mailersend, zone = self.env["platform.services"]._mail_outside()
        self.assertTrue(mailersend.is_simulation and zone.is_simulation)

    # ------------------------------------------------------------------ the New firm form

    def test_the_new_firm_form_recommends_the_platform_address_once_set_up(self):
        self.assertEqual(self._wizard("cabinet-b").mail_choice, "none")
        self._apply_settings()
        wizard = self._wizard("cabinet-c")
        self.assertEqual(wizard.mail_choice, "platform")
        self.assertEqual(wizard.preview_platform_address, "support@cabinet-c.cm-ea.com")

    def test_provisioning_sets_up_the_address_and_the_firm_sends(self):
        firm, job = self._platform_firm()
        self.assertEqual(job.state, "done")
        step = job.step_ids.filtered(lambda s: s.code == "platform_mail")
        self.assertEqual(step.state, "done")
        self.assertEqual(firm.mail_choice, "platform")
        self.assertEqual(firm.pmail_sender, "support@cabinet-a.cm-ea.com")
        self.assertEqual(firm.pmail_reply_to, "awa@exemple.cm")
        self.assertTrue(firm.pmail_verified)
        self.assertEqual(firm.pmail_state, "sending")
        self.assertEqual(firm.mail_request_host, "smtp.mailersend.net")
        self.assertEqual(firm.mail_request_port, 587)
        self.assertEqual(firm.mail_request_sender, "support@cabinet-a.cm-ea.com")
        # The firm's server collects the settings, tests them, and says "on".
        firm._simulate_heartbeat()
        firm._simulate_heartbeat()
        self.assertEqual(firm.mail_request_state, "on")
        self.assertEqual(firm.pmail_state, "on")
        self.assertIn("Sending is on, from support@cabinet-a.cm-ea.com", firm.pmail_status)
        self.assertEqual(firm.sudo()._heartbeat_answer()["mail_reply_to"], "awa@exemple.cm")
        records = self._dry()["zone"]["records"].values()
        self.assertEqual(len(records), 4)
        self.assertTrue(all(r["name"].endswith("cabinet-a.cm-ea.com") for r in records))

    def test_the_smtp_password_is_in_no_table(self):
        firm, _job = self._platform_firm()
        self.env.flush_all()
        password = "simulated-" + firm.pmail_user_ref
        for table, column in (("ir_config_parameter", "value"), ("platform_firm", "mail_request_summary"),
                              ("platform_log", "detail"), ("platform_provision_step", "message_raw")):
            self.env.cr.execute(f"SELECT count(*) FROM {table} WHERE {column} LIKE %s", ["%" + password + "%"])
            self.assertEqual(self.env.cr.fetchone()[0], 0, table)

    def test_a_domain_not_verified_yet_does_not_hold_up_the_firm(self):
        self._apply_settings()
        state = self._dry()
        state["mailersend"]["verify_after"] = 3
        self.params.set_param("ea_platform.mail_dry_run_state", json.dumps(state))
        firm, job = self._onboard("cabinet-d")
        self.assertEqual(job.state, "done")
        self.assertEqual(firm.state, "active")
        self.assertEqual(firm.pmail_state, "verifying")
        self.assertTrue(firm.pmail_next_check_at)
        # The console's watch checks again later, with longer waits, and carries on by itself.
        for _check in range(3):
            firm.sudo().pmail_next_check_at = fields.Datetime.now() - timedelta(minutes=1)
            self.env["platform.firm"]._pmail_watch()
            if firm.pmail_state != "verifying":
                break
        self.assertEqual(firm.pmail_state, "on", "a simulation firm on line answers at once")

    def test_a_mailersend_refusal_is_shown_on_the_firm_and_the_firm_still_goes_live(self):
        self._apply_settings()
        self._faulty(mailersend=platform_mail.DryRunMailerSend(fail_on={
            "create_domain": ProviderError(platform_mail._("MailerSend: the account has reached its plan's number of "
                                                           "sending domains. Upgrade the plan, or remove the address of "
                                                           "a firm that left, then check again."))}))
        firm, job = self._onboard("cabinet-e")
        self.assertEqual(job.state, "done")
        self.assertEqual(firm.state, "active")
        self.assertEqual(firm.pmail_state, "problem")
        self.assertIn("plan", firm.pmail_problem)

    def test_a_temporary_fault_is_retried_by_the_step(self):
        self._apply_settings()
        self._faulty(zone=platform_mail.DryRunZone(fail_on={"create": 1}))
        firm, job = self._onboard("cabinet-f")
        self.env["platform.provision.job"]._cron_run_jobs()
        job.invalidate_recordset()
        self.assertEqual(firm.pmail_state, "sending")
        self.assertEqual(job.state, "done")

    def test_the_firms_own_mailbox_is_still_offered(self):
        self._apply_settings()
        wizard = self._wizard("cabinet-g", mail_choice="own", mail_host="smtp.office365.com", mail_port=587,
                              mail_encryption="starttls", mail_user="cabinet@exemple.cm", mail_sender="cabinet@exemple.cm",
                              mail_password="Mot-de-passe-7f3a")
        self._through_steps(wizard)
        job = self.env["platform.provision.job"].browse(wizard.action_confirm()["res_id"])
        firm = job.firm_id
        self.assertEqual(firm.mail_choice, "own")
        self.assertEqual(firm.pmail_state, "none")
        self.assertEqual(firm.mail_request_host, "smtp.office365.com")

    def test_no_email_for_now(self):
        self._apply_settings()
        firm, _job = self._onboard("cabinet-h", mail_choice="none")
        self.assertEqual(firm.pmail_state, "none")
        self.assertEqual(firm.mail_request_state, "none")

    # ------------------------------------------------------------------ an existing firm

    def test_an_existing_firm_gets_an_address_from_its_page(self):
        firm = self._active_firm("cabinet-i")
        with self.assertRaisesRegex(UserError, "not set up"):
            firm.with_user(self.operator).action_pmail_give()
        self._apply_settings()
        firm.with_user(self.operator).action_pmail_give()
        self.assertEqual(firm.pmail_state, "on")
        self.assertEqual(firm.mail_request_sender, "support@cabinet-i.cm-ea.com")

    def test_the_viewer_cannot_give_an_address(self):
        self._apply_settings()
        firm = self._active_firm("cabinet-j")
        with self.assertRaises(Exception):
            firm.with_user(self.viewer).action_pmail_give()

    def test_removing_the_address_removes_everything_and_switches_sending_off(self):
        firm, _job = self._platform_firm("cabinet-k")
        firm._simulate_heartbeat()
        firm._simulate_heartbeat()
        self.assertEqual(firm.pmail_state, "on")
        with patch.object(type(self.env["platform.firm"]), "_mail_simulate_answer", lambda _self: None):
            firm.with_user(self.operator).action_pmail_remove()
        state = self._dry()
        self.assertEqual(state["mailersend"]["domains"], {})
        self.assertEqual(state["zone"]["records"], {})
        self.assertEqual(firm.pmail_state, "none")
        self.assertEqual(firm.mail_choice, "none")
        self.assertEqual(firm.mail_request_action, "off")
        self.assertEqual(firm.sudo()._heartbeat_answer()["mail_reply_to"], "")

    def test_the_undo_used_by_a_rollback_and_by_destroy_removes_the_domain(self):
        firm, _job = self._platform_firm("cabinet-l")
        firm._pmail_undo()
        self.assertEqual(self._dry()["mailersend"]["domains"], {})
        self.assertEqual(firm.pmail_state, "none")

    def test_settings_not_collected_in_time_are_sent_again_with_a_new_password(self):
        firm, _job = self._platform_firm("cabinet-m")
        first_user = firm.pmail_user_ref
        firm.sudo().mail_request_at = fields.Datetime.now() - timedelta(hours=7)
        self.env["platform.firm"]._mail_expire()
        self.assertEqual(firm.pmail_state, "setting_up")
        self.env["platform.firm"]._pmail_watch()
        self.assertNotEqual(firm.pmail_user_ref, first_user)
        self.assertIn(firm.pmail_state, ("sending", "on"))

    # ------------------------------------------------------------------ the test email

    def test_the_test_email_and_the_practice_list(self):
        firm, _job = self._platform_firm("cabinet-n")
        wizard = self.env["platform.mail.test.wizard"].with_user(self.operator).create(
            {"firm_id": firm.id, "address": "owner@exemple.cm"})
        wizard.action_send()
        self.assertIn("MailerSend accepted", wizard.result)
        self.assertEqual(self._dry()["mailersend"]["sent"], 1)
        practice = self.env["platform.mail.test.wizard"].with_user(self.operator).create(
            {"firm_id": firm.id, "address": "owner@exemple.cm", "practice": True})
        with self.assertRaisesRegex(UserError, "not on the list"):
            practice.action_send()
        self.params.set_param(PARAM_PRACTICE_ALLOWLIST, "owner@exemple.cm")
        practice.action_send()
        self.assertIn("MailerSend accepted", practice.result)
        log = firm.log_ids.filtered(lambda r: r.action == "Test email")
        self.assertTrue(log)
        self.assertNotIn("owner@", " ".join(log.mapped("detail")))

    def test_the_practice_computer_is_told_the_list(self):
        computer = self.env["platform.practice.computer"]._enrol("practice-1", token_path=None, simulation=True)
        self.assertEqual(computer._answer()["mail_allowlist"], [])
        self.params.set_param(PARAM_PRACTICE_ALLOWLIST, "Owner@exemple.cm")
        self.assertEqual(computer._answer()["mail_allowlist"], ["owner@exemple.cm"])

    def test_the_address_follows_the_parent_domain_setting(self):
        self._apply_settings(mail_parent_domain="mail.cm-ea.com", mail_local_part="contact")
        self.assertEqual(self.params.get_param(PARAM_MAIL_PARENT), "mail.cm-ea.com")
        firm, _job = self._onboard("cabinet-o")
        self.assertEqual(firm.pmail_sender, "contact@cabinet-o.mail.cm-ea.com")
