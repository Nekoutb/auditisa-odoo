import json
import os
import shutil
import tempfile
from unittest.mock import patch

import requests

from odoo.tests import TransactionCase, tagged

from ..models import firm_agent
from ..services import signing

TOKEN = "t" * 64
SLUG = "cabinet-a"
URL = "https://hb.example.invalid/platform/heartbeat"


class Answer:
    def __init__(self, status=200, content=b"{}", signature=None):
        self.status_code = status
        self.content = content
        self.headers = {signing.HEADER_RESPONSE_SIGNATURE: signature} if signature else {}


class HeartbeatCase(TransactionCase):
    """A firm's server with its token, status folder and spool in a temporary folder."""

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp(prefix="ea-agent-test-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.status = os.path.join(self.folder, "status")
        os.mkdir(self.status)
        self.spool = os.path.join(self.folder, "desired.json")
        token_file = os.path.join(self.folder, "token")
        with open(token_file, "w", encoding="ascii") as out:
            out.write(TOKEN + "\n")
        for name, value in (("TOKEN_FILE", token_file), ("STATUS_DIR", self.status), ("SPOOL_FILE", self.spool)):
            patcher = patch.object(firm_agent, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.agent = self.env["ea.firm.agent"]
        params = self.env["ir.config_parameter"].sudo()
        params.set_param(firm_agent.PARAM_URL, URL)
        params.set_param(firm_agent.PARAM_SLUG, SLUG)
        with open(os.path.join(self.status, "release"), "w", encoding="ascii") as out:
            out.write("abcdef123456\n")

    def _capture(self, answer=None):
        sent = {}

        def post(url, data=None, headers=None, timeout=None, allow_redirects=None):
            sent.update(url=url, data=data, headers=headers, timeout=timeout, allow_redirects=allow_redirects)
            if isinstance(answer, Exception):
                raise answer
            return answer or Answer()

        return sent, patch.object(firm_agent.requests, "post", post)

    def _signed_answer(self, answer):
        import hashlib
        import hmac

        body = json.dumps(answer).encode()
        message = b"\n".join([
            b"ea-heartbeat-response-v1", SLUG.encode(), b"1800000000", hashlib.sha256(body).hexdigest().encode(),
        ])
        signature = hmac.new(TOKEN.encode(), message, hashlib.sha256).hexdigest()
        with patch.object(firm_agent.time, "time", return_value=1800000000), \
                patch.object(firm_agent.requests, "post", return_value=Answer(content=body, signature=signature)):
            self.assertTrue(self.agent._cron_send_heartbeat())
        with open(self.spool, encoding="ascii") as handle:
            return json.load(handle)


@tagged("post_install", "-at_install")
class TestHeartbeat(HeartbeatCase):
    def test_figures_are_counts_and_never_records(self):
        figures = self.agent._build_figures()
        self.assertEqual(figures["release"], "abcdef123456")
        self.assertGreaterEqual(figures["users_active"], 1)
        self.assertFalse(figures["mail_enabled"])
        for key, value in figures.items():
            if key in ("addons_on", "errors"):
                self.assertTrue(all(isinstance(code, str) for code in value))
                continue
            self.assertIsInstance(value, (int, str, bool, type(None)), key)
        allowed = {
            "schema", "release", "odoo_version", "update_state", "export_state", "ssh_sessions_24h",
            "mem_total_mb", "mem_available_mb", "disk_total_gb", "disk_used_pct",
            "users_active", "engagements_active", "mail_enabled", "addons_on", "addons_refused", "errors",
        }
        self.assertEqual(set(figures), allowed)

    def test_engagement_count_needs_no_audit_addon(self):
        self.assertIsInstance(self.agent._count_engagements(), int)

    def test_a_sent_heartbeat_is_signed_and_goes_out_without_redirects(self):
        sent, patcher = self._capture()
        with patcher:
            self.agent._cron_send_heartbeat()
        self.assertEqual(sent["url"], URL)
        self.assertFalse(sent["allow_redirects"])
        self.assertTrue(sent["timeout"])
        timestamp = sent["headers"][signing.HEADER_TIMESTAMP]
        self.assertEqual(sent["headers"][signing.HEADER_FIRM], SLUG)
        self.assertEqual(
            sent["headers"][signing.HEADER_SIGNATURE],
            signing.sign(TOKEN, SLUG, timestamp, sent["data"]),
        )
        self.assertNotIn(TOKEN.encode(), sent["data"])

    def test_nothing_goes_out_without_a_configuration(self):
        self.env["ir.config_parameter"].sudo().set_param(firm_agent.PARAM_URL, False)
        with patch.object(firm_agent.requests, "post", side_effect=AssertionError("sent")):
            self.assertFalse(self.agent._cron_send_heartbeat())

    def test_nothing_goes_out_without_a_token(self):
        with patch.object(firm_agent, "TOKEN_FILE", os.path.join(self.folder, "none")), \
                patch.object(firm_agent.requests, "post", side_effect=AssertionError("sent")):
            self.assertFalse(self.agent._cron_send_heartbeat())

    def test_plain_http_is_refused(self):
        self.env["ir.config_parameter"].sudo().set_param(firm_agent.PARAM_URL, "http://hb.example.invalid/x")
        with patch.object(firm_agent.requests, "post", side_effect=AssertionError("sent")):
            self.assertFalse(self.agent._cron_send_heartbeat())

    def test_a_network_failure_is_quiet(self):
        _sent, patcher = self._capture(requests.ConnectionError("down"))
        with patcher:
            self.assertFalse(self.agent._cron_send_heartbeat())

    def test_an_unsigned_answer_is_ignored(self):
        body = json.dumps({"export_requested": True}).encode()
        _sent, patcher = self._capture(Answer(content=body))
        with patcher:
            self.assertFalse(self.agent._cron_send_heartbeat())
        self.assertFalse(os.path.exists(self.spool))

    def test_a_signed_answer_reaches_the_spool(self):
        body = json.dumps({"export_requested": True, "run": "rm -rf /"}).encode()
        import hashlib
        import hmac

        def answer_for(sent_timestamp):
            message = b"\n".join([
                b"ea-heartbeat-response-v1", SLUG.encode(), str(sent_timestamp).encode(),
                hashlib.sha256(body).hexdigest().encode(),
            ])
            return hmac.new(TOKEN.encode(), message, hashlib.sha256).hexdigest()

        with patch.object(firm_agent.time, "time", return_value=1800000000), \
                patch.object(firm_agent.requests, "post", return_value=Answer(content=body, signature=answer_for(1800000000))):
            self.assertTrue(self.agent._cron_send_heartbeat())
        with open(self.spool, encoding="ascii") as handle:
            self.assertEqual(json.load(handle), {"export_requested": True})

    def test_the_email_request_gets_a_file_of_its_own_readable_by_this_user_only(self):
        mail_spool = os.path.join(self.folder, "mail.json")
        request = {
            "ref": "0123456789abcdef", "action": "set", "host": "smtp.office365.com", "port": 587,
            "encryption": "starttls", "user": "cabinet@exemple.cm", "password": "pw-of-the-firm", "from": "cabinet@exemple.cm",
        }
        with patch.object(firm_agent, "MAIL_SPOOL_FILE", mail_spool):
            spool = self._signed_answer({"mail_request": request, "export_requested": False})
        self.assertNotIn("mail_request", spool)
        with open(self.spool, encoding="ascii") as handle:
            self.assertNotIn("pw-of-the-firm", handle.read())
        with open(mail_spool, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), request)
        self.assertEqual(os.stat(mail_spool).st_mode & 0o777, 0o600)

    def test_the_email_answer_goes_back_as_a_reference_and_one_word(self):
        for name, value in (("mail_request_ref", "0123456789abcdef"), ("mail_request_result", "on")):
            with open(os.path.join(self.status, name), "w", encoding="ascii") as out:
                out.write(value + "\n")
        figures = self.agent._build_figures()
        self.assertEqual(figures["mail_request_ref"], "0123456789abcdef")
        self.assertEqual(figures["mail_request_result"], "on")

    def test_the_administrator_request_is_applied_once_and_answered_with_its_link(self):
        if "ea.audit.firm.admin" not in self.env:
            self.skipTest("the firm administrator's screens are not installed")
        link = "https://cabinet-a.auditisa.com/web/signup?db=cabinet_a&token=Abc-123_x"
        request = {"ref": "0123456789abcdef", "action": "replace", "name": "Paul Mbida", "email": "paul@exemple.cm"}
        calls = []

        def apply(_self, action, name, email):
            calls.append((action, name, email))
            return "done", link

        with patch.object(type(self.env["ea.audit.firm.admin"]), "_ea_fa_from_platform", apply):
            spool = self._signed_answer({"admin_request": request, "export_requested": False})
            self.assertNotIn("admin_request", spool)
            self.assertEqual(calls, [("replace", "Paul Mbida", "paul@exemple.cm")])
            figures = self.agent._build_figures()
            self.assertEqual(figures["admin_request_ref"], "0123456789abcdef")
            self.assertEqual(figures["admin_request_result"], "done")
            self.assertEqual(figures["admin_request_link"], link)
            # The console sends the request again until it hears the answer: nothing is done twice, and once
            # a heartbeat has carried the link, the firm's server forgets it.
            self._signed_answer({"admin_request": request})
            self.assertEqual(len(calls), 1)
        figures = self.agent._build_figures()
        self.assertEqual(figures["admin_request_result"], "done")
        self.assertNotIn("admin_request_link", figures)
        self.assertFalse(self.env["ir.config_parameter"].sudo().get_param(firm_agent.PARAM_ADMIN_LINK))

    def test_a_failed_administrator_request_is_reported_without_details(self):
        if "ea.audit.firm.admin" not in self.env:
            self.skipTest("the firm administrator's screens are not installed")
        request = {"ref": "fedcba9876543210", "action": "add", "name": "Paul", "email": "paul@exemple.cm"}

        def apply(_self, action, name, email):
            raise ValueError("Paul paul@exemple.cm")

        with patch.object(type(self.env["ea.audit.firm.admin"]), "_ea_fa_from_platform", apply):
            self._signed_answer({"admin_request": request})
        figures = self.agent._build_figures()
        self.assertEqual((figures["admin_request_ref"], figures["admin_request_result"]), ("fedcba9876543210", "failed"))
        self.assertNotIn("admin_request_link", figures)

    def test_the_add_ons_asked_reach_the_spool(self):
        spool = self._signed_answer({"desired_addons": ["ea_client_b", "ea_client_a"]})
        self.assertEqual(spool["addons"], ["ea_client_a", "ea_client_b"])

    def test_an_empty_add_on_list_is_a_request_and_an_absent_one_is_not(self):
        self.assertEqual(self._signed_answer({"desired_addons": []})["addons"], [])
        self.assertNotIn("addons", self._signed_answer({"export_requested": False}))

    def test_add_on_names_of_the_wrong_shape_are_dropped_before_the_spool(self):
        for bad in (["Bad Name"], ["x;reboot"], "ea_client_a", [1], ["a" * 41]):
            self.assertNotIn("addons", self._signed_answer({"desired_addons": bad}))

    def test_a_refusal_changes_nothing(self):
        _sent, patcher = self._capture(Answer(status=403))
        with patcher:
            self.assertFalse(self.agent._cron_send_heartbeat())
        self.assertFalse(os.path.exists(self.spool))


@tagged("post_install", "-at_install")
class TestDocumentReading(HeartbeatCase):
    """The console's Document reading tab (owner, 2026-11-20): the firm's key for Opening Balance Testing."""

    KEY = "sk-ant-api03-Cabinet-Key-For-Reading-7f3aQx9Z"

    def setUp(self):
        super().setUp()
        self.key_path = os.path.join(self.folder, "data", "auditisa", "document-reading.key")
        patcher = patch.object(type(self.agent), "_docr_key_path", lambda _self: self.key_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_key_is_kept_in_a_file_of_its_own_and_answered_once(self):
        tested = []

        def test_key(_self, key):
            tested.append(key)
            return "on"

        request = {"ref": "0123456789abcdef", "action": "set", "key": self.KEY}
        with patch.object(type(self.agent), "_docr_test_key", test_key):
            spool = self._signed_answer({"doc_reading_request": request, "export_requested": False})
            self.assertNotIn("doc_reading_request", spool)
            self.assertNotIn(self.KEY, json.dumps(spool))
            with open(self.key_path, encoding="ascii") as handle:
                self.assertEqual(handle.read(), self.KEY)
            if os.name == "posix":
                self.assertEqual(os.stat(self.key_path).st_mode & 0o777, 0o600)
                self.assertEqual(os.stat(os.path.dirname(self.key_path)).st_mode & 0o777, 0o700)
            # the console sends the request again until it hears the answer: nothing is done twice
            self._signed_answer({"doc_reading_request": request})
        self.assertEqual(tested, [self.KEY])
        figures = self.agent._build_figures()
        self.assertEqual((figures["doc_reading_ref"], figures["doc_reading_result"], figures["doc_reading_last4"]),
                         ("0123456789abcdef", "on", "Qx9Z"))
        params = self.env["ir.config_parameter"].sudo()
        self.assertFalse([p for p in params.search([]).mapped("value") if self.KEY in (p or "")])

    def test_this_month_s_use_is_reported_once_a_key_was_asked_for(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param(firm_agent.PARAM_DOCR_USAGE, json.dumps({"month": "2026-11", "documents": 4, "pages": 19}))
        self.assertNotIn("doc_reading_month", self.agent._build_figures())
        with patch.object(type(self.agent), "_docr_test_key", lambda _self, key: "refused"):
            self._signed_answer({"doc_reading_request": {"ref": "1111111111111111", "action": "set", "key": self.KEY}})
        figures = self.agent._build_figures()
        self.assertEqual(figures["doc_reading_result"], "refused")
        self.assertEqual((figures["doc_reading_month"], figures["doc_reading_documents"], figures["doc_reading_pages"]),
                         ("2026-11", 4, 19))

    def test_remove_forgets_the_key_and_test_reads_it(self):
        with patch.object(type(self.agent), "_docr_test_key", lambda _self, key: "on" if key == self.KEY else "removed"):
            self._signed_answer({"doc_reading_request": {"ref": "2222222222222222", "action": "set", "key": self.KEY}})
            self._signed_answer({"doc_reading_request": {"ref": "3333333333333333", "action": "test"}})
            self.assertEqual(self.agent._build_figures()["doc_reading_result"], "on")
            self._signed_answer({"doc_reading_request": {"ref": "4444444444444444", "action": "remove"}})
        self.assertFalse(os.path.exists(self.key_path))
        figures = self.agent._build_figures()
        self.assertEqual(figures["doc_reading_result"], "removed")
        self.assertNotIn("doc_reading_last4", figures)

    def test_a_malformed_request_is_ignored(self):
        for request in (
            {"ref": "0123456789abcdef", "action": "set", "key": "short"},
            {"ref": "0123456789abcdef", "action": "set", "key": self.KEY, "extra": 1},
            {"ref": "nothex", "action": "test"},
            {"ref": "0123456789abcdef", "action": "steal"},
        ):
            self._signed_answer({"doc_reading_request": request})
        self.assertFalse(os.path.exists(self.key_path))
        self.assertNotIn("doc_reading_ref", self.agent._build_figures())

    def test_without_the_package_the_key_test_says_unavailable(self):
        import sys
        saved = sys.modules.get("anthropic")
        sys.modules["anthropic"] = None
        try:
            self.assertEqual(self.agent._docr_test_key(self.KEY), "unavailable")
        finally:
            if saved is None:
                sys.modules.pop("anthropic", None)
            else:
                sys.modules["anthropic"] = saved
        self.assertEqual(self.agent._docr_test_key(""), "removed")
