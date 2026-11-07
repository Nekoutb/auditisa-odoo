import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from ..models import error_capture, firm_agent, support
from ..services import signing

TOKEN = "t" * 64
SLUG = "cabinet-a"
URL = "https://hb.example.invalid/platform/heartbeat"
CLIENT_TEXT = "Agro Industries SA, awa.ngono@agro.cm, solde 12 500 000 FCFA"


class Answer:
    def __init__(self, content, signature, status=200):
        self.status_code = status
        self.content = content
        self.headers = {signing.HEADER_RESPONSE_SIGNATURE: signature}


class SupportCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp(prefix="ea-support-test-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        token_file = os.path.join(self.folder, "token")
        with open(token_file, "w", encoding="ascii") as out:
            out.write(TOKEN)
        for name, value in (("TOKEN_FILE", token_file), ("STATUS_DIR", self.folder)):
            patcher = patch.object(firm_agent, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        params = self.env["ir.config_parameter"].sudo()
        params.set_param(firm_agent.PARAM_URL, URL)
        params.set_param(firm_agent.PARAM_SLUG, SLUG)

    def _platform(self, answer_for):
        """Stands for the control plane: checks the signature, answers signed."""
        sent = []

        def post(url, data=None, headers=None, timeout=None, allow_redirects=None):
            prefix = signing.PREFIX_TICKET if url.endswith("/ticket") else signing.PREFIX_SYNC
            stamp = headers[signing.HEADER_TIMESTAMP]
            assert headers[signing.HEADER_SIGNATURE] == signing.sign_kind(prefix, TOKEN, SLUG, stamp, data)
            sent.append((url, json.loads(data)))
            body = json.dumps(answer_for(url, json.loads(data))).encode()
            message = b"\n".join([prefix + b"-response", SLUG.encode(), stamp.encode(), hashlib.sha256(body).hexdigest().encode()])
            import hmac
            return Answer(body, hmac.new(TOKEN.encode(), message, hashlib.sha256).hexdigest())

        return sent, patch.object(support.requests, "post", post)


@tagged("post_install", "-at_install")
class TestErrorsLeaveAsCodes(SupportCase):
    def test_client_data_in_an_error_never_leaves(self):
        path = os.path.join(self.folder, "errors.log")
        error_capture.install_handler()
        thread = threading.current_thread()
        with patch.object(error_capture, "errors_file", lambda _db: path), patch.object(thread, "dbname", self.env.cr.dbname, create=True):
            try:
                raise ValueError(CLIENT_TEXT)
            except ValueError:
                logging.getLogger("odoo.addons.ea_audit_firm_agent.tests").exception("Failed on %s", CLIENT_TEXT)
            with open(path, encoding="ascii") as handle:
                written = handle.read()
            self.assertIn("ValueError", written)
            self.assertIn("ea_audit_firm_agent", written)
            with open(os.path.join(self.folder, "release"), "w", encoding="ascii") as out:
                out.write("abcdef123456\n")
            figures = self.env["ea.firm.agent"].with_context(ea_error_files=[])._build_figures()
        body = signing.encode(figures).decode()
        for piece in ("Agro", "awa.ngono", "agro.cm", "12 500 000", "FCFA", "solde"):
            self.assertNotIn(piece, written)
            self.assertNotIn(piece, body)
        self.assertEqual(figures["errors"][0]["kind"], "ValueError")
        self.assertEqual(figures["errors"][0]["count"], 1)

    def test_a_warning_or_a_refusal_is_not_a_technical_error(self):
        path = os.path.join(self.folder, "errors.log")
        error_capture.install_handler()
        thread = threading.current_thread()
        with patch.object(error_capture, "errors_file", lambda _db: path), patch.object(thread, "dbname", self.env.cr.dbname, create=True):
            logging.getLogger("odoo.addons.ea_audit_firm_agent.tests").warning("A user error: %s", CLIENT_TEXT)
            logging.getLogger("odoo.addons.ea_audit_firm_agent.tests").error("No traceback: %s", CLIENT_TEXT)
        self.assertFalse(os.path.exists(path))


@tagged("post_install", "-at_install")
class TestReportAProblem(SupportCase):
    def test_a_problem_goes_to_the_operator_and_the_reply_comes_back(self):
        user = new_test_user(self.env, login="ea_reporter", groups="base.group_user")
        replies = {}

        def answer(url, data):
            if url.endswith("/ticket"):
                return {"ok": True}
            return {"tickets": [{"ref": ref, "state": "closed", "reply": replies.get(ref, "")} for ref in data["refs"]]}

        sent, patcher = self._platform(answer)
        with patcher:
            ticket = self.env["ea.firm.support.ticket"].with_user(user).create({
                "subject": "The lead schedule does not open", "message": "Click on it, nothing happens.",
            })
            self.assertEqual(ticket.state, "open")
            self.assertEqual(sent[0][0], "https://hb.example.invalid/platform/support/ticket")
            self.assertEqual(set(sent[0][1]), {"ref", "subject", "message", "screen"})
            replies[ticket.ref] = "Fixed in the next release."
            ticket.with_user(user).action_refresh()
        self.assertEqual(ticket.state, "closed")
        self.assertEqual(ticket.reply, "Fixed in the next release.")
        self.assertNotIn(user.login, json.dumps(sent))

    def test_a_user_sees_only_their_own_problems_and_cannot_set_the_reply(self):
        alice = new_test_user(self.env, login="ea_alice", groups="base.group_user")
        bob = new_test_user(self.env, login="ea_bob", groups="base.group_user")
        _sent, patcher = self._platform(lambda url, data: {"ok": True})
        with patcher:
            ticket = self.env["ea.firm.support.ticket"].with_user(alice).create({"subject": "S", "message": "M", "reply": "forged"})
        self.assertFalse(ticket.reply)
        self.assertFalse(self.env["ea.firm.support.ticket"].with_user(bob).search([]))
        with self.assertRaises(AccessError):
            ticket.with_user(alice).write({"reply": "forged"})

    def test_without_the_platform_it_waits_and_is_sent_later(self):
        user = new_test_user(self.env, login="ea_waiter", groups="base.group_user")
        with patch.object(support.requests, "post", side_effect=support.requests.ConnectionError("down")):
            ticket = self.env["ea.firm.support.ticket"].with_user(user).create({"subject": "S", "message": "M"})
        self.assertEqual(ticket.state, "queued")
        _sent, patcher = self._platform(lambda url, data: {"ok": True} if url.endswith("/ticket") else {"tickets": []})
        with patcher:
            self.env["ea.firm.support.ticket"]._cron_sync()
        self.assertEqual(ticket.state, "open")

    def test_an_unsigned_answer_changes_nothing(self):
        user = new_test_user(self.env, login="ea_unsigned", groups="base.group_user")
        with patch.object(support.requests, "post", return_value=Answer(b'{"ok":true}', "0" * 64)):
            ticket = self.env["ea.firm.support.ticket"].with_user(user).create({"subject": "S", "message": "M"})
        self.assertEqual(ticket.state, "queued")


@tagged("post_install", "-at_install")
class TestSupportVisit(SupportCase):
    def setUp(self):
        super().setUp()
        self.visits = self.env["ea.firm.support.visit"]
        self.token = "k" * 43
        self.hash = hashlib.sha256(self.token.encode()).hexdigest()
        self.admin = new_test_user(self.env, login="firm_admin_x", groups="base.group_system")

    def _login(self, token):
        credential = {"type": "ea_support_visit", "login": support.SUPPORT_LOGIN, "token": token}
        return self.env["res.users"].authenticate(credential, {"interactive": True})

    def test_a_visit_opens_signs_in_by_link_and_ends_by_itself(self):
        visit = self.visits._root_request(11, 60, self.hash)
        self.assertEqual(visit.state, "open")
        user = self.visits._support_user()
        self.assertTrue(user.active)
        self.assertEqual(user.name, support.SUPPORT_NAME)
        self.assertEqual(self._login(self.token)["uid"], user.id)
        with self.assertRaises(AccessDenied):
            self._login("w" * 43)
        events = self.env["ea.firm.access.log"].search([("account", "=", support.SUPPORT_LOGIN)]).mapped("event")
        self.assertIn("support-visit-open", events)
        self.assertIn("support-login", events)
        self.assertEqual(self.visits._current_figure(), {"id": 11, "state": "open"})
        visit.ends_at = fields.Datetime.now() - timedelta(seconds=1)
        self.visits._cron_expire()
        self.assertEqual(visit.state, "expired")
        self.assertFalse(user.active)
        with self.assertRaises(AccessDenied):
            self._login(self.token)

    def test_the_support_account_has_no_password_way_in(self):
        self.visits._root_request(12, 60, self.hash)
        user = self.visits._support_user()
        with self.assertRaises(AccessDenied):
            self.env["res.users"].authenticate({"type": "password", "login": user.login, "password": "anything"}, {"interactive": True})

    def test_with_the_setting_on_it_waits_for_the_administrator(self):
        self.env["ir.config_parameter"].sudo().set_param(support.PARAM_APPROVAL, "True")
        visit = self.visits._root_request(13, 30, self.hash)
        self.assertEqual(visit.state, "waiting")
        with self.assertRaises(AccessDenied):
            self._login(self.token)
        visit.with_user(self.admin).action_approve()
        self.assertEqual(visit.state, "open")
        self.assertTrue(self._login(self.token))

    def test_the_administrator_ends_it_and_support_cannot_approve_itself(self):
        visit = self.visits._root_request(14, 60, self.hash)
        support_user = self.visits._support_user()
        with self.assertRaises(UserError):
            visit.with_user(support_user).action_end()
        visit.with_user(self.admin).action_end()
        self.assertEqual(visit.state, "ended")
        self.assertEqual(visit.ended_by, self.admin)
        self.assertFalse(support_user.active)

    def test_the_platform_ends_it_and_a_repeated_request_opens_nothing_new(self):
        first = self.visits._root_request(15, 60, self.hash)
        self.assertEqual(self.visits._root_request(15, 60, self.hash), first)
        self.visits._end_from_platform(15)
        self.assertEqual(first.state, "ended")

    def test_a_malformed_request_is_refused(self):
        for args in ((0, 60, self.hash), (16, 241, self.hash), (16, 60, "x" * 64), ("16", 60, self.hash)):
            with self.assertRaises(UserError):
                self.visits._root_request(*args)

    def test_the_settings_field_defaults_off(self):
        self.assertFalse(self.env["res.config.settings"].create({}).support_visit_requires_approval)


@tagged("post_install", "-at_install")
class TestSupportLink(HttpCase):
    def test_the_link_signs_in_as_support_and_the_session_ends_with_the_visit(self):
        token = "L" * 43
        visits = self.env["ea.firm.support.visit"]
        visit = visits._root_request(21, 60, hashlib.sha256(token.encode()).hexdigest())
        self.env.flush_all()
        self.assertEqual(self.url_open("/ea-firm/support/" + "x" * 43, allow_redirects=False).status_code, 403)
        response = self.url_open("/ea-firm/support/" + token, allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        info = self.url_open("/web/session/get_session_info", data="{}", headers={"Content-Type": "application/json"}).json()
        self.assertEqual(info["result"]["username"], support.SUPPORT_LOGIN)
        visit._close("ended")
        self.env.flush_all()
        info = self.url_open("/web/session/get_session_info", data="{}", headers={"Content-Type": "application/json"}).json()
        self.assertNotEqual((info.get("result") or {}).get("username"), support.SUPPORT_LOGIN)
