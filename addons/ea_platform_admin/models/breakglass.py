from odoo import fields, models
from odoo.exceptions import AccessError

from ..services.messages import _
from .i18n import t


class PlatformBreakglass(models.Model):
    """Every time the operator opens a firm's server by hand. Append-only.

    The firm's server keeps its own record of each SSH login and reports the count, so a login with
    no entry here turns the firm orange. The operator holds the keys for now: see SECURITY-MODEL.md
    for the firm-held option.
    """

    _name = "platform.breakglass"
    _description = "Break-glass access"
    _order = "opened_at desc, id desc"
    _rec_name = "reason"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True, ondelete="restrict", index=True)
    user_id = fields.Many2one("res.users", "Operator", required=True, readonly=True, ondelete="restrict")
    opened_at = fields.Datetime("Opened on", required=True, readonly=True, default=fields.Datetime.now)
    reason = fields.Text("Reason", required=True, readonly=True)
    firm_informed = fields.Boolean("Firm told", readonly=True)

    def write(self, vals):
        raise AccessError(t(self.env, _("The break-glass log cannot be changed.")))

    def unlink(self):
        raise AccessError(t(self.env, _("The break-glass log cannot be deleted.")))
