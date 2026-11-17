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

    # The profile questionnaire leads back to these screens rather than to the raw forms.
    def _ea_open_engagement_screen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_ui.dashboard",
            "name": self.env._("Engagement dashboard"), "params": {"resId": self.id},
        }

    def _ea_open_task_list(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_ui.all_tasks",
            "name": self.env._("Tasks"), "params": {"resId": self.id},
        }

    def _ea_wa_deadline(self, item):
        """Work allocation shows the one deadline the task lists and the dashboard show (F011)."""
        return item._ea_deadline_payload()["date"]

    def _ea_board(self, view_xmlid, name):
        """A tool board names its view, so "? Help" in the top bar opens the page of that board."""
        action = super()._ea_board(view_xmlid, name)
        action["context"] = dict(action.get("context") or {}, ea_help_view=view_xmlid)
        return action
