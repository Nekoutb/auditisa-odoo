"""The decision tree of the engagement profile, one condition at a time."""
from datetime import date

import pytest

from engagement_profile import (
    ANSWER_FIELDS,
    COMPLEX,
    NON_COMPLEX,
    VERY_SIMPLE,
    answered_count,
    conclude,
    is_first_year,
    lce_available,
    missing,
    provisional,
    retired_reasons,
    task_codes,
)

# A small owner-managed company: every answer on the Very simple side.
PLAIN = {
    "q1_listed": "no", "q2_pie": "none", "q3_controls_law": "no", "q4_group": "standalone",
    "q5_activities": "one", "q6_sites": "one", "q7_major_change": "no",
    **{"q8_%d" % n: "low" for n in range(1, 9)},
    "q9_specialists": "none", "q10_regulator": "no",
    "q11_fraud": "no",
    "q12_owners_known": "yes", "q13_automated": "no", "q14_keeper": "entity",
    "q16_risks": "no", "q17_going_concern": "no",
    "q18_related_parties": "no", "q19_approach": "substantive", "q20_first_year": "no",
}


def answers(**changes):
    return {**PLAIN, **changes}


def test_plain_company_is_very_simple_with_no_reason():
    assert conclude(PLAIN) == (VERY_SIMPLE, [])


def test_two_to_three_activities_or_sites_stay_very_simple():
    assert conclude(answers(q5_activities="few", q6_sites="few"))[0] == VERY_SIMPLE


# ---------------------------------------------------------------- gate 1

@pytest.mark.parametrize("changes, reason", [
    ({"q1_listed": "yes"}, "q1"),
    ({"q2_pie": "bank"}, "q2:bank"),
    ({"q2_pie": "microfinance"}, "q2:microfinance"),
    ({"q2_pie": "insurer"}, "q2:insurer"),
    ({"q2_pie": "pension"}, "q2:pension"),
    ({"q2_pie": "designated"}, "q2:designated"),
    ({"q3_controls_law": "yes"}, "q3"),
    ({"q4_group": "parent", "q4_consolidates": "yes", "q4_other_auditors": "yes"}, "q4"),
    ({"q5_activities": "more"}, "q5"),
    ({"q6_sites": "more"}, "q6"),
    ({"q7_major_change": "yes"}, "q7"),
    ({"q9_specialists": "core"}, "q9"),
] + [({"q8_%d" % n: "high"}, "q8:%d" % n) for n in range(1, 9)])
def test_each_sign_of_complexity_alone_makes_it_complex(changes, reason):
    level, reasons = conclude(answers(**changes))
    assert level == COMPLEX
    assert reason in reasons


def test_every_reason_is_listed():
    level, reasons = conclude(answers(q2_pie="bank", q8_3="high", q8_7="high"))
    assert (level, reasons) == (COMPLEX, ["q2:bank", "q8:3", "q8:7"])


def test_a_subsidiary_is_judged_like_a_stand_alone_company():
    assert conclude(answers(q4_group="subsidiary"))[0] == VERY_SIMPLE


def test_a_parent_auditing_its_whole_group_itself_is_not_complex_for_that():
    level, reasons = conclude(answers(q4_group="parent", q4_consolidates="yes", q4_other_auditors="no"))
    assert level == NON_COMPLEX
    assert reasons == ["q4:consolidates"]


def test_a_parent_that_does_not_consolidate_can_be_very_simple():
    assert conclude(answers(q4_group="parent", q4_consolidates="no", q4_other_auditors="no"))[0] == VERY_SIMPLE


def test_group_sub_answers_left_from_an_earlier_choice_are_ignored():
    stale = answers(q4_group="subsidiary", q4_consolidates="yes", q4_other_auditors="yes")
    assert conclude(stale) == (VERY_SIMPLE, [])


# ---------------------------------------------------------------- gate 2

@pytest.mark.parametrize("changes, reason", [
    ({"q10_regulator": "yes"}, "q10"),
    ({"q11_fraud": "yes"}, "q11"),
    ({"q12_owners_known": "no"}, "q12"),
    ({"q4_group": "parent", "q4_consolidates": "yes", "q4_other_auditors": "no"}, "q4:consolidates"),
    ({"q13_automated": "yes"}, "q13"),
    ({"q14_keeper": "accountant", "q14_rely_report": "yes"}, "q14"),
    ({"q16_risks": "yes"}, "q16"),
    ({"q17_going_concern": "yes"}, "q17"),
    ({"q18_related_parties": "yes"}, "q18"),
    ({"q9_specialists": "other"}, "q9:other"),
    ({"q19_approach": "other", "q19_controls": True}, "q19"),
    ({"q19_approach": "other", "q19_interim": True}, "q19"),
    ({"q19_approach": "other", "q19_internal_audit": True}, "q19"),
])
def test_each_unmet_very_simple_condition_alone_makes_it_non_complex(changes, reason):
    assert conclude(answers(**changes)) == (NON_COMPLEX, [reason])


def test_a_tax_specialist_keeps_it_very_simple():
    assert conclude(answers(q9_specialists="tax"))[0] == VERY_SIMPLE


def test_an_outside_bookkeeper_without_reliance_on_its_auditor_keeps_it_very_simple():
    assert conclude(answers(q14_keeper="accountant", q14_rely_report="no"))[0] == VERY_SIMPLE


def test_first_year_changes_no_level():
    assert conclude(answers(q20_first_year="yes"))[0] == VERY_SIMPLE


def test_gate_one_wins_over_gate_two():
    level, reasons = conclude(answers(q1_listed="yes", q10_regulator="yes"))
    assert (level, reasons) == (COMPLEX, ["q1"])


# ---------------------------------------------------------------- compulsory answers

def test_nothing_answered_lists_every_question_once():
    assert missing({}) == ["Q%d" % n for n in range(1, 20)]


@pytest.mark.parametrize("field", sorted(set(PLAIN)))
def test_each_question_is_compulsory(field):
    partial = dict(PLAIN)
    del partial[field]
    assert missing(partial)
    with pytest.raises(ValueError):
        conclude(partial)


@pytest.mark.parametrize("changes, question", [
    ({"q4_group": "parent"}, "Q4"),
    ({"q4_group": "parent", "q4_consolidates": "yes"}, "Q4"),
    ({"q14_keeper": "payroll"}, "Q14"),
    ({"q19_approach": "other"}, "Q18"),
])
def test_a_sub_answer_is_compulsory_in_its_case(changes, question):
    assert missing(answers(**changes)) == [question]


def test_no_sub_answer_is_asked_outside_its_case():
    assert missing(answers(q20_first_year="yes", q14_keeper="entity")) == []


def test_every_answer_field_is_known():
    assert set(PLAIN) <= set(ANSWER_FIELDS)


# ---------------------------------------------------------------- tasks

def test_a_plain_company_switches_nothing_on():
    assert task_codes(PLAIN) == set()


@pytest.mark.parametrize("changes, code", [
    ({"q20_first_year": "yes"}, "P1.2"),
    ({"q11_fraud": "yes"}, "P5.1"),
    ({"q11_fraud": "yes"}, "E3.1"),
    ({"q11_fraud": "yes"}, "E6.1"),
    ({"q3_controls_law": "yes"}, "P4.2"),
    ({"q13_automated": "yes"}, "P4.2"),
    ({"q19_approach": "other", "q19_controls": True}, "P4.2"),
    ({"q8_4": "high"}, "P4.3"),
    ({"q13_automated": "yes"}, "P4.3"),
    ({"q9_specialists": "tax"}, "S5.1"),
    ({"q9_specialists": "other"}, "S5.1"),
    ({"q9_specialists": "core"}, "S5.1"),
    ({"q14_keeper": "hosting", "q14_rely_report": "no"}, "S5.2"),
    ({"q19_approach": "other", "q19_internal_audit": True}, "S5.3"),
    ({"q4_group": "parent", "q4_consolidates": "yes", "q4_other_auditors": "no"}, "P2.3"),
    ({"q4_group": "parent", "q4_consolidates": "no", "q4_other_auditors": "yes"}, "P2.3"),
])
def test_an_answer_switches_its_task_on(changes, code):
    assert code in task_codes(answers(**changes))


def test_options_ticked_before_choosing_year_end_substantive_switch_nothing_on():
    assert task_codes(answers(q19_approach="substantive", q19_controls=True, q19_internal_audit=True)) == set()


def test_retired_income_statement_tasks_are_never_switched_on():
    everything = answers(
        q1_listed="yes", q3_controls_law="yes", q13_automated="yes", q9_specialists="core",
        q14_keeper="accountant", q14_rely_report="yes", q19_approach="other",
        q19_controls=True, q19_interim=True, q19_internal_audit=True, q20_first_year="yes",
        q4_group="parent", q4_consolidates="yes", q4_other_auditors="yes", **{"q8_%d" % n: "high" for n in range(1, 9)},
    )
    assert not {code for code in task_codes(everything) if code.startswith("E5.")}


# ---- the former Q15, removed on 2026-11-16: the firm decides on a quality review on P1.5 only

@pytest.mark.parametrize("old", [
    {"q15_monitoring": "yes"}, {"q15_eqr": "yes"}, {"q15_monitoring": "yes", "q15_eqr": "yes"},
])
def test_former_q15_answers_change_neither_level_nor_tasks(old):
    assert conclude(answers(**old)) == (VERY_SIMPLE, [])
    assert task_codes(answers(**old)) == set()
    assert "C4.2" not in task_codes(answers(**old))


def test_former_q15_is_not_asked():
    assert not {"q15_monitoring", "q15_eqr"} & set(ANSWER_FIELDS)
    assert missing(PLAIN) == []


def test_former_q15_answers_explain_an_old_conclusion():
    assert retired_reasons({"q15_monitoring": "yes", "q15_eqr": "no"}) == ["q15:monitoring"]
    assert retired_reasons({"q15_monitoring": "yes", "q15_eqr": "yes"}) == ["q15:monitoring", "q15:eqr"]
    assert retired_reasons({}) == []


def test_first_year():
    assert not is_first_year(PLAIN)
    assert is_first_year(answers(q20_first_year="yes"))


# ---------------------------------------------------------------- ISA for LCE

def test_isa_for_lce_from_periods_beginning_15_december_2025():
    assert lce_available(NON_COMPLEX, date(2025, 12, 15))
    assert lce_available(VERY_SIMPLE, date(2026, 1, 1))
    assert not lce_available(VERY_SIMPLE, date(2025, 1, 1))
    assert not lce_available(COMPLEX, date(2026, 1, 1))
    assert not lce_available(NON_COMPLEX, None)


# ---- the level so far, shown while the questionnaire is being answered

def test_nothing_answered_leaves_the_level_open():
    assert provisional({}) == (None, [])
    assert answered_count({}) == 0


def test_a_sign_of_complexity_settles_complex_before_the_end():
    assert provisional({"q8_2": "high"}) == (COMPLEX, ["q8:2"])


def test_low_it_is_not_a_sign_of_complexity():
    assert provisional({"q8_2": "low"}) == (None, [])


def test_an_unmet_very_simple_condition_rules_very_simple_out_early():
    assert provisional({"q17_going_concern": "yes"}) == (NON_COMPLEX, ["q17"])


def test_plain_answers_stay_open_until_the_last_one():
    partial = {k: v for k, v in PLAIN.items() if k != "q20_first_year"}
    assert provisional(partial) == (None, [])
    assert answered_count(partial) == 18


@pytest.mark.parametrize("changes", [{}, {"q2_pie": "bank"}, {"q16_risks": "yes"}, {"q4_group": "parent", "q4_consolidates": "yes", "q4_other_auditors": "no"}])
def test_once_complete_it_is_exactly_the_conclusion(changes):
    answers = {**PLAIN, **changes}
    assert answered_count(answers) == 19
    assert provisional(answers) == conclude(answers)


def test_a_parent_without_its_sub_answers_is_not_answered():
    answers = {**PLAIN, "q4_group": "parent"}
    assert answered_count(answers) == 18
