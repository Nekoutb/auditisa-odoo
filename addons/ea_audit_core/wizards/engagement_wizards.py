from datetime import date

from odoo import api, fields, models

from ..models.engagement import NEW_NATURE_SELECTION, REPORT_LANGUAGE_SELECTION
from ..models.signoff_policy import LADDER_SELECTION
from ..models.team_member import TEAM_ROLE_SELECTION
from ..services.errors import rule_error
from ..services.signoff_rules import may_hold_partner_seat


class EngagementCreateWizard(models.TransientModel):
    """Opening a file. A wizard, not the engagement form: a partner may open a
    file for another partner and may not read it back afterwards (F008), and the
    standard form would read the new row in the same transaction.

    Owner's rulings of 2026-11-15: nothing about the client's profile is asked here. The
    questionnaire opens right after, and the tasks come from its conclusion."""

    _name = "ea.audit.engagement.create.wizard"
    _description = "New engagement"

    client_id = fields.Many2one("ea.audit.client", string="Client", required=True)
    name = fields.Char(string="Engagement name")
    nature = fields.Selection(NEW_NATURE_SELECTION, string="Nature of the service")
    fiscal_year = fields.Integer(string="Financial year", required=True, default=lambda self: fields.Date.context_today(self).year - 1)
    period_start = fields.Date(string="Audit period from", default=lambda self: date(fields.Date.context_today(self).year - 1, 1, 1))
    period_end = fields.Date(string="to", required=True, default=lambda self: date(fields.Date.context_today(self).year - 1, 12, 31))
    report_language = fields.Selection(
        REPORT_LANGUAGE_SELECTION, string="Report language", required=True,
        default=lambda self: self.env["ea.audit.engagement"]._ea_firm_language(),
    )
    engagement_partner_id = fields.Many2one(
        "res.users", string="Engagement partner",
        domain=lambda self: [("all_group_ids", "in", self.env.ref("ea_audit_core.group_partner").ids)],
    )

    # owner, 2026-11-17: a partner who opens a file for another partner is not on its team
    # (team-only access), and is told so before creating it. No rule changes here.
    partner_warning = fields.Char(string="Team warning", compute="_compute_partner_warning")

    @api.depends("engagement_partner_id")
    @api.depends_context("uid")
    def _compute_partner_warning(self):
        creator = self.env.user
        creator_is_partner = may_hold_partner_seat(creator._ea_firm_role())
        for wizard in self:
            chosen = wizard.engagement_partner_id
            if creator_is_partner and chosen and chosen != creator:
                wizard.partner_warning = self.env._(
                    "You will not be on this engagement's team. To open it later, ask %(partner)s to add you.",
                    partner=chosen.name,
                )
            else:
                wizard.partner_warning = False

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
            "name": (self.name or "").strip() or False,
            "nature": self.nature or False,
            "fiscal_year": self.fiscal_year,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "report_language": self.report_language,
            # no level yet: the questionnaire works it out, and only then are the tasks made
            "complexity": False,
            "engagement_partner_id": self.engagement_partner_id.id,
        })
        return engagement._ea_open_profile_or_notify()


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
