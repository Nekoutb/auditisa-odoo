from odoo import models

from ..services.presentation import TEAM_ROLE_LABELS


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_seat_invitation(self, user, team_role, eqr_declaration):
        member = super()._ea_seat_invitation(user, team_role, eqr_declaration)
        as_root = self.sudo()
        env = self.with_context(lang=user.sudo().lang or self.env.lang).env
        role = env._(TEAM_ROLE_LABELS[team_role]) if team_role in TEAM_ROLE_LABELS else team_role
        self.env["ea.audit.notification"].sudo().create({
            "user_id": user.id,
            "kind": "invitation",
            "title": env._("Invitation: %(client)s", client=as_root.client_id.name),
            "detail": env._("You are invited as %(role)s, fiscal year %(year)s", role=role, year=as_root.fiscal_year),
            "engagement_id": self.id,
        })
        return member
