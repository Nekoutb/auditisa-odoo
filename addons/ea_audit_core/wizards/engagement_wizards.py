from odoo import api, fields, models

from ..models.engagement import COMPLEXITY_SELECTION, NATURE_SELECTION
from ..models.signoff_policy import LADDER_SELECTION
from ..models.team_member import TEAM_ROLE_SELECTION
from ..services.errors import rule_error


class EngagementCreateWizard(models.TransientModel):
    """Opening a file. A wizard, not the engagement form: a partner may open a
    file for another partner and may not read it back afterwards (F008), and the
    standard form would read the new row in the same transaction."""

    _name = "ea.audit.engagement.create.wizard"
    _description = "New engagement"

    client_id = fields.Many2one("ea.audit.client", string="Client", required=True)
    fiscal_year = fields.Integer(required=True, default=lambda self: fields.Date.context_today(self).year - 1)
    period_end = fields.Date(required=True)
    name_preview = fields.Char(string="Name of the file", compute="_compute_name_preview")
    duration_months = fields.Integer(string="Duration (months)", default=12)
    nature = fields.Selection(NATURE_SELECTION, default="statutory_audit")
    complexity = fields.Selection(COMPLEXITY_SELECTION, default="complex")
    first_year = fields.Boolean(string="First-year audit")
    engagement_partner_id = fields.Many2one(
        "res.users", string="Engagement partner",
        domain=lambda self: [("all_group_ids", "in", self.env.ref("ea_audit_core.group_partner").ids)],
    )

    @api.depends("client_id", "fiscal_year")
    def _compute_name_preview(self):
        """F075: as the file will read; a dash until the client is chosen."""
        for wizard in self:
            wizard.name_preview = "%s %s" % (wizard.client_id.name, wizard.fiscal_year) if wizard.client_id else "—"

    @api.onchange("period_end")
    def _onchange_period_end(self):
        if self.period_end:
            self.fiscal_year = self.period_end.year

    def action_create(self):
        self.ensure_one()
        if self.fiscal_year < 1900:
            raise rule_error(self.env, "fiscal-year-required")
        engagement = self.env["ea.audit.engagement"].create({
            "client_id": self.client_id.id,
            "fiscal_year": self.fiscal_year,
            "period_end": self.period_end,
            "duration_months": self.duration_months,
            "nature": self.nature,
            "complexity": self.complexity,
            "first_year": self.first_year,
            "engagement_partner_id": self.engagement_partner_id.id,
        })
        return engagement._ea_open_or_notify()


class TeamInviteWizard(models.TransientModel):
    _name = "ea.audit.team.invite.wizard"
    _description = "Invite to the engagement team"

    engagement_id = fields.Many2one("ea.audit.engagement", string="Engagement", required=True)
    email = fields.Char(required=True)
    display_name_typed = fields.Char(string="Name")
    team_role = fields.Selection(TEAM_ROLE_SELECTION, required=True, default="staff")
    eqr_declaration = fields.Boolean(string="Objectivity declaration")

    def action_invite(self):
        self.ensure_one()
        self.engagement_id.invite_team_member(
            self.email, self.team_role, self.display_name_typed, self.eqr_declaration,
        )
        return {"type": "ir.actions.act_window_close"}


class PartnerTransferWizard(models.TransientModel):
    _name = "ea.audit.partner.transfer.wizard"
    _description = "Transfer the engagement partner role"

    engagement_id = fields.Many2one("ea.audit.engagement", string="Engagement", required=True)
    new_user_id = fields.Many2one(
        "res.users", string="New engagement partner", required=True,
        domain=lambda self: [("all_group_ids", "in", self.env.ref("ea_audit_core.group_partner").ids)],
    )
    outgoing_role = fields.Selection(LADDER_SELECTION, string="Outgoing partner's new role", required=True, default="director")

    def action_transfer(self):
        self.ensure_one()
        self.engagement_id.transfer_engagement_partner(self.new_user_id.id, self.outgoing_role)
        return {"type": "ir.actions.act_window_close"}


class TeamDeclineWizard(models.TransientModel):
    """The invited member cannot read the engagement, nor write their row: their
    answer goes through action_decline."""

    _name = "ea.audit.team.decline.wizard"
    _description = "Decline the engagement"

    member_id = fields.Many2one("ea.audit.team.member", required=True)
    reason = fields.Char(required=True)

    def action_decline(self):
        self.ensure_one()
        return self.member_id.action_decline(self.reason)
