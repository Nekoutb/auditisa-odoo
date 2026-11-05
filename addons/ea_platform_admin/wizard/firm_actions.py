from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.firm import DEFAULT_RETENTION_DAYS, MIN_RETENTION_DAYS
from ..services import provisioning as engine
from ..services.provider import ProviderError

DESTROY_WORD = "DETRUIRE"


class PlatformSuspendWizard(models.TransientModel):
    _name = "platform.suspend.wizard"
    _description = "Suspendre un cabinet"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    reason = fields.Text("Motif", required=True)

    def action_confirm(self):
        self.ensure_one()
        firm = self.firm_id.sudo()
        if firm.state != "active":
            raise UserError("Seul un cabinet actif peut être suspendu.")
        provider, dns, _probe = self.env["platform.services"]._outside()
        try:
            provider.stop_server(firm.server_id)
        except ProviderError as error:
            raise UserError(str(error)) from None
        self.env["platform.services"]._save_dry_state(provider, dns)
        firm.write({"state": "suspended"})
        self.env["platform.log"]._record("Cabinet suspendu", firm, self.reason, user=self.env.user)
        firm._evaluate_health()
        return {"type": "ir.actions.act_window_close"}


class PlatformBreakglassWizard(models.TransientModel):
    """To be filled BEFORE opening the server. The server counts logins, and the board compares."""

    _name = "platform.breakglass.wizard"
    _description = "Ouvrir un accès d'urgence"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    reason = fields.Text("Motif", required=True)
    firm_informed = fields.Boolean("Le cabinet a été informé")
    command = fields.Char("Commande à utiliser", compute="_compute_command")

    @api.depends("firm_id")
    def _compute_command(self):
        for wizard in self:
            firm = wizard.firm_id
            wizard.command = (
                f"ssh -i ~/.ssh/auditisa-{firm.slug} root@{firm.platform_host}" if firm else False
            )

    def action_confirm(self):
        self.ensure_one()
        firm = self.firm_id
        self.env["platform.breakglass"].sudo().create({
            "firm_id": firm.id,
            "user_id": self.env.user.id,
            "reason": self.reason,
            "firm_informed": self.firm_informed,
        })
        self.env["platform.log"]._record("Accès d'urgence ouvert", firm, self.reason, user=self.env.user)
        firm._evaluate_health()
        return {"type": "ir.actions.act_window_close"}


class PlatformFirstAdminLink(models.TransientModel):
    """Shows the first administrator's link once. The stored copy is erased as it is shown."""

    _name = "platform.first.admin.link"
    _description = "Lien du premier administrateur"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    revealed = fields.Boolean(readonly=True)
    link = fields.Char("Lien à usage unique", readonly=True)
    expires_at = fields.Datetime("Expire le", readonly=True)

    def action_reveal(self):
        self.ensure_one()
        firm = self.firm_id.sudo()
        if not firm.first_admin_ready or not firm.first_admin_token:
            raise UserError(
                "Ce lien n'est plus disponible : il a déjà été affiché ou il a expiré. Pour en créer un nouveau, "
                "ouvrez un accès d'urgence puis lancez firm-first-admin-link sur le serveur du cabinet."
            )
        self.write({
            "revealed": True,
            "link": f"https://{firm.platform_host}/ea-firm/first-admin/{firm.first_admin_token}",
            "expires_at": firm.first_admin_expires_at,
        })
        firm.write({"first_admin_token": False, "first_admin_revealed_at": fields.Datetime.now()})
        self.env["platform.log"]._record("Lien du premier administrateur affiché", firm, user=self.env.user)
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_close(self):
        """Nothing of the link outlives the screen."""
        self.write({"link": False})
        return {"type": "ir.actions.act_window_close"}


class PlatformOffboardWizard(models.TransientModel):
    """First confirmation: starts the exit. Nothing is destroyed here."""

    _name = "platform.offboard.wizard"
    _description = "Sortie d'un cabinet"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    slug = fields.Char(related="firm_id.slug")
    typed_slug = fields.Char("Tapez l'identifiant du cabinet pour confirmer")
    retention_days = fields.Integer("Durée de conservation après l'export (jours)", default=DEFAULT_RETENTION_DAYS, required=True)
    reason = fields.Text("Motif", required=True)

    def action_confirm(self):
        self.ensure_one()
        firm = self.firm_id.sudo()
        if firm.state not in ("active", "suspended"):
            raise UserError("Seul un cabinet actif ou suspendu peut sortir.")
        if (self.typed_slug or "").strip() != firm.slug:
            raise UserError("L'identifiant tapé ne correspond pas : rien n'a été fait.")
        if self.retention_days < MIN_RETENTION_DAYS:
            raise UserError(f"La durée de conservation est d'au moins {MIN_RETENTION_DAYS} jours.")
        if firm.state == "suspended":
            provider, dns, _probe = self.env["platform.services"]._outside()
            try:
                provider.start_server(firm.server_id)
            except ProviderError as error:
                raise UserError(str(error)) from None
            self.env["platform.services"]._save_dry_state(provider, dns)
        firm.write({
            "state": "offboarding",
            "offboard_requested_at": fields.Datetime.now(),
            "offboard_retention_days": self.retention_days,
            "export_requested": True,
        })
        self.env["platform.log"]._record(
            "Sortie du cabinet lancée", firm, f"{self.retention_days} jours de conservation. {self.reason}",
            user=self.env.user,
        )
        firm._evaluate_health()
        return {"type": "ir.actions.act_window_close"}


class PlatformDestroyWizard(models.TransientModel):
    """Second confirmation: the slug, then the word. Only once the export is out and time is up."""

    _name = "platform.destroy.wizard"
    _description = "Destruction du serveur d'un cabinet"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    slug = fields.Char(related="firm_id.slug")
    step = fields.Selection([("slug", "Identifiant"), ("word", "Confirmation finale")], default="slug", required=True)
    typed_slug = fields.Char("Tapez l'identifiant du cabinet")
    typed_word = fields.Char(f"Tapez {DESTROY_WORD} en majuscules")

    def _check_possible(self):
        firm = self.firm_id.sudo()
        if firm.state != "offboarding":
            raise UserError("Ce cabinet n'est pas en sortie.")
        if firm.export_state != "done":
            raise UserError("L'export n'est pas terminé sur le serveur du cabinet.")
        if not firm.export_received_on:
            raise UserError("La remise de l'export au cabinet n'a pas été confirmée.")
        if not firm.destroy_after or firm.destroy_after > fields.Date.context_today(self):
            raise UserError(f"La durée de conservation court jusqu'au {firm.destroy_after}.")

    def action_next(self):
        self.ensure_one()
        self._check_possible()
        if (self.typed_slug or "").strip() != self.firm_id.slug:
            raise UserError("L'identifiant tapé ne correspond pas : rien n'a été fait.")
        self.step = "word"
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_destroy(self):
        self.ensure_one()
        self._check_possible()
        if self.step != "word" or (self.typed_slug or "").strip() != self.firm_id.slug:
            raise UserError("Passez d'abord par la confirmation de l'identifiant.")
        if self.typed_word != DESTROY_WORD:
            raise UserError(f"Tapez exactement {DESTROY_WORD} : rien n'a été fait.")
        firm = self.firm_id.sudo()
        provider, dns, probe = self.env["platform.services"]._outside()
        keys = ("ssh_key_id", "firewall_id", "storage_id", "server_id", "server_ip")
        resources = {key: firm[key] for key in keys if firm[key]}
        ctx = engine.Context(
            provider, dns, probe, resources, {}, {"slug": firm.slug, "host": firm.platform_host},
            fields.Datetime.now(),
        )
        leftovers = engine.destroy_resources(ctx)
        self.env["platform.services"]._save_dry_state(provider, dns)
        if leftovers:
            # No error raised here: that would roll back the record of what was already removed.
            detail = "\n".join(leftovers)
            firm.write({
                "orphan_flag": True, "orphan_detail": detail,
                **{key: resources.get(key) or False for key in keys},
            })
            self.env["platform.log"]._record("Destruction INCOMPLÈTE", firm, detail[:500], user=self.env.user)
            firm._evaluate_health()
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Destruction incomplète",
                    "message": detail,
                    "type": "danger",
                    "sticky": True,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        firm.write({
            "state": "archived",
            "server_id": False, "server_ip": False, "ssh_key_id": False, "firewall_id": False, "storage_id": False,
            "heartbeat_token": False, "first_admin_token": False, "export_requested": False,
            "orphan_flag": False, "orphan_detail": False, "desired_release_id": False,
        })
        self.env["platform.log"]._record("Serveur détruit, cabinet archivé", firm, user=self.env.user)
        firm._evaluate_health()
        return {"type": "ir.actions.act_window_close"}
