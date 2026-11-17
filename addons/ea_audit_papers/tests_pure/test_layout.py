"""The working-paper layout of 2026-11-17: depth by engagement profile, the new definition keys and
the tool hooks the converted papers name (services/layout.py)."""
import hashlib
import json
import pathlib
import re

import pytest

from services.definitions import carried_paper_keys
from services import (
    CONCLUSION_KEY,
    SUMMARY_KEY,
    all_paper_keys,
    by_exception_count,

    depth_of,
    exception_refusal,
    is_converted,
    isa_links,
    load_definition,
    load_index,
    load_isa_links,
    missing_parts,
    paper_keys,
    paper_missing,
    paper_progress,
    required_keys,
    resolve_definition,
    shape,
)

ADDON = pathlib.Path(__file__).resolve().parent.parent
HOOKS = (ADDON.parent / "ea_audit_tools" / "models" / "paper_hooks.py").read_text(encoding="utf-8")
CONVERTED = ("S4.2", "P6.1", "P6.2", "S1.1", "S1.2", "S1.3", "S1.4", "S3.1")


def resolved(code):
    return resolve_definition(load_definition(code), "current", "SA")


def full_values(definition, **extra):
    values = {key: "yes" if key[:2] in ("q_", "c_") else "Done." for key in required_keys(definition)}
    values.update(extra)
    return values


def test_an_older_definition_is_left_as_it_is():
    definition = resolved("P3.1")
    assert not is_converted(definition)
    assert shape(definition, "P3.1", "very_simple", {}) is definition
    assert depth_of(definition, "P3.1", "very_simple", {}) == ("complex", None)
    assert not {k for k in paper_keys(definition) if k.endswith(("_m", "_src"))}


@pytest.mark.parametrize("code", CONVERTED)
def test_converted_papers_carry_the_new_keys(code):
    definition = resolved(code)
    assert is_converted(definition)
    assert definition["objectiveFr"] and definition["isa"] and definition["tools"]
    for section in definition["sections"]:
        for proc in section.get("procs", []):
            assert proc["shortEn"] and proc["shortFr"] and proc["isa"], (code, proc["key"])
            assert len(proc.get("tipsEn") or []) <= 3 and len(proc.get("tipsFr") or []) == len(proc.get("tipsEn") or [])
            if not proc.get("toolDone"):
                assert proc.get("stdEn") and proc.get("stdFr") or proc.get("neverLight"), (code, proc["key"])
            assert "tipEn" not in proc
    keys = paper_keys(definition)
    assert {SUMMARY_KEY, CONCLUSION_KEY} <= keys
    assert not ({SUMMARY_KEY, CONCLUSION_KEY} & carried_paper_keys(load_definition(code)))


@pytest.mark.parametrize("code", CONVERTED)
def test_every_hook_named_exists_in_the_tools(code):
    definition = load_definition(code)
    names = [("card", definition.get("toolCard"))]
    for section in definition["sections"]:
        names += [("done", p.get("toolDone")) for p in section.get("procs", [])]
        names += [("check", i.get("autoCheck")) for i in section.get("items", [])]
    for kind, name in names:
        if name:
            method = "def _ea_hook_%s_%s(self)" % (kind, re.sub(r"[.-]", "_", name))
            assert method in HOOKS, (code, kind, name)


@pytest.mark.parametrize("code", CONVERTED)
def test_index_hash_follows_the_definition(code):
    definition = load_definition(code)
    expected = hashlib.sha256(
        json.dumps(definition, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert load_index()["papers"][code]["definition_hash"] == expected


def test_stored_answers_keep_their_keys():
    # S4.2's work at completion moved to the conclusion under its old key; the proc keys stay
    allowed = all_paper_keys(load_definition("S4.2"))
    assert {"p_indicators", "p_capital", "p_plan", "q_none", "q_capital"} <= allowed
    assert {"p_benchmark", "specific", "revisions"} <= all_paper_keys(load_definition("P6.1"))


def test_isa_links_are_read_in_the_shared_table():
    table = load_isa_links()
    for code in CONVERTED:
        for link in isa_links(resolved(code), table):
            assert link["url"].startswith("https://"), (code, link)
    assert isa_links({"isa": [{"label": "Own", "url": "https://example.org"}]}, table) == [{"label": "Own", "url": "https://example.org"}]
    assert isa_links({"isa": ["ISA 999"]}, table) == [{"label": "ISA 999", "url": False}]


def test_depth_follows_complexity_and_switches_back_to_full():
    definition = resolved("S4.2")
    assert depth_of(definition, "S4.2", "complex", {}) == ("complex", None)
    assert depth_of(definition, "S4.2", False, {}) == ("complex", None)
    assert depth_of(definition, "S4.2", "non_complex", {}) == ("non_complex", None)
    assert depth_of(definition, "S4.2", "very_simple", {}) == ("very_simple", None)
    assert depth_of(definition, "S4.2", "very_simple", {}, ["equity below half"]) == ("complex", "warning")
    assert depth_of(definition, "S4.2", "non_complex", {"q_none": "no"}) == ("complex", "no_answer")
    assert depth_of(dict(definition, neverLight=True), "S4.2", "very_simple", {}) == ("complex", "never_light")
    assert depth_of(definition, "P5.1", "very_simple", {}) == ("complex", "never_light")


def test_no_exceptions_noted_needs_a_source():
    definition = shape(resolved("S4.2"), "S4.2", "non_complex", {})
    values = full_values(definition, p_indicators_m="nx")
    assert "p_indicators_src" in paper_missing(definition, values)
    assert any("p_indicators_src" in part["keys"] for part in missing_parts(definition, values))
    values["p_indicators_src"] = "A2"
    assert "p_indicators_src" not in paper_missing(definition, values)
    assert by_exception_count(definition, values) == 1


def test_a_warning_closes_no_exceptions_noted():
    definition = resolved("S4.2")
    assert exception_refusal(definition, {"p_capital_m": "nx"}, ["equity below half"]) == "exception-blocked"
    assert exception_refusal(definition, {"p_capital_m": "ex"}, ["equity below half"]) is None
    assert exception_refusal(definition, {"p_capital_m": "nx"}, []) is None
    shaped = shape(definition, "S4.2", "non_complex", {}, ["equity below half"])
    assert shaped["_depth"] == "complex"
    values = full_values(shaped, p_capital_m="nx")
    assert "p_capital" in paper_missing(shaped, values)


def test_very_simple_ticks_and_one_summary():
    definition = shape(resolved("S4.2"), "S4.2", "very_simple", {})
    items = [i["key"] for s in definition["sections"] if s["kind"] == "yn" for i in s["items"]]
    assert items == ["none", "assessment"]
    assert SUMMARY_KEY in required_keys(definition)
    fields = [f["key"] for s in definition["sections"] if s["kind"] == "fields" for f in s["fields"]]
    assert "p_plan" not in fields
    values = {"p_%s_m" % p["key"]: "tick" for s in definition["sections"] if s["kind"] == "proc" for p in s["procs"]}
    values.update({"q_none": "yes", "q_assessment": "yes", "conclusion": "No doubt.", "summary": "Met the owner."})
    assert paper_missing(definition, values) == []
    progress = paper_progress(definition, values)
    assert progress["done"] == progress["total"]


def test_a_task_done_in_the_tool_needs_no_input():
    tool = {"benchmark": {"done": True, "result": "Revenue"}, "figure": {"done": False, "result": ""}}
    definition = shape(resolved("P6.1"), "P6.1", "complex", {}, (), tool)
    procs = {p["key"]: p for s in definition["sections"] if s["kind"] == "proc" for p in s["procs"]}
    assert procs["benchmark"]["_mode"] == "tool"
    assert procs["figure"]["_mode"] == "full"
    assert "p_benchmark" not in paper_missing(definition, {})
    assert "p_figure" in paper_missing(definition, {})
    # optional boxes never stop a signature
    assert "specific" not in required_keys(definition)


def test_a_never_light_task_stays_full_in_a_light_paper():
    definition = shape(resolved("S3.1"), "S3.1", "non_complex", {})
    procs = {p["key"]: p for s in definition["sections"] if s["kind"] == "proc" for p in s["procs"]}
    assert procs["significant"]["_mode"] == "full"
    assert procs["fs_level"]["_mode"] == "exception"
