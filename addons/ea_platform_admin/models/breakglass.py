from odoo import fields, models
from odoo.exceptions import AccessError


class PlatformBreakglass(models.Model):
    """Every time the operator opens a firm's server by hand. Append-only.

    The firm's server keeps its own record of each SSH login and reports the count, so a login with
    no entry here turns the firm orange. The operator holds the keys for now: see SECURITY-MODEL.md
    for the firm-held option.
    """

    _name = "platform.breakglass"
    _description = "Accès d'urgence"
    _order = "opened_at desc, id desc"
    _rec_name = "reason"

    firm_id = fields.Many2one("platform.firm", "Cabinet", required=True, readonly=True, ondelete="restrict", index=True)
    user_id = fields.Many2one("res.users", "Opérateur", required=True, readonly=True, ondelete="restrict")
    opened_at = fields.Datetime("Ouvert le", required=True, readonly=True, default=fields.Datetime.now)
    reason = fields.Text("Motif", required=True, readonly=True)
    firm_informed = fields.Boolean("Cabinet informé", readonly=True)

    def write(self, vals):
        raise AccessError("Le journal d'accès d'urgence ne se modifie pas.")

    def unlink(self):
        raise AccessError("Le journal d'accès d'urgence ne se supprime pas.")
