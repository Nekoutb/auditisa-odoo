from odoo import api, fields, models

from ..services.conditional_triggers import trigger_text
from ..services.errors import rule_error
from ..services.phases import phase_still_open
from ..services.signoff_rules import (
    EQR_PAPER,
    EQR_ROLE,
    PARTNER_GATED,
    PARTNER_ONLY_APPROVAL,
    SIGNOFF_ROLES,
    below_minimum_code,
    can_partner_signoff,
    can_review,
    team_rank,
)
from ..services.tool_fed import tool_output_missing_code, tool_outputs_for

# file_item column -> who the task's preparer rules apply to
_ASSIGNMENT_FIELD = {"preparer": "preparer_id", "approver": "approver_id", "assignee": "assignee_id"}
_ENGINE_FIELDS = {"state", "template_id", "engagement_id", "conditional", "code", "section"}


class FileItem(models.Model):
    """One task of the file index on one engagement (file_item)."""

    _name = "ea.audit.file.item"
    _inherit = ["ea.audit.engagement.mixin"]
    _description = "Audit file task"
    _order = "engagement_id, sequence, id"
    _rec_name = "code"

    template_id = fields.Many2one("ea.audit.task.template", string="Task", required=True, index=True, ondelete="restrict")
    code = fields.Char(related="template_id.code", store=True, index=True)
    section = fields.Selection(related="template_id.section", store=True)
    title = fields.Char(related="template_id.title")
    short_title = fields.Char(related="template_id.short_title")
    task_phase = fields.Selection(related="template_id.phase")
    sequence = fields.Integer(related="template_id.sequence", store=True)
    state = fields.Selection(
        [
            ("not_started", "Not started"),
            ("in_progress", "In progress"),
            ("prepared", "Prepared"),
            ("reviewed", "Reviewed"),
            ("signed", "Signed"),
        ],
        required=True, default="not_started", index=True,
    )
    conditional = fields.Boolean(help="True while the trigger is unanswered: the task is not active on the file.")
    not_applicable = fields.Boolean(string="Not applicable")
    material = fields.Boolean(help="Material E-section: planning cannot close without planned coverage.")
    preparer_id = fields.Many2one("res.users", string="Preparer", index=True, ondelete="restrict")
    approver_id = fields.Many2one("res.users", string="Reviewer", index=True, ondelete="restrict")
    assignee_id = fields.Many2one("res.users", string="Assignee", index=True, ondelete="restrict")
    due_date = fields.Date()
    signoff_ids = fields.One2many("ea.audit.signoff", "file_item_id", string="Sign-offs")
    tool_outputs_missing = fields.Char(
        string="Missing tool output", compute="_compute_tool_outputs_missing", compute_sudo=True,
    )
    team_user_ids = fields.Many2many(
        "res.users", string="Team members", compute="_compute_team_user_ids", compute_sudo=True,
        help="Who a task can go to: the accepted members of the team, the quality reviewer apart.",
    )
    conditional_trigger = fields.Char(string="Comes onto the file when", compute="_compute_conditional_trigger")

    _engagement_template_uniq = models.Constraint(
        "UNIQUE(engagement_id, template_id)", "This task is already on the file.",
    )

    @api.depends("code")
    def _compute_tool_outputs_missing(self):
        for item in self:
            item.tool_outputs_missing = item._ea_tool_output_missing() or False

    @api.depends("engagement_id")
    def _compute_team_user_ids(self):
        for item in self:
            item.team_user_ids = item.engagement_id.team_member_ids.filtered(
                lambda member: member.state == "accepted" and member.team_role != EQR_ROLE
            ).user_id

    @api.depends_context("lang")
    @api.depends("code", "conditional")
    def _compute_conditional_trigger(self):
        for item in self:
            item.conditional_trigger = trigger_text(item.code, self.env.lang) if item.conditional else False

    # ------------------------------------------------------------------
    # Extension points of the later addons. Until they are installed, the
    # output or paper they read does not exist: what depends on it is refused.
    # ------------------------------------------------------------------

    def _ea_tool_output_present(self, output):
        """ea_audit_tools: materiality approved, valid TB, SAD conclusion."""
        return False

    def _ea_document_refusal(self, role):
        """ea_audit_papers: no-version, checked-out."""
        return None

    def _ea_paper_refusal(self, role):
        """ea_audit_papers: paper-incomplete, embedded-work gaps, significance-
        unjustified (P6.2), itapp-strategy-missing (S2.3)."""
        return None

    def _ea_review_refusal(self):
        """ea_audit_papers: open-notes, review-conclusion-first."""
        return None

    def _ea_paper_content_hash(self):
        """ea_audit_papers: the hash that binds a signature to the answers."""
        return ""

    def _ea_paper_version(self):
        """ea_audit_papers: the current version of the document."""
        return 0

    # ------------------------------------------------------------------

    def _ea_tool_output_missing(self):
        self.ensure_one()
        for output in tool_outputs_for(self.code or ""):
            if not self._ea_tool_output_present(output):
                return tool_output_missing_code(output)
        return None

    def write(self, vals):
        if self.env.su:
            return super().write(vals)
        if set(vals) & _ENGINE_FIELDS:
            raise rule_error(self.env, "forbidden")
        vals = dict(vals)
        for role, field in _ASSIGNMENT_FIELD.items():
            if field in vals:
                self.assign_tasks(vals.pop(field), role)
        if vals:
            self.env["ea.audit.engagement"]._ea_require_write()
            for item in self.sudo():
                engagement = item.engagement_id.with_env(self.env)
                engagement._ea_require_access()
                engagement._ea_assert_mutable()
                # the quality reviewer writes on C4.2 only (assertNotEqrWriteOnItem)
                if item.code != EQR_PAPER and engagement._ea_acts_as_eqr(self.env.user):
                    raise rule_error(self.env, "eqr-read-only")
        return super().write(vals) if vals else True

    def assign_tasks(self, user_id, role="assignee"):
        """Port of assignTasks / assignTask, with assertAssignmentRulesTx. False
        unassigns. Returns how many tasks were repointed."""
        if not self:
            return 0
        if role not in _ASSIGNMENT_FIELD:
            raise rule_error(self.env, "forbidden")
        Engagement = self.env["ea.audit.engagement"]
        Engagement._ea_require_write()
        items = self.sudo()
        for engagement in items.engagement_id:
            engagement.with_env(self.env)._ea_require_access()
            engagement.with_env(self.env)._ea_assert_mutable()
            # staffing the team's work is not the independent reviewer's call
            if engagement._ea_acts_as_eqr(self.env.user):
                raise rule_error(self.env, "eqr-read-only")
        user = self.env["res.users"].browse(user_id) if user_id else None
        policy = self.env["ea.audit.signoff.policy"]._ea_policy()
        if user:
            for item in items:
                member = item.engagement_id._ea_member(user)
                if not member:
                    raise rule_error(self.env, "not-found")
                if member.team_role == EQR_ROLE:
                    raise rule_error(self.env, "eqr-not-assignable")
                rule = self.env["ea.audit.signoff.policy"]._ea_effective_rule(item.code, policy)
                minimum = rule["min_reviewer"] if role == "approver" else rule["min_preparer"]
                if team_rank(member.team_role) < team_rank(minimum):
                    raise rule_error(self.env, below_minimum_code(minimum))
                if policy["require_distinct_preparer_approver"]:
                    clash = (
                        user in (item.preparer_id, item.assignee_id)
                        if role == "approver"
                        else user == item.approver_id
                    )
                    if clash:
                        raise rule_error(self.env, "preparer-equals-approver")
        items.write({_ASSIGNMENT_FIELD[role]: user.id if user else False})
        for engagement in items.engagement_id:
            codes = items.filtered(lambda i: i.engagement_id == engagement).mapped("code")
            engagement._ea_log(
                "tasks_assigned" if user else "tasks_unassigned",
                ("%d task(s) assigned as %s: %s" if user else "%d task(s) unassigned as %s: %s") % (len(codes), role, ", ".join(codes[:12])),
            )
        return len(items)

    def set_due_date(self, due_date):
        """The task's own deadline (F011), whoever may hand out its work may set it. Empty goes
        back to the deadline of its phase."""
        self.ensure_one()
        Engagement = self.env["ea.audit.engagement"]
        Engagement._ea_require_write()
        item = self.sudo()
        engagement = item.engagement_id.with_env(self.env)
        engagement._ea_require_access()
        engagement._ea_assert_mutable()
        if engagement.sudo()._ea_acts_as_eqr(self.env.user):
            raise rule_error(self.env, "eqr-read-only")
        if not can_review(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "requires-senior")
        value = fields.Date.to_date(due_date) if due_date else False
        if value == item.due_date:
            return True
        item.due_date = value
        item.engagement_id._ea_log(
            "due_date_set" if value else "due_date_cleared",
            "%s due date set to %s" % (item.code, value.strftime("%d/%m/%Y")) if value else "%s due date cleared" % item.code,
        )
        return True

    def action_sign(self, requested):
        """Port of signDocument: the refusals in the same order, each its code.
        Returns the role recorded (a partner pressing R is recorded as partner)."""
        self.ensure_one()
        env = self.env
        Engagement = env["ea.audit.engagement"]
        user = env.user
        Engagement._ea_require_write()
        firm_role = user._ea_firm_role()
        item = self.sudo()
        if not item.exists():
            raise rule_error(env, "not-found")
        engagement = item.engagement_id
        engagement.with_env(env)._ea_require_access()
        if requested not in SIGNOFF_ROLES:
            raise rule_error(env, "forbidden")
        if firm_role == EQR_ROLE and requested != "eqr":
            raise rule_error(env, "forbidden")
        if requested == "reviewer" and not can_review(firm_role):
            raise rule_error(env, "requires-senior")
        if requested == "partner" and not can_partner_signoff(firm_role):
            raise rule_error(env, "requires-partner")
        role = requested

        env.cr.execute("SELECT id FROM ea_audit_file_item WHERE id = %s FOR UPDATE", [item.id])
        item.invalidate_recordset()
        if engagement._ea_is_archived():
            raise rule_error(env, "archived")
        if role == "eqr":
            if item.code != EQR_PAPER:
                raise rule_error(env, "forbidden")
            if not engagement._ea_is_appointed_eqr(user):
                raise rule_error(env, "eqr-own-paper")
        elif engagement._ea_acts_as_eqr(user):
            raise rule_error(env, "forbidden")
        if item.state == "signed" and role != "eqr":
            raise rule_error(env, "signed-locked")
        still_open = phase_still_open(item.task_phase, engagement.phase, item.code)
        if still_open:
            raise rule_error(env, still_open)

        member = engagement._ea_member(user)
        partner_required = item.code in PARTNER_GATED
        if role != "eqr":
            if not member:
                raise rule_error(env, "not-on-team-to-sign")
            if member.state != "accepted":
                raise rule_error(env, "accept-engagement-first")
            rule = env["ea.audit.signoff.policy"]._ea_effective_rule(item.code)
            partner_required = rule["partner_required"]
            partners, delegate = engagement._ea_partner_seat()
            is_engagement_partner = user in partners or (delegate and delegate == user)

            def partner_refusal():
                if not partners:
                    return "designate-engagement-partner-first"
                return None if is_engagement_partner else "not-engagement-partner"

            if role == "preparer" and team_rank(member.team_role) < team_rank(rule["min_preparer"]):
                raise rule_error(env, below_minimum_code(rule["min_preparer"]))
            # The engagement partner or delegate pressing R on a paper that needs
            # the partner's signature is recorded as the partner they are.
            if role == "reviewer" and partner_required and is_engagement_partner and can_partner_signoff(firm_role):
                role = "partner"
            if role == "reviewer" and team_rank(member.team_role) < team_rank(rule["min_reviewer"]):
                raise rule_error(env, below_minimum_code(rule["min_reviewer"]))
            if role == "reviewer" and partner_required and item.code in PARTNER_ONLY_APPROVAL:
                refusal = partner_refusal() or "partner-only"
                raise rule_error(env, refusal if can_partner_signoff(firm_role) else "partner-only")
            if role == "partner":
                refusal = partner_refusal()
                if refusal:
                    raise rule_error(env, refusal)
            missing = item._ea_tool_output_missing()
            if missing:
                raise rule_error(env, missing)

        refusal = item._ea_document_refusal(role)
        if refusal:
            raise rule_error(env, refusal)

        active = item.signoff_ids.filtered(
            lambda s: s.kind == "workpaper" and not s.voided_at and not s.invalidated_at
        )
        if role in active.mapped("role"):
            raise rule_error(env, "already-signed")
        if role not in ("preparer", "eqr") and "preparer" not in active.mapped("role"):
            raise rule_error(env, "preparer-first")
        refusal = item._ea_paper_refusal(role)
        if refusal:
            raise rule_error(env, refusal)
        if item.code == "P7.2" and role != "preparer" and not engagement._ea_ras_partner_approved():
            raise rule_error(env, "ras-not-approved")

        if role not in ("preparer", "eqr"):
            # ISA 220 (Revised) para. 29, F001: the preparer never signs as
            # reviewer or partner on their own paper. There is no exemption.
            if user in active.filtered(lambda s: s.role == "preparer").user_id:
                raise rule_error(env, "self-review")
            refusal = item._ea_review_refusal()
            if refusal:
                raise rule_error(env, refusal)

        # The whole chain ran and nothing is written: how a chip learns why it is grey.
        if env.context.get("ea_sign_dry_run"):
            return role

        env["ea.audit.signoff"].sudo().create({
            "file_item_id": item.id,
            "role": role,
            "user_id": user.id,
            "version_no": item._ea_paper_version(),
            "content_hash": item._ea_paper_content_hash(),
        })
        # The reviewer locks the paper, except where the partner still has to
        # sign; the EQR's own sign-off does not lock it.
        if role == "partner" or (role == "reviewer" and not partner_required):
            item.state = "signed"
        elif role == "reviewer":
            item.state = "reviewed"
        elif role == "preparer":
            item.state = "prepared"
        engagement._ea_log("signed_off", "%s signed by %s as %s" % (item.code, user.name, role))
        return role

    def action_sign_preparer(self):
        self.action_sign("preparer")

    def action_sign_reviewer(self):
        self.action_sign("reviewer")

    def action_sign_partner(self):
        self.action_sign("partner")

    def action_sign_eqr(self):
        self.action_sign("eqr")
