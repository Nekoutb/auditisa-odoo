from odoo import fields, models

from odoo.addons.ea_audit_addons.models.addon_switch import addon_required


class EaClientSampleNote(models.Model):
    """A sample, to prove the whole path. It is all a client add-on has to do to be switchable."""

    _name = "ea.client.sample.note"
    _description = "Sample client note"
    _inherit = ["ea.client.addon.mixin"]

    name = fields.Char("Note", required=True)
    reviewed = fields.Boolean("Reviewed")

    @addon_required
    def action_mark_reviewed(self):
        self.write({"reviewed": True})
        return True
