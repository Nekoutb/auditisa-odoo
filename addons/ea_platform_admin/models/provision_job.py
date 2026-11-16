import base64
import hashlib
import logging

import psycopg2

from odoo import api, fields, models, modules
from odoo.exceptions import UserError

from ..services import provisioning as engine
from ..services.catalogue import SIZES
from ..services.messages import Msg, _, dumps, dumps_list, loads
from ..services.provider import ProviderError
from ..services.recipe import render_user_data
from ..services.validation import flatten_errors, onboarding_errors
from .i18n import read, t
from .platform_services import RELEASE_URL_SECONDS_FIRST_BOOT

_logger = logging.getLogger(__name__)

JOB_STATES = [
    ("waiting", "Under way"),
    ("done", "Finished"),
    ("rolled_back", "Cancelled, nothing remains"),
    ("rollback_failed", "CLEAN-UP FAILED"),
]
STEP_STATES = [
    ("pending", "To do"),
    ("running", "Running"),
    ("done", "Done"),
    ("failed", "Failed"),
    ("undone", "Undone"),
]
_RESOURCE_FIELDS = ("ssh_key_id", "firewall_id", "storage_id", "server_id", "server_ip")
_RUN_LOCK = 0x50524F56  # "PROV": first key of the advisory lock of a provisioning run


class PlatformProvisionJob(models.Model):
    _name = "platform.provision.job"
    _description = "Provisioning run"
    _order = "id desc"
    _rec_name = "firm_id"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True, ondelete="restrict", index=True)
    state = fields.Selection(JOB_STATES, "State", required=True, default="waiting", readonly=True)
    started_by = fields.Many2one("res.users", "Started by", readonly=True, default=lambda self: self.env.user)
    is_simulation = fields.Boolean("Simulation", readonly=True)
    step_ids = fields.One2many("platform.provision.step", "job_id", "Steps", readonly=True)
    leftovers_raw = fields.Text("What remains at the provider (source)", readonly=True)
    leftovers = fields.Text("What remains at the provider", compute="_compute_text")
    last_message_raw = fields.Text("Last message (source)", readonly=True)
    last_message = fields.Char("Last message", compute="_compute_text")
    progress = fields.Float("Progress", compute="_compute_progress")

    @api.depends("leftovers_raw", "last_message_raw")
    @api.depends_context("lang")
    def _compute_text(self):
        for job in self:
            job.leftovers = read(self.env, job.leftovers_raw)
            job.last_message = read(self.env, job.last_message_raw)

    @api.depends("step_ids.state")
    def _compute_progress(self):
        for job in self:
            total = len(job.step_ids)
            job.progress = 100.0 * len(job.step_ids.filtered(lambda s: s.state == "done")) / total if total else 0.0

    @api.model
    def _start(self, firm):
        job = self.sudo().create({
            "firm_id": firm.id,
            "is_simulation": firm.is_simulation,
            "started_by": self.env.user.id,
        })
        self.env["platform.provision.step"].sudo().create([
            {"job_id": job.id, "sequence": index, "code": step["code"], "label_source": dumps(step["label"])}
            for index, step in enumerate(engine.new_steps())
        ])
        self.env["platform.log"]._record(_("Provisioning started"), firm, _("Simulation") if firm.is_simulation else "")
        return job

    # ------------------------------------------------------------------ running

    def _step_dicts(self):
        return [
            {
                "code": step.code, "label": Msg(step.label_source), "state": step.state, "attempts": step.attempts,
                "message": (loads(step.message_raw) or [""])[0], "started_at": step.started_at, "finished_at": step.finished_at,
            }
            for step in self.step_ids.sorted("sequence")
        ]

    def _save(self, steps, resources):
        self.ensure_one()
        by_code = {step.code: step for step in self.step_ids}
        for data in steps:
            by_code[data["code"]].sudo().write({
                "state": data["state"],
                "attempts": data["attempts"],
                "message_raw": dumps(data["message"]),
                "started_at": data["started_at"],
                "finished_at": data["finished_at"],
            })
        self.firm_id.sudo().write({field: resources.get(field) or False for field in _RESOURCE_FIELDS})
        messages = [data["message"] for data in steps if data["message"] and data["state"] != "undone"]
        self.sudo().last_message_raw = dumps(messages[-1]) if messages else False

    def _commit(self):
        """A crash then costs at most the step in progress. Tests have no real commit."""
        if not modules.module.current_test:
            self.env.cr.commit()

    def _context(self, provider, dns, probe, resources):
        self.ensure_one()
        firm = self.firm_id.sudo()
        size = SIZES[firm.size]
        config = {
            "slug": firm.slug,
            "host": firm.platform_host,
            "region": firm.region,
            "plan": size["plan"],
            "os_id": self._os_id(firm),
            "ssh_public_key": firm.ssh_public_key,
            "ssh_allowlist": self._allowlist(),
        }
        hooks = {
            "validate": lambda: self._validation_errors(),
            "check_release": lambda: self._check_release(),
            "prepare_first_admin": firm._start_first_admin_link,
            "user_data": self._user_data,
            "heartbeat_seen": self._heartbeat_seen,
            "figures_problems": self._figures_problems,
            "activate": self._activate,
        }
        return engine.Context(provider, dns, probe, resources, hooks, config, fields.Datetime.now())

    def _os_id(self, firm):
        value = self.env["ir.config_parameter"].sudo().get_param("ea_platform.vultr_os_id")
        if firm.is_simulation:
            return int(value or 0)
        if not value:
            raise ProviderError(_("Operating system id (ea_platform.vultr_os_id) not set."))
        return int(value)

    def _allowlist(self):
        allowlist = self.firm_id._ssh_allowlist()
        if allowlist:
            return allowlist
        if self.firm_id.is_simulation:
            return ["198.51.100.1/32"]  # reserved for documentation: reaches nothing
        raise ProviderError(_("No operator address set for port 22."))

    def _validation_errors(self):
        firm = self.firm_id.sudo()
        all_firms = firm.with_context(active_test=False).search([("id", "!=", firm.id)])
        errors = onboarding_errors(
            {
                "name": firm.name, "slug": firm.slug, "contact_name": firm.contact_name,
                "contact_email": firm.contact_email, "region": firm.region, "size": firm.size, "lang": firm.lang,
                "allowed_email_domains": firm.allowed_email_domains, "ssh_public_key": firm.ssh_public_key,
            },
            existing_slugs=all_firms.mapped("slug"),
            existing_fingerprints=all_firms.mapped("ssh_key_fingerprint"),
        )
        return flatten_errors(errors)

    def _check_release(self):
        if not self.firm_id.desired_release_id:
            raise ProviderError(_("No release has been chosen for this firm."))

    def _config_value(self, key, simulation_value):
        value = self.env["ir.config_parameter"].sudo().get_param(key)
        if value:
            return value
        if self.firm_id.is_simulation:
            return simulation_value
        raise ProviderError(_("Missing setting: %(key)s", key=key))

    def _user_data(self, credentials):
        firm = self.firm_id.sudo()
        token = firm.first_admin_token
        release = firm.desired_release_id
        values = {
            "FIRM_SLUG": firm.slug,
            "FIRM_NAME_B64": base64.b64encode(firm.name.encode("utf-8")).decode("ascii"),
            "FIRM_HOST": firm.platform_host,
            "FIRM_SIZE": firm.size,
            "FIRM_LANG": firm.lang,
            "FIRM_ADMIN_EMAIL": firm.contact_email.strip(),
            "FIRM_ALLOWED_DOMAINS": " ".join(firm.allowed_email_domains.split()),
            "RELEASE_SHA": release.sha,
            "RELEASE_BUNDLE_SHA256": release.bundle_sha256,
            "RELEASE_BASE_URL": self._release_base_url(),
            "HEARTBEAT_URL": self._config_value("ea_platform.heartbeat_url", "https://hb.example.invalid/platform/heartbeat"),
            "HEARTBEAT_TOKEN": firm.heartbeat_token,
            "FIRST_ADMIN_TOKEN_SHA256": hashlib.sha256(token.encode("ascii")).hexdigest(),
            "SSH_ALLOWLIST": " ".join(self._allowlist()),
            "S3_ENDPOINT": credentials.endpoint,
            "S3_REGION": credentials.region,
            "S3_BUCKET": credentials.bucket,
            "S3_ACCESS_KEY": credentials.access_key,
            "S3_SECRET_KEY": credentials.secret_key,
        }
        # The releases bucket is private: the first boot downloads with an address that expires, and
        # installs the file only if its SHA-256 is RELEASE_BUNDLE_SHA256.
        url = self.env["platform.services"]._release_url(release, RELEASE_URL_SECONDS_FIRST_BOOT)
        if url:
            values["RELEASE_BUNDLE_URL_B64"] = base64.b64encode(url.encode("ascii")).decode("ascii")
        elif not firm.is_simulation:
            raise ProviderError(_("No download address for the release: check the Wasabi settings."), retryable=True)
        return render_user_data(values, firm.ssh_public_key)

    def _release_base_url(self):
        url = self.env["platform.services"]._release_base_url()
        if not url:
            raise ProviderError(_("Missing setting: %(key)s", key="ea_platform.releases_bucket"))
        return url

    def _heartbeat_seen(self):
        firm = self.firm_id
        if firm.is_simulation and not firm.last_heartbeat_at:
            firm._simulate_heartbeat(release=firm.desired_release_id.sha)
        return bool(firm.sudo().last_heartbeat_at)

    def _figures_problems(self):
        firm = self.firm_id.sudo()
        problems = []
        if firm.addon_release != firm.desired_release_id.sha:
            problems.append(_("the server does not report the requested release"))
        if firm.mail_enabled:
            problems.append(_("mail is open when it must be closed"))
        if not firm.cert_expires_on:
            problems.append(_("the HTTPS certificate is not there yet"))
        return problems

    def _activate(self):
        firm = self.firm_id.sudo()
        firm.write({"state": "active", "activated_at": fields.Datetime.now()})
        self.env["platform.log"]._record(_("Firm went live"), firm)
        firm._evaluate_health()

    def _resources(self):
        firm = self.firm_id.sudo()
        return {field: firm[field] for field in _RESOURCE_FIELDS if firm[field]}

    def _lock(self):
        """Two runners on one job would create resources twice. Skips if another holds it.

        A session-level advisory lock, held until _unlock: a row lock ended at the commit made after
        each step, and on the first real firm (2026-11-09) the cron took the job over from the
        screen's own run in that gap and created a second server.
        """
        self.env.cr.execute("SELECT pg_try_advisory_lock(%s, %s)", [_RUN_LOCK, self.id])
        return bool(self.env.cr.fetchone()[0])

    def _unlock(self):
        try:
            self.env.cr.execute("SELECT pg_advisory_unlock(%s, %s)", [_RUN_LOCK, self.id])
        except psycopg2.Error:
            # An aborted transaction: its work is lost anyway, the lock must not be.
            if modules.module.current_test:
                raise
            self.env.cr.rollback()
            self.env.cr.execute("SELECT pg_advisory_unlock(%s, %s)", [_RUN_LOCK, self.id])

    def _run(self):
        self.ensure_one()
        if self.state != "waiting" or not self._lock():
            return self.state
        try:
            # Another runner may have moved the job on while we waited: read it again.
            self.env.invalidate_all()
            if self.state != "waiting":
                return self.state
            return self._run_locked()
        finally:
            self._unlock()

    def _mode_changed(self):
        """A real run must never be carried on, nor cleaned up, with the simulated services, and
        the reverse. On 2026-11-09 a worker that still believed in simulation "cleaned up" a real
        job: it removed nothing real, said nothing remained, and left a billed server behind."""
        return bool(self.is_simulation) != bool(self.env["platform.services"]._is_simulation())

    def _mode_message(self):
        return _("The platform's mode (simulation or real) is not the one this run started in: nothing done.")

    def _run_locked(self):
        if self._mode_changed():
            self.sudo().last_message_raw = dumps(self._mode_message())
            return self.state
        try:
            provider, dns, probe = self.env["platform.services"]._outside()
        except ProviderError as error:
            self.sudo().last_message_raw = dumps(error.message)
            return self.state
        resources = self._resources()
        steps = self._step_dicts()
        ctx = self._context(provider, dns, probe, resources)

        def on_change():
            self._save(steps, resources)
            self.env["platform.services"]._save_dry_state(provider, dns)
            self._commit()

        result = engine.advance(steps, ctx, on_change=on_change)
        on_change()
        self._finish(result, steps, ctx)
        return self.state

    def _finish(self, result, steps, ctx):
        firm = self.firm_id.sudo()
        if result == engine.JOB_DONE:
            self.sudo().state = "done"
        elif result == engine.JOB_ROLLED_BACK:
            self.sudo().state = "rolled_back"
            firm.write({"first_admin_token": False, "first_admin_expires_at": False})
            failed = [s for s in steps if s["state"] == engine.FAILED]
            detail = _("%(step)s: %(what)s", step=failed[0]["label"], what=failed[0]["message"]) if failed else ""
            self.env["platform.log"]._record(_("Provisioning cancelled, full clean-up"), firm, detail)
        elif result == engine.JOB_ROLLBACK_FAILED:
            self._flag_leftovers(ctx, steps)
        firm._evaluate_health()

    def _flag_leftovers(self, ctx, steps):
        firm = self.firm_id.sudo()
        lines = [s["message"] for s in steps if s["message"].startswith("Rollback impossible")]
        if ctx.resources.get("server_id"):
            lines.insert(0, _("Server %(id)s still at the provider", id=ctx.resources["server_id"]))
        lines = lines or [_("Resources to check at the provider")]
        detail = dumps_list(lines)
        self.sudo().write({"state": "rollback_failed", "leftovers_raw": detail})
        firm.write({"orphan_flag": True, "orphan_detail_raw": detail})
        self.env["platform.log"]._record(_("CLEAN-UP FAILED: resources remain"), firm, lines[0])

    @api.model
    def _cron_run_jobs(self):
        for job in self.search([("state", "=", "waiting")]):
            try:
                job._run()
                self._commit()
            except Exception:
                _logger.exception("Provisioning job %s stopped; it will be resumed", job.id)
                if not modules.module.current_test:
                    self.env.cr.rollback()

    # ------------------------------------------------------------------ actions of the screens

    def action_resume(self):
        """Carries on from the first unfinished step. Safe at any time."""
        self.ensure_one()
        self._run()
        return True

    def action_rollback(self):
        """Cleans up: on a job that is stuck, and again after a clean-up that left something."""
        self.ensure_one()
        if self.state not in ("waiting", "rollback_failed"):
            raise UserError(t(self.env, _("This provisioning run can no longer be cancelled.")))
        if not self._lock():
            raise UserError(t(self.env, _("This provisioning run is moving right now: try again in a minute.")))
        try:
            return self._rollback_locked()
        finally:
            self._unlock()

    def _rollback_locked(self):
        if self._mode_changed():
            raise UserError(t(self.env, self._mode_message()))
        firm = self.firm_id.sudo()
        provider, dns, probe = self.env["platform.services"]._outside()
        resources = self._resources()
        steps = self._step_dicts()
        ctx = self._context(provider, dns, probe, resources)
        result, _orphans = engine.rollback(steps, ctx)
        self._save(steps, resources)
        self.env["platform.services"]._save_dry_state(provider, dns)
        if result == engine.JOB_ROLLED_BACK:
            self.sudo().write({"state": "rolled_back", "leftovers_raw": False})
            firm.write({
                "orphan_flag": False, "orphan_detail_raw": False,
                "first_admin_token": False, "first_admin_expires_at": False,
                "last_heartbeat_at": False, "last_heartbeat_timestamp": 0, "addon_release": False,
            })
            self.env["platform.log"]._record(_("Provisioning cancelled, full clean-up"), firm)
        else:
            self._flag_leftovers(ctx, steps)
        firm._evaluate_health()
        return True

    def action_retry(self):
        """A new attempt for the same firm, after a clean rollback."""
        self.ensure_one()
        if self.state != "rolled_back":
            raise UserError(t(self.env, _("Only a cancelled provisioning run can be restarted.")))
        firm = self.firm_id.sudo()
        if firm.state != "provisioning":
            raise UserError(t(self.env, _("This firm is no longer being provisioned.")))
        firm.write({"last_heartbeat_at": False, "last_heartbeat_timestamp": 0, "addon_release": False})
        job = self._start(firm)
        job._run()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": job.id, "view_mode": "form", "views": [(False, "form")]}


class PlatformProvisionStep(models.Model):
    _name = "platform.provision.step"
    _description = "Provisioning step"
    _order = "sequence"
    _rec_name = "label_source"

    job_id = fields.Many2one("platform.provision.job", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(readonly=True)
    code = fields.Char(readonly=True, required=True)
    label_source = fields.Char("Step (source)", readonly=True, required=True)
    label = fields.Char("Step", compute="_compute_text")
    state = fields.Selection(STEP_STATES, "State", default="pending", readonly=True, required=True)
    attempts = fields.Integer("Attempts", readonly=True)
    message_raw = fields.Text("Message (source)", readonly=True)
    message = fields.Char("Message", compute="_compute_text")
    started_at = fields.Datetime("Started", readonly=True)
    finished_at = fields.Datetime("Finished", readonly=True)

    @api.depends("label_source", "message_raw")
    @api.depends_context("lang")
    def _compute_text(self):
        for step in self:
            step.label = read(self.env, step.label_source)
            step.message = read(self.env, step.message_raw)
