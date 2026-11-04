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

NA = "na"

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
    return keys


def required_keys(definition):
    """The fields the preparer must complete, in paper order."""
    out = [f["key"] for f in definition.get("fields") or [] if _typed(f)]
    for section in _sections(definition):
        kind = section["kind"]
        if kind == "fields":
            out.extend(f["key"] for f in section["fields"] if _typed(f))
        elif kind == "proc":
            out.extend(proc_key(p["key"]) for p in section["procs"])
        elif kind == "yn":
            out.extend(yn_key(i["key"]) for i in section["items"])
    out.extend(concl_key(i) for i in range(len(definition.get("conclEn") or [])))
    return out


def _value(values, key):
    value = values.get(key)
    return js_trim(value) if value is not None else ""


def _is_proc_key(definition, key):
    for section in _sections(definition):
        if section["kind"] == "proc" and any(proc_key(p["key"]) == key for p in section["procs"]):
            return True
    return False


def key_answered(definition, key, values):
    """A factor or a procedure marked N/A is an answer only with its reason (F040)."""
    if key.startswith("q_"):
        answer = _value(values, key)
        if answer == NA:
            return len(_value(values, "%s_x" % key)) > 0
        return len(answer) > 0
    if key.startswith("p_") and _is_proc_key(definition, key):
        if _value(values, "%s_na" % key) == NA:
            return len(_value(values, "%s_x" % key)) > 0
        return len(_value(values, key)) > 0
    return len(_value(values, key)) > 0


def unanswered_keys(definition, values):
    """The required keys still without an answer, in paper order."""
    return [k for k in required_keys(definition) if not key_answered(definition, k, values)]


def paper_complete(definition, values):
    return not unanswered_keys(definition, values)


def paper_progress(definition, values):
    """Answered fields over required fields, as {"done": n, "total": n}."""
    total = len(required_keys(definition))
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
    return missing


def completeness_exempt(code, has_bespoke):
    """Tasks whose screen is not the questionnaire, so a signature does not read
    paper_missing (documents.ts completenessExempt)."""
    return code.startswith("E4.") or code == "P7.2" or code in EMBED_ONLY_PAPERS or not has_bespoke
