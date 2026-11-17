"""The completion papers (group compl) in the working-paper layout of 2026-11-17: each one converted,
its tips short and in English on the English side, a standard answer wherever a task can be closed by
exception, its hooks defined in the tools, its index hash current, and its stored answer keys kept."""
import hashlib
import json
import pathlib
import re

import pytest

from services import (
    EQR_C42_KEYS,
    SUMMARY_KEY,
    all_paper_keys,
    depth_of,
    is_converted,
    isa_links,
    load_definition,
    load_index,
    load_isa_links,
    paper_keys,
    paper_for,
    required_keys,
    resolve_definition,
    shape,
)
from services.layout import NEVER_LIGHT_CODES

ADDON = pathlib.Path(__file__).resolve().parent.parent
MODELS = ADDON.parent / "ea_audit_tools" / "models"
HOOKS = "".join(path.read_text(encoding="utf-8") for path in MODELS.glob("paper_hooks*.py"))
FORMS = ("SA", "SA_AG", "SARL", "SAS")

# Every answer key the papers held before the conversion (release/2026-11-23): none may go.
KEPT = {
    "C1.1": "p_accumulate p_classify p_communicate p_reasons p_reassess p_aggregate p_nature p_tcwg p_representation q_accumulated q_reassessed q_immaterial q_nature q_communicated matters effect",
    "C1.2": "p_collect p_conclusion p_judgements p_disagreements p_communicate p_kam q_collected q_concluded q_resolved q_communicated matters effect",
    "C1.3": "p_identify p_consult p_information p_conclusion p_implement p_external q_undertaken q_complete_info q_agreed q_implemented",
    "C2.1": "p_analytics p_tieout p_notes p_adjustments p_presentation p_disclosure p_comparatives p_consistency p_terminology q_ties q_adjustments q_disclosures q_other_info matters effect",
    "C2.2": "p_extend p_inquire p_minutes p_classify p_gc_conclude p_gc_disclosure p_representation q_to_date q_treated q_basis q_no_uncertainty matters effect",
    "C3.1": "p_schedule p_specific p_materiality p_signatories p_draft p_date p_periods p_consistency p_refusal p_update q_complete q_unqualified q_signed q_reviewed q_dated q_consistent q_updated matters effect",
    "C4.1": "p_programme p_signoffs p_outstanding p_misstatements p_consultation p_eqr p_evidence p_assembly q_performed q_signed q_cleared q_eqr q_sufficient",
    "C4.2": "p_required p_scope p_review p_completion q_complete q_resolved",
    "C5.1": "p_evidence p_misstatements p_opinion p_components p_going_concern p_kam p_emphasis p_other_info p_certification p_specific_verifications p_statutory p_date q_sufficient q_unmodified q_components q_going_concern q_certification_form q_specific_done q_dated q_eqr matters effect",
    "C5.3": "p_candidates p_notify p_ordinary_course p_forbidden p_authorisation p_authorisation_ag p_approval p_statutes_sas p_terms p_continuing p_register p_draft p_unauthorised q_notified q_ordinary_excluded q_no_forbidden q_authorised q_abstained q_authorised_ag q_approved q_registered q_complete matters effect",
    "C5.4": "p_verifications p_fs_modifications p_irregularities p_comparison p_changes p_send q_complete q_modifications q_comparison q_sent matters effect",
    "C5.5": "p_facts p_assess p_stage1 p_response p_stage2 p_court p_stage3 p_interaction q_not_engaged q_deadlines q_court_informed q_consistent matters effect",
    "C5.6": "p_facts p_characterise p_advice p_materiality p_decision p_disclosure p_confidentiality q_none q_advice q_decided q_filed matters effect",
    "C5.7": "p_exists p_holding_mode p_intermediary p_agree p_movements p_holders p_pledges p_attest q_kept q_intermediary_reconciled q_agrees q_supported matters effect",
    "C5.9": "p_appointment p_regulator p_division p_common p_cross_review p_differences p_report joint_reason regulator q_written q_joint q_cross q_agreed matters effect",
    "C5.10": "headcount persons amount scope provided p_headcount p_statement p_scope p_reconcile p_consistency p_draft p_review p_provide q_count_right q_scope_complete q_reconciled q_consistent q_form_right q_provided",
    "C5.11": "p_tcwg p_planning p_findings p_independence p_evaluate p_sig_written p_mgmt p_timing p_two_way q_planning q_findings q_independence q_graded q_sig_written q_mgmt q_timely",
    "C6.2": "p_complete p_deadline p_assemble p_lock p_later q_within_60 q_signoffs q_nothing_open q_retention q_mods_logged",
}
COMPL = tuple(KEPT)
# Words the English tips must not carry (the brief's list): French acronyms and French words.
NOT_ENGLISH = re.compile(r"\b(CNPS|DSF|TAFIRE|AGE|AGO|RCCM|lettre|soutien|procès|commissaire|gérant|capitaux)\b|[éèêàçùôî]")


def every_form(code):
    return [resolve_definition(load_definition(code), "current", form) for form in FORMS]


def procs(definition):
    return [p for s in definition["sections"] if s["kind"] == "proc" for p in s["procs"]]


def items(definition):
    return [i for s in definition["sections"] if s["kind"] == "yn" for i in s["items"]]


def fields(definition):
    return [f for s in definition["sections"] if s["kind"] == "fields" for f in s["fields"]]


@pytest.mark.parametrize("code", COMPL)
def test_the_paper_is_converted(code):
    for definition in every_form(code):
        assert is_converted(definition)
        assert definition["objectiveFr"] and definition["isa"] and definition["conclStdEn"] and definition["conclStdFr"]
        assert "conclEn" not in definition
        for tool in definition["tools"]:
            assert tool["action"].startswith("action_tool_") and tool["en"] and tool["fr"] and tool["noteEn"], (code, tool)
        assert [s["kind"] for s in definition["sections"]] == sorted(
            (s["kind"] for s in definition["sections"]), key=("proc", "yn", "fields").index,
        )


@pytest.mark.parametrize("code", COMPL)
def test_tasks_carry_titles_short_tips_and_standard_answers(code):
    light_paper = code not in NEVER_LIGHT_CODES
    for definition in every_form(code):
        light_paper = light_paper and not definition.get("neverLight")
        field_keys = {f["key"] for f in fields(definition)}
        for proc in procs(definition):
            where = (code, proc["key"])
            assert proc["shortEn"] and proc["shortFr"] and proc["isa"], where
            assert not {"tipEn", "tipFr", "srcEn", "srcFr"} & set(proc), where
            tips_en, tips_fr = proc.get("tipsEn") or [], proc.get("tipsFr") or []
            assert 1 <= len(tips_en) <= 3 and len(tips_fr) == len(tips_en), where
            for tip in tips_en:
                assert not NOT_ENGLISH.search(tip), (where, tip)
            if light_paper and not proc.get("neverLight") and not proc.get("toolDone"):
                assert proc.get("stdEn") and proc.get("stdFr") and proc.get("sourceHint"), where
            assert set(proc.get("fieldKeys") or []) <= field_keys, where
        keys = {p["key"] for p in procs(definition)}
        for item in items(definition):
            # a task of another legal form drops out with it: the statement keeps at least one of its own
            assert item.get("tasks") and set(item["tasks"]) & keys, (code, item["key"])
            assert set(item["tasks"]) <= {p["key"] for p in procs(load_definition(code))}, (code, item["key"])
            # the statements point at their tasks, no longer at "procedure 3"
            assert not re.search(r"procedures? \d", item["en"]), (code, item["key"])


@pytest.mark.parametrize("code", COMPL)
def test_every_hook_named_exists_in_the_tools(code):
    definition = load_definition(code)
    names = [("card", definition.get("toolCard"))]
    names += [("done", p.get("toolDone")) for p in procs(definition)]
    names += [("check", i.get("autoCheck")) for i in items(definition)]
    for kind, name in names:
        if name:
            assert "def _ea_hook_%s_%s(self)" % (kind, re.sub(r"[.-]", "_", name)) in HOOKS, (code, kind, name)


@pytest.mark.parametrize("code", COMPL)
def test_index_hash_follows_the_definition(code):
    definition = load_definition(code)
    expected = hashlib.sha256(
        json.dumps(definition, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert load_index()["papers"][code]["definition_hash"] == expected


@pytest.mark.parametrize("code", COMPL)
def test_stored_answers_keep_their_keys(code):
    allowed = all_paper_keys(load_definition(code))
    assert set(KEPT[code].split()) <= allowed, set(KEPT[code].split()) - allowed


def test_isa_links_open_the_iaasb_pages():
    table = load_isa_links()
    for code in COMPL:
        for link in isa_links(resolve_definition(load_definition(code), "current", "SA"), table):
            assert link["url"].startswith("https://"), (code, link)


def test_c41_holds_the_open_points_of_c43():
    definition = paper_for("C4.1", "current", "SA")
    keys = [p["key"] for p in procs(definition)]
    assert keys.index("signoffs") < keys.index("points") < keys.index("points_clear") < keys.index("outstanding")
    # the reader never sees C4.3; only the merge mark (absorbedFrom) names it, for older files
    assert "C4.3" not in json.dumps(definition, ensure_ascii=False).replace('"absorbedFrom": "C4.3"', "")
    cleared = next(i for i in items(definition) if i["key"] == "cleared")
    assert cleared["autoCheck"] == "review_notes_cleared"
    # the open-points list is a box nobody has to fill, shown inside its task
    assert "points_list" not in required_keys(definition)
    assert "C4.1" in json.dumps(paper_for("C6.2", "current", "SA"), ensure_ascii=False)


def test_c42_reviewer_owns_the_review_and_the_conclusion():
    definition = paper_for("C4.2")
    assert EQR_C42_KEYS <= paper_keys(definition)
    reviewer = {p["key"]: p for p in procs(definition) if "p_%s" % p["key"] in EQR_C42_KEYS}
    assert set(reviewer) == {"review", "completion"} and all(p.get("neverLight") for p in reviewer.values())
    assert "conclusion" in EQR_C42_KEYS and "c_0" not in EQR_C42_KEYS


def test_never_light_papers_and_tasks_stay_in_full():
    for code in ("C1.1", "C3.1", "C5.5", "C5.6", "C5.11"):
        definition = paper_for(code, "current", "SA")
        assert depth_of(definition, code, "very_simple", {}) == ("complex", "never_light"), code
    definition = paper_for("C2.2", "current", "SA")
    assert depth_of(definition, "C2.2", "non_complex", {}) == ("non_complex", None)
    shaped = shape(definition, "C2.2", "non_complex", {})
    modes = {p["key"]: p["_mode"] for p in procs(shaped)}
    assert modes["gc_conclude"] == "full" and modes["extend"] == "exception"
    # a "No" on the uncertainty sends the paper back to full documentation
    assert depth_of(definition, "C2.2", "non_complex", {"q_no_uncertainty": "no"}) == ("complex", "no_answer")


def test_very_simple_drops_the_statements_marked_so_and_asks_one_summary():
    definition = shape(paper_for("C2.1", "current", "SA"), "C2.1", "very_simple", {})
    assert [i["key"] for i in items(definition)] == ["ties", "adjustments", "disclosures"]
    assert SUMMARY_KEY in required_keys(definition)
    assert not {"matters", "effect"} & set(required_keys(definition))


def test_c510_keeps_its_boxes_inside_the_tasks_and_links_the_payroll_tool():
    definition = paper_for("C5.10", "current", "SA")
    owned = {key: p["key"] for p in procs(definition) for key in p.get("fieldKeys") or []}
    assert owned == {"headcount": "headcount", "persons": "headcount", "scope": "scope", "amount": "reconcile", "provided": "provide"}
    assert "action_tool_payroll" in [tool["action"] for tool in definition["tools"]]
    assert {"headcount", "persons", "amount", "scope", "provided"} <= set(required_keys(definition))


def test_c11_reads_the_summary_of_audit_differences():
    definition = load_definition("C1.1")
    assert definition["toolCard"] == "sad"
    assert definition["tools"][0]["action"] == "action_tool_sad"
    checks = {i["key"]: i.get("autoCheck") for i in items(definition)}
    assert checks["immaterial"] == "sad_uncorrected"


# Owner's decision of 2026-11-17: no abbreviations in English text (the French side may keep its terms).
ABBREVIATIONS = re.compile(
    r"\b(SCOTs?|WCGW|ITGCs?|ToC|ToD|JEs?|EQR|TCWG|NOCLAR|SAD|CRA|TB|GL|KAM|FS|Rep\.|Prelim|vs\.?|AGO|AGE|AGM|EGM"
    r"|AUSCGIE|TFT|DSF|CNPS|RCCM|N/A)\b|&"
)


def english_strings(value, key=""):
    if isinstance(value, dict):
        for k, v in value.items():
            if not (k.endswith("Fr") or k == "fr"):
                yield from english_strings(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from english_strings(v, key)
    elif isinstance(value, str):
        yield key, value


@pytest.mark.parametrize("code", COMPL)
def test_english_text_spells_out_its_terms(code):
    for key, text in english_strings(load_definition(code)):
        assert not ABBREVIATIONS.search(text), (code, key, text[:120])
