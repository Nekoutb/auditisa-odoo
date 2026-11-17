"""The execution papers in the layout of 2026-11-17 (group "exec"): E1.1, E1.2, E2.1 and E6.1 to
E6.10. Each is converted, its tips are short and in English on the English side, a task that can be
closed by exception has its standard answer, every hook it names exists, its index hash follows it,
and the answer keys of existing files are still there."""
import hashlib
import json
import pathlib
import re

import pytest

from services import all_paper_keys, is_converted, load_definition, load_index, required_keys, resolve_definition, shape

ADDON = pathlib.Path(__file__).resolve().parent.parent
MODELS = ADDON.parent / "ea_audit_tools" / "models"
HOOKS = "".join((MODELS / name).read_text(encoding="utf-8") for name in ("paper_hooks.py", "paper_hooks_exec.py"))
EXEC = ("E1.1", "E1.2", "E2.1", "E6.1", "E6.2", "E6.3", "E6.4", "E6.5", "E6.6", "E6.7", "E6.8", "E6.9", "E6.10")
# Local words that have an English name: the English tips use the English one.
LOCAL_WORDS = re.compile(r"\b(?:CNPS|DSF|TAFIRE|AGE|RCCM|SOCD|SCOT|IPE|lettre|soutien|procès|commissaire)\b", re.IGNORECASE)
FRENCH_LETTERS = re.compile(r"[àâçéèêëîïôûùœÀÂÇÉÈÊÔ«»]")


def resolved(code):
    return resolve_definition(load_definition(code), "current", "SA")


def procs(definition):
    return [p for s in definition["sections"] if s["kind"] == "proc" for p in s["procs"]]


@pytest.mark.parametrize("code", EXEC)
def test_exec_papers_are_converted(code):
    definition = resolved(code)
    assert is_converted(definition)
    assert definition["objectiveFr"] and definition["isa"] and definition["tools"] and definition["links"]
    assert definition["conclStdEn"] and definition["conclStdFr"]
    assert "conclEn" not in definition
    assert all(isinstance(tool, dict) and tool["action"].startswith("action_tool_") for tool in definition["tools"])
    keys = {p["key"] for p in procs(definition)}
    fields = {f["key"] for s in definition["sections"] if s["kind"] == "fields" for f in s["fields"]}
    for proc in procs(definition):
        assert proc["shortEn"] and proc["shortFr"] and proc["isa"], (code, proc["key"])
        assert not {"tipEn", "tipFr", "srcEn", "srcFr"} & set(proc), (code, proc["key"])
        tips_en, tips_fr = proc.get("tipsEn") or [], proc.get("tipsFr") or []
        assert 1 <= len(tips_en) <= 3 and len(tips_fr) == len(tips_en), (code, proc["key"])
        for tip in tips_en:
            assert len(tip) <= 110, (code, proc["key"], tip)
            assert not LOCAL_WORDS.search(tip) and not FRENCH_LETTERS.search(tip), (code, proc["key"], tip)
        if not proc.get("neverLight"):
            assert proc.get("stdEn") and proc.get("stdFr") and proc.get("sourceHint"), (code, proc["key"])
        assert set(proc.get("fieldKeys") or []) <= fields, (code, proc["key"])
    for section in definition["sections"]:
        assert not section.get("titleEn", "").startswith("Part "), (code, section["titleEn"])
        for item in section.get("items", []):
            assert set(item.get("tasks") or []) <= keys, (code, item["key"])
            assert not re.search(r"\(procedures? ", item["en"]), (code, item["key"])
            if section.get("task") is None:
                assert item.get("tasks"), (code, item["key"])


@pytest.mark.parametrize("code", EXEC)
def test_exec_hooks_exist_in_the_tools(code):
    definition = load_definition(code)
    names = [("card", definition.get("toolCard"))]
    for section in definition["sections"]:
        names += [("done", p.get("toolDone")) for p in section.get("procs", [])]
        names += [("check", i.get("autoCheck")) for i in section.get("items", [])]
    warnings = definition.get("warnings") or []
    names += [("warn", name) for name in ([warnings] if isinstance(warnings, str) else warnings)]
    for kind, name in names:
        if name:
            assert "def _ea_hook_%s_%s(self)" % (kind, re.sub(r"[.-]", "_", name)) in HOOKS, (code, kind, name)


@pytest.mark.parametrize("code", EXEC)
def test_exec_index_hash_follows_the_definition(code):
    definition = load_definition(code)
    expected = hashlib.sha256(json.dumps(definition, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
    assert load_index()["papers"][code]["definition_hash"] == expected


def test_exec_answer_keys_of_existing_files_stay():
    expected = {
        "E1.1": {"p_scope", "p_deficiency", "q_socd", "domain_changes", "it_process", "response"},
        "E1.2": {"p_selection", "p_exceptions", "q_grids", "q_rotation", "exceptions", "carried"},
        "E2.1": {"p_period", "p_conclude", "q_all_interim", "q_failures_fed"},
        "E6.1": {"p_framework", "p_report", "q_none", "q_reporting"},
        "E6.2": {"p_register", "p_disclosure", "q_complete", "q_disclosed"},
        "E6.3": {"p_carry", "p_communicate", "q_no_uncertainty", "q_close_call", "exceptions", "carried"},
        "E6.6": {"p_transactions", "p_classify", "q_period", "q_carried"},
        "E6.8": {"p_deviations", "p_procedures", "q_documented"},
        "E6.10": {"p_tie_n", "p_tie_n1", "p_checklist", "q_n_agrees", "q_not_copied", "q_ohada_A_1", "q_ohada_N_36", "q_ohada_F_7"},
    }
    for code, keys in expected.items():
        assert keys <= all_paper_keys(load_definition(code)), code


def test_e6_3_takes_over_the_equity_check_of_c5_8():
    definition = load_definition("E6.3")
    assert definition["toolCard"] == "going_concern"
    keys = [p["key"] for p in procs(definition)]
    assert {"capital", "capital_procedure"} <= set(keys)
    items = {i["key"]: i for s in definition["sections"] if s["kind"] == "yn" for i in s["items"]}
    assert items["capital"]["autoCheck"] == "going_concern_equity" and items["capital"]["vs"] is False
    assert items["capital_procedure"]["na"] is True
    # the meeting reads in the client's legal form
    text = next(p for p in procs(resolved("E6.3")) if p["key"] == "capital_procedure")["en"]
    assert "[[lf." not in text
    # a warning of the equity check sends the paper back to full documentation
    assert shape(resolved("E6.3"), "E6.3", "non_complex", {}, ["Equity below half."])["_depth"] == "complex"


def test_e6_10_checklist_is_grouped_inside_its_task():
    definition = load_definition("E6.10")
    groups = [s for s in definition["sections"] if s.get("task")]
    assert {s["task"] for s in groups} == {"checklist"}
    assert len(groups) == 12
    rows = [i for s in groups for i in s["items"]]
    assert len(rows) == 126 and len({i["key"] for i in rows}) == 126
    assert all(i["na"] is True for i in rows)
    assert max(len(s["items"]) for s in groups) <= 20
    assert [s["titleEn"].split(" — ")[0] for s in groups] == [
        "Checklist A", "Checklist B", "Checklist C", "Checklist D1", "Checklist D2", "Checklist D3", "Checklist D4",
        "Checklist D5", "Checklist D6", "Checklist D7", "Checklist E", "Checklist F",
    ]
    # the evaluation statements are the conclusion's; the checklist rows stay required answers
    statements = [s for s in definition["sections"] if s["kind"] == "yn" and not s.get("task")]
    assert len(statements) == 1 and len(statements[0]["items"]) == 10
    assert "q_ohada_D_1" in required_keys(resolved("E6.10"))


def test_e6_6_reads_the_next_year_ledger():
    definition = load_definition("E6.6")
    assert definition["toolCard"] == "subsequent"
    assert any(tool["action"] == "action_tool_gl" for tool in definition["tools"])
