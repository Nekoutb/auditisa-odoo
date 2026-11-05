from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ea_mail_server_id = fields.Many2one(
        "ir.mail_server", string="Firm's outgoing mail server", copy=False, ondelete="set null", groups="base.group_system",
    )
    ea_mail_tested_at = fields.Datetime(string="Mail server tested at", copy=False, groups="base.group_system")
