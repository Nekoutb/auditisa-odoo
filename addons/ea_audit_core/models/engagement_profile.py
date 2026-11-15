"""The engagement profile questionnaire (owner's rulings of 2026-11-15).

One row an engagement, made when the engagement is opened through the creation screen, or when
someone first opens the questionnaire of an older file. It may be saved unfinished: the
engagement then has no tasks and shows a banner. Concluding works the level out with the decision
tree of services/engagement_profile.py, never by hand, and puts the tasks of that level and of the
answers on the file. Answers changed afterwards conclude again and only ever ADD tasks.
"""
from odoo import api, fields, models
from odoo.tools.translate import LazyTranslate

from ..services import engagement_profile as tree
from ..services.errors import rule_error
from ..services.file_scope import nature_has_audit_programme
from ..services.standards_edition import period_start_of

_lt = LazyTranslate("ea_audit_core")

YES_NO = [("yes", "Yes"), ("no", "No")]
LOW_HIGH = [("low", "Low"), ("high", "High")]
ONE_FEW_MORE = [("one", "1"), ("few", "2 to 3"), ("more", "More than 3")]
PIE_SELECTION = [
    ("none", "No"),
    ("bank", "Bank"),
    ("microfinance", "Microfinance institution"),
    ("insurer", "Insurer"),
    ("pension", "Pension fund"),
    ("designated", "Designated by law or by the firm"),
]
GROUP_SELECTION = [("standalone", "Stand-alone"), ("parent", "Parent"), ("subsidiary", "Subsidiary or branch")]
SPECIALIST_SELECTION = [
    ("none", "None"),
    ("tax", "Tax only"),
    ("other", "Other specialists, not on the core of the business"),
    ("core", "On the core of the business"),
]
KEEPER_SELECTION = [
    ("entity", "The entity itself"),
    ("accountant", "An external accountant"),
    ("payroll", "A payroll bureau"),
    ("hosting", "A hosting or IT provider"),
]
APPROACH_SELECTION = [
    ("substantive", "Test balances only, all at year end"),
    ("other", "Something else (tick below)"),
]
STATE_SELECTION = [("draft", "Not finished"), ("concluded", "Concluded")]

IT_POINT_LABELS = (
    "How much is automated",
    "Software customised, integrated or built in-house",
    "Big IT changes this year",
    "Number of interfaces",
    "IT outsourced to several providers",
    "Reliance on reports from the system",
    "Data entered by hand or automatically",
    "Volume of data",
)

# The reason keys of the tree, in plain words. "%s" receives the kind of entity or the IT point.
_REASONS = {
    "q1": _lt("Q1 listed or offered to the public"),
    "q2": _lt("Q2 public-interest entity: %s"),
    "q3": _lt("Q3 controls testing required by law or a regulator"),
    "q4": _lt("Q4 parent whose components are audited by other auditors"),
    "q5": _lt("Q5 more than 3 activities"),
    "q6": _lt("Q6 more than 3 sites"),
    "q7": _lt("Q7 major change this year"),
    "q8": _lt("Q8 IT point %s high"),
    "q9": _lt("Q9 specialists needed on the core of the business"),
    "q10": _lt("Q10 a regulator sets the reporting rules or receives the accounts"),
    "q11": _lt("Q11 known or suspected fraud, non-compliance or whistle-blowing reports"),
    "q12": _lt("Q12 not all owners are known"),
    "q4:consolidates": _lt("Q4 the entity prepares consolidated accounts"),
    "q13": _lt("Q13 a process too automated for testing balances alone"),
    "q14": _lt("Q14 we rely on a service provider's own auditor report"),
    "q15:monitoring": _lt("Q15 under the firm's close monitoring"),
    "q15:eqr": _lt("Q15 an engagement quality review is required"),
    "q16": _lt("Q16 significant risks or complex estimates expected"),
    "q17": _lt("Q17 doubt about going concern"),
    "q18": _lt("Q18 significant related-party or unusual transactions"),
    "q9:other": _lt("Q9 specialists other than tax"),
    "q19": _lt("Q19 not tested by balances only at year end"),
}
_TITLES = {
    tree.COMPLEX: _lt("Complex because:"),
    tree.NON_COMPLEX: _lt("Non-complex: no sign of complexity, but not Very simple because:"),
    tree.VERY_SIMPLE: _lt("Very simple: no sign of complexity and every Very simple condition is met."),
}
_LCE_YES = _lt(
    "The ISA for LCE is adopted in Cameroon: because this period begins on or after 15 December 2025, "
    "this engagement may be documented under the ISA for LCE. For information only."
)
_LCE_LATER = _lt(
    "The ISA for LCE is adopted in Cameroon for periods beginning on or after 15 December 2025. "
    "This period begins earlier, so it is documented under the full ISAs."
)
_MISSING = _lt("Still to answer: %s")

# Written only by the methods that carry the rule.
_ENGINE_FIELDS = {"engagement_id", "state", "level", "concluded_at", "concluded_by_id"}


class EngagementProfile(models.Model):
    _name = "ea.audit.engagement.profile"
    _description = "Engagement profile questionnaire"
    _rec_name = "engagement_id"

    engagement_id = fields.Many2one("ea.audit.engagement", string="Engagement", required=True, index=True, ondelete="cascade")
    state = fields.Selection(STATE_SELECTION, string="Status", required=True, default="draft")
    level = fields.Selection(
        [("complex", "Complex"), ("non_complex", "Non-complex"), ("very_simple", "Very simple")],
        string="Level", readonly=True,
    )
    concluded_at = fields.Datetime(readonly=True)
    concluded_by_id = fields.Many2one("res.users", string="Concluded by", readonly=True)

    # The entity
    q1_listed = fields.Selection(YES_NO, string="Q1 Listed or offered to the public")
    q2_pie = fields.Selection(PIE_SELECTION, string="Q2 Public-interest entity")
    q3_controls_law = fields.Selection(YES_NO, string="Q3 Controls testing required by law")
    q4_group = fields.Selection(GROUP_SELECTION, string="Q4 Part of a group")
    q4_consolidates = fields.Selection(YES_NO, string="Q4 Prepares consolidated accounts")
    q4_other_auditors = fields.Selection(YES_NO, string="Q4 Components audited by other auditors")
    # The business
    q5_activities = fields.Selection(ONE_FEW_MORE, string="Q5 Activities")
    q6_sites = fields.Selection(ONE_FEW_MORE, string="Q6 Sites")
    q7_major_change = fields.Selection(YES_NO, string="Q7 Major change this year")
    # IT
    q8_1 = fields.Selection(LOW_HIGH, string=IT_POINT_LABELS[0])
    q8_2 = fields.Selection(LOW_HIGH, string=IT_POINT_LABELS[1])
    q8_3 = fields.Selection(LOW_HIGH, string=IT_POINT_LABELS[2])
    q8_4 = fields.Selection(LOW_HIGH, string=IT_POINT_LABELS[3])
    q8_5 = fields.Selection(LOW_HIGH, string=IT_POINT_LABELS[4])
    q8_6 = fields.Selection(LOW_HIGH, string=IT_POINT_LABELS[5])
    q8_7 = fields.Selection(LOW_HIGH, string=IT_POINT_LABELS[6])
    q8_8 = fields.Selection(LOW_HIGH, string=IT_POINT_LABELS[7])
    # Specialists, people and ownership
    q9_specialists = fields.Selection(SPECIALIST_SELECTION, string="Q9 Specialists")
    q10_regulator = fields.Selection(YES_NO, string="Q10 Regulator sets the reporting rules")
    q11_fraud = fields.Selection(YES_NO, string="Q11 Fraud, non-compliance or whistle-blowing")
    q12_owners_known = fields.Selection(YES_NO, string="Q12 All owners known")
    # How the evidence will be obtained
    q13_automated = fields.Selection(YES_NO, string="Q13 Process too automated for balance testing alone")
    q14_keeper = fields.Selection(KEEPER_SELECTION, string="Q14 Who keeps the books")
    q14_rely_report = fields.Selection(YES_NO, string="Q14 Rely on the provider's auditor report")
    # Risk
    q15_monitoring = fields.Selection(YES_NO, string="Q15 Under close monitoring")
    q15_eqr = fields.Selection(YES_NO, string="Q15 Engagement quality review required")
    q16_risks = fields.Selection(YES_NO, string="Q16 Significant risks or complex estimates")
    q17_going_concern = fields.Selection(YES_NO, string="Q17 Doubt about going concern")
    q18_related_parties = fields.Selection(YES_NO, string="Q18 Significant related-party or unusual transactions")
    # Approach and history
    q19_approach = fields.Selection(APPROACH_SELECTION, string="Q19 Planned approach")
    q19_controls = fields.Boolean(string="Rely on controls")
    q19_interim = fields.Boolean(string="Test at an interim date")
    q19_internal_audit = fields.Boolean(string="Use internal audit's work")
    q20_first_year = fields.Selection(YES_NO, string="Q20 First-year audit")

    # What the screen shows
    missing_text = fields.Char(string="Still to answer", compute="_compute_texts")
    conclusion_title = fields.Char(string="Conclusion", compute="_compute_texts")
    reasons_text = fields.Text(string="Reasons", compute="_compute_texts")
    lce_note = fields.Char(string="ISA for LCE", compute="_compute_texts")

    _engagement_uniq = models.Constraint("UNIQUE(engagement_id)", "An engagement has one profile.")

    # ------------------------------------------------------------------
    # Reading the answers
    # ------------------------------------------------------------------

    def _ea_answers(self):
        self.ensure_one()
        return {name: self[name] for name in tree.ANSWER_FIELDS}

    def _ea_reason_words(self, key, lang):
        head, _sep, detail = key.partition(":")
        label = _REASONS.get(key) or _REASONS.get(head)
        if label is None:
            return key
        text = label._translate(lang)
        if head == "q2":
            kinds = dict(self._fields["q2_pie"]._description_selection(self.env))
            return text % kinds.get(detail, detail)
        if head == "q8":
            return text % detail
        return text

    def _ea_period_start(self):
        engagement = self.engagement_id.sudo()
        if engagement.period_start:
            return engagement.period_start
        if engagement.period_end:
            return period_start_of(engagement.period_end, engagement.duration_months)
        return False

    @api.depends(*tree.ANSWER_FIELDS, "state", "level")
    @api.depends_context("lang")
    def _compute_texts(self):
        lang = self.env.lang or "en_US"
        for profile in self:
            answers = profile._ea_answers()
            still_open = tree.missing(answers)
            profile.missing_text = _MISSING._translate(lang) % ", ".join(still_open) if still_open else False
            if profile.state != "concluded" or not profile.level or still_open:
                profile.conclusion_title = profile.reasons_text = profile.lce_note = False
                continue
            level, reasons = tree.conclude(answers)
            profile.conclusion_title = _TITLES[level]._translate(lang)
            profile.reasons_text = "\n".join("• " + profile._ea_reason_words(key, lang) for key in reasons) or False
            if level == tree.COMPLEX:
                profile.lce_note = False
            elif tree.lce_available(level, profile._ea_period_start()):
                profile.lce_note = _LCE_YES._translate(lang)
            else:
                profile.lce_note = _LCE_LATER._translate(lang)

    # ------------------------------------------------------------------
    # Who may answer
    # ------------------------------------------------------------------

    def _ea_check_answerer(self):
        """Any accepted member who writes, on an open file; a quality reviewer only reads."""
        self.env["ea.audit.engagement"]._ea_require_write()
        for profile in self:
            engagement = profile.engagement_id
            engagement._ea_require_access()
            engagement._ea_assert_mutable()
            if engagement._ea_acts_as_eqr(self.env.user):
                raise rule_error(self.env, "eqr-read-only")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise rule_error(self.env, "forbidden")
        return super().create(vals_list)

    def write(self, vals):
        if not vals:
            return True
        if not self.env.su:
            if set(vals) & _ENGINE_FIELDS:
                raise rule_error(self.env, "forbidden")
            self._ea_check_answerer()
        result = super().write(vals)
        if not self.env.context.get("ea_profile_applying") and set(vals) & set(tree.ANSWER_FIELDS):
            # A concluded profile stays concluded: new answers conclude again and only add tasks.
            for profile in self.filtered(lambda p: p.state == "concluded"):
                profile._ea_apply()
        return result

    # ------------------------------------------------------------------
    # Concluding
    # ------------------------------------------------------------------

    def _ea_apply(self):
        """Work the level out and put its tasks on the file. Adds, never removes."""
        self.ensure_one()
        answers = self._ea_answers()
        still_open = tree.missing(answers)
        if still_open:
            raise rule_error(self.env, "profile-incomplete", questions=", ".join(still_open))
        level, _reasons = tree.conclude(answers)
        profile = self.sudo().with_context(ea_profile_applying=True)
        values = {"level": level}
        if profile.state != "concluded":
            values.update(state="concluded", concluded_at=fields.Datetime.now(), concluded_by_id=self.env.user.id)
        profile.write(values)
        engagement = profile.engagement_id
        if engagement._ea_is_archived():
            raise rule_error(self.env, "archived")
        engagement_values = {}
        if engagement.complexity != level:
            engagement_values["complexity"] = level
        if tree.is_first_year(answers) and not engagement.first_year:
            engagement_values["first_year"] = True
        if engagement_values:
            engagement.write(engagement_values)
        engagement._ea_instantiate_file_index()
        if nature_has_audit_programme(engagement.nature):
            engagement._ea_seed_presumed_risks()
        for code in sorted(tree.task_codes(answers)):
            engagement._ea_ensure_task(code)
        return level

    def action_conclude(self):
        self.ensure_one()
        self._ea_check_answerer()
        self._ea_apply()
        return True

    def action_save_for_later(self):
        """The form saved the answers before calling this: back to the engagement."""
        self.ensure_one()
        return self.engagement_id._ea_open_engagement_screen()

    def action_open_tasks(self):
        self.ensure_one()
        return self.engagement_id._ea_open_task_list()
