import os

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.platform_services import CREDENTIAL_CLOUDFLARE, CREDENTIAL_VULTR, PARAM_PROVIDER
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
    _description = "Réglages de la plateforme"

    provider = fields.Selection(
        [("dry_run", "Simulation"), ("vultr", "Réel : Vultr et Cloudflare")],
        "Fournisseur", default=lambda self: self._param(PARAM_PROVIDER, "dry_run"), required=True,
    )
    base_domain = fields.Char("Domaine de base", default=lambda self: self._param("ea_platform.base_domain", "auditisa.com"), required=True)
    heartbeat_url = fields.Char("Adresse de réception des heartbeats", default=lambda self: self._param("ea_platform.heartbeat_url"))
    release_base_url = fields.Char("Adresse des versions", default=lambda self: self._param("ea_platform.release_base_url"))
    release_signing_public_key = fields.Text(
        "Clé publique de signature des versions",
        default=lambda self: self._param("ea_platform.release_signing_public_key"),
    )
    ssh_allowlist = fields.Text("Adresses de l'opérateur pour le port 22", default=lambda self: self._param("ea_platform.ssh_allowlist"))
    vultr_os_id = fields.Char("Système du serveur (identifiant Vultr)", default=lambda self: self._param("ea_platform.vultr_os_id"))
    vultr_storage_cluster = fields.Char("Grappe de stockage objet (identifiant Vultr)", default=lambda self: self._param("ea_platform.vultr_storage_cluster"))
    dns_zone_id = fields.Char("Zone DNS (identifiant Cloudflare)", default=lambda self: self._param("ea_platform.dns_zone_id"))
    confirm_real = fields.Boolean("Je veux créer de vrais serveurs, facturés par le fournisseur.")

    @api.model
    def _param(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def action_save(self):
        self.ensure_one()
        _cidrs, errors = parse_allowlist(self.ssh_allowlist) if self.ssh_allowlist else ([], [])
        if errors:
            raise UserError("\n".join(errors))
        for url in (self.heartbeat_url, self.release_base_url):
            if url and not url.startswith("https://"):
                raise UserError(f"Cette adresse doit commencer par https:// : {url}")
        if self.provider == "vultr":
            self._check_real_mode()
        params = self.env["ir.config_parameter"].sudo()
        before = params.get_param(PARAM_PROVIDER, "dry_run")
        for field, key in PARAMS.items():
            params.set_param(key, self[field] or False)
        params.set_param(PARAM_PROVIDER, self.provider)
        self.env["platform.log"]._record(
            "Réglages modifiés", detail=f"Fournisseur : {before} -> {self.provider}" if before != self.provider else "",
        )
        return {"type": "ir.actions.client", "tag": "reload"}

    def _check_real_mode(self):
        """The door to real servers: every setting, both token files, and an explicit tick."""
        if not self.confirm_real:
            raise UserError("Cochez la confirmation pour passer au réel.")
        missing = [
            self._fields[field].string
            for field in ("heartbeat_url", "release_base_url", "release_signing_public_key", "ssh_allowlist",
                          "vultr_os_id", "vultr_storage_cluster", "dns_zone_id")
            if not self[field]
        ]
        if missing:
            raise UserError("À renseigner avant de passer au réel :\n" + "\n".join(missing))
        folder = os.environ.get("CREDENTIALS_DIRECTORY")
        for name in (CREDENTIAL_VULTR, CREDENTIAL_CLOUDFLARE):
            path = os.path.join(folder, name) if folder else ""
            if not path or not os.path.isfile(path) or not os.path.getsize(path):
                raise UserError(
                    f"Le service n'a pas reçu le jeton « {name} ». Voir docs/runbook/PREREQUISITES.md."
                )
