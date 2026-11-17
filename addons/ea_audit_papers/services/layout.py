"""The working-paper layout of 2026-11-17 (owner-approved): one page, Objective, Tasks required,
Conclusion and sign-off, and the depth of documentation set by the engagement's complexity.
No Odoo import.

A definition is *converted* when it carries ``objectiveEn``. Only a converted definition gets
the depths and the new answer keys; any other definition reads in full documentation, with the
keys it always had, so that the parity with the platform holds for it.

Definition keys (all optional, backwards compatible):
    objectiveEn / objectiveFr      the Objective, in the words of the standard
    isa                            [{label, url}] or [{label, std}] or ["ISA 570"]: the links of
                                   the Objective, ``std`` read in data/isa_links.json
    tools                          [{action, en, fr, noteEn, noteFr}] (``action`` an engagement
                                   method, action_tool_*); a bare string is the older tool id
    links                          [codes]: the Linked tasks of the rail, in place of the default
    toolCard                       hook name: the read-only "From the <tool>" card
    warnings                       hook name or [names]: flags that force full documentation
    neverLight                     true: always full documentation
    conclStdEn / conclStdFr        the standard conclusion offered in the Conclusion box
procs[i]:
    shortEn / shortFr              the step list's title          isa       the ISA reference
    tipsEn / tipsFr                up to three short bullets (replace tipEn / tipFr)
    stdEn / stdFr                  the standard answer of "No exceptions noted"
    sourceHint                     what the source usually is (placeholder only)
    profiles                       ["complex", "non_complex", "very_simple"], default all
    neverLight                     true: this task stays in full documentation
    toolDone                       hook name: the task is closed in the tool
    fieldKeys                      [keys] of the paper's fields shown inside this task
fields[i] (a fields section):
    optional                       true: a box nobody has to fill
    profiles                       as for a procedure
sections[i] of kind yn:
    task                           a procedure key: the block is that task's checklist, read inside
                                   the task in folding groups (E6.10), not in the conclusion
procs[i], items[i], fields[i]:
    absorbedFrom                   the code of a task merged into this paper on 2026-11-17 (P4.2 into
                                   P4.1, C4.3 into C4.1, C5.8 into E6.3): the part is hidden on a
                                   file that still carries that task, or keeps the scope it was
                                   opened with, so the work stays where it was done
items[i]:
    vs                             false: dropped on a very simple engagement (default true)
    autoCheck                      hook name: "checked by the tool"
    tasks                          [proc keys] the statement rests on (shown as 2.1-2.7)

Answer keys added for converted papers (existing keys never change):
    p_<k>_m     the mark: "nx" no exceptions noted, "ex" exceptions noted, "tick" very simple
    p_<k>_src   the source of a "No exceptions noted"
    summary     "Summary of work performed" (very simple)
    conclusion  the conclusion text

Existing files (owner's condition of 2026-11-17: a paper complete before stays complete). A paper
concluded before its conversion holds its conclusion under the old keys (c_0, c_1...), which the
converted definition no longer asks. Read time only, no answer is rewritten: ``legacy_paper`` tells
such a paper, ``legacy_values`` shows and counts the old conclusion as the conclusion (and the task
answers as the summary of a very simple file) while the new box is empty, and ``shape`` with
``legacy_keys`` does not require what the conversion added to the paper.
"""

import copy

DEPTHS = ("complex", "non_complex", "very_simple")
FULL = "complex"
EXCEPTION = "non_complex"
VERY_SIMPLE = "very_simple"

MARK_NONE = "nx"
MARK_EXCEPTIONS = "ex"
MARK_TICK = "tick"

SUMMARY_KEY = "summary"
CONCLUSION_KEY = "conclusion"

# Owner's list of 2026-11-17: papers never lightened, whatever the profile. Parts of a paper
# (S3.1's significant risks, the identification in S4.3 and E6.2) carry neverLight on the task.
NEVER_LIGHT_CODES = frozenset({"P5.1", "P5.2", "E3.1", "P2.1", "P1.1", "C1.1", "C3.1", "C5.11", "C5.6", "C5.5"})

# Why a light engagement reads a paper in full documentation.
REASON_NEVER_LIGHT = "never_light"
REASON_WARNING = "warning"
REASON_NO_ANSWER = "no_answer"


def is_converted(definition):
    return bool((definition or {}).get("objectiveEn"))


def mark_key(key):
    return "p_%s_m" % key


def source_key(key):
    return "p_%s_src" % key


def procs_of(definition):
    """Every procedure of a definition, in paper order."""
    return [proc for section in definition.get("sections") or [] if section["kind"] == "proc" for proc in section["procs"]]


def items_of(definition):
    return [item for section in definition.get("sections") or [] if section["kind"] == "yn" for item in section["items"]]


def new_keys(definition):
    """The keys a converted definition adds to what a save may write."""
    if not is_converted(definition):
        return set()
    keys = {SUMMARY_KEY, CONCLUSION_KEY}
    for proc in procs_of(definition):
        keys.update((mark_key(proc["key"]), source_key(proc["key"])))
    return keys


def _clean(value):
    return (value or "").strip()


def wanted_depth(complexity):
    """The engagement's complexity, as a depth. A file with none reads in full."""
    return complexity if complexity in DEPTHS else FULL


def depth_of(definition, code, complexity, values, warnings=()):
    """(depth, reason): the depth this paper is documented at, and why a light engagement
    reads it in full. Facts decide whether a task is on the file; complexity decides depth."""
    wanted = wanted_depth(complexity)
    if not is_converted(definition) or wanted == FULL:
        return FULL, None
    if definition.get("neverLight") or code in NEVER_LIGHT_CODES:
        return FULL, REASON_NEVER_LIGHT
    if warnings:
        return FULL, REASON_WARNING
    values = values or {}
    if any(_clean(values.get("q_%s" % item["key"])) == "no" for item in items_of(definition)):
        return FULL, REASON_NO_ANSWER
    return wanted, None


def in_profile(entry, complexity):
    profiles = entry.get("profiles")
    return not profiles or wanted_depth(complexity) in profiles


LIST_OF_KIND = {"proc": "procs", "yn": "items", "fields": "fields"}


def hide_absorbed(definition, hidden_sources):
    """Drops, in place, the parts a merged task brought into this paper (``absorbedFrom``) when
    that task is in ``hidden_sources``, and the references of the statements to them."""
    hidden_sources = set(hidden_sources or ())
    if not hidden_sources:
        return definition
    keep = lambda entry: entry.get("absorbedFrom") not in hidden_sources  # noqa: E731
    gone = set()
    for section in definition.get("sections") or []:
        kind = section["kind"]
        if kind == "proc":
            gone.update(proc["key"] for proc in section["procs"] if not keep(proc))
        if kind in LIST_OF_KIND:
            section[LIST_OF_KIND[kind]] = [entry for entry in section[LIST_OF_KIND[kind]] if keep(entry)]
    if definition.get("fields"):
        definition["fields"] = [field for field in definition["fields"] if keep(field)]
    for item in items_of(definition):
        if item.get("tasks"):
            item["tasks"] = [key for key in item["tasks"] if key not in gone]
    definition["sections"] = [
        section for section in definition.get("sections") or []
        if section["kind"] not in LIST_OF_KIND or section[LIST_OF_KIND[section["kind"]]]
    ]
    return definition


def _legacy_optional(definition, legacy_keys):
    """On a paper concluded before its conversion, what the conversion added is offered, not
    required: the paper was complete on the text it was worked on."""
    for section in definition.get("sections") or []:
        if section["kind"] == "proc":
            for proc in section["procs"]:
                if "p_%s" % proc["key"] not in legacy_keys:
                    proc["_optional"] = True
        elif section["kind"] == "yn":
            for item in section["items"]:
                if "q_%s" % item["key"] not in legacy_keys:
                    item["_optional"] = True
        elif section["kind"] == "fields":
            for field in section["fields"]:
                if field.get("key") and field["key"] not in legacy_keys:
                    field["optional"] = True


def shape(definition, code, complexity, values=None, warnings=(), tool_done=None, hidden_sources=(), legacy_keys=None):
    """The resolved definition as this engagement documents it, annotated for completeness and
    the renderer. Returns a new object; ``definition`` is left as it is.

    ``tool_done`` maps a procedure key to {"done": bool, "result": text} from the tool hooks.
    ``hidden_sources``: the merged tasks whose parts this file does not show (``hide_absorbed``).
    ``legacy_keys``: the answer keys the paper had before its conversion, for a paper concluded
    on that text (``legacy_paper``); what is not among them is not required.

    Annotations: ``_depth``, ``_depthReason``, ``_profile``, ``_summary`` on the paper;
    ``_mode`` (full, exception, tick, tool) and ``_tool`` on each procedure; ``_optional`` on a
    procedure or statement a legacy paper does not require."""
    if not is_converted(definition):
        return definition
    out = hide_absorbed(copy.deepcopy(definition), hidden_sources)
    if legacy_keys is not None:
        _legacy_optional(out, set(legacy_keys))
    depth, reason = depth_of(out, code, complexity, values, warnings)
    tool_done = tool_done or {}
    out["_depth"] = depth
    out["_depthReason"] = reason
    out["_profile"] = wanted_depth(complexity)
    out["_warnings"] = bool(warnings)
    out["_summary"] = depth == VERY_SIMPLE
    for section in out.get("sections") or []:
        if section["kind"] == "proc":
            section["procs"] = [proc for proc in section["procs"] if in_profile(proc, complexity)]
            for proc in section["procs"]:
                done = tool_done.get(proc["key"]) or {}
                if done.get("done"):
                    proc["_mode"] = "tool"
                    proc["_tool"] = done.get("result") or ""
                elif proc.get("neverLight") or depth == FULL:
                    proc["_mode"] = "full"
                elif depth == VERY_SIMPLE:
                    proc["_mode"] = "tick"
                else:
                    proc["_mode"] = "exception"
                if done and not done.get("done"):
                    proc["_tool"] = done.get("result") or ""
        elif section["kind"] == "fields":
            section["fields"] = [field for field in section["fields"] if in_profile(field, complexity)]
        elif section["kind"] == "yn":
            section["items"] = [
                item for item in section["items"]
                if in_profile(item, complexity) and not (depth == VERY_SIMPLE and item.get("vs") is False)
            ]
    return out


LEGACY_WORDS = {
    "en": {"yes": "Yes", "no": "No", "na": "Not applicable"},
    "fr": {"yes": "Oui", "no": "Non", "na": "Non applicable"},
}


def _legacy_answered(values, index):
    return bool(_clean(values.get("c_%d" % index)) or _clean(values.get("c_%d_x" % index)))


def legacy_paper(definition, entry, values, legacy_file=False):
    """Whether a converted paper was concluded before its conversion: an old conclusion key the
    definition no longer asks holds an answer. ``entry`` is the paper's line of
    data/papers_legacy_2026_11_17.json. A paper that kept its statements (P1.1) is read so only
    on a file still on the scope it was opened with (``legacy_file``), while its new conclusion
    box is empty."""
    if not entry or not is_converted(definition):
        return False
    values = values or {}
    asked = len(definition.get("conclEn") or [])
    count = max(len(entry.get("conclEn") or []), asked)
    if any(_legacy_answered(values, index) for index in range(asked, count)):
        return True
    return bool(legacy_file and not _clean(values.get(CONCLUSION_KEY)) and any(
        _legacy_answered(values, index) for index in range(asked)
    ))


def legacy_values(definition, entry, values, lang="en"):
    """What a legacy paper shows and counts while its new boxes are empty: the conclusion it
    recorded (each old statement and its answer) and, for the summary of a very simple file,
    the task answers. ``entry`` carries the old statements, already resolved for the file."""
    values = values or {}
    words = LEGACY_WORDS.get(lang) or LEGACY_WORDS["en"]
    suffix = "Fr" if lang == "fr" else "En"
    out = {}
    if not _clean(values.get(CONCLUSION_KEY)):
        texts = entry.get("concl" + suffix) or entry.get("conclEn") or []
        lines = []
        for index, text in enumerate(texts):
            if not _legacy_answered(values, index):
                continue
            answer = _clean(values.get("c_%d" % index))
            why = _clean(values.get("c_%d_x" % index))
            line = "%s %s" % (text, words.get(answer, answer)) if answer else text
            lines.append("%s: %s" % (line, why) if why else line)
        if lines:
            out[CONCLUSION_KEY] = "\n".join(lines)
    if not _clean(values.get(SUMMARY_KEY)):
        lines = []
        for proc in procs_of(definition):
            key = proc["key"]
            if _clean(values.get("p_%s_na" % key)) == "na":
                text = "%s: %s" % (words["na"], _clean(values.get("p_%s_x" % key)))
            else:
                text = _clean(values.get("p_%s" % key))
            if text:
                title = proc.get("short" + suffix) or proc.get("shortEn") or proc.get(suffix.lower()) or proc.get("en") or key
                lines.append("%s: %s" % (title, text))
        if lines:
            out[SUMMARY_KEY] = "\n".join(lines)
    return out


def proc_answered(proc, values, warnings_active=False):
    """Whether a procedure of a shaped definition is answered. Not applicable needs its reason
    in every depth; a task closed in the tool needs nothing."""
    key = proc["key"]
    value = lambda k: _clean(values.get(k))  # noqa: E731
    if value("p_%s_na" % key) == "na":
        return bool(value("p_%s_x" % key))
    mode = proc.get("_mode") or "full"
    if mode == "tool":
        return True
    mark = value(mark_key(key))
    if mode == "tick" and mark == MARK_TICK:
        return True
    if mark == MARK_NONE and warnings_active:
        # a warning closed the door to "No exceptions noted": the result is to be written again
        return False
    return bool(value("p_%s" % key))


def missing_sources(definition, values):
    """The source keys of "No exceptions noted" answers given without one."""
    if not definition.get("_depth"):
        return []
    out = []
    for proc in procs_of(definition):
        key = proc["key"]
        if proc.get("_mode") == "exception" and _clean(values.get(mark_key(key))) == MARK_NONE:
            if _clean(values.get("p_%s_na" % key)) != "na" and not _clean(values.get(source_key(key))):
                out.append(source_key(key))
    return out


def by_exception_count(definition, values):
    """How many tasks were closed by "No exceptions noted": what the reviewer is shown."""
    return len([
        proc for proc in procs_of(definition)
        if _clean(values.get(mark_key(proc["key"]))) == MARK_NONE and _clean(values.get("p_%s_na" % proc["key"])) != "na"
    ])


def exception_refusal(definition, posted, warnings):
    """A save that closes a task by exception while a hook reports a warning is refused."""
    if not warnings or not is_converted(definition):
        return None
    for proc in procs_of(definition):
        if _clean(posted.get(mark_key(proc["key"]))) == MARK_NONE:
            return "exception-blocked"
    return None


def isa_links(definition, table):
    """The Objective's links, read against data/isa_links.json (standard -> latest IAASB page)."""
    out = []
    for entry in definition.get("isa") or []:
        if isinstance(entry, str):
            entry = {"std": entry}
        std = entry.get("std")
        known = table.get(std) or {} if std else {}
        url = entry.get("url") or known.get("url")
        label = entry.get("label") or known.get("label") or std
        if label:
            out.append({"label": label, "url": url or False})
    return out
