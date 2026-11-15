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
from ..services.file_scope import code_in_scope, nature_has_audit_programme
from ..services.signoff_rules import can_write
from ..services.standards_edition import period_start_of

_lt = LazyTranslate("ea_audit_core")

YES_NO = [("yes", "Yes"), ("no", "No")]
LOW_HIGH = [("low", "Low"), ("medium", "Medium"), ("high", "High")]  # only High counts (the tree)
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

# ----------------------------------------------------------------------
# The screen (owner's mock-up "profile-redesign", 2026-11-15): seven sections, one at a time.
# Each question: (number, text, help line, parts). A part is (field, label or None, kind, shown when).
# The order and the conditions of the sub-answers are those of the tree (services/engagement_profile).
# ----------------------------------------------------------------------
def _parent(a):
    return a.get("q4_group") == "parent"


def _outside_keeper(a):
    return bool(a.get("q14_keeper")) and a.get("q14_keeper") != "entity"


def _other_approach(a):
    return a.get("q19_approach") == "other"


_IT_POINT_WORDS = (
    _lt("1. How much is automated"),
    _lt("2. Software customised, integrated or built in-house"),
    _lt("3. Big IT changes this year"),
    _lt("4. Number of interfaces"),
    _lt("5. IT outsourced to several providers"),
    _lt("6. Reliance on reports from the system"),
    _lt("7. Data entered by hand or automatically"),
    _lt("8. Volume of data"),
)

SCREEN = (
    (_lt("The entity"), (
        ("Q1", _lt("Q1. Are its shares or bonds listed (BVMAC or another exchange) or offered to the public, or will they be within about two years?"),
         _lt("A listing or a public offering always makes the audit Complex."),
         (("q1_listed", None, "choice", None),)),
        ("Q2", _lt("Q2. Is it a public-interest entity?"),
         _lt("Bank, microfinance institution, insurer, pension fund, or named as such by law or by the firm."),
         (("q2_pie", None, "choice", None),)),
        ("Q3", _lt("Q3. Does a law or regulator require the auditor to test internal controls?"),
         _lt("Answer Yes only when testing the controls is an obligation, not a choice."),
         (("q3_controls_law", None, "choice", None),)),
        ("Q4", _lt("Q4. Is the entity part of a group?"),
         _lt("A branch keeping its own ledger and management also counts. Being in a group alone does not make it Complex."),
         (("q4_group", None, "choice", None),
          ("q4_consolidates", _lt("Does it prepare consolidated accounts?"), "choice", _parent),
          ("q4_other_auditors", _lt("Are some components audited by other auditors?"), "choice", _parent))),
    )),
    (_lt("The business"), (
        ("Q5", _lt("Q5. How many distinct activities or revenue streams?"),
         _lt("Count what management follows and reports separately."),
         (("q5_activities", None, "choice", None),)),
        ("Q6", _lt("Q6. How many sites keep accounting records or hold significant inventory?"),
         _lt("Count offices, plants, shops or warehouses with their own records or large stocks."),
         (("q6_sites", None, "choice", None),)),
        ("Q7", _lt("Q7. Major change this year?"),
         _lt("New activity, acquisition, restructuring or new management."),
         (("q7_major_change", None, "choice", None),)),
    )),
    (_lt("IT"), (
        ("Q8", _lt("Q8. Rate each IT point."),
         _lt("One point rated High makes the audit Complex. Low means simple, off-the-shelf and stable; "
             "High means custom-built, many interfaces or heavy reliance on reports from the system."),
         tuple(("q8_%d" % n, _IT_POINT_WORDS[n - 1], "choice", None) for n in range(1, 9))),
    )),
    (_lt("Specialists, people and ownership"), (
        ("Q9", _lt("Q9. Will specialists be needed, and on what?"),
         _lt("Actuary, valuer, engineer, IT or tax. Tax alone keeps Very simple possible."),
         (("q9_specialists", None, "choice", None),)),
        ("Q10", _lt("Q10. Does a regulator set the entity's reporting rules or receive its accounts?"),
         _lt("For example a sector regulator that fixes the form of the accounts or must receive them."),
         (("q10_regulator", None, "choice", None),)),
        ("Q11", _lt("Q11. Is there known or suspected fraud, non-compliance with laws and regulations, or whistle-blowing reports?"),
         _lt("Yes adds the fraud and laws work: P5.1, E3.1 and E6.1."),
         (("q11_fraud", None, "choice", None),)),
        ("Q12", _lt("Q12. Are all owners, including those who really own and control it, known?"),
         _lt("Think of the people who really own or control it, even through others."),
         (("q12_owners_known", None, "choice", None),)),
    )),
    (_lt("How the evidence will be obtained"), (
        ("Q13", _lt("Q13. Is any process so automated that testing balances and transactions alone cannot give enough evidence?"),
         _lt("For example sales recorded only by the system, with no document to check."),
         (("q13_automated", None, "choice", None),)),
        ("Q14", _lt("Q14. Who keeps the books or processes key data?"),
         _lt("Anyone other than the entity itself adds S5.2, service organisations."),
         (("q14_keeper", None, "choice", None),
          ("q14_rely_report", _lt("Will we rely on that provider's own auditor's report?"), "choice", _outside_keeper))),
        ("Q15", _lt("Q15. Is the engagement under the firm's close monitoring? Is an engagement quality review required?"),
         _lt("A quality review adds C4.2."),
         (("q15_monitoring", _lt("Close monitoring"), "choice", None),
          ("q15_eqr", _lt("Engagement quality review"), "choice", None))),
    )),
    (_lt("Risk"), (
        ("Q16", _lt("Q16. Significant risks beyond the presumed ones, or complex estimates?"),
         _lt("For example impairment, provisions or fair values with high uncertainty."),
         (("q16_risks", None, "choice", None),)),
        ("Q17", _lt("Q17. Any doubt about going concern?"),
         _lt("Losses, debts falling due, or the loss of a key customer or lender."),
         (("q17_going_concern", None, "choice", None),)),
        ("Q18", _lt("Q18. Significant related-party or unusual transactions outside the normal business?"),
         _lt("Dealings with owners, managers or their companies, or one-off operations outside the normal business."),
         (("q18_related_parties", None, "choice", None),)),
    )),
    (_lt("Approach and history"), (
        ("Q19", _lt("Q19. Planned approach"),
         _lt("Balances only at year end, or tick what else you will do: rely on controls, test at an interim date, use internal audit's work."),
         (("q19_approach", None, "choice", None),
          ("q19_controls", None, "toggle", _other_approach),
          ("q19_interim", None, "toggle", _other_approach),
          ("q19_internal_audit", None, "toggle", _other_approach))),
        ("Q20", _lt("Q20. Is this a first-year audit?"),
         _lt("Yes adds P1.2, contact with the predecessor auditor."),
         (("q20_first_year", None, "choice", None),)),
    )),
)

_WORDS = {
    "title": _lt("Engagement profile"),
    "back": _lt("Back to the engagement"),
    "previous": _lt("Previous"),
    "next": _lt("Next section"),
    "autosave": _lt("Answers are saved automatically."),
    "saving": _lt("Saving…"),
    "saved": _lt("Saved"),
    "provisional": _lt("Provisional"),
    "why": _lt("Why"),
    "tasks": _lt("Tasks"),
    "added": _lt("Added by your answers:"),
    "conclude": _lt("Conclude"),
    "see_tasks": _lt("See the tasks"),
    "held": _lt("Answer the questions that have just appeared to save this change."),
}
_ANSWERED = _lt("%(n)s of %(total)s answered")
_SECTION = _lt("Section %(n)s of %(total)s")
_LEVEL_SO_FAR = _lt("Level so far")
_LEVEL = _lt("Level")
_NOT_SETTLED = _lt("Not settled yet")
_OPEN_PATH = _lt("No sign of complexity so far. Very simple is still possible.")
_NOT_VS_SO_FAR = _lt("No sign of complexity so far. Not Very simple because:")
_TASKS_SO_FAR = _lt("%s tasks so far")
_TASKS_ALL = _lt("%s tasks")
_STILL_ONE = _lt("Still to answer: 1 question. The level can still change.")
_STILL_MANY = _lt("Still to answer: %s questions. The level can still change.")
_CONCLUDE_WAIT = _lt("Available once all 20 questions are answered.")
_CONCLUDE_READY = _lt("Puts the tasks on the file. You can reopen the questionnaire later.")
_CONCLUDED = _lt("Concluded on %(date)s by %(name)s. Changing an answer works the level out again and only adds tasks.")
_READ_ONLY = {
    "archived": _lt("Read only: this engagement is archived."),
    "eqr": _lt("Read only: the quality reviewer reads the answers but does not change them."),
    "role": _lt("Read only: your role reads the files but does not change them."),
}
_TOGGLES = set(tree.Q19_OPTIONS)

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
        """Back to the engagement. The answers are already saved: the screen saves each one."""
        self.ensure_one()
        return self.engagement_id._ea_open_engagement_screen()

    def action_open_tasks(self):
        self.ensure_one()
        return self.engagement_id._ea_open_task_list()

    # ------------------------------------------------------------------
    # The screen: one call reads it, one call saves answers, one concludes.
    # The client shows what these return and decides nothing.
    # ------------------------------------------------------------------

    def _ea_read_only_reason(self):
        """None when the user may answer; otherwise the key of _READ_ONLY."""
        self.ensure_one()
        engagement = self.engagement_id
        if engagement._ea_is_archived():
            return "archived"
        if engagement._ea_acts_as_eqr(self.env.user):
            return "eqr"
        if not can_write(self.env.user._ea_firm_role()):
            return "role"
        return None

    def _ea_clean_values(self, values):
        """Only answers, each one of its field's own values."""
        clean = {}
        for name, value in (values or {}).items():
            if name not in tree.ANSWER_FIELDS:
                raise rule_error(self.env, "forbidden")
            field = self._fields[name]
            if field.type == "boolean":
                clean[name] = bool(value)
            elif value in (False, None, ""):
                clean[name] = False
            elif value in dict(field.selection):
                clean[name] = value
            else:
                raise rule_error(self.env, "forbidden")
        return clean

    def _ea_task_preview(self, answers, level):
        """The tasks the file would hold at this level: (count, [(code, title)] the answers add)."""
        self.ensure_one()
        engagement = self.engagement_id.sudo()
        templates = self.env["ea.audit.task.template"].sudo().search([])
        form, nature = engagement.client_id.legal_form, engagement.nature
        codes = {
            t.code for t in templates
            if not t.conditional and code_in_scope(t.code, t.tier, t.conditional, level or tree.VERY_SIMPLE, form, nature)
        }
        added = tree.task_codes(answers) & set(templates.mapped("code"))
        codes |= added
        if self.state == "concluded":
            codes |= set(engagement.file_item_ids.filtered(lambda i: not i.conditional).mapped("code"))
        titles = {t.code: t.short_title or t.title for t in templates if t.code in added}
        return len(codes), [(code, titles.get(code, "")) for code in sorted(added)]

    def _ea_screen_parts(self, parts, answers, lang):
        env = self.env
        shown = []
        for field_name, label, kind, when in parts:
            field = self._fields[field_name]
            if label:
                words = label._translate(lang)
            elif kind == "toggle":
                words = self.fields_get([field_name], ["string"])[field_name]["string"]
            else:
                words = False
            shown.append({
                "field": field_name,
                "label": words,
                "kind": kind,
                "visible": when is None or bool(when(answers)),
                "options": [] if kind == "toggle" else [
                    {"value": value, "label": text} for value, text in field._description_selection(env)
                ],
            })
        return shown

    def ea_profile_screen(self, overlay=None, held=False):
        """Everything the questionnaire screen shows, in the reader's language."""
        self.ensure_one()
        self.engagement_id._ea_require_access()
        env = self.env
        lang = env.lang or "en_US"
        answers = self._ea_answers()
        answers.update(overlay or {})
        still_open = set(tree.missing(answers))
        answered = tree.answered_count(answers)
        total = len(tree.QUESTION_NUMBERS)
        complete = not still_open

        sections = []
        for title, questions in SCREEN:
            rows = [{
                "number": number,
                "text": text._translate(lang),
                "help": help_line._translate(lang),
                "answered": number not in still_open,
                "grid": number == "Q8",
                "parts": self._ea_screen_parts(parts, answers, lang),
            } for number, text, help_line, parts in questions]
            done = sum(1 for row in rows if row["answered"])
            sections.append({
                "title": title._translate(lang), "questions": rows, "answered": done, "total": len(rows),
                "done": done == len(rows),
            })

        level, reasons = tree.provisional(answers)
        if level == tree.NON_COMPLEX and not complete:
            intro = _NOT_VS_SO_FAR
        else:
            intro = _TITLES.get(level, _OPEN_PATH)
        count, added = self._ea_task_preview(answers, level)
        lce = False
        if complete and level != tree.COMPLEX:
            lce = (_LCE_YES if tree.lce_available(level, self._ea_period_start()) else _LCE_LATER)._translate(lang)
        still = total - answered
        if complete:
            still_line = False
        elif still == 1:
            still_line = _STILL_ONE._translate(lang)
        else:
            still_line = _STILL_MANY._translate(lang) % still
        level_words = dict(self._fields["level"]._description_selection(env))
        panel = {
            "heading": (_LEVEL if complete else _LEVEL_SO_FAR)._translate(lang),
            "provisional": not complete,
            "level": level or False,
            "level_label": level_words.get(level) if level else _NOT_SETTLED._translate(lang),
            "intro": intro._translate(lang),
            "reasons": [self._ea_reason_words(key, lang) for key in reasons],
            "tasks_line": (_TASKS_ALL if complete else _TASKS_SO_FAR)._translate(lang) % count,
            "task_count": count,
            "tasks": [{"code": code, "title": words} for code, words in added],
            "still_open": still_line,
            "lce_note": lce,
        }

        reason = self._ea_read_only_reason()
        concluded_note = False
        if self.state == "concluded" and self.concluded_at:
            day = fields.Date.context_today(self, self.concluded_at).strftime("%d/%m/%Y")
            concluded_note = _CONCLUDED._translate(lang) % {"date": day, "name": self.sudo().concluded_by_id.name or ""}
        words = {key: text._translate(lang) for key, text in _WORDS.items()}
        words["answered"] = _ANSWERED._translate(lang) % {"n": answered, "total": total}
        # the client puts the section's number in place of {n}
        words["section"] = _SECTION._translate(lang) % {"n": "{n}", "total": len(SCREEN)}
        return {
            "profile_id": self.id,
            "engagement": self.engagement_id.sudo().display_name,
            "state": self.state,
            "readonly": bool(reason),
            "readonly_note": _READ_ONLY[reason]._translate(lang) if reason else False,
            "held": bool(held),
            "answers": {name: answers.get(name) or False for name in tree.ANSWER_FIELDS},
            "progress": {"answered": answered, "total": total},
            "sections": sections,
            "panel": panel,
            "conclude": {
                "can": complete and not reason and self.state != "concluded",
                "show": self.state != "concluded",
                "hint": (_CONCLUDE_READY if complete else _CONCLUDE_WAIT)._translate(lang),
            },
            "concluded_note": concluded_note,
            "words": words,
        }

    def ea_profile_save(self, values):
        """Saves answers as they are given. A concluded profile concludes again on every change,
        so a change that opens a sub-question is held, not written, until that is answered too."""
        self.ensure_one()
        clean = self._ea_clean_values(values)
        self._ea_check_answerer()
        if self.state == "concluded" and tree.missing({**self._ea_answers(), **clean}):
            return self.ea_profile_screen(overlay=clean, held=True)
        if clean:
            self.write(clean)
        return self.ea_profile_screen()

    def ea_profile_conclude(self):
        """Conclude: refused, as before, while a question is open."""
        self.ensure_one()
        self.action_conclude()
        return self.ea_profile_screen()
