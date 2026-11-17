import json
import logging
import os

from odoo import api, models, modules

from ..services import platform_mail
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
# The platform email address (services/platform_mail.py). Optional: without them, no firm gets one.
CREDENTIAL_MAILERSEND = "mailersend-token"
CREDENTIAL_CLOUDFLARE_MAIL = "cloudflare-mail-token"
MAIL_CREDENTIALS = (CREDENTIAL_MAILERSEND, CREDENTIAL_CLOUDFLARE_MAIL)
PARAM_MAIL_DRY_STATE = "ea_platform.mail_dry_run_state"
PARAM_MAIL_PARENT = "ea_platform.mail_parent_domain"
PARAM_MAIL_ZONE = "ea_platform.mail_zone_name"
PARAM_MAIL_ZONE_ID = "ea_platform.mail_zone_id"
PARAM_MAIL_LOCAL = "ea_platform.mail_local_part"
PARAM_MAIL_REPLY = "ea_platform.mail_reply_to_policy"
PARAM_PRACTICE_ALLOWLIST = "ea_platform.practice_mail_allowlist"


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

    # ------------------------------------------------------------------ the platform email address

    @api.model
    def _mail_credential_present(self, name):
        """True when the service received this token file, not empty. Never reads it."""
        folder = os.environ.get("CREDENTIALS_DIRECTORY")
        path = os.path.join(folder, name) if folder else ""
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0

    @api.model
    def _mail_config(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        parent = platform_mail.clean_parent(get_param(PARAM_MAIL_PARENT) or platform_mail.DEFAULT_PARENT)
        return {
            "parent": parent,
            "zone": platform_mail.clean_parent(get_param(PARAM_MAIL_ZONE) or parent),
            "zone_id": get_param(PARAM_MAIL_ZONE_ID) or "",
            "local_part": get_param(PARAM_MAIL_LOCAL) or platform_mail.DEFAULT_LOCAL_PART,
            "reply_to_policy": get_param(PARAM_MAIL_REPLY) or "contact",
        }

    @api.model
    def _mail_ready(self):
        """Can a firm be given a platform address now? Once the operator has applied the "Sending service for
        firms" settings (the parent domain is saved); outside simulation, also both tokens and the zone's id."""
        if not self.env["ir.config_parameter"].sudo().get_param(PARAM_MAIL_PARENT):
            return False
        if self._is_simulation():
            return True
        return bool(self._mail_config()["zone_id"]) and all(self._mail_credential_present(n) for n in MAIL_CREDENTIALS)

    @api.model
    def _mail_dry_state(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(PARAM_MAIL_DRY_STATE)
        return json.loads(raw) if raw else {"mailersend": {}, "zone": {}}

    @api.model
    def _mail_outside(self, zone_id=None):
        """(mailersend, zone). Simulation: the DryRun classes, no network. The real ones are only built here."""
        if self._is_simulation():
            state = self._mail_dry_state()
            return platform_mail.DryRunMailerSend(state["mailersend"]), platform_mail.DryRunZone(state["zone"])
        mailersend = platform_mail.MailerSend(read_secret_file(_credential_path(CREDENTIAL_MAILERSEND)))
        zone = platform_mail.CloudflareZone(
            read_secret_file(_credential_path(CREDENTIAL_CLOUDFLARE_MAIL)),
            zone_id if zone_id is not None else self._mail_config()["zone_id"],
        )
        return mailersend, zone

    @api.model
    def _save_mail_dry_state(self, mailersend, zone):
        if mailersend.is_simulation:
            state = {"mailersend": mailersend.state, "zone": zone.state}
            self.env["ir.config_parameter"].sudo().set_param(PARAM_MAIL_DRY_STATE, json.dumps(state))

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
    def _release_url(self, release, seconds):
        """A time-limited download address of a release's bundle, or None.

        None in simulation, and when the storage cannot be reached from here (logged): the server
        then has no address and does nothing, which the screens show as an update not started.
        """
        if not release or self._is_simulation():
            return None
        try:
            storage = self._storage()
            if not storage.releases_bucket:
                return None
            return storage.release_url(f"{release.sha}.tar.gz", seconds)
        except ProviderError as error:
            _logger.warning("No download address for release %s: %s", release.sha[:12], error)
            return None
