"""rasGaps and the deliverables rule of lib/planning-ras.ts."""
from services.planning_ras import SECTION_A, SECTION_B, SECTION_C, outstanding, ras_gaps, unready_lines


def answers_to(sections, value="yes"):
    return {item["key"]: value for section in sections for item in section}


def test_the_port_keeps_the_33_lines():
    assert (len(SECTION_A), len(SECTION_B), len(SECTION_C)) == (11, 17, 5)
    assert outstanding({}) == 33


def test_the_partner_needs_both_sections_and_the_two_lower_tiers():
    gaps = ras_gaps(answers_to([SECTION_A, SECTION_B]), {}, [], "partner")
    assert gaps == ["sig_fieldwork", "sig_manager"]
    assert not ras_gaps(answers_to([SECTION_A, SECTION_B]), {"fieldwork": 1, "manager": 1}, [], "partner")


def test_a_no_needs_its_explanation():
    answers = answers_to([SECTION_A])
    answers["a1"] = "no"
    assert ras_gaps(answers, {}, [], "manager") == ["a1_x"]
    answers["a1_x"] = "  "
    assert ras_gaps(answers, {}, [], "manager") == ["a1_x"]
    answers["a1_x"] = "Expliqué."
    assert ras_gaps(answers, {}, [], "manager") == []


def test_an_untouched_deliverable_stops_the_manager_and_the_partner_not_the_fieldwork():
    answers = answers_to([SECTION_A, SECTION_B])
    unready = unready_lines(answers, {"P2.1": "not_started"})
    assert unready == ["a1"]
    assert "deliverables" in ras_gaps(answers, {}, unready, "manager")
    assert ras_gaps(answers, {}, unready, "fieldwork") == []


def test_a_line_answered_na_or_a_task_absent_is_not_unready():
    answers = answers_to([SECTION_A])
    answers["a1"] = "na"
    assert unready_lines(answers, {"P2.1": "not_started"}) == []
    assert unready_lines(answers_to([SECTION_A]), {}) == []
