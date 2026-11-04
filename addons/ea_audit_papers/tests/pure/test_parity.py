"""Python against the TypeScript's recorded behaviour (scripts/papers/record_parity.ts)."""

import json
import os
import re

import pytest

from services import (
    canonical,
    default_definition,
    digest,
    group_of_task,
    has_bespoke_paper,
    load_definition,
    load_index,
    load_shadowed,
    paper_complete,
    paper_keys,
    paper_missing,
    paper_progress,
    required_keys,
    resolve_definition,
    unanswered_keys,
)
from services import tokens
from services.completeness import proc_key

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "parity")


def _fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


RESOLVED = _fixture("resolved.json")
COMPLETENESS = _fixture("completeness.json")
CASES = _fixture("cases.json")


def _definition(subject_id, kind):
    if kind == "shadowed":
        return load_shadowed(subject_id)
    if kind == "default":
        return default_definition(subject_id)
    return load_definition(subject_id)


def answers(definition, recipe):
    """The interpreter of scripts/papers/record_parity.ts answers()."""
    proc_keys = {
        proc_key(p["key"])
        for section in definition.get("sections") or []
        if section["kind"] == "proc"
        for p in section["procs"]
    }
    out = {}

    def put(key, recipe_key):
        if recipe_key in recipe:
            out[key] = recipe[recipe_key]

    for index, key in enumerate(required_keys(definition)):
        stride = recipe.get("stride")
        if stride and index % stride != 0:
            continue
        if key.startswith("q_"):
            put(key, "q")
            put(key + "_x", "q_x")
        elif key in proc_keys:
            put(key, "p")
            put(key + "_na", "p_na")
            put(key + "_x", "p_x")
        elif re.fullmatch(r"c_[0-9]+", key):
            put(key, "c")
            put(key + "_x", "c_x")
        else:
            put(key, "f")
    return out


def test_fixtures_share_the_exported_baseline():
    commit = load_index()["baseline_commit"]
    assert RESOLVED["baseline_commit"] == commit
    assert COMPLETENESS["baseline_commit"] == commit
    assert CASES["baseline_commit"] == commit


def test_every_definition_is_covered():
    index = load_index()
    subjects = RESOLVED["subjects"]
    assert sum(1 for s in subjects.values() if s["kind"] != "default") == index["counts"]["definitions"]
    assert set(index["papers"]) <= set(subjects)
    assert set(index["tasks_on_default_paper"]) <= set(subjects)
    assert RESOLVED["combinations"] == len(subjects) * len(RESOLVED["editions"]) * len(RESOLVED["forms"])


@pytest.mark.parametrize("subject_id", sorted(RESOLVED["subjects"]))
def test_resolved_output_and_keys(subject_id):
    subject = RESOLVED["subjects"][subject_id]
    keysets = RESOLVED["keysets"]
    unresolved = _definition(subject_id, subject["kind"])
    for edition, by_form in subject["results"].items():
        for form, (expected_hash, required_id, keys_id) in by_form.items():
            resolved = resolve_definition(unresolved, edition, form)
            where = (subject_id, edition, form)
            assert digest(resolved) == expected_hash, where
            assert required_keys(resolved) == keysets[required_id], where
            assert sorted(paper_keys(resolved)) == keysets[keys_id], where
    other = subject["results"]["current"]["OTHER"][0]
    for odd in (None, "XYZ", "sa"):
        assert digest(resolve_definition(unresolved, "current", odd)) == other


@pytest.mark.parametrize("subject_id", sorted(COMPLETENESS["results"]))
def test_completeness_on_answer_sets(subject_id):
    kind = RESOLVED["subjects"][subject_id]["kind"]
    unresolved = _definition(subject_id, kind)
    scenarios = COMPLETENESS["scenarios"]
    for form, rows in COMPLETENESS["results"][subject_id].items():
        definition = resolve_definition(unresolved, COMPLETENESS["edition"], form)
        for recipe, (complete, done, total, lists) in zip(scenarios, rows):
            values = answers(definition, recipe)
            where = (subject_id, form, recipe["name"])
            progress = paper_progress(definition, values)
            assert paper_complete(definition, values) == bool(complete), where
            assert (progress["done"], progress["total"]) == (done, total), where
            produced = [unanswered_keys(definition, values), paper_missing(definition, values)]
            assert digest(produced)[:16] == lists, (where, produced)


def test_strings_and_lookups():
    functions = {
        "resolve_text": tokens.resolve_text,
        "resolve_legal_form_text": tokens.resolve_legal_form_text,
        "has_unresolved_token": tokens.has_unresolved_token,
        "has_unresolved_legal_form_token": tokens.has_unresolved_legal_form_token,
        "applies_to_form": tokens.applies_to_form,
        "task_applies_to_form": tokens.task_applies_to_form,
        "group_of_task": group_of_task,
        "has_bespoke_paper": has_bespoke_paper,
    }
    assert len(CASES["cases"]) > 1000
    for name, args, expected in CASES["cases"]:
        assert functions[name](*args) == expected, (name, args)


def test_canonical_form_is_the_typescript_one():
    assert canonical({"b": ["é", "¶\n\"", 1, True, None], "a": {"z": 1, "y": " \x01"}}) == (
        '{"a":{"y":" \\u0001","z":1},"b":["é","¶\\n\\"",1,true,null]}'
    )
