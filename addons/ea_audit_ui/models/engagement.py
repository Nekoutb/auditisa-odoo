from odoo import models

from ..services.presentation import TEAM_ROLE_LABELS


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_seat_invitation(self, user, team_role, eqr_declaration):
        member = super()._ea_seat_invitation(user, team_role, eqr_declaration)
        as_root = self.sudo()
        self.env["ea.audit.notification"].sudo().create({
            "user_id": user.id,
            "kind": "invitation",
            "title": "Invitation : %s" % as_root.client_id.name,
            "detail": "Vous êtes invité comme %s, exercice %s" % (
                TEAM_ROLE_LABELS.get(team_role, team_role), as_root.fiscal_year,
            ),
            "engagement_id": self.id,
        })
        return member
