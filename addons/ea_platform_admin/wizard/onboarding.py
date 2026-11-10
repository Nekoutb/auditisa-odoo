import secrets

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.i18n import t
from ..services.catalogue import LANGUAGES, REGIONS, SIZES, monthly_cost, selection
from ..services.messages import _
from ..services.validation import (
    flatten_errors,
    normalise_slug,
    onboarding_errors,
    parse_allowlist,
)

STEP_FIELDS = {
    "identity": ("name", "slug", "contact_name", "contact_email", "allowed_email_domains"),
    "technical": ("region", "size", "lang", "ssh_public_key"),
}


class PlatformOnboardingWizard(models.TransientModel):
    """A new client firm: three screens, then the provisioning job with its visible step log."""

    _name = "platform.onboarding.wizard"
    _description = "New firm"

    step = fields.Selection(
        [("identity", "The firm"), ("technical", "The server"), ("preflight", "Review")],
        default="identity", required=True,
    )
    name = fields.Char("Firm name")
    slug = fields.Char("Slug", help="Becomes the address: slug.auditisa.com. It never changes.")
    contact_name = fields.Char("Contact name")
    contact_email = fields.Char("Contact email", help="Will be the first administrator's login.")
    contact_phone = fields.Char("Phone")
    allowed_email_domains = fields.Text("Allowed email domains", help="One per line, for example exemple.cm")
    region = fields.Selection(selection(REGIONS), "Region", default="cdg")
    size = fields.Selection(selection(SIZES), "Size", default="standard")
    lang = fields.Selection(
        selection(LANGUAGES), "Default language", default="fr_FR",
        help="The firm's default language. Each user can then choose French or English in their preferences.",
    )
    ssh_public_key = fields.Char(
        "The firm's public SSH key",
        help="The content of the .pub file made on your computer for this firm. "
             "The private key stays with you: never paste it here.",
    )
    release_id = fields.Many2one(
        "platform.release", "Release to install",
        default=lambda self: self.env["platform.release"].search([], limit=1),
    )
    confirmed = fields.Boolean("I confirm the creation of this server and its estimated monthly cost.")

    preview_address = fields.Char("Address", compute="_compute_preview")
    preview_server = fields.Char("Server", compute="_compute_preview")
    preview_server_cost = fields.Float("Server (USD/month)", compute="_compute_preview")
    preview_storage_cost = fields.Float("Backup storage (USD/month)", compute="_compute_preview")
    preview_total_cost = fields.Float("Estimated total (USD/month)", compute="_compute_preview")
    preview_mode = fields.Char("Mode", compute="_compute_preview")
    preview_allowlist = fields.Char("Port 22 open to", compute="_compute_preview")

    @api.depends("slug", "size", "region")
    @api.depends_context("lang")
    def _compute_preview(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        base = get_param("ea_platform.base_domain", "auditisa.com")
        simulation = self.env["platform.services"]._is_simulation()
        regions = dict(self._fields["region"]._description_selection(self.env))
        for wizard in self:
            size = SIZES.get(wizard.size)
            wizard.preview_address = f"{normalise_slug(wizard.slug)}.{base}" if wizard.slug else False
            wizard.preview_server = t(self.env, _(
                "%(vcpu)s vCPU, %(ram)s GB memory, %(disk)s GB disk, %(region)s",
                vcpu=size["vcpu"], ram=size["ram_gb"], disk=size["disk_gb"], region=regions.get(wizard.region, ""),
            )) if size else False
            server, storage, total = monthly_cost(wizard.size) if size else (0.0, 0.0, 0.0)
            wizard.preview_server_cost = server
            wizard.preview_storage_cost = storage
            wizard.preview_total_cost = total
            wizard.preview_mode = t(self.env, (
                _("SIMULATION: no server will be created and nothing will be billed.")
                if simulation else _("REAL: a server will be created and billed by the provider.")
            ))
            wizard.preview_allowlist = ", ".join(parse_allowlist(get_param("ea_platform.ssh_allowlist", ""))[0]) or t(
                self.env, _("no address set (simulation)") if simulation else _("no address set"),
            )

    def _data(self):
        self.ensure_one()
        return {
            "name": self.name, "slug": normalise_slug(self.slug), "contact_name": self.contact_name,
            "contact_email": (self.contact_email or "").strip(), "region": self.region, "size": self.size,
            "lang": self.lang, "allowed_email_domains": self.allowed_email_domains,
            "ssh_public_key": (self.ssh_public_key or "").strip(),
        }

    def _errors(self, fields_to_check=None):
        firms = self.env["platform.firm"].sudo().with_context(active_test=False).search([])
        errors = onboarding_errors(
            self._data(),
            existing_slugs=firms.mapped("slug"),
            existing_fingerprints=firms.mapped("ssh_key_fingerprint"),
        )
        if fields_to_check is not None:
            errors = {field: messages for field, messages in errors.items() if field in fields_to_check}
        return errors

    def _raise_errors(self, errors):
        raise UserError("\n".join(t(self.env, message) for message in flatten_errors(errors)))

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "name": self.env["ir.model"]._get(self._name).name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_next(self):
        self.ensure_one()
        errors = self._errors(STEP_FIELDS.get(self.step))
        if errors:
            self._raise_errors(errors)
        self.write({
            "slug": normalise_slug(self.slug),
            "step": {"identity": "technical", "technical": "addons", "addons": "preflight"}[self.step],
            "confirmed": False,
        })
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        self.write({"step": {"preflight": "addons", "addons": "technical", "technical": "identity"}[self.step], "confirmed": False})
        return self._reopen()

    def action_confirm(self):
        self.ensure_one()
        if self.step != "preflight":
            raise UserError(t(self.env, _("Go through the review screen first.")))
        if not self.confirmed:
            raise UserError(t(self.env, _("Tick the confirmation: nothing is created without it.")))
        errors = self._errors()
        if errors:
            self._raise_errors(errors)
        if not self.release_id:
            raise UserError(t(self.env, _(
                "No release is registered. Register a release first (Platform > Releases): "
                "see docs/runbook/UPDATING.md."
            )))
        simulation = self.env["platform.services"]._is_simulation()
        if not simulation:
            self._check_settings()
        data = self._data()
        firm = self.env["platform.firm"].sudo().create({
            **data,
            "contact_phone": self.contact_phone,
            "state": "provisioning",
            "is_simulation": simulation,
            "desired_release_id": self.release_id.id,
            "heartbeat_token": secrets.token_hex(32),
        })
        self.env["platform.log"]._record(
            _("New firm confirmed"), firm,
            _("Size %(size)s, region %(region)s, estimated cost %(cost)s USD/month",
              size=firm.size, region=firm.region, cost=f"{firm.monthly_cost_usd:.2f}"),
        )
        self._after_firm_created(firm)
        job = self.env["platform.provision.job"]._start(firm)
        job._run()
        return {
            "type": "ir.actions.act_window",
            "res_model": "platform.provision.job",
            "res_id": job.id,
            "view_mode": "form",
            "target": "current",
        }

    def _after_firm_created(self, firm):
        """wizard/addons.py records the add-ons chosen, before the job starts."""

    def _check_settings(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        required = {
            "ea_platform.heartbeat_url": _("Heartbeat receiving address"),
            "ea_platform.releases_bucket": _("Releases bucket (Wasabi)"),
            "ea_platform.ssh_allowlist": _("Operator addresses for port 22"),
            "ea_platform.vultr_os_id": _("Server operating system (Vultr id)"),
            "ea_platform.dns_zone_id": _("DNS zone"),
        }
        missing = [t(self.env, label) for key, label in required.items() if not get_param(key)]
        if missing:
            raise UserError(t(self.env, _("Missing settings (Platform > Settings):")) + "\n" + "\n".join(missing))

    @api.onchange("ssh_public_key")
    def _onchange_ssh_public_key(self):
        if self.ssh_public_key and "PRIVATE KEY" in self.ssh_public_key:
            self.ssh_public_key = False
            return {"warning": {
                "title": t(self.env, _("Private key erased")),
                "message": t(self.env, _(
                    "You pasted a PRIVATE key. It has been erased from this form without being saved. "
                    "Paste the content of the .pub file."
                )),
            }}
        return None
