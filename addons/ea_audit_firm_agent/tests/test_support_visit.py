import base64
import hashlib
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.tests import HttpCase, new_test_user, tagged

from ..models import support
from .test_support import SupportCase


@tagged("post_install", "-at_install")
class TestSupportVisit(SupportCase):
    def setUp(self):
        super().setUp()
        self.visits = self.env["ea.firm.support.visit"]
        self.token = "k" * 43
        self.hash = hashlib.sha256(self.token.encode()).hexdigest()
        self.admin = new_test_user(self.env, login="firm_admin_x", groups="base.group_system")

    def _open(self, ref=11, minutes=60):
        return self.visits._root_request(ref, minutes, self.hash, "Awa Operator", "The lead schedule does not open")

    def _login(self, token):
        credential = {"type": "ea_support_visit", "login": support.SUPPORT_LOGIN, "token": token}
        return self.env["res.users"].authenticate(credential, {"interactive": True})

    def test_a_visit_opens_signs_in_by_link_and_ends_by_itself(self):
        visit = self._open()
        self.assertEqual(visit.state, "open")
        self.assertEqual((visit.operator, visit.reason), ("Awa Operator", "The lead schedule does not open"))
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
        visit._internal().write({"ends_at": fields.Datetime.now() - timedelta(seconds=1)})
        self.visits._cron_expire()
        self.assertEqual(visit.state, "expired")
        self.assertFalse(user.active)
        with self.assertRaises(AccessDenied):
            self._login(self.token)

    def test_the_expiry_cron_with_nothing_to_end_leaves_the_account_alone(self):
        """First real firm, 2026-11-09: the cron rewrote the password every minute, and each write
        queued a "password changed" notice."""
        user = self.visits._support_user()
        before = user.write_date
        with patch.object(type(user), "write", autospec=True, side_effect=type(user).write) as write:
            self.visits._cron_expire()
            self.visits._cron_expire()
        self.assertFalse([c for c in write.call_args_list if "password" in c.args[1]])
        self.assertEqual(user.write_date, before)

    def test_the_support_account_has_no_password_way_in(self):
        self._open(12)
        user = self.visits._support_user()
        with self.assertRaises(AccessDenied):
            self.env["res.users"].authenticate(
                {"type": "password", "login": user.login, "password": "anything"}, {"interactive": True},
            )

    def test_the_support_account_reads_and_never_writes(self):
        self._open(13)
        support_env = self.env(user=self.visits._support_user())
        partner = self.env["res.partner"].create({"name": "Client of the firm"})
        partners = support_env["res.partner"]
        self.assertEqual(partners.browse(partner.id).name, "Client of the firm")
        attempts = {
            "create": lambda: partners.create({"name": "New"}),
            "write": lambda: partners.browse(partner.id).write({"name": "Changed"}),
            "delete": lambda: partners.browse(partner.id).unlink(),
            "copy": lambda: partners.browse(partner.id).copy(),
            "archive": lambda: partners.browse(partner.id).action_archive(),
            "write as superuser": lambda: partners.sudo().browse(partner.id).write({"name": "Changed"}),
            "create as superuser": lambda: partners.sudo().create({"name": "New"}),
            "upload": lambda: support_env["ir.attachment"].sudo().create(
                {"name": "x.pdf", "res_model": "res.partner", "res_id": partner.id, "raw": b"x"}),
            "settings": lambda: support_env["ir.config_parameter"].sudo().set_param("x.y", "1"),
            "users": lambda: support_env["res.users"].sudo().create({"name": "Me", "login": "me_too"}),
        }
        if "mail.mail" in self.env:
            attempts["send"] = lambda: support_env["mail.mail"].sudo().create({"subject": "x", "email_to": "a@b.c"})
            attempts["message"] = lambda: partners.browse(partner.id).message_post(body="x")
        if "ea.audit.engagement" in self.env:
            attempts["engagement"] = lambda: support_env["ea.audit.engagement"].sudo().search([], limit=1).write({})
        for kind, attempt in attempts.items():
            with self.subTest(kind=kind), self.assertRaises(AccessError):
                attempt()
        self.assertEqual(partner.name, "Client of the firm")
        self.assertTrue(partner.active)

    def test_the_screens_opened_are_traced_by_identifier_only(self):
        visit = self._open(14)
        support_env = self.env(user=self.visits._support_user())
        partner = self.env["res.partner"].create({"name": "Client Agro SA"})
        support_env["res.partner"].browse(partner.id).web_read({"name": {}})
        support_env["res.partner"].web_search_read([("id", "=", partner.id)], {"name": {}})
        visit.invalidate_recordset(["trace_ids"])
        trace = visit.trace_ids
        self.assertEqual(trace.mapped("model"), ["res.partner", "res.partner"])
        self.assertEqual(trace.mapped("method"), ["form", "list"])
        self.assertEqual(trace.mapped("res_ids"), [str(partner.id), str(partner.id)])
        self.assertNotIn("Agro", " ".join(f"{t.model} {t.method} {t.res_ids}" for t in trace))

    def test_the_visit_and_its_trail_cannot_be_changed_or_deleted(self):
        visit = self._open(15)
        self.env(user=self.visits._support_user())["res.partner"].web_search_read([], {"name": {}}, limit=1)
        for target in (visit.with_user(self.admin), visit.sudo()):
            with self.assertRaises(AccessError):
                target.write({"reason": "Something else"})
            with self.assertRaises(AccessError):
                target.unlink()
        with self.assertRaises(AccessError):
            visit.trace_ids.sudo().write({"model": "x"})
        with self.assertRaises(AccessError):
            visit.trace_ids.sudo().unlink()

    def test_the_administrator_ends_it_and_support_cannot(self):
        visit = self._open(16)
        support_user = self.visits._support_user()
        with self.assertRaises(UserError):
            visit.with_user(support_user).action_end()
        visit.with_user(self.admin).action_end()
        self.assertEqual(visit.state, "ended")
        self.assertEqual(visit.ended_by, self.admin)
        self.assertFalse(support_user.active)

    def test_the_platform_ends_it_and_a_repeated_request_opens_nothing_new(self):
        first = self._open(17)
        self.assertEqual(self._open(17), first)
        self.visits._end_from_platform(17)
        self.assertEqual(first.state, "ended")

    def test_a_malformed_request_is_refused(self):
        good = (18, 60, self.hash, "Awa Operator", "Reason")
        for index, bad in ((0, 0), (1, 241), (2, "x" * 64), (0, "18"), (3, "Awa<script>"), (4, "r" * 501), (4, "")):
            args = list(good)
            args[index] = bad
            with self.assertRaises(UserError):
                self.visits._root_request(*args)

    def test_the_root_script_hands_over_base64_json_only(self):
        payload = {"id": 19, "minutes": 5, "token_sha256": self.hash, "operator": "Awa", "reason": "x'); import os; ('"}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        visit = self.visits._root_request(*support.decode_request(encoded))
        self.assertEqual(visit.reason, payload["reason"])


@tagged("post_install", "-at_install")
class TestSupportLink(HttpCase):
    def test_the_link_signs_in_as_support_and_closed_routes_stay_closed(self):
        token = "L" * 43
        visits = self.env["ea.firm.support.visit"]
        visit = visits._root_request(21, 60, hashlib.sha256(token.encode()).hexdigest(), "Awa", "Check a screen")
        self.env.flush_all()
        self.assertEqual(self.url_open("/ea-firm/support/" + "x" * 43, allow_redirects=False).status_code, 403)
        response = self.url_open("/ea-firm/support/" + token, allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        info = self.url_open("/web/session/get_session_info", data="{}", headers={"Content-Type": "application/json"}).json()
        self.assertEqual(info["result"]["username"], support.SUPPORT_LOGIN)
        partner = self.env["res.partner"].search([], limit=1)
        read = self.url_open("/web/dataset/call_kw/res.partner/web_search_read", headers={"Content-Type": "application/json"},
                             data=json.dumps({"params": {"model": "res.partner", "method": "web_search_read", "args": [],
                                                          "kwargs": {"domain": [("id", "=", partner.id)], "specification": {"name": {}}}}}))
        self.assertIn("result", read.json())
        visit.invalidate_recordset(["trace_ids"])
        self.assertEqual(visit.trace_ids.mapped("model"), ["res.partner"])
        for path in ("/web/export/xlsx", "/web/content/1", "/report/pdf/base.report_irmodulereference/1"):
            self.assertEqual(self.url_open(path, allow_redirects=False).status_code, 403, path)
        visit._close("ended")
        self.env.flush_all()
        info = self.url_open("/web/session/get_session_info", data="{}", headers={"Content-Type": "application/json"}).json()
        self.assertIsNone((info.get("result") or {}).get("uid"))
