"""Changing or adding a firm's administrator from the console (owner's request of 2026-11-18).

The firm's server is never reached: the request goes in the signed answer to its next heartbeat, and its
answer comes back as a reference, one word and, for a new account, a one-time link. The console shows that
link once, then forgets it; it is in no log.
"""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import PlatformCase

LINK = "https://cabinet-a.auditisa.com/web/signup?db=cabinet_a&token=Zx9-_" + "k" * 60


@tagged("post_install", "-at_install")
class TestFirmAdminChange(PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")

    def _ask(self, firm, action="add", name="Paul Mbida", email="paul@exemple.cm", user=None):
        """As the real console does for a real firm: no simulated answer."""
        with patch.object(type(self.env["platform.firm"]), "_admin_change_simulate_answer", lambda _self: None):
            wizard = self.env["platform.firm.admin.change.wizard"].with_user(user or self.operator).create({
                "firm_id": firm.id, "change_action": action, "name": name, "email": email,
            })
            wizard.action_confirm()

    def test_the_request_is_queued_for_the_next_heartbeat(self):
        firm = self._active_firm()
        self._ask(firm, "replace")
        self.assertEqual(firm.admin_change_state, "waiting")
        self.assertEqual(firm.admin_change_by, self.operator)
        self.assertIn("Waiting for the firm's next check-in", firm.admin_change_message)
        answer = firm.sudo()._heartbeat_answer()
        self.assertEqual(answer["admin_request"], {
            "ref": firm.admin_change_ref, "action": "replace", "name": "Paul Mbida", "email": "paul@exemple.cm",
        })
        self.assertTrue(firm.admin_change_delivered_at)
        self.assertIn("admin_request", firm.sudo()._heartbeat_answer(), "sent again until the firm answers")
        self.assertIn("Firm administrator: change asked", firm.log_ids.mapped("action_text"))

    def test_the_answer_closes_the_request_and_the_link_shows_once(self):
        firm = self._active_firm()
        self._ask(firm)
        firm.sudo()._heartbeat_answer()
        firm._simulate_heartbeat(admin_request_ref=firm.admin_change_ref, admin_request_result="done",
                                 admin_request_link=LINK)
        self.assertEqual(firm.admin_change_state, "done")
        self.assertIn("Done: Paul Mbida is now the firm administrator.", firm.admin_change_message)
        self.assertIn("Paul Mbida", firm.with_context(lang="fr_FR").admin_change_message)
        self.assertNotIn("admin_request", firm.sudo()._heartbeat_answer())
        self.assertTrue(firm.admin_link_ready)
        wizard = self.env["platform.firm.admin.link"].with_user(self.operator).create({"firm_id": firm.id})
        wizard.action_reveal()
        self.assertEqual(wizard.link, LINK)
        self.assertFalse(firm.sudo().admin_link_token)
        firm.invalidate_recordset()
        self.assertFalse(firm.admin_link_ready)
        wizard.action_close()
        self.assertFalse(wizard.link)
        again = self.env["platform.firm.admin.link"].with_user(self.operator).create({"firm_id": firm.id})
        with self.assertRaisesRegex(UserError, "no longer available"):
            again.action_reveal()
        self.assertIn("Administrator's link shown", firm.log_ids.mapped("action"))
        self.assertFalse(self.env["platform.log"].search_count([("detail", "ilike", "token=Zx9")]))

    def test_an_answer_under_another_reference_changes_nothing(self):
        firm = self._active_firm()
        self._ask(firm)
        firm.sudo()._heartbeat_answer()
        firm._simulate_heartbeat(admin_request_ref="0" * 16, admin_request_result="done")
        self.assertEqual(firm.admin_change_state, "waiting")

    def test_a_refusal_is_said_in_plain_words(self):
        firm = self._active_firm()
        self._ask(firm)
        firm.sudo()._heartbeat_answer()
        firm._simulate_heartbeat(admin_request_ref=firm.admin_change_ref, admin_request_result="domain")
        self.assertEqual(firm.admin_change_state, "domain")
        self.assertIn("allowed email domains", firm.admin_change_message)
        self.assertFalse(firm.admin_link_ready)

    def test_the_address_must_be_in_the_firm_s_domains(self):
        firm = self._active_firm()
        with self.assertRaisesRegex(UserError, "allowed email domains"):
            self._ask(firm, email="paul@ailleurs.cm")
        self.assertEqual(firm.admin_change_state, "none")
        self.assertNotIn("admin_request", firm.sudo()._heartbeat_answer())

    def test_only_an_operator_may_ask(self):
        firm = self._active_firm()
        with self.assertRaises(AccessError):
            self._ask(firm, user=self.viewer)
        with self.assertRaises(AccessError):
            firm.with_user(self.viewer)._admin_change_request("add", "Paul", "paul@exemple.cm")
        with self.assertRaises(AccessError):
            self.env["platform.firm.admin.link"].with_user(self.viewer).create({"firm_id": firm.id})
        self.assertEqual(firm.admin_change_state, "none")

    def test_a_simulation_firm_answers_at_once(self):
        firm = self._active_firm()
        wizard = self.env["platform.firm.admin.change.wizard"].with_user(self.operator).create({
            "firm_id": firm.id, "change_action": "replace", "name": "Paul Mbida", "email": "paul@exemple.cm",
        })
        wizard.action_confirm()
        self.assertEqual(firm.admin_change_state, "done")
        self.assertIn("Partner role", firm.admin_change_message)
        self.assertTrue(firm.admin_link_ready)

    def test_the_link_is_forgotten_when_it_expires(self):
        firm = self._active_firm()
        self._ask(firm)
        firm.sudo()._heartbeat_answer()
        firm._simulate_heartbeat(admin_request_ref=firm.admin_change_ref, admin_request_result="done",
                                 admin_request_link=LINK)
        firm.sudo().admin_link_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self.env["platform.firm"]._cron_watch()
        self.assertFalse(firm.sudo().admin_link_token)
        firm.invalidate_recordset()
        self.assertFalse(firm.admin_link_ready)

    def test_a_firm_that_is_not_live_cannot_be_asked(self):
        firm = self._active_firm()
        firm.sudo().state = "suspended"
        with self.assertRaisesRegex(UserError, "live firm"):
            self._ask(firm)

    def test_a_change_of_the_contact_is_logged_old_and_new(self):
        firm = self._active_firm()
        firm.with_user(self.operator).write({"contact_name": "Paul Mbida", "contact_email": "paul@exemple.cm",
                                             "legal_name": "Cabinet SARL"})
        row = firm.log_ids.filtered(lambda r: r.action == "Contact details changed")
        self.assertEqual(len(row), 1)
        self.assertEqual(row.user_id, self.operator)
        self.assertIn("Contact's name: Awa Ngono → Paul Mbida", row.detail_text)
        self.assertIn("Contact's email: awa@exemple.cm → paul@exemple.cm", row.detail_text)
        self.assertNotIn("phone", row.detail_text)
        self.assertIn("Nom du contact", row.with_context(lang="fr_FR").detail_text)
        firm.with_user(self.operator).write({"contact_name": "Paul Mbida"})
        self.assertEqual(len(firm.log_ids.filtered(lambda r: r.action == "Contact details changed")), 1,
                         "nothing changed, nothing logged")

    def test_a_viewer_cannot_change_the_contact(self):
        firm = self._active_firm()
        with self.assertRaises(AccessError):
            firm.with_user(self.viewer).write({"contact_phone": "+237 699 999 999"})
