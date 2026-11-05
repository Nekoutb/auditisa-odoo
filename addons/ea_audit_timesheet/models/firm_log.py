from odoo import api, fields, models
from odoo.http import request

from .common import refuse

KINDS = [
    ("support_login", "Connexion du compte technique"),
    ("user_invited", "Invitation"),
    ("link_issued", "Nouveau lien d'invitation"),
    ("role_changed", "Changement de rôle"),
    ("user_deactivated", "Désactivation"),
    ("user_reactivated", "Réactivation"),
    ("domains_changed", "Domaines autorisés"),
    ("mail_saved", "Serveur de messagerie enregistré"),
    ("mail_tested", "Test du serveur de messagerie"),
    ("mail_enabled", "Envoi activé"),
    ("mail_disabled", "Envoi désactivé"),
    ("project_changed", "Projet interne"),
    ("week_reopened", "Réouverture d'une semaine"),
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
            raise refuse("fa-forbidden")
        return super().create(vals_list)

    def write(self, vals):
        raise refuse("fa-forbidden")

    def unlink(self):
        raise refuse("fa-forbidden")

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
