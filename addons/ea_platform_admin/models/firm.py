import json
import logging
import secrets
import time
from datetime import date, datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services import health, heartbeat, simulator
from ..services.messages import _, dumps_list, loads
from ..services.catalogue import LANGUAGES, REGIONS, SIZES, monthly_cost, selection
from ..services.provider import ProviderError
from ..services.provisioning import SERVER_TAG
from ..services.validation import custom_domain_errors, parse_allowlist, parse_domain_list, ssh_key_fingerprint
from .i18n import read, t
from .platform_services import RELEASE_URL_SECONDS_HEARTBEAT

_logger = logging.getLogger(__name__)

STATES = [
    ("provisioning", "Provisioning"),
    ("active", "Active"),
    ("suspended", "Suspended"),
    ("offboarding", "Leaving"),
    ("archived", "Archived"),
]
HEALTH = [
    ("green", "Green"),
    ("amber", "Amber"),
    ("red", "Red"),
    ("grey", "Grey"),
]
FIRST_ADMIN_LINK_HOURS = 72
MIN_RETENTION_DAYS = 30
DEFAULT_RETENTION_DAYS = 90


class PlatformFirm(models.Model):
    """One firm and its dedicated server, as the control plane sees it.

    Holds identity, the provider's references and the heartbeat's figures. It holds no database
    credential, no firm password, no backup key, no storage key and no SSH private key, and it has
    no way to reach a firm's server: tests/test_no_firm_data.py checks all of that.
    """

    _name = "platform.firm"
    _description = "Firm"
    _inherit = ["mail.thread"]
    _order = "name"

    # Identity
    name = fields.Char("Firm name", required=True, tracking=True)
    slug = fields.Char("Slug", required=True, readonly=True, copy=False, index=True)
    legal_name = fields.Char("Legal name")
    legal_form = fields.Char("Legal form")
    registration_number = fields.Char("Trade register no. (RCCM)")
    tax_number = fields.Char("Tax number (NIU)")
    contact_name = fields.Char("Contact", required=True)
    contact_email = fields.Char("Contact email", required=True)
    contact_phone = fields.Char("Phone")
    street = fields.Char("Street address")
    city = fields.Char("City")
    country_id = fields.Many2one("res.country", "Country")
    lang = fields.Selection(selection(LANGUAGES), "Default language", required=True, default="fr_FR")
    allowed_email_domains = fields.Text("Allowed email domains", required=True)

    # Server
    state = fields.Selection(
        STATES, "State", required=True, default="provisioning", tracking=True, group_expand="_expand_states",
    )
    is_simulation = fields.Boolean("Simulation", readonly=True, copy=False)
    custom_domain = fields.Char("The firm's own domain")
    platform_host = fields.Char("Platform address", compute="_compute_address", store=True)
    address = fields.Char("Web address", compute="_compute_address", store=True)
    region = fields.Selection(selection(REGIONS), "Region", required=True, readonly=True)
    size = fields.Selection(selection(SIZES), "Size", required=True, readonly=True)
    monthly_cost_usd = fields.Float("Estimated monthly cost (USD)", compute="_compute_cost")
    server_id = fields.Char("Server id", readonly=True, copy=False)
    server_ip = fields.Char("IP address", readonly=True, copy=False)
    ssh_key_id = fields.Char("SSH key at the provider", readonly=True, copy=False)
    firewall_id = fields.Char("Firewall at the provider", readonly=True, copy=False)
    storage_id = fields.Char("Backup storage", readonly=True, copy=False)
    ssh_public_key = fields.Char("Public SSH key", readonly=True, required=True, copy=False)
    ssh_key_fingerprint = fields.Char("SSH key fingerprint", compute="_compute_fingerprint", store=True)
    activated_at = fields.Datetime("Went live on", readonly=True, copy=False)
    odoo_version = fields.Char("Odoo version", readonly=True, default="19.0")

    # Release
    addon_release = fields.Char("Installed release", readonly=True, copy=False)
    desired_release_id = fields.Many2one("platform.release", "Requested release", readonly=True, copy=False, ondelete="restrict")
    release_locked = fields.Boolean("Release locked", help="This firm is left out of updates while this box is ticked.")

    # Heartbeat figures: this list is all a firm ever tells the platform
    last_heartbeat_at = fields.Datetime("Last heartbeat", readonly=True, copy=False)
    last_heartbeat_timestamp = fields.Integer("Last heartbeat timestamp", readonly=True, copy=False)
    last_backup_at = fields.Datetime("Last backup", readonly=True, copy=False)
    last_backup_ok = fields.Boolean("Backup succeeded", readonly=True, copy=False)
    last_restore_test_at = fields.Datetime("Last restore test", readonly=True, copy=False)
    last_restore_test_ok = fields.Boolean("Restore test succeeded", readonly=True, copy=False)
    cert_expires_on = fields.Date("Certificate expiry", readonly=True, copy=False)
    disk_total_gb = fields.Integer("Disk (GB)", readonly=True, copy=False)
    disk_used_pct = fields.Integer("Disk used (%)", readonly=True, copy=False)
    mem_total_mb = fields.Integer("Memory (MB)", readonly=True, copy=False)
    mem_available_mb = fields.Integer("Available memory (MB)", readonly=True, copy=False)
    users_active = fields.Integer("Users", readonly=True, copy=False)
    engagements_active = fields.Integer("Engagements", readonly=True, copy=False)
    mail_enabled = fields.Boolean("Mail open", readonly=True, copy=False)
    update_state = fields.Char("Update state", readonly=True, copy=False)
    update_release = fields.Char("Last update's release", readonly=True, copy=False)
    export_state = fields.Char("Export state", readonly=True, copy=False)
    export_at = fields.Datetime("Exported on", readonly=True, copy=False)
    export_sha256 = fields.Char("Export digest", readonly=True, copy=False)
    ssh_sessions_24h = fields.Integer("SSH logins (24 h)", readonly=True, copy=False)
    last_ssh_at = fields.Datetime("Last SSH login", readonly=True, copy=False)
    heartbeat_rejects_24h = fields.Integer("Heartbeats rejected (24 h)", readonly=True, copy=False)
    last_reject_at = fields.Datetime("Last rejection", readonly=True, copy=False)
    last_reject_code = fields.Char("Last rejection's reason", readonly=True, copy=False)

    # Health
    health_color = fields.Selection(HEALTH, "Health", readonly=True, default="grey", copy=False)
    # As written, in English; the two fields below show it in the reader's language.
    health_reason_raw = fields.Text("Reason (source)", readonly=True, copy=False, default="Provisioning under way")
    health_reason = fields.Text("Reason", compute="_compute_health_text")
    health_summary = fields.Char("Main reason", compute="_compute_health_text")
    needs_attention = fields.Boolean("Needs attention", readonly=True, copy=False, index=True)

    # Guardrails
    orphan_flag = fields.Boolean("Orphan server", readonly=True, copy=False)
    orphan_detail_raw = fields.Text("Orphan detail (source)", readonly=True, copy=False)
    orphan_detail = fields.Text("Orphan detail", compute="_compute_health_text")
    backup_key_escrowed_at = fields.Datetime("Backup key put in the safe on", readonly=True, copy=False)
    backup_key_escrowed_by = fields.Many2one("res.users", "By", readonly=True, copy=False)

    # Secrets the platform must hold. Administrators of Odoo only; no view shows them.
    heartbeat_token = fields.Char("Heartbeat token", groups="base.group_system", copy=False)
    first_admin_token = fields.Char("First administrator's link", groups="base.group_system", copy=False)
    first_admin_expires_at = fields.Datetime("The link expires on", readonly=True, copy=False)
    first_admin_revealed_at = fields.Datetime("Link shown on", readonly=True, copy=False)
    first_admin_ready = fields.Boolean("Link available", compute="_compute_first_admin_ready")

    # Offboarding
    offboard_requested_at = fields.Datetime("Exit requested on", readonly=True, copy=False)
    offboard_retention_days = fields.Integer("Retention (days)", readonly=True, copy=False)
    export_requested = fields.Boolean("Export requested", readonly=True, copy=False)
    export_received_on = fields.Date("Export handed to the firm on", readonly=True, copy=False)
    destroy_after = fields.Date("Can be destroyed from", compute="_compute_destroy_after", store=True)
    can_destroy = fields.Boolean("Can be destroyed", compute="_compute_can_destroy")

    job_ids = fields.One2many("platform.provision.job", "firm_id", "Provisioning runs")
    last_job_id = fields.Many2one("platform.provision.job", "Last provisioning run", compute="_compute_last_job")
    log_ids = fields.One2many("platform.log", "firm_id", "Log")
    breakglass_ids = fields.One2many("platform.breakglass", "firm_id", "Break-glass accesses")
    note = fields.Text("Operator notes")

    _slug_unique = models.Constraint("unique(slug)", "This slug has already been given.")

    @api.model
    def _expand_states(self, states, domain):
        return [key for key, _label in STATES]

    # ------------------------------------------------------------------ computes

    @api.depends("slug", "custom_domain")
    def _compute_address(self):
        base = self.env["ir.config_parameter"].sudo().get_param("ea_platform.base_domain", "auditisa.com")
        for firm in self:
            firm.platform_host = f"{firm.slug}.{base}" if firm.slug else False
            firm.address = firm.custom_domain or firm.platform_host

    @api.depends("size")
    def _compute_cost(self):
        for firm in self:
            firm.monthly_cost_usd = monthly_cost(firm.size)[2] if firm.size else 0.0

    @api.depends("ssh_public_key")
    def _compute_fingerprint(self):
        for firm in self:
            firm.ssh_key_fingerprint = ssh_key_fingerprint(firm.ssh_public_key) if firm.ssh_public_key else False

    @api.depends("health_reason_raw", "orphan_detail_raw")
    @api.depends_context("lang")
    def _compute_health_text(self):
        for firm in self:
            firm.health_reason = read(self.env, firm.health_reason_raw)
            firm.health_summary = (firm.health_reason or "").split("\n")[0]
            firm.orphan_detail = read(self.env, firm.orphan_detail_raw)

    @api.depends("job_ids")
    def _compute_last_job(self):
        for firm in self:
            firm.last_job_id = firm.job_ids.sorted("id")[-1:] if firm.job_ids else False

    @api.depends("first_admin_expires_at", "first_admin_revealed_at", "state")
    def _compute_first_admin_ready(self):
        now = fields.Datetime.now()
        for firm in self:
            firm.first_admin_ready = bool(
                firm.state == "active" and firm.first_admin_expires_at
                and firm.first_admin_expires_at > now and not firm.first_admin_revealed_at
            )

    @api.depends("export_at", "offboard_retention_days")
    def _compute_destroy_after(self):
        for firm in self:
            firm.destroy_after = (
                firm.export_at.date() + timedelta(days=firm.offboard_retention_days)
                if firm.export_at and firm.offboard_retention_days else False
            )

    @api.depends("state", "export_state", "export_received_on", "destroy_after")
    def _compute_can_destroy(self):
        today = fields.Date.context_today(self)
        for firm in self:
            firm.can_destroy = bool(
                firm.state == "offboarding" and firm.export_state == "done" and firm.export_received_on
                and firm.destroy_after and firm.destroy_after <= today
            )

    @api.constrains("custom_domain")
    def _check_custom_domain(self):
        base = self.env["ir.config_parameter"].sudo().get_param("ea_platform.base_domain", "auditisa.com")
        for firm in self:
            errors = custom_domain_errors(firm.custom_domain, base)
            if errors:
                raise ValidationError(t(self.env, errors[0]))

    @api.constrains("allowed_email_domains")
    def _check_domains(self):
        for firm in self:
            _domains, errors = parse_domain_list(firm.allowed_email_domains)
            if errors:
                raise ValidationError(t(self.env, errors[0]))

    def unlink(self):
        raise UserError(t(self.env, _("A firm cannot be deleted: its slug and its log remain. It is archived through the exit procedure.")))

    # ------------------------------------------------------------------ health

    def _health_input(self):
        self.ensure_one()
        since = fields.Datetime.now() - timedelta(hours=24)
        job = self.last_job_id
        rejected_recently = self.last_reject_at and self.last_reject_at >= since
        return {
            "state": self.state,
            "orphan_flag": self.orphan_flag,
            "orphan_detail": (loads(self.orphan_detail_raw) or [None])[0],
            "job_failed": bool(job and job.state in ("rolled_back", "rollback_failed")),
            "last_heartbeat_at": self.last_heartbeat_at,
            "activated_at": self.activated_at,
            "last_backup_at": self.last_backup_at,
            "last_backup_ok": self.last_backup_ok if self.last_backup_at else None,
            "last_restore_test_at": self.last_restore_test_at,
            "last_restore_test_ok": self.last_restore_test_ok if self.last_restore_test_at else None,
            "cert_expires_on": self.cert_expires_on,
            "disk_used_pct": self.disk_used_pct if self.last_heartbeat_at else None,
            "mem_total_mb": self.mem_total_mb,
            "mem_available_mb": self.mem_available_mb,
            "update_state": self.update_state,
            "export_state": self.export_state,
            "backup_key_escrowed": bool(self.backup_key_escrowed_at),
            "ssh_sessions_24h": self.ssh_sessions_24h,
            "breakglass_24h": self.sudo().env["platform.breakglass"].search_count([
                ("firm_id", "=", self.id), ("opened_at", ">=", since),
            ]),
            "heartbeat_rejects_24h": self.heartbeat_rejects_24h if rejected_recently else 0,
        }

    def _evaluate_health(self):
        now = fields.Datetime.now()
        for firm in self.sudo():
            before = firm.health_color
            colour, reasons = health.evaluate(firm._health_input(), now)
            firm.write({
                "health_color": colour,
                "health_reason_raw": dumps_list(reasons),
                "needs_attention": colour in ("red", "amber"),
            })
            if colour == "red" and before != "red":
                firm._alert(reasons)

    def _alert(self, reasons):
        """A note on the firm, for the owners, in the first owner's language."""
        self.ensure_one()
        owners = self.env.ref("ea_platform_admin.group_platform_owner").user_ids
        env = self.with_context(lang=owners[:1].lang or "en_US").env
        lines = "; ".join(t(env, reason) for reason in reasons)
        self.message_post(
            body=t(env, _("Alert: %(reasons)s", reasons=lines)),
            partner_ids=owners.partner_id.ids,
            subtype_xmlid="mail.mt_note",
        )
        self.env["platform.log"]._record(_("Alert"), self, reasons[0])

    @api.model
    def _cron_watch(self):
        self.search([("state", "!=", "archived")])._evaluate_health()
        self._find_orphan_servers()
        self.search([("first_admin_expires_at", "<", fields.Datetime.now())])._expire_first_admin_links()

    @api.model
    def _find_orphan_servers(self):
        """A server tagged for the platform that no firm claims is reported, never destroyed."""
        try:
            provider = self.env["platform.services"]._outside()[0]
            servers = provider.list_servers(SERVER_TAG)
        except ProviderError as error:
            _logger.warning("Provider not reachable while looking for orphans: %s", error)
            return []
        known = set(self.with_context(active_test=False).search([("server_id", "!=", False)]).mapped("server_id"))
        orphans = [server for server in servers if server.id not in known]
        log = self.env["platform.log"].sudo()
        for server in orphans:
            firm = self.search([("slug", "=", server.label.removeprefix("auditisa-firm-"))], limit=1)
            if firm and firm.job_ids.filtered(lambda job: job.state == "waiting"):
                continue  # still being built: the job records the server after this step
            detail = f"{server.id} ({server.label})"
            if not log.search_count([("action", "=", "Orphan server detected"), ("detail", "=", detail)]):
                log._record(_("Orphan server detected"), firm or None, detail)
            if firm and not firm.orphan_flag:
                firm.sudo().write({"orphan_flag": True, "orphan_detail_raw": detail})
                firm._evaluate_health()
        return orphans

    def _expire_first_admin_links(self):
        self.sudo().write({"first_admin_token": False})

    # ------------------------------------------------------------------ heartbeat

    @api.model
    def _receive_heartbeat(self, headers, body):
        """Everything the receiver does. Returns (answer body, signature); raises HeartbeatRejected.

        Runs without a session. Only the figures validated by services/heartbeat.py are stored, and
        nothing from a rejected request is, except which rule refused it.
        """
        firms = self.sudo().with_context(active_test=False)
        found = {}

        def find_firm(slug):
            firm = firms.search([("slug", "=", slug), ("state", "!=", "archived")], limit=1)
            if not firm:
                return None
            self.env.cr.execute("SELECT id FROM platform_firm WHERE id = %s FOR UPDATE", [firm.id])
            found["firm"] = firm
            return firm.heartbeat_token, firm.last_heartbeat_timestamp

        try:
            slug, timestamp, figures = heartbeat.accept(headers, body, find_firm, int(time.time()))
        except heartbeat.HeartbeatRejected as rejected:
            firm = found.get("firm")
            # A bad signature can come from anyone: it must not be a way to turn a firm orange.
            if firm and rejected.code not in ("bad_signature", "unknown_firm"):
                firm._record_reject(rejected.code)
            raise
        firm = found["firm"]
        firm._apply_figures(figures, timestamp)
        answer = json.dumps(firm._heartbeat_answer(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return answer, heartbeat.sign_response(firm.heartbeat_token, slug, timestamp, answer)

    def _record_reject(self, code):
        self.ensure_one()
        since = fields.Datetime.now() - timedelta(hours=24)
        count = self.heartbeat_rejects_24h if self.last_reject_at and self.last_reject_at >= since else 0
        self.write({
            "heartbeat_rejects_24h": count + 1,
            "last_reject_at": fields.Datetime.now(),
            "last_reject_code": code,
        })
        _logger.warning("Heartbeat of %s rejected: %s", self.slug, code)
        self._evaluate_health()

    def _apply_figures(self, figures, timestamp):
        self.ensure_one()
        instant = heartbeat.parse_instant
        cert = figures.get("cert_expires_on")
        values = {
            "last_heartbeat_at": fields.Datetime.now(),
            "last_heartbeat_timestamp": timestamp,
            "addon_release": figures["release"],
            "odoo_version": figures.get("odoo_version") or self.odoo_version,
            "disk_total_gb": figures.get("disk_total_gb", 0),
            "disk_used_pct": figures["disk_used_pct"],
            "mem_total_mb": figures["mem_total_mb"],
            "mem_available_mb": figures["mem_available_mb"],
            "users_active": figures["users_active"],
            "engagements_active": figures["engagements_active"],
            "last_backup_at": instant(figures.get("last_backup_at")),
            "last_backup_ok": bool(figures.get("last_backup_ok")),
            "last_restore_test_at": instant(figures.get("last_restore_test_at")),
            "last_restore_test_ok": bool(figures.get("last_restore_test_ok")),
            "cert_expires_on": date.fromisoformat(cert) if cert else False,
            "mail_enabled": figures["mail_enabled"],
            "update_state": figures["update_state"],
            "update_release": figures.get("update_release"),
            "export_state": figures["export_state"],
            "export_at": instant(figures.get("export_at")),
            "export_sha256": figures.get("export_sha256"),
            "ssh_sessions_24h": figures.get("ssh_sessions_24h", 0),
            "last_ssh_at": instant(figures.get("last_ssh_at")),
        }
        self.write(values)
        self._evaluate_health()
        self.env["platform.rollout"]._on_firm_figures(self)

    def _ssh_allowlist(self):
        return parse_allowlist(self.env["ir.config_parameter"].sudo().get_param("ea_platform.ssh_allowlist", ""))[0]

    def _heartbeat_answer(self):
        """What a firm may be asked: a release (with its fingerprint), an export, the operator's addresses. No more."""
        self.ensure_one()
        answer = {"ok": True, "export_requested": bool(self.export_requested and self.state == "offboarding")}
        allowlist = self._ssh_allowlist()
        if allowlist:
            answer["ssh_allowlist"] = allowlist
        release = self.desired_release_id
        if release and not self.release_locked and self.state == "active":
            answer["desired_release"] = release.sha
            answer["desired_bundle_sha256"] = release.bundle_sha256
            # A time-limited download address into the private releases bucket, renewed at each answer. The
            # server installs the file only if its SHA-256 is desired_bundle_sha256: this answer is
            # authenticated (HMAC under the firm's own token, over HTTPS), the bucket is not trusted.
            url = self.env["platform.services"]._release_url(release, RELEASE_URL_SECONDS_HEARTBEAT)
            if url:
                answer["desired_bundle_url"] = url
        return answer

    # ------------------------------------------------------------------ simulation

    def _simulate_heartbeat(self, release=None, **changes):
        """A dry-run firm sends a real signed heartbeat through the real receiver. Refused on others."""
        self.ensure_one()
        if not self.is_simulation:
            raise UserError(t(self.env, _("Only for simulation firms.")))
        firm = self.sudo()
        now = datetime.utcnow().replace(microsecond=0)
        figures = simulator.healthy_figures(now, release or firm.addon_release or firm.desired_release_id.sha)
        figures.update(changes)
        timestamp = max(int(time.time()), (firm.last_heartbeat_timestamp or 0) + 1)
        headers, body = simulator.signed_request(firm.heartbeat_token, firm.slug, timestamp, figures)
        self.env["platform.firm"]._receive_heartbeat(headers, body)

    def action_simulate_heartbeat(self):
        for firm in self:
            firm._simulate_heartbeat()
        return True

    def action_simulate_export(self):
        self.ensure_one()
        now = heartbeat.format_instant(datetime.utcnow().replace(microsecond=0))
        self._simulate_heartbeat(export_state="done", export_at=now, export_sha256="ab" * 32)
        return True

    # ------------------------------------------------------------------ actions of the screens

    def action_run_last_job(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "platform.provision.job",
            "res_id": self.last_job_id.id,
            "view_mode": "form",
        }

    def action_confirm_key_escrow(self):
        """The firm's backup key is on its server and in the owner's safe, never on this platform."""
        self.ensure_one()
        self.sudo().write({
            "backup_key_escrowed_at": fields.Datetime.now(),
            "backup_key_escrowed_by": self.env.user.id,
        })
        self.env["platform.log"]._record(_("Backup key put in the safe (declared)"), self)
        self._evaluate_health()
        return True

    def action_resume(self):
        self.ensure_one()
        if self.state != "suspended":
            raise UserError(t(self.env, _("Only a suspended firm can resume.")))
        provider, dns, _probe = self.env["platform.services"]._outside()
        try:
            provider.start_server(self.server_id)
        except ProviderError as error:
            raise UserError(t(self.env, error.message)) from None
        self.env["platform.services"]._save_dry_state(provider, dns)
        self.sudo().write({"state": "active"})
        self.env["platform.log"]._record(_("Firm resumed"), self)
        self._evaluate_health()
        return True

    def action_confirm_export_received(self):
        self.ensure_one()
        if self.export_state != "done":
            raise UserError(t(self.env, _("The export has not finished on the firm's server yet.")))
        self.sudo().write({"export_received_on": fields.Date.context_today(self)})
        self.env["platform.log"]._record(_("Export handed to the firm (declared)"), self, _("Digest %(digest)s", digest=self.export_sha256))
        return True

    def action_open_firm_wizard(self):
        """Opens a firm wizard named in the context, on this firm."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env["ir.model"]._get(self.env.context["firm_wizard"]).name,
            "res_model": self.env.context["firm_wizard"],
            "view_mode": "form",
            "target": "new",
            "context": {"default_firm_id": self.id},
        }

    def _start_first_admin_link(self):
        """Idempotent. The plaintext stays until shown once or until it expires; the server gets a hash."""
        self.ensure_one()
        firm = self.sudo()
        if not firm.first_admin_token and not firm.first_admin_revealed_at:
            firm.write({
                "first_admin_token": secrets.token_urlsafe(32),
                "first_admin_expires_at": fields.Datetime.now() + timedelta(hours=FIRST_ADMIN_LINK_HOURS),
            })
        return firm.first_admin_token
