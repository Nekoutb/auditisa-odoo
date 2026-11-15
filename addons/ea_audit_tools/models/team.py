"""The Engagement team tile (owner, 2026-11-15): who is on this file, in which role, and where
their invitation stands, with a way to invite someone. Every rule stays with the engagement's
team methods (invite_team_member, assign_team_member): this only opens the screens."""
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from ..rules import rule_error


class TeamMemberTool(models.Model):
    _inherit = "ea.audit.team.member"

    # Not stored: whether this reader may change a role here. Only a manager or above, on a
    # file that is not archived, sees the role cell open; the write path checks it again.
    ea_role_locked = fields.Boolean(string="Role read-only", compute="_compute_ea_role_locked")

    @api.depends_context("uid")
    def _compute_ea_role_locked(self):
        verdicts = {}
        for member in self:
            engagement = member.sudo().engagement_id
            if engagement.id not in verdicts:
                verdicts[engagement.id] = not engagement.with_env(self.env)._ea_may_manage_team()
            member.ea_role_locked = verdicts[engagement.id]

    def action_ea_invite_member(self):
        """The list's "Invite a member" button: the invitation form, set to this engagement."""
        engagement = self.env["ea.audit.engagement"].browse(self.env.context.get("ea_engagement_id")).exists()
        if not engagement:
            raise rule_error(self.env, "not-found")
        engagement._ea_require_team_manager()
        engagement._ea_assert_mutable()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Invite a member"),
            "res_model": "ea.audit.team.invite.wizard",
            "view_mode": "form",
            "views": [(self.env.ref("ea_audit_core.view_team_invite_wizard").id, "form")],
            "target": "new",
            "context": {"default_engagement_id": engagement.id, "ea_engagement_id": engagement.id},
        }


class EngagementTeamTool(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_may_manage_team(self):
        """True when this user may invite to the team and set roles: manager or above, a
        member of the file, not the EQR, and the file not archived."""
        self.ensure_one()
        try:
            self._ea_require_team_manager()
            self._ea_assert_mutable()
        except (UserError, AccessError):
            return False
        return True

    def action_tool_team(self):
        """The team of this engagement: members, role and status, and the invitation button."""
        self.ensure_one()
        self._ea_require_read()
        return self._ea_list(
            "ea.audit.team.member", self.env._("Engagement team"),
            [("ea_audit_tools.view_team_tool_list", "list")],
            {"context": {"ea_engagement_id": self.id, "default_engagement_id": self.id, "create": False}},
        )
