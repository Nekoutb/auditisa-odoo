"""Execution of the designed substantive procedures (owner's mock-ups of 2026-11-16, mock-proc-exec-*).

Pure rules, no Odoo: what the "Substantive procedures" page counts, what the tool compares in a
reconciliation, which ledger entries it picks for a cut-off test or the search for unrecorded
liabilities, what one tested item may carry, and the difference of a third-party confirmation.

Dates are ISO text (yyyy-mm-dd); amounts are floats; a ledger line is a dict with ``key`` (where
it comes from, "c<line>" in the year audited, "s<line>" in the next year), ``date``,
``account``, ``je_number``, ``signed`` (debit less credit), ``label`` and ``third``.
"""
import re

from ._js import _civil_from_days, _days_from_civil, js_round, js_sum

#: Default cut-off window: this many days either side of the year end.
CUTOFF_DAYS = 10
#: Default window of the search for unrecorded liabilities: days of the next year read.
UNRECORDED_DAYS = 90
#: Default threshold: this share of performance materiality.
THRESHOLD_SHARE = 0.10
#: At most this many entries in one selection: beyond, the threshold is too low to be a test.
SELECTION_CAP = 300
#: Below this, a difference is a rounding.
TOLERANCE = 0.5

#: The accounts read by the cut-off test of each lead index: families in order, each with the sign
#: that turns its usual side into a positive amount. The first family an entry touches gives its
#: amount, so a sale (receivable and revenue) is counted once.
CUTOFF_FAMILIES = {
    "E": (("70", -1), ("41", 1)),
    "N": (("60", 1), ("61", 1), ("62", 1), ("40", -1)),
    "F": (("3", 1), ("60", 1)),
    "C": (("52", 1), ("53", 1), ("57", 1)),
}
#: The search for unrecorded liabilities: payments to suppliers and expenses booked next year.
UNRECORDED_FAMILIES = (("40", 1), ("6", 1))

#: What the reconciliation of each lead index compares: the sub-ledger upload, the general ledger
#: accounts, and the sign that turns the ledger balance into the sub-ledger's positive total.
RECON = {
    "E": {"kind": "ar_open_items", "prefixes": ("41",), "sign": 1},
    "N": {"kind": "ap_open_items", "prefixes": ("40",), "sign": -1},
    "F": {"kind": "inventory_listing", "prefixes": ("3",), "sign": 1},
}

CONFIRMATION_STATUSES = ("to_send", "sent", "reminder", "received", "no_reply")
CONCLUSIONS = ("satisfactory", "exceptions")
_CONFIRMATION_WORDS = re.compile(r"confirm", re.I)
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


# ----------------------------------------------------------------------
# The overview
# ----------------------------------------------------------------------

def progress(states):
    """{done, started, total} of a list of procedure states (draft, started, done)."""
    states = list(states)
    return {
        "done": states.count("done"),
        "started": states.count("started"),
        "total": len(states),
    }


def is_confirmation(code, title_en):
    """A procedure of the confirmation type: its library title speaks of confirmations."""
    return bool(_CONFIRMATION_WORDS.search(title_en or "")) and bool(code)


def split_steps(summary):
    """The steps of a procedure, from its library summary: one per sentence or clause."""
    text = (summary or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.;])\s+", text)
    return [part.strip().rstrip(";").strip() for part in parts if part.strip().rstrip(";").strip()]


def default_threshold(performance):
    """Performance materiality x 10 %, rounded; None when no materiality is approved."""
    if not performance:
        return None
    return float(js_round(performance * THRESHOLD_SHARE))


# ----------------------------------------------------------------------
# Reconciliation
# ----------------------------------------------------------------------

def gl_accounts(balances, prefixes, sign):
    """The ledger accounts compared: [(account, name, balance as the sub-ledger reads it)]."""
    out = []
    for account, name, value in balances:
        if any(str(account).startswith(prefix) for prefix in prefixes):
            out.append({"account": str(account), "name": name or "", "balance": float(value or 0) * sign})
    return sorted(out, key=lambda row: row["account"])


def recon_compare(accounts, sub_total, explanations=()):
    """The comparison: ledger total, sub-ledger total, difference (sub-ledger less ledger), what
    the auditor explained, and what is left. ``state``: "no-gl" (no ledger figure), "no-subledger"
    (no upload), "agrees", "explained" or "difference"."""
    gl_total = js_round(js_sum(row["balance"] for row in accounts) * 100) / 100 if accounts else None
    explained = js_round(js_sum(float(item.get("amount") or 0) for item in explanations) * 100) / 100
    if gl_total is None:
        return {"gl": None, "sub": sub_total, "difference": None, "explained": explained, "unexplained": None, "state": "no-gl"}
    if sub_total is None:
        return {"gl": gl_total, "sub": None, "difference": None, "explained": explained, "unexplained": None, "state": "no-subledger"}
    difference = js_round((sub_total - gl_total) * 100) / 100
    unexplained = js_round((difference - explained) * 100) / 100
    if abs(difference) < TOLERANCE:
        state = "agrees"
    elif abs(unexplained) < TOLERANCE:
        state = "explained"
    else:
        state = "difference"
    return {"gl": gl_total, "sub": sub_total, "difference": difference, "explained": explained, "unexplained": unexplained, "state": state}


def largest_parties(rows, limit=10):
    """The sub-ledger by party, largest first: [{party, name, amount, items}]. ``rows``:
    [(party, name, amount)]."""
    by_party = {}
    for party, name, amount in rows:
        key = (party or name or "").strip()
        if not key:
            continue
        entry = by_party.setdefault(key, {"party": (party or "").strip(), "name": (name or "").strip(), "amount": 0.0, "items": 0})
        entry["amount"] += float(amount or 0)
        entry["items"] += 1
        if not entry["name"] and name:
            entry["name"] = name.strip()
    ranked = sorted(by_party.values(), key=lambda e: (-abs(e["amount"]), e["party"]))
    for entry in ranked:
        entry["amount"] = js_round(entry["amount"] * 100) / 100
    return ranked[:limit] if limit else ranked


def clean_explanation(values):
    """One line the auditor explains: text, amount, cleared. None when refused."""
    if not isinstance(values, dict) or set(values) - {"text", "amount", "cleared"}:
        return None
    text = str(values.get("text") or "").strip()[:500]
    amount = _number(values.get("amount"))
    if amount is False:
        return None
    return {"text": text, "amount": amount or 0.0, "cleared": bool(values.get("cleared"))}


# ----------------------------------------------------------------------
# Cut-off and unrecorded liabilities
# ----------------------------------------------------------------------

def _day(iso):
    match = _ISO.match(iso or "")
    if not match:
        return None
    year, month, day = (int(x) for x in match.groups())
    return _days_from_civil(year, month, day)


def cutoff_window(period_end, days):
    """(first day read in the year audited, last day read in the next year), as day numbers."""
    end = _day(period_end)
    return end - days + 1, end + days


def _families_amount(lines, families):
    """The amount of one entry: the first family it touches, signed to its usual side. None when
    it touches none."""
    for prefix, sign in families:
        mine = [line for line in lines if str(line["account"]).startswith(prefix)]
        if mine:
            return js_round(js_sum(float(line["signed"] or 0) for line in mine) * sign * 100) / 100, prefix
    return None, None


def _entries(lines, families, first, last, side):
    """Entries of a ledger whose date falls in [first, last], on the families' accounts."""
    grouped = {}
    for line in lines:
        day = _day(line.get("date"))
        if day is None or day < first or day > last:
            continue
        if not any(str(line["account"]).startswith(prefix) for prefix, _sign in families):
            continue
        grouped.setdefault((line["je_number"], line["date"]), []).append(line)
    out = []
    for (number, date), mine in grouped.items():
        amount, prefix = _families_amount(mine, families)
        if amount is None:
            continue
        head = min(mine, key=lambda line: str(line["key"]))
        out.append({
            "key": head["key"], "side": side, "date": date, "entry": number, "account": head["account"] if prefix else "",
            "label": next((line.get("label") for line in mine if line.get("label")), "") or "",
            "third": next((line.get("third") for line in mine if line.get("third")), "") or "",
            "amount": amount,
        })
    return out


def select_entries(candidates, threshold):
    """The entries at or above the threshold (in absolute value), by date then entry; a credit
    note (negative) of that size is picked as well."""
    floor = abs(float(threshold or 0))
    picked = [entry for entry in candidates if abs(entry["amount"]) >= floor]
    return sorted(picked, key=lambda e: (e["date"], str(e["entry"]), str(e["key"])))[:SELECTION_CAP]


def cutoff_select(current_lines, next_lines, period_end, days, threshold, families):
    """The cut-off selection: the last ``days`` days of the year audited from its ledger, the first
    ``days`` of the next year from the next-year ledger (when there is one). Returns
    {picks, population: {before, after, total, value}, window: {from, to}}."""
    days = int(days)
    first, last = cutoff_window(period_end, days)
    end = _day(period_end)
    before = _entries(current_lines, families, first, end, "before")
    after = _entries(next_lines or [], families, end + 1, last, "after")
    population = before + after
    return {
        "picks": select_entries(population, threshold),
        "population": {
            "before": len(before), "after": len(after), "total": len(population),
            "value": js_round(js_sum(abs(e["amount"]) for e in population) * 100) / 100,
        },
        "window": {"from": _iso_of(first), "to": _iso_of(last)},
    }


def unrecorded_select(next_lines, period_end, days, threshold, families=UNRECORDED_FAMILIES):
    """The search for unrecorded liabilities: next-year entries on supplier and expense accounts
    in the ``days`` after the year end, at or above the threshold."""
    end = _day(period_end)
    candidates = _entries(next_lines or [], families, end + 1, end + int(days), "after")
    return {
        "picks": select_entries(candidates, threshold),
        "population": {
            "before": 0, "after": len(candidates), "total": len(candidates),
            "value": js_round(js_sum(abs(e["amount"]) for e in candidates) * 100) / 100,
        },
        "window": {"from": _iso_of(end + 1), "to": _iso_of(end + int(days))},
    }


def _iso_of(day_number):
    return "%04d-%02d-%02d" % _civil_from_days(day_number)


def clean_selection_params(days, threshold):
    """(days, threshold) a person may set, or None when refused: 1 to 366 days, a threshold of
    zero or more."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        return None
    amount = _number(threshold)
    if amount is False or amount is None or amount < 0 or not 1 <= days <= 366:
        return None
    return days, amount


def clean_cutoff_patch(patch):
    """What a person may set on one selected entry: right period (yes, no or nothing), the
    document seen, the delivery or service date (a few words), a note. None when refused."""
    if not isinstance(patch, dict) or not patch or set(patch) - {"period", "doc", "when", "note"}:
        return None
    out = {}
    if "period" in patch:
        if patch["period"] not in ("yes", "no", None, "", False):
            return None
        out["period"] = patch["period"] or None
    if "doc" in patch:
        out["doc"] = bool(patch["doc"])
    if "when" in patch:
        out["when"] = str(patch["when"] or "").strip()[:40]
    if "note" in patch:
        out["note"] = str(patch["note"] or "").strip()[:2000]
    return out


def selection_counts(picks, results):
    """{done, wrong, total}: entries with an answer, entries in the wrong period."""
    done = wrong = 0
    for pick in picks:
        found = (results or {}).get(str(pick)) or {}
        if found.get("period"):
            done += 1
        if found.get("period") == "no":
            wrong += 1
    return {"done": done, "wrong": wrong, "total": len(picks)}


# ----------------------------------------------------------------------
# Confirmations
# ----------------------------------------------------------------------

def confirmation_difference(book, confirmed, status):
    """Confirmed less book, once a reply is in; None before."""
    if status != "received" or confirmed is None or book is None:
        return None
    return js_round((float(confirmed) - float(book)) * 100) / 100


def confirmation_state(book, confirmed, status, explanation):
    """What a request needs next: "waiting", "alternative" (no reply: other procedures),
    "agrees", "explained" or "difference" (a finding to raise)."""
    if status == "no_reply":
        return "alternative"
    difference = confirmation_difference(book, confirmed, status)
    if difference is None:
        return "waiting"
    if abs(difference) < TOLERANCE:
        return "agrees"
    return "explained" if (explanation or "").strip() else "difference"


# ----------------------------------------------------------------------

def _number(value):
    """A typed amount: a float, None when empty, False when unreadable."""
    if value in (None, "", False):
        return None
    if isinstance(value, bool):
        return False
    try:
        text = str(value).replace(" ", "").replace(" ", "").replace(" ", "")
        text = text.replace(",", "") if "." in text else text.replace(",", ".")
        number = float(text)
    except ValueError:
        return False
    if number != number or number in (float("inf"), float("-inf")):
        return False
    return number
