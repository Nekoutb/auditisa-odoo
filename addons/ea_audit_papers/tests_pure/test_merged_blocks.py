"""P7.1 into P1.4 Part D and S6.2 into S6.1 Part E (owner's decision of 2026-11-16): a block
that folds to one line on one answer, or on a fact the server sends with the auto values."""

from services import load_definition, paper_progress, required_keys, resolve_definition, unanswered_keys

P14_BLOCK = ["tcwg_is_mgmt", "tcwg_who", "tcwg_planned", "tcwg_independence", "tcwg_form", "tcwg_when", "tcwg_response"]
S61_BLOCK = ["dir_review_areas", "dir_supervision", "dir_consult"]


def resolved(code):
    return resolve_definition(load_definition(code), "current", "SA")


def test_p14_asks_the_governance_block_until_answered():
    definition = resolved("P1.4")
    # the planning communication block, last of the paper, folds on one answer
    assert definition["sections"][-1]["collapse"]["key"] == "tcwg_is_mgmt"
    assert required_keys(definition)[-len(P14_BLOCK) - 1:-1] == P14_BLOCK
    assert set(P14_BLOCK) <= set(unanswered_keys(definition, {}))


def test_management_as_governance_folds_p14_to_one_line():
    definition = resolved("P1.4")
    folded = unanswered_keys(definition, {"tcwg_is_mgmt": "yes"})
    assert not set(P14_BLOCK) & set(folded)
    open_block = unanswered_keys(definition, {"tcwg_is_mgmt": "no"})
    assert set(P14_BLOCK[1:]) <= set(open_block)
    full = paper_progress(definition, {})["total"]
    assert paper_progress(definition, {"tcwg_is_mgmt": "yes"}) == {"done": 1, "total": full - 6}


def test_s61_direction_block_and_sole_practitioner():
    definition = resolved("S6.1")
    part_e = definition["sections"][-1]
    assert part_e["titleEn"].startswith("Part E")
    assert [f["key"] for f in part_e["fields"] if f["kind"] == "auto"] == ["dir_briefing"]
    assert set(S61_BLOCK) <= set(unanswered_keys(definition, {"dir_sole": "no"}))
    assert "dir_briefing" not in required_keys(definition)
    assert not set(S61_BLOCK) & set(unanswered_keys(definition, {"dir_sole": "yes"}))


def test_no_reference_to_the_merged_papers_left_in_their_heirs():
    for code in ("P1.4", "S6.1"):
        text = str(load_definition(code))
        assert "P7.1" not in text and "S6.2" not in text, code


def test_without_values_nothing_folds():
    definition = resolved("P1.4")
    assert required_keys(definition) == required_keys(definition, None)
    assert set(P14_BLOCK) <= set(required_keys(definition))
