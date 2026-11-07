"""Practice spaces, from the control room: created with the firm, same add-ons, reset, first login
shown once, figures-only heartbeat, and the release order (practice computer first)."""

import hashlib
import json
import time
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..services import practice
from ..services.heartbeat import HeartbeatRejected
from .common import PlatformCase
from .test_addons import SAMPLE, catalogue_bytes


@tagged("post_install", "-at_install")
class TestPracticeSpaces(PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Computer = cls.env["platform.practice.computer"]
        cls.release.with_user(cls.owner)._load_catalogue(catalogue_bytes(cls.release.sha))
        cls.addon = cls.env["platform.addon"].sudo().search([("code", "=", SAMPLE)])

    def _computer(self):
        return self.Computer._enrol(
            "practice-1", entry_url="https://test.auditisa.com:8443/practice/%s",
            first_login_url="https://test.auditisa.com:8443/practice/%s/first-admin/%t",
            token_path=None, simulation=True,
        )

    def _signed(self, computer, figures, timestamp=None):
        body = json.dumps(figures, sort_keys=True, separators=(",", ":")).encode()
        timestamp = timestamp or max(int(time.time()), (computer.last_heartbeat_timestamp or 0) + 1)
        token = computer.sudo().heartbeat_token
        return {
            practice.HEADER_COMPUTER: computer.name, practice.HEADER_TIMESTAMP: str(timestamp),
            practice.HEADER_SIGNATURE: practice.sign(token, computer.name, timestamp, body),
        }, body

    # ------------------------------------------------------------------ creation

    def test_a_new_firm_gets_its_practice_space_by_default(self):
        computer = self._computer()
        firm, _job = self._onboard("cabinet-a")
        space = firm.practice_space_id
        self.assertTrue(space)
        self.assertEqual(space.computer_id, computer)
        self.assertEqual(space.state, "requested")
        self.assertEqual(space.admin_login, "awa@exemple.cm")
        self.assertEqual(space.address, "https://test.auditisa.com:8443/practice/cabinet-a")
        self.assertIn("Practice space asked", firm.log_ids.mapped("action"))

    def test_the_switch_off_means_no_practice_space(self):
        firm, _job = self._onboard("cabinet-b", practice_space=False)
        self.assertFalse(firm.practice_space_ids)
        firm.with_user(self.operator).action_create_practice_space()
        self.assertTrue(firm.practice_space_ids)
        with self.assertRaisesRegex(UserError, "already"):
            firm.with_user(self.operator).action_create_practice_space()

    def test_spaces_asked_before_the_computer_exists_wait_for_it(self):
        firm, _job = self._onboard("cabinet-c")
        self.assertEqual(firm.practice_space_id.state, "waiting")
        computer = self._computer()
        self.assertEqual(firm.practice_space_id.computer_id, computer)
        self.assertEqual(firm.practice_space_id.state, "requested")

    def test_the_space_has_the_firms_add_ons_and_follows_its_switches(self):
        computer = self._computer()
        firm = self._active_firm("cabinet-d")
        item = computer._answer()["spaces"][0]
        self.assertEqual(item["addons"], [])
        firm.with_user(self.operator)._set_addon(self.addon, True, "Asked in the engagement letter")
        item = computer._answer()["spaces"][0]
        self.assertEqual(item["addons"], [self.addon.code])
        firm.with_user(self.operator)._set_addon(self.addon, False, "Not needed after all")
        self.assertEqual(computer._answer()["spaces"][0]["addons"], [])

    # ------------------------------------------------------------------ heartbeat

    def test_a_heartbeat_fills_the_figures_and_is_answered_signed(self):
        computer = self._computer()
        firm = self._active_firm("cabinet-e")
        answer, signature = computer._simulate_heartbeat()
        space = firm.practice_space_id
        self.assertEqual(space.state, "ready")
        self.assertEqual(space.users_count, 6)
        self.assertTrue(space.last_reset_at)
        self.assertTrue(computer.last_heartbeat_at)
        self.assertEqual(computer.guard_state, "ok")
        data = json.loads(answer)
        self.assertEqual([item["slug"] for item in data["spaces"]], ["cabinet-e"])
        self.assertEqual(base64_name(data["spaces"][0]), firm.name)
        self.assertEqual(len(signature), 64)

    def test_the_heartbeat_takes_figures_only(self):
        computer = self._computer()
        self._active_firm("cabinet-f")
        figures = computer._simulated_figures()
        figures["spaces"][0]["client_name"] = "Société Agro SA"
        headers, body = self._signed(computer, figures)
        with self.assertRaises(HeartbeatRejected) as caught:
            self.Computer._receive_heartbeat(headers, body)
        self.assertEqual(caught.exception.code, "bad_space")
        figures = computer._simulated_figures()
        figures["spaces"][0]["users"] = "six"
        headers, body = self._signed(computer, figures)
        with self.assertRaises(HeartbeatRejected):
            self.Computer._receive_heartbeat(headers, body)

    def test_a_forged_or_replayed_heartbeat_is_refused(self):
        computer = self._computer()
        figures = computer._simulated_figures()
        headers, body = self._signed(computer, figures)
        headers[practice.HEADER_SIGNATURE] = "0" * 64
        with self.assertRaises(HeartbeatRejected) as caught:
            self.Computer._receive_heartbeat(headers, body)
        self.assertEqual(caught.exception.code, "bad_signature")
        headers, body = self._signed(computer, figures)
        self.Computer._receive_heartbeat(headers, body)
        with self.assertRaises(HeartbeatRejected) as caught:
            self.Computer._receive_heartbeat(headers, body)
        self.assertEqual(caught.exception.code, "replayed_timestamp")

    def test_the_token_is_never_in_a_view_or_readable_by_an_operator(self):
        computer = self._computer()
        with self.assertRaises(AccessError):
            computer.with_user(self.owner).read(["heartbeat_token"])

    # ------------------------------------------------------------------ reset

    def test_reset_needs_the_typed_slug_and_a_reason_then_waits_for_the_computer(self):
        computer = self._computer()
        firm = self._active_firm("cabinet-g")
        computer._simulate_heartbeat()
        space = firm.practice_space_id
        wizard = self.env["platform.practice.reset.wizard"].with_user(self.operator).create({
            "space_id": space.id, "typed": "cabinet-x", "reason": "The firm asked for a clean start",
        })
        with self.assertRaisesRegex(UserError, "exactly"):
            wizard.action_confirm()
        wizard.typed = "cabinet-g"
        wizard.reason = " "
        with self.assertRaisesRegex(UserError, "why"):
            wizard.action_confirm()
        wizard.reason = "The firm asked for a clean start"
        wizard.action_confirm()
        self.assertEqual(space.state, "resetting")
        self.assertEqual(space.reset_generation, 1)
        self.assertEqual(computer._answer()["spaces"][0]["reset_generation"], 1)
        self.assertIn("Practice space reset to fresh demo data asked", firm.log_ids.mapped("action"))
        computer._simulate_heartbeat()
        self.assertEqual(space.state, "ready")
        self.assertEqual(space.reset_done_generation, 1)

    def test_a_viewer_cannot_reset(self):
        computer = self._computer()
        firm = self._active_firm("cabinet-h")
        computer._simulate_heartbeat()
        with self.assertRaises(UserError):  # AccessError is one too
            firm.practice_space_id.with_user(self.viewer)._request_reset("no")

    # ------------------------------------------------------------------ first login

    def test_the_first_login_shows_once_and_only_once_the_space_has_its_link(self):
        computer = self._computer()
        firm = self._active_firm("cabinet-i")
        space = firm.practice_space_id
        token = space.sudo().first_login_token
        item = computer._answer()["spaces"][0]
        self.assertEqual(item["first_admin_hash"], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, json.dumps(computer._answer()))
        self.assertFalse(space.first_login_ready)  # the practice computer does not have it yet
        computer._simulate_heartbeat()
        self.assertTrue(space.link_set)
        self.assertTrue(space.first_login_ready)
        wizard = self.env["platform.practice.first.login"].with_user(self.operator).create({"space_id": space.id})
        wizard.action_reveal()
        self.assertEqual(wizard.link, f"https://test.auditisa.com:8443/practice/cabinet-i/first-admin/{token}")
        self.assertEqual(wizard.login, "awa@exemple.cm")
        self.assertFalse(space.sudo().first_login_token)
        self.assertNotIn("first_admin_hash", computer._answer()["spaces"][0])
        again = self.env["platform.practice.first.login"].with_user(self.operator).create({"space_id": space.id})
        with self.assertRaisesRegex(UserError, "not available"):
            again.action_reveal()
        wizard.action_close()
        self.assertFalse(wizard.link)
        self.assertIn("First login of a practice space shown", firm.log_ids.mapped("action"))

    def test_an_expired_link_is_not_sent_and_a_new_one_can_be_made(self):
        computer = self._computer()
        firm = self._active_firm("cabinet-j")
        space = firm.practice_space_id
        space.sudo().first_login_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self.assertNotIn("first_admin_hash", computer._answer()["spaces"][0])
        space.with_user(self.operator).action_new_first_login()
        self.assertIn("first_admin_hash", computer._answer()["spaces"][0])

    # ------------------------------------------------------------------ removal

    def test_removal_is_the_owners_and_goes_through_the_computer(self):
        computer = self._computer()
        firm = self._active_firm("cabinet-k")
        computer._simulate_heartbeat()
        space = firm.practice_space_id
        with self.assertRaises(UserError):
            space.with_user(self.operator).action_remove()
        space.with_user(self.owner).action_remove()
        self.assertEqual(computer._answer()["remove"], ["cabinet-k"])
        computer._simulate_heartbeat()  # it no longer lists the space
        self.assertFalse(space.active)
        with self.assertRaises(UserError):
            space.sudo().unlink()

    # ------------------------------------------------------------------ release order

    def test_without_a_practice_computer_the_release_order_does_not_apply(self):
        ok, _until, message = self.release2._practice_hold()
        self.assertTrue(ok)
        self.assertIn("No practice computer", message)

    def test_firms_wait_for_the_holding_period_after_the_practice_computer(self):
        computer = self._computer()
        canary = self._active_firm("cabinet-l")
        rollout = self.env["platform.rollout"].with_user(self.operator).create({
            "release_id": self.release2.id, "canary_firm_id": canary.id, "firm_ids": [(6, 0, canary.ids)],
        })
        with self.assertRaisesRegex(UserError, "Not yet for the firms"):
            rollout.action_start()
        # The practice computer runs it: the 7 days start.
        wizard = self.env["platform.practice.release.wizard"].with_user(self.owner).create({
            "computer_id": computer.id, "release_id": self.release2.id,
        })
        wizard.action_confirm()
        self.assertEqual(computer._answer()["release"]["sha"], self.release2.sha)
        computer._simulate_heartbeat()
        self.assertEqual(computer.release, self.release2.sha)
        self.assertTrue(self.release2.practice_since)
        self.assertFalse(self.release2.practice_hold_ok)
        with self.assertRaisesRegex(UserError, "Not yet for the firms"):
            rollout.action_start()
        self.release2.sudo().practice_since = fields.Datetime.now() - timedelta(days=7, minutes=1)
        self.assertTrue(self.release2.practice_hold_ok)
        rollout.action_start()
        self.assertEqual(rollout.state, "running")

    def test_the_owner_alone_can_waive_the_holding_period(self):
        self._computer()
        with self.assertRaises(UserError):  # AccessError is one too
            self.release2.with_user(self.operator).write({"practice_hold_days": 0})
        self.release2.with_user(self.owner).write({"practice_hold_days": 0})
        self.assertTrue(self.release2.practice_hold_ok)
        self.assertIn("waived", self.release2.practice_hold_text)
        with self.assertRaises(UserError):
            self.release2.with_user(self.owner).write({"practice_hold_days": -1})

    def test_only_the_owner_sends_a_release_to_the_practice_computer(self):
        computer = self._computer()
        with self.assertRaises(UserError):  # AccessError is one too
            self.env["platform.practice.release.wizard"].with_user(self.operator).create({
                "computer_id": computer.id, "release_id": self.release2.id,
            }).action_confirm()

    def test_labels_exist_in_french(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"].sudo().search([("name", "=", "ea_platform_admin")])._update_translations(["fr_FR"])
        french = self.env["platform.practice.space"].with_context(lang="fr_FR")
        labels = dict(french._fields["state"]._description_selection(french.env))
        self.assertEqual(labels["ready"], "Prêt")
        self.assertEqual(french._fields["last_reset_at"]._description_string(french.env), "Dernière remise à zéro")


def base64_name(item):
    import base64
    return base64.b64decode(item["name_b64"]).decode()
