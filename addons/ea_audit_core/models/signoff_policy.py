from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services.email_domains import InvalidDomainError, parse_domain_list
from ..services.errors import rule_error
from ..services.signoff_matrix import MatrixFileError, build_workbook, normalise, parse_workbook
from ..services.signoff_rules import (
    DEFAULT_MIN_REVIEWER,
    TEAM_LADDER,
    at_least,
    can_write,
    default_policy,
    default_require_partner_on,
    effective_task_rule,
    is_ladder_role,
)
from ..services.work_allocation import ROLE_WORDS, rule_text

LADDER_SELECTION = [
    ("staff", "Staff"),
    ("senior", "Senior"),
    ("manager", "Manager"),
    ("senior_manager", "Senior manager"),
    ("director", "Director"),
    ("partner", "Partner"),
]


def _require_policy_editor(env):
    """Firm administrators and partners set the firm's sign-off rules."""
    role = env.user._ea_firm_role()
    if not can_write(role):
        raise rule_error(env, "read-only-role")
    if not at_least(role, "partner"):
        raise rule_error(env, "signoff-policy-partner-only")


class SignoffPolicy(models.Model):
    """The firm's sign-off policy. One row at most (firm = database); no row
    means the default matrix. allow_sole_practitioner is stored false and read
    by no sign-off path: self-review is refused in every circumstance (F001)."""

    _name = "ea.audit.signoff.policy"
    _description = "Firm sign-off policy"

    singleton = fields.Boolean(default=True, required=True, readonly=True)
    min_reviewer_role = fields.Selection(LADDER_SELECTION, string="Minimum Reviewer Role", required=True, default=DEFAULT_MIN_REVIEWER)
    require_partner_on_ids = fields.Many2many(
        "ea.audit.task.template",
        string="Partner sign-off required on",
        default=lambda self: self._default_require_partner_on(),
    )
    allow_sole_practitioner = fields.Boolean(readonly=True, default=False)
    require_distinct_preparer_approver = fields.Boolean(default=True)
    allowed_email_domains = fields.Text(
        compute="_compute_allowed_email_domains",
        inverse="_inverse_allowed_email_domains",
        help="One per line. Kept by the firm administrator. Empty means no restriction.",
    )

    firm_language = fields.Selection(
        [("fr_FR", "French"), ("en_US", "English")],
        string="Language of the firm",
        compute="_compute_firm_language",
        inverse="_inverse_firm_language",
        help="New accounts take this language. Each person can then choose their own. Kept by the firm administrator.",
    )

    _singleton_uniq = models.Constraint("UNIQUE(singleton)", "The firm has one sign-off policy.")

    @api.depends_context("lang")
    def _compute_display_name(self):
        for policy in self:
            policy.display_name = self.env._("Sign-off policy")

    def _compute_firm_language(self):
        lang = self.env.company.sudo().partner_id.lang
        for policy in self:
            policy.firm_language = "fr_FR" if (lang or "").startswith("fr") else "en_US"

    def _inverse_firm_language(self):
        for policy in self:
            if policy.firm_language and policy.firm_language != self.env.company.sudo().partner_id.lang:
                self.env["res.company"].ea_set_firm_language(policy.firm_language)

    def _ea_snapshot(self):
        self.ensure_one()
        return "\n".join((
            "%s: %s" % ("min_reviewer_role", self.min_reviewer_role),
            "%s: %s" % ("require_distinct_preparer_approver", self.require_distinct_preparer_approver),
            "%s: %s" % ("require_partner_on", ", ".join(sorted(self.require_partner_on_ids.mapped("code")))),
        ))

    @api.model
    def _default_require_partner_on(self):
        templates = self.env["ea.audit.task.template"].sudo().search([])
        codes = set(default_require_partner_on(templates.mapped("code")))
        return templates.filtered(lambda t: t.code in codes).ids

    def _compute_allowed_email_domains(self):
        value = "\n".join(self.env["res.company"]._ea_allowed_domains())
        for policy in self:
            policy.allowed_email_domains = value

    def _inverse_allowed_email_domains(self):
        company = self.env["res.company"]
        for policy in self:
            try:
                wanted = parse_domain_list(policy.allowed_email_domains or "")
            except InvalidDomainError:
                raise rule_error(self.env, "invalid-email-domain") from None
            if wanted != sorted(company._ea_allowed_domains()):
                company.ea_set_allowed_domains(policy.allowed_email_domains or "")
        self.invalidate_recordset(["allowed_email_domains"])

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            _require_policy_editor(self.env)
        for vals in vals_list:
            vals["allow_sole_practitioner"] = False
        policies = super().create(vals_list)
        for policy in policies:
            self.env["ea.audit.activity"]._ea_record(
                False, "signoff_policy_updated", "Firm sign-off policy updated", after=policy._ea_snapshot(),
            )
        return policies

    def write(self, vals):
        if not self.env.su:
            _require_policy_editor(self.env)
        if "allow_sole_practitioner" in vals:
            vals = dict(vals, allow_sole_practitioner=False)
        before = {policy.id: policy._ea_snapshot() for policy in self}
        result = super().write(vals)
        for policy in self:
            after = policy._ea_snapshot()
            if after != before[policy.id]:
                self.env["ea.audit.activity"]._ea_record(
                    False, "signoff_policy_updated", "Firm sign-off policy updated", before=before[policy.id], after=after,
                )
        return result

    def unlink(self):
        if not self.env.su:
            _require_policy_editor(self.env)
        return super().unlink()

    @api.model
    def action_open_firm_policy(self):
        """Open the firm's row, or a new form holding the default matrix."""
        policy = self.search([], limit=1)
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Sign-off policy"),
            "res_model": self._name,
            "view_mode": "form", "views": [(False, "form")],
            "res_id": policy.id or False,
            "target": "current",
        }

    @api.model
    def _ea_policy(self):
        """The firm's policy as the rules engine reads it (getPolicyTx)."""
        templates = self.env["ea.audit.task.template"].sudo().search([])
        row = self.sudo().search([], limit=1)
        if not row:
            return default_policy(templates.mapped("code"))
        return {
            "min_reviewer_role": row.min_reviewer_role,
            "require_partner_on": row.require_partner_on_ids.mapped("code"),
            "allow_sole_practitioner": row.allow_sole_practitioner,
            "require_distinct_preparer_approver": row.require_distinct_preparer_approver,
            "stored": True,
        }

    @api.model
    def _ea_effective_rule(self, code, policy=None):
        """What applies to one task (effectiveRuleTx)."""
        policy = policy or self._ea_policy()
        rules = self.env["ea.audit.signoff.task.rule"]._ea_rules([code])
        return effective_task_rule(policy, rules, code)

    @api.model
    def _ea_rule_words(self, rule):
        """A task's rule in plain words, in the reader's language (work allocation)."""
        return rule_text(rule, lambda source: self.env._(source))

    @api.model
    def _ea_sentence_role_words(self):
        """Each rung of the ladder as it reads inside a sentence: "a senior or above"."""
        return {role: self.env._(word) for role, word in ROLE_WORDS.items()}

    @api.model
    def save_policy(self, min_reviewer_role, require_partner_on, require_distinct_preparer_approver):
        """Port of savePolicy. The sole-practitioner flag is not an argument."""
        _require_policy_editor(self.env)
        if not is_ladder_role(min_reviewer_role):
            raise rule_error(self.env, "invalid-team-role")
        codes = sorted({c.strip() for c in require_partner_on if c and c.strip()})
        templates = self.env["ea.audit.task.template"].sudo().search([("code", "in", codes)])
        if len(templates) != len(codes):
            raise rule_error(self.env, "unknown-task-code")
        vals = {
            "min_reviewer_role": min_reviewer_role,
            "require_partner_on_ids": [(6, 0, templates.ids)],
            "require_distinct_preparer_approver": require_distinct_preparer_approver,
        }
        row = self.sudo().search([], limit=1)
        if row:
            row.write(vals)
        else:
            self.sudo().create(vals)
        return True


class SignoffTaskRule(models.Model):
    """The firm's per-task override. A "default" column reads through to the
    matrix; a "no" on partner_required is how a firm lifts a default signature."""

    _name = "ea.audit.signoff.task.rule"
    _description = "Firm sign-off rule for one task"
    _order = "template_id"
    _rec_name = "template_id"

    template_id = fields.Many2one(
        "ea.audit.task.template", string="Task", required=True, index=True, ondelete="cascade",
    )
    code = fields.Char(related="template_id.code", store=True, index=True)
    min_preparer = fields.Selection(LADDER_SELECTION, string="Minimum preparer")
    min_reviewer = fields.Selection(LADDER_SELECTION, string="Minimum reviewer")
    partner_required = fields.Selection(
        [("default", "Firm default"), ("yes", "Yes"), ("no", "No")], required=True, default="default",
    )

    _template_uniq = models.Constraint("UNIQUE(template_id)", "This task already has a rule.")

    def _ea_snapshot(self):
        self.ensure_one()
        return "min_preparer: %s\nmin_reviewer: %s\npartner_required: %s" % (
            self.min_preparer or "default", self.min_reviewer or "default", self.partner_required,
        )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            _require_policy_editor(self.env)
        rules = super().create(vals_list)
        for rule in rules:
            self.env["ea.audit.activity"]._ea_record(
                False, "signoff_rule_added", "Sign-off rule of %s added" % rule.code, code=rule.code, after=rule._ea_snapshot(),
            )
        return rules

    def write(self, vals):
        if not self.env.su:
            _require_policy_editor(self.env)
        before = {rule.id: rule._ea_snapshot() for rule in self}
        result = super().write(vals)
        for rule in self:
            after = rule._ea_snapshot()
            if after != before[rule.id]:
                self.env["ea.audit.activity"]._ea_record(
                    False, "signoff_rule_changed", "Sign-off rule of %s changed" % rule.code,
                    code=rule.code, before=before[rule.id], after=after,
                )
        return result

    def unlink(self):
        if not self.env.su:
            _require_policy_editor(self.env)
        for rule in self:
            self.env["ea.audit.activity"]._ea_record(
                False, "signoff_rule_removed", "Sign-off rule of %s removed" % rule.code, code=rule.code, before=rule._ea_snapshot(),
            )
        return super().unlink()

    @api.model
    def _ea_rules(self, codes=None):
        domain = [("code", "in", list(codes))] if codes is not None else []
        tri_state = {"yes": True, "no": False, "default": None}
        return {
            row.code: {
                "min_preparer": row.min_preparer or None,
                "min_reviewer": row.min_reviewer or None,
                "partner_required": tri_state[row.partner_required],
            }
            for row in self.sudo().search(domain)
        }

    @api.model
    def save_task_rules(self, rules):
        """Port of saveTaskRules: each item holds code, min_preparer, min_reviewer
        and partner_required (True, False or None). A row whose three values are
        all None is the firm default and is deleted. Returns the rows changed."""
        _require_policy_editor(self.env)
        templates = {t.code: t for t in self.env["ea.audit.task.template"].sudo().search([])}
        for rule in rules:
            if rule["code"] not in templates:
                raise rule_error(self.env, "unknown-task-code")
            for key in ("min_preparer", "min_reviewer"):
                if rule.get(key) is not None and rule[key] not in TEAM_LADDER:
                    raise rule_error(self.env, "invalid-team-role")
        changed = 0
        for rule in rules:
            min_preparer, min_reviewer = rule.get("min_preparer"), rule.get("min_reviewer")
            partner_required = rule.get("partner_required")
            row = self.sudo().search([("code", "=", rule["code"])], limit=1)
            empty = min_preparer is None and min_reviewer is None and partner_required is None
            if empty:
                if row:
                    row.unlink()
                    changed += 1
                continue
            vals = {
                "min_preparer": min_preparer or False,
                "min_reviewer": min_reviewer or False,
                "partner_required": {True: "yes", False: "no", None: "default"}[partner_required],
            }
            if row:
                row.write(vals)
            else:
                self.sudo().create(dict(vals, template_id=templates[rule["code"]].id))
            changed += 1
        return changed

    # ------------------------------------------------------------------
    # The matrix as a workbook (F002)
    # ------------------------------------------------------------------

    def _ea_role_words(self, lang):
        field = self._fields["min_preparer"]
        return dict(field._description_selection(self.with_context(lang=lang).env))

    @api.model
    def _ea_matrix_workbook(self):
        """(filename, bytes): every task of the index with today's rule and the firm's own columns."""
        _require_policy_editor(self.env)
        env = self.env
        lang = env.lang or "en_US"
        fr = lang.startswith("fr")
        Template = env["ea.audit.task.template"].sudo()
        policy = env["ea.audit.signoff.policy"]._ea_policy()
        own = self._ea_rules()
        labels = self._ea_role_words(lang)
        yes, no = env._("Yes"), env._("No")
        phases = dict(Template._fields["phase"]._description_selection(env))
        tiers = dict(Template._fields["tier"]._description_selection(env))
        rows = []
        for template in Template.search([], order="matrix_order, id"):
            rule = effective_task_rule(policy, own, template.code)
            firm = own.get(template.code) or {}
            firm_partner = firm.get("partner_required")
            rows.append([
                template.code,
                phases.get(template.phase),
                template.with_context(lang="fr_FR").title,
                template.with_context(lang="en_US").title,
                tiers.get(template.tier),
                labels[rule["min_preparer"]],
                labels[rule["min_reviewer"]],
                yes if rule["partner_required"] else no,
                labels[firm["min_preparer"]] if firm.get("min_preparer") else "",
                labels[firm["min_reviewer"]] if firm.get("min_reviewer") else "",
                "" if firm_partner is None else (yes if firm_partner else no),
                "",
            ])
        words = {
            "roles_sheet": env._("Roles"),
            "roles_header": [env._("Rank"), env._("Key"), "FR", "EN"],
            "roles": [
                [rank + 1, role, self._ea_role_words("fr_FR")[role], self._ea_role_words("en_US")[role]]
                for rank, role in enumerate(TEAM_LADDER)
            ],
            "role_labels": [labels[role] for role in TEAM_LADDER],
            "yes_no": [yes, no],
            "blank_note": env._("A blank cell in columns I, J or K applies the firm default. K accepts Yes or No."),
            "headers": [
                env._("Code"), env._("Phase"), env._("Task (FR)"), env._("Task (EN)"), env._("Tier"),
                env._("Today's minimum preparer"), env._("Today's minimum reviewer"), env._("Partner sign-off today"),
                env._("Your minimum preparer"), env._("Your minimum reviewer"),
                env._("Partner sign-off required (Yes/No)"), env._("Comment"),
            ],
        }
        name = "AuditISA-matrice-roles-signature.xlsx" if fr else "AuditISA-signoff-roles-matrix.xlsx"  # i18n: term
        return name, build_workbook(rows, words)

    @api.model
    def _ea_matrix_import(self, content):
        """Reads a completed matrix; saves it whole or not at all. Returns the rows changed."""
        _require_policy_editor(self.env)
        env = self.env
        lookup = {}
        for lang in ("en_US", "fr_FR"):
            for role, label in self._ea_role_words(lang).items():
                lookup[normalise(label)] = role
                lookup[normalise(role)] = role
        known = set(env["ea.audit.task.template"].sudo().search([]).mapped("code"))
        try:
            rules, errors = parse_workbook(content, known, lookup)
        except MatrixFileError as error:
            raise UserError({
                "unreadable": env._("The file is not a readable Excel workbook (.xlsx)."),
                "no-sheet": env._('The workbook has no "Tasks" sheet.'),
            }[error.code]) from None
        if errors:
            words = {
                "unknown-code": lambda row, value: env._("row %(row)s: unknown task code %(value)s (column A)", row=row, value=value),
                "duplicate": lambda row, value: env._("row %(row)s: task %(value)s appears more than once", row=row, value=value),
                "bad-preparer": lambda row, value: env._("row %(row)s: unknown role %(value)s in column I", row=row, value=value),
                "bad-reviewer": lambda row, value: env._("row %(row)s: unknown role %(value)s in column J", row=row, value=value),
                "bad-yes-no": lambda row, value: env._("row %(row)s: value %(value)s in column K, expected Yes or No", row=row, value=value),
            }
            lines = [words[kind](row, value) for row, kind, value in errors[:30]]
            raise UserError(env._("Nothing was saved. Correct these rows and import again:") + "\n" + "\n".join(lines))
        if not rules:
            raise UserError(env._('No task found on the "Tasks" sheet.'))
        return self.save_task_rules(rules)
