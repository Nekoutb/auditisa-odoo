"""Each client firm's platform email address, support@<slug>.cm-ea.com (owner's request of 2026-11-17).

The console makes the address at MailerSend and its DNS records at Cloudflare (services/platform_mail.py),
waits for MailerSend's domain check, makes an SMTP user, and hands its settings to the firm's server the
way the "Email for this firm" screen does (models/firm_mail.py): once, in the signed answer to the firm's
next heartbeat, the password never written to the database. The firm's server tests them and switches
sending on only if the test passed; its answer closes the request here, and this page says it.

A problem with email never stops a firm's provisioning: the step records it on the firm's page, and
the console's own five-minute watch carries on with the checks. What the console keeps: the domain, its
MailerSend and DNS references, the state and the last message. Never a token, never the SMTP password.
"""

import json
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import mail_settings, platform_mail
from ..services.messages import _, dumps, dumps_list
from ..services.provider import ProviderError
from .i18n import read, t

_logger = logging.getLogger(__name__)

OPEN_STATES = ("provisioning", "active")
# Settings not collected in time (a long install) are sent again with a new password, this many times.
MAX_RENEWALS = 3
# The provisioning step asks for a retry this many times; after that the watch carries on alone.
STEP_RETRIES = 2
MAIL_CHOICES = [
    ("platform", "AuditISA sends for this firm (platform address)"),
    ("own", "The firm's own mailbox"),
    ("none", "No email for now"),
]


class PlatformFirm(models.Model):
    _inherit = "platform.firm"

    mail_choice = fields.Selection(MAIL_CHOICES, "How the firm sends email", default="none", required=True,
                                   readonly=True, copy=False)
    pmail_state = fields.Selection(platform_mail.STATES, "Platform address", default="none", required=True,
                                   readonly=True, copy=False)
    pmail_message = fields.Text("What it means", compute="_compute_pmail_text")
    pmail_status = fields.Char("Email", compute="_compute_pmail_text")
    pmail_problem_raw = fields.Text("Last problem (source)", readonly=True, copy=False)
    pmail_problem = fields.Text("Last problem", compute="_compute_pmail_text")
    pmail_domain = fields.Char("Sending domain", readonly=True, copy=False)
    pmail_sender = fields.Char("Sending address", readonly=True, copy=False)
    pmail_reply_to = fields.Char("Replies go to", readonly=True, copy=False)
    pmail_verified = fields.Boolean("Domain verified by MailerSend", readonly=True, copy=False)
    pmail_domain_ref = fields.Char("MailerSend domain reference", readonly=True, copy=False)
    pmail_user_ref = fields.Char("MailerSend SMTP user reference", readonly=True, copy=False)
    pmail_login = fields.Char("SMTP username", readonly=True, copy=False)
    pmail_dns_raw = fields.Text("DNS records written", readonly=True, copy=False)
    pmail_renew = fields.Boolean("New password to make", readonly=True, copy=False)
    pmail_renewals = fields.Integer("Settings sent again", readonly=True, copy=False)
    pmail_tries = fields.Integer("Checks so far", readonly=True, copy=False)
    pmail_started_at = fields.Datetime("Asked on", readonly=True, copy=False)
    pmail_checked_at = fields.Datetime("Last checked on", readonly=True, copy=False)
    pmail_next_check_at = fields.Datetime("Next check", readonly=True, copy=False)
    pmail_request_ref = fields.Char("Request reference", readonly=True, copy=False)
    pmail_test_raw = fields.Text("Last test email (source)", readonly=True, copy=False)
    pmail_test = fields.Text("Last test email", compute="_compute_pmail_text")
    pmail_test_at = fields.Datetime("Last test email on", readonly=True, copy=False)

    @api.depends("pmail_state", "pmail_sender", "pmail_problem_raw", "pmail_test_raw", "mail_choice")
    @api.depends_context("lang")
    def _compute_pmail_text(self):
        for firm in self:
            state = firm.pmail_state or "none"
            firm.pmail_message = t(self.env, platform_mail.MESSAGES[state])
            firm.pmail_problem = read(self.env, firm.pmail_problem_raw)
            firm.pmail_test = read(self.env, firm.pmail_test_raw)
            if state == "on":
                status = _("Sending is on, from %(address)s", address=firm.pmail_sender)
            elif state in ("setting_up", "verifying", "sending"):
                status = _("Being set up: %(address)s", address=firm.pmail_sender)
            elif state == "problem":
                status = _("Needs attention: %(address)s", address=firm.pmail_sender)
            elif firm.mail_choice == "own":
                status = _("The firm's own mailbox")
            else:
                status = _("No email for now")
            firm.pmail_status = t(self.env, status)

    # ------------------------------------------------------------------ state kept between passes

    def _pmail_state_dict(self):
        self.ensure_one()
        state = {"domain": self.pmail_domain}
        if self.pmail_domain_ref:
            state["domain_id"] = self.pmail_domain_ref
        dns = json.loads(self.pmail_dns_raw) if self.pmail_dns_raw else []
        if dns:
            state["dns"] = dns
        if self.pmail_verified:
            state["verified"] = True
        if self.pmail_user_ref:
            state["smtp_user_id"] = self.pmail_user_ref
            state["smtp_username"] = self.pmail_login
        return state

    def _pmail_save_state(self, state):
        self.sudo().write({
            "pmail_domain_ref": state.get("domain_id") or False,
            "pmail_dns_raw": json.dumps(state["dns"]) if state.get("dns") else False,
            "pmail_verified": bool(state.get("verified")),
            "pmail_user_ref": state.get("smtp_user_id") or False,
            "pmail_login": state.get("smtp_username") or False,
        })

    def _pmail_problem(self, message):
        self.sudo().write({"pmail_state": "problem", "pmail_problem_raw": dumps(message), "pmail_next_check_at": False})
        self.env["platform.log"]._record(_("Platform email address: problem"), self, message)

    # ------------------------------------------------------------------ starting

    def _pmail_refusal(self):
        """Why this firm cannot be given a platform address now, or None."""
        self.ensure_one()
        if self.state not in OPEN_STATES:
            return _("A platform address goes only to a firm that is live or being set up.")
        if not self.env["platform.services"]._mail_ready():
            return _("The sending service for firms is not set up: see Platform > Settings, "
                     "and docs/runbook/PLATFORM-EMAIL.md.")
        return None

    def _pmail_require_operator(self):
        if not self.env.su and not self.env.user.has_group("ea_platform_admin.group_platform_operator"):
            raise AccessError(t(self.env, _("Only an operator can do this.")))

    def _pmail_start(self, user=None, raise_retryable=False):
        """Makes the address (or carries on with it). Idempotent."""
        self.ensure_one()
        firm = self.sudo()
        refusal = firm._pmail_refusal()
        if refusal:
            raise UserError(t(self.env, refusal))
        if firm.pmail_state in ("sending", "on"):
            return
        config = self.env["platform.services"]._mail_config()
        domain = firm.pmail_domain or platform_mail.subdomain(firm.slug, config["parent"])
        firm.write({
            "mail_choice": "platform",
            "pmail_state": "setting_up",
            "pmail_domain": domain,
            "pmail_sender": platform_mail.sender(config["local_part"], domain),
            "pmail_reply_to": platform_mail.reply_to(config["reply_to_policy"], firm.contact_email) or False,
            "pmail_problem_raw": False,
            "pmail_tries": 0,
            "pmail_renewals": 0,
            "pmail_started_at": fields.Datetime.now(),
            "pmail_next_check_at": fields.Datetime.now(),
        })
        self.env["platform.log"]._record(_("Platform email address asked"), firm, firm.pmail_sender, user=user or self.env.user)
        firm._pmail_advance(raise_retryable=raise_retryable)

    def action_pmail_give(self):
        self.ensure_one()
        self._pmail_require_operator()
        self._pmail_start(self.env.user)
        return True

    def action_pmail_check_now(self):
        self.ensure_one()
        self._pmail_require_operator()
        firm = self.sudo()
        if firm.pmail_state == "problem":
            refusal = firm._pmail_refusal()
            if refusal:
                raise UserError(t(self.env, refusal))
            firm.write({"pmail_state": "setting_up", "pmail_problem_raw": False, "pmail_tries": 0,
                        "pmail_started_at": fields.Datetime.now()})
        firm._pmail_advance()
        return True

    # ------------------------------------------------------------------ one pass

    def _pmail_advance(self, raise_retryable=False):
        """One pass of services/platform_mail.setup(). Never raises, unless asked to for a temporary fault."""
        self.ensure_one()
        firm = self.sudo()
        if firm.pmail_state not in ("setting_up", "verifying"):
            return firm.pmail_state
        services = self.env["platform.services"]
        try:
            mailersend, zone = services._mail_outside()
        except ProviderError as error:
            firm._pmail_problem(error.message)
            return firm.pmail_state
        state = firm._pmail_state_dict()
        now = fields.Datetime.now()
        try:
            if firm.pmail_renew:
                platform_mail.renew_smtp_user(mailersend, state)
                firm.pmail_renew = False
            phase, credentials = platform_mail.setup(mailersend, zone, state)
            if phase == "done":
                # The SMTP user exists but its settings never reached the firm: a new password is needed.
                platform_mail.renew_smtp_user(mailersend, state)
                phase, credentials = platform_mail.setup(mailersend, zone, state)
        except ProviderError as error:
            firm._pmail_save_state(state)
            services._save_mail_dry_state(mailersend, zone)
            if not error.retryable:
                firm._pmail_problem(error.message)
                return firm.pmail_state
            tries = firm.pmail_tries + 1
            firm.write({
                "pmail_tries": tries, "pmail_checked_at": now, "pmail_problem_raw": dumps(error.message),
                "pmail_next_check_at": now + timedelta(minutes=platform_mail.next_check_minutes(tries)),
            })
            if raise_retryable:
                raise
            return firm.pmail_state
        firm._pmail_save_state(state)
        services._save_mail_dry_state(mailersend, zone)
        firm.pmail_checked_at = now
        if phase == "verifying":
            tries = firm.pmail_tries + 1
            started = firm.pmail_started_at or now
            if now - started > timedelta(hours=platform_mail.VERIFY_GIVE_UP_HOURS):
                firm._pmail_problem(_(
                    "MailerSend has not verified %(domain)s after %(hours)s hours. Check its DNS records at Cloudflare "
                    "(docs/runbook/PLATFORM-EMAIL.md), then use \"Check again now\".",
                    domain=firm.pmail_domain, hours=platform_mail.VERIFY_GIVE_UP_HOURS))
            else:
                firm.write({
                    "pmail_state": "verifying", "pmail_tries": tries, "pmail_problem_raw": False,
                    "pmail_next_check_at": now + timedelta(minutes=platform_mail.next_check_minutes(tries)),
                })
            return firm.pmail_state
        firm._pmail_deliver(credentials)
        return firm.pmail_state

    def _pmail_deliver(self, credentials):
        """The SMTP settings go to the firm's server the "Email for this firm" way. The password is not kept."""
        firm = self.sudo()
        values = {**credentials, "sender": firm.pmail_sender}
        try:
            ref = firm.with_context(ea_platform_mail=True)._mail_send_settings(values)
        except UserError as error:
            firm._pmail_problem(_("The settings could not be sent to the firm's server: %(reason)s",
                                  reason=str(error.args[0] if error.args else error)))
            return
        firm.write({
            "pmail_state": "sending", "pmail_request_ref": ref, "pmail_problem_raw": False,
            "pmail_next_check_at": False,
        })
        self.env["platform.log"]._record(_("Platform email address verified: settings sent to the firm's server"),
                                         firm, firm.pmail_sender)
        firm._mail_simulate_answer()

    # ------------------------------------------------------------------ the firm's answer

    def _mail_send_settings(self, values, user=None):
        """The operator sending the firm's own mailbox settings: the platform address is no longer used."""
        ref = super()._mail_send_settings(values, user=user)
        if not self.env.context.get("ea_platform_mail"):
            self.sudo().write({"mail_choice": "own"})
        return ref

    def _mail_close(self, state):
        super()._mail_close(state)
        firm = self.sudo()
        if firm.pmail_state != "sending" or firm.pmail_request_ref != firm.mail_request_ref:
            return
        if state == "on":
            firm.write({"pmail_state": "on", "pmail_problem_raw": False})
            self.env["platform.log"]._record(_("Platform email address: sending is on"), firm, firm.pmail_sender)
        elif state in ("expired", "no_answer") and firm.pmail_renewals < MAX_RENEWALS:
            # Not collected in time (a long install): a new password, sent again at the next watch.
            firm.write({
                "pmail_state": "setting_up", "pmail_renew": True, "pmail_renewals": firm.pmail_renewals + 1,
                "pmail_next_check_at": fields.Datetime.now(),
            })
        else:
            firm._pmail_problem(mail_settings.MESSAGES[state])

    def _heartbeat_answer(self):
        """The address replies go to, at every heartbeat (empty: none). A firm's older agent ignores it."""
        answer = super()._heartbeat_answer()
        firm = self.sudo()
        if firm.state == "active":
            answer["mail_reply_to"] = (firm.pmail_reply_to or "") if firm.pmail_state in ("sending", "on") else ""
        return answer

    # ------------------------------------------------------------------ the watch

    @api.model
    def _cron_watch(self):
        result = super()._cron_watch()
        self._pmail_watch()
        return result

    @api.model
    def _pmail_watch(self):
        due = self.sudo().search([
            ("pmail_state", "in", ("setting_up", "verifying")), ("state", "in", OPEN_STATES),
            "|", ("pmail_next_check_at", "=", False), ("pmail_next_check_at", "<=", fields.Datetime.now()),
        ])
        for firm in due:
            try:
                firm._pmail_advance()
            except Exception:  # noqa: BLE001  one firm's problem must not stop the others
                _logger.exception("Platform email address of firm %s: check failed", firm.id)

    # ------------------------------------------------------------------ provisioning

    def _pmail_provision_step(self):
        """The provisioning step "Set up the firm's email". Never fails the firm."""
        self.ensure_one()
        firm = self.sudo()
        if firm.mail_choice != "platform" or firm.pmail_state in ("sending", "on", "problem"):
            return
        if firm.pmail_state == "none":
            refusal = firm._pmail_refusal()
            if refusal:
                firm._pmail_problem(refusal)
                return
            try:
                firm._pmail_start(raise_retryable=True)
            except UserError as error:
                firm._pmail_problem(_("Not started: %(reason)s", reason=str(error.args[0] if error.args else error)))
            return
        firm._pmail_advance(raise_retryable=firm.pmail_tries < STEP_RETRIES)

    def _pmail_undo(self):
        """Removes everything made for the address. ProviderError naming what stays, if something does."""
        self.ensure_one()
        firm = self.sudo()
        if not (firm.pmail_domain or firm.pmail_domain_ref):
            return
        leftovers = firm._pmail_remove_resources()
        if leftovers:
            raise ProviderError(leftovers[0])

    def _pmail_remove_resources(self):
        firm = self.sudo()
        services = self.env["platform.services"]
        try:
            mailersend, zone = services._mail_outside()
        except ProviderError as error:
            return [error.message]
        state = firm._pmail_state_dict()
        leftovers = platform_mail.remove(mailersend, zone, state)
        services._save_mail_dry_state(mailersend, zone)
        if leftovers:
            firm._pmail_save_state(state)
            firm.write({"pmail_state": "problem", "pmail_problem_raw": dumps_list(leftovers)})
            return leftovers
        firm.write({
            "pmail_state": "none", "pmail_domain": False, "pmail_sender": False, "pmail_reply_to": False,
            "pmail_verified": False, "pmail_domain_ref": False, "pmail_user_ref": False, "pmail_login": False,
            "pmail_dns_raw": False, "pmail_renew": False, "pmail_tries": 0, "pmail_next_check_at": False,
            "pmail_request_ref": False, "pmail_problem_raw": False,
        })
        return []

    def action_pmail_remove(self):
        """Removes the platform address: SMTP user, DNS records and domain. The view asks to confirm first."""
        self.ensure_one()
        self._pmail_require_operator()
        firm = self.sudo()
        sender = firm.pmail_sender
        in_use = firm.mail_choice == "platform" and firm.mail_request_sender == sender
        leftovers = firm._pmail_remove_resources()
        if leftovers:
            self.env["platform.log"]._record(_("Platform email address: removal INCOMPLETE"), firm,
                                             leftovers[0], user=self.env.user)
            return {
                "type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": t(self.env, _("Removal incomplete")), "type": "danger", "sticky": True,
                           "message": "\n".join(t(self.env, item) for item in leftovers)},
            }
        if firm.mail_choice == "platform":
            firm.mail_choice = "none"
        self.env["platform.log"]._record(_("Platform email address removed"), firm, sender or "", user=self.env.user)
        if in_use and firm.state == "active" and firm.mail_request_state in ("on", "waiting"):
            # Its SMTP user is gone: the firm's server could send nothing. Sending is switched off there.
            firm._mail_switch_off(self.env.user)
            firm._mail_simulate_answer()
        return True

    # ------------------------------------------------------------------ the test email

    def _pmail_send_test(self, address, practice=False, user=None):
        """Sends one test email through MailerSend from this firm's platform address. Returns the message
        shown to the operator, and keeps it on the firm's page. The email carries the firm's name only."""
        self.ensure_one()
        self._pmail_require_operator()
        firm = self.sudo()
        address = (address or "").strip().lower()
        if not platform_mail.EMAIL_RE.match(address):
            raise UserError(t(self.env, _("Type one email address, for example owner@example.com.")))
        if practice:
            allowlist = platform_mail.parse_allowlist(self.env["ir.config_parameter"].sudo().get_param(
                "ea_platform.practice_mail_allowlist") or "")[0]
            if not platform_mail.allowed(address, allowlist):
                raise UserError(t(self.env, _(
                    "Not sent: this address is not on the list \"Practice spaces may email only these addresses\" "
                    "(Platform > Settings).")))
        if not (firm.pmail_verified and firm.pmail_sender):
            raise UserError(t(self.env, _("This firm's platform address is not verified yet: nothing was sent.")))
        services = self.env["platform.services"]
        # The firm's name and nothing else: no client data ever goes into an email from here.
        subject = "AuditISA: test email" + (" (practice space)" if practice else "")
        text = (
            "This is a test email from AuditISA for %(name)s. It proves that this address can send. "
            "No reply is needed.\n\n"
            "Ceci est un e-mail de test d'AuditISA pour %(name)s. Il prouve que cette adresse peut envoyer. "
            "Aucune r\u00e9ponse n'est n\u00e9cessaire.\n"
        ) % {"name": firm.name}
        try:
            mailersend, zone = services._mail_outside()
            mailersend.send_test(firm.pmail_sender, firm.name, address, firm.pmail_reply_to or "", subject, text)
            services._save_mail_dry_state(mailersend, zone)
            result = _("MailerSend accepted the test email for %(address)s. It usually arrives within a minute or "
                       "two; if not, look in the spam folder.", address=address)
        except ProviderError as error:
            result = _("Not sent: %(reason)s", reason=error.message)
        firm.write({"pmail_test_raw": dumps(result), "pmail_test_at": fields.Datetime.now()})
        self.env["platform.log"]._record(
            _("Test email"), firm, _("To an address at %(domain)s", domain=address.split("@", 1)[1]),
            user=user or self.env.user,
        )
        return t(self.env, result)
