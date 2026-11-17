"""Which answers a paper needs, and which it has. No Odoo import.

Ports lib/papers/types.ts (paperKeys, requiredKeys, keyAnswered, unansweredKeys) and
lib/working-papers.ts (paperComplete, paperProgress, paperMissing). Every function
takes a RESOLVED definition: requiredKeys depends on the legal form, through the
`forms` filter. `values` maps a storage key to its text; a missing key, None and
blank text all mean "no answer".

Storage keys (kept stable so that migrated answers keep working):
    p_<k>      a procedure's result       p_<k>_na  "na" when not applicable
    p_<k>_x    why it is not applicable
    q_<k>      yes / no / na              q_<k>_x   the explanation of a no or an na
    c_<i>      a conclusion, yes / no     c_<i>_x   the explanation of a no
    other      an input or select field   key_findings  on every paper, never required
"""

from .layout import CONCLUSION_KEY, SUMMARY_KEY, is_converted, missing_sources, new_keys, proc_answered, source_key

NA = "na"
SUMMARY_TITLE_EN = "Summary of work performed"
SUMMARY_TITLE_FR = "Synthèse des travaux réalisés"

# ECMAScript String.prototype.trim. Not str.strip(), which also removes U+001C-U+001F
# and U+0085 and keeps U+FEFF: an "answer" of U+FEFF would count here and not there.
_JS_WHITESPACE = (
    "\t\n\x0b\x0c\r \xa0          "
    "      　﻿"
)

# Screens that are a structured board: the questionnaire is never shown (documents.ts).
EMBED_ONLY_PAPERS = frozenset({"S1.2", "S1.3", "S2.1", "S2.2"})


def js_trim(text):
    return text.strip(_JS_WHITESPACE)


def proc_key(key):
    return "p_%s" % key


def proc_na_key(key):
    return "p_%s_na" % key


def proc_why_key(key):
    return "p_%s_x" % key


def yn_key(key):
    return "q_%s" % key


def yn_why_key(key):
    return "q_%s_x" % key


def concl_key(index):
    return "c_%d" % index


def concl_why_key(index):
    return "c_%d_x" % index


def _typed(field):
    return field["kind"] in ("input", "select")


def _sections(definition):
    return definition.get("sections") or []


def paper_keys(definition):
    """Every key a paper can persist: what a save may write."""
    keys = {"key_findings"}
    for field in definition.get("fields") or []:
        if _typed(field):
            keys.add(field["key"])
    for section in _sections(definition):
        kind = section["kind"]
        if kind == "fields":
            keys.update(f["key"] for f in section["fields"] if _typed(f))
        elif kind == "proc":
            for proc in section["procs"]:
                keys.update((proc_key(proc["key"]), proc_na_key(proc["key"]), proc_why_key(proc["key"])))
        elif kind == "yn":
            for item in section["items"]:
                keys.update((yn_key(item["key"]), yn_why_key(item["key"])))
    for index in range(len(definition.get("conclEn") or [])):
        keys.update((concl_key(index), concl_why_key(index)))
    return keys | new_keys(definition)


# Roll forward (owner 2026-11-16): papers that only conclude, attest or close the year (the
# partner's conclusion, the EQR, points forward, the archive checklist) start again empty.
NOT_CARRIED_PAPERS = ("C4.1", "C4.2", "C6.1", "C6.2")


def carried_answer_keys(definition):
    """What a roll-forward carries of a paper: every answer key, except this year's record of the
    work and its conclusion (a procedure's done / N/A / why, the conclusion boxes)."""
    keys = paper_keys(definition)
    for section in _sections(definition):
        if section["kind"] == "proc":
            for proc in section["procs"]:
                keys -= {proc_key(proc["key"]), proc_na_key(proc["key"]), proc_why_key(proc["key"])}
    for index in range(len(definition.get("conclEn") or [])):
        keys -= {concl_key(index), concl_why_key(index)}
    return keys - new_keys(definition)


def section_collapsed(section, values):
    """A block that folds to one line on one answer (owner's decision of 2026-11-16): the
    section's ``collapse`` names the key and the value. ``values`` may carry the paper's auto
    values too, so a fact the system knows (a team of one) can fold a block as well."""
    rule = section.get("collapse")
    if not rule or values is None:
        return False
    return _value(values, rule["key"]) == rule["value"]


def _section_fields(section, values):
    """The typed fields of a fields section that still ask for an answer."""
    if section_collapsed(section, values):
        return [f["key"] for f in section["fields"] if _typed(f) and f["key"] == section["collapse"]["key"]]
    # a converted paper may offer a box nobody has to fill (services/layout.py, ``optional``)
    return [f["key"] for f in section["fields"] if _typed(f) and not f.get("optional")]


def required_keys(definition, values=None):
    """The fields the preparer must complete, in paper order. With ``values``, the fields of
    a folded block are left out."""
    out = [f["key"] for f in definition.get("fields") or [] if _typed(f)]
    for section in _sections(definition):
        kind = section["kind"]
        if kind == "fields":
            out.extend(_section_fields(section, values))
        elif kind == "proc":
            out.extend(proc_key(p["key"]) for p in section["procs"])
        elif kind == "yn":
            out.extend(yn_key(i["key"]) for i in section["items"])
    out.extend(concl_key(i) for i in range(len(definition.get("conclEn") or [])))
    if is_converted(definition):
        if definition.get("_summary"):
            out.append(SUMMARY_KEY)
        out.append(CONCLUSION_KEY)
    return out


def _value(values, key):
    value = values.get(key)
    return js_trim(value) if value is not None else ""


def _proc_of(definition, key):
    for section in _sections(definition):
        if section["kind"] == "proc":
            for proc in section["procs"]:
                if proc_key(proc["key"]) == key:
                    return proc
    return None


def _is_proc_key(definition, key):
    return _proc_of(definition, key) is not None


def _field_when(definition, key):
    """The {"key", "value"} condition under which a typed field is asked, or None."""
    fields = list(definition.get("fields") or [])
    for section in _sections(definition):
        if section["kind"] == "fields":
            fields.extend(section["fields"])
    for field in fields:
        if field.get("key") == key and field.get("when"):
            return field["when"]
    return None


def key_answered(definition, key, values):
    """A factor or a procedure marked N/A is an answer only with its reason (F040). A field
    asked only under a condition (P1.5's reviewer, when the firm appoints one) needs no answer
    while the condition is not met."""
    when = _field_when(definition, key)
    if when and _value(values, when["key"]) != when["value"]:
        return True
    if key.startswith("q_"):
        answer = _value(values, key)
        if answer == NA:
            return len(_value(values, "%s_x" % key)) > 0
        return len(answer) > 0
    proc = _proc_of(definition, key) if key.startswith("p_") else None
    if proc is not None and definition.get("_depth"):
        # a converted paper, shaped for the engagement's depth (services/layout.py)
        return proc_answered(proc, values, bool(definition.get("_warnings")))
    if proc is not None:
        if _value(values, "%s_na" % key) == NA:
            return len(_value(values, "%s_x" % key)) > 0
        return len(_value(values, key)) > 0
    return len(_value(values, key)) > 0


def unanswered_keys(definition, values):
    """The required keys still without an answer, in paper order."""
    return [k for k in required_keys(definition, values) if not key_answered(definition, k, values)]


def paper_complete(definition, values):
    return not unanswered_keys(definition, values)


def paper_progress(definition, values):
    """Answered fields over required fields, as {"done": n, "total": n}."""
    total = len(required_keys(definition, values))
    return {"done": total - len(unanswered_keys(definition, values)), "total": total}


def paper_missing(definition, values):
    """What still stops a signature: the unanswered keys, then every unexplained "No"
    of a factor and of a conclusion, as the key of the missing explanation."""
    missing = unanswered_keys(definition, values)
    for section in _sections(definition):
        if section["kind"] != "yn":
            continue
        for item in section["items"]:
            if _value(values, yn_key(item["key"])) == "no" and not _value(values, yn_why_key(item["key"])):
                missing.append(yn_why_key(item["key"]))
    for index in range(len(definition.get("conclEn") or [])):
        if _value(values, concl_key(index)) == "no" and not _value(values, concl_why_key(index)):
            missing.append(concl_why_key(index))
    missing.extend(missing_sources(definition, values))
    return missing


def completeness_exempt(code, has_bespoke, converted=False):
    """Tasks whose screen is not the questionnaire, so a signature does not read
    paper_missing (documents.ts completenessExempt). A converted paper of a board (S1.2, S1.3:
    the tool's card, then its own tasks) is read like any other paper."""
    if converted and code in EMBED_ONLY_PAPERS:
        return False
    return code.startswith("E4.") or code == "P7.2" or code in EMBED_ONLY_PAPERS or not has_bespoke


def missing_parts(definition, values):
    """The parts of a paper that still stop a signature, in paper order, as
    {"en", "fr", "keys"}: what paper-incomplete names."""
    missing = set(paper_missing(definition, values))
    parts = []

    def part(title_en, title_fr, keys):
        hit = [k for k in keys if k in missing]
        if hit:
            parts.append({"en": title_en, "fr": title_fr, "keys": hit})

    part("Questionnaire", "Questionnaire", [f["key"] for f in definition.get("fields") or [] if _typed(f)])
    for section in _sections(definition):
        kind = section["kind"]
        if kind == "fields":
            keys = [f["key"] for f in section["fields"] if _typed(f)]
        elif kind == "proc":
            keys = [k for p in section["procs"] for k in (proc_key(p["key"]), source_key(p["key"]))]
        else:
            keys = [k for i in section["items"] for k in (yn_key(i["key"]), yn_why_key(i["key"]))]
        part(section["titleEn"], section["titleFr"], keys)
    if is_converted(definition):
        part(SUMMARY_TITLE_EN, SUMMARY_TITLE_FR, [SUMMARY_KEY])
    count = len(definition.get("conclEn") or [])
    extra = [CONCLUSION_KEY] if is_converted(definition) else []
    part("Conclusion", "Conclusion", [k for i in range(count) for k in (concl_key(i), concl_why_key(i))] + extra)
    return parts


# eqrDeterminationFields: q_eqr of the older paper, and the Part B criteria P1.5 asked until
# 2026-11-16. They decide only on a file where the firm has not yet recorded its decision.
EQR_LEGACY_KEYS = tuple(
    ["q_eqr"]
    + [yn_key(k) for k in ("listed", "law", "pie", "high_risk", "first_year", "complexity", "capital", "monitor", "policy")]
)
EQR_DECISION = "decision"


def eqr_decided(values):
    """Owner's ruling of 2026-11-16: appointing a quality reviewer is always the firm's
    decision, recorded on P1.5. A file saved before that ruling has no decision yet; its
    old criteria answers keep deciding until one is recorded, so nothing changes silently."""
    decision = (values.get(EQR_DECISION) or "").strip()
    if decision:
        return decision == "appoint"
    return any((values.get(key) or "").strip() == "yes" for key in EQR_LEGACY_KEYS)
