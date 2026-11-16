"""Ports of the pure parts of concurrency, batch4-paper-ux, paper-keys-forms and F058."""

import pytest
from services import (
    EQR_C42_KEYS,
    StaleEdit,
    acceptance_verdict,
    all_paper_keys,
    answer_changed,
    field_digest,
    group_siblings,
    is_blank,
    load_definition,
    missing_parts,
    paper_for,
    paper_keys,
    persons_on_save,
    plan_save,
    required_keys,
    same_answer,
)

ALLOWED = {"a", "b", "c"}


def test_all_keys_include_what_the_formless_paper_leaves_out_on_c53():
    formless = paper_keys(paper_for("C5.3"))
    every = all_paper_keys(load_definition("C5.3"))
    assert formless < every
    assert paper_keys(paper_for("C5.3", "current", "SA")) <= every


def test_all_keys_cover_c55_and_every_form_of_every_paper():
    assert paper_keys(paper_for("C5.5", "current", "SA_AG")) <= all_paper_keys(load_definition("C5.5"))


def test_digest_ignores_crlf_only():
    assert field_digest("a\r\nb") == field_digest("a\nb")
    assert field_digest("a") != field_digest("b")
    assert len(field_digest("a")) == 16


def test_blank_and_change_rules():
    assert is_blank(None) and is_blank("") and is_blank("  \n")
    assert not answer_changed(None, "   ")
    assert not answer_changed("", None)
    assert answer_changed("x", "")
    assert not answer_changed("a\r\nb", "a\nb")
    assert answer_changed("a", "a ")
    assert same_answer(" a\r\n", "a")


def test_plan_with_no_lock_writes_every_allowed_key():
    assert plan_save({"a": "1", "z": "9"}, ALLOWED, {"a": "0"}) == ({"a": "1"}, {})


def test_plan_when_stale_without_digests_refuses():
    with pytest.raises(StaleEdit):
        plan_save({"a": "1"}, ALLOWED, {"a": "0"}, None, True)


def test_plan_left_alone_keeps_the_colleagues_text():
    digests = {"a": field_digest("old")}
    assert plan_save({"a": "old"}, ALLOWED, {"a": "theirs"}, digests, True) == ({}, {})


def test_plan_both_changed_holds_back():
    digests = {"a": field_digest("old")}
    assert plan_save({"a": "mine"}, ALLOWED, {"a": "theirs"}, digests, True) == ({}, {"a": "mine"})


def test_plan_both_wrote_the_same_is_no_clash():
    digests = {"a": field_digest("old")}
    assert plan_save({"a": "same\r\n"}, ALLOWED, {"a": "same\n"}, digests, True) == ({"a": "same\r\n"}, {})


def test_plan_a_field_nobody_else_moved_saves():
    digests = {"a": field_digest("old"), "b": field_digest("kept")}
    writes, conflicts = plan_save({"b": "new"}, ALLOWED, {"a": "theirs", "b": "kept"}, digests, True)
    assert writes == {"b": "new"} and not conflicts


def test_plan_a_new_key_from_a_colleague_counts_as_moved_from_blank():
    assert plan_save({"a": "mine"}, ALLOWED, {"a": "theirs"}, {}, True) == ({}, {"a": "mine"})


@pytest.mark.parametrize(
    "stored,posted,expected",
    [
        ({}, {"headcount": "212 salariés au 31/12"}, "ten"),
        ({}, {"headcount": "200"}, "five"),
        ({}, {"headcount": "1 250"}, "ten"),
        ({}, {"headcount": "no figure"}, None),
        ({}, {"persons": "five"}, None),
        ({"headcount": "100", "persons": "five"}, {"headcount": "300", "persons": "five"}, "ten"),
        ({"headcount": "100", "persons": "five"}, {"headcount": "300", "persons": "ten"}, None),
        ({"headcount": "100", "persons": "ten"}, {"headcount": "100", "persons": "ten"}, None),
    ],
)
def test_persons_on_save(stored, posted, expected):
    assert persons_on_save(stored, posted) == expected


def test_eqr_keys_are_on_c42():
    assert EQR_C42_KEYS <= paper_keys(paper_for("C4.2"))


def _answered(code):
    return {k: "yes" if k[:2] in ("q_", "c_") else "Done" for k in required_keys(paper_for(code))}


def test_acceptance_verdict():
    p11, p12 = paper_for("P1.1"), paper_for("P1.2")
    assert acceptance_verdict(p11, p12, {}, {})["complete"] is False
    values = _answered("P1.1")
    verdict = acceptance_verdict(p11, p12, values, {})
    assert verdict["complete"] and verdict["accepted"] and verdict["checks_passed"]
    # the first conclusion answered No is no acceptance
    assert not acceptance_verdict(p11, p12, {**values, "c_0": "no", "c_0_x": "Declined."}, {})["accepted"]
    # P1.2 on the file (a first-year audit, from the questionnaire) needs a completed P1.2
    assert not acceptance_verdict(p11, p12, values, {}, predecessor_required=True)["checks_passed"]
    assert acceptance_verdict(p11, p12, values, _answered("P1.2"), predecessor_required=True)["checks_passed"]
    # an older P1.1 that still holds "change of auditor: yes" keeps its rule
    changed = {**values, "auditor_change": "yes"}
    assert not acceptance_verdict(p11, p12, changed, {})["checks_passed"]


def test_missing_parts_name_the_part_in_both_languages_in_paper_order():
    definition = paper_for("E4.1")
    parts = missing_parts(definition, {})
    assert [p["fr"][:8] for p in parts] == ["Partie A", "Partie B", "Partie C", "Conclusi"]
    assert parts[0]["en"].startswith("Part A")
    assert missing_parts(definition, _answered("E4.1")) == []


def test_missing_parts_name_an_unexplained_no():
    values = _answered("E4.1")
    factor = next(k for k in values if k.startswith("q_"))
    parts = missing_parts(paper_for("E4.1"), {**values, factor: "no"})
    assert [p["keys"] for p in parts] == [["%s_x" % factor]]


def test_missing_parts_on_a_default_paper():
    parts = missing_parts(paper_for("E5.1"), {})
    assert [p["en"] for p in parts] == ["Questionnaire"]


def test_group_siblings_skip_the_task_itself():
    siblings = group_siblings("P1.1")
    assert "P1.2" in siblings and "P1.1" not in siblings
    assert group_siblings("NOPE") == []


def test_p15_reviewer_is_asked_only_when_the_firm_appoints_one():
    """Owner's ruling of 2026-11-16: the firm decides; Part 4 matters only for "appoint"."""
    from services import unanswered_keys

    definition = paper_for("P1.5")
    base = {"other_capital": "not_applies", "other_policy": "not_applies", "decision_why": "Small private company.", "c_0": "yes"}
    assert unanswered_keys(definition, dict(base, decision="none")) == []
    assert unanswered_keys(definition, dict(base, decision="appoint")) == ["reviewer", "eligibility", "points"]
    assert unanswered_keys(definition, dict(base, decision="")) == ["decision"]
    assert unanswered_keys(definition, dict(base, decision="none", decision_why=" ")) == ["decision_why"]
    # the profile's facts, the reminder and the conclusion are shown, never saved
    keys = paper_keys(definition)
    assert {"decision", "decision_why", "other_capital", "other_policy", "reviewer"} <= keys
    assert not {"profile_listed", "p11_rating", "decision_note", "decision_conclusion", "q_listed"} & keys


def test_p15_decision_and_the_answers_given_before_it():
    from services.completeness import eqr_decided

    assert eqr_decided({"decision": "appoint"})
    assert not eqr_decided({"decision": "none"})
    # the decision wins over the old criteria, which stay stored on older files
    assert not eqr_decided({"decision": "none", "q_listed": "yes"})
    assert eqr_decided({"decision": "appoint", "q_listed": "no"})
    # no decision yet: the old answers keep deciding, so nothing changes silently
    assert eqr_decided({"q_pie": "yes"})
    assert eqr_decided({"q_eqr": "yes", "decision": "  "})
    assert not eqr_decided({"q_pie": "no"})
    assert not eqr_decided({})
