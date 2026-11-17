"""The strategy papers (group "strat") in the working-paper layout of 2026-11-17: S2.1 to S2.5, S4.1,
S4.3, S4.4, S5.1 to S5.4, S5.6 and S6.1 converted, in plain English with no abbreviation, every hook
they name defined in the tools, and every answer stored before the conversion still readable."""
import hashlib
import json
import pathlib
import re

import pytest

from services import (
    SUMMARY_KEY,
    all_paper_keys,
    is_converted,
    isa_links,
    load_definition,
    load_index,
    load_isa_links,
    required_keys,
    resolve_definition,
    shape,
)

ADDON = pathlib.Path(__file__).resolve().parent.parent
MODELS = ADDON.parent / "ea_audit_tools" / "models"
HOOKS = "".join((MODELS / name).read_text(encoding="utf-8") for name in ("paper_hooks.py", "paper_hooks_strat.py", "paper_hooks_je.py"))
STRAT = ("S2.1", "S2.2", "S2.3", "S2.4", "S2.5", "S4.1", "S4.3", "S4.4", "S5.1", "S5.2", "S5.3", "S5.4", "S5.6", "S6.1")

# Owner's request of 2026-11-17: English text says the words out (standard names stay).
ABBREVIATIONS = re.compile(
    r"\b(SCOTs?|WCGWs?|ITGCs?|ToC|ToCs|TCWG|TB|GL|EQR|EQCR|CRA|SAD|PBC|JE|DSF|CNPS|RCCM|DAF|DG|FS|AGM|EGM|DBA|N-1)\b"
    r"|&|\bvs\b\.?|\be\.g\.|\bi\.e\.|\betc\b\."
)
# Tips in English stay English: no French words or local acronyms (the French tips may use them).
FRENCH = re.compile(
    r"[àâçéèêëîïôûùü]|\b(TAFIRE|AGE|lettre|rapprochement|bancaire|grand livre|honoraires|avocat|notaire|fiduciaire|"
    r"relevés?|statuts|caution|aval|fiches? de paie|chef comptable|commissaire|bons? de)\b",
    re.IGNORECASE,
)


def resolved(code):
    return resolve_definition(load_definition(code), "current", "SA")


def procs(definition):
    return [p for s in definition["sections"] if s["kind"] == "proc" for p in s["procs"]]


def english_texts(definition):
    out = [definition["objectiveEn"], definition["conclStdEn"], *definition.get("reqEn", [])]
    for entry in definition["tools"]:
        out += [entry["en"], entry["noteEn"]]
    for section in definition["sections"]:
        out.append(section["titleEn"])
        for proc in section.get("procs", []):
            out += [proc["en"], proc["shortEn"], proc.get("stdEn", ""), proc.get("sourceHint", ""), *proc.get("tipsEn", [])]
        for item in section.get("items", []):
            out.append(item["en"])
        for field in section.get("fields", []):
            out.append(field["labelEn"])
            out += [option["en"] for option in field.get("options", [])]
    return [text for text in out if text]


@pytest.mark.parametrize("code", STRAT)
def test_the_paper_is_converted(code):
    definition = resolved(code)
    assert is_converted(definition)
    assert definition["objectiveFr"] and definition["isa"] and definition["tools"] and definition["links"]
    assert definition["conclStdEn"] and definition["conclStdFr"]
    assert "conclEn" not in definition and "ownsEn" not in definition
    for entry in definition["tools"]:
        assert entry["action"].startswith("action_tool_") and entry["fr"] and entry["noteFr"], (code, entry)
    for proc in procs(definition):
        where = (code, proc["key"])
        assert proc["shortEn"] and proc["shortFr"] and proc["isa"], where
        assert "tipEn" not in proc and "srcEn" not in proc, where
        assert len(proc.get("tipsEn") or []) <= 3, where
        assert len(proc.get("tipsFr") or []) == len(proc.get("tipsEn") or []), where
        if not proc.get("neverLight"):
            # every task that can be closed by exception offers its standard answer
            assert proc.get("stdEn") and proc.get("stdFr"), where


@pytest.mark.parametrize("code", STRAT)
def test_english_has_no_abbreviation_and_the_tips_no_french(code):
    definition = load_definition(code)
    for text in english_texts(definition):
        assert not ABBREVIATIONS.search(text), (code, text)
    for proc in procs(definition):
        for tip in proc.get("tipsEn", []):
            assert not FRENCH.search(tip), (code, proc["key"], tip)


@pytest.mark.parametrize("code", STRAT)
def test_every_hook_named_is_defined_in_the_tools(code):
    definition = load_definition(code)
    names = [("card", definition.get("toolCard"))]
    for section in definition["sections"]:
        names += [("done", p.get("toolDone")) for p in section.get("procs", [])]
        names += [("check", i.get("autoCheck")) for i in section.get("items", [])]
    for kind, name in names:
        if name:
            method = "def _ea_hook_%s_%s(self)" % (kind, re.sub(r"[.-]", "_", name))
            assert method in HOOKS, (code, kind, name)


@pytest.mark.parametrize("code", STRAT)
def test_index_hash_follows_the_definition(code):
    definition = load_definition(code)
    expected = hashlib.sha256(
        json.dumps(definition, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert load_index()["papers"][code]["definition_hash"] == expected


@pytest.mark.parametrize("code", STRAT)
def test_statements_rest_on_tasks_and_boxes_sit_in_tasks(code):
    definition = load_definition(code)
    keys = {p["key"] for p in procs(definition)}
    fields = {f["key"]: f for s in definition["sections"] if s["kind"] == "fields" for f in s["fields"]}
    for section in definition["sections"]:
        for item in section.get("items", []):
            assert set(item.get("tasks", [])) <= keys, (code, item["key"])
    for proc in procs(definition):
        for key in proc.get("fieldKeys", []):
            # a box inside a task is not shown on a very simple file: it cannot be required
            assert fields[key].get("optional"), (code, key)


def test_stored_answers_keep_their_keys():
    expected = {
        "S2.1": {"p_strategy", "p_forced", "p_select", "p_itgc_dep", "p_substantive", "q_every_assertion", "q_itgc_ok"},
        "S2.3": {"p_apps", "p_ddc", "p_common", "apps_register", "risk_register", "ddc_assessment", "q_common"},
        "S2.4": {"p_deficiencies", "tests_register", "exceptions_register", "q_exceptions"},
        "S2.5": {"itgc_state", "evaluations_register", "responses_register", "deficiencies", "p_ladder", "q_wcgw"},
        "S4.1": {"p_tax_social", "p_strategy", "q_legal_letter", "q_carried"},
        "S4.3": {"p_identity", "p_outside", "q_independent"},
        "S5.4": {"rationale", "timing"},
        "S5.6": {"p_opening", "p_governance", "q_assigned", "q_linked"},
        "S6.1": {"p_prior", "direction", "changes", "uses_expert", "uses_service_org", "has_internal_audit",
                 "assess_control_env", "assess_it_env", "dir_review_areas", "dir_supervision", "dir_consult", "q_carried"},
    }
    for code, keys in expected.items():
        assert keys <= all_paper_keys(load_definition(code)), code


def test_isa_links_are_read_in_the_shared_table():
    table = load_isa_links()
    for code in STRAT:
        links = isa_links(resolved(code), table)
        assert links, code
        for link in links:
            assert link["url"] and link["url"].startswith("https://"), (code, link)


def test_identification_of_related_parties_stays_full_in_a_light_paper():
    definition = shape(resolved("S4.3"), "S4.3", "non_complex", {})
    modes = {p["key"]: p["_mode"] for p in procs(definition)}
    assert modes["identity"] == modes["outside"] == "full"
    assert modes["registers"] == "exception"


def test_tasks_done_in_the_tools_need_no_input():
    tool = {"strategy": {"done": True, "result": "set"}, "aggregate": {"done": True, "result": "Support reliance"}}
    for code, key in (("S2.1", "strategy"), ("S2.5", "aggregate")):
        definition = shape(resolved(code), code, "non_complex", {}, (), tool)
        assert {p["key"]: p["_mode"] for p in procs(definition)}[key] == "tool"


def test_very_simple_keeps_the_boxes_that_decide():
    # S2.5's conclusion is read by the combined risk assessment; S6.1's facts bring tasks onto the file
    s25 = shape(resolved("S2.5"), "S2.5", "very_simple", {})
    assert "itgc_state" in required_keys(s25) and SUMMARY_KEY in required_keys(s25)
    s61 = shape(resolved("S6.1"), "S6.1", "very_simple", {})
    assert {"direction", "uses_expert", "assess_it_env"} <= set(required_keys(s61))
    assert "changes" not in required_keys(s61)
    assert s61["sections"][-1]["collapse"]["key"] == "dir_sole"
    items = [i["key"] for s in s61["sections"] if s["kind"] == "yn" for i in s["items"]]
    assert items == ["deadline", "risk_weight", "carried"]


def test_s5_4_design_is_the_criteria_and_settings_of_the_tool():
    definition = load_definition("S5.4")
    assert definition["toolCard"] == "je_testing"
    assert {p["key"]: p["toolDone"] for p in procs(definition)} == {"criteria": "je_criteria", "thresholds": "je_settings"}
    tool = {"criteria": {"done": True, "result": "set"}, "thresholds": {"done": True, "result": "set"}}
    shaped = shape(resolved("S5.4"), "S5.4", "non_complex", {}, (), tool)
    assert {p["_mode"] for p in procs(shaped)} == {"tool"}
    assert {"rationale", "timing"} <= set(required_keys(shaped))
