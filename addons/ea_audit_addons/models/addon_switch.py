import functools
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.modules.module import Manifest

from ..services.approved import read_approved

_logger = logging.getLogger(__name__)

# Written by deploy/firm/firm-addons.sh, as root, after it checked the request against the signed
# release. This process cannot write there (ReadWritePaths in the service's unit).
APPROVED_FILE = "/var/lib/auditisa-firm/addons/approved.json"
MANIFEST_MARKER = "ea_client_addon"
FEATURE_GROUP = "group_feature"


def addon_required(method):
    """For a button or a server action of a client add-on: refused while the add-on is off."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        self._ea_addon_require()
        return method(self, *args, **kwargs)

    return wrapper


class EaAddonSwitch(models.Model):
    """Which optional client add-ons are on, on this firm.

    Off means: its menus and its views are gone for everyone, its models refuse every user, and its
    tables and rows stay as they are. Nothing here or anywhere uninstalls an add-on, since Odoo's
    uninstall drops tables and audit records have retention rules. On again restores it all.

    The switch is the group `<add-on>.group_feature`, implied by "internal user" while on. Odoo's
    own menus, views and access rules then do the hiding, with nothing left for an add-on to forget.
    """

    _name = "ea.addon.switch"
    _description = "Client add-on switch"
    _order = "code"
    _rec_name = "code"

    code = fields.Char("Add-on", required=True, readonly=True, index=True)
    enabled = fields.Boolean("On", readonly=True)
    changed_at = fields.Datetime("Changed on", readonly=True)

    _code_unique = models.Constraint("unique(code)", "An add-on has one switch.")

    @api.model
    def _client_addons_installed(self):
        names = self.env["ir.module.module"].sudo().search([("state", "=", "installed")]).mapped("name")
        found = []
        for name in names:
            manifest = Manifest.for_addon(name, display_warning=False)
            if manifest and manifest.get(MANIFEST_MARKER) is True:
                found.append(name)
        return sorted(found)

    @api.model
    def _is_on(self, code):
        return bool(self.sudo().search_count([("code", "=", code), ("enabled", "=", True)]))

    @api.model
    def _codes_on(self):
        return sorted(self.sudo().search([("enabled", "=", True)]).mapped("code"))

    def _apply_group(self):
        """Links or unlinks the feature group. Odoo's group caches are cleared across workers."""
        internal = self.env.ref("base.group_user").sudo()
        for switch in self:
            group = self.env.ref(f"{switch.code}.{FEATURE_GROUP}", raise_if_not_found=False)
            if not group:
                _logger.warning("Add-on %s has no %s group: its screens are not switched", switch.code, FEATURE_GROUP)
                continue
            linked = group in internal.implied_ids
            if switch.enabled and not linked:
                internal.write({"implied_ids": [(4, group.id)]})
            elif not switch.enabled and linked:
                internal.write({"implied_ids": [(3, group.id)]})

    @api.model
    def _sync(self, approved):
        """Every installed client add-on gets a switch; on only if `approved` says so.

        `approved` None means no request has ever been made, or the list cannot be read: existing
        switches stay as they are and a new one starts off.
        """
        self = self.sudo()
        for code in self._client_addons_installed():
            switch = self.search([("code", "=", code)], limit=1)
            if not switch:
                switch = self.create({"code": code, "enabled": False, "changed_at": fields.Datetime.now()})
            if approved is not None and switch.enabled != (code in approved):
                switch.write({"enabled": code in approved, "changed_at": fields.Datetime.now()})
                _logger.info("Add-on %s is now %s", code, "on" if switch.enabled else "off")
            switch._apply_group()

    @api.model
    def _cron_apply(self):
        self._sync(read_approved(APPROVED_FILE))


class EaClientAddonMixin(models.AbstractModel):
    """What a model of a client add-on inherits. Its code comes from the addon that defines it.

    The access rules already refuse every user while off. This refuses code that runs as superuser
    too, so that nothing writes into an add-on's tables while the firm has it off.
    """

    _name = "ea.client.addon.mixin"
    _description = "Model of an optional client add-on"

    def _ea_addon_code(self):
        return self._original_module

    def _ea_addon_require(self):
        # While a module loads or updates, its own data files must still go in.
        if not self.env.registry.ready or self.env.context.get("install_mode"):
            return
        if not self.env["ea.addon.switch"]._is_on(self._ea_addon_code()):
            raise UserError(self.env._(
                "This add-on is switched off for this firm. Its data is kept, and switching it on again restores it."
            ))

    @api.model_create_multi
    def create(self, vals_list):
        self._ea_addon_require()
        return super().create(vals_list)

    def write(self, vals):
        self._ea_addon_require()
        return super().write(vals)

    def unlink(self):
        self._ea_addon_require()
        return super().unlink()
