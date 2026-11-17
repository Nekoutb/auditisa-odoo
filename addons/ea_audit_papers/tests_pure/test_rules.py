"""Rules stated directly, independent of the recorded fixtures, plus guards on the data."""

import ast
import glob
import os

from services import (
    completeness_exempt,
    digest,
    has_unresolved_legal_form_token,
    has_unresolved_token,
    key_answered,
    legal_forms,
    load_definition,
    load_index,
    paper_complete,
    paper_for,
    paper_missing,
    paper_progress,
    required_keys,
    standards_editions,
    unanswered_keys,
)
from services.completeness import js_trim
from services.tokens import DATA_DIR

DEF = {
    "fields": [{"key": "top", "kind": "input"}, {"key": "tool", "kind": "auto", "source": "materiality"}],
    "conclEn": ["One", "Two"],
    "sections": [
        {"kind": "proc", "procs": [{"key": "a"}]},
        {"kind": "yn", "items": [{"key": "b"}]},
        {"kind": "fields", "fields": [{"key": "pick", "kind": "select"}, {"key": "p_plain", "kind": "input"}]},
    ],
}
FULL = {"top": "t", "p_a": "done", "q_b": "yes", "pick": "x", "p_plain": "t", "c_0": "yes", "c_1": "yes"}


def test_required_keys_in_paper_order_without_auto_fields():
    assert required_keys(DEF) == ["top", "p_a", "q_b", "pick", "p_plain", "c_0", "c_1"]


def test_complete_and_progress():
    assert paper_complete(DEF, FULL)
    assert paper_progress(DEF, FULL) == {"done": 7, "total": 7}
    assert paper_progress(DEF, {}) == {"done": 0, "total": 7}


def test_na_needs_its_reason():
    assert not key_answered(DEF, "q_b", {"q_b": "na"})
    assert not key_answered(DEF, "q_b", {"q_b": "na", "q_b_x": "  "})
    assert key_answered(DEF, "q_b", {"q_b": "na", "q_b_x": "why"})
    # a result does not rescue a procedure marked N/A with no reason
    assert not key_answered(DEF, "p_a", {"p_a": "done", "p_a_na": "na"})
    assert key_answered(DEF, "p_a", {"p_a_na": "na", "p_a_x": "why"})


def test_a_field_named_like_a_procedure_is_a_field():
    assert key_answered(DEF, "p_plain", {"p_plain": "t", "p_plain_na": "na"})


def test_no_needs_its_explanation_only_for_signature():
    values = dict(FULL, q_b="no", c_1="no")
    assert unanswered_keys(DEF, values) == []
    assert paper_complete(DEF, values)
    assert paper_missing(DEF, values) == ["q_b_x", "c_1_x"]
    assert paper_missing(DEF, dict(values, q_b_x="w", c_1_x="w")) == []


def test_trim_is_ecmascript_not_python():
    assert js_trim("﻿ a \xa0") == "a"
    assert js_trim("\x85") == "\x85"
    assert js_trim("\x1c") == "\x1c"


def test_completeness_exemptions():
    assert completeness_exempt("E4.1", True)
    assert completeness_exempt("P7.2", False)
    assert completeness_exempt("S1.3", True)
    assert completeness_exempt("E5.1", False)
    assert not completeness_exempt("C5.3", True)


def test_forms_filter_and_organs():
    sa = required_keys(paper_for("C5.3", "current", "SA"))
    sarl = required_keys(paper_for("C5.3", "current", "SARL"))
    assert "p_authorisation" in sa and "p_authorisation" not in sarl
    assert "p_approval" in sarl and "p_approval" not in sa
    # three items share the key `above`, one per family of forms: exactly one survives
    for form in legal_forms():
        assert required_keys(paper_for("C5.8", "current", form)).count("q_above") == 1


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)


def test_no_token_survives_resolution_on_any_paper():
    codes = list(load_index()["papers"]) + load_index()["tasks_on_default_paper"]
    for code in codes:
        for edition in standards_editions():
            for form in legal_forms():
                for text in _strings(paper_for(code, edition, form)):
                    assert not has_unresolved_token(text), (code, edition, form, text)
                    assert not has_unresolved_legal_form_token(text), (code, edition, form, text)


def test_definitions_on_disk_match_the_index():
    index = load_index()
    assert index["counts"]["definitions"] == 95
    assert index["counts"]["codes"] == 94 and len(index["papers"]) == 94
    assert index["counts"]["shadowed"] == 1
    for code, meta in index["papers"].items():
        assert digest(load_definition(code)) == meta["definition_hash"], code


def test_draft_marks_are_kept_as_written():
    marks = load_index()["marks"]
    # the converted papers replaced their long draft tips with short ones (layout of 2026-11-17)
    assert marks == {"[Projet]": 40, "[Draft]": 40, "(à valider)": 70}
    found = dict.fromkeys(marks, 0)
    for path in glob.glob(os.path.join(DATA_DIR, "papers*", "*.json")):
        if os.path.basename(path) == "index.json":
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for mark in marks:
            found[mark] += text.count(mark)
    assert found == marks


def test_services_import_no_odoo():
    folder = os.path.join(os.path.dirname(DATA_DIR), "services")
    for path in glob.glob(os.path.join(folder, "*.py")):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(n.split(".")[0] == "odoo" for n in names), path
