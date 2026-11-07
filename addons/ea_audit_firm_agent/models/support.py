import json
import logging
import re
import secrets
import time
import uuid
from datetime import timedelta

import requests

from odoo import api, fields, models
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request

from ..services import signing
from ..services.first_admin import token_matches

_logger = logging.getLogger(__name__)

SUPPORT_LOGIN = "auditisa-support"
SUPPORT_NAME = "AuditISA support (operator, not a firm user)"
PARAM_APPROVAL = "ea_firm_agent.support_visit_requires_approval"
MAX_MINUTES = 240
_REF = re.compile(r"^[0-9a-f]{32}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
TICKET_STATES = [("queued", "Not sent yet"), ("open", "Open"), ("in_progress", "In progress"), ("closed", "Closed")]
VISIT_STATES = [
    ("waiting", "Waiting for your approval"),
    ("open", "Open"),
    ("ended", "Ended"),
    ("refused", "Refused"),
    ("expired", "Expired"),
]


def _support_url(heartbeat_url, path):
    return heartbeat_url.rsplit("/platform/", 1)[0] + path if heartbeat_url and "/platform/" in heartbeat_url else None


class EaFirmSupportTicket(models.Model):
    """'Report a problem': a message a user chooses to send to the operator, and the reply.

    This is a separate channel from the heartbeat, which carries no free text. The form warns the
    user not to write client details. The operator sees the text and a ticket number, not who wrote it.
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
            vals.pop("user_id", None)
            vals.pop("state", None)
            vals.pop("reply", None)
        tickets = super().create(vals_list)
        tickets.sudo()._send()
        return tickets

    def _send(self):
        agent = self.env["ea.firm.agent"].sudo()
        target = agent._support_target("/platform/support/ticket")
        if not target:
            return False
        for ticket in self.filtered(lambda t: t.state == "queued"):
            body = {"ref": ticket.ref, "subject": ticket.subject or "", "message": ticket.message or "",
                    "screen": ticket.screen if ticket.screen and re.match(r"^[a-z][a-z0-9_.]{0,79}$", ticket.screen) else ""}
            answer = agent._post_support(target, signing.PREFIX_TICKET, body)
            if answer is not None and answer.get("ok") is True:
                ticket.write({"state": "open", "sent_at": fields.Datetime.now()})
        return True

    @api.model
    def _cron_sync(self):
        """Sends what is queued, then fetches states and replies for the tickets still open."""
        tickets = self.sudo().search([("state", "!=", "closed")], limit=50)
        tickets._send()
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
        self._cron_sync()
        return True


class EaFirmSupportVisit(models.Model):
    """A support visit: the operator signs in to this firm's Odoo, for a limited time, as a named
    support account. Asked by the control plane, opened by this server's root script, visible to
    the firm's administrator, who can approve it (if the setting asks for that) and end it at once.
    """

    _name = "ea.firm.support.visit"
    _description = "Support visit by the operator"
    _order = "id desc"

    platform_ref = fields.Integer("Request number", readonly=True, index=True)
    minutes = fields.Integer("Length (minutes)", readonly=True)
    token_hash = fields.Char("Link fingerprint", readonly=True, groups="base.group_no_one")
    state = fields.Selection(VISIT_STATES, "State", readonly=True, default="waiting")
    requested_at = fields.Datetime("Asked on", readonly=True)
    opened_at = fields.Datetime("Opened on", readonly=True)
    ends_at = fields.Datetime("Ends on", readonly=True)
    ended_at = fields.Datetime("Ended on", readonly=True)
    ended_by = fields.Many2one("res.users", "Ended by", readonly=True)
    logins = fields.Integer("Sign-ins", readonly=True)

    _ref_unique = models.Constraint("unique(platform_ref)", "One visit per request.")

    @api.model
    def _support_user(self):
        """The named account. Created once; no password anyone knows; inactive outside a visit."""
        users = self.env["res.users"].sudo().with_context(active_test=False, no_reset_password=True)
        user = users.search([("login", "=", SUPPORT_LOGIN)], limit=1)
        groups = [self.env.ref("base.group_user").id, self.env.ref("base.group_system").id]
        firm_admin = self.env.ref("ea_audit_core.group_firm_admin", raise_if_not_found=False)
        if firm_admin:
            groups.append(firm_admin.id)
        if not user:
            user = users.create({
                "name": SUPPORT_NAME, "login": SUPPORT_LOGIN, "active": False,
                "password": secrets.token_urlsafe(48), "group_ids": [(6, 0, groups)],
            })
        return user

    @api.model
    def _root_request(self, ref, minutes, token_hash):
        """Called by deploy/firm/firm-support-visit.sh, as root through the Odoo shell, only."""
        if not (isinstance(ref, int) and ref > 0 and isinstance(minutes, int) and 1 <= minutes <= MAX_MINUTES
                and isinstance(token_hash, str) and _HASH.match(token_hash)):
            raise UserError("refused")
        visit = self.sudo().search([("platform_ref", "=", ref)], limit=1)
        if visit:
            return visit
        self._support_user()
        approval = self.env["ir.config_parameter"].sudo().get_param(PARAM_APPROVAL) in ("1", "True")
        visit = self.sudo().create({
            "platform_ref": ref, "minutes": minutes, "token_hash": token_hash, "requested_at": fields.Datetime.now(),
        })
        self._log("support-visit-requested")
        if approval:
            self._notify_admins(self.env._("The operator asks for a support visit. Approve or refuse it in Settings > Support visits."))
        else:
            visit._open()
        return visit

    def _open(self):
        self.ensure_one()
        now = fields.Datetime.now()
        self.write({"state": "open", "opened_at": now, "ends_at": now + timedelta(minutes=self.minutes)})
        self._support_user().write({"active": True})
        self._log("support-visit-open")
        self._notify_admins(self.env._(
            "A support visit is open until %(end)s UTC. The operator signs in as \"%(name)s\". "
            "You can end it at any time in Settings > Support visits.",
            end=self.ends_at.strftime("%H:%M"), name=SUPPORT_NAME,
        ))

    def _close(self, state, user=None):
        for visit in self.filtered(lambda v: v.state in ("waiting", "open")):
            visit.write({"state": state, "ended_at": fields.Datetime.now(), "ended_by": user.id if user else False})
            self._log(f"support-visit-{state}")
        if not self.search_count([("state", "=", "open")]):
            # A new random password also ends every session the account had.
            self._support_user().write({"active": False, "password": secrets.token_urlsafe(48)})

    def action_approve(self):
        self._check_admin()
        for visit in self.filtered(lambda v: v.state == "waiting"):
            visit._open()
        return True

    def action_refuse(self):
        self._check_admin()
        self.filtered(lambda v: v.state == "waiting")._close("refused", self.env.user)
        return True

    def action_end(self):
        self._check_admin()
        self._close("ended", self.env.user)
        return True

    def _check_admin(self):
        if self.env.user.login == SUPPORT_LOGIN or not self.env.user.has_group("base.group_system"):
            raise UserError(self.env._("Only the firm's administrator decides on a support visit."))

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
        partners = admins.partner_id
        if hasattr(partners, "_bus_send"):
            for partner in partners:
                partner._bus_send("simple_notification", {"type": "warning", "sticky": True, "title": self.env._("Support visit"), "message": text})
        _logger.info("Support visit: administrators told on screen")

    @api.model
    def _open_visit_for(self, token):
        visit = self.sudo().search([("state", "=", "open"), ("ends_at", ">", fields.Datetime.now())])
        return visit.filtered(lambda v: token_matches(token, v.token_hash))[:1]


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
            visit.sudo().write({"logins": visit.logins + 1})
            self.env["ea.firm.support.visit"]._log("support-login")
            return {"uid": self.env.user.id, "auth_method": "ea_support_visit", "mfa": "skip"}
        if self.env.user.login == SUPPORT_LOGIN:
            raise AccessDenied()
        return super()._check_credentials(credential, env)


class IrHttpSupport(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _authenticate(cls, endpoint):
        """Outside an open visit, a support session ends at its next request."""
        session = request.session
        if request.db and session.uid and session.get("login") == SUPPORT_LOGIN:
            env = request.env(su=True)
            if not env["ea.firm.support.visit"].search_count([("state", "=", "open"), ("ends_at", ">", fields.Datetime.now())]):
                session.logout(keep_db=True)
        return super()._authenticate(endpoint)


class ResConfigSettingsSupport(models.TransientModel):
    _inherit = "res.config.settings"

    support_visit_requires_approval = fields.Boolean(
        "A support visit waits for my approval", config_parameter=PARAM_APPROVAL,
        help="When ticked, the operator cannot sign in until the firm's administrator approves the visit.",
    )
