"""Substantive procedures, second build (owner's mock-ups of 2026-11-16, mock-sub2-*).

Pure rules, no Odoo:

* the working order of an account's procedures (mandatory first, then the alternatives, then the
  team's own) and the colour of an account's card;
* K-M1: the fixed asset register against the general ledger, by category (classes 21 to 25 for
  the cost, 28 and 291 to 295 for depreciation and impairment, SYSCOHADA);
* F-M1: the attendance at the physical count: the checklists before, during and after the count,
  the test counts sheet to floor (drawn by the tool from the inventory listing) and floor to sheet
  (typed), and the roll-forward from the count date to the year end;
* the customers or suppliers proposed for confirmation: the largest balances plus a few others.

Amounts are floats; a missing figure is None.
"""
import random
import re

from ._js import js_round, js_sum
from .amount import parse_amount
from .procedure_execution import TOLERANCE, _number

KIND_RANK = {"MSP": 0, "ASP": 1, "custom": 2}

#: The checklists of the attendance at the count, by phase. The words are on the page (EN + FR).
COUNT_CHECKS = (
    ("before", ("instructions", "teams", "numbers", "special")),
    ("during", ("follow", "testcounts", "sheets")),
    ("after", ("agree", "cutoff", "rollforward")),
)
COUNT_CHECK_KEYS = tuple("%s.%s" % (phase, key) for phase, keys in COUNT_CHECKS for key in keys)
COUNT_PHASES = tuple(phase for phase, _keys in COUNT_CHECKS)
#: Test counts sheet to floor drawn by default; at most this many.
COUNT_SIZE = 15
COUNT_MAX = 200
#: Floor-to-sheet items typed: at most this many.
FLOOR_MAX = 200
#: Customers or suppliers proposed for confirmation: the largest, then a few of the others.
CONFIRM_TOP = 10
CONFIRM_EXTRA = 5

_LEADING_DIGITS = re.compile(r"^\s*(\d+)")


def _r(value):
    return js_round(value * 100) / 100


# ----------------------------------------------------------------------
# The page
# ----------------------------------------------------------------------

def working_order(procs):
    """Sort key of a procedure ({kind, sequence, code}): MSP, then ASP, then the team's own."""
    return sorted(procs, key=lambda p: (KIND_RANK.get(p.get("kind"), 3), p.get("sequence") or 0, p.get("code") or ""))


def account_state(done, started, total):
    """The card's colour: "done" (green, all done), "started" (amber), "open" (grey)."""
    if total and done == total:
        return "done"
    if done or started:
        return "started"
    return "open"


# ----------------------------------------------------------------------
# K-M1: fixed asset register against the general ledger
# ----------------------------------------------------------------------

def far_prefix(account):
    """The ledger class of a register line's account: its first three digits when it is a fixed
    asset account (21 to 25), else None."""
    match = _LEADING_DIGITS.match(str(account or ""))
    digits = match.group(1) if match else ""
    if len(digits) >= 2 and digits[0] == "2" and digits[1] in "12345":
        return digits[:3]
    return None


def is_far_account(account):
    """A ledger account the register answers for: cost (21-25), depreciation (28), impairment (291-295)."""
    text = str(account or "")
    if len(text) < 2 or text[0] != "2":
        return False
    if text[1] in "12345" or text[:2] == "28":
        return True
    return text[:2] == "29" and len(text) > 2 and text[2] in "12345"


def _ledger_of_prefix(balances, prefix):
    """Net book value in the ledger of one class: its cost accounts with their depreciation and impairment."""
    tail = prefix[1:]
    heads = (prefix, "28" + tail, "29" + tail)
    return _r(js_sum(float(value or 0) for account, _name, value in balances if str(account).startswith(heads)))


def far_number(value):
    """A figure of the register, typed or exported: a float, or None."""
    number = parse_amount(value)
    return None if number is None else float(number)


def far_recon(rows, balances, explanation=""):
    """The register against the ledger, by category.

    ``rows``: the register's lines, dicts with ``category``, ``account`` (texts) and ``opening``,
    ``additions``, ``disposals``, ``charge`` (depreciation of the year), ``closing`` (net book
    value), floats or None. ``balances``: [(account, name, closing)] of the ledger, debit positive.

    Disposals and depreciation are shown as reductions (negative). A category whose lines carry a
    fixed asset account is compared with that ledger class; otherwise only the total is compared.
    ``state``: "no-register", "no-gl", "agrees", "explained" or "difference"."""
    ledger_rows = [(a, n, v) for a, n, v in balances if is_far_account(a)]
    names = {str(a): n for a, n, _v in balances}
    groups, order = {}, []
    for row in rows:
        prefix = far_prefix(row.get("account"))
        category = str(row.get("category") or "").strip()
        key = prefix or "cat:" + category.lower()
        group = groups.get(key)
        if group is None:
            group = groups[key] = {
                "key": key, "prefix": prefix, "label": category,
                "opening": None, "additions": None, "disposals": None, "charge": None, "closing": None,
            }
            order.append(key)
        if not group["label"] and category:
            group["label"] = category
        for name in ("opening", "additions", "disposals", "charge", "closing"):
            value = row.get(name)
            if value is None:
                continue
            if name in ("disposals", "charge"):
                value = -abs(value)
            group[name] = (group[name] or 0.0) + value
    out = []
    for key in sorted(order, key=lambda k: (groups[k]["prefix"] or "~", groups[k]["label"].lower())):
        group = groups[key]
        for name in ("opening", "additions", "disposals", "charge", "closing"):
            if group[name] is not None:
                group[name] = _r(group[name])
        if not group["label"]:
            group["label"] = "%s %s" % (group["prefix"], names.get(group["prefix"], "")) if group["prefix"] else ""
            group["label"] = group["label"].strip()
        moves = [group[name] for name in ("additions", "disposals", "charge") if group[name] is not None]
        group["movement"] = _r(group["opening"] + js_sum(moves)) if group["opening"] is not None and moves else None
        group["moveDifference"] = (
            _r(group["closing"] - group["movement"]) if group["movement"] is not None and group["closing"] is not None else None
        )
        if group["moveDifference"] is not None and abs(group["moveDifference"]) < TOLERANCE:
            group["moveDifference"] = 0.0
        group["ledger"] = _ledger_of_prefix(ledger_rows, group["prefix"]) if group["prefix"] else None
        group["difference"] = (
            _r((group["closing"] or 0) - group["ledger"]) if group["ledger"] is not None else None
        )
        out.append(group)
    linked = bool(out) and all(g["prefix"] for g in out)
    ledger_total = _r(js_sum(float(v or 0) for _a, _n, v in ledger_rows)) if ledger_rows else None
    if linked and ledger_total is not None:
        rest = _r(ledger_total - js_sum(g["ledger"] for g in out))
        if abs(rest) >= TOLERANCE:
            out.append({
                "key": "rest", "prefix": None, "label": "", "rest": True,
                "opening": None, "additions": None, "disposals": None, "charge": None, "closing": 0.0,
                "movement": None, "moveDifference": None, "ledger": rest, "difference": _r(-rest),
            })

    def column(name):
        values = [g[name] for g in out if g[name] is not None]
        return _r(js_sum(values)) if values else None

    total = {name: column(name) for name in ("opening", "additions", "disposals", "charge", "closing")}
    total["ledger"] = ledger_total
    total["difference"] = _r((total["closing"] or 0) - ledger_total) if ledger_total is not None and out else None
    gaps = [g for g in out if g["difference"] is not None and abs(g["difference"]) >= TOLERANCE]
    moved = [g for g in out if g["moveDifference"]]
    if not rows:
        state = "no-register"
    elif ledger_total is None:
        state = "no-gl"
    elif not gaps and (total["difference"] is None or abs(total["difference"]) < TOLERANCE) and not moved:
        state = "agrees"
    elif (explanation or "").strip():
        state = "explained"
    else:
        state = "difference"
    return {
        "rows": out, "total": total, "linked": linked, "state": state,
        "gaps": [{"label": g["label"], "difference": g["difference"]} for g in gaps],
        "moved": [{"label": g["label"], "difference": g["moveDifference"]} for g in moved],
        "hasMovements": any(total[name] is not None for name in ("opening", "additions", "disposals", "charge")),
        "needsExplanation": state in ("difference", "explained"),
    }


# ----------------------------------------------------------------------
# F-M1: attendance at the physical count
# ----------------------------------------------------------------------

def clean_count_size(size):
    """The number of test counts sheet to floor a person may ask: 1 to COUNT_MAX, or None."""
    try:
        size = int(size)
    except (TypeError, ValueError):
        return None
    return size if 1 <= size <= COUNT_MAX else None


def count_sample(rows, size, seed):
    """The test counts sheet to floor: the highest values first (half of the size, rounded up),
    then items drawn at random among the others. ``rows``: [(row_no, amount)].
    Returns [(row_no, "top" | "random")], in the order drawn."""
    ranked = sorted(rows, key=lambda r: (-abs(float(r[1] or 0)), r[0]))
    top = ranked[: (size + 1) // 2]
    picked = {row_no for row_no, _amount in top}
    rest = sorted(row_no for row_no, _amount in rows if row_no not in picked)
    extra = random.Random(str(seed)).sample(rest, min(len(rest), size - len(top))) if rest else []
    return [(row_no, "top") for row_no, _amount in top] + [(row_no, "random") for row_no in extra]


def count_item(per_sheet, counted):
    """(difference, state) of one test count: "todo" (not counted yet), "ok", "diff" (a
    difference: a finding to raise or explain) or "missing" (on the floor, not on the sheets)."""
    if counted is None:
        return None, "todo"
    if per_sheet is None:
        return None, "missing"
    difference = _r(counted - per_sheet)
    if abs(difference) < 1e-9:
        return 0.0, "ok"
    return difference, "diff"


def clean_count_patch(patch):
    """What a person sets on a test count sheet to floor: the quantity counted, a note. None when refused."""
    if not isinstance(patch, dict) or not patch or set(patch) - {"counted", "note"}:
        return None
    out = {}
    if "counted" in patch:
        number = _number(patch["counted"])
        if number is False or (number is not None and number < 0):
            return None
        out["counted"] = number
    if "note" in patch:
        out["note"] = str(patch["note"] or "").strip()[:500]
    return out


def clean_floor_item(values, adding=False):
    """One item picked on the floor and traced to the sheets: item, location, quantity per
    sheet (empty: not on the sheets), quantity counted, note. None when refused."""
    if not isinstance(values, dict) or set(values) - {"item", "location", "sheet", "counted", "note"}:
        return None
    out = {}
    for name, limit in (("item", 200), ("location", 100), ("note", 500)):
        if name in values:
            out[name] = str(values[name] or "").strip()[:limit]
    if adding and not out.get("item"):
        return None
    for name in ("sheet", "counted"):
        if name in values:
            number = _number(values[name])
            if number is False or (number is not None and number < 0):
                return None
            out[name] = number
    return out


def clean_rollforward(values):
    """The roll-forward a person types: count date (ISO), count value, receipts and issues
    between the count and the year end, the final listing (when no upload gives it)."""
    if not isinstance(values, dict) or set(values) - {"countDate", "count", "receipts", "issues", "final"}:
        return None
    out = {}
    if "countDate" in values:
        text = str(values["countDate"] or "").strip()
        if text and not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            return None
        out["countDate"] = text
    for name in ("count", "receipts", "issues", "final"):
        if name in values:
            number = _number(values[name])
            if number is False:
                return None
            out[name] = number
    return out


def rollforward(count_value, receipts, issues, final):
    """Count value + receipts - issues = expected at year end, against the final listing.
    ``state``: "incomplete", "agrees" or "difference"."""
    if count_value is None or final is None:
        return {"expected": None, "difference": None, "state": "incomplete"}
    expected = _r(count_value + (receipts or 0) - abs(issues or 0))
    difference = _r(final - expected)
    return {"expected": expected, "difference": difference, "state": "agrees" if abs(difference) < TOLERANCE else "difference"}


def count_left(checks, sheet_items, floor_items):
    """What still stops "Mark as done": checks not ticked, test counts not counted."""
    ticks = checks or {}
    return {
        "checks": len([key for key in COUNT_CHECK_KEYS if not ticks.get(key)]),
        "items": len([i for i in sheet_items if i.get("counted") is None]) + len([i for i in floor_items if i.get("counted") is None]),
    }


# ----------------------------------------------------------------------
# Confirmations
# ----------------------------------------------------------------------

def confirmation_pick(parties, existing, seed, top=CONFIRM_TOP, extra=CONFIRM_EXTRA):
    """The customers or suppliers proposed for confirmation and not requested yet: the largest
    balances, then a few of the others drawn at random. ``parties``: largest_parties' list;
    ``existing``: party names or numbers already requested (any case)."""
    taken = {str(x or "").strip().lower() for x in existing}
    free = [p for p in parties if (p["party"] or "").lower() not in taken and (p["name"] or "").lower() not in taken]
    largest = free[:top]
    others = free[top:]
    drawn = random.Random(str(seed)).sample(others, min(extra, len(others))) if others else []
    return largest + sorted(drawn, key=lambda p: (-abs(p["amount"]), p["party"]))
