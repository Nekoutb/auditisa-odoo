import os

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.i18n import t
from ..models.platform_services import (
    CREDENTIALS,
    DEFAULT_WASABI_REGION,
    PARAM_PROVIDER,
    PARAM_RELEASES_BUCKET,
    PARAM_WASABI_ENDPOINT,
    PARAM_WASABI_REGION,
)
from ..services import wasabi_policy
from ..services.messages import _
from ..services.validation import parse_allowlist

# field -> parameter. There is no field for any token: those live in root-only files.
PARAMS = {
    "base_domain": "ea_platform.base_domain",
    "heartbeat_url": "ea_platform.heartbeat_url",
    "release_signing_public_key": "ea_platform.release_signing_public_key",
    "ssh_allowlist": "ea_platform.ssh_allowlist",
    "vultr_os_id": "ea_platform.vultr_os_id",
    "dns_zone_id": "ea_platform.dns_zone_id",
    "wasabi_region": PARAM_WASABI_REGION,
    "wasabi_endpoint": PARAM_WASABI_ENDPOINT,
    "releases_bucket": PARAM_RELEASES_BUCKET,
}


class PlatformSettings(models.TransientModel):
    _name = "platform.settings"
    _description = "Platform settings"

    provider = fields.Selection(
        [("dry_run", "Simulation"), ("vultr", "Real: Vultr, Wasabi and Cloudflare")],
        "Provider", default=lambda self: self._param(PARAM_PROVIDER, "dry_run"), required=True,
    )
    base_domain = fields.Char("Base domain", default=lambda self: self._param("ea_platform.base_domain", "auditisa.com"), required=True)
    heartbeat_url = fields.Char("Heartbeat receiving address", default=lambda self: self._param("ea_platform.heartbeat_url"))
    release_signing_public_key = fields.Text(
        "Release signing public key",
        default=lambda self: self._param("ea_platform.release_signing_public_key"),
    )
    ssh_allowlist = fields.Text("Operator addresses for port 22", default=lambda self: self._param("ea_platform.ssh_allowlist"))
    vultr_os_id = fields.Char("Server operating system (Vultr id)", default=lambda self: self._param("ea_platform.vultr_os_id"))
    dns_zone_id = fields.Char("DNS zone (Cloudflare id)", default=lambda self: self._param("ea_platform.dns_zone_id"))
    # Backup storage and releases: Wasabi. The key and secret are root-only files, not settings.
    wasabi_region = fields.Char(
        "Wasabi region", required=True,
        default=lambda self: self._param(PARAM_WASABI_REGION, DEFAULT_WASABI_REGION),
    )
    wasabi_endpoint = fields.Char(
        "Wasabi address (if not the region's own)", default=lambda self: self._param(PARAM_WASABI_ENDPOINT),
    )
    releases_bucket = fields.Char("Releases bucket (Wasabi)", default=lambda self: self._param(PARAM_RELEASES_BUCKET))
    confirm_real = fields.Boolean("I want to create real servers, billed by the provider.")

    def _compute_display_name(self):
        for settings in self:
            settings.display_name = t(self.env, _("Settings"))

    @api.model
    def _param(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def action_save(self):
        self.ensure_one()
        _cidrs, errors = parse_allowlist(self.ssh_allowlist) if self.ssh_allowlist else ([], [])
        if errors:
            raise UserError("\n".join(t(self.env, error) for error in errors))
        for url in (self.heartbeat_url,):
            if url and not url.startswith("https://"):
                raise UserError(t(self.env, _("This address must start with https://: %(url)s", url=url)))
        self.wasabi_region = (self.wasabi_region or "").strip()
        self.wasabi_endpoint = (self.wasabi_endpoint or "").strip() or False
        self.releases_bucket = (self.releases_bucket or "").strip() or False
        if not wasabi_policy.REGION_RE.match(self.wasabi_region):
            raise UserError(t(self.env, _("Wasabi region: a code such as eu-central-1.")))
        if self.wasabi_endpoint and not wasabi_policy.ENDPOINT_RE.match(self.wasabi_endpoint):
            raise UserError(t(self.env, _("Wasabi address: a host name only, such as s3.eu-central-1.wasabisys.com.")))
        if self.releases_bucket and not wasabi_policy.RELEASES_BUCKET_RE.match(self.releases_bucket):
            raise UserError(t(self.env, _("The releases bucket is named auditisa-releases- followed by at least 8 letters or digits.")))
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
        """The door to real servers: every setting, the four credential files, and an explicit tick."""
        if not self.confirm_real:
            raise UserError(t(self.env, _("Tick the confirmation to go real.")))
        missing = [
            self._fields[field]._description_string(self.env)
            for field in ("heartbeat_url", "release_signing_public_key", "ssh_allowlist",
                          "vultr_os_id", "dns_zone_id", "wasabi_region", "releases_bucket")
            if not self[field]
        ]
        if missing:
            raise UserError(t(self.env, _("To fill in before going real:")) + "\n" + "\n".join(missing))
        folder = os.environ.get("CREDENTIALS_DIRECTORY")
        for name in CREDENTIALS:
            path = os.path.join(folder, name) if folder else ""
            if not path or not os.path.isfile(path) or not os.path.getsize(path):
                raise UserError(t(self.env, _(
                    "The service has not received the token \"%(name)s\". See docs/runbook/PREREQUISITES.md.", name=name,
                )))
