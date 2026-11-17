import ipaddress
import smtplib
import socket
import ssl
from urllib.parse import urlencode

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import LazyTranslate

from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.addons.ea_audit_core.services.email_domains import email_domain_allowed, is_valid_email
from odoo.addons.ea_audit_core.services.signoff_rules import TEAM_LADDER, may_hold_partner_seat

from ..services import deadlines
from .common import refuse

_lt = LazyTranslate("ea_audit_timesheet")

ROLES = [
    ("firm_admin", _lt("Firm administrator"), "ea_audit_core.group_firm_admin"),
    ("partner", _lt("Partner"), "ea_audit_core.group_partner"),
    ("manager", _lt("Manager"), "ea_audit_core.group_manager"),
    ("senior", _lt("Senior"), "ea_audit_core.group_senior"),
    ("staff", _lt("Staff"), "ea_audit_core.group_staff"),
    ("eqr_reviewer", _lt("Engagement quality reviewer"), "ea_audit_core.group_eqr_reviewer"),
    ("read_only", _lt("Read only"), "ea_audit_core.group_read_only"),
]
_ROLE_XMLIDS = {key: xmlid for key, _label, xmlid in ROLES}
_ROLE_LABELS = {key: label for key, label, _xmlid in ROLES}
_PLUMBING = ("ea_audit_core.group_writer", "ea_audit_core.group_member")

# How long a link lasts. Either works once: signing in changes the last login date the
# token is signed with (owner, 2026-11-17).
INVITE_LINK_HOURS = 72
PASSWORD_LINK_HOURS = 24

MAIL_PORTS = (25, 465, 587, 2525)
MAIL_ENCRYPTIONS = ("none", "starttls", "ssl")
_STAGING_VALUES = ("1", "True", "true")
_MAIL_SERVER_NAME = "Firm server"


class FirmAdmin(models.AbstractModel):
    """What a firm administrator may do without the technical account, and nothing
    more. Each method checks the caller's firm role, then does this one thing as
    superuser: a firm administrator's own rights on res.users, res.groups, ir.rule
    and ir.mail_server stay Odoo's, that is none."""

    _name = "ea.audit.firm.admin"
    _description = "Firm administrator's screens"

    @api.model
    def _ea_fa_require(self):
        if self.env.user._ea_firm_role() != "firm_admin":
            raise refuse(self.env, "fa-forbidden")

    @api.model
    def _ea_fa_target(self, user_id):
        user = self.env["res.users"].sudo().with_context(active_test=False).browse(int(user_id)).exists()
        if not user or user.share or user.id == self.env.ref("base.user_root").id:
            raise refuse(self.env, "fa-forbidden")
        if user.has_group("base.group_system"):
            raise refuse(self.env, "fa-technical-target")
        return user

    @api.model
    def _ea_fa_role_label(self, role):
        return self.env._(_ROLE_LABELS[role]) if role in _ROLE_LABELS else self.env._("No role")

    @api.model
    def _ea_fa_other_active_admins(self, user):
        group = self.env.ref("ea_audit_core.group_firm_admin")
        return group.sudo().all_user_ids.filtered(lambda u: u.active and u != user)

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    @api.model
    def ea_fa_users(self):
        self._ea_fa_require()
        Users = self.env["res.users"].sudo().with_context(active_test=False)
        rows = []
        for user in Users.search([("share", "=", False), ("id", "!=", self.env.ref("base.user_root").id)], order="active desc, name"):
            technical = user.has_group("base.group_system")
            role = user._ea_firm_role()
            joined = bool(user.login_date)
            rows.append({
                "id": user.id,
                "name": user.name,
                "login": user.login,
                "role": role or "",
                "role_label": self._ea_fa_role_label(role),
                "technical": technical,
                "active": user.active,
                "joined": joined,
                "is_me": user == self.env.user,
                "state_label": self.env._("Deactivated") if not user.active else (self.env._("Active") if joined or technical else self.env._("Invited")),
                "last_login": deadlines.instant_label(user.login_date) if joined else "",
            })
        company = self.env.company.sudo()
        return {
            "mail_on": self._ea_fm_can_send(),
            "users": rows,
            "roles": [{"key": key, "label": self.env._(label)} for key, label, _xmlid in ROLES],
            "domains": company.ea_allowed_email_domains or "",
            "log": self._ea_fa_log_rows(),
            "engagements": self._ea_fa_my_engagements(),
            "team_roles": self._ea_fa_team_roles(),
        }

    @api.model
    def _ea_fa_my_engagements(self):
        """The open engagements the administrator may add someone to: those whose team they
        are on, accepted, as for any team manager. Nobody else's file appears here."""
        seats = self.env["ea.audit.team.member"].sudo().search([
            ("user_id", "=", self.env.user.id), ("state", "=", "accepted"), ("team_role", "in", list(TEAM_LADDER)),
        ])
        engagements = seats.engagement_id.filtered(lambda e: not e._ea_is_archived())
        return [{"id": e.id, "name": e.display_name} for e in engagements.sorted("display_name")]

    @api.model
    def _ea_fa_team_roles(self):
        labels = dict(self.env["ea.audit.team.member"]._fields["team_role"]._description_selection(self.env))
        return [{"key": key, "label": labels.get(key, key)} for key in TEAM_LADDER]

    @api.model
    def _ea_fa_log_rows(self, limit=15):
        kinds = dict(self.env["ea.audit.firm.log"]._fields["kind"]._description_selection(self.env))
        return [
            {
                "id": row.id,
                "kind": kinds.get(row.kind),
                "support": row.kind == "support_login",
                "actor": row.actor_name,
                "target": row.target_name or "",
                "detail": row.detail or "",
                "at": deadlines.instant_label(row.create_date),
            }
            for row in self.env["ea.audit.firm.log"].sudo().search([], limit=limit)
        ]

    @api.model
    def _ea_fa_link(self, user, signup_type="signup"):
        """The way in: a signed, expiring link that sets a password chosen by the
        person. Nobody else, and no e-mail, ever carries a password. Odoo's own token
        (auth_signup), with our validity: an invitation 72 hours, a new password 24."""
        partner = user.partner_id.sudo()
        partner.signup_prepare(signup_type=signup_type)
        hours = PASSWORD_LINK_HOURS if signup_type == "reset" else INVITE_LINK_HOURS
        token = partner._generate_signup_token(expiration=hours)
        route = "reset_password" if signup_type == "reset" else "signup"
        query = urlencode({"db": self.env.cr.dbname, "token": token})
        return "%s/web/%s?%s" % (partner.get_base_url().rstrip("/"), route, query)

    @api.model
    def ea_fa_invite(self, email, name=None, role="staff", engagement_id=None, team_role=None):
        """A new firm user and their invitation link. With an engagement, they are also
        invited to its team by the engagement's own method: that invitation waits for them
        to accept it and confirm their independence. The administrator must be on that
        team, as any team manager."""
        self._ea_fa_require()
        email = (email or "").strip().lower()
        if role not in _ROLE_XMLIDS:
            raise refuse(self.env, "fa-role-invalid")
        if not is_valid_email(email):
            raise refuse(self.env, "fa-email-invalid")
        self.env["ea.audit.engagement"]._ea_assert_member_domain(email)
        engagement = self.env["ea.audit.engagement"]
        if engagement_id:
            team_role = team_role or "staff"
            if team_role not in TEAM_LADDER:
                raise refuse(self.env, "fa-team-role-invalid")
            engagement = engagement.browse(int(engagement_id))
            # the engagement's own checks, before any account exists
            engagement._ea_require_team_manager(team_role)
            engagement._ea_assert_mutable()
        Users = self.env["res.users"].sudo().with_context(active_test=False)
        if Users.search_count([("login", "=", email)]):
            raise refuse(self.env, "fa-user-exists")
        user = Users.with_context(no_reset_password=True, active_test=True).create({
            "name": (name or "").strip() or email,
            "login": email,
            "email": email,
            "group_ids": [(6, 0, [self.env.ref(_ROLE_XMLIDS[role]).id])],
        })
        user._ea_ts_ensure_employee()
        detail = self._ea_fa_role_label(role)
        if engagement:
            engagement.invite_team_member(email, team_role, display_name=user.name)
            detail = self.env._("%(role)s; invited to %(engagement)s", role=detail, engagement=engagement.sudo().display_name)
        self.env["ea.audit.firm.log"]._ea_append("user_invited", user, detail)
        return {
            "user_id": user.id, "link": self._ea_fa_link(user), "hours": INVITE_LINK_HOURS,
            "engagement": engagement.sudo().display_name if engagement else "",
        }

    @api.model
    def ea_fa_link(self, user_id):
        self._ea_fa_require()
        user = self._ea_fa_target(user_id)
        if not user.active:
            raise refuse(self.env, "fa-user-inactive")
        if user.login_date:
            raise refuse(self.env, "fa-already-joined")
        self.env["ea.audit.firm.log"]._ea_append("link_issued", user)
        return {"link": self._ea_fa_link(user), "hours": INVITE_LINK_HOURS}

    @api.model
    def ea_fa_password_link(self, user_id):
        """A new password link for any active firm user, at any time. Shown once to the
        administrator, who hands it over; the person chooses the new password."""
        self._ea_fa_require()
        user = self._ea_fa_target(user_id)
        if not user.active:
            raise refuse(self.env, "fa-user-inactive")
        self.env["ea.audit.firm.log"]._ea_append("password_link_issued", user)
        return {"link": self._ea_fa_link(user, "reset"), "hours": PASSWORD_LINK_HOURS}

    @api.model
    def ea_fa_send_link(self, user_id):
        """Sends the invitation to the person by email, from the firm's own mailbox. Offered only
        while the firm's sending is on (set from the AuditISA console, never from here). The email
        holds a link that sets a password chosen by the person: no password travels."""
        self._ea_fa_require()
        user = self._ea_fa_target(user_id)
        if not user.active:
            raise refuse(self.env, "fa-user-inactive")
        if user.login_date:
            raise refuse(self.env, "fa-already-joined")
        if not self._ea_fm_can_send():
            raise refuse(self.env, "fa-mail-off")
        if not user.email:
            raise refuse(self.env, "fa-email-invalid")
        try:
            # create_user: Odoo's invitation email ("set your password"), not the reset one.
            user.with_context(create_user=1, lang=user.lang or self.env.lang).action_reset_password()
        except (UserError, MailDeliveryException):
            raise refuse(self.env, "fa-mail-failed") from None
        self.env["ea.audit.firm.log"]._ea_append("link_emailed", user)
        return {"sent_to": user.email}

    @api.model
    def ea_fa_set_role(self, user_id, role):
        self._ea_fa_require()
        if role not in _ROLE_XMLIDS:
            raise refuse(self.env, "fa-role-invalid")
        user = self._ea_fa_target(user_id)
        if user == self.env.user:
            raise refuse(self.env, "fa-self")
        current = user._ea_firm_role()
        if current == "firm_admin" and role != "firm_admin" and not self._ea_fa_other_active_admins(user):
            raise refuse(self.env, "fa-last-admin")
        if not may_hold_partner_seat(role) and self._ea_fa_partner_seats(user):
            raise refuse(self.env, "fa-holds-partner-seat")
        self._ea_fa_put_role(user, role)
        self.env["ea.audit.firm.log"]._ea_append(
            "role_changed", user, "%s > %s" % (self._ea_fa_role_label(current), self._ea_fa_role_label(role)),
        )
        return True

    @api.model
    def _ea_fa_put_role(self, user, role):
        """The one firm role `role` in place of any other. Engagement seats and work are not touched."""
        firm_groups = [self.env.ref(xmlid).id for xmlid in (*_ROLE_XMLIDS.values(), *_PLUMBING)]
        user.sudo().write({
            "group_ids": [(3, gid) for gid in firm_groups] + [(4, self.env.ref(_ROLE_XMLIDS[role]).id)],
        })

    # ------------------------------------------------------------------
    # Asked by the AuditISA console (owner, 2026-11-18): "Add a firm administrator" and "Replace the
    # firm administrator". The request comes in the signed answer to this server's heartbeat; the
    # agent (ea_audit_firm_agent) calls this once per request and reports the result.
    # ------------------------------------------------------------------

    @api.model
    def _ea_fa_from_platform(self, action, name, email):
        """Returns (result, link): result is one word for the console, link a one-time invitation link
        (72 hours, one use) when the person has never signed in, else None. Never logged.

        "add": the person gets the firm administrator role; an account is made if none has this address.
        "replace": the same, then every other firm administrator becomes Partner. They keep their account,
        their engagement seats and all their work: nobody is deactivated and nothing is deleted."""
        if not self.env.su:
            raise refuse(self.env, "fa-forbidden")
        if action not in ("add", "replace"):
            return "failed", None
        email = (email or "").strip().lower()
        if not is_valid_email(email):
            return "email", None
        if not email_domain_allowed(email, self.env["res.company"]._ea_allowed_domains()):
            return "domain", None
        platform = self.env.ref("base.user_root")
        platform_name = self.env._("AuditISA platform")
        Log = self.env["ea.audit.firm.log"]
        Users = self.env["res.users"].sudo().with_context(active_test=False)
        user = (Users.search([("login", "=ilike", email)], order="id", limit=1)
                or Users.search([("email", "=ilike", email), ("share", "=", False)], order="id", limit=1))
        if user and (user.share or user == platform):
            return "account", None
        admin_label = self._ea_fa_role_label("firm_admin")
        if not user:
            user = Users.with_context(no_reset_password=True, active_test=True).create({
                "name": (name or "").strip() or email,
                "login": email,
                "email": email,
                "group_ids": [(6, 0, [self.env.ref(_ROLE_XMLIDS["firm_admin"]).id])],
            })
            user._ea_ts_ensure_employee()
            Log._ea_append("platform_admin_added", user, admin_label, actor=platform, actor_name=platform_name)
        else:
            before = user._ea_firm_role()
            if not user.active:
                user.active = True
            if before != "firm_admin":
                self._ea_fa_put_role(user, "firm_admin")
            Log._ea_append("platform_admin_added", user, "%s > %s" % (self._ea_fa_role_label(before), admin_label),
                           actor=platform, actor_name=platform_name)
        if action == "replace":
            partner_label = self._ea_fa_role_label("partner")
            for previous in self._ea_fa_other_active_admins(user).filtered(lambda u: not u.share and u != platform):
                self._ea_fa_put_role(previous, "partner")
                Log._ea_append("platform_admin_removed", previous, "%s > %s" % (admin_label, partner_label),
                               actor=platform, actor_name=platform_name)
        return "done", (None if user.login_date else self._ea_fa_link(user))

    @api.model
    def _ea_fa_partner_seats(self, user):
        return self.env["ea.audit.team.member"].sudo().search_count([
            ("user_id", "=", user.id), ("team_role", "=", "partner"), ("state", "!=", "declined"),
        ])

    @api.model
    def ea_fa_set_active(self, user_id, active):
        self._ea_fa_require()
        user = self._ea_fa_target(user_id)
        active = bool(active)
        if user == self.env.user:
            raise refuse(self.env, "fa-self")
        if active == user.active:
            return True
        if not active:
            if user._ea_firm_role() == "firm_admin" and not self._ea_fa_other_active_admins(user):
                raise refuse(self.env, "fa-last-admin")
            if self._ea_fa_partner_seats(user):
                raise refuse(self.env, "fa-holds-partner-seat")
        user.active = active
        self.env["ea.audit.firm.log"]._ea_append("user_reactivated" if active else "user_deactivated", user)
        return True

    @api.model
    def ea_fa_set_domains(self, raw):
        self._ea_fa_require()
        domains = self.env["res.company"].ea_set_allowed_domains(raw)
        self.env["ea.audit.firm.log"]._ea_append("domains_changed", detail=", ".join(domains) or self.env._("No restriction"))
        return domains

    # ------------------------------------------------------------------
    # Internal projects
    # ------------------------------------------------------------------

    @api.model
    def ea_fa_projects(self):
        self._ea_fa_require()
        Project = self.env["project.project"].sudo().with_context(active_test=False)
        return [
            {"id": p.id, "name": p.name, "active": p.active}
            for p in Project.search([("ea_is_internal", "=", True)], order="active desc, name")
        ]

    @api.model
    def ea_fa_project_add(self, name):
        self._ea_fa_require()
        name = (name or "").strip()
        if not name:
            raise refuse(self.env, "fa-project-name")
        project = self.env["project.project"]._ea_ts_create_internal(name)
        self.env["ea.audit.firm.log"]._ea_append("project_changed", detail=self.env._("Created: %(name)s", name=name))
        return project.id

    @api.model
    def ea_fa_project_active(self, project_id, active):
        self._ea_fa_require()
        project = self.env["project.project"].sudo().with_context(active_test=False).browse(int(project_id)).exists()
        if not project or not project.ea_is_internal:
            raise refuse(self.env, "ts-project-not-chargeable")
        project.active = bool(active)
        self.env["ea.audit.firm.log"]._ea_append(
            "project_changed", detail=(self.env._("Reactivated: %(name)s", name=project.name) if active else self.env._("Archived: %(name)s", name=project.name)),
        )
        return True

    # ------------------------------------------------------------------
    # Mail. Set by root at the firm's onboarding (deploy/firm/firm-mail-server.sh), never from a
    # screen: no firm user, the firm administrator and the technical account included, reaches the
    # outgoing mail server (owner, 2026-11-07). The server stays off until a test of the settings as
    # saved has passed, and on staging it never goes on.
    # ------------------------------------------------------------------

    @api.model
    def _ea_fm_staging(self):
        return self.env["ir.config_parameter"].sudo().get_param("ea_audit.staging_band") in _STAGING_VALUES

    @api.model
    def _ea_fm_server(self):
        return self.env.company.sudo().ea_mail_server_id.with_context(active_test=False)

    @api.model
    def _ea_fm_state(self):
        server = self._ea_fm_server()
        if not server:
            return "none"
        if server.active:
            return "on"
        return "tested" if self.env.company.sudo().ea_mail_tested_at else "untested"

    @api.model
    def _ea_fm_can_send(self):
        """True when this firm's own mailbox sends: set, tested, switched on, and not a test environment."""
        if self._ea_fm_staging() or self._ea_fm_state() != "on":
            return False
        gate_closed = getattr(self.env["ir.mail_server"].sudo(), "_ea_mail_gate_closed", None)
        return not (gate_closed and gate_closed())

    @api.model
    def ea_fm_get(self):
        """What the firm administrator's Settings screen says: sending on or off, nothing more."""
        self._ea_fa_require()
        return {"on": self._ea_fm_state() == "on", "staging": self._ea_fm_staging()}

    @api.model
    def ea_fm_save(self, vals):
        raise refuse(self.env, "fm-onboarding-only")

    @api.model
    def ea_fm_test(self):
        raise refuse(self.env, "fm-onboarding-only")

    @api.model
    def ea_fm_enable(self):
        raise refuse(self.env, "fm-onboarding-only")

    @api.model
    def ea_fm_disable(self):
        raise refuse(self.env, "fm-onboarding-only")

    @api.model
    def _ea_fm_require_root(self):
        """The superuser only, that is root's Odoo shell. A private method is not callable over RPC;
        this also refuses one reached through sudo() from a person's request."""
        if not self.env.su or self.env.uid != SUPERUSER_ID:
            raise refuse(self.env, "fm-onboarding-only")

    @api.model
    def _ea_fm_root_get(self):
        self._ea_fm_require_root()
        server = self._ea_fm_server()
        company = self.env.company.sudo()
        return {
            "host": server.smtp_host or "",
            "port": server.smtp_port or 587,
            "encryption": server.smtp_encryption or "starttls",
            "user": server.smtp_user or "",
            "from_filter": server.from_filter or "",
            # the password never leaves the server: the caller learns only that one is set
            "has_password": bool(server.smtp_pass),
            "state": self._ea_fm_state(),
            "tested_at": deadlines.instant_label(company.ea_mail_tested_at) if company.ea_mail_tested_at else "",
            "staging": self._ea_fm_staging(),
        }

    @api.model
    def _ea_fm_address_refused(self, address):
        try:
            return not ipaddress.ip_address(address).is_global
        except ValueError:
            return False

    @api.model
    def _ea_fm_root_save(self, vals):
        self._ea_fm_require_root()
        host = (vals.get("host") or "").strip()
        if not host or " " in host or self._ea_fm_address_refused(host) or host.lower() == "localhost":
            raise refuse(self.env, "fm-host")
        try:
            port = int(vals.get("port") or 0)
        except (TypeError, ValueError):
            raise refuse(self.env, "fm-port") from None
        if port not in MAIL_PORTS:
            raise refuse(self.env, "fm-port")
        encryption = vals.get("encryption")
        if encryption not in MAIL_ENCRYPTIONS:
            raise refuse(self.env, "fm-encryption")
        company = self.env.company.sudo()
        server = self._ea_fm_server()
        password = vals.get("password") or False
        if encryption == "none" and (password or (server and server.smtp_pass)):
            raise refuse(self.env, "fm-plaintext-password")
        values = {
            "name": _MAIL_SERVER_NAME,
            "smtp_host": host,
            "smtp_port": port,
            "smtp_encryption": encryption,
            "smtp_authentication": "login",
            "smtp_user": (vals.get("user") or "").strip() or False,
            "from_filter": (vals.get("from_filter") or "").strip() or False,
            "active": False,
        }
        if password:
            values["smtp_pass"] = password
        if server:
            server.write(values)
        else:
            server = self.env["ir.mail_server"].sudo().create(values)
            company.ea_mail_server_id = server
        company.ea_mail_tested_at = False
        self.env["ea.audit.firm.log"]._ea_append("mail_saved", detail="%s:%s" % (host, port))
        return self._ea_fm_root_get()

    @api.model
    def _ea_fm_assert_public_host(self, server):
        for info in socket.getaddrinfo(server.smtp_host, server.smtp_port, type=socket.SOCK_STREAM):
            if self._ea_fm_address_refused(info[4][0]):
                raise refuse(self.env, "fm-host")

    @api.model
    def _ea_fm_probe(self, server):
        """Odoo's own test: connects, MAIL FROM, RCPT TO, DATA, and sends nothing."""
        self._ea_fm_assert_public_host(server)
        server.test_smtp_connection()

    @api.model
    def _ea_fm_root_test(self):
        self._ea_fm_require_root()
        if self._ea_fm_staging():
            raise refuse(self.env, "fm-staging-policy")
        server = self._ea_fm_server()
        if not server:
            raise refuse(self.env, "fm-none")
        company = self.env.company.sudo()
        try:
            self._ea_fm_probe(server)
        except (UserError, OSError) as error:
            company.ea_mail_tested_at = False
            server.active = False
            self.env["ea.audit.firm.log"]._ea_append("mail_tested", detail=self.env._("Failed"))
            return {"ok": False, "message": str(error)[:400], "kind": self._ea_fm_failure_kind(error),
                    "state": self._ea_fm_root_get()}
        company.ea_mail_tested_at = fields.Datetime.now()
        self.env["ea.audit.firm.log"]._ea_append("mail_tested", detail=self.env._("Passed"))
        return {"ok": True, "message": self.env._("Connection passed. No message was sent."), "state": self._ea_fm_root_get()}

    @api.model
    def _ea_fm_failure_kind(self, error):
        """One word for the console, which says it in plain language: login, connect, tls, sender or
        failed. Read from the exception Odoo's test wrapped, never from its translated message."""
        if getattr(error, "code", None) == "fm-host":
            return "connect"
        seen = set()
        current = error
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, smtplib.SMTPAuthenticationError):
                return "login"
            if isinstance(current, (smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused)):
                return "sender"
            if isinstance(current, (ssl.SSLError, smtplib.SMTPNotSupportedError, smtplib.SMTPServerDisconnected)):
                return "tls"
            if isinstance(current, (socket.gaierror, TimeoutError, ConnectionError, smtplib.SMTPConnectError)):
                return "connect"
            current = current.__cause__ or current.__context__
        return "failed"

    @api.model
    def _ea_fm_root_enable(self):
        self._ea_fm_require_root()
        if self._ea_fm_staging():
            raise refuse(self.env, "fm-staging-policy")
        server = self._ea_fm_server()
        if not server:
            raise refuse(self.env, "fm-none")
        if not self.env.company.sudo().ea_mail_tested_at:
            raise refuse(self.env, "fm-untested")
        server.active = True
        self.env["ea.audit.firm.log"]._ea_append("mail_enabled")
        return self._ea_fm_root_get()

    @api.model
    def _ea_fm_root_disable(self):
        self._ea_fm_require_root()
        server = self._ea_fm_server()
        if server:
            server.active = False
            self.env["ea.audit.firm.log"]._ea_append("mail_disabled")
        return self._ea_fm_root_get()

    @api.model
    def _ea_fm_root_configure(self, vals):
        """What firm-mail-server.sh runs: save, test, and switch sending on only if the test passed.
        Returns the state and the test's message, never the password. On staging it saves and stops."""
        self._ea_fm_require_root()
        self._ea_fm_root_save(vals)
        if self._ea_fm_staging():
            return {"ok": False, "message": self.env._("Sending email stays off on the test environment, by policy."),
                    "state": self._ea_fm_root_get()}
        result = self._ea_fm_root_test()
        if result["ok"]:
            result["state"] = self._ea_fm_root_enable()
        return result
