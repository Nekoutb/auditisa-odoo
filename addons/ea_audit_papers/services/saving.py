"""The merge rules of a paper save and small per-code rules. No Odoo import.

Ports lib/working-papers.ts (savePaper, fieldDigest, filterPaperWrite's comparison,
acceptancePaperVerdict), lib/papers/statutory-525.ts (personsOnSave) and lib/eqr.ts
(EQR_C42_KEYS).
"""

import hashlib
import re

from .completeness import concl_key, js_trim, paper_missing, yn_key

EQR_C42_KEYS = frozenset(
    {"p_review", "p_completion", "q_complete", "q_complete_x", "q_resolved", "q_resolved_x", "c_0", "c_0_x"}
)
ART_525_HEADCOUNT_THRESHOLD = 200
_HEADCOUNT = re.compile("\\d[\\d\\s  .]*")


class StaleEdit(Exception):
    pass


def norm_text(value):
    """A browser posts a textarea's line breaks as CRLF: compare text without them."""
    return (value or "").replace("\r\n", "\n")


def field_digest(value):
    return hashlib.sha256(norm_text(value).encode("utf-8")).hexdigest()[:16]


def base_digests(values):
    return {key: field_digest(value) for key, value in values.items()}


def is_blank(value):
    return not js_trim(value or "")


def answer_changed(before, after):
    """NULL, '' and blank are the same thing, "nobody said anything"."""
    if is_blank(before) and is_blank(after):
        return False
    return norm_text(before) != norm_text(after)


def same_answer(a, b):
    """filterPaperWrite: an unchanged field posted back by whoever does not own it."""
    return js_trim(norm_text(a)) == js_trim(norm_text(b))


def plan_save(values, allowed, stored, digests=None, stale=False):
    """What a save writes, given what is stored now.

    `stale` is whether the paper moved since the form was loaded. Returns
    (writes, conflicts): `writes` maps key to text, `conflicts` maps a key both people
    changed to this user's text. Raises StaleEdit when the paper moved and the form
    sent no digests.
    """
    moved = {}
    if stale:
        if digests is None:
            raise StaleEdit()
        empty = field_digest("")
        for key, value in stored.items():
            if key in allowed and field_digest(value) != digests.get(key, empty):
                moved[key] = value
    writes, conflicts = {}, {}
    for key, value in values.items():
        if key not in allowed:
            continue
        if key in moved:
            base = (digests or {}).get(key, field_digest(""))
            if field_digest(value) == base:
                continue  # left alone by this user: the colleague's text stands
            if norm_text(moved[key]) != norm_text(value):
                conflicts[key] = value
                continue
        writes[key] = value
    return writes, conflicts


def _headcount_figure(text):
    match = _HEADCOUNT.search(text or "")
    if not match:
        return None
    return int(re.sub("[\\s  .]", "", match.group(0)))


def persons_from_headcount(headcount):
    figure = _headcount_figure(headcount)
    if figure is None:
        return None
    return "ten" if figure > ART_525_HEADCOUNT_THRESHOLD else "five"


def persons_on_save(stored, posted):
    """C5.10: what a save stores as the number of persons, None to leave it alone."""
    if "headcount" not in posted:
        return None
    posted_persons = js_trim(posted.get("persons") or "")
    stored_persons = js_trim(stored.get("persons") or "")
    if posted_persons and posted_persons != stored_persons:
        return None
    changed = _headcount_figure(posted["headcount"]) != _headcount_figure(stored.get("headcount"))
    if not changed and posted_persons:
        return None
    return persons_from_headcount(posted["headcount"])


def acceptance_verdict(p11_definition, p12_definition, p11, p12, predecessor_required=None):
    """What the acceptance gates read from the P1.1 paper (acceptancePaperVerdict).
    predecessor_required: whether P1.2 is on the file (the engagement profile questionnaire
    puts it there for a first-year audit). None reads an older P1.1's own "change of auditor"."""

    def answer(key):
        return js_trim(p11.get(key) or "")

    complete = not paper_missing(p11_definition, p11)
    accepted = answer(concl_key(0)) == "yes"
    any_no = any(
        answer(yn_key(item["key"])) == "no"
        for section in p11_definition.get("sections") or []
        if section["kind"] == "yn"
        for item in section["items"]
    )
    rating_holds = not (any_no and answer("rating") == "low")
    if predecessor_required is None:
        predecessor_required = answer("auditor_change") == "yes"
    predecessor = not predecessor_required or not paper_missing(p12_definition, p12)
    return {
        "complete": complete,
        "accepted": accepted,
        "predecessor_recorded": predecessor,
        "checks_passed": complete and accepted and answer(concl_key(1)) == "yes" and rating_holds and predecessor,
    }
