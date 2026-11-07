import base64

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.i18n import t
from ..services.messages import _


class PlatformAddonToggleWizard(models.TransientModel):
    """Switching one optional add-on on or off for one firm, with the reason for the log."""

    _name = "platform.addon.toggle.wizard"
    _description = "Switch an add-on"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True)
    addon_id = fields.Many2one("platform.addon", "Add-on", required=True, readonly=True)
    target = fields.Selection([("on", "On"), ("off", "Off")], "Switch", required=True, readonly=True)
    reason = fields.Text("Why", required=True)

    def action_confirm(self):
        self.ensure_one()
        self.firm_id._set_addon(self.addon_id, self.target == "on", self.reason, user=self.env.user)
        return {"type": "ir.actions.act_window_close"}


class PlatformCatalogueWizard(models.TransientModel):
    """Loads the catalogue file that build_release.sh wrote beside the bundle."""

    _name = "platform.catalogue.wizard"
    _description = "Load a release's add-on catalogue"

    release_id = fields.Many2one("platform.release", "Release", required=True, readonly=True)
    catalogue_file = fields.Binary("Catalogue (<commit>.catalogue.json)", required=True)
    catalogue_name = fields.Char("Catalogue file name")
    proof_file = fields.Binary("Its signature (<commit>.catalogue.json.sig)")
    proof_name = fields.Char("Signature file name")

    def action_confirm(self):
        self.ensure_one()
        raw = base64.b64decode(self.catalogue_file or b"")
        proof = base64.b64decode(self.proof_file) if self.proof_file else None
        self.release_id._load_catalogue(raw, proof)
        return {"type": "ir.actions.act_window_close"}


class PlatformOnboardingAddon(models.TransientModel):
    """One line of the wizard's Add-ons screen."""

    _name = "platform.onboarding.addon"
    _description = "Optional add-on chosen at onboarding"
    _order = "addon_id"

    wizard_id = fields.Many2one("platform.onboarding.wizard", required=True, ondelete="cascade")
    addon_id = fields.Many2one("platform.addon", "Add-on", required=True, readonly=True)
    summary_text = fields.Char(related="addon_id.summary_text", string="Description")
    version = fields.Char(related="addon_id.version", string="Version")
    enabled = fields.Boolean("On")


class PlatformOnboardingWizard(models.TransientModel):
    """The wizard's fourth screen. See wizard/onboarding.py for the three others and the job."""

    _inherit = "platform.onboarding.wizard"

    step = fields.Selection(selection_add=[("addons", "Add-ons"), ("preflight",)], ondelete={"addons": "set default"})
    addon_line_ids = fields.One2many("platform.onboarding.addon", "wizard_id", "Optional add-ons")
    addons_reason = fields.Text("Why these add-ons", help="Goes in the platform log with your name and the date.")
    base_addon_ids = fields.Many2many("platform.addon", string="Base features, always on", compute="_compute_addon_screen")
    catalogue_missing = fields.Boolean("No catalogue for this release", compute="_compute_addon_screen")
    preview_addons = fields.Char("Add-ons on", compute="_compute_addon_screen")

    @api.depends("release_id", "addon_line_ids.enabled")
    @api.depends_context("lang")
    def _compute_addon_screen(self):
        base = self.env["platform.addon"].sudo().search([("is_optional", "=", False)])
        for wizard in self:
            wizard.base_addon_ids = base
            wizard.catalogue_missing = bool(wizard.release_id and not wizard.release_id.catalogue_loaded_at)
            chosen = wizard.addon_line_ids.filtered("enabled").mapped("addon_id.name_text")
            wizard.preview_addons = ", ".join(chosen) or t(self.env, _("None: base features only"))

    def _fill_addon_lines(self):
        """The optional add-ons of the chosen release; what was already chosen stays chosen."""
        self.ensure_one()
        offered = self.release_id.sudo().addon_line_ids.filtered("is_optional").addon_id
        self.addon_line_ids.filtered(lambda line: line.addon_id not in offered).unlink()
        for addon in offered - self.addon_line_ids.addon_id:
            self.env["platform.onboarding.addon"].create({"wizard_id": self.id, "addon_id": addon.id})

    def action_next(self):
        self.ensure_one()
        if self.step == "addons":
            self._check_addon_choice()
        result = super().action_next()
        if self.step == "addons":
            self._fill_addon_lines()
        return result

    def _check_addon_choice(self):
        chosen = self.addon_line_ids.filtered("enabled")
        if chosen and not (self.addons_reason or "").strip():
            raise UserError(t(self.env, _("Say why these add-ons: the reason goes in the platform log.")))
        allowed = set(self.release_id.sudo()._optional_codes())
        wrong = [line.addon_id.code for line in chosen if line.addon_id.code not in allowed]
        if wrong:
            raise UserError(t(self.env, _(
                "Not in the chosen release: %(codes)s. Go back to the add-ons screen.", codes=", ".join(wrong),
            )))

    def _after_firm_created(self, firm):
        self._check_addon_choice()
        for line in self.addon_line_ids.filtered("enabled"):
            firm._set_addon(line.addon_id, True, self.addons_reason, user=self.env.user)
