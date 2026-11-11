from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.firm import DEFAULT_RETENTION_DAYS, MIN_RETENTION_DAYS
from ..models.i18n import t
from ..services import firm_keys
from ..services import provisioning as engine
from ..services.messages import _, dumps_list
from ..services.provider import ProviderError

DESTROY_WORD = "DESTROY"


class PlatformSuspendWizard(models.TransientModel):
    _name = "platform.suspend.wizard"
    _description = "Suspend a firm"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    reason = fields.Text("Reason", required=True)

    def action_confirm(self):
        self.ensure_one()
        firm = self.firm_id.sudo()
        if firm.state != "active":
            raise UserError(t(self.env, _("Only an active firm can be suspended.")))
        provider, dns, _probe = self.env["platform.services"]._outside()
        try:
            provider.stop_server(firm.server_id)
        except ProviderError as error:
            raise UserError(t(self.env, error.message)) from None
        self.env["platform.services"]._save_dry_state(provider, dns)
        firm.write({"state": "suspended"})
        self.env["platform.log"]._record(_("Firm suspended"), firm, self.reason, user=self.env.user)
        firm._evaluate_health()
        return {"type": "ir.actions.act_window_close"}


class PlatformBreakglassWizard(models.TransientModel):
    """To be filled BEFORE opening the server. The server counts logins, and the board compares."""

    _name = "platform.breakglass.wizard"
    _description = "Open a break-glass access"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    reason = fields.Text("Reason", required=True)
    firm_informed = fields.Boolean("The firm has been told")
    command = fields.Char("Command to use", compute="_compute_command")

    @api.depends("firm_id")
    def _compute_command(self):
        for wizard in self:
            firm = wizard.firm_id
            if firm and firm.ssh_by_console:
                # The console made this firm's key: the developer runs this on the console's server.
                key = firm_keys.key_path(firm._firm_keys_dir(), firm.slug)
                wizard.command = f"sudo -u odoo ssh -i {key} root@{firm.platform_host}"
            else:
                wizard.command = f"ssh -i ~/.ssh/auditisa-{firm.slug} root@{firm.platform_host}" if firm else False

    def action_confirm(self):
        self.ensure_one()
        firm = self.firm_id
        self.env["platform.breakglass"].sudo().create({
            "firm_id": firm.id,
            "user_id": self.env.user.id,
            "reason": self.reason,
            "firm_informed": self.firm_informed,
        })
        self.env["platform.log"]._record(_("Break-glass access opened"), firm, self.reason, user=self.env.user)
        firm._evaluate_health()
        return {"type": "ir.actions.act_window_close"}


class PlatformFirstAdminLink(models.TransientModel):
    """Shows the first administrator's link once. The stored copy is erased as it is shown."""

    _name = "platform.first.admin.link"
    _description = "First administrator's link"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    revealed = fields.Boolean(readonly=True)
    link = fields.Char("One-time link", readonly=True)
    expires_at = fields.Datetime("Expires on", readonly=True)

    def action_reveal(self):
        self.ensure_one()
        firm = self.firm_id.sudo()
        if not firm.first_admin_ready or not firm.first_admin_token:
            raise UserError(t(self.env, _(
                "This link is no longer available: it has already been shown or it has expired. To make a new one, "
                "open a break-glass access then run firm-first-admin-link on the firm's server."
            )))
        self.write({
            "revealed": True,
            "link": f"https://{firm.platform_host}/ea-firm/first-admin/{firm.first_admin_token}",
            "expires_at": firm.first_admin_expires_at,
        })
        firm.write({"first_admin_token": False, "first_admin_revealed_at": fields.Datetime.now()})
        self.env["platform.log"]._record(_("First administrator's link shown"), firm, user=self.env.user)
        return {
            "type": "ir.actions.act_window",
            "name": self.env["ir.model"]._get(self._name).name,
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
    _description = "Firm's exit"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    slug = fields.Char(related="firm_id.slug")
    typed_slug = fields.Char("Type the firm's slug to confirm")
    retention_days = fields.Integer("Retention after the export (days)", default=DEFAULT_RETENTION_DAYS, required=True)
    reason = fields.Text("Reason", required=True)

    def action_confirm(self):
        self.ensure_one()
        firm = self.firm_id.sudo()
        if firm.state not in ("active", "suspended"):
            raise UserError(t(self.env, _("Only an active or suspended firm can leave.")))
        if (self.typed_slug or "").strip() != firm.slug:
            raise UserError(t(self.env, _("The slug typed does not match: nothing was done.")))
        if self.retention_days < MIN_RETENTION_DAYS:
            raise UserError(t(self.env, _("The retention period is at least %(days)s days.", days=MIN_RETENTION_DAYS)))
        if firm.state == "suspended":
            provider, dns, _probe = self.env["platform.services"]._outside()
            try:
                provider.start_server(firm.server_id)
            except ProviderError as error:
                raise UserError(t(self.env, error.message)) from None
            self.env["platform.services"]._save_dry_state(provider, dns)
        firm.write({
            "state": "offboarding",
            "offboard_requested_at": fields.Datetime.now(),
            "offboard_retention_days": self.retention_days,
            "export_requested": True,
        })
        self.env["platform.log"]._record(
            _("Firm's exit started"), firm,
            _("%(days)s days of retention. %(reason)s", days=self.retention_days, reason=self.reason),
            user=self.env.user,
        )
        firm._evaluate_health()
        return {"type": "ir.actions.act_window_close"}


class PlatformDestroyWizard(models.TransientModel):
    """Second confirmation: the slug, then the word. Only once the export is out and time is up."""

    _name = "platform.destroy.wizard"
    _description = "Destroying a firm's server"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    slug = fields.Char(related="firm_id.slug")
    step = fields.Selection([("slug", "Slug"), ("word", "Final confirmation")], default="slug", required=True)
    typed_slug = fields.Char("Type the firm's slug")
    typed_word = fields.Char("Type DESTROY in capitals")

    def _check_possible(self):
        firm = self.firm_id.sudo()
        if firm.state != "offboarding":
            raise UserError(t(self.env, _("This firm is not leaving.")))
        if firm.export_state != "done":
            raise UserError(t(self.env, _("The export has not finished on the firm's server.")))
        if not firm.export_received_on:
            raise UserError(t(self.env, _("Handing the export to the firm has not been confirmed.")))
        if not firm.destroy_after or firm.destroy_after > fields.Date.context_today(self):
            raise UserError(t(self.env, _("The retention period runs until %(date)s.", date=firm.destroy_after)))

    def action_next(self):
        self.ensure_one()
        self._check_possible()
        if (self.typed_slug or "").strip() != self.firm_id.slug:
            raise UserError(t(self.env, _("The slug typed does not match: nothing was done.")))
        self.step = "word"
        return {
            "type": "ir.actions.act_window",
            "name": self.env["ir.model"]._get(self._name).name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_destroy(self):
        self.ensure_one()
        self._check_possible()
        if self.step != "word" or (self.typed_slug or "").strip() != self.firm_id.slug:
            raise UserError(t(self.env, _("Go through the slug confirmation first.")))
        if self.typed_word != DESTROY_WORD:
            raise UserError(t(self.env, _("Type exactly %(word)s: nothing was done.", word=DESTROY_WORD)))
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
            firm.write({
                "orphan_flag": True, "orphan_detail_raw": dumps_list(leftovers),
                **{key: resources.get(key) or False for key in keys},
            })
            self.env["platform.log"]._record(_("Destruction INCOMPLETE"), firm, leftovers[0], user=self.env.user)
            firm._evaluate_health()
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": t(self.env, _("Destruction incomplete")),
                    "message": "\n".join(t(self.env, item) for item in leftovers),
                    "type": "danger",
                    "sticky": True,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        firm.write({
            "state": "archived",
            "server_id": False, "server_ip": False, "ssh_key_id": False, "firewall_id": False, "storage_id": False,
            "heartbeat_token": False, "first_admin_token": False, "export_requested": False,
            "orphan_flag": False, "orphan_detail_raw": False, "desired_release_id": False,
        })
        self.env["platform.log"]._record(_("Server destroyed, firm archived"), firm, user=self.env.user)
        firm._drop_console_key()
        firm._evaluate_health()
        return {"type": "ir.actions.act_window_close"}
