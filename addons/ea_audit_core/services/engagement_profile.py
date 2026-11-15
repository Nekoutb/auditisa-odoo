"""The engagement profile: twenty compulsory questions, the decision tree and the tasks they bring.

Owner's rulings of 2026-11-15 (approved page "Engagement profile questionnaire", draft 3):

* every question must be answered before the level can be worked out; there is no "don't know";
* the level follows from the answers alone, nobody changes it by hand;
* gate 1: any sign of complexity makes the engagement Complex;
* gate 2: when every Very simple condition is met it is Very simple; otherwise Non-complex;
* a subsidiary is judged like a stand-alone company: being in a group only adds tasks;
* no hour limit, no size threshold, joint audit never set automatically;
* answers only ever ADD tasks (the caller never removes one).

Pure: standard library only, so the tree is tested without Odoo. The texts shown to people live in
the model, which turns the reason keys returned here into words in the reader's language.
"""

COMPLEX = "complex"
NON_COMPLEX = "non_complex"
VERY_SIMPLE = "very_simple"

IT_POINTS = tuple("q8_%d" % n for n in range(1, 9))
Q19_OPTIONS = ("q19_controls", "q19_interim", "q19_internal_audit")

# The questions a person must answer, in the order they are asked. Each entry is
# (question number, field, when it is asked). A sub-answer is asked only in its case.
REQUIRED = (
    ("Q1", "q1_listed", None),
    ("Q2", "q2_pie", None),
    ("Q3", "q3_controls_law", None),
    ("Q4", "q4_group", None),
    ("Q4", "q4_consolidates", lambda a: a.get("q4_group") == "parent"),
    ("Q4", "q4_other_auditors", lambda a: a.get("q4_group") == "parent"),
    ("Q5", "q5_activities", None),
    ("Q6", "q6_sites", None),
    ("Q7", "q7_major_change", None),
) + tuple(("Q8", point, None) for point in IT_POINTS) + (
    ("Q9", "q9_specialists", None),
    ("Q10", "q10_regulator", None),
    ("Q11", "q11_fraud", None),
    ("Q12", "q12_owners_known", None),
    ("Q13", "q13_automated", None),
    ("Q14", "q14_keeper", None),
    ("Q14", "q14_rely_report", lambda a: bool(a.get("q14_keeper")) and a.get("q14_keeper") != "entity"),
    ("Q15", "q15_monitoring", None),
    ("Q15", "q15_eqr", None),
    ("Q16", "q16_risks", None),
    ("Q17", "q17_going_concern", None),
    ("Q18", "q18_related_parties", None),
    ("Q19", "q19_approach", None),
    ("Q20", "q20_first_year", None),
)

ANSWER_FIELDS = tuple(dict.fromkeys(field for _q, field, _when in REQUIRED)) + Q19_OPTIONS


def _yes(answers, field):
    return answers.get(field) == "yes"


def _parent(answers):
    return answers.get("q4_group") == "parent"


def _relies_on_provider_report(answers):
    keeper = answers.get("q14_keeper")
    return bool(keeper) and keeper != "entity" and _yes(answers, "q14_rely_report")


def missing(answers):
    """The question numbers still to answer, in order, each once. Empty when complete."""
    open_questions = []
    for number, field, when in REQUIRED:
        if when is not None and not when(answers):
            continue
        if not answers.get(field):
            open_questions.append(number)
    # "Something other than year-end substantive" must say which.
    if answers.get("q19_approach") == "other" and not any(answers.get(f) for f in Q19_OPTIONS):
        open_questions.append("Q19")
    return list(dict.fromkeys(open_questions))


def is_complete(answers):
    return not missing(answers)


def complex_reasons(answers):
    """Gate 1: every sign of complexity, as reason keys ("q2:bank", "q8:3")."""
    reasons = []
    if _yes(answers, "q1_listed"):
        reasons.append("q1")
    pie = answers.get("q2_pie")
    if pie and pie != "none":
        reasons.append("q2:%s" % pie)
    if _yes(answers, "q3_controls_law"):
        reasons.append("q3")
    if _parent(answers) and _yes(answers, "q4_other_auditors"):
        reasons.append("q4")
    if answers.get("q5_activities") == "more":
        reasons.append("q5")
    if answers.get("q6_sites") == "more":
        reasons.append("q6")
    if _yes(answers, "q7_major_change"):
        reasons.append("q7")
    for n, point in enumerate(IT_POINTS, start=1):
        if answers.get(point) == "high":
            reasons.append("q8:%d" % n)
    if answers.get("q9_specialists") == "core":
        reasons.append("q9")
    return reasons


def not_very_simple_reasons(answers):
    """Gate 2: every Very simple condition that is NOT met, as reason keys."""
    reasons = []
    if _yes(answers, "q10_regulator"):
        reasons.append("q10")
    if _yes(answers, "q11_fraud"):
        reasons.append("q11")
    if answers.get("q12_owners_known") == "no":
        reasons.append("q12")
    if _parent(answers) and _yes(answers, "q4_consolidates"):
        reasons.append("q4:consolidates")
    if _yes(answers, "q13_automated"):
        reasons.append("q13")
    if _relies_on_provider_report(answers):
        reasons.append("q14")
    if _yes(answers, "q15_monitoring"):
        reasons.append("q15:monitoring")
    if _yes(answers, "q15_eqr"):
        reasons.append("q15:eqr")
    if _yes(answers, "q16_risks"):
        reasons.append("q16")
    if _yes(answers, "q17_going_concern"):
        reasons.append("q17")
    if _yes(answers, "q18_related_parties"):
        reasons.append("q18")
    if answers.get("q9_specialists") not in (None, False, "", "none", "tax"):
        reasons.append("q9:other")
    if answers.get("q19_approach") not in (None, False, "", "substantive"):
        reasons.append("q19")
    return reasons


def conclude(answers):
    """(level, reason keys). Raises ValueError while a question is unanswered."""
    still_open = missing(answers)
    if still_open:
        raise ValueError("unanswered: %s" % ", ".join(still_open))
    reasons = complex_reasons(answers)
    if reasons:
        return COMPLEX, reasons
    reasons = not_very_simple_reasons(answers)
    if reasons:
        return NON_COMPLEX, reasons
    return VERY_SIMPLE, []


QUESTION_NUMBERS = tuple(dict.fromkeys(number for number, _field, _when in REQUIRED))


def answered_count(answers):
    """How many of the twenty questions are fully answered, sub-answers included."""
    return len(QUESTION_NUMBERS) - len(missing(answers))


def provisional(answers):
    """(level or None, reason keys) from the answers given so far, for the screen only.

    The same two gates as conclude(), read on a partial set of answers: a sign of complexity
    already makes the level Complex, an unmet Very simple condition already rules Very simple
    out. While nothing rules it out and a question is open, the level is not settled (None).
    Once every question is answered this is exactly conclude().
    """
    reasons = complex_reasons(answers)
    if reasons:
        return COMPLEX, reasons
    reasons = not_very_simple_reasons(answers)
    if reasons:
        return NON_COMPLEX, reasons
    if is_complete(answers):
        return VERY_SIMPLE, []
    return None, []


def is_first_year(answers):
    return _yes(answers, "q20_first_year")


# What the answers switch on, whatever the level. The eleven conditional templates of the catalogue:
#   P1.2 predecessor auditor .... Q20 first-year audit (as the old "first-year audit" box did)
#   P4.2 control environment .... Q3 controls testing by law, Q13 automated process, Q19 reliance on controls
#   P4.3 IT environment ......... Q8 any IT point high, Q13 automated process
#   S5.1 experts (ISA 620) ...... Q9 any specialist, tax included
#   S5.2 service organisations .. Q14 books or key data kept by someone outside the entity
#   S5.3 internal audit ......... Q19 internal audit's work used
#   E5.1-E5.5 .................... retired (income statement covered by the E4 indexes): never
# Two tasks of the "extended" tier, which a Non-complex file does not have otherwise:
#   C4.2 engagement quality review  Q15 a quality review is required
#   P2.3 scope and components ....  Q4 a parent that consolidates or whose components others audit
# Q11 known or suspected fraud, non-compliance or whistle-blowing: the fraud and laws work, P5.1 (fraud
# risks), E3.1 (journal entries and fraud) and E6.1 (laws and NOCLAR). They are core tasks, on every
# file already; they are named here so the answer keeps them on whatever happens elsewhere.
def task_codes(answers):
    codes = set()
    if is_first_year(answers):
        codes.add("P1.2")
    if _yes(answers, "q3_controls_law") or _yes(answers, "q13_automated") or (
        answers.get("q19_approach") == "other" and answers.get("q19_controls")
    ):
        codes.add("P4.2")
    if any(answers.get(point) == "high" for point in IT_POINTS) or _yes(answers, "q13_automated"):
        codes.add("P4.3")
    if answers.get("q9_specialists") in ("tax", "other", "core"):
        codes.add("S5.1")
    keeper = answers.get("q14_keeper")
    if keeper and keeper != "entity":
        codes.add("S5.2")
    if answers.get("q19_approach") == "other" and answers.get("q19_internal_audit"):
        codes.add("S5.3")
    if _yes(answers, "q15_eqr"):
        codes.add("C4.2")
    if _parent(answers) and (_yes(answers, "q4_consolidates") or _yes(answers, "q4_other_auditors")):
        codes.add("P2.3")
    if _yes(answers, "q11_fraud"):
        codes.update(("P5.1", "E3.1", "E6.1"))
    return codes


# The ISA for LCE, adopted in Cameroon, applies to periods beginning on or after this day.
LCE_FROM = (2025, 12, 15)


def lce_available(level, period_start):
    """True when a Non-complex or Very simple engagement may be documented under the ISA for LCE."""
    if level not in (NON_COMPLEX, VERY_SIMPLE) or not period_start:
        return False
    return (period_start.year, period_start.month, period_start.day) >= LCE_FROM
