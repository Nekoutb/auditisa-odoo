import json
import logging
import os

from odoo import api, models, modules

from ..services.messages import _
from ..services.provider import DryRunDns, DryRunProbe, DryRunProvider, ProviderError
from ..services.provider_vultr import CloudflareDns, UrllibProbe, VultrProvider, read_secret_file
from ..services.storage_wasabi import WasabiStorage

_logger = logging.getLogger(__name__)

PARAM_PROVIDER = "ea_platform.provider"
PARAM_DRY_STATE = "ea_platform.dry_run_state"
PARAM_WASABI_REGION = "ea_platform.wasabi_region"
PARAM_WASABI_ENDPOINT = "ea_platform.wasabi_endpoint"
PARAM_RELEASES_BUCKET = "ea_platform.releases_bucket"
DEFAULT_WASABI_REGION = "eu-central-1"  # Amsterdam

# How long a signed download address of a release lasts. A heartbeat answer is renewed every 15
# minutes; a first boot may wait for the provider. SigV4 allows seven days at most.
RELEASE_URL_SECONDS_HEARTBEAT = 6 * 3600
RELEASE_URL_SECONDS_FIRST_BOOT = 3 * 24 * 3600

# systemd's LoadCredential hands the service a private copy of each root-only file:
# see deploy/control-plane/install-control-plane.sh. Odoo stores no token.
CREDENTIAL_VULTR = "vultr-token"
CREDENTIAL_CLOUDFLARE = "cloudflare-token"
CREDENTIAL_WASABI_KEY = "wasabi-key"
CREDENTIAL_WASABI_SECRET = "wasabi-secret"
CREDENTIALS = (CREDENTIAL_VULTR, CREDENTIAL_CLOUDFLARE, CREDENTIAL_WASABI_KEY, CREDENTIAL_WASABI_SECRET)


def _credential_path(name):
    folder = os.environ.get("CREDENTIALS_DIRECTORY")
    if not folder:
        raise ProviderError(_("No token given to this service (LoadCredential missing)."))
    return os.path.join(folder, name)


class PlatformServices(models.AbstractModel):
    """Which implementation of the outside services this instance uses."""

    _name = "platform.services"
    _description = "Access to outside services"

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
        provider = VultrProvider(read_secret_file(_credential_path(CREDENTIAL_VULTR)), storage=self._storage())
        zone = get_param("ea_platform.dns_zone_id")
        if not zone:
            raise ProviderError(_("No DNS zone set."))
        dns = CloudflareDns(read_secret_file(_credential_path(CREDENTIAL_CLOUDFLARE)), zone)
        return provider, dns, UrllibProbe()

    @api.model
    def _storage(self):
        """The real backup storage. Only built outside simulation, like the other real classes."""
        if self._is_simulation():
            raise ProviderError(_("No real storage in simulation."))
        get_param = self.env["ir.config_parameter"].sudo().get_param
        return WasabiStorage(
            read_secret_file(_credential_path(CREDENTIAL_WASABI_KEY)),
            read_secret_file(_credential_path(CREDENTIAL_WASABI_SECRET)),
            region=get_param(PARAM_WASABI_REGION) or DEFAULT_WASABI_REGION,
            endpoint=get_param(PARAM_WASABI_ENDPOINT) or None,
            releases_bucket=get_param(PARAM_RELEASES_BUCKET) or None,
        )

    @api.model
    def _release_base_url(self):
        """Where releases live: the releases bucket. Simulation: a reserved address that reaches nothing."""
        if self._is_simulation():
            return "https://releases.example.invalid"
        return self._storage().releases_base_url()

    @api.model
    def _release_urls(self, release, seconds):
        """(bundle, signature): signed download addresses of a release, or None.

        None in simulation, and when the storage cannot be reached from here (logged): the server
        then has no address and does nothing, which the screens show as an update not started.
        """
        if not release or self._is_simulation():
            return None
        try:
            storage = self._storage()
            if not storage.releases_bucket:
                return None
            return (
                storage.release_url(f"{release.sha}.tar.gz", seconds),
                storage.release_url(f"{release.sha}.tar.gz.sig", seconds),
            )
        except ProviderError as error:
            _logger.warning("No download address for release %s: %s", release.sha[:12], error)
            return None
