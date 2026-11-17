from odoo import api, fields, models
from odoo.http import request

from .common import refuse

KINDS = [
    ("support_login", "Technical account login"),
    ("user_invited", "Invitation"),
    ("link_issued", "New invitation link"),
    ("password_link_issued", "New password link"),
    ("link_emailed", "Invitation sent by email"),
    ("role_changed", "Role change"),
    ("user_deactivated", "Deactivation"),
    ("user_reactivated", "Reactivation"),
    ("domains_changed", "Allowed domains"),
    ("mail_saved", "Mail server saved"),
    ("mail_tested", "Mail server test"),
    ("mail_enabled", "Sending enabled"),
    ("mail_disabled", "Sending disabled"),
    ("project_changed", "Internal project"),
    ("week_reopened", "Week reopened"),
]


class FirmLog(models.Model):
    """What the firm can read of its administration and of support: append only."""

    _name = "ea.audit.firm.log"
    _description = "Firm administration log"
    _order = "id desc"

    kind = fields.Selection(KINDS, required=True, index=True)
    actor_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    actor_name = fields.Char(required=True)
    target_id = fields.Many2one("res.users", ondelete="set null")
    target_name = fields.Char()
    detail = fields.Char()
    ip_address = fields.Char(string="IP address")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise refuse(self.env, "fa-forbidden")
        return super().create(vals_list)

    def write(self, vals):
        raise refuse(self.env, "fa-forbidden")

    def unlink(self):
        raise refuse(self.env, "fa-forbidden")

    @api.model
    def _ea_append(self, kind, target=None, detail=None, actor=None):
        actor = (actor or self.env.user).sudo()
        return self.sudo().create({
            "kind": kind,
            "actor_id": actor.id,
            "actor_name": actor.name,
            "target_id": target.id if target else False,
            "target_name": target.sudo().name if target else False,
            "detail": (detail or "")[:500] or False,
            "ip_address": request.httprequest.remote_addr if request else False,
        })
