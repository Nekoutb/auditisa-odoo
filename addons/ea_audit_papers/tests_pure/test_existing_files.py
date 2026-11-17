"""Existing files under the layout of 2026-11-17 (owner's condition: live engagements hold work).

a) A paper concluded before its conversion kept its conclusion under the old keys (c_0, c_1...);
   read time only, the old conclusion shows and counts in the empty new box (and the task answers
   as the summary of a very simple file), and what the conversion added is not required. A paper
   complete before stays complete; P1.1 feeds the acceptance gate.
b) The tasks merged on 2026-11-17 (P4.2 into P4.1, C4.3 into C4.1, C5.8 into E6.3): a file that
   still carries the task does not see its parts in the paper that took it over.
"""
import pytest

from services import (
    CONCLUSION_KEY,
    SUMMARY_KEY,
    acceptance_verdict,
    is_converted,
    legacy_entry,
    legacy_paper,
    legacy_values,
    load_definition,
    paper_for,
    paper_missing,
    resolve_definition,
    shape,
)
from services.definitions import _legacy_table
from services.layout import items_of, procs_of

DEPTHS = ("complex", "non_complex", "very_simple")
MERGED = {"P4.1": "P4.2", "C4.1": "C4.3", "E6.3": "C5.8"}
LEGACY = sorted(_legacy_table())


def _fields(definition):
    out = {f["key"]: f for f in definition.get("fields") or [] if f.get("key")}
    for section in definition.get("sections") or []:
        if section["kind"] == "fields":
            out.update({f["key"]: f for f in section["fields"] if f.get("key")})
    return out


def old_complete(code, definition):
    """The answers of a paper completed on its old text: every answer key it had, answered the
    plain way, the conclusion statements included (Yes)."""
    entry = legacy_entry(code)
    fields = _fields(definition)
    values = {}
    for key in entry["keys"]:
        if key.endswith(("_na", "_x", "_m", "_src")) or key in (CONCLUSION_KEY, SUMMARY_KEY):
            continue
        field = fields.get(key)
        if key.startswith(("q_", "c_")):
            values[key] = "yes"
        elif field and field.get("kind") == "select":
            option = (field.get("options") or [{"value": "yes"}])[0]
            values[key] = option.get("value") if isinstance(option, dict) else str(option)
        else:
            values[key] = "Done, see file."
    return values


def read(code, depth, values, hidden=(), legacy_file=False, lang="en"):
    """The paper as the model reads it (paper._ea_shaped, _ea_gauge_values)."""
    definition = resolve_definition(load_definition(code), "current", "SA")
    entry = legacy_entry(code)
    legacy = legacy_paper(definition, entry, values, legacy_file)
    statements = resolve_definition({"conclEn": entry["conclEn"], "conclFr": entry["conclFr"]}, "current", "SA")
    shown = legacy_values(definition, statements, values, lang) if legacy else {}
    gauge = {**values, **shown}
    shaped = shape(definition, code, depth, gauge, (), {}, hidden_sources=hidden,
                   legacy_keys=entry["keys"] if legacy else None)
    return shaped, gauge, shown


def test_the_legacy_table_covers_every_converted_paper_that_had_conclusions():
    assert len(LEGACY) >= 60
    for code in LEGACY:
        assert is_converted(load_definition(code)), code
        assert legacy_entry(code)["conclEn"], code


@pytest.mark.parametrize("code", LEGACY)
@pytest.mark.parametrize("depth", DEPTHS)
def test_a_paper_complete_before_stays_complete(code, depth):
    definition = resolve_definition(load_definition(code), "current", "SA")
    values = old_complete(code, definition)
    hidden = {MERGED[code]} if code in MERGED else ()
    shaped, gauge, _shown = read(code, depth, values, hidden, legacy_file=True)
    assert paper_missing(shaped, gauge) == [], code


@pytest.mark.parametrize("code", [code for code in LEGACY if code != "P1.1"])
def test_the_old_conclusion_counts_on_any_scope(code):
    """The old keys can only come from before the conversion: a converted paper never saves them."""
    definition = resolve_definition(load_definition(code), "current", "SA")
    values = old_complete(code, definition)
    hidden = {MERGED[code]} if code in MERGED else ()
    shaped, gauge, shown = read(code, "complex", values, hidden, legacy_file=False)
    assert shown[CONCLUSION_KEY]
    assert paper_missing(shaped, gauge) == [], code


def test_the_old_conclusion_is_shown_with_its_answers():
    values = {"c_0": "yes", "p_inquiry": "Done."}
    _shaped, _gauge, shown = read("P3.2", "complex", values)
    statement = resolve_definition({"conclEn": legacy_entry("P3.2")["conclEn"]}, "current", "SA")["conclEn"][0]
    assert shown[CONCLUSION_KEY] == statement + " Yes"
    _shaped, _gauge, shown = read("P3.2", "complex", {"c_0": "no", "c_0_x": "Resolved with the client."}, lang="fr")
    assert shown[CONCLUSION_KEY].endswith(" Non: Resolved with the client.")


def test_the_summary_of_a_very_simple_file_reads_the_task_answers():
    definition = resolve_definition(load_definition("P3.2"), "current", "SA")
    first, second = procs_of(definition)[:2]
    values = {"c_0": "yes", "p_%s" % first["key"]: "Seen the minutes.",
              "p_%s_na" % second["key"]: "na", "p_%s_x" % second["key"]: "No group."}
    _shaped, _gauge, shown = read("P3.2", "very_simple", values)
    lines = shown[SUMMARY_KEY].split("\n")
    assert lines[0].endswith(": Seen the minutes.")
    assert lines[1].endswith(": Not applicable: No group.")


def test_a_written_box_is_never_replaced():
    values = {"c_0": "yes", CONCLUSION_KEY: "Our own conclusion.", SUMMARY_KEY: "Our summary."}
    _shaped, gauge, shown = read("P3.2", "very_simple", values)
    assert shown == {}
    assert gauge[CONCLUSION_KEY] == "Our own conclusion."


def test_a_new_file_writes_its_conclusion():
    definition = resolve_definition(load_definition("P3.2"), "current", "SA")
    values = {k: v for k, v in old_complete("P3.2", definition).items() if not k.startswith("c_")}
    shaped, gauge, shown = read("P3.2", "complex", values)
    assert shown == {}
    assert CONCLUSION_KEY in paper_missing(shaped, gauge)


def test_what_the_conversion_added_is_required_on_a_new_file():
    """P6.1 gained a task (the revision of materiality): optional on a legacy paper only."""
    definition = resolve_definition(load_definition("P6.1"), "current", "SA")
    values = old_complete("P6.1", definition)
    added = [p["key"] for p in procs_of(definition) if "p_%s" % p["key"] not in legacy_entry("P6.1")["keys"]]
    assert added
    shaped, gauge, _shown = read("P6.1", "complex", values)
    assert paper_missing(shaped, gauge) == []
    fresh = {k: v for k, v in values.items() if not k.startswith("c_")}
    fresh[CONCLUSION_KEY] = "Concluded."
    shaped, gauge, _shown = read("P6.1", "complex", fresh)
    assert "p_%s" % added[0] in paper_missing(shaped, gauge)


def test_p11_keeps_its_statements_and_reads_old_files_on_their_scope():
    definition = resolve_definition(load_definition("P1.1"), "current", "SA")
    values = old_complete("P1.1", definition)
    shaped, gauge, _shown = read("P1.1", "complex", values, legacy_file=True)
    assert paper_missing(shaped, gauge) == []
    # a file of the current scope writes the conclusion of the new layout
    shaped, gauge, _shown = read("P1.1", "complex", values, legacy_file=False)
    assert CONCLUSION_KEY in paper_missing(shaped, gauge)


def test_the_acceptance_gate_reads_an_old_p11_as_complete():
    p11 = paper_for("P1.1")
    values = old_complete("P1.1", p11)
    values["rating"] = "low"
    entry = legacy_entry("P1.1")
    assert not acceptance_verdict(p11, paper_for("P1.2"), values, {}, False)["complete"]
    shown = legacy_values(p11, entry, values) if legacy_paper(p11, entry, values, True) else {}
    verdict = acceptance_verdict(p11, paper_for("P1.2"), {**values, **shown}, {}, False)
    assert verdict["complete"] and verdict["accepted"] and verdict["checks_passed"]


# ---------------------------------------------------------------------------- b) merged tasks

def _parts(definition):
    procs = {p["key"] for p in procs_of(definition)}
    items = {i["key"] for i in items_of(definition)}
    return procs, items, set(_fields(definition))


@pytest.mark.parametrize("target,source", sorted(MERGED.items()))
def test_the_merged_parts_are_marked(target, source):
    definition = load_definition(target)
    marked = [e for s in definition["sections"] for e in s.get("procs", []) + s.get("items", []) + s.get("fields", [])
              if e.get("absorbedFrom")]
    assert marked and {e["absorbedFrom"] for e in marked} == {source}
    # nothing else in the catalogue claims a merged origin
    for code in LEGACY:
        if code not in MERGED:
            other = load_definition(code)
            assert not any(e.get("absorbedFrom") for s in other["sections"]
                           for e in s.get("procs", []) + s.get("items", []) + s.get("fields", [])), code


@pytest.mark.parametrize("target,source", sorted(MERGED.items()))
@pytest.mark.parametrize("depth", DEPTHS)
def test_a_file_with_the_source_task_does_not_see_its_parts(target, source, depth):
    definition = resolve_definition(load_definition(target), "current", "SA")
    absorbed = {e["key"] for s in definition["sections"] for e in s.get("procs", []) + s.get("items", []) + s.get("fields", [])
                if e.get("absorbedFrom") == source}
    shown = shape(definition, target, depth, {}, (), {})
    hidden = shape(definition, target, depth, {}, (), {}, hidden_sources={source})
    seen_procs, seen_items, seen_fields = _parts(shown)
    kept_procs, kept_items, kept_fields = _parts(hidden)
    assert absorbed & (seen_procs | seen_items | seen_fields)
    assert not absorbed & (kept_procs | kept_items | kept_fields)
    assert kept_procs and kept_items
    # the statements no longer point at the hidden tasks
    for item in items_of(hidden):
        assert not set(item.get("tasks") or []) - kept_procs, item["key"]
    missing = paper_missing(hidden, {})
    assert not {"p_%s" % k for k in absorbed} & set(missing)
    assert not {"q_%s" % k for k in absorbed} & set(missing)


def test_p41_without_p42_asks_the_control_environment():
    definition = resolve_definition(load_definition("P4.1"), "current", "SA")
    missing = paper_missing(shape(definition, "P4.1", "complex", {}, (), {}), {})
    assert {"p_tone", "p_pressure", "q_foundation"} <= set(missing)
