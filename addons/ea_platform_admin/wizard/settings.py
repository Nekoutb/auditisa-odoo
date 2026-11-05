import os

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.i18n import t
from ..models.platform_services import CREDENTIAL_CLOUDFLARE, CREDENTIAL_VULTR, PARAM_PROVIDER
from ..services.messages import _
from ..services.validation import parse_allowlist

# field -> parameter. There is no field for any token: those live in root-only files.
PARAMS = {
    "base_domain": "ea_platform.base_domain",
    "heartbeat_url": "ea_platform.heartbeat_url",
    "release_base_url": "ea_platform.release_base_url",
    "release_signing_public_key": "ea_platform.release_signing_public_key",
    "ssh_allowlist": "ea_platform.ssh_allowlist",
    "vultr_os_id": "ea_platform.vultr_os_id",
    "vultr_storage_cluster": "ea_platform.vultr_storage_cluster",
    "dns_zone_id": "ea_platform.dns_zone_id",
}


class PlatformSettings(models.TransientModel):
    _name = "platform.settings"
    _description = "Platform settings"

    provider = fields.Selection(
        [("dry_run", "Simulation"), ("vultr", "Real: Vultr and Cloudflare")],
        "Provider", default=lambda self: self._param(PARAM_PROVIDER, "dry_run"), required=True,
    )
    base_domain = fields.Char("Base domain", default=lambda self: self._param("ea_platform.base_domain", "auditisa.com"), required=True)
    heartbeat_url = fields.Char("Heartbeat receiving address", default=lambda self: self._param("ea_platform.heartbeat_url"))
    release_base_url = fields.Char("Releases address", default=lambda self: self._param("ea_platform.release_base_url"))
    release_signing_public_key = fields.Text(
        "Release signing public key",
        default=lambda self: self._param("ea_platform.release_signing_public_key"),
    )
    ssh_allowlist = fields.Text("Operator addresses for port 22", default=lambda self: self._param("ea_platform.ssh_allowlist"))
    vultr_os_id = fields.Char("Server operating system (Vultr id)", default=lambda self: self._param("ea_platform.vultr_os_id"))
    vultr_storage_cluster = fields.Char("Object storage cluster (Vultr id)", default=lambda self: self._param("ea_platform.vultr_storage_cluster"))
    dns_zone_id = fields.Char("DNS zone (Cloudflare id)", default=lambda self: self._param("ea_platform.dns_zone_id"))
    confirm_real = fields.Boolean("I want to create real servers, billed by the provider.")

    @api.model
    def _param(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def action_save(self):
        self.ensure_one()
        _cidrs, errors = parse_allowlist(self.ssh_allowlist) if self.ssh_allowlist else ([], [])
        if errors:
            raise UserError("\n".join(t(self.env, error) for error in errors))
        for url in (self.heartbeat_url, self.release_base_url):
            if url and not url.startswith("https://"):
                raise UserError(t(self.env, _("This address must start with https://: %(url)s", url=url)))
        if self.provider == "vultr":
            self._check_real_mode()
        params = self.env["ir.config_parameter"].sudo()
        before = params.get_param(PARAM_PROVIDER, "dry_run")
        for field, key in PARAMS.items():
            params.set_param(key, self[field] or False)
        params.set_param(PARAM_PROVIDER, self.provider)
        self.env["platform.log"]._record(
            _("Settings changed"),
            detail=_("Provider: %(before)s -> %(after)s", before=before, after=self.provider) if before != self.provider else "",
        )
        return {"type": "ir.actions.client", "tag": "reload"}

    def _check_real_mode(self):
        """The door to real servers: every setting, both token files, and an explicit tick."""
        if not self.confirm_real:
            raise UserError(t(self.env, _("Tick the confirmation to go real.")))
        missing = [
            self._fields[field]._description_string(self.env)
            for field in ("heartbeat_url", "release_base_url", "release_signing_public_key", "ssh_allowlist",
                          "vultr_os_id", "vultr_storage_cluster", "dns_zone_id")
            if not self[field]
        ]
        if missing:
            raise UserError(t(self.env, _("To fill in before going real:")) + "\n" + "\n".join(missing))
        folder = os.environ.get("CREDENTIALS_DIRECTORY")
        for name in (CREDENTIAL_VULTR, CREDENTIAL_CLOUDFLARE):
            path = os.path.join(folder, name) if folder else ""
            if not path or not os.path.isfile(path) or not os.path.getsize(path):
                raise UserError(t(self.env, _(
                    "The service has not received the token \"%(name)s\". See docs/runbook/PREREQUISITES.md.", name=name,
                )))
