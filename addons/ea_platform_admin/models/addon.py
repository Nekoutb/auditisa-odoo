from pathlib import Path

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import addons as catalogue
from ..services.messages import _
from .i18n import read, t

STATUSES = [
    (catalogue.ON, "On"),
    (catalogue.OFF, "Off"),
    (catalogue.SWITCHING_ON, "Switching on"),
    (catalogue.SWITCHING_OFF, "Switching off"),
    (catalogue.DIFFERS_ON, "Asked on, firm says off"),
    (catalogue.DIFFERS_OFF, "Asked off, firm says on"),
    (catalogue.NOT_IN_RELEASE, "Not in the firm's release"),
]


class PlatformAddon(models.Model):
    """One feature of the shared codebase, as the manifests of the releases describe it.

    Base features are on for every firm and have no switch. An optional client add-on is chosen per
    firm. Nobody edits these rows: a release's catalogue file writes them.
    """

    _name = "platform.addon"
    _description = "Add-on"
    _order = "is_optional, code"

    code = fields.Char("Code", required=True, readonly=True, index=True)
    name = fields.Char("Name (source)", required=True, readonly=True)
    summary = fields.Char("Description (source)", readonly=True)
    name_text = fields.Char("Name", compute="_compute_text")
    summary_text = fields.Char("Description", compute="_compute_text")
    version = fields.Char("Version", readonly=True)
    is_optional = fields.Boolean("Optional", readonly=True, index=True)
    is_sample = fields.Boolean("Sample", readonly=True)
    kind = fields.Selection(
        [("base", "Base, always on"), ("optional", "Optional"), ("sample", "Sample")],
        "Kind", compute="_compute_kind", store=True,
    )
    release_line_ids = fields.One2many("platform.release.addon", "addon_id", "In the releases")
    firm_ids = fields.Many2many("platform.firm", string="Firms that have it", compute="_compute_firms")
    firm_count = fields.Integer("Firms", compute="_compute_firms")

    _code_unique = models.Constraint("unique(code)", "This add-on is already in the catalogue.")

    @api.depends("name", "summary")
    @api.depends_context("lang")
    def _compute_text(self):
        for addon in self:
            addon.name_text = read(self.env, addon.name)
            addon.summary_text = read(self.env, addon.summary)

    @api.depends("is_optional", "is_sample")
    def _compute_kind(self):
        for addon in self:
            addon.kind = "sample" if addon.is_sample else "optional" if addon.is_optional else "base"

    def _compute_firms(self):
        firms = self.env["platform.firm"].sudo().search([("state", "!=", "archived")])
        lines = self.env["platform.firm.addon"].sudo().search([("desired", "=", True), ("firm_id", "in", firms.ids)])
        for addon in self:
            have = lines.filtered(lambda line: line.addon_id == addon).firm_id if addon.is_optional else firms
            addon.firm_ids = have
            addon.firm_count = len(have)

    @api.depends("name_text", "code")
    def _compute_display_name(self):
        for addon in self:
            addon.display_name = addon.name_text or addon.code


class PlatformReleaseAddon(models.Model):
    """What one release carries. It is the first allowlist of what a firm may be asked."""

    _name = "platform.release.addon"
    _description = "Add-on in a release"
    _order = "release_id desc, is_optional, addon_id"

    release_id = fields.Many2one("platform.release", "Release", required=True, readonly=True, ondelete="cascade", index=True)
    addon_id = fields.Many2one("platform.addon", "Add-on", required=True, readonly=True, ondelete="restrict", index=True)
    code = fields.Char(related="addon_id.code", string="Code")
    version = fields.Char("Version", readonly=True)
    is_optional = fields.Boolean("Optional", readonly=True)

    _once = models.Constraint("unique(release_id, addon_id)", "An add-on is listed once per release.")


class PlatformRelease(models.Model):
    _inherit = "platform.release"

    addon_line_ids = fields.One2many("platform.release.addon", "release_id", "Add-ons in this release")
    catalogue_loaded_at = fields.Datetime("Catalogue loaded on", readonly=True, copy=False)
    catalogue_signed = fields.Boolean("Catalogue signature verified", readonly=True, copy=False)
    catalogue_digest = fields.Char("Catalogue digest", readonly=True, copy=False)
    optional_addon_count = fields.Integer("Optional add-ons", compute="_compute_optional_count")

    def _compute_optional_count(self):
        for release in self:
            release.optional_addon_count = len(release.addon_line_ids.filtered("is_optional"))

    def _optional_codes(self):
        self.ensure_one()
        return self.addon_line_ids.filtered("is_optional").mapped("code")

    def _verify_catalogue(self, raw, signature):
        """Required on a real platform; checked in simulation only when both sides are present.

        The signature must be one of a signer trusted TODAY (Platform > Updates > Signers). The release
        then records who signed it, if nothing recorded it before.
        """
        signers = self.env["platform.signer"].sudo().search([])
        simulation = self.env["platform.services"]._is_simulation()
        if not (signers and signature):
            if simulation:
                return False
            raise UserError(t(self.env, _(
                "The catalogue needs its signature file and at least one trusted signer (Platform > Updates > Signers)."
            )))
        signer = self.env["platform.signer"]._who_signed(signature, raw)
        if not signer:
            raise UserError(t(self.env, _("The catalogue's signature does not hold: nothing was loaded."))
                            + "\n" + t(self.env, _("It was not made by a trusted signer.")))
        if not self.signer_id:
            self.sudo().signer_id = signer
        return True

    def _load_catalogue(self, raw, signature=None):
        """Writes the rows. A release does not change: a second load must be the same file."""
        self.ensure_one()
        try:
            entries = catalogue.parse_catalogue(raw, self.sha)
        except catalogue.CatalogueRefused as refused:
            raise UserError(t(self.env, refused.message)) from None
        signed = self._verify_catalogue(raw, signature)
        digest = _sha256(raw)
        if self.catalogue_digest and self.catalogue_digest != digest:
            raise UserError(t(self.env, _("This release already has another catalogue: a release does not change.")))
        addons = self.env["platform.addon"].sudo()
        newest = not self.sudo().search_count([("id", ">", self.id), ("catalogue_loaded_at", "!=", False)])
        for entry in entries:
            addon = addons.search([("code", "=", entry["code"])], limit=1)
            values = {
                "name": entry["name"], "summary": entry["summary"], "version": entry["version"],
                "is_optional": entry["optional"], "is_sample": entry["sample"],
            }
            if not addon:
                addon = addons.create({"code": entry["code"], **values})
            elif newest:
                addon.write(values)
            line = self.addon_line_ids.sudo().filtered(lambda row: row.addon_id == addon)
            if not line:
                self.env["platform.release.addon"].sudo().create({
                    "release_id": self.id, "addon_id": addon.id,
                    "version": entry["version"], "is_optional": entry["optional"],
                })
        self.sudo().write({
            "catalogue_loaded_at": fields.Datetime.now(),
            "catalogue_signed": signed or self.catalogue_signed,
            "catalogue_digest": digest,
        })
        self.env["platform.firm"].sudo().search([("state", "!=", "archived")])._ensure_addon_lines()
        self.env["platform.log"]._record(
            _("Add-on catalogue loaded"), None,
            _("Release %(sha)s: %(count)s add-ons, %(optional)s optional",
              sha=self.sha[:12], count=len(entries), optional=sum(1 for entry in entries if entry["optional"])),
        )
        return True

    def action_read_catalogue_here(self):
        """Simulation only: reads the manifests beside this addon, with no signature to show for it."""
        self.ensure_one()
        if not self.env.user.has_group("ea_platform_admin.group_platform_owner"):
            raise AccessError(t(self.env, _("Only the owner loads a catalogue.")))
        if not self.env["platform.services"]._is_simulation():
            raise UserError(t(self.env, _("On a real platform a catalogue comes from a signed file only.")))
        import json

        folder = Path(__file__).parents[2]
        document = {"schema": 1, "release": self.sha, "addons": catalogue.scan(folder)}
        return self._load_catalogue(json.dumps(document, sort_keys=True).encode("utf-8"))

    def action_open_catalogue_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env["ir.model"]._get("platform.catalogue.wizard").name,
            "res_model": "platform.catalogue.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_release_id": self.id},
        }


def _sha256(raw):
    import hashlib

    return hashlib.sha256(raw).hexdigest()


class PlatformFirmAddon(models.Model):
    """One optional add-on on one firm: what was asked, and what the firm last said."""

    _name = "platform.firm.addon"
    _description = "Optional add-on of a firm"
    _order = "firm_id, addon_id"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True, ondelete="restrict", index=True)
    addon_id = fields.Many2one("platform.addon", "Add-on", required=True, readonly=True, ondelete="restrict", index=True)
    code = fields.Char(related="addon_id.code", string="Code")
    summary_text = fields.Char(related="addon_id.summary_text", string="Description")
    version = fields.Char(related="addon_id.version", string="Version")
    is_sample = fields.Boolean(related="addon_id.is_sample", string="Sample")
    desired = fields.Boolean("Asked on", readonly=True)
    reported = fields.Boolean("Firm says on", readonly=True)
    changed_at = fields.Datetime("Last changed on", readonly=True)
    changed_by = fields.Many2one("res.users", "By", readonly=True)
    status = fields.Selection(STATUSES, "State", compute="_compute_status")

    _once = models.Constraint("unique(firm_id, addon_id)", "An add-on is listed once per firm.")

    @api.depends("desired", "reported", "changed_at", "firm_id.addons_reported_at", "firm_id.addon_release")
    def _compute_status(self):
        now = fields.Datetime.now()
        for line in self:
            line.status = catalogue.line_status(
                line.desired, line.reported, bool(line.firm_id.addons_reported_at),
                line.code in line.firm_id._allowed_addon_codes(), line.changed_at, now,
            )

    def _open_toggle(self, target):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env["ir.model"]._get("platform.addon.toggle.wizard").name,
            "res_model": "platform.addon.toggle.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_firm_id": self.firm_id.id, "default_addon_id": self.addon_id.id, "default_target": target,
            },
        }

    def action_switch_on(self):
        return self._open_toggle("on")

    def action_switch_off(self):
        return self._open_toggle("off")
