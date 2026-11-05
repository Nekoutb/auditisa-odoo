import base64
import hashlib
import logging

import psycopg2

from odoo import api, fields, models, modules
from odoo.exceptions import UserError

from ..services import provisioning as engine
from ..services.catalogue import SIZES
from ..services.provider import ProviderError
from ..services.recipe import render_user_data
from ..services.validation import flatten_errors, onboarding_errors

_logger = logging.getLogger(__name__)

JOB_STATES = [
    ("waiting", "En cours"),
    ("done", "Terminée"),
    ("rolled_back", "Annulée, rien ne reste"),
    ("rollback_failed", "ÉCHEC DU NETTOYAGE"),
]
STEP_STATES = [
    ("pending", "À faire"),
    ("running", "En cours"),
    ("done", "Fait"),
    ("failed", "Échec"),
    ("undone", "Annulé"),
]
_RESOURCE_FIELDS = ("ssh_key_id", "firewall_id", "storage_id", "server_id", "server_ip")


class PlatformProvisionJob(models.Model):
    _name = "platform.provision.job"
    _description = "Mise en service"
    _order = "id desc"
    _rec_name = "firm_id"

    firm_id = fields.Many2one("platform.firm", "Cabinet", required=True, readonly=True, ondelete="restrict", index=True)
    state = fields.Selection(JOB_STATES, "État", required=True, default="waiting", readonly=True)
    started_by = fields.Many2one("res.users", "Lancée par", readonly=True, default=lambda self: self.env.user)
    is_simulation = fields.Boolean("Simulation", readonly=True)
    step_ids = fields.One2many("platform.provision.step", "job_id", "Étapes", readonly=True)
    leftovers = fields.Text("Ce qui reste chez le fournisseur", readonly=True)
    last_message = fields.Char("Dernier message", readonly=True)
    progress = fields.Float("Avancement", compute="_compute_progress")

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
            {"job_id": job.id, "sequence": index, "code": step["code"], "label": step["label"]}
            for index, step in enumerate(engine.new_steps())
        ])
        self.env["platform.log"]._record("Mise en service lancée", firm, "Simulation" if firm.is_simulation else "")
        return job

    # ------------------------------------------------------------------ running

    def _step_dicts(self):
        return [
            {
                "code": step.code, "label": step.label, "state": step.state, "attempts": step.attempts,
                "message": step.message or "", "started_at": step.started_at, "finished_at": step.finished_at,
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
                "message": data["message"],
                "started_at": data["started_at"],
                "finished_at": data["finished_at"],
            })
        self.firm_id.sudo().write({field: resources.get(field) or False for field in _RESOURCE_FIELDS})
        messages = [data["message"] for data in steps if data["message"] and data["state"] != "undone"]
        self.sudo().last_message = messages[-1][:200] if messages else False

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
            raise ProviderError("Identifiant du système (ea_platform.vultr_os_id) non configuré.")
        return int(value)

    def _allowlist(self):
        allowlist = self.firm_id._ssh_allowlist()
        if allowlist:
            return allowlist
        if self.firm_id.is_simulation:
            return ["198.51.100.1/32"]  # reserved for documentation: reaches nothing
        raise ProviderError("Aucune adresse d'opérateur configurée pour le port 22.")

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
            raise ProviderError("Aucune version signée n'a été choisie pour ce cabinet.")

    def _config_value(self, key, simulation_value):
        value = self.env["ir.config_parameter"].sudo().get_param(key)
        if value:
            return value
        if self.firm_id.is_simulation:
            return simulation_value
        raise ProviderError(f"Réglage manquant : {key}")

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
            "RELEASE_BASE_URL": self._config_value("ea_platform.release_base_url", "https://releases.example.invalid"),
            "HEARTBEAT_URL": self._config_value("ea_platform.heartbeat_url", "https://hb.example.invalid/platform/heartbeat"),
            "HEARTBEAT_TOKEN": firm.heartbeat_token,
            "FIRST_ADMIN_TOKEN_SHA256": hashlib.sha256(token.encode("ascii")).hexdigest(),
            "SSH_ALLOWLIST": " ".join(self._allowlist()),
            "S3_ENDPOINT": credentials.endpoint,
            "S3_BUCKET": credentials.bucket,
            "S3_ACCESS_KEY": credentials.access_key,
            "S3_SECRET_KEY": credentials.secret_key,
        }
        signing_key = self._config_value(
            "ea_platform.release_signing_public_key",
            "-----BEGIN PUBLIC KEY-----\nSIMULATION\n-----END PUBLIC KEY-----",
        )
        return render_user_data(values, firm.ssh_public_key, signing_key)

    def _heartbeat_seen(self):
        firm = self.firm_id
        if firm.is_simulation and not firm.last_heartbeat_at:
            firm._simulate_heartbeat(release=firm.desired_release_id.sha)
        return bool(firm.sudo().last_heartbeat_at)

    def _figures_problems(self):
        firm = self.firm_id.sudo()
        problems = []
        if firm.addon_release != firm.desired_release_id.sha:
            problems.append("le serveur n'annonce pas la version demandée")
        if firm.mail_enabled:
            problems.append("la messagerie est ouverte alors qu'elle doit être fermée")
        if not firm.cert_expires_on:
            problems.append("le certificat HTTPS n'est pas encore là")
        return problems

    def _activate(self):
        firm = self.firm_id.sudo()
        firm.write({"state": "active", "activated_at": fields.Datetime.now()})
        self.env["platform.log"]._record("Cabinet mis en service", firm)
        firm._evaluate_health()

    def _resources(self):
        firm = self.firm_id.sudo()
        return {field: firm[field] for field in _RESOURCE_FIELDS if firm[field]}

    def _lock(self):
        """Two runners on one job would create resources twice. Skips if another holds it."""
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("SELECT id FROM platform_provision_job WHERE id = %s FOR UPDATE NOWAIT", [self.id])
        except psycopg2.errors.LockNotAvailable:
            return False
        return True

    def _run(self):
        self.ensure_one()
        if self.state != "waiting" or not self._lock():
            return self.state
        try:
            provider, dns, probe = self.env["platform.services"]._outside()
        except ProviderError as error:
            self.sudo().last_message = str(error)[:200]
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
            detail = f"{failed[0]['label']} : {failed[0]['message']}" if failed else ""
            self.env["platform.log"]._record("Mise en service annulée, nettoyage complet", firm, detail[:500])
        elif result == engine.JOB_ROLLBACK_FAILED:
            self._flag_leftovers(ctx, steps)
        firm._evaluate_health()

    def _flag_leftovers(self, ctx, steps):
        firm = self.firm_id.sudo()
        lines = [s["message"] for s in steps if s["message"].startswith("Retour arrière impossible")]
        if ctx.resources.get("server_id"):
            lines.insert(0, f"Serveur {ctx.resources['server_id']} toujours chez le fournisseur")
        detail = "\n".join(lines) or "Ressources à vérifier chez le fournisseur"
        self.sudo().write({"state": "rollback_failed", "leftovers": detail})
        firm.write({"orphan_flag": True, "orphan_detail": detail})
        self.env["platform.log"]._record("ÉCHEC DU NETTOYAGE : ressources restantes", firm, detail[:500])

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
            raise UserError("Cette mise en service ne peut plus être annulée.")
        firm = self.firm_id.sudo()
        provider, dns, probe = self.env["platform.services"]._outside()
        resources = self._resources()
        steps = self._step_dicts()
        ctx = self._context(provider, dns, probe, resources)
        result, _orphans = engine.rollback(steps, ctx)
        self._save(steps, resources)
        self.env["platform.services"]._save_dry_state(provider, dns)
        if result == engine.JOB_ROLLED_BACK:
            self.sudo().write({"state": "rolled_back", "leftovers": False})
            firm.write({
                "orphan_flag": False, "orphan_detail": False,
                "first_admin_token": False, "first_admin_expires_at": False,
                "last_heartbeat_at": False, "last_heartbeat_timestamp": 0, "addon_release": False,
            })
            self.env["platform.log"]._record("Mise en service annulée, nettoyage complet", firm)
        else:
            self._flag_leftovers(ctx, steps)
        firm._evaluate_health()
        return True

    def action_retry(self):
        """A new attempt for the same firm, after a clean rollback."""
        self.ensure_one()
        if self.state != "rolled_back":
            raise UserError("Seule une mise en service annulée peut être relancée.")
        firm = self.firm_id.sudo()
        if firm.state != "provisioning":
            raise UserError("Ce cabinet n'est plus en cours de mise en service.")
        firm.write({"last_heartbeat_at": False, "last_heartbeat_timestamp": 0, "addon_release": False})
        job = self._start(firm)
        job._run()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": job.id, "view_mode": "form"}


class PlatformProvisionStep(models.Model):
    _name = "platform.provision.step"
    _description = "Étape de mise en service"
    _order = "sequence"
    _rec_name = "label"

    job_id = fields.Many2one("platform.provision.job", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(readonly=True)
    code = fields.Char(readonly=True, required=True)
    label = fields.Char("Étape", readonly=True, required=True)
    state = fields.Selection(STEP_STATES, "État", default="pending", readonly=True, required=True)
    attempts = fields.Integer("Tentatives", readonly=True)
    message = fields.Char("Message", readonly=True)
    started_at = fields.Datetime("Début", readonly=True)
    finished_at = fields.Datetime("Fin", readonly=True)
