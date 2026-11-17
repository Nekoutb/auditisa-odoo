from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from .client import FRAMEWORK_SELECTION
from ..services.email_domains import email_domain_allowed, is_valid_email
from ..services.errors import rule_error, gate_label
from ..services.file_scope import (
    FACT_CODES,
    SCOPE_CURRENT,
    SCOPE_LEGACY,
    code_in_scope,
    nature_has_audit_programme,
    retired_codes,
    starts_dormant,
)
from ..services.signoff_rules import (
    EQR_ROLE,
    TEAM_LADDER,
    at_least,
    can_write,
    effective_task_rule,
    may_hold_partner_seat,
)
from ..services.work_allocation import check_row, refused
from ..services.engagement_profile import task_codes as profile_task_codes
from ..services.rollforward_plan import ROLLFORWARD_KEYS, invitations, uses_last_year_tasks
from ..services.standards_edition import STANDARDS_EDITIONS, default_standards_edition, edition_for_period

PHASE_SELECTION = [
    ("acceptance", "Acceptance"),
    ("planning", "Planning"),
    ("execution", "Execution"),
    ("conclusion", "Conclusion"),
    ("archived", "Archived"),
]
NATURE_SELECTION = [
    ("statutory_audit", "Statutory audit"),
    ("contractual_audit", "Non-statutory audit"),
    ("limited_review", "Limited review (ISRE 2400/2410)"),
    ("commissariat_apports", "Contribution auditor (commissariat aux apports)"),
    ("agreed_procedures", "Agreed-upon procedures"),
    ("other", "Other"),
]
# The two natures a new file chooses from (owner's ruling of 2026-11-15). The other values stay for
# the files opened before, whose tasks were chosen with them.
NEW_NATURE_SELECTION = [("statutory_audit", "Statutory audit"), ("contractual_audit", "Non-statutory audit")]
# How an older file's nature reads in those two words: a contribution audit is required by law.
NATURE_KIND = {"statutory_audit": "statutory", "commissariat_apports": "statutory", False: "statutory"}
REPORT_LANGUAGE_SELECTION = [("en", "English"), ("fr", "French")]
COMPLEXITY_SELECTION = [("complex", "Complex"), ("non_complex", "Non-complex"), ("very_simple", "Very simple")]
EDITION_SELECTION = [("current", "ISA in force"), ("revised_2026", "ISA revised (periods from 15 December 2026)")]

# Written only by the methods that carry their rule.
_ENGINE_FIELDS = {
    "phase", "standards_edition", "edition_reason", "archived_at", "complexity",
    # set at creation; the period and set-up screen (F073) brings their own rules
    "client_id", "fiscal_year", "period_end", "duration_months", "nature", "first_year",
    "period_start",
    # the task scope of the file: the partner applies the current one (action_rescope)
    "scope_version",
}
# The questions whose answer brings a task onto a file of the current scope (owner's table of
# 2026-11-17): field -> task.
_FACT_FIELDS = {"consultation_needed": "C1.3", "joint_auditors": "C5.9"}
YES_NO_SELECTION = [("yes", "Yes"), ("no", "No")]
_CREATOR_SEAT = {"manager": "manager", "senior": "senior", "staff": "staff"}


class Engagement(models.Model):
    _name = "ea.audit.engagement"
    _inherit = ["mail.thread"]
    _description = "Audit engagement"
    _order = "fiscal_year desc, id desc"

    @api.model
    def _ea_firm_language(self):
        """The firm's language, set at onboarding on the company's partner."""
        return "fr" if (self.env.company.sudo().partner_id.lang or "").startswith("fr") else "en"

    def _ea_report_fr(self):
        self.ensure_one()
        return self.sudo().report_language == "fr"

    def _ea_report_lang_code(self):
        return "fr_FR" if self._ea_report_fr() else "en_US"

    def _ea_pick(self, english, french):
        """The wording of a generated document, in the engagement's report language."""
        return french if self._ea_report_fr() else english

    name = fields.Char(tracking=True)
    client_id = fields.Many2one("ea.audit.client", string="Client", required=True, index=True, ondelete="restrict")
    fiscal_year = fields.Integer(required=True, tracking=True)
    period_end = fields.Date(required=True, tracking=True)
    duration_months = fields.Integer(string="Duration (months)")
    # A new file chooses Statutory or Non-statutory (contractual_audit, which leaves out the OHADA
    # statutory-only tasks). The other values stay for the files opened before, as they were.
    nature = fields.Selection(NATURE_SELECTION, tracking=True)
    nature_kind = fields.Selection(
        [("statutory", "Statutory audit"), ("non_statutory", "Non-statutory audit")],
        string="Nature of the service", compute="_compute_nature_kind",
    )
    period_start = fields.Date(string="Period from", tracking=True)
    framework = fields.Selection(FRAMEWORK_SELECTION, string="Reporting framework", tracking=True)
    planned_report_date = fields.Date(tracking=True)
    planned_agm_date = fields.Date(string="Planned general meeting", tracking=True)
    report_language = fields.Selection(
        REPORT_LANGUAGE_SELECTION, string="Report language", required=True, default=lambda self: self._ea_firm_language(),
        tracking=True, help="The language of the audit report, the letters, the legal documents and the exports of this engagement.",
    )
    first_year = fields.Boolean(string="First-year audit")
    scope_version = fields.Integer(
        string="Task scope", readonly=True, copy=False,
        help="1 (or empty): the tasks chosen when the file was opened, before 2026-11-17. 2: the current "
             "scope, where facts decide whether a task applies and the complexity how deep it goes.",
    )
    consultation_needed = fields.Selection(
        YES_NO_SELECTION, string="Was a consultation needed?", tracking=True, copy=False,
        help="Compulsory before the report. Yes brings C1.3 (consultation record) onto the file.",
    )
    joint_auditors = fields.Selection(
        YES_NO_SELECTION, string="Are there joint auditors?", tracking=True, copy=False,
        help="Yes brings C5.9 (joint auditor coordination file) onto the file.",
    )
    complexity = fields.Selection(COMPLEXITY_SELECTION, default="complex", tracking=True)
    phase = fields.Selection(PHASE_SELECTION, required=True, default="acceptance", index=True, tracking=True)
    standards_edition = fields.Selection(EDITION_SELECTION, required=True, default="current", tracking=True)
    edition_reason = fields.Char()
    archived_at = fields.Datetime(copy=False)
    team_member_ids = fields.One2many("ea.audit.team.member", "engagement_id", string="Team")
    file_item_ids = fields.One2many("ea.audit.file.item", "engagement_id", string="File index")
    engagement_partner_id = fields.Many2one(
        "res.users", string="Engagement partner", compute="_compute_engagement_partner", compute_sudo=True,
        search="_search_engagement_partner",
    )
    partner_delegate_id = fields.Many2one(
        "res.users", string="Partner delegate", ondelete="set null", tracking=True, index="btree_not_null",
    )
    gate_summary = fields.Text(string="Gates of this phase", compute="_compute_gate_summary")
    profile_ids = fields.One2many("ea.audit.engagement.profile", "engagement_id", string="Profile")
    profile_state = fields.Selection(
        [("none", "Not started"), ("draft", "Not finished"), ("concluded", "Concluded")],
        string="Profile questionnaire", compute="_compute_profile_state",
    )
    profile_pending = fields.Boolean(string="Profile not finished", compute="_compute_profile_state")

    @api.depends("nature")
    def _compute_nature_kind(self):
        for engagement in self:
            engagement.nature_kind = NATURE_KIND.get(engagement.nature, "non_statutory")

    @api.depends("profile_ids.state", "file_item_ids", "file_item_ids.conditional")
    def _compute_profile_state(self):
        """A file opened before the questionnaire existed has its tasks and is never held up. The
        hidden tasks a roll-forward adds to hold last year's evidence are not tasks yet."""
        for engagement in self:
            as_root = engagement.sudo()
            profile = as_root.profile_ids[:1]
            engagement.profile_state = profile.state or "none"
            engagement.profile_pending = (
                profile.state != "concluded" and not as_root.file_item_ids.filtered(lambda i: not i.conditional)
                and not as_root.archived_at and as_root.phase != "archived"
            )

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

    def _search_engagement_partner(self, operator, value):
        """F076: the partner's portfolio. Same seat as the compute, in the files the reader can open."""
        return [("team_member_ids", "any", [("team_role", "=", "partner"), ("state", "!=", "declined"), ("user_id", operator, value)])]

    def init(self):
        # F073: free text from before the list; the same value, so the export and the letters read the same.
        self.env.cr.execute("UPDATE ea_audit_engagement SET framework = 'SYSCOHADA' WHERE framework IS DISTINCT FROM 'SYSCOHADA'")

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
            # the firm's audit log (F027), which outlives the file and does not depend on the team
            self.env["ea.audit.activity"]._ea_record(engagement, action, summary)

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
            # every new file gets the current scope; only a migration or a test of an older file
            # (superuser) states another one
            if not self.env.su or not vals.get("scope_version"):
                vals["scope_version"] = SCOPE_CURRENT
            partner_id = vals.pop("engagement_partner_id", False)
            if not partner_id:
                raise rule_error(self.env, "engagement-partner-required")
            partner = self.env["res.users"].browse(partner_id)
            # the seat is a firm partner's or firm administrator's (F003)
            if not partner.exists() or not may_hold_partner_seat(partner._ea_firm_role()):
                raise rule_error(self.env, "partner-role-requires-partner-rank")
            partners.append(partner)
            if vals.get("period_start") and vals.get("period_end"):
                start, end = fields.Date.to_date(vals["period_start"]), fields.Date.to_date(vals["period_end"])
                if start > end:
                    raise rule_error(self.env, "period-order")
                if not vals.get("duration_months"):
                    vals["duration_months"] = max(1, round(((end - start).days + 1) / 30.44))
            if vals.get("period_end") and (not self.env.su or "standards_edition" not in vals):
                # F045: the edition follows the first day of the period
                if vals.get("period_start"):
                    vals["standards_edition"] = default_standards_edition(fields.Date.to_date(vals["period_start"]))
                else:
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

    def _ea_scope_version(self):
        self.ensure_one()
        return self.sudo().scope_version or SCOPE_LEGACY

    def _ea_scoped_templates(self, active_only=False, complexity=None):
        """The tasks of the file's scope at its complexity (or ``complexity``); with ``active_only``,
        without those that wait for their fact."""
        self.ensure_one()
        form = self.client_id.legal_form
        level = complexity or self.complexity
        scope = self._ea_scope_version()
        return self.env["ea.audit.task.template"].sudo().search([]).filtered(
            lambda t: code_in_scope(t.code, t.tier, t.conditional, level, form, self.nature, scope)
            and not (active_only and starts_dormant(t.code, t.conditional, scope))
        )

    def _ea_instantiate_file_index(self):
        """Inserts only the codes missing, so a re-assessment adds and never removes."""
        self.ensure_one()
        have = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id)]).template_id
        scope = self._ea_scope_version()
        self.env["ea.audit.file.item"].sudo().create([
            {"engagement_id": self.id, "template_id": t.id, "conditional": starts_dormant(t.code, t.conditional, scope)}
            for t in self._ea_scoped_templates() - have
        ])
        self._ea_apply_scope_facts()

    def _ea_ensure_task(self, code):
        """ensureTaskTx: put a task on the file when a trigger makes it apply, or
        activate it. Idempotent; an archived file is left alone, and a task merged into
        another one (file_scope.retired_codes) never comes back."""
        self.ensure_one()
        template = self.env["ea.audit.task.template"].sudo().search([("code", "=", code)], limit=1)
        if not template or self._ea_is_archived() or code in retired_codes(self._ea_scope_version()):
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

    def _ea_task_holds_work(self, item):
        """Extension point of ea_audit_papers: answers, evidence or a conclusion on the task."""
        return bool(item.signoff_ids)

    def _ea_set_task_active(self, code, active):
        """A conditional task comes onto the file when its trigger answers yes, and leaves it
        again when the answer changes, unless it already holds work."""
        self.ensure_one()
        if active:
            self._ea_ensure_task(code)
            return
        item = self.env["ea.audit.file.item"].sudo().search(
            [("engagement_id", "=", self.id), ("code", "=", code), ("conditional", "=", False)], limit=1,
        )
        if (
            item and not self._ea_task_holds_work(item) and code not in self._ea_profile_task_codes()
            and not self._ea_required_by_scope(code)
        ):
            item.conditional = True

    def _ea_required_by_scope(self, code):
        """A task the current scope puts on every file of this kind (P4.3 since 2026-11-17): an answer
        elsewhere does not take it off."""
        self.ensure_one()
        if self._ea_scope_version() < SCOPE_CURRENT:
            return False
        return code in self._ea_scoped_templates(active_only=True).mapped("code")

    # ------------------------------------------------------------------
    # Facts decide whether a task applies (owner's table of 2026-11-17)
    # ------------------------------------------------------------------

    def _ea_fact_codes(self):
        """{code: why} of the "if applicable" tasks whose fact exists on this file. The later addons
        add theirs: ea_audit_papers (S6.1 answers, the P1.5 decision, going-concern facts,
        non-compliance), ea_audit_tools (reliance on controls), ea_audit_legal (alert procedure,
        criminal facts, joint auditor file)."""
        self.ensure_one()
        root = self.sudo()
        facts = {}
        if root.first_year:
            facts["P1.2"] = "first-year audit"
        for field, code in _FACT_FIELDS.items():
            if root[field] == "yes":
                facts[code] = "%s Yes" % self._fields[field].string
        for code in sorted(self._ea_profile_task_codes() & FACT_CODES):
            facts.setdefault(code, "profile questionnaire")
        return facts

    def _ea_apply_scope_facts(self):
        """Brings onto each file of the current scope the tasks whose fact now exists. Adds only, and
        only tasks of the file's scope; each addition is written to the activity trail. A file of the
        older scope is left as it is until its partner applies the current one."""
        for engagement in self:
            root = engagement.sudo()
            if root._ea_scope_version() < SCOPE_CURRENT or root._ea_is_archived() or not root.complexity:
                continue
            facts = root._ea_fact_codes()
            if not facts:
                continue
            scoped = set(root._ea_scoped_templates().mapped("code"))
            added = [code for code in sorted(facts) if code in scoped and root._ea_ensure_task(code)]
            if added:
                engagement._ea_log("tasks_from_facts", "Tasks brought onto the file by their facts: %s" % ", ".join(added))
        return True

    def _ea_answer_facts(self, answered):
        """A question of _FACT_FIELDS answered: Yes brings its task, No takes it off again unless it
        holds work (as the S6.1 questions do). The task follows on a file of the current scope only."""
        for engagement in self:
            root = engagement.sudo()
            for field in sorted(answered):
                value = root[field]
                engagement._ea_log("scope_fact", "Scope question %s answered %s" % (field, value or "blank"))
                if root._ea_scope_version() >= SCOPE_CURRENT and not root._ea_is_archived() and value == "no":
                    root._ea_set_task_active(_FACT_FIELDS[field], False)
            root._ea_apply_scope_facts()

    def action_rescope(self):
        """The partner applies the current task scope to a file opened before it (owner's ruling of
        2026-11-17: no task comes or goes on a live file by itself). Adds the tasks the scope brings;
        takes off, as hidden tasks, only those that hold no work and that the scope no longer asks for
        or whose fact does not exist; keeps every task holding work. Logged in the activity trail."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        self._ea_assert_mutable()
        if not at_least(self.env.user._ea_firm_role(), "partner") or self._ea_acts_as_eqr(self.env.user):
            raise rule_error(self.env, "forbidden")
        root = self.sudo()
        before = root._ea_scope_version()
        root.write({"scope_version": SCOPE_CURRENT})
        if not root.complexity:
            self._ea_log("scope_applied", "Current task scope applied by %s, no task yet: the profile decides" % self.env.user.name)
            return True
        Item = self.env["ea.audit.file.item"].sudo()
        items = Item.search([("engagement_id", "=", root.id)])
        scope = {t: starts_dormant(t.code, t.conditional, SCOPE_CURRENT) for t in root._ea_scoped_templates()}
        keep = set(root._ea_fact_codes()) | root._ea_profile_task_codes()
        added, hidden, kept = [], [], []
        for item in items.filtered(lambda i: not i.conditional):
            template = item.template_id
            if template in scope and not (scope[template] and item.code not in keep):
                continue
            if root._ea_task_holds_work(item):
                kept.append(item.code)
            else:
                item.conditional = True
                hidden.append(item.code)
        by_template = {item.template_id: item for item in items}
        for template, dormant in scope.items():
            item = by_template.get(template)
            if not item:
                Item.create({"engagement_id": root.id, "template_id": template.id, "conditional": dormant})
                if not dormant:
                    added.append(template.code)
            elif item.conditional and not dormant and item.code not in hidden:
                item.conditional = False
                added.append(template.code)
        self._ea_log("scope_applied", (
            "Current task scope applied by %s (scope %s to %s). Added: %s. Taken off, holding no work: %s. "
            "Kept, holding work: %s"
        ) % (
            self.env.user.name, before, SCOPE_CURRENT, ", ".join(sorted(added)) or "-", ", ".join(sorted(hidden)) or "-",
            ", ".join(sorted(kept)) or "-",
        ))
        root._ea_apply_scope_facts()
        return True

    # ------------------------------------------------------------------
    # The profile questionnaire (owner's rulings of 2026-11-15)
    # ------------------------------------------------------------------

    def _ea_profile(self):
        self.ensure_one()
        return self.env["ea.audit.engagement.profile"].sudo().search([("engagement_id", "=", self.id)], limit=1)

    def _ea_profile_task_codes(self):
        """The tasks a concluded profile switched on: a later "no" elsewhere does not switch them off."""
        profile = self._ea_profile()
        return profile_task_codes(profile._ea_answers()) if profile.state == "concluded" else set()

    def action_open_profile(self):
        """The questionnaire. An older file gets an empty one, which holds nothing up."""
        self.ensure_one()
        self._ea_require_access()
        profile = self._ea_profile()
        if not profile:
            self._ea_assert_mutable()
            profile = self.env["ea.audit.engagement.profile"].sudo().create({"engagement_id": self.id})
        # The screen of the owner's mock-up of 2026-11-15: one section at a time, a live level
        # panel. res_model and res_id say which record it is; active_id survives a reload.
        return {
            "type": "ir.actions.client", "tag": "ea_audit_core.profile", "target": "current",
            "res_model": "ea.audit.engagement.profile", "res_id": profile.id,
            "params": {"profile_id": profile.id},
            "context": {"active_id": profile.id, "ea_engagement_id": self.id},
            "name": self.env._("Profile questionnaire"),
        }

    def _ea_open_engagement_screen(self):
        """Where "Save for later" goes back to. ea_audit_ui opens the engagement dashboard instead."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "views": [(False, "form")], "target": "current",
        }

    def _ea_open_task_list(self):
        """The tasks of the file. ea_audit_ui opens its task list instead."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "ea.audit.file.item", "name": self.env._("Tasks"),
            "view_mode": "list,form", "views": [(False, "list"), (False, "form")], "target": "current",
            "domain": [("engagement_id", "=", self.id), ("conditional", "=", False)],
        }

    def _ea_open_profile_or_notify(self):
        """Right after creation: the questionnaire, when the creator is on the team."""
        self.ensure_one()
        if self._ea_member(self.env.user).state == "accepted":
            return self.action_open_profile()
        return self._ea_open_or_notify()

    def _ea_carry_profile_forward(self, source):
        """Next year's file starts from last year's answers, the client now recurring. It is not
        concluded: the team reads the answers again and concludes, which brings the tasks."""
        self.ensure_one()
        previous = source._ea_profile()
        if not previous:
            return
        values = previous._ea_answers()
        values.update(q20_first_year="no")
        self.env["ea.audit.engagement.profile"].sudo().create({"engagement_id": self.id, **values})

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

    def rollforward(self, new_year, options=None):
        """Port of rollforward: a new file for a later year, carrying the prior
        year's accepted partner while they still hold partner rank.

        With options (the "Roll forward" wizard, owner's mock-up of 2026-11-16) the caller says
        what to carry, the year end, the partner, the team and the approach: see
        _ea_rollforward_with."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        source = self.sudo()
        if new_year <= source.fiscal_year:
            raise rule_error(self.env, "invalid-year")
        if options is not None:
            return self._ea_rollforward_with(new_year, options)
        partners, _delegate = source._ea_partner_seat()
        partners = partners.filtered(lambda u: may_hold_partner_seat(u._ea_firm_role()))
        if not partners:
            raise rule_error(self.env, "engagement-partner-required")
        shift = relativedelta(years=new_year - source.fiscal_year)
        vals = {
            "client_id": source.client_id.id,
            "fiscal_year": new_year,
            "period_end": source.period_end + shift,
            "engagement_partner_id": partners[0].id,
        }
        concluded = source._ea_profile().state == "concluded"
        if concluded:
            # A file opened with the questionnaire: next year's tasks come from its conclusion.
            vals.update(complexity=False, nature=source.nature, report_language=source.report_language)
            if source.period_start:
                vals["period_start"] = source.period_start + shift
        target = self.create(vals)
        if concluded:
            target.sudo()._ea_carry_profile_forward(source)
        target.sudo()._ea_carry_forward_from(source)
        return target

    # ------------------------------------------------------------------
    # Roll forward with the wizard (owner's mock-up and rulings of 2026-11-16)
    # ------------------------------------------------------------------

    def _ea_may_roll_forward(self):
        """From a closed file only: archived, or its report issued."""
        self.ensure_one()
        root = self.sudo()
        return root._ea_is_archived() or bool("report_date" in root._fields and root.report_date)

    def action_rollforward_next_year(self):
        """The wizard: what to carry, the year, the team and the approach."""
        self.ensure_one()
        self._ea_require_team_manager()
        if not self._ea_may_roll_forward():
            raise rule_error(self.env, "rollforward-not-closed")
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Roll forward to %(year)s", year=self.sudo().fiscal_year + 1),
            "res_model": "ea.audit.rollforward.wizard",
            "view_mode": "form", "views": [(False, "form")], "target": "new",
            "context": {"default_source_id": self.id},
        }

    def _ea_rf_task(self, code):
        """The task of the new file that receives what was on the same task last year. A task not
        on the file (yet) is added hidden: the questionnaire's conclusion brings it in."""
        self.ensure_one()
        Item = self.env["ea.audit.file.item"].sudo()
        item = Item.search([("engagement_id", "=", self.id), ("code", "=", code)], limit=1)
        if item:
            return item
        template = self.env["ea.audit.task.template"].sudo().search([("code", "=", code)], limit=1)
        if not template:
            return Item
        return Item.create({"engagement_id": self.id, "template_id": template.id, "conditional": True})

    def _ea_rollforward_carry(self, source, carry, mapping):
        """ea_audit_tools: the records carried as drafts (SCOTs, risks, procedures, ...).
        mapping[(model, source id)] = new record, for the evidence links."""

    def _ea_rollforward_evidence(self, source, carry, mapping):
        """ea_audit_papers: the evidence copied to the new file. Returns how many files."""
        return 0

    def _ea_rollforward_with(self, new_year, options):
        """The new file, as the wizard asked. The source file is only read: an archived file
        refuses any row change. Nothing is concluded or signed in the new file, and every seat,
        the partner's and the caller's included, waits for its holder to accept the invitation,
        which is where each member confirms independence for the new year."""
        self.ensure_one()
        self._ea_require_team_manager()
        source = self.sudo()
        carry = set(options.get("carry") or ())
        Users = self.env["res.users"]
        partner = Users.browse(options["partner_id"]).exists() if options.get("partner_id") else Users
        if not partner:
            partners, _delegate = source._ea_partner_seat()
            partner = partners.filtered(lambda u: may_hold_partner_seat(u._ea_firm_role()))[:1]
        if not partner:
            raise rule_error(self.env, "engagement-partner-required")
        shift = relativedelta(years=new_year - source.fiscal_year)
        period_end = fields.Date.to_date(options.get("period_end")) or source.period_end + shift
        if period_end <= source.period_end:
            raise rule_error(self.env, "invalid-year")
        same = uses_last_year_tasks(carry, options.get("approach"))
        name = source.name and source.name.replace(str(source.fiscal_year), str(new_year))
        vals = {
            "client_id": source.client_id.id,
            "name": name or False,
            "fiscal_year": new_year,
            "period_end": period_end,
            "engagement_partner_id": partner.id,
            "nature": source.nature,
            "report_language": source.report_language,
            # Same as last year: last year's level and tasks. Otherwise the questionnaire decides.
            "complexity": (source.complexity or "complex") if same else False,
        }
        if source.period_start:
            months = source.duration_months or 12
            vals["period_start"] = period_end - relativedelta(months=months) + relativedelta(days=1)
        target = self.create(vals)
        as_target = target.sudo()
        if "scope" in carry:
            as_target._ea_carry_profile_forward(source)
        if same:
            for code in source.file_item_ids.filtered(lambda i: not i.conditional).mapped("code"):
                as_target._ea_ensure_task(code)
        as_target._ea_carry_forward_from(source)
        mapping = {}
        as_target._ea_rollforward_carry(source, carry, mapping)
        evidence = as_target._ea_rollforward_evidence(source, carry, mapping)
        target._ea_rollforward_team(partner, options.get("members") or [])
        target._ea_log("rolled_forward", "Rolled forward from the %d file by %s" % (source.fiscal_year, self.env.user.name))
        if carry:
            target._ea_log("rolled_forward", "Carried forward from the %d file: %s" % (
                source.fiscal_year, ", ".join(key for key in ROLLFORWARD_KEYS if key in carry),
            ))
        if evidence:
            target._ea_log("evidence_carried", "%d evidence file(s) carried forward from %d, to review before relying on them" % (
                evidence, source.fiscal_year,
            ))
        return target

    def _ea_rollforward_team(self, partner, members):
        """The team of the new file: the invitations go through the usual invitation, by the
        caller when they sit on the new team, else by its engagement partner. Then every seat
        waits for its holder's acceptance."""
        self.ensure_one()
        inviter = self if self._ea_member(self.env.user).state == "accepted" else self.with_user(partner)
        seated = self.env["ea.audit.team.member"].sudo().search([("engagement_id", "=", self.id)]).user_id.mapped("login")
        for line in invitations([dict(line, invite=True) for line in members], seated):
            inviter.invite_team_member(
                line["email"], line.get("role") or "staff", line.get("name"), bool(line.get("eqr_declaration")),
            )
        now = fields.Datetime.now()
        self.env["ea.audit.team.member"].sudo().search([
            ("engagement_id", "=", self.id), ("state", "=", "accepted"),
        ]).write({"state": "invited", "invited_at": now, "responded_at": False})

    def _ea_open_or_notify(self):
        """Open the file when the caller is on its team. A partner who opened a
        file for another partner is not, and cannot open it (F008)."""
        self.ensure_one()
        if self._ea_member(self.env.user).state == "accepted":
            return {
                "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current",
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
        answered = set(vals or {}) & set(_FACT_FIELDS)
        result = self._ea_write(vals)
        if answered:
            self._ea_answer_facts(answered)
        return result

    def _ea_write(self, vals):
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
        """Port of addTeamMemberByEmail, without its account creation (owner, 2026-11-17): only
        the firm administrator adds people to the firm, on the Users screen. The domain rule comes
        first; then the address must be an active colleague already in the firm.
        ``display_name`` stays for the callers' signature and is no longer used."""
        self.ensure_one()
        if team_role not in TEAM_LADDER and team_role != EQR_ROLE:
            raise rule_error(self.env, "invalid-team-role")
        self._ea_require_team_manager(team_role)
        self._ea_assert_mutable()
        email = (email or "").strip().lower()
        if not is_valid_email(email):
            raise rule_error(self.env, "invalid-email")
        self._ea_assert_member_domain(email)
        user = self._ea_firm_colleague(email)
        if not user:
            raise rule_error(self.env, "not-in-firm-yet")
        if team_role == "partner" and not may_hold_partner_seat(user._ea_firm_role()):
            raise rule_error(self.env, "partner-role-requires-partner-rank")
        member = self._ea_seat_invitation(user, team_role, eqr_declaration)
        self._ea_send_team_invitation(member, False)
        return member

    def _ea_firm_colleague(self, email):
        """The active internal user of the firm signing in with ``email``, or an empty
        recordset: a portal contact, an archived account or a stranger is not one."""
        Users = self.env["res.users"].sudo()
        user = Users.search(["|", ("login", "=ilike", email), ("email", "=ilike", email)], limit=1)
        if not user or user.share or not user._ea_firm_role():
            return Users.browse()
        return user.with_env(self.env)

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

    # ------------------------------------------------------------------
    # Work allocation (owner's mock-up of 2026-11-18)
    # ------------------------------------------------------------------

    def _ea_allocation_partner(self):
        """The engagement partner, as the dashboard names them: the accepted seat, else the invited one."""
        self.ensure_one()
        seats = self.env["ea.audit.team.member"].sudo().search([
            ("engagement_id", "=", self.id), ("team_role", "=", "partner"), ("state", "!=", "declined"),
        ])
        return (seats.filtered(lambda m: m.state == "accepted") or seats)[:1].user_id

    def _ea_allocation_rules(self, items):
        """{task id: its rule from the sign-off policy}, the policy and the firm's rules read once."""
        policy = self.env["ea.audit.signoff.policy"].sudo()._ea_policy()
        own = self.env["ea.audit.signoff.task.rule"].sudo()._ea_rules(set(items.mapped("code")))
        return {item.id: effective_task_rule(policy, own, item.code) for item in items}

    def _ea_sync_partner_approval(self, items=None, log=True):
        """Partner approval goes to the engagement partner by itself, on every task whose rule asks
        for it, and on no other. Runs when tasks come onto the file, when the partner seat changes
        hands and when the allocation is saved. An archived file is left as it is."""
        Item = self.env["ea.audit.file.item"].sudo()
        for engagement in self.sudo():
            if engagement._ea_is_archived():
                continue
            own = Item.search([("engagement_id", "=", engagement.id)]) if items is None else (
                items.sudo().filtered(lambda i: i.engagement_id == engagement)
            )
            if not own:
                continue
            partner = engagement._ea_allocation_partner()
            rules = engagement._ea_allocation_rules(own)
            targets = {}
            for item in own:
                target = partner if rules[item.id]["partner_required"] else self.env["res.users"]
                if item.partner_approver_id != target:
                    targets.setdefault(target, Item)
                    targets[target] |= item
            for target, group in targets.items():
                group.write({"partner_approver_id": target.id or False})
                if not log:
                    continue
                codes = ", ".join(group.mapped("code")[:12])
                if target:
                    engagement._ea_log(
                        "partner_approval_assigned",
                        "%d task(s) for partner approval assigned to %s: %s" % (len(group), target.name, codes),
                    )
                elif partner:
                    # without a partner seat the change of seat is itself on the trail
                    engagement._ea_log(
                        "partner_approval_removed", "%d task(s) no longer need partner approval: %s" % (len(group), codes),
                    )
        return True

    def ea_allocate_tasks(self, changes):
        """Saves the Work allocation screen. ``changes`` holds one dict per task changed: its id, and
        preparer_id and/or approver_id (a user id, or False for an empty box). Only accepted members
        of the team, the quality reviewer apart. A reviewer who is also the preparer refuses the whole
        save (F001); a person below the task's minimum is saved, and the answer lists the warnings
        (owner's ruling of 2026-11-18: signing still follows the sign-off policy). Each change goes
        through the assignment of the tasks screen: the same notifications, the same trail lines.
        Signatures already given are never touched."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_team_manager()
        self._ea_assert_mutable()
        if self._ea_acts_as_eqr(self.env.user):
            raise rule_error(self.env, "eqr-read-only")
        Item = self.env["ea.audit.file.item"].sudo()
        wanted = {}
        for change in changes or []:
            item = Item.browse(int(change.get("id") or 0)).exists()
            if not item or item.engagement_id != self.sudo() or item.conditional:
                raise rule_error(self.env, "not-found")
            wanted[item.id] = {
                field: int(change[field]) if change[field] else False
                for field in ("preparer_id", "approver_id") if field in change
            }
        items = Item.browse(list(wanted))
        members = self.sudo().team_member_ids.filtered(lambda m: m.state == "accepted" and m.team_role != EQR_ROLE)
        roles = {member.user_id.id: member.team_role for member in members}
        if any(uid and uid not in roles for values in wanted.values() for uid in values.values()):
            raise rule_error(self.env, "not-found")
        rules = self._ea_allocation_rules(items)
        rows = []
        for item in items:
            values = wanted[item.id]
            rows.append({
                "id": item.id,
                "min_preparer": rules[item.id]["min_preparer"],
                "min_reviewer": rules[item.id]["min_reviewer"],
                "preparer": values.get("preparer_id", item.preparer_id.id) or None,
                "reviewer": values.get("approver_id", item.approver_id.id) or None,
                "assignee": item.assignee_id.id or None,
            })
        if refused(rows, roles):
            raise rule_error(self.env, "preparer-equals-approver")
        # the reviewer who becomes the preparer leaves the reviewer box first: no step sees one person twice
        handover = items.filtered(
            lambda i: wanted[i.id].get("preparer_id") and wanted[i.id]["preparer_id"] == i.approver_id.id
        )
        if handover:
            handover.with_env(self.env)._ea_assign_tasks(False, "approver")
        for field, role in (("preparer_id", "preparer"), ("approver_id", "approver")):
            targets = {}
            for item in items:
                if field in wanted[item.id] and (item[field].id or False) != wanted[item.id][field]:
                    targets.setdefault(wanted[item.id][field], []).append(item.id)
            for uid, ids in targets.items():
                Item.browse(ids).with_env(self.env)._ea_assign_tasks(uid, role, below_minimum_warns=True)
        self._ea_sync_partner_approval()
        warnings = [
            {"id": row["id"], "box": box, "role": role}
            for row in rows for box, _kind, _blocking, role in check_row(row, roles)
        ]
        return {"saved": len(items), "warnings": warnings}

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
