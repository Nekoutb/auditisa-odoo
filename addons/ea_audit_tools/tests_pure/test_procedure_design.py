"""Procedure design (owner's mock-ups of 2026-11-16): the library as data, and the rules that pick
the mandatory procedures, suggest the alternatives and say when an account's design is complete."""
import json
import os

import pytest

from services.assertions import ASSERTIONS
from services.procedure_design import covered, dataset_kind, design_state, is_locked, sample_mode, suggest, suggestion_level

LIBRARY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "procedure_library.json")


@pytest.fixture(scope="module")
def library():
    with open(LIBRARY, encoding="utf-8") as handle:
        return {item["code"]: item for item in json.load(handle)}


def test_the_library_holds_both_languages_and_known_values(library):
    assert len(library) == 59
    assert sum(1 for item in library.values() if item["kind"] == "MSP") == 26
    for code, item in library.items():
        assert code.startswith(item["cycle"] + "-"), code
        assert item["kind"] in ("MSP", "ASP"), code
        assert item["assertions"] and set(item["assertions"]) <= set(ASSERTIONS), code
        for key in ("title_en", "title_fr", "summary_en", "summary_fr", "when_en", "when_fr"):
            assert item[key].strip(), (code, key)
        assert set(item["suggest_levels"]) <= {"low", "moderate", "high"}, code
        assert set(item["suggest_assertions"]) <= set(item["assertions"]) | set(ASSERTIONS), code
        assert item["automatable"] in (
            None, "reconciliation", "cutoff_selection", "sample_selection", "confirmation", "count_attendance"), code
        assert bool(item["condition_en"]) == bool(item["condition_fr"]), code
        if item["kind"] == "ASP":
            # every alternative is either suggested by the risk or tied to a condition of the client
            assert item["suggest_levels"] or item["condition_en"], code


def test_only_the_unconditional_mandatory_procedures_are_locked(library):
    assert is_locked(library["E-M1"])
    assert not is_locked(library["F-M2"])  # inventory held by others: only if
    assert not is_locked(library["E-A2"])


def test_covered_keeps_the_relevant_assertions_in_order(library):
    assert covered(library["E-M2"], ["V", "E"]) == ["E", "V"]
    assert covered(library["E-A6"], ["E", "V"]) == []


def test_suggestions_follow_the_combined_risk(library):
    relevant = ["E", "V"]
    assert suggest(library["E-A2"], {"E": "high", "V": "moderate"}, relevant) == {"why": "risk", "assertion": "E", "level": "high"}
    assert suggest(library["E-A2"], {"E": "low", "V": "moderate"}, relevant) == {"why": "risk", "assertion": "V", "level": "moderate"}
    assert suggest(library["E-A2"], {"E": "low", "V": "low"}, relevant) is None
    assert suggest(library["E-A3"], {"E": "minimal"}, relevant) == {"why": "risk", "assertion": "E", "level": "low"}
    assert suggest(library["E-A2"], {"E": "to_assess"}, relevant) is None
    assert suggest(library["E-M1"], {"E": "high"}, relevant) is None


def test_a_control_not_effective_suggests_the_risk_driven_alternatives(library):
    assert suggest(library["E-A8"], {"V": "low"}, ["V"], failed={"V"}) == {"why": "control", "assertion": "V", "level": None}
    # a Low-only alternative is no answer to a failed control
    assert suggest(library["E-A3"], {"E": "moderate"}, ["E"], failed={"E"}) is None
    assert suggest(library["E-A8"], {"V": "low"}, ["V"], failed=set()) is None


def test_suggestion_level():
    assert suggestion_level("minimal") == "low"
    assert suggestion_level("high") == "high"
    assert suggestion_level("to_assess") is None


def test_a_high_risk_needs_an_alternative_before_the_design_is_complete():
    msp = {"kind": "MSP", "assertions": ["E", "V"]}
    state = design_state({"E": "high", "V": "low"}, ["E", "V"], [msp])
    assert state == {"to_assess": [], "missing_asp": ["E"], "complete": False}
    state = design_state({"E": "high", "V": "low"}, ["E", "V"], [msp, {"kind": "ASP", "assertions": ["E"]}])
    assert state["complete"]
    state = design_state({"E": "high"}, ["E"], [msp, {"kind": "custom", "assertions": ["E"]}])
    assert state["complete"]


def test_nothing_is_complete_while_a_risk_is_to_assess():
    state = design_state({"E": "to_assess", "V": "low"}, ["E", "V"], [{"kind": "MSP", "assertions": ["E"]}])
    assert state["to_assess"] == ["E"]
    assert not state["complete"]
    assert not design_state({}, [], [])["complete"]


def test_what_feeds_a_procedure(library):
    assert sample_mode(library["E-M1"]) == "tool"
    assert sample_mode(library["E-A2"]) == "draw"
    # confirmations and the count pick their own items on the working paper
    assert sample_mode(library["E-M2"]) == "tool"
    assert sample_mode(library["F-M1"]) == "tool"
    assert sample_mode(library["E-M4"]) == "none"
    assert dataset_kind(library["E-M2"], "E") == "ar_open_items"
    assert dataset_kind(library["E-M3"], "E") == "journal_entries"
    assert dataset_kind(library["K-M2"], "K") == "fixed_asset_register"
