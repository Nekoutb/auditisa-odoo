import hashlib
import json
import time
from datetime import datetime

from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, tagged

from ..services import heartbeat, support
from ..services.simulator import healthy_figures, signed_request
from .common import PlatformCase, PlatformMixin

ERROR = {"module": "ea_audit_core", "model": "res.partner", "kind": "ValueError", "count": 3}


def support_request(firm, prefix, payload, timestamp=None):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    timestamp = timestamp or int(time.time())
    headers = {
        heartbeat.HEADER_FIRM: firm.slug,
        heartbeat.HEADER_TIMESTAMP: str(timestamp),
        heartbeat.HEADER_SIGNATURE: heartbeat.sign_kind(prefix, firm.sudo().heartbeat_token, firm.slug, timestamp, body),
    }
    return headers, body


@tagged("post_install", "-at_install")
class TestErrors(PlatformCase):
    def test_reported_errors_are_kept_as_codes_and_raise_attention(self):
        firm = self._active_firm()
        now = heartbeat.format_instant(datetime.utcnow().replace(microsecond=0))
        firm._simulate_heartbeat(errors=[{**ERROR, "last_at": now}])
        firm.invalidate_recordset()
        self.assertEqual(firm.errors_24h, 3)
        self.assertEqual(firm.error_ids.kind, "ValueError")
        self.assertEqual(firm.health_color, "amber")
        self.assertIn("3 technical error(s)", firm.health_reason)
        self.assertTrue(firm.needs_attention)

    def test_an_error_carrying_client_text_is_refused_and_kept_nowhere(self):
        firm = self._active_firm()
        figures = healthy_figures(datetime.utcnow().replace(microsecond=0), self.release.sha)
        figures["errors"] = [{**ERROR, "kind": "Agro Industries SA", "last_at": "2026-11-07T11:00:00Z"}]
        headers, body = signed_request(firm.sudo().heartbeat_token, firm.slug, int(time.time()) + 30, figures)
        with self.assertRaises(heartbeat.HeartbeatRejected):
            self.env["platform.firm"]._receive_heartbeat(headers, body)
        self.env.flush_all()
        self.env.cr.execute("SELECT count(*) FROM platform_firm_error WHERE kind LIKE %s", ["%Agro%"])
        self.assertEqual(self.env.cr.fetchone()[0], 0)


@tagged("post_install", "-at_install")
class TestReportedProblems(PlatformCase):
    def _ticket(self, firm, ref="a" * 32, **changes):
        payload = {"ref": ref, "subject": "Lead schedule", "message": "It does not open.", "screen": "", **changes}
        return self.env["platform.firm"]._receive_support(support.PREFIX_TICKET, *support_request(firm, support.PREFIX_TICKET, payload))

    def test_a_problem_lands_in_the_list_once_and_the_reply_goes_back(self):
        firm = self._active_firm()
        answer, signature = self._ticket(firm)
        self.assertEqual(json.loads(answer), {"ok": True})
        self.assertTrue(signature)
        firm.sudo().last_support_timestamp -= 10
        self._ticket(firm)
        ticket = self.env["platform.ticket"].search([("firm_id", "=", firm.id)])
        self.assertEqual(len(ticket), 1)
        self.assertEqual(ticket.state, "open")
        firm.invalidate_recordset()
        self.assertEqual(firm.tickets_open, 1)
        self.assertIn("reported problem", firm.health_reason)
        ticket.with_user(self.operator).write({"reply": "Fixed in the next release.", "state": "in_progress"})
        self.assertEqual(ticket.replied_by, self.operator)
        headers, body = support_request(firm, support.PREFIX_SYNC, {"refs": [ticket.ref]}, int(time.time()) + 5)
        answer, _sig = self.env["platform.firm"]._receive_support(support.PREFIX_SYNC, headers, body)
        self.assertEqual(json.loads(answer)["tickets"], [{"ref": ticket.ref, "state": "in_progress", "reply": "Fixed in the next release."}])
        ticket.with_user(self.operator).action_close()
        firm.invalidate_recordset()
        self.assertEqual(firm.tickets_open, 0)

    def test_a_viewer_reads_and_cannot_answer(self):
        firm = self._active_firm()
        self._ticket(firm)
        ticket = self.env["platform.ticket"].search([("firm_id", "=", firm.id)])
        self.assertTrue(ticket.with_user(self.viewer).subject)
        with self.assertRaises(AccessError):
            ticket.with_user(self.viewer).write({"reply": "x"})

    def test_a_signature_for_another_kind_or_firm_or_an_old_one_is_refused(self):
        firm = self._active_firm("cabinet-a")
        other = self._active_firm("cabinet-b")
        payload = {"ref": "b" * 32, "subject": "S", "message": "M", "screen": ""}
        headers, body = support_request(firm, support.PREFIX_SYNC, payload)
        with self.assertRaises(heartbeat.HeartbeatRejected):
            self.env["platform.firm"]._receive_support(support.PREFIX_TICKET, headers, body)
        headers, body = support_request(other, support.PREFIX_TICKET, payload)
        headers[heartbeat.HEADER_FIRM] = firm.slug
        with self.assertRaises(heartbeat.HeartbeatRejected):
            self.env["platform.firm"]._receive_support(support.PREFIX_TICKET, headers, body)
        with self.assertRaises(heartbeat.HeartbeatRejected):
            self.env["platform.firm"]._receive_support(support.PREFIX_TICKET, *support_request(firm, support.PREFIX_TICKET, payload, int(time.time()) - 3600))
        self.assertFalse(self.env["platform.ticket"].search_count([]))


@tagged("post_install", "-at_install")
class TestSupportVisit(PlatformCase):
    def _start(self, firm, user=None, reason="The lead schedule does not open", minutes=60):
        wizard = self.env["platform.support.visit.wizard"].with_user(user or self.operator).create({
            "firm_id": firm.id, "reason": reason, "minutes": minutes,
        })
        wizard.action_confirm()
        return wizard

    def test_the_link_is_shown_once_and_only_its_fingerprint_is_kept(self):
        firm = self._active_firm()
        wizard = self._start(firm)
        token = wizard.link.rsplit("/", 1)[1]
        visit = firm.support_visit_ids
        self.assertEqual(visit.link_fingerprint, hashlib.sha256(token.encode()).hexdigest())
        self.assertEqual(visit.release, firm.addon_release)
        wizard.action_close()
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT table_name, column_name FROM information_schema.columns
             WHERE table_schema = 'public' AND data_type IN ('text', 'character varying')
               AND table_name LIKE 'platform\\_%%'
        """)
        for table, column in self.env.cr.fetchall():
            self.env.cr.execute(f'SELECT count(*) FROM "{table}" WHERE "{column}" LIKE %s', [f"%{token}%"])  # noqa: S608
            self.assertEqual(self.env.cr.fetchone()[0], 0, f"{table}.{column}")
        log = firm.log_ids.filtered(lambda r: r.action == "Support visit asked")
        self.assertEqual(log.user_id, self.operator)
        self.assertIn("The lead schedule does not open", log.detail_text)

    def test_the_answer_asks_then_the_firm_opens_then_it_ends(self):
        firm = self._active_firm()
        self._start(firm)
        visit = firm.support_visit_ids
        answer = firm.sudo()._heartbeat_answer()["support_visit"]
        self.assertEqual(set(answer), {"id", "minutes", "token_sha256", "operator", "reason"})
        self.assertEqual(answer["token_sha256"], visit.link_fingerprint)
        firm._simulate_heartbeat()
        self.assertEqual(visit.state, "open")
        self.assertNotIn("support_visit", firm.sudo()._heartbeat_answer())
        firm.invalidate_recordset()
        self.assertEqual(firm.health_color, "amber")
        self.assertIn("support visit is open", firm.health_reason)
        firm.with_user(self.operator).action_end_support_visit()
        self.assertEqual(firm.sudo()._heartbeat_answer()["support_visit_end"], visit.id)
        firm._simulate_heartbeat()
        self.assertEqual(visit.state, "ended")

    def test_a_reason_is_required_one_visit_at_a_time_and_only_for_a_live_firm(self):
        firm = self._active_firm()
        with self.assertRaises(UserError):
            self._start(firm, reason="   ")
        with self.assertRaises(UserError):
            self._start(firm, minutes=500)
        self._start(firm)
        with self.assertRaises(UserError):
            self._start(firm)
        firm.sudo().state = "suspended"
        firm.support_visit_ids.with_context(ea_visit_internal=True).write({"state": "ended"})
        with self.assertRaises(UserError):
            self._start(firm)

    def test_a_viewer_cannot_start_a_visit(self):
        firm = self._active_firm()
        with self.assertRaises(AccessError):
            self._start(firm, user=self.viewer)

    def test_the_record_cannot_be_changed_or_deleted_and_the_trail_arrives(self):
        firm = self._active_firm()
        self._start(firm)
        firm._simulate_heartbeat()
        visit = firm.support_visit_ids
        for user in (self.operator, self.owner):
            with self.assertRaises((UserError, AccessError)):
                visit.with_user(user).write({"reason": "Other"})
            with self.assertRaises((UserError, AccessError)):
                visit.with_user(user).unlink()
        with self.assertRaises(UserError):
            visit.sudo().with_context(ea_visit_internal=True).write({"reason": "Other"})
        payload = {"visit": visit.id, "release": firm.addon_release, "entries": [
            {"at": "2026-11-07T11:00:00Z", "model": "ea.audit.engagement", "method": "form", "ids": [12]},
        ]}
        answer, _sig = self.env["platform.firm"]._receive_support(
            support.PREFIX_TRACE, *support_request(firm, support.PREFIX_TRACE, payload, int(time.time()) + 3))
        self.assertEqual(json.loads(answer), {"ok": True})
        self.assertEqual(visit.trace_ids.mapped("model_name"), ["ea.audit.engagement"])
        self.assertEqual(visit.trace_ids.res_ids, "12")
        with self.assertRaises(UserError):
            visit.trace_ids.sudo().write({"res_ids": "13"})
        with self.assertRaises(UserError):
            visit.trace_ids.sudo().unlink()


@tagged("post_install", "-at_install")
class TestSupervisionShowsSupport(PlatformCase):
    def test_the_page_and_the_workbook_carry_the_support_figures(self):
        from ..controllers import supervision

        names = {name for name, _title in supervision.COLUMNS}
        self.assertLessEqual({"errors_24h", "tickets_open", "visit_state"}, names)
        arch = self.env.ref("ea_platform_admin.view_supervision_kanban").arch_db
        for name in ("errors_24h", "tickets_open", "visit_state"):
            self.assertIn(name, arch)

    def test_the_status_tab_is_there_for_the_status_screen(self):
        menu = self.env.ref("ea_platform_admin.menu_status")
        self.assertEqual(menu.parent_id, self.env.ref("ea_platform_admin.menu_root"))
        self.assertEqual(menu.action, self.env.ref("ea_platform_admin.action_status"))
        siblings = menu.parent_id.child_id.sorted("sequence")
        self.assertEqual(siblings[:2].mapped("name"), ["Supervision", "Status"])


@tagged("post_install", "-at_install")
class TestSupportRoutes(PlatformMixin, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_platform()

    def test_a_signed_ticket_is_taken_and_anything_else_answers_alike(self):
        firm = self._active_firm()
        self.env.flush_all()
        payload = {"ref": "c" * 32, "subject": "S", "message": "M", "screen": ""}
        headers, body = support_request(firm, support.PREFIX_TICKET, payload)
        response = self.url_open("/platform/support/ticket", data=body, headers={**headers, "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get(heartbeat.HEADER_RESPONSE_SIGNATURE))
        headers[heartbeat.HEADER_SIGNATURE] = "0" * 64
        refused = self.url_open("/platform/support/ticket", data=body, headers={**headers, "Content-Type": "application/json"})
        self.assertEqual((refused.status_code, refused.text), (403, '{"ok":false}'))
