import base64
import json
import logging
import re
import secrets
import time
import uuid
from datetime import timedelta

import requests
import werkzeug.exceptions

from odoo import api, fields, models, tools
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.http import request

from ..services import collect, signing
from ..services.first_admin import token_matches

_logger = logging.getLogger(__name__)

SUPPORT_LOGIN = "auditisa-support"
SUPPORT_NAME = "AuditISA support (operator, not a firm user)"
MAX_MINUTES = 240
MAX_TRACE_IDS = 20
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MODEL = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+){0,6}$")
_OPERATOR = re.compile(r"^[\w .'-]{1,64}$")
TICKET_STATES = [("queued", "Not sent yet"), ("open", "Open"), ("in_progress", "In progress"), ("closed", "Closed")]
VISIT_STATES = [("open", "Open"), ("ended", "Ended"), ("expired", "Expired")]

# What the support account's own requests may still write: its sign-in record, the visit's trail,
# and Odoo's own bookkeeping of a session. Nothing that belongs to the firm.
SUPPORT_WRITABLE = frozenset({
    "ea.firm.support.visit", "ea.firm.support.trace", "ea.firm.access.log", "res.users.log",
    "res.users.settings", "res.users.settings.volumes", "bus.presence", "mail.presence", "res.device", "res.device.log",
})
# Routes that hand content out or take files in, closed to the support account.
SUPPORT_CLOSED_ROUTES = re.compile(r"^/(web/export/|web/content|web/binary/upload|report/|mail/attachment/upload|html_editor/attachment)")


def _support_url(heartbeat_url, path):
    return heartbeat_url.rsplit("/platform/", 1)[0] + path if heartbeat_url and "/platform/" in heartbeat_url else None


class EaFirmSupportTicket(models.Model):
    """'Report a problem': a message a user chooses to send to the operator, and the reply.

    This is a separate channel from the heartbeat, which carries no free text. The form warns the
    user not to write client details. The operator sees the text and a reference, not who wrote it.
    """

    _name = "ea.firm.support.ticket"
    _description = "Problem reported to the operator"
    _order = "id desc"
    _rec_name = "subject"

    ref = fields.Char("Reference", readonly=True, copy=False, default=lambda self: uuid.uuid4().hex)
    user_id = fields.Many2one("res.users", "Reported by", readonly=True, default=lambda self: self.env.user)
    subject = fields.Char("Subject", required=True)
    message = fields.Text("What happened", required=True)
    screen = fields.Char("Screen", readonly=True, help="The technical name of the screen, if known.")
    state = fields.Selection(TICKET_STATES, "State", readonly=True, default="queued")
    reply = fields.Text("The operator's reply", readonly=True)
    replied_at = fields.Datetime("Replied on", readonly=True)
    sent_at = fields.Datetime("Sent on", readonly=True)

    _ref_unique = models.Constraint("unique(ref)", "A ticket has one reference.")

    @api.constrains("subject", "message")
    def _check_size(self):
        for ticket in self:
            if len(ticket.subject or "") > 200 or len(ticket.message or "") > 4000:
                raise UserError(self.env._("Keep the subject under 200 characters and the message under 4000."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            for key in ("user_id", "state", "reply", "replied_at", "sent_at"):
                vals.pop(key, None)
        tickets = super().create(vals_list)
        tickets.sudo()._send()
        return tickets

    def _send(self):
        agent = self.env["ea.firm.agent"].sudo()
        target = agent._support_target("/platform/support/ticket")
        if not target:
            return False
        for ticket in self.filtered(lambda t: t.state == "queued"):
            screen = ticket.screen if ticket.screen and _MODEL.match(ticket.screen) else ""
            body = {"ref": ticket.ref, "subject": ticket.subject or "", "message": ticket.message or "", "screen": screen}
            answer = agent._post_support(target, signing.PREFIX_TICKET, body)
            if answer is not None and answer.get("ok") is True:
                ticket.write({"state": "open", "sent_at": fields.Datetime.now()})
        return True

    @api.model
    def _cron_sync(self):
        """Sends what is queued, fetches states and replies, then hands over the visits' trails."""
        tickets = self.sudo().search([("state", "!=", "closed")], limit=50)
        tickets._send()
        self.env["ea.firm.support.trace"]._send_pending()
        agent = self.env["ea.firm.agent"].sudo()
        target = agent._support_target("/platform/support/sync")
        sent = tickets.filtered(lambda t: t.state != "queued")
        if not target or not sent:
            return False
        answer = agent._post_support(target, signing.PREFIX_SYNC, {"refs": sent.mapped("ref")})
        if not answer or not isinstance(answer.get("tickets"), list):
            return False
        for item in answer["tickets"]:
            if not isinstance(item, dict):
                continue
            ticket = sent.filtered(lambda t: t.ref == item.get("ref"))
            state = item.get("state")
            reply = item.get("reply")
            if not ticket or state not in ("open", "in_progress", "closed"):
                continue
            values = {"state": state}
            if isinstance(reply, str) and reply != (ticket.reply or ""):
                values.update(reply=reply[:4000], replied_at=fields.Datetime.now())
            ticket.write(values)
        return True

    def action_refresh(self):
        self.sudo()._cron_sync()
        return True


class EaFirmSupportVisit(models.Model):
    """One support visit: numbered, never edited, never deleted.

    The operator signs in to this firm's Odoo for a limited time as the named support account, which
    can read every screen and change nothing (see `base` below). Asked by the control plane, opened
    by this server's root script, shown to the firm's administrator, who can end it at once.
    """

    _name = "ea.firm.support.visit"
    _description = "Support visit by the operator"
    _order = "id desc"
    _rec_name = "platform_ref"

    platform_ref = fields.Integer("Visit number", readonly=True, index=True)
    operator = fields.Char("Operator", readonly=True)
    reason = fields.Text("Reason", readonly=True)
    release = fields.Char("Release in use", readonly=True)
    minutes = fields.Integer("Length (minutes)", readonly=True)
    token_hash = fields.Char("Link fingerprint", readonly=True, groups="base.group_no_one")
    state = fields.Selection(VISIT_STATES, "State", readonly=True, default="open")
    opened_at = fields.Datetime("Started on", readonly=True)
    ends_at = fields.Datetime("Ends on", readonly=True)
    ended_at = fields.Datetime("Ended on", readonly=True)
    ended_by = fields.Many2one("res.users", "Ended by", readonly=True)
    logins = fields.Integer("Sign-ins", readonly=True)
    trace_ids = fields.One2many("ea.firm.support.trace", "visit_id", "Screens and records opened")

    _ref_unique = models.Constraint("unique(platform_ref)", "One record per visit.")

    def write(self, vals):
        if not self.env.context.get("ea_support_visit_internal"):
            raise AccessError(self.env._("A support visit's record cannot be changed."))
        return super().write(vals)

    def unlink(self):
        raise AccessError(self.env._("A support visit's record cannot be deleted."))

    def _internal(self):
        return self.sudo().with_context(ea_support_visit_internal=True)

    @api.model
    def _support_user(self):
        """The named account. Created once; no password anyone knows; inactive outside a visit.

        It holds the groups of the firm's administrator so that every screen opens; the read-only
        guard on `base` refuses every change it might attempt.
        """
        users = self.env["res.users"].sudo().with_context(active_test=False, no_reset_password=True)
        user = users.search([("login", "=", SUPPORT_LOGIN)], limit=1)
        if not user:
            admin = self.env.ref("base.user_admin")
            user = users.create({
                "name": SUPPORT_NAME, "login": SUPPORT_LOGIN, "tz": "UTC",
                "password": secrets.token_urlsafe(48), "group_ids": [(6, 0, admin.group_ids.ids)],
            })
            user.write({"active": False})
            self.env.registry.clear_cache()
        return user

    @api.model
    def _root_request(self, ref, minutes, token_hash, operator, reason):
        """Called by deploy/firm/firm-support-visit.sh, as root through the Odoo shell, only."""
        if not (isinstance(ref, int) and 0 < ref < 10 ** 9 and isinstance(minutes, int) and 1 <= minutes <= MAX_MINUTES
                and isinstance(token_hash, str) and _HASH.match(token_hash)
                and isinstance(operator, str) and _OPERATOR.match(operator)
                and isinstance(reason, str) and 0 < len(reason) <= 500):
            raise UserError("refused")
        visit = self.sudo().search([("platform_ref", "=", ref)], limit=1)
        if visit:
            return visit
        user = self._support_user()
        from .firm_agent import STATUS_DIR

        now = fields.Datetime.now()
        visit = self.sudo().create({
            "platform_ref": ref, "minutes": minutes, "token_hash": token_hash, "operator": operator,
            "reason": reason, "release": collect.read_status(STATUS_DIR).get("release") or False,
            "opened_at": now, "ends_at": now + timedelta(minutes=minutes),
        })
        user.write({"active": True})
        self._log("support-visit-open")
        self._notify_admins(self.env._(
            "Support visit %(number)s is open until %(end)s UTC: %(operator)s may read your screens as \"%(name)s\", "
            "and can change nothing. Reason: %(reason)s. You can end it at any time in Settings > Support visits.",
            number=ref, end=visit.ends_at.strftime("%H:%M"), operator=operator, name=SUPPORT_NAME, reason=reason,
        ))
        return visit

    def _close(self, state, user=None):
        for visit in self.filtered(lambda v: v.state == "open"):
            visit._internal().write({"state": state, "ended_at": fields.Datetime.now(), "ended_by": user.id if user else False})
            self._log(f"support-visit-{state}")
        if not self.sudo().search_count([("state", "=", "open")]):
            # A new random password also ends every session the account had.
            self._support_user().write({"active": False, "password": secrets.token_urlsafe(48)})

    def action_end(self):
        if self.env.user.login == SUPPORT_LOGIN or not self.env.user.has_group("base.group_system"):
            raise UserError(self.env._("Only the firm's administrator ends a support visit from here."))
        self._close("ended", self.env.user)
        return True

    @api.model
    def _end_from_platform(self, ref):
        self.sudo().search([("platform_ref", "=", ref)])._close("ended")

    @api.model
    def _cron_expire(self):
        self.sudo().search([("state", "=", "open"), ("ends_at", "<=", fields.Datetime.now())])._close("expired")

    @api.model
    def _current_figure(self):
        """What the heartbeat says of the latest visit: a number and a state, nothing else."""
        visit = self.sudo().search([], limit=1)
        return {"id": visit.platform_ref, "state": visit.state} if visit else None

    @api.model
    def _log(self, event):
        self.env["ea.firm.access.log"].sudo().create({
            "logged_at": fields.Datetime.now(), "event": event, "account": SUPPORT_LOGIN, "source": "",
        })

    @api.model
    def _notify_admins(self, text):
        admins = self.env.ref("base.group_system").sudo().all_user_ids.filtered(lambda u: u.login != SUPPORT_LOGIN and u.active)
        for partner in admins.partner_id:
            if hasattr(partner, "_bus_send"):
                partner._bus_send("simple_notification", {
                    "type": "warning", "sticky": True, "title": self.env._("Support visit"), "message": text,
                })

    @api.model
    def _open_visit_for(self, token):
        visit = self.sudo().search([("state", "=", "open"), ("ends_at", ">", fields.Datetime.now())])
        return visit.filtered(lambda v: token_matches(token, v.token_hash))[:1]


class EaFirmSupportTrace(models.Model):
    """Which screens and records the support account opened: model, method, ids. Never content."""

    _name = "ea.firm.support.trace"
    _description = "Screen opened during a support visit"
    _order = "id"

    visit_id = fields.Many2one("ea.firm.support.visit", "Visit", readonly=True, index=True, ondelete="restrict")
    opened_at = fields.Datetime("Opened on", readonly=True)
    model = fields.Char("Screen (model)", readonly=True)
    method = fields.Char("Kind", readonly=True)
    res_ids = fields.Char("Record ids", readonly=True)

    def init(self):
        self.env.cr.execute("""
            CREATE OR REPLACE FUNCTION ea_support_trace_refuse_change() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'ea_firm_support_trace is append-only'; END; $$ LANGUAGE plpgsql;
            DROP TRIGGER IF EXISTS ea_support_trace_append_only ON ea_firm_support_trace;
            CREATE TRIGGER ea_support_trace_append_only BEFORE UPDATE OR DELETE ON ea_firm_support_trace
                FOR EACH ROW EXECUTE FUNCTION ea_support_trace_refuse_change();
        """)

    def write(self, vals):
        raise AccessError(self.env._("A support visit's trail cannot be changed."))

    def unlink(self):
        raise AccessError(self.env._("A support visit's trail cannot be deleted."))

    @api.model
    def _record(self, model, method, ids):
        """Its own cursor: screens are read on read-only cursors, and the trail must stay anyway."""
        if not (isinstance(model, str) and _MODEL.match(model)):
            return
        ids = ",".join(str(i) for i in list(ids or [])[:MAX_TRACE_IDS] if isinstance(i, int))
        self.env["ea.firm.support.visit"].flush_model()
        if self.env.cr.readonly:
            # Screens are read on read-only cursors: the trail goes through a cursor of its own.
            with self.env.registry.cursor() as cr:
                self._insert_trace(cr, model, method, ids)
        else:
            self._insert_trace(self.env.cr, model, method, ids)

    def _insert_trace(self, cr, model, method, ids):
        cr.execute("SELECT id FROM ea_firm_support_visit WHERE state = 'open' ORDER BY id DESC LIMIT 1")
        row = cr.fetchone()
        if row:
            cr.execute(
                "INSERT INTO ea_firm_support_trace (visit_id, opened_at, model, method, res_ids, create_uid, create_date, write_uid, write_date)"
                " VALUES (%s, now() at time zone 'utc', %s, %s, %s, %s, now() at time zone 'utc', %s, now() at time zone 'utc')",
                [row[0], model, method, ids, self.env.uid, self.env.uid],
            )

    @api.model
    def _send_pending(self):
        """Hands the trail to the control plane, visit by visit. Identifiers only."""
        params = self.env["ir.config_parameter"].sudo()
        last = int(params.get_param("ea_firm_agent.trace_sent_id") or 0)
        rows = self.sudo().search([("id", ">", last)], limit=200)
        agent = self.env["ea.firm.agent"].sudo()
        target = agent._support_target("/platform/support/trace")
        if not rows or not target:
            return False
        for visit in rows.visit_id:
            mine = rows.filtered(lambda r: r.visit_id == visit)
            body = {"visit": visit.platform_ref, "release": visit.release or "", "entries": [{
                "at": r.opened_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "model": r.model, "method": r.method,
                "ids": [int(i) for i in (r.res_ids or "").split(",") if i],
            } for r in mine]}
            answer = agent._post_support(target, signing.PREFIX_TRACE, body)
            if not answer or answer.get("ok") is not True:
                return False
            params.set_param("ea_firm_agent.trace_sent_id", str(max(mine.ids)))
        return True


class Base(models.AbstractModel):
    """The support account reads and never writes: refused here, for every model, even under sudo."""

    _inherit = "base"

    @api.model
    @tools.ormcache()
    def _ea_support_uid(self):
        self.env.cr.execute("SELECT id FROM res_users WHERE login = %s", [SUPPORT_LOGIN])
        row = self.env.cr.fetchone()
        return row[0] if row else 0

    def _ea_support_refuses(self, vals_list=None):
        uid = self.env.uid
        if not uid or uid != self.env["base"]._ea_support_uid() or self._name in SUPPORT_WRITABLE:
            return
        if self._name == "ir.attachment" and vals_list is not None and all(
            str(vals.get("url") or "").startswith("/web/assets/") and not vals.get("res_model") for vals in vals_list
        ):
            return  # the web client's own style and script bundles
        raise AccessError(self.env._("A support visit reads only: nothing can be created, changed, deleted or sent."))

    @api.model_create_multi
    def create(self, vals_list):
        self._ea_support_refuses(vals_list)
        return super().create(vals_list)

    def write(self, vals):
        self._ea_support_refuses()
        return super().write(vals)

    def unlink(self):
        self._ea_support_refuses()
        return super().unlink()

    @api.model
    @api.readonly
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        # A list reads its rows through web_read: one line in the trail, not two.
        quiet = self.with_context(ea_support_no_trace=True)
        result = super(Base, quiet).web_search_read(domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit)
        if self.env.uid and self.env.uid == self.env["base"]._ea_support_uid():
            self.env["ea.firm.support.trace"]._record(self._name, "list", [r.get("id") for r in result.get("records", [])])
        return result

    @api.readonly
    def web_read(self, specification):
        result = super().web_read(specification)
        if not self.env.context.get("ea_support_no_trace") and self.env.uid and self.env.uid == self.env["base"]._ea_support_uid():
            self.env["ea.firm.support.trace"]._record(self._name, "form", self.ids)
        return result


class EaFirmAgentSupport(models.AbstractModel):
    _inherit = "ea.firm.agent"

    @api.model
    def _support_target(self, path):
        from .firm_agent import PARAM_SLUG, PARAM_URL

        get_param = self.env["ir.config_parameter"].sudo().get_param
        url, slug, token = _support_url(get_param(PARAM_URL), path), get_param(PARAM_SLUG), self._read_token()
        if not (url and slug and token and url.startswith("https://")):
            return None
        return url, slug, token

    @api.model
    def _post_support(self, target, prefix, payload):
        """A signed POST on the support channel. Returns the verified answer, or None."""
        url, slug, token = target
        body = signing.encode(payload)
        timestamp = int(time.time())
        headers = {
            "Content-Type": "application/json",
            signing.HEADER_FIRM: slug,
            signing.HEADER_TIMESTAMP: str(timestamp),
            signing.HEADER_SIGNATURE: signing.sign_kind(prefix, token, slug, timestamp, body),
        }
        try:
            response = requests.post(url, data=body, headers=headers, timeout=20, allow_redirects=False)
        except requests.RequestException as error:
            _logger.warning("Support message not delivered: %s", type(error).__name__)
            return None
        if response.status_code != 200 or not signing.response_is_authentic_kind(
            prefix, token, slug, timestamp, response.content, response.headers.get(signing.HEADER_RESPONSE_SIGNATURE),
        ):
            _logger.warning("Support answer refused or not authentic: HTTP %s", response.status_code)
            return None
        try:
            answer = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        return answer if isinstance(answer, dict) else None


class ResUsersSupport(models.Model):
    _inherit = "res.users"

    def _check_credentials(self, credential, env):
        """The support account signs in with an open visit's link, and only that way."""
        if credential.get("type") == "ea_support_visit":
            if self.env.user.login != SUPPORT_LOGIN or credential.get("login") != SUPPORT_LOGIN:
                raise AccessDenied()
            visit = self.env["ea.firm.support.visit"]._open_visit_for(credential.get("token"))
            if not visit:
                raise AccessDenied()
            visit._internal().write({"logins": visit.logins + 1})
            self.env["ea.firm.support.visit"]._log("support-login")
            return {"uid": self.env.user.id, "auth_method": "ea_support_visit", "mfa": "skip"}
        if self.env.user.login == SUPPORT_LOGIN:
            raise AccessDenied()
        return super()._check_credentials(credential, env)


class IrHttpSupport(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _authenticate(cls, endpoint):
        """Outside an open visit a support session ends; inside one, no route hands content out."""
        session = request.session
        support = bool(request.db and session.uid and session.get("login") == SUPPORT_LOGIN)
        if support:
            env = request.env(su=True)
            if not env["ea.firm.support.visit"].search_count([("state", "=", "open"), ("ends_at", ">", fields.Datetime.now())]):
                session.logout(keep_db=True)
                support = False
        result = super()._authenticate(endpoint)
        if support and SUPPORT_CLOSED_ROUTES.match(request.httprequest.path):
            raise werkzeug.exceptions.Forbidden()
        return result


def decode_request(encoded):
    """What firm-support-visit.sh hands over: base64 of a JSON object, so no value is ever code."""
    data = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    return data["id"], data["minutes"], data["token_sha256"], data["operator"], data["reason"]
