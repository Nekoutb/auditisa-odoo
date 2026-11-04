from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from ..services.email_domains import email_domain_allowed, is_valid_email
from ..services.errors import rule_error, gate_label
from ..services.file_scope import code_in_scope, nature_has_audit_programme
from ..services.signoff_rules import (
    EQR_ROLE,
    TEAM_LADDER,
    at_least,
    can_write,
    may_hold_partner_seat,
)
from ..services.standards_edition import STANDARDS_EDITIONS, edition_for_period

PHASE_SELECTION = [
    ("acceptance", "Acceptance"),
    ("planning", "Planning"),
    ("execution", "Execution"),
    ("conclusion", "Conclusion"),
    ("archived", "Archived"),
]
NATURE_SELECTION = [
    ("statutory_audit", "Statutory audit"),
    ("contractual_audit", "Contractual audit"),
    ("limited_review", "Limited review (ISRE 2400/2410)"),
    ("commissariat_apports", "Contribution auditor (commissariat aux apports)"),
    ("agreed_procedures", "Agreed-upon procedures"),
    ("other", "Other"),
]
COMPLEXITY_SELECTION = [("complex", "Complex"), ("non_complex", "Non-complex"), ("very_simple", "Very simple")]
EDITION_SELECTION = [("current", "ISA in force"), ("revised_2026", "ISA revised (periods from 15 December 2026)")]

# Written only by the methods that carry their rule.
_ENGINE_FIELDS = {"phase", "standards_edition", "edition_reason", "archived_at"}
_CREATOR_SEAT = {"manager": "manager", "senior": "senior", "staff": "staff"}


class Engagement(models.Model):
    _name = "ea.audit.engagement"
    _inherit = ["mail.thread"]
    _description = "Audit engagement"
    _order = "fiscal_year desc, id desc"

    name = fields.Char(tracking=True)
    client_id = fields.Many2one("ea.audit.client", string="Client", required=True, index=True, ondelete="restrict")
    fiscal_year = fields.Integer(required=True, tracking=True)
    period_end = fields.Date(required=True, tracking=True)
    duration_months = fields.Integer(string="Duration (months)")
    nature = fields.Selection(NATURE_SELECTION, tracking=True)
    framework = fields.Char(tracking=True)
    first_year = fields.Boolean(string="First-year audit")
    complexity = fields.Selection(COMPLEXITY_SELECTION, default="complex", tracking=True)
    phase = fields.Selection(PHASE_SELECTION, required=True, default="acceptance", index=True, tracking=True)
    standards_edition = fields.Selection(EDITION_SELECTION, required=True, default="current", tracking=True)
    edition_reason = fields.Char()
    archived_at = fields.Datetime(copy=False)
    team_member_ids = fields.One2many("ea.audit.team.member", "engagement_id", string="Team")
    file_item_ids = fields.One2many("ea.audit.file.item", "engagement_id", string="File index")
    engagement_partner_id = fields.Many2one(
        "res.users", string="Engagement partner", compute="_compute_engagement_partner", compute_sudo=True,
    )
    partner_delegate_id = fields.Many2one(
        "res.users", string="Partner delegate", ondelete="set null", tracking=True, index="btree_not_null",
    )
    gate_summary = fields.Text(string="Gates of this phase", compute="_compute_gate_summary")

    @api.depends("client_id", "fiscal_year", "name")
    def _compute_display_name(self):
        for engagement in self.sudo():
            engagement.display_name = engagement.name or "%s %s" % (engagement.client_id.name, engagement.fiscal_year)

    @api.depends("team_member_ids.team_role", "team_member_ids.state")
    def _compute_engagement_partner(self):
        for engagement in self:
            seats = engagement.team_member_ids.filtered(lambda m: m.team_role == "partner" and m.state != "declined")
            accepted = seats.filtered(lambda m: m.state == "accepted")
            engagement.engagement_partner_id = (accepted or seats)[:1].user_id

    @api.depends("phase")
    @api.depends_context("lang")
    def _compute_gate_summary(self):
        for engagement in self:
            gates = []
            if not engagement._origin.id:
                gates = []
            elif engagement.phase == "acceptance":
                gates = engagement.sudo()._ea_acceptance_gates()
            elif engagement.phase == "planning":
                gates = engagement.sudo()._ea_planning_close_gates()
            engagement.gate_summary = "\n".join(
                "[%s] %s%s" % ("x" if g["ok"] else " ", gate_label(self.env, g["key"]), " (%s)" % g["detail"] if g.get("detail") else "")
                for g in gates
            ) or False

    # ------------------------------------------------------------------
    # Who is acting
    # ------------------------------------------------------------------

    @api.model
    def _ea_require_write(self):
        if not can_write(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "read-only-role")

    def _ea_member(self, user):
        self.ensure_one()
        return self.env["ea.audit.team.member"].sudo().search(
            [("engagement_id", "=", self.id), ("user_id", "=", user.id)], limit=1,
        )

    def _ea_require_access(self):
        """F008: only an accepted member opens the file, whatever their firm
        role. The record rules say the same; this gives the refusal its code."""
        for engagement in self:
            if engagement._ea_member(self.env.user).state != "accepted":
                raise rule_error(self.env, "not-on-this-engagement")

    def _ea_is_archived(self):
        self.ensure_one()
        return bool(self.sudo().archived_at) or self.sudo().phase == "archived"

    def _ea_assert_mutable(self):
        for engagement in self:
            if engagement._ea_is_archived():
                raise rule_error(self.env, "archived")

    def _ea_require_team_manager(self, team_role=None):
        role = self.env.user._ea_firm_role()
        if role == EQR_ROLE or not at_least(role, "manager"):
            raise rule_error(self.env, "team-manager-only")
        if team_role == "partner" and not at_least(role, "partner"):
            raise rule_error(self.env, "partner-only-team-role")
        self._ea_require_access()

    def _ea_partner_seat(self):
        """engagementPartnerTx: the accepted partner(s) and the delegate."""
        self.ensure_one()
        seats = self.env["ea.audit.team.member"].sudo().search([
            ("engagement_id", "=", self.id), ("team_role", "=", "partner"), ("state", "=", "accepted"),
        ])
        return seats.user_id, self.sudo().partner_delegate_id

    def _ea_is_appointed_eqr(self, user):
        member = self._ea_member(user)
        if not member or member.state == "declined":
            return False
        return member.team_role == EQR_ROLE or user._ea_firm_role() == EQR_ROLE

    def _ea_acts_as_eqr(self, user):
        if user._ea_firm_role() == EQR_ROLE:
            return True
        member = self._ea_member(user)
        return bool(member) and member.team_role == EQR_ROLE and member.state != "declined"

    def _ea_log(self, action, summary):
        """The activity trail: a note on the engagement's chatter."""
        user = self.env.user
        for engagement in self:
            engagement.sudo().message_post(
                body="%s: %s" % (action, summary),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
                author_id=user.partner_id.id,
                email_from=user.email_formatted or user.name,
            )

    # ------------------------------------------------------------------
    # Extension points of the later addons. A hook that reads output a later
    # addon produces fails closed until that addon overrides it; a hook that
    # counts blocking rows (risks, notes, ...) reads zero because none exists.
    # ------------------------------------------------------------------

    def _ea_p11_form_state(self):
        """ea_audit_papers: isFormComplete and p11FailedChecks on the P1.1 form."""
        return {"complete": False, "concluded_accept": False, "checks_passed": False}

    def _ea_open_review_notes(self, code_patterns):
        """ea_audit_papers: open notes on tasks matching the LIKE patterns."""
        return 0, []

    def _ea_materiality_approved(self):
        """ea_audit_tools: the latest materiality version is approved."""
        return False

    def _ea_ras_partner_approved(self):
        """ea_audit_papers: rasPartnerApprovedTx, the P7.2 summary's partner approval."""
        return False

    def _ea_unsupported_rely_count(self):
        """ea_audit_tools: CRA "rely" cells with no tested control and no basis."""
        return 0

    def _ea_unlinked_significant_risk_count(self):
        """ea_audit_tools: significant, non-rebutted risks with no program step."""
        return 0

    def _ea_unapproved_rebuttal_count(self):
        """ea_audit_tools: rebutted risks without the partner's approval."""
        return 0

    def _ea_section_has_planned_step(self, item):
        """ea_audit_tools: a program step not marked n/a on this material section."""
        return False

    def _ea_unmapped_tb_account_count(self):
        """ea_audit_tools: current-TB accounts matching no grouping rule or override."""
        return 0

    def _ea_planning_snapshot_data(self):
        """ea_audit_tools: materiality, risks and program steps as they close."""
        return {}

    def _ea_seed_presumed_risks(self):
        """ea_audit_tools: the two presumed ISA 240 risks."""

    def _ea_carry_forward_from(self, source):
        """ea_audit_tools and ea_audit_papers: carryForwardFromPriorYear, points forward."""

    def _ea_send_team_invitation(self, member, provisioned):
        """No mail in this milestone: the invitation shows under My invitations."""

    # ------------------------------------------------------------------
    # Creation, the file index, roll-forward
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            self._ea_require_write()
        partners = []
        for vals in vals_list:
            partner_id = vals.pop("engagement_partner_id", False)
            if not partner_id:
                raise rule_error(self.env, "engagement-partner-required")
            partner = self.env["res.users"].browse(partner_id)
            # the seat is a firm partner's or firm administrator's (F003)
            if not partner.exists() or not may_hold_partner_seat(partner._ea_firm_role()):
                raise rule_error(self.env, "partner-role-requires-partner-rank")
            partners.append(partner)
            if vals.get("period_end") and (not self.env.su or "standards_edition" not in vals):
                # F045: the edition follows the first day of the period
                vals["standards_edition"] = edition_for_period(
                    fields.Date.to_date(vals["period_end"]), vals.get("duration_months"),
                )
            if not vals.get("framework") and vals.get("client_id"):
                vals["framework"] = self.env["ea.audit.client"].sudo().browse(vals["client_id"]).framework
        # The creator may not be on the team (a partner opening a file for another
        # partner), so nothing here reads the new row back under their rights.
        quiet = self.with_context(tracking_disable=True, mail_create_nolog=True, mail_create_nosubscribe=True)
        records = super(Engagement, quiet).create(vals_list).with_env(self.env)
        creator_seat = _CREATOR_SEAT.get(self.env.user._ea_firm_role())
        now = fields.Datetime.now()
        Team = self.env["ea.audit.team.member"].sudo()
        for engagement, partner in zip(records, partners):
            as_root = engagement.sudo()
            if as_root.complexity:
                as_root._ea_instantiate_file_index()
                if nature_has_audit_programme(as_root.nature):
                    as_root._ea_seed_presumed_risks()
                if as_root.first_year:
                    as_root._ea_ensure_task("P1.2")
            Team.create({
                "engagement_id": engagement.id, "user_id": partner.id, "team_role": "partner",
                "state": "accepted", "responded_at": now,
            })
            # The creator joins the team (UAT B24). A partner or firm administrator
            # opening a file for another partner is NOT seated (F008).
            if creator_seat and self.env.user != partner:
                Team.create({
                    "engagement_id": engagement.id, "user_id": self.env.user.id,
                    "team_role": creator_seat, "state": "accepted",
                })
        return records

    def _ea_scoped_templates(self):
        self.ensure_one()
        form = self.client_id.legal_form
        return self.env["ea.audit.task.template"].sudo().search([]).filtered(
            lambda t: code_in_scope(t.code, t.tier, t.conditional, self.complexity, form, self.nature)
        )

    def _ea_instantiate_file_index(self):
        """Inserts only the codes missing, so a re-assessment adds and never removes."""
        self.ensure_one()
        have = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id)]).template_id
        self.env["ea.audit.file.item"].sudo().create([
            {"engagement_id": self.id, "template_id": t.id, "conditional": t.conditional}
            for t in self._ea_scoped_templates() - have
        ])

    def _ea_ensure_task(self, code):
        """ensureTaskTx: put a task on the file when a trigger makes it apply, or
        activate it. Idempotent; an archived file is left alone."""
        self.ensure_one()
        template = self.env["ea.audit.task.template"].sudo().search([("code", "=", code)], limit=1)
        if not template or self._ea_is_archived():
            return False
        Item = self.env["ea.audit.file.item"].sudo()
        item = Item.search([("engagement_id", "=", self.id), ("template_id", "=", template.id)], limit=1)
        if item:
            if item.conditional:
                item.conditional = False
                return True
            return False
        Item.create({"engagement_id": self.id, "template_id": template.id, "conditional": False})
        return True

    def apply_complexity(self, complexity, first_audit=False):
        """Port of applyComplexity: record the classification, add what it brings."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        self._ea_assert_mutable()
        as_root = self.sudo()
        as_root.complexity = complexity
        as_root._ea_instantiate_file_index()
        if nature_has_audit_programme(as_root.nature):
            as_root._ea_seed_presumed_risks()
        if first_audit:
            as_root._ea_ensure_task("P1.2")
        return True

    def rollforward(self, new_year):
        """Port of rollforward: a new file for a later year, carrying the prior
        year's accepted partner while they still hold partner rank."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        source = self.sudo()
        if new_year <= source.fiscal_year:
            raise rule_error(self.env, "invalid-year")
        partners, _delegate = source._ea_partner_seat()
        partners = partners.filtered(lambda u: may_hold_partner_seat(u._ea_firm_role()))
        if not partners:
            raise rule_error(self.env, "engagement-partner-required")
        target = self.create({
            "client_id": source.client_id.id,
            "fiscal_year": new_year,
            "period_end": source.period_end + relativedelta(years=new_year - source.fiscal_year),
            "engagement_partner_id": partners[0].id,
        })
        target.sudo()._ea_carry_forward_from(source)
        return target

    def action_rollforward_next_year(self):
        self.ensure_one()
        target = self.rollforward(self.fiscal_year + 1)
        return target._ea_open_or_notify()

    def _ea_open_or_notify(self):
        """Open the file when the caller is on its team. A partner who opened a
        file for another partner is not, and cannot open it (F008)."""
        self.ensure_one()
        if self._ea_member(self.env.user).state == "accepted":
            return {
                "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "current",
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._(
                    "The engagement was created. Its engagement partner staffs it: "
                    "you will see it once you are an accepted member of its team."
                ),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def write(self, vals):
        if self.env.su or not vals:
            return super().write(vals)
        self._ea_require_write()
        self._ea_require_access()
        self._ea_assert_mutable()
        if set(vals) & _ENGINE_FIELDS:
            raise rule_error(self.env, "forbidden")
        vals = dict(vals)
        if "partner_delegate_id" in vals:
            delegate = vals.pop("partner_delegate_id")
            for engagement in self:
                engagement.set_partner_delegate(delegate)
        # team_member_ids carries its own rules; the rest is the team's work
        if set(vals) - {"team_member_ids"} and any(e._ea_acts_as_eqr(self.env.user) for e in self):
            raise rule_error(self.env, "eqr-read-only")
        return super().write(vals) if vals else True

    def set_standards_edition(self, edition, reason):
        """Port of setStandardsEdition (F045)."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        if not at_least(self.env.user._ea_firm_role(), "manager"):
            raise rule_error(self.env, "forbidden")
        if edition not in STANDARDS_EDITIONS:
            raise rule_error(self.env, "invalid-standards-edition")
        why = (reason or "").strip()[:500]
        if not why:
            raise rule_error(self.env, "reason-required")
        self._ea_assert_mutable()
        as_root = self.sudo()
        before = as_root.standards_edition
        if before != edition:
            as_root.write({"standards_edition": edition, "edition_reason": why})
            self._ea_log("standards_edition_changed", "Standards edition changed from %s to %s: %s" % (before, edition, why))
        return True

    # ------------------------------------------------------------------
    # The team
    # ------------------------------------------------------------------

    def _ea_assert_member_domain(self, email):
        allowed = self.env["res.company"]._ea_allowed_domains()
        if not email_domain_allowed(email, allowed):
            raise rule_error(self.env, "email-domain-not-allowed", domains=", ".join(allowed))

    def _ea_assert_partner_seat(self, user, current, next_role):
        """assertPartnerSeatTx: only a firm partner or administrator holds it,
        one per engagement, and once accepted it cannot be left empty."""
        Team = self.env["ea.audit.team.member"].sudo()
        others = [("engagement_id", "=", self.id), ("user_id", "!=", user.id), ("team_role", "=", "partner")]
        if next_role == "partner":
            if not may_hold_partner_seat(user._ea_firm_role()):
                raise rule_error(self.env, "partner-role-requires-partner-rank")
            if Team.search_count(others + [("state", "!=", "declined")]):
                raise rule_error(self.env, "one-engagement-partner")
        if current and current.team_role == "partner" and current.state == "accepted" and next_role != "partner":
            if not Team.search_count(others + [("state", "=", "accepted")]):
                raise rule_error(self.env, "last-partner")

    def _ea_assert_eqr_eligible(self, user, declaration):
        """assertEqrEligibleTx (F005, ISQM 2 para. 18-20), the refusals in order."""
        role = user._ea_firm_role()
        if not (role == EQR_ROLE or may_hold_partner_seat(role)):
            raise rule_error(self.env, "eqr-rank")
        as_root = self.sudo()
        if as_root.partner_delegate_id == user:
            raise rule_error(self.env, "eqr-on-team")
        cooling = self.env["ea.audit.team.member"].sudo().search_count([
            ("user_id", "=", user.id),
            ("team_role", "=", "partner"),
            ("state", "=", "accepted"),
            ("engagement_id", "!=", self.id),
            ("engagement_id.client_id", "=", as_root.client_id.id),
            ("engagement_id.period_end", "<=", as_root.period_end),
            ("engagement_id.period_end", ">=", as_root.period_end - relativedelta(years=2)),
        ])
        if cooling:
            raise rule_error(self.env, "eqr-cooling-off")
        if declaration is not True:
            raise rule_error(self.env, "eqr-declaration-required")

    def _ea_record_eqr_declaration(self, member):
        member.write({
            "eqr_declaration": True,
            "eqr_declared_at": fields.Datetime.now(),
            "eqr_declared_by_id": self.env.user.id,
        })

    def assign_team_member(self, user_id, team_role, eqr_declaration=False):
        """Port of assignTeamMember: seat a firm member, accepted, or change the
        role of someone already on the team."""
        self.ensure_one()
        if team_role not in TEAM_LADDER and team_role != EQR_ROLE:
            raise rule_error(self.env, "invalid-team-role")
        self._ea_require_team_manager(team_role)
        self._ea_assert_mutable()
        user = self.env["res.users"].browse(user_id).exists()
        member = self._ea_member(user) if user else self.env["ea.audit.team.member"]
        if member.team_role == "partner" and team_role != "partner" and not at_least(self.env.user._ea_firm_role(), "partner"):
            raise rule_error(self.env, "partner-only-team-role")
        if not user or not user._ea_firm_role():
            raise rule_error(self.env, "not-a-firm-member")
        # a new member comes from an allowed domain (F070); re-roling does not re-check
        if not member:
            self._ea_assert_member_domain(user.login)
        if member and (team_role == EQR_ROLE) != (member.team_role == EQR_ROLE):
            raise rule_error(self.env, "eqr-on-team")
        appoints_eqr = team_role == EQR_ROLE and member.team_role != EQR_ROLE
        if appoints_eqr:
            self._ea_assert_eqr_eligible(user, eqr_declaration)
        self._ea_assert_partner_seat(user, member, team_role)
        if member:
            member.team_role = team_role
        else:
            member = member.create({
                "engagement_id": self.id, "user_id": user.id, "team_role": team_role, "state": "accepted",
                "responded_at": fields.Datetime.now(),
            })
        if appoints_eqr:
            self._ea_record_eqr_declaration(member)
        if team_role == EQR_ROLE:
            self.sudo()._ea_ensure_task("C4.2")
        return member.with_env(self.env)

    def _ea_invite_user(self, user, team_role, eqr_declaration=False):
        """The team half of addTeamMemberByEmail, for an existing firm user."""
        self.ensure_one()
        if team_role not in TEAM_LADDER and team_role != EQR_ROLE:
            raise rule_error(self.env, "invalid-team-role")
        self._ea_require_team_manager(team_role)
        self._ea_assert_mutable()
        if not user.exists() or not user._ea_firm_role():
            raise rule_error(self.env, "not-a-firm-member")
        self._ea_assert_member_domain(user.login)
        return self._ea_seat_invitation(user, team_role, eqr_declaration)

    def _ea_seat_invitation(self, user, team_role, eqr_declaration):
        member = self._ea_member(user)
        if member:
            if member.state != "declined":
                raise rule_error(self.env, "already-on-team")
            if (team_role == EQR_ROLE) != (member.team_role == EQR_ROLE):
                raise rule_error(self.env, "eqr-on-team")
        if team_role == "partner":
            self._ea_assert_partner_seat(user, None, "partner")
        if team_role == EQR_ROLE:
            self._ea_assert_eqr_eligible(user, eqr_declaration)
        vals = {
            "team_role": team_role, "state": "invited", "invited_at": fields.Datetime.now(),
            "decline_reason": False, "responded_at": False,
        }
        if member:
            member.write(vals)
        else:
            member = member.create(dict(vals, engagement_id=self.id, user_id=user.id))
        if team_role == EQR_ROLE:
            self._ea_record_eqr_declaration(member)
            self.sudo()._ea_ensure_task("C4.2")
        return member.with_env(self.env)

    def invite_team_member(self, email, team_role, display_name=None, eqr_declaration=False):
        """Port of addTeamMemberByEmail: the domain rule comes first, before any
        account is provisioned. An unknown address gets a staff account with no
        password; a colleague already in the firm keeps theirs."""
        self.ensure_one()
        if team_role not in TEAM_LADDER and team_role != EQR_ROLE:
            raise rule_error(self.env, "invalid-team-role")
        self._ea_require_team_manager(team_role)
        self._ea_assert_mutable()
        email = (email or "").strip().lower()
        if not is_valid_email(email):
            raise rule_error(self.env, "invalid-email")
        self._ea_assert_member_domain(email)
        Users = self.env["res.users"].sudo().with_context(active_test=False)
        user = Users.search(["|", ("login", "=ilike", email), ("email", "=ilike", email)], limit=1)
        provisioned = False
        if user:
            if not user._ea_firm_role():
                # someone outside the firm (a portal contact): never attach
                raise rule_error(self.env, "email-taken")
            if team_role == "partner" and not may_hold_partner_seat(user._ea_firm_role()):
                raise rule_error(self.env, "partner-role-requires-partner-rank")
        else:
            if team_role == "partner":
                raise rule_error(self.env, "partner-role-requires-partner-rank")
            if team_role == EQR_ROLE:
                raise rule_error(self.env, "eqr-rank")
            name = (display_name or "").strip() or email.split("@")[0].replace(".", " ").replace("_", " ").replace("-", " ").title()
            user = self._ea_provision_staff_user(email, name)
            provisioned = True
        member = self._ea_seat_invitation(user, team_role, eqr_declaration)
        self._ea_send_team_invitation(member, provisioned)
        return member

    def _ea_provision_staff_user(self, email, name):
        # res.users refuses group commands from a plain sudo; the rank given is
        # fixed here, not taken from the caller.
        staff = self.env.ref("ea_audit_core.group_staff")
        return self.env["res.users"].with_user(self.env.ref("base.user_root")).with_context(no_reset_password=True).create({
            "name": name, "login": email, "email": email, "group_ids": [(6, 0, [staff.id])],
        }).with_env(self.env)

    def remove_team_member(self, user_id):
        """Port of removeTeamMember. Their tasks go back to the unassigned pool."""
        self.ensure_one()
        self._ea_require_team_manager()
        self._ea_assert_mutable()
        user = self.env["res.users"].browse(user_id)
        member = self._ea_member(user)
        if member.team_role == "partner" and not at_least(self.env.user._ea_firm_role(), "partner"):
            raise rule_error(self.env, "partner-only-team-role")
        self._ea_assert_partner_seat(user, member, None)
        as_root = self.sudo()
        if as_root.partner_delegate_id == user:
            as_root.partner_delegate_id = False
        for field in ("preparer_id", "approver_id", "assignee_id"):
            as_root.file_item_ids.filtered(lambda i: i[field] == user).write({field: False})
        if member:
            summary = "%s removed from the team (%s)" % (user.sudo().name, member.team_role)
            member.unlink()
            self._ea_log("team_removed", summary)
        return True

    def transfer_engagement_partner(self, new_user_id, outgoing_role):
        """Port of transferEngagementPartner: the seat changes hands in one
        transaction, the incoming partner holding it at once."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        self._ea_assert_mutable()
        if outgoing_role not in TEAM_LADDER or outgoing_role == "partner":
            raise rule_error(self.env, "invalid-team-role")
        self.env.cr.execute("SELECT id FROM ea_audit_engagement WHERE id = %s FOR UPDATE", [self.id])
        Team = self.env["ea.audit.team.member"].sudo()
        seats = Team.search([
            ("engagement_id", "=", self.id), ("team_role", "=", "partner"), ("state", "!=", "declined"),
        ]).sorted(lambda m: (m.state != "accepted", m.id))
        if not seats:
            raise rule_error(self.env, "designate-engagement-partner-first")
        outgoing = seats[0]
        actor = self.env.user
        if actor._ea_firm_role() != "firm_admin" and actor != outgoing.user_id:
            raise rule_error(self.env, "transfer-partner-forbidden")
        new_user = self.env["res.users"].browse(new_user_id).exists()
        if new_user == outgoing.user_id:
            raise rule_error(self.env, "already-engagement-partner")
        if not new_user or not may_hold_partner_seat(new_user._ea_firm_role()):
            raise rule_error(self.env, "partner-role-requires-partner-rank")
        incoming = self._ea_member(new_user)
        if incoming.team_role == EQR_ROLE:
            raise rule_error(self.env, "eqr-on-team")
        if not incoming:
            self._ea_assert_member_domain(new_user.login)
        outgoing.team_role = outgoing_role
        outgoing.flush_recordset()
        now = fields.Datetime.now()
        if incoming:
            incoming.write({
                "team_role": "partner", "state": "accepted",
                "responded_at": incoming.responded_at or now, "decline_reason": False,
            })
        else:
            Team.create({
                "engagement_id": self.id, "user_id": new_user.id, "team_role": "partner",
                "state": "accepted", "responded_at": now,
            })
        # the new partner signs in their own right; nobody delegates to themselves
        as_root = self.sudo()
        if as_root.partner_delegate_id == new_user:
            as_root.partner_delegate_id = False
        self._ea_log(
            "engagement_partner_transferred",
            "Engagement partner transferred from %s to %s (%s now %s)" % (
                outgoing.user_id.name, new_user.sudo().name, outgoing.user_id.name, outgoing_role,
            ),
        )
        return True

    def set_partner_delegate(self, delegate_user_id):
        """Port of setPartnerDelegate. The engagement partner or a firm
        administrator decides; False clears the delegation."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        self._ea_assert_mutable()
        partners, _delegate = self._ea_partner_seat()
        actor = self.env.user
        if actor._ea_firm_role() != "firm_admin" and actor not in partners:
            raise rule_error(self.env, "not-engagement-partner")
        delegate = self.env["res.users"].browse(delegate_user_id).exists() if delegate_user_id else self.env["res.users"]
        if delegate_user_id:
            if not partners:
                raise rule_error(self.env, "designate-engagement-partner-first")
            if delegate in partners:
                raise rule_error(self.env, "delegate-is-partner")
            if not delegate or not may_hold_partner_seat(delegate._ea_firm_role()):
                raise rule_error(self.env, "delegate-requires-partner-rank")
            member = self._ea_member(delegate)
            if not member or member.state == "declined":
                raise rule_error(self.env, "delegate-not-on-team")
            if member.team_role == EQR_ROLE:
                raise rule_error(self.env, "eqr-on-team")
        as_root = self.sudo()
        if as_root.partner_delegate_id != delegate:
            as_root.partner_delegate_id = delegate
            self._ea_log(
                "partner_delegate_set" if delegate else "partner_delegate_cleared",
                "Partner sign-off delegated" if delegate else "Partner sign-off delegation cleared",
            )
        return True

    # ------------------------------------------------------------------
    # Gates (lib/gates.ts): "gates, not guidance"
    # ------------------------------------------------------------------

    def _ea_partner_signed(self, code):
        """An active partner sign-off on the WORKING PAPER of a code: a letter
        filed under the same index does not satisfy the gate."""
        return bool(self.env["ea.audit.signoff"].sudo().search_count([
            ("engagement_id", "=", self.id), ("code", "=", code), ("kind", "=", "workpaper"),
            ("role", "=", "partner"), ("voided_at", "=", False),
        ]))

    def _ea_approval_signed(self, code):
        """The partner's signature where the firm's rule requires one, otherwise
        the reviewer's: a firm lifting it must still be able to close the gate."""
        rule = self.env["ea.audit.signoff.policy"]._ea_effective_rule(code)
        if rule["partner_required"]:
            return self._ea_partner_signed(code)
        return bool(self.env["ea.audit.signoff"].sudo().search_count([
            ("engagement_id", "=", self.id), ("code", "=", code), ("kind", "=", "workpaper"),
            ("role", "in", ("reviewer", "partner")), ("voided_at", "=", False),
        ]))

    def _ea_task_active(self, code):
        return bool(self.env["ea.audit.file.item"].sudo().search_count([
            ("engagement_id", "=", self.id), ("code", "=", code), ("conditional", "=", False),
        ]))

    def _ea_review_notes_gate(self, patterns):
        count, codes = self._ea_open_review_notes(patterns)
        if not count:
            return {"key": "review_notes_cleared", "ok": True}
        return {"key": "review_notes_cleared", "ok": False, "detail": "%s · %s" % (count, ", ".join(codes))}

    def _ea_acceptance_gates(self):
        self.ensure_one()
        form = self._ea_p11_form_state()
        partners, _delegate = self._ea_partner_seat()
        # F008: no independence gate, declarations are obtained outside the system.
        return [
            {"key": "d31_form_complete", "ok": bool(form["complete"] and form["concluded_accept"])},
            {"key": "d31_checks_passed", "ok": bool(form["complete"] and form["checks_passed"])},
            {"key": "d31_partner_signed", "ok": self._ea_approval_signed("P1.1")},
            {"key": "engagement_partner_designated", "ok": len(partners) == 1},
            self._ea_review_notes_gate(["P1.%"]),
        ]

    def _ea_planning_close_gates(self):
        self.ensure_one()
        papers = []
        # a paper gate applies where the task is on this file (UAT run 2 B09)
        for code in ("P2.2", "P5.2", "S3.1"):
            if self._ea_task_active(code):
                papers.append({
                    "key": "%s_partner_signed" % code.lower().replace(".", ""),
                    "ok": self._ea_approval_signed(code),
                })
        papers.append({"key": "p72_partner_signed", "ok": bool(self._ea_ras_partner_approved())})
        material = self.env["ea.audit.file.item"].sudo().search([
            ("engagement_id", "=", self.id), ("section", "=", "E"), ("material", "=", True),
        ])
        uncovered = material.filtered(lambda item: not self._ea_section_has_planned_step(item))
        return [
            {"key": "materiality_approved", "ok": bool(self._ea_materiality_approved())},
            *papers,
            {"key": "cra_reliance_supported", "ok": self._ea_unsupported_rely_count() == 0},
            {"key": "significant_risks_linked", "ok": self._ea_unlinked_significant_risk_count() == 0},
            {"key": "rebuttals_approved", "ok": self._ea_unapproved_rebuttal_count() == 0},
            {"key": "material_sections_covered", "ok": not uncovered},
            {"key": "tb_mapped", "ok": self._ea_unmapped_tb_account_count() == 0},
            self._ea_review_notes_gate(["P%", "S%"]),
        ]

    def acceptance_gates(self):
        self.ensure_one()
        self._ea_require_access()
        return self.sudo()._ea_acceptance_gates()

    def planning_close_gates(self):
        self.ensure_one()
        self._ea_require_access()
        return self.sudo()._ea_planning_close_gates()

    def _ea_lock_phase(self, expected):
        """Gate check and mutation run in one transaction with the row locked,
        so a double-submit cannot slip through."""
        self.env.cr.execute("SELECT phase FROM ea_audit_engagement WHERE id = %s FOR UPDATE", [self.id])
        row = self.env.cr.fetchone()
        if not row:
            raise rule_error(self.env, "not-found")
        if row[0] != expected:
            raise rule_error(self.env, "wrong-phase")
        self.invalidate_recordset(["phase"])

    def _ea_raise_failed_gates(self, gates):
        failed = [g["key"] for g in gates if not g["ok"]]
        if failed:
            labels = ", ".join(gate_label(self.env, key) for key in failed)
            raise rule_error(self.env, "gates-failed:%s" % ",".join(failed), gates=labels)

    def advance_to_planning(self):
        """acceptance -> planning: gate check and transition atomically."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        self._ea_lock_phase("acceptance")
        as_root = self.sudo()
        self._ea_raise_failed_gates(as_root._ea_acceptance_gates())
        as_root.phase = "planning"
        self._ea_log("phase_advanced", "Acceptance gates passed: engagement moved to planning")
        return True

    def close_planning(self):
        """planning -> execution: gates, snapshot and transition in one transaction."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        self._ea_lock_phase("planning")
        as_root = self.sudo()
        self._ea_raise_failed_gates(as_root._ea_planning_close_gates())
        self.env["ea.audit.planning.snapshot"].sudo().create({
            "engagement_id": self.id,
            "data": as_root._ea_planning_snapshot_data(),
            "taken_by_id": self.env.user.id,
        })
        as_root.phase = "execution"
        self._ea_log("phase_advanced", "Planning closed: snapshot taken, engagement moved to execution")
        return True
