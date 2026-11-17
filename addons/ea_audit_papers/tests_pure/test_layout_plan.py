"""The plan group's papers in the layout of 2026-11-17 (P1.1-P5.2, P4.2's control environment
in P4.1): every one converted, short English tips, standard answers where a task can close by
exception, hooks that exist in the tools, and the index hash following the definition."""
import hashlib
import json
import pathlib
import re

import pytest

from services import (
    all_paper_keys,
    depth_of,
    is_converted,
    isa_links,
    load_definition,
    load_index,
    load_isa_links,
    resolve_definition,
)

ADDON = pathlib.Path(__file__).resolve().parent.parent
MODELS = ADDON.parent / "ea_audit_tools" / "models"
HOOKS = "".join(path.read_text(encoding="utf-8") for path in sorted(MODELS.glob("paper_hooks*.py")))
PLAN = ("P1.1", "P1.2", "P1.3", "P1.4", "P2.1", "P2.2", "P2.3", "P3.1", "P3.2", "P4.1", "P4.3", "P5.1", "P5.2")
NEVER_LIGHT = ("P1.1", "P2.1", "P5.1", "P5.2")
# French or local terms an English tip must not carry (the French tips may)
NOT_ENGLISH = re.compile(
    r"\b(CNPS|DSF|TAFIRE|AGE|RCCM|OD|lettre|soutien|balance des comptes|grand livre|commissaire|procès-verbal|"
    r"révélation|caisse|chef comptable|Sage|SAARI|brouillard)\b|[àâçéèêëîïôûùœ]",
    re.IGNORECASE,
)


def resolved(code):
    return resolve_definition(load_definition(code), "current", "SA")


def procs(definition):
    return [p for s in definition["sections"] if s["kind"] == "proc" for p in s["procs"]]


def items(definition):
    return [i for s in definition["sections"] if s["kind"] == "yn" for i in s["items"]]


def fields(definition):
    return [f for s in definition["sections"] if s["kind"] == "fields" for f in s["fields"]]


@pytest.mark.parametrize("code", PLAN)
def test_the_paper_is_converted(code):
    definition = resolved(code)
    assert is_converted(definition) and definition["objectiveFr"]
    assert definition["tools"] and all(t["action"].startswith("action_tool_") for t in definition["tools"])
    assert definition["links"] and definition["conclStdEn"] and definition["conclStdFr"]
    assert [s["titleEn"] for s in definition["sections"]][:2] == ["Tasks required", "Conclusion: statements"]
    text = json.dumps(load_definition(code), ensure_ascii=False)
    assert "tipEn" not in text and "srcEn" not in text and "Part A" not in text


@pytest.mark.parametrize("code", PLAN)
def test_tasks_are_short_with_english_tips_and_standard_answers(code):
    definition = resolved(code)
    never_light = code in NEVER_LIGHT or definition.get("neverLight")
    for proc in procs(definition):
        where = (code, proc["key"])
        assert proc["shortEn"] and proc["shortFr"] and proc["isa"], where
        tips_en, tips_fr = proc.get("tipsEn") or [], proc.get("tipsFr") or []
        assert len(tips_en) <= 3 and len(tips_fr) == len(tips_en), where
        for tip in tips_en:
            assert len(tip) <= 120 and not NOT_ENGLISH.search(tip), (where, tip)
        if never_light or proc.get("neverLight") or proc.get("toolDone"):
            continue
        assert proc.get("stdEn") and proc.get("stdFr") and proc.get("sourceHint"), where


@pytest.mark.parametrize("code", PLAN)
def test_statements_and_boxes_point_at_real_tasks(code):
    definition = resolved(code)
    keys = {p["key"] for p in procs(definition)}
    for item in items(definition):
        assert "tasks" in item and set(item["tasks"]) <= keys, (code, item["key"])
        # the old "(procedure 3)" pointers gave way to the tasks list
        assert not re.search(r"\(proc[ée]dures? \d", item["en"] + item["fr"]), (code, item["key"])
    field_keys = {f["key"] for f in fields(definition)}
    for proc in procs(definition):
        assert set(proc.get("fieldKeys") or []) <= field_keys, (code, proc["key"])


@pytest.mark.parametrize("code", PLAN)
def test_every_hook_named_exists_in_the_tools(code):
    definition = load_definition(code)
    names = [("card", definition.get("toolCard"))]
    names += [("done", p.get("toolDone")) for p in procs(definition)]
    names += [("check", i.get("autoCheck")) for i in items(definition)]
    for kind, name in names:
        if name:
            assert "def _ea_hook_%s_%s(self)" % (kind, re.sub(r"[.-]", "_", name)) in HOOKS, (code, kind, name)


@pytest.mark.parametrize("code", PLAN)
def test_index_hash_follows_the_definition(code):
    definition = load_definition(code)
    expected = hashlib.sha256(
        json.dumps(definition, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert load_index()["papers"][code]["definition_hash"] == expected


@pytest.mark.parametrize("code", PLAN)
def test_objective_links_open_the_iaasb_pages(code):
    for link in isa_links(resolved(code), load_isa_links()):
        assert str(link["url"]).startswith("https://"), (code, link)


def test_never_light_papers_stay_in_full_documentation():
    for code in NEVER_LIGHT:
        assert depth_of(resolved(code), code, "very_simple", {}) == ("complex", "never_light"), code
    assert depth_of(resolved("P4.1"), "P4.1", "very_simple", {}) == ("very_simple", None)


def test_p41_holds_the_control_environment_of_p42():
    p41 = all_paper_keys(load_definition("P4.1"))
    for key in ("tone", "oversight", "structure", "competence", "pressure"):
        assert "p_%s" % key in p41
    for key in ("culture", "oversight", "segregation", "competence", "no_pressure", "foundation"):
        assert "q_%s" % key in p41
    # P4.1's own answers keep their keys
    assert {"p_risk_process", "p_deficiencies", "q_all_components", "q_communicated"} <= p41
    # the reader never sees P4.2; only the merge mark (absorbedFrom) names it, for older files
    assert "P4.2" not in json.dumps(load_definition("P4.1"), ensure_ascii=False).replace('"absorbedFrom": "P4.2"', "")
    # P4.2 stays readable for the files that hold it
    assert not is_converted(load_definition("P4.2"))


def test_keys_read_elsewhere_are_kept():
    # the acceptance gate reads P1.1's rating and its two conclusions; S6.1 reads P5.2's partner answer
    p11 = all_paper_keys(load_definition("P1.1"))
    assert {"rating", "c_0", "c_1"} <= p11
    assert {"profile_first_year", "profile_level"} <= {f["key"] for f in fields(load_definition("P1.1"))}
    assert "q_partner" in all_paper_keys(load_definition("P5.2"))
    # P1.3 shows the engagement's framework as an auto field (ea_audit_tools fills it)
    assert {"framework": "auto"}.items() <= {f["key"]: f["kind"] for f in fields(load_definition("P1.3"))}.items()


def test_p51_tasks_closed_by_the_risk_register():
    definition = load_definition("P5.1")
    done = {p["key"]: p.get("toolDone") for p in procs(definition)}
    assert done["revenue"] == "plan_fraud.revenue" and done["override"] == "plan_fraud.override"
    assert load_definition("P3.2")["toolCard"] == "plan_analytics"


# Owner's decision of 2026-11-17: no abbreviations in English text (French may keep its terms).
ABBREVIATIONS = re.compile(
    r"\b(SCOTs?|WCGWs?|ITGCs?|ToC|ToD|JEs?|EQR|TCWG|NOCLAR|SAD|CRA|TB|GL|FS|Prelim|vs|CEO|CFO|MD|HR|AGO|AGE|AGM|EGM|"
    r"AUSCGIE|RCCM|PEP)\b|N/A|&"
)


def _english_strings(value, english=True):
    if isinstance(value, str):
        if english:
            yield value
    elif isinstance(value, list):
        for entry in value:
            yield from _english_strings(entry, english)
    elif isinstance(value, dict):
        for key, entry in value.items():
            yield from _english_strings(entry, english and key != "fr" and not key.endswith("Fr"))


@pytest.mark.parametrize("code", PLAN)
def test_english_text_spells_terms_out(code):
    for text in _english_strings(load_definition(code)):
        assert not ABBREVIATIONS.search(text), (code, text)
