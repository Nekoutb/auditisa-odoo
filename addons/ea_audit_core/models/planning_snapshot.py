from odoo import fields, models


class PlanningSnapshot(models.Model):
    """What planning closed on (spec section 5.4): taken in the transaction that
    moves the engagement to execution."""

    _name = "ea.audit.planning.snapshot"
    _inherit = ["ea.audit.engagement.mixin"]
    _description = "Planning snapshot"
    _order = "id desc"

    data = fields.Json()
    taken_by_id = fields.Many2one("res.users", string="Taken by", ondelete="restrict")
    taken_at = fields.Datetime(default=fields.Datetime.now)
