"""Each client firm's own email, set from the console (owner's ruling of 2026-11-17).

The operator enters the firm's mailbox settings on the firm's page. The console never reaches a firm's
server (tests/test_no_firm_data.py): the settings travel the way every other request does, in the signed
answer to the firm's next heartbeat, once. On the firm's server, root's firm-mail-server checks them again,
saves the server switched off, tests the connection without sending anything, and switches sending on only
if the test passed. The next heartbeat brings back a reference and one word, which this page says in
plain language.

What the console keeps: who asked, when, the server, port, encryption, username and sender, and the
answer. Never the password: it waits encrypted in a file outside the database (services/mail_handoff.py)
until the heartbeat answer takes it, and is erased then, or after HANDOFF_HOURS at most.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import mail_handoff, mail_settings
from ..services.messages import _
from .i18n import t

_logger = logging.getLogger(__name__)

# Long enough for a firm still being installed (20 to 45 minutes) to go live and collect its settings.
HANDOFF_HOURS = 6
# A form's password the operator typed and never sent.
FORM_HOURS = 2
_KEY_CONTEXT = b"ea-platform-mail-handoff-v1"
OPEN_STATES = ("provisioning", "active")


class PlatformFirm(models.Model):
    _inherit = "platform.firm"

    mail_request_state = fields.Selection(
        mail_settings.STATES, "Email", default="none", required=True, readonly=True, copy=False,
    )
    mail_request_message = fields.Text("What it means", compute="_compute_mail_request_message")
    mail_request_action = fields.Selection(
        [("set", "Settings sent"), ("off", "Switch sending off")], "Last request", readonly=True, copy=False,
    )
    mail_request_ref = fields.Char("Request reference", readonly=True, copy=False)
    mail_request_summary = fields.Char(
        "Settings sent", readonly=True, copy=False,
        help="Server, port, encryption, username and sender address. The password is never kept by the console.",
    )
    # The same, field by field, so that the form opens on what was last sent. Never the password.
    mail_request_host = fields.Char("Mail server", readonly=True, copy=False)
    mail_request_port = fields.Integer("Port", readonly=True, copy=False)
    mail_request_encryption = fields.Selection(mail_settings.ENCRYPTION_CHOICES, "Encryption", readonly=True, copy=False)
    mail_request_user = fields.Char("Username", readonly=True, copy=False)
    mail_request_sender = fields.Char("Sender address", readonly=True, copy=False)
    mail_request_at = fields.Datetime("Asked on", readonly=True, copy=False)
    mail_request_by = fields.Many2one("res.users", "Asked by", readonly=True, copy=False)
    mail_request_delivered_at = fields.Datetime("Collected by the firm's server on", readonly=True, copy=False)
    mail_request_answered_at = fields.Datetime("Answer received on", readonly=True, copy=False)

    @api.depends("mail_request_state")
    @api.depends_context("lang")
    def _compute_mail_request_message(self):
        for firm in self:
            firm.mail_request_message = t(self.env, mail_settings.MESSAGES[firm.mail_request_state or "none"])

    # ------------------------------------------------------------------ the waiting file

    @api.model
    def _mail_folder(self):
        return self.env["ir.config_parameter"].sudo().get_param(mail_handoff.FOLDER_PARAM) or mail_handoff.FOLDER_DEFAULT

    @api.model
    def _mail_cipher(self):
        """Opens the waiting files. Its key comes from the database's own secret, never stored with them."""
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret") or ""
        if not secret:
            raise UserError(t(self.env, _("The console has no database secret: tell the developer.")))
        digest = hmac.new(secret.encode("utf-8"), _KEY_CONTEXT, hashlib.sha256).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    @api.model
    def _mail_seal(self, name, data):
        try:
            mail_handoff.store(self._mail_folder(), name, self._mail_cipher().encrypt(json.dumps(data).encode("utf-8")))
        except (OSError, ValueError):
            raise UserError(t(self.env, _(
                "The console could not keep the password until the firm's server collects it (its folder cannot be "
                "written). Nothing was sent. Tell the developer."))) from None

    @api.model
    def _mail_unseal(self, raw):
        if raw is None:
            return None
        try:
            data = json.loads(self._mail_cipher().decrypt(raw).decode("utf-8"))
        except (InvalidToken, ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    # ------------------------------------------------------------------ the operator's requests

    def _mail_check_open(self):
        if self.state not in OPEN_STATES:
            raise UserError(t(self.env, _("Email settings go only to a firm that is live or being set up.")))

    def _mail_send_settings(self, values, user=None):
        """Checks the settings, keeps them out of the database until the firm's server collects them,
        and logs who asked, without the password."""
        self.ensure_one()
        firm = self.sudo()
        firm._mail_check_open()
        problems = mail_settings.errors(values)
        if problems:
            lines = [t(self.env, message) for messages in problems.values() for message in messages]
            raise UserError("\n".join(lines))
        settings = mail_settings.settings(values)
        ref = secrets.token_hex(8)
        firm._mail_seal(mail_handoff.firm_name(firm.slug), {"ref": ref, **settings})
        summary = mail_settings.summary(values)
        firm.write({
            "mail_request_state": "waiting",
            "mail_request_action": "set",
            "mail_request_ref": ref,
            "mail_request_summary": summary,
            "mail_request_host": settings["host"],
            "mail_request_port": settings["port"],
            "mail_request_encryption": settings["encryption"],
            "mail_request_user": settings["user"] or False,
            "mail_request_sender": settings["from"],
            "mail_request_at": fields.Datetime.now(),
            "mail_request_by": (user or self.env.user).id,
            "mail_request_delivered_at": False,
            "mail_request_answered_at": False,
        })
        self.env["platform.log"]._record(
            _("Email settings sent to the firm's server"), firm, summary, user=user or self.env.user,
        )
        return ref

    def _mail_switch_off(self, user=None):
        self.ensure_one()
        firm = self.sudo()
        if firm.state != "active":
            raise UserError(t(self.env, _("Sending can be switched off only on a live firm.")))
        mail_handoff.discard(self._mail_folder(), mail_handoff.firm_name(firm.slug))
        firm.write({
            "mail_request_state": "waiting",
            "mail_request_action": "off",
            "mail_request_ref": secrets.token_hex(8),
            "mail_request_at": fields.Datetime.now(),
            "mail_request_by": (user or self.env.user).id,
            "mail_request_delivered_at": False,
            "mail_request_answered_at": False,
        })
        self.env["platform.log"]._record(_("Email: switching sending off asked"), firm, user=user or self.env.user)

    def action_mail_switch_off(self):
        self.ensure_one()
        self._mail_switch_off(self.env.user)
        self._mail_simulate_answer()
        return True

    def _mail_simulate_answer(self):
        """A simulation firm answers at once: one heartbeat collects the request, the next reports."""
        firm = self.sudo()
        if firm.is_simulation and firm.state == "active" and firm.mail_request_state == "waiting":
            firm._simulate_heartbeat()
            firm._simulate_heartbeat()

    # ------------------------------------------------------------------ heartbeat

    def _heartbeat_answer(self):
        """Adds the email request, once, to a live firm's answer. Taken from its file, then erased."""
        answer = super()._heartbeat_answer()
        firm = self.sudo()
        if firm.state == "active" and firm.mail_request_state == "waiting" and not firm.mail_request_delivered_at:
            request = firm._mail_take_request()
            if request:
                answer["mail_request"] = request
                firm.write({"mail_request_delivered_at": fields.Datetime.now()})
        return answer

    def _mail_take_request(self):
        self.ensure_one()
        if self.mail_request_action == "off":
            return {"ref": self.mail_request_ref, "action": "off"}
        data = self._mail_unseal(mail_handoff.take(self._mail_folder(), mail_handoff.firm_name(self.slug)))
        keys = {"ref", "host", "port", "encryption", "user", "password", "from"}
        if not data or set(data) != keys or data["ref"] != self.mail_request_ref:
            self._mail_close("expired")
            return None
        return {**data, "action": "set"}

    def _apply_figures(self, figures, timestamp):
        result = super()._apply_figures(figures, timestamp)
        ref, word = figures.get("mail_request_ref"), figures.get("mail_request_result")
        if ref and word and ref == self.mail_request_ref and self.mail_request_state == "waiting":
            self._mail_close(word)
        return result

    def _mail_close(self, state):
        self.ensure_one()
        self.sudo().write({"mail_request_state": state, "mail_request_answered_at": fields.Datetime.now()})
        self.env["platform.log"]._record(_("Email: the firm's server answered"), self, mail_settings.MESSAGES[state])

    def _simulate_heartbeat(self, release=None, **changes):
        """A simulation firm obeys: the settings it collected pass their test, a switch-off switches off."""
        self.ensure_one()
        firm = self.sudo()
        if firm.is_simulation and firm.mail_request_ref:
            if firm.mail_request_state == "waiting" and firm.mail_request_delivered_at:
                changes.setdefault("mail_request_ref", firm.mail_request_ref)
                changes.setdefault("mail_request_result", "on" if firm.mail_request_action == "set" else "off")
            on = changes.get("mail_request_result", firm.mail_request_state) == "on"
            if firm.state == "active":
                changes.setdefault("mail_enabled", on)
        return super()._simulate_heartbeat(release=release, **changes)

    # ------------------------------------------------------------------ clean-up

    @api.model
    def _cron_watch(self):
        result = super()._cron_watch()
        self._mail_expire()
        return result

    @api.model
    def _mail_expire(self):
        """Nothing waits for ever: a request not collected, or not answered, is closed and its file erased."""
        limit = fields.Datetime.now() - timedelta(hours=HANDOFF_HOURS)
        folder = self._mail_folder()
        for firm in self.sudo().search([("mail_request_state", "=", "waiting"), ("mail_request_at", "<", limit)]):
            mail_handoff.discard(folder, mail_handoff.firm_name(firm.slug))
            firm._mail_close("no_answer" if firm.mail_request_delivered_at else "expired")
        # Files no request points to any more (a form closed without sending, a creation undone).
        erased = mail_handoff.sweep(folder, FORM_HOURS * 3600, prefix="form-")
        erased += mail_handoff.sweep(folder, HANDOFF_HOURS * 3600, prefix="firm-")
        if erased:
            _logger.info("Email hand-over: %s old file(s) erased", len(erased))

    def _drop_console_key(self):
        """A destroyed firm's waiting settings go with its maintenance key."""
        for firm in self.sudo():
            mail_handoff.discard(self._mail_folder(), mail_handoff.firm_name(firm.slug))
        return super()._drop_console_key()
