import json
import time
from datetime import datetime

from odoo.tests import HttpCase, tagged

from ..services import heartbeat, simulator
from .common import PlatformMixin

URL = "/platform/heartbeat"


@tagged("post_install", "-at_install")
class TestHeartbeatEndpoint(PlatformMixin, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_platform()

    def setUp(self):
        super().setUp()
        self.firm, _job = self._onboard()
        self.firm.action_confirm_key_escrow()
        self.token = self.firm.sudo().heartbeat_token
        self.now = int(time.time()) + 5

    def _figures(self, **changes):
        figures = simulator.healthy_figures(datetime.utcnow().replace(microsecond=0), self.release.sha, users=7, engagements=3)
        figures.update(changes)
        return figures

    def _send(self, figures=None, token=None, slug=None, timestamp=None, content_type="application/json", tamper=None):
        headers, body = simulator.signed_request(
            token or self.token, slug or self.firm.slug, timestamp or self.now, figures or self._figures(),
        )
        headers["Content-Type"] = content_type
        return self.url_open(URL, data=tamper or body, headers=headers)

    def test_a_good_heartbeat_updates_the_figures(self):
        answer = self._send()
        self.assertEqual(answer.status_code, 200)
        self.env.invalidate_all()
        self.assertEqual(self.firm.users_active, 7)
        self.assertEqual(self.firm.engagements_active, 3)
        self.assertEqual(self.firm.disk_used_pct, 12)
        self.assertEqual(self.firm.health_color, "green")

    def test_the_answer_is_signed_and_holds_only_what_may_be_asked(self):
        answer = self._send()
        expected = heartbeat.sign_response(self.token, self.firm.slug, self.now, answer.content)
        self.assertEqual(answer.headers[heartbeat.HEADER_RESPONSE_SIGNATURE], expected)
        self.assertLessEqual(
            set(json.loads(answer.content)),
            {"ok", "export_requested", "ssh_allowlist", "desired_release", "desired_bundle_sha256"},
        )

    def test_no_session_cookie_is_set(self):
        self.assertNotIn("session_id", self._send().headers.get("Set-Cookie", ""))

    def test_every_refusal_looks_the_same(self):
        answers = [
            self._send(token="x" * 64),
            self._send(slug="inconnu-du-tout"),
            self._send(timestamp=self.now - 3600),
            self._send(self._figures(client_name="Agro SA")),
            self._send(content_type="text/plain"),
            self._send(tamper=b"{}"),
        ]
        for answer in answers:
            self.assertEqual(answer.status_code, 403)
            self.assertEqual(answer.json(), {"ok": False})

    def test_refusals_store_no_figure(self):
        before = self.firm.users_active
        self._send(self._figures(users_active=999, client_name="Agro SA"))
        self.env.invalidate_all()
        self.assertEqual(self.firm.users_active, before)
        self.assertEqual(self.firm.last_reject_code, "unknown_key")
        self.assertNotIn("Agro", json.dumps(self.firm.read(["last_reject_code", "health_reason"]), default=str))

    def test_a_valid_token_with_extra_data_turns_the_firm_orange(self):
        self._send()
        self._send(self._figures(client_name="Agro SA"), timestamp=self.now + 1)
        self.env.invalidate_all()
        self.assertEqual(self.firm.heartbeat_rejects_24h, 1)
        self.assertEqual(self.firm.health_color, "amber")

    def test_a_stranger_with_a_bad_signature_cannot_turn_a_firm_orange(self):
        self._send()
        self._send(token="x" * 64)
        self.env.invalidate_all()
        self.assertEqual(self.firm.heartbeat_rejects_24h, 0)
        self.assertEqual(self.firm.health_color, "green")

    def test_a_replayed_heartbeat_is_refused(self):
        self.assertEqual(self._send().status_code, 200)
        self.assertEqual(self._send().status_code, 403)

    def test_another_firms_token_is_refused(self):
        other, _job = self._onboard("cabinet-b")
        answer = self._send(token=other.sudo().heartbeat_token)
        self.assertEqual(answer.status_code, 403)

    def test_an_archived_firm_is_refused(self):
        self.firm.sudo().state = "archived"
        self.assertEqual(self._send().status_code, 403)

    def test_get_is_refused(self):
        self.assertNotEqual(self.url_open(URL).status_code, 200)

    def test_nothing_else_opens_without_a_login(self):
        answer = self.url_open("/web", allow_redirects=False)
        self.assertIn(answer.status_code, (302, 303))
        self.assertIn("/web/login", answer.headers["Location"])

    def test_the_answer_names_the_desired_release_for_an_active_firm_only(self):
        answer = json.loads(self._send().content)
        self.assertEqual(answer["desired_release"], self.release.sha)
        self.assertEqual(answer["desired_bundle_sha256"], self.release.bundle_sha256)
        self.firm.release_locked = True
        answer = json.loads(self._send(timestamp=self.now + 1).content)
        self.assertNotIn("desired_release", answer)

    def test_the_answer_asks_for_an_export_only_during_offboarding(self):
        self.assertFalse(json.loads(self._send().content)["export_requested"])
        self.firm.sudo().write({"state": "offboarding", "export_requested": True})
        self.assertTrue(json.loads(self._send(timestamp=self.now + 1).content)["export_requested"])
