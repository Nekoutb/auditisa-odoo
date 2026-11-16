from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from ..models.team_member import TEAM_ROLE_SELECTION
from ..services.errors import rule_error
from ..services.rollforward_plan import CARRY_FIELDS, NOTE_DECLINED, NOTE_LEFT, carry_keys, team_lines
from ..services.signoff_rules import may_hold_partner_seat


class RollforwardWizard(models.TransientModel):
    """Roll forward to next year: choose what to carry, then confirm the year, the team and the
    approach. The new file starts with nothing concluded or signed; each member accepts the
    invitation, confirming independence, before working on it."""

    _name = "ea.audit.rollforward.wizard"
    _description = "Roll forward to next year"

    source_id = fields.Many2one("ea.audit.engagement", string="From the file", required=True, readonly=True)
    source_label = fields.Char(string="From", compute="_compute_labels")
    intro = fields.Char(compute="_compute_labels")
    period_end = fields.Date(string="Year end", required=True)
    new_year = fields.Integer(string="New year", compute="_compute_labels")
    engagement_partner_id = fields.Many2one(
        "res.users", string="Engagement partner", required=True,
        domain=lambda self: [("all_group_ids", "in", self.env.ref("ea_audit_core.group_partner").ids)],
    )
    carry_scope = fields.Boolean(string="Tasks and scope (profile answers)", default=True,
                                 help="Carried to re-confirm: the questionnaire is not concluded in the new file.")
    carry_materiality = fields.Boolean(string="Materiality basis and percentages (no amounts)", default=True,
                                       help="The basis and the percentages, to re-confirm. The amounts are worked out again from this year's figures.")
    carry_scots = fields.Boolean(string="SCOTs, controls and walkthrough notes", default=True,
                                 help="As drafts, to update: every test result, conclusion and sign-off starts again.")
    carry_risks = fields.Boolean(string="Risk register and lead-index links", default=True,
                                 help="As drafts: each risk assessment is to re-confirm.")
    carry_procedures = fields.Boolean(string="Procedure design (chosen ASPs and own procedures)", default=True,
                                      help="As drafts, not started, with no conclusion.")
    carry_significance = fields.Boolean(string="Significance decisions", default=True, help="As drafts, to re-confirm.")
    carry_comparatives = fields.Boolean(string="Prior-year balances as comparatives (ISA 510)", default=True,
                                        help="Last year's closing trial balance becomes the prior-year trial balance of the new file.")
    carry_answers = fields.Boolean(string="Paper answers", default=True,
                                   help="Every working paper's answers, as drafts marked \"Carried forward: to update\". "
                                        "Sign-offs, conclusions, completion records and review notes start again.")
    carry_evidence = fields.Boolean(string="All of last year's evidence", default=True,
                                    help="Copied to the new file and marked \"Prior year, carried forward: review before relying on it\".")
    approach = fields.Selection(
        [("same", "Same as last year"), ("change", "Change")], string="Approach", required=True, default="same",
        help="Change: the profile questionnaire opens again in the new file and its conclusion gives the tasks.",
    )
    member_ids = fields.One2many("ea.audit.rollforward.member", "wizard_id", string="Team")

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        source = self.env["ea.audit.engagement"].browse(values.get("source_id") or self.env.context.get("active_id"))
        if not source.exists():
            return values
        root = source.sudo()
        values["source_id"] = source.id
        values.setdefault("period_end", root.period_end + relativedelta(years=1))
        partners, _delegate = root._ea_partner_seat()
        partner = partners.filtered(lambda u: may_hold_partner_seat(u._ea_firm_role()))[:1]
        if partner:
            values.setdefault("engagement_partner_id", partner.id)
        if "member_ids" in field_names:
            values["member_ids"] = [(0, 0, line) for line in self._ea_member_lines(root)]
        return values

    @api.model
    def _ea_member_lines(self, root):
        """Last year's team, partner apart: those still in the firm ticked to invite again, those
        who left or declined unticked."""
        notes = {NOTE_LEFT: self.env._("No longer in the firm: not carried"), NOTE_DECLINED: self.env._("Declined last year")}
        lines = team_lines([{
            "email": member.user_id.login, "name": member.user_id.name, "role": member.team_role, "state": member.state,
            "active": member.user_id.active and bool(member.user_id._ea_firm_role()),
        } for member in root.team_member_ids])
        return [dict(line, note=notes.get(line["note"], False), carried=True) for line in lines]

    @api.depends("source_id", "period_end")
    def _compute_labels(self):
        for wizard in self:
            root = wizard.source_id.sudo()
            year = root.fiscal_year + (wizard.period_end.year - root.period_end.year) if root and wizard.period_end else 0
            wizard.new_year = year
            wizard.source_label = root.display_name if root else ""
            wizard.intro = self.env._(
                "A new file for %(client)s, year ending %(date)s. Nothing is concluded or signed in the new file; "
                "each member confirms independence before working.",
                client=root.client_id.name or "", date=wizard.period_end.strftime("%d/%m/%Y") if wizard.period_end else "",
            ) if root else ""

    def _ea_options(self):
        self.ensure_one()
        return {
            "carry": carry_keys({field: self[field] for field, _key in CARRY_FIELDS}),
            "approach": self.approach,
            "period_end": self.period_end,
            "partner_id": self.engagement_partner_id.id,
            "members": [
                {"email": line.email, "role": line.team_role, "name": line.name, "eqr_declaration": line.eqr_declaration}
                for line in self.member_ids if line.invite and line.email
            ],
        }

    def action_create(self):
        self.ensure_one()
        source = self.source_id.with_env(self.env)
        if not source._ea_may_roll_forward():
            raise rule_error(self.env, "rollforward-not-closed")
        target = source.rollforward(self.new_year, self._ea_options())
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "sticky": True,
                "message": self.env._(
                    "The %(year)s file is created. Accept its invitation under My invitations to confirm your "
                    "independence and open it; each member of the team does the same.",
                    year=target.sudo().fiscal_year,
                ),
                "next": self.env["ir.actions.actions"]._for_xml_id("ea_audit_core.action_my_invitations"),
            },
        }


class RollforwardMember(models.TransientModel):
    _name = "ea.audit.rollforward.member"
    _description = "Roll forward: a member to invite"

    wizard_id = fields.Many2one("ea.audit.rollforward.wizard", required=True, ondelete="cascade")
    invite = fields.Boolean(string="Invite", default=True)
    email = fields.Char(string="Email")
    name = fields.Char(string="Name")
    team_role = fields.Selection(TEAM_ROLE_SELECTION, string="Role", required=True, default="staff")
    eqr_declaration = fields.Boolean(string="Objectivity declaration")
    carried = fields.Boolean(string="On last year's team", readonly=True)
    note = fields.Char(string="Note", readonly=True)
