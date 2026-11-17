import json
import os
import secrets
import time
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import platform_mail, practice
from ..services.heartbeat import HeartbeatRejected
from ..services.messages import _
from .i18n import t
from .platform_services import RELEASE_URL_SECONDS_HEARTBEAT

FIRST_LOGIN_LINK_HOURS = 72
DEFAULT_ENTRY_URL = "https://%s.practice.auditisa.com/web/login"
DEFAULT_FIRST_LOGIN_URL = "https://%s.practice.auditisa.com/ea-firm/first-admin/%t"
SPACE_STATES = [
    ("waiting", "Waiting for the practice computer"),
    ("requested", "Being created"),
    ("ready", "Ready"),
    ("resetting", "Reset asked"),
    ("missing", "Missing"),
    ("removing", "Being removed"),
]
GUARD_STATES = [("ok", "Clean"), ("refused", "Refused a database"), ("unknown", "Unknown")]


class PlatformPracticeComputer(models.Model):
    """The shared client practice computer: one Odoo, one practice space per firm (deploy/practice).

    Holds what its heartbeat says and what the control room asks of it. Like a firm's server it has
    no credential of ours but its heartbeat token, and we have none of its.
    """

    _name = "platform.practice.computer"
    _description = "Practice computer"
    _order = "id"

    name = fields.Char("Name", required=True, readonly=True, help="PRACTICE_NAME on the computer, for example practice-1.")
    domain = fields.Char("Domain", required=True, default="practice.auditisa.com")
    entry_url = fields.Char(
        "Address of a space", required=True, default=DEFAULT_ENTRY_URL,
        help="%s stands for the firm's slug. On the preview: https://test.auditisa.com:8443/practice/%s",
    )
    first_login_url = fields.Char(
        "First login link", required=True, default=DEFAULT_FIRST_LOGIN_URL,
        help="%s stands for the slug, %t for the one-time token. "
             "On the preview: https://test.auditisa.com:8443/practice/%s/first-admin/%t",
    )
    active = fields.Boolean(default=True)
    is_simulation = fields.Boolean("Simulation", readonly=True)
    heartbeat_token = fields.Char("Heartbeat token", groups="base.group_system", copy=False)
    last_heartbeat_at = fields.Datetime("Last heartbeat", readonly=True, copy=False)
    last_heartbeat_timestamp = fields.Integer(readonly=True, copy=False)
    release = fields.Char("Release running", readonly=True, copy=False)
    release_since = fields.Datetime("Running it since", readonly=True, copy=False)
    template_release = fields.Char("Demo template's release", readonly=True, copy=False)
    guard_state = fields.Selection(GUARD_STATES, "Real-data guard", readonly=True, default="unknown", copy=False)
    desired_release_id = fields.Many2one("platform.release", "Release asked", readonly=True, copy=False, ondelete="restrict")
    desired_since = fields.Datetime("Asked on", readonly=True, copy=False)
    # How far its last update has gone, as its heartbeat says: closed words only (services/practice.py).
    progress_target = fields.Char("Update: release", readonly=True, copy=False)
    progress_step = fields.Integer("Update: step", readonly=True, copy=False)
    progress_total = fields.Integer("Update: steps", readonly=True, copy=False)
    progress_code = fields.Char("Update: step code", readonly=True, copy=False)
    progress_slug = fields.Char("Update: space", readonly=True, copy=False)
    progress_failed = fields.Boolean("Update: failed", readonly=True, copy=False)
    progress_reason = fields.Char("Update: reason code", readonly=True, copy=False)
    progress_at = fields.Datetime("Update: reported on", readonly=True, copy=False)
    space_ids = fields.One2many("platform.practice.space", "computer_id", "Practice spaces")
    space_count = fields.Integer("Spaces", compute="_compute_space_count")

    _name_unique = models.Constraint("unique(name)", "This practice computer is already registered.")

    def _compute_space_count(self):
        for computer in self:
            computer.space_count = len(computer.space_ids)

    @api.model
    def _current(self):
        return self.sudo().search([], limit=1)

    def write(self, values):
        if "desired_release_id" in values and "desired_since" not in values:
            values = dict(values, desired_since=fields.Datetime.now() if values["desired_release_id"] else False)
        return super().write(values)

    def _progress(self):
        """The last update's progress as the heartbeat gave it, or None."""
        self.ensure_one()
        if not self.progress_target or self.progress_code not in practice.PROGRESS_CODES:
            return None
        return {
            "target": self.progress_target, "step": self.progress_step, "total": self.progress_total,
            "code": self.progress_code, "slug": self.progress_slug or None, "failed": self.progress_failed,
            "reason": self.progress_reason or None, "at": self.progress_at,
        }

    @api.model
    def _enrol(self, name, entry_url=None, first_login_url=None,
               token_path="/etc/auditisa-platform/practice-heartbeat.token", simulation=False):
        """Registers the practice computer. From `odoo shell` on the control room, once.

        The token goes to a root-only file and is never printed: the owner copies it to the practice
        computer's /etc/auditisa-practice/secrets/heartbeat.token. Spaces asked before it existed
        are attached to it.
        """
        token = secrets.token_hex(32)
        values = {"name": name, "heartbeat_token": token, "is_simulation": simulation}
        if entry_url:
            values["entry_url"] = entry_url
        if first_login_url:
            values["first_login_url"] = first_login_url
        computer = self.sudo().create(values)
        if token_path:
            descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(token + "\n")
        orphans = self.env["platform.practice.space"].sudo().search([("computer_id", "=", False)])
        orphans.write({"computer_id": computer.id, "state": "requested"})
        self.env["platform.log"]._record(_("Practice computer registered"), None, name)
        return computer

    # ------------------------------------------------------------------ heartbeat

    @api.model
    def _receive_heartbeat(self, headers, body):
        """Returns (answer, signature) or raises HeartbeatRejected. Runs without a session."""
        computers = self.sudo()
        found = {}

        def find(name):
            computer = computers.search([("name", "=", name)], limit=1)
            if not computer:
                return None
            self.env.cr.execute("SELECT id FROM platform_practice_computer WHERE id = %s FOR UPDATE", [computer.id])
            found["computer"] = computer
            return computer.heartbeat_token, computer.last_heartbeat_timestamp

        name, timestamp, figures = practice.accept(headers, body, find, int(time.time()))
        computer = found["computer"]
        computer._apply_figures(figures, timestamp)
        answer = json.dumps(computer._answer(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return answer, practice.sign_response(computer.heartbeat_token, name, timestamp, answer)

    def _apply_figures(self, figures, timestamp):
        self.ensure_one()
        now = fields.Datetime.now()
        values = {
            "last_heartbeat_at": now,
            "last_heartbeat_timestamp": timestamp,
            "template_release": figures["template_release"],
            "guard_state": figures["guard"],
        }
        progress = figures.get("progress")
        if progress:
            was_failed = self.progress_failed and self.progress_target == progress["target"]
            values.update(
                progress_target=progress["target"], progress_step=progress["step"], progress_total=progress["total"],
                progress_code=progress["code"], progress_slug=progress["slug"] or False,
                progress_failed=progress["failed"], progress_reason=progress["reason"] or False,
                progress_at=practice.parse_instant(progress["at"]),
            )
            if progress["failed"] and not was_failed:
                self.env["platform.log"]._record(
                    _("Practice computer: the update failed"), None,
                    _("Release %(release)s, reason code %(reason)s", release=progress["target"][:12], reason=progress["reason"]),
                )
        if figures["release"] != self.release:
            values.update(release=figures["release"], release_since=now if figures["release"] else False)
            if figures["release"]:
                self.env["platform.release"].sudo()._practice_started(figures["release"], now)
                self.env["platform.log"]._record(_("Practice computer on a new release"), None, figures["release"][:12])
        self.write(values)
        reported = {space["slug"]: space for space in figures["spaces"]}
        for space in self.space_ids:
            space._apply_reported(reported.get(space.slug), figures["release"], now)

    def _answer(self):
        """What the practice computer may be asked: a release (with its fingerprint), and each firm's space."""
        self.ensure_one()
        answer = {"ok": True, "spaces": [], "remove": []}
        # The only addresses a practice space may email (Platform > Settings). Empty, the default: none at all.
        answer["mail_allowlist"] = platform_mail.parse_allowlist(
            self.env["ir.config_parameter"].sudo().get_param("ea_platform.practice_mail_allowlist") or "")[0]
        release = self.desired_release_id
        if release:
            answer["release"] = {"sha": release.sha, "bundle_sha256": release.bundle_sha256}
            url = self.env["platform.services"]._release_url(release, RELEASE_URL_SECONDS_HEARTBEAT)
            if url:
                answer["release"]["bundle_url"] = url
        for space in self.space_ids.with_context(active_test=False):
            if space.state == "removing":
                answer["remove"].append(space.slug)
            elif space.active:
                item = space._request_item()
                if item:
                    answer["spaces"].append(item)
        return answer

    def _simulated_figures(self, now=None):
        """What a practice computer that obeyed its last answer would say. For simulations and tests."""
        self.ensure_one()
        answer = self._answer()
        stamp = practice.format_instant(now or datetime.utcnow().replace(microsecond=0))
        spaces = [{
            "slug": item["slug"], "state": "ready", "last_reset_at": stamp, "users": 6, "last_login_on": None,
            "reset_generation": item["reset_generation"], "addons_on": item["addons"],
            "link_set": "first_admin_hash" in item,
        } for item in answer["spaces"]]
        release = (self.desired_release_id.sha if self.desired_release_id else self.release) or None
        return {"schema": 1, "computer": self.name, "release": release, "template_release": release,
                "guard": "ok", "spaces": spaces, "progress": None}

    def _simulate_heartbeat(self, figures=None):
        self.ensure_one()
        if not self.is_simulation:
            raise UserError(t(self.env, _("Only for a simulated practice computer.")))
        computer = self.sudo()
        body = json.dumps(figures or computer._simulated_figures(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        timestamp = max(int(time.time()), (computer.last_heartbeat_timestamp or 0) + 1)
        headers = {
            practice.HEADER_COMPUTER: computer.name, practice.HEADER_TIMESTAMP: str(timestamp),
            practice.HEADER_SIGNATURE: practice.sign(computer.heartbeat_token, computer.name, timestamp, body),
        }
        return self.env["platform.practice.computer"]._receive_heartbeat(headers, body)

    def action_simulate_heartbeat(self):
        for computer in self:
            computer._simulate_heartbeat()
        return True

    def action_send_release(self):
        """Opens the release choice: a release goes to the practice computer before any firm."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "platform.practice.release.wizard", "view_mode": "form", "views": [(False, "form")],
            "target": "new", "context": {"default_computer_id": self.id},
        }


class PlatformPracticeSpace(models.Model):
    """A firm's practice space: its own database on the practice computer, made-up data only."""

    _name = "platform.practice.space"
    _description = "Practice space"
    _order = "slug"
    _rec_name = "slug"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True, ondelete="restrict", index=True)
    computer_id = fields.Many2one("platform.practice.computer", "Practice computer", readonly=True, ondelete="restrict")
    slug = fields.Char(related="firm_id.slug", store=True, string="Slug")
    firm_name = fields.Char(related="firm_id.name", string="Firm name")
    active = fields.Boolean(default=True)
    address = fields.Char("Address", compute="_compute_address")
    admin_login = fields.Char("First administrator's login", readonly=True)
    state = fields.Selection(SPACE_STATES, "State", readonly=True, default="waiting", required=True)
    version = fields.Char("Version", readonly=True)
    last_reset_at = fields.Datetime("Last reset", readonly=True)
    users_count = fields.Integer("Users", readonly=True)
    last_login_on = fields.Date("Last login", readonly=True)
    last_heartbeat_at = fields.Datetime("Last heartbeat", readonly=True)
    reset_generation = fields.Integer("Resets asked", readonly=True, default=0)
    reset_done_generation = fields.Integer("Resets done", readonly=True, default=0)
    addons_asked = fields.Char("Add-ons asked", compute="_compute_addons")
    addons_reported = fields.Char("Add-ons on", readonly=True)
    first_login_token = fields.Char("First login link", groups="base.group_system", copy=False)
    first_login_expires_at = fields.Datetime("The link expires on", readonly=True, copy=False)
    first_login_revealed_at = fields.Datetime("Link shown on", readonly=True, copy=False)
    first_login_ready = fields.Boolean("Link ready to show", compute="_compute_first_login_ready")
    link_set = fields.Boolean("Link in place on the space", readonly=True)
    computer_simulated = fields.Boolean(related="computer_id.is_simulation", string="Simulated practice computer")

    _firm_unique = models.Constraint("unique(firm_id)", "A firm has one practice space.")

    @api.depends("slug", "computer_id.entry_url")
    def _compute_address(self):
        for space in self:
            pattern = space.computer_id.entry_url or DEFAULT_ENTRY_URL
            space.address = pattern.replace("%s", space.slug) if space.slug else False

    @api.depends("firm_id.addon_line_ids.desired")
    def _compute_addons(self):
        for space in self:
            space.addons_asked = ", ".join(space._addon_codes())

    @api.depends("first_login_expires_at", "first_login_revealed_at", "link_set", "state")
    def _compute_first_login_ready(self):
        now = fields.Datetime.now()
        for space in self:
            space.first_login_ready = bool(
                space.state == "ready" and space.link_set and space.first_login_expires_at
                and space.first_login_expires_at > now and not space.first_login_revealed_at
            )

    def _first_login_link(self, token):
        self.ensure_one()
        pattern = self.computer_id.first_login_url or DEFAULT_FIRST_LOGIN_URL
        return pattern.replace("%s", self.slug).replace("%t", token)

    def _addon_codes(self):
        """The firm's own switches: what is on for the firm is on in its practice space."""
        self.ensure_one()
        return sorted(self.firm_id.sudo().addon_line_ids.filtered("desired").mapped("code"))

    @api.model
    def _create_for(self, firm):
        computer = self.env["platform.practice.computer"]._current()
        space = self.sudo().create({
            "firm_id": firm.id,
            "computer_id": computer.id or False,
            "admin_login": (firm.contact_email or "").strip().lower(),
            "state": "requested" if computer else "waiting",
        })
        space._start_first_login_link()
        self.env["platform.log"]._record(_("Practice space asked"), firm, space.slug)
        return space

    def _start_first_login_link(self):
        """A one-time link for the firm's first administrator, as for its real server. Only the hash leaves."""
        for space in self.sudo():
            space.write({
                "first_login_token": secrets.token_urlsafe(32),
                "first_login_expires_at": fields.Datetime.now() + timedelta(hours=FIRST_LOGIN_LINK_HOURS),
                "first_login_revealed_at": False,
            })

    def _request_item(self):
        self.ensure_one()
        space = self.sudo()
        token = space.first_login_token
        expires = space.first_login_expires_at
        live = token and expires and expires > fields.Datetime.now() and not space.first_login_revealed_at
        return practice.space_request(
            space.slug, space.firm_id.name, space.admin_login, space.firm_id.lang, space._addon_codes(),
            space.reset_generation,
            practice.link_hash(token) if live else None, expires if live else None,
        )

    def _apply_reported(self, reported, release, now):
        self.ensure_one()
        if self.state == "removing":
            if reported is None:
                self.write({"active": False, "state": "missing"})
                self.env["platform.log"]._record(_("Practice space removed"), self.firm_id, self.slug)
            return
        if reported is None:
            if self.state in ("ready", "resetting"):
                self.write({"state": "missing"})
            return
        done = reported["reset_generation"]
        values = {
            "last_heartbeat_at": now,
            "version": release,
            "last_reset_at": practice.parse_instant(reported["last_reset_at"]),
            "users_count": reported["users"] or 0,
            "last_login_on": reported["last_login_on"] or False,
            "reset_done_generation": done,
            "addons_reported": ", ".join(reported["addons_on"]),
            "link_set": reported["link_set"],
            "state": "ready" if reported["state"] == "ready" and done >= self.reset_generation
            else ("resetting" if reported["state"] == "ready" else "missing"),
        }
        self.write(values)

    # ------------------------------------------------------------------ the owner's buttons

    def _require_operator(self):
        if not self.env.user.has_group("ea_platform_admin.group_platform_operator"):
            raise UserError(t(self.env, _("Only an operator or the owner can do this.")))

    def action_open_reset(self):
        self.ensure_one()
        self._require_operator()
        return {
            "type": "ir.actions.act_window", "res_model": "platform.practice.reset.wizard", "view_mode": "form", "views": [(False, "form")],
            "target": "new", "context": {"default_space_id": self.id},
        }

    def _request_reset(self, reason, user=None):
        self.ensure_one()
        self._require_operator()
        if not (reason or "").strip():
            raise UserError(t(self.env, _("Say why: the reason goes in the platform log.")))
        if self.state not in ("ready", "missing", "resetting"):
            raise UserError(t(self.env, _("This practice space is not ready yet: nothing to reset.")))
        self.sudo().write({"reset_generation": max(self.reset_generation, self.reset_done_generation) + 1, "state": "resetting"})
        self.env["platform.log"]._record(
            _("Practice space reset to fresh demo data asked"), self.firm_id,
            _("%(slug)s. Reason: %(reason)s", slug=self.slug, reason=reason.strip()), user=user or self.env.user,
        )

    def action_open_first_login(self):
        self.ensure_one()
        self._require_operator()
        wizard = self.env["platform.practice.first.login"].create({"space_id": self.id})
        return {
            "type": "ir.actions.act_window", "res_model": wizard._name, "res_id": wizard.id, "view_mode": "form", "views": [(False, "form")],
            "target": "new",
        }

    def action_new_first_login(self):
        """A new one-time link, when the first one was lost or expired. The old one stops working."""
        self.ensure_one()
        self._require_operator()
        self._start_first_login_link()
        self.sudo().write({"link_set": False})
        self.env["platform.log"]._record(_("New first-login link for a practice space"), self.firm_id, self.slug)
        return True

    def action_remove(self):
        self.ensure_one()
        if not self.env.user.has_group("ea_platform_admin.group_platform_owner"):
            raise UserError(t(self.env, _("Only the owner can remove a practice space.")))
        self.sudo().write({"state": "removing"})
        self.env["platform.log"]._record(_("Practice space removal asked"), self.firm_id, self.slug)
        return True

    def unlink(self):
        raise UserError(t(self.env, _("A practice space is removed with its button, so that the practice computer removes it too.")))


class PlatformFirm(models.Model):
    _inherit = "platform.firm"

    practice_space_ids = fields.One2many("platform.practice.space", "firm_id", "Practice space")
    practice_space_id = fields.Many2one("platform.practice.space", "Practice space", compute="_compute_practice_space")

    def _compute_practice_space(self):
        for firm in self:
            firm.practice_space_id = firm.practice_space_ids[:1]

    def action_create_practice_space(self):
        self.ensure_one()
        if not self.env.user.has_group("ea_platform_admin.group_platform_operator"):
            raise UserError(t(self.env, _("Only an operator or the owner can do this.")))
        if self.practice_space_ids:
            raise UserError(t(self.env, _("This firm already has a practice space.")))
        self.env["platform.practice.space"]._create_for(self.sudo())
        return True


class PlatformRelease(models.Model):
    """Release order: Staging (the practice computer) first, then Production (the client firms)."""

    _inherit = "platform.release"

    practice_since = fields.Datetime("First on Staging on", readonly=True, copy=False)
    staging_ok = fields.Boolean("May go to Production", compute="_compute_staging")
    staging_text = fields.Char("Release order", compute="_compute_staging")

    @api.depends("sha")
    @api.depends_context("lang")
    def _compute_staging(self):
        for release in self:
            ok, message = release._staging_check()
            release.staging_ok = ok
            release.staging_text = t(self.env, message)

    def _staging_check(self):
        """(ok, message). Production takes only what Staging (the practice computer) runs now. No
        practice computer registered: the order cannot apply, and it says so."""
        self.ensure_one()
        computer = self.env["platform.practice.computer"]._current()
        if not computer:
            return True, _("No practice computer yet: the release order does not apply.")
        return practice.staging_status(computer.release, self.sha)

    @api.model
    def _practice_started(self, sha, when):
        releases = self.sudo().with_context(active_test=False).search([("practice_since", "=", False)])
        for release in releases.filtered(lambda r: sha.startswith(r.sha) or r.sha.startswith(sha)):
            release.practice_since = when



class PlatformRollout(models.Model):
    _inherit = "platform.rollout"

    def action_start(self):
        """A firm is offered only a release that Staging runs now. A rollback (back to a release the firms
        already ran) is the one exception, and only the pipeline's rollback asks for it."""
        for rollout in self:
            if self.env.context.get("ea_rollback"):
                continue
            ok, message = rollout.release_id.sudo()._staging_check()
            if not ok:
                raise UserError(t(self.env, _("Not yet for the firms: %(why)s", why=message)))
        return super().action_start()
