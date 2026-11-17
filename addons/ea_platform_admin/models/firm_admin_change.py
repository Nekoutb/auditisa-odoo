"""Changing or adding a firm's administrator from the console (owner's request of 2026-11-18).

The firm's administrator is, at first, the contact person given at onboarding. On the firm's page an
operator can now:

- change the contact's name, email and phone (each change is in the platform log: who, what, old and new);
- ask for a firm administrator to be added, or to replace the current one(s).

The request is queued here and goes to the firm's server in the signed answer to its next heartbeat, the
way the email settings do (models/firm_mail.py): nothing over SSH, the console never reaches the server.
The firm's server makes the change (ea_audit_timesheet/models/firm_admin.py) and its next heartbeat brings
back the request's reference, one word, and, for a new account, the one-time invitation link. The console
keeps that link only until an operator has seen it once, 72 hours at most, and never logs it.
"""

import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import admin_change
from ..services.messages import _, dumps_list
from .i18n import t

CONTACT_FIELDS = (
    ("contact_name", _("Contact's name")),
    ("contact_email", _("Contact's email")),
    ("contact_phone", _("Contact's phone")),
)
TITLES = {"add": _("Add a firm administrator"), "replace": _("Replace the firm administrator")}


class PlatformFirm(models.Model):
    _inherit = "platform.firm"

    admin_change_state = fields.Selection(
        admin_change.STATES, "Firm administrator", default="none", required=True, readonly=True, copy=False,
    )
    admin_change_message = fields.Text("What it means", compute="_compute_admin_change_message")
    admin_change_action = fields.Selection(admin_change.ACTION_CHOICES, "Last request", readonly=True, copy=False)
    admin_change_name = fields.Char("Person's name", readonly=True, copy=False)
    admin_change_email = fields.Char("Person's email", readonly=True, copy=False)
    admin_change_ref = fields.Char("Request reference", readonly=True, copy=False)
    admin_change_at = fields.Datetime("Asked on", readonly=True, copy=False)
    admin_change_by = fields.Many2one("res.users", "Asked by", readonly=True, copy=False)
    admin_change_delivered_at = fields.Datetime("Collected by the firm's server on", readonly=True, copy=False)
    admin_change_answered_at = fields.Datetime("Answer received on", readonly=True, copy=False)
    # The one-time invitation link the firm's server made. Odoo administrators only; no view shows it.
    admin_link_token = fields.Char("Administrator's link", groups="base.group_system", copy=False)
    admin_link_expires_at = fields.Datetime("The administrator's link expires on", readonly=True, copy=False)
    admin_link_revealed_at = fields.Datetime("Administrator's link shown on", readonly=True, copy=False)
    admin_link_ready = fields.Boolean("Administrator's link available", compute="_compute_admin_link_ready")

    @api.depends("admin_change_state", "admin_change_name", "admin_change_action")
    @api.depends_context("lang")
    def _compute_admin_change_message(self):
        for firm in self:
            state = firm.admin_change_state or "none"
            if state != "done":
                firm.admin_change_message = t(self.env, admin_change.MESSAGES[state])
            elif firm.admin_change_action == "replace":
                firm.admin_change_message = t(self.env, _(
                    "Done: %(name)s is now the firm administrator. The previous firm administrator keeps their "
                    "account, their engagements and all their work, with the Partner role.",
                    name=firm.admin_change_name))
            else:
                firm.admin_change_message = t(self.env, _(
                    "Done: %(name)s is now the firm administrator.", name=firm.admin_change_name))

    @api.depends("admin_link_expires_at", "admin_link_revealed_at")
    def _compute_admin_link_ready(self):
        now = fields.Datetime.now()
        for firm in self:
            firm.admin_link_ready = bool(
                firm.admin_link_expires_at and firm.admin_link_expires_at > now and not firm.admin_link_revealed_at
            )

    # ------------------------------------------------------------------ the contact's details

    def write(self, vals):
        """A change of the contact's name, email or phone is logged: who, what, old and new."""
        watched = [(name, label) for name, label in CONTACT_FIELDS if name in vals]
        before = {firm.id: {name: firm[name] or "" for name, _label in watched} for firm in self} if watched else {}
        result = super().write(vals)
        for firm in self if watched else ():
            changes = [
                _("%(field)s: %(old)s → %(new)s", field=label, old=before[firm.id][name] or "-", new=firm[name] or "-")
                for name, label in watched if (firm[name] or "") != before[firm.id][name]
            ]
            if changes:
                self.env["platform.log"]._record(_("Contact details changed"), firm, dumps_list(changes),
                                                 user=self.env.user)
        return result

    # ------------------------------------------------------------------ the operator's request

    def _admin_change_request(self, action, name, email, user=None):
        """Queues the request for the firm's next heartbeat. Operators only."""
        self.ensure_one()
        self._pmail_require_operator()
        firm = self.sudo()
        if action not in admin_change.ACTIONS:
            raise UserError(t(self.env, _("Choose to add or to replace the firm administrator.")))
        if firm.state != "active":
            raise UserError(t(self.env, _("The firm administrator can be changed only on a live firm.")))
        problems = admin_change.request_errors(name, email, firm.allowed_email_domains)
        if problems:
            raise UserError("\n".join(t(self.env, problem) for problem in problems))
        name, email = admin_change.clean_name(name), admin_change.clean_email(email)
        firm.write({
            "admin_change_state": "waiting",
            "admin_change_action": action,
            "admin_change_name": name,
            "admin_change_email": email,
            "admin_change_ref": secrets.token_hex(8),
            "admin_change_at": fields.Datetime.now(),
            "admin_change_by": (user or self.env.user).id,
            "admin_change_delivered_at": False,
            "admin_change_answered_at": False,
            # A link of an earlier request not shown yet is forgotten: only the latest request counts.
            "admin_link_token": False,
            "admin_link_expires_at": False,
            "admin_link_revealed_at": False,
        })
        asked = (_("Add a firm administrator: %(name)s, %(email)s", name=name, email=email) if action == "add"
                 else _("Replace the firm administrator: %(name)s, %(email)s", name=name, email=email))
        self.env["platform.log"]._record(_("Firm administrator: change asked"), firm, asked, user=user or self.env.user)
        firm._admin_change_simulate_answer()
        return firm.admin_change_ref

    def action_admin_change_open(self):
        """Opens the small form, for "add" or "replace" as the button's context says."""
        self.ensure_one()
        self._pmail_require_operator()
        action = self.env.context.get("admin_change_action")
        if action not in admin_change.ACTIONS:
            raise UserError(t(self.env, _("Choose to add or to replace the firm administrator.")))
        return {
            "type": "ir.actions.act_window",
            "name": t(self.env, TITLES[action]),
            "res_model": "platform.firm.admin.change.wizard",
            "view_mode": "form", "views": [(False, "form")],
            "target": "new",
            "context": {"default_firm_id": self.id, "default_change_action": action},
        }

    def _admin_change_simulate_answer(self):
        """A simulation firm answers at once: one heartbeat collects the request, the next reports."""
        firm = self.sudo()
        if firm.is_simulation and firm.state == "active" and firm.admin_change_state == "waiting":
            firm._simulate_heartbeat()
            firm._simulate_heartbeat()

    # ------------------------------------------------------------------ heartbeat

    def _heartbeat_answer(self):
        """The waiting request, at every heartbeat until the firm answers. The firm's server acts once per reference."""
        answer = super()._heartbeat_answer()
        firm = self.sudo()
        if firm.state == "active" and firm.admin_change_state == "waiting":
            try:
                answer["admin_request"] = admin_change.request(
                    firm.admin_change_ref, firm.admin_change_action, firm.admin_change_name, firm.admin_change_email,
                )
            except ValueError:
                firm._admin_change_close("failed")
                return answer
            if not firm.admin_change_delivered_at:
                firm.write({"admin_change_delivered_at": fields.Datetime.now()})
        return answer

    def _apply_figures(self, figures, timestamp):
        result = super()._apply_figures(figures, timestamp)
        ref, word = figures.get("admin_request_ref"), figures.get("admin_request_result")
        if ref and word and ref == self.admin_change_ref and self.admin_change_state == "waiting":
            self._admin_change_close(word, figures.get("admin_request_link"))
        return result

    def _admin_change_close(self, word, link=None):
        """Records the answer. The link is kept for one showing, never logged."""
        self.ensure_one()
        now = fields.Datetime.now()
        values = {"admin_change_state": word, "admin_change_answered_at": now}
        if word == "done" and link:
            values.update({
                "admin_link_token": link,
                # The firm's server made the link when it collected the request: its 72 hours count from then.
                "admin_link_expires_at": (self.admin_change_delivered_at or now) + timedelta(hours=admin_change.LINK_HOURS),
                "admin_link_revealed_at": False,
            })
        self.sudo().write(values)
        if word == "done":
            detail = _("%(name)s is now the firm administrator", name=self.admin_change_name)
        else:
            detail = admin_change.MESSAGES[word]
        self.env["platform.log"]._record(_("Firm administrator: the firm's server answered"), self, detail)

    def _simulate_heartbeat(self, release=None, **changes):
        """A simulation firm obeys: the person becomes the firm administrator, with a made-up one-time link."""
        self.ensure_one()
        firm = self.sudo()
        if firm.is_simulation and firm.admin_change_state == "waiting" and firm.admin_change_delivered_at:
            changes.setdefault("admin_request_ref", firm.admin_change_ref)
            changes.setdefault("admin_request_result", "done")
            if changes["admin_request_result"] == "done":
                changes.setdefault(
                    "admin_request_link",
                    f"https://{firm.platform_host}/web/signup?db={firm.slug}&token={secrets.token_urlsafe(32)}",
                )
        return super()._simulate_heartbeat(release=release, **changes)

    # ------------------------------------------------------------------ the watch

    @api.model
    def _cron_watch(self):
        result = super()._cron_watch()
        self.sudo().search([
            ("admin_link_expires_at", "<", fields.Datetime.now()), ("admin_link_token", "!=", False),
        ]).write({"admin_link_token": False})
        return result
