import json
import os

from odoo import api, models, modules

from ..services.provider import DryRunDns, DryRunProbe, DryRunProvider, ProviderError
from ..services.provider_vultr import CloudflareDns, UrllibProbe, VultrProvider, read_secret_file

PARAM_PROVIDER = "ea_platform.provider"
PARAM_DRY_STATE = "ea_platform.dry_run_state"

# systemd's LoadCredential hands the service a private copy of each root-only file:
# see deploy/control-plane/install-control-plane.sh. Odoo stores no token.
CREDENTIAL_VULTR = "vultr-token"
CREDENTIAL_CLOUDFLARE = "cloudflare-token"


def _credential_path(name):
    folder = os.environ.get("CREDENTIALS_DIRECTORY")
    if not folder:
        raise ProviderError("Aucun jeton fourni à ce service (LoadCredential manquant).")
    return os.path.join(folder, name)


class PlatformServices(models.AbstractModel):
    """Which implementation of the outside services this instance uses."""

    _name = "platform.services"
    _description = "Accès aux services extérieurs"

    @api.model
    def _is_simulation(self):
        """Tests are always a simulation, whatever the parameter says."""
        if modules.module.current_test:
            return True
        return self.env["ir.config_parameter"].sudo().get_param(PARAM_PROVIDER, "dry_run") != "vultr"

    @api.model
    def _dry_state(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(PARAM_DRY_STATE)
        return json.loads(raw) if raw else {"provider": {}, "dns": {}}

    @api.model
    def _save_dry_state(self, provider, dns):
        if provider.is_simulation:
            state = {"provider": provider.state, "dns": dns.state}
            self.env["ir.config_parameter"].sudo().set_param(PARAM_DRY_STATE, json.dumps(state))

    @api.model
    def _outside(self):
        """(provider, dns, probe). The real classes are only ever built here."""
        if self._is_simulation():
            state = self._dry_state()
            return DryRunProvider(state["provider"]), DryRunDns(state["dns"]), DryRunProbe()
        get_param = self.env["ir.config_parameter"].sudo().get_param
        provider = VultrProvider(
            read_secret_file(_credential_path(CREDENTIAL_VULTR)),
            object_storage_cluster=get_param("ea_platform.vultr_storage_cluster"),
        )
        zone = get_param("ea_platform.dns_zone_id")
        if not zone:
            raise ProviderError("Aucune zone DNS configurée.")
        dns = CloudflareDns(read_secret_file(_credential_path(CREDENTIAL_CLOUDFLARE)), zone)
        return provider, dns, UrllibProbe()
