from odoo import api, fields, models

from ..services.errors import rule_error
from .signoff_policy import LADDER_SELECTION

TEAM_ROLE_SELECTION = LADDER_SELECTION + [("eqr_reviewer", "Engagement quality reviewer")]


class TeamMember(models.Model):
    """A seat on an engagement's team. The ORM entry points below route to the
    rule-bearing methods of ea.audit.engagement; those do their own checks and
    then write as superuser, the only path where self.env.su is true. There is
    deliberately no context key that relaxes anything: RPC callers set context."""

    _name = "ea.audit.team.member"
    _inherit = ["ea.audit.engagement.mixin"]
    _description = "Engagement team member"
    _order = "engagement_id, id"
    _rec_name = "user_id"

    user_id = fields.Many2one("res.users", string="Member", required=True, index=True, ondelete="restrict")
    email = fields.Char(related="user_id.login", string="Email")
    team_role = fields.Selection(TEAM_ROLE_SELECTION, required=True, default="staff")
    state = fields.Selection(
        [("invited", "Invited"), ("accepted", "Accepted"), ("declined", "Declined")],
        string="Status", required=True, default="invited", index=True,
    )
    invited_at = fields.Datetime()
    responded_at = fields.Datetime()
    decline_reason = fields.Char()
    eqr_declaration = fields.Boolean(string="Objectivity declaration")
    eqr_declared_at = fields.Datetime(string="Declared at")
    eqr_declared_by_id = fields.Many2one("res.users", string="Declared by", ondelete="restrict")

    # What an invited member sees before accepting: the invitation's own facts.
    invitation_engagement_name = fields.Char(
        string="Engagement name", compute="_compute_invitation", compute_sudo=True,
    )
    invitation_client_name = fields.Char(string="Client", compute="_compute_invitation", compute_sudo=True)
    invitation_fiscal_year = fields.Integer(string="Fiscal year", compute="_compute_invitation", compute_sudo=True)

    _engagement_user_uniq = models.Constraint(
        "UNIQUE(engagement_id, user_id)", "This person is already on the engagement team.",
    )
    # the database closes the race _check_one_partner cannot see
    _one_partner_seat = models.UniqueIndex(
        "(engagement_id) WHERE team_role = 'partner' AND state <> 'declined'",
        "This engagement already has its engagement partner.",
    )

    @api.depends("engagement_id")
    def _compute_invitation(self):
        for member in self:
            engagement = member.engagement_id
            member.invitation_engagement_name = engagement.display_name
            member.invitation_client_name = engagement.client_id.name
            member.invitation_fiscal_year = engagement.fiscal_year

    @api.constrains("team_role", "state", "engagement_id")
    def _check_one_partner(self):
        """Backstop of the partner-seat rule, whichever path wrote the row."""
        for member in self.sudo().filtered(lambda m: m.team_role == "partner" and m.state != "declined"):
            others = self.sudo().search_count([
                ("engagement_id", "=", member.engagement_id.id),
                ("id", "!=", member.id),
                ("team_role", "=", "partner"),
                ("state", "!=", "declined"),
            ])
            if others:
                raise rule_error(self.env, "one-engagement-partner")

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.su:
            return super().create(vals_list)
        # Adding a row from the team list is an invitation: nobody is made an
        # accepted member by writing state on a row.
        members = self.browse()
        for vals in vals_list:
            engagement = self.env["ea.audit.engagement"].browse(vals.get("engagement_id"))
            user = self.env["res.users"].browse(vals.get("user_id"))
            members |= engagement._ea_invite_user(
                user, vals.get("team_role") or "staff", bool(vals.get("eqr_declaration")),
            )
        return members

    def write(self, vals):
        if self.env.su:
            return super().write(vals)
        if set(vals) - {"team_role", "eqr_declaration"}:
            raise rule_error(self.env, "forbidden")
        for member in self:
            engagement = member.engagement_id
            engagement.assign_team_member(
                member.user_id.id,
                vals.get("team_role", member.team_role),
                bool(vals.get("eqr_declaration", member.eqr_declaration)),
            )
        return True

    def unlink(self):
        if self.env.su:
            return super().unlink()
        for member in self:
            member.engagement_id.remove_team_member(member.user_id.id)
        return True

    def _ea_own_open_invitation(self):
        """The row as superuser, when it is the caller's own. Their answer is
        the only write an invited member may make, and it goes through here."""
        self.ensure_one()
        member = self.sudo()
        if not member.exists() or member.user_id != self.env.user:
            raise rule_error(self.env, "not-found")
        return member if member.state == "invited" else None

    def action_accept(self):
        member = self._ea_own_open_invitation()
        if member:
            member.write({"state": "accepted", "responded_at": fields.Datetime.now(), "decline_reason": False})
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_decline(self, reason=""):
        """A decline carries its reason and reaches the engagement partner's trail."""
        why = (reason or "").strip()
        if not why:
            raise rule_error(self.env, "reason-required")
        member = self._ea_own_open_invitation()
        if member:
            member.write({"state": "declined", "responded_at": fields.Datetime.now(), "decline_reason": why})
            member.engagement_id._ea_log(
                "engagement_declined", "%s declined the engagement: %s" % (member.user_id.name, why[:400]),
            )
        return {"type": "ir.actions.client", "tag": "soft_reload"}
