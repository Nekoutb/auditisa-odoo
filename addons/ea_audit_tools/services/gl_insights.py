"""lib/gl-insights.ts: the insight suite's folds, over the raw imported rows.

CY = the post-audit ledger when present, else the pre-audit one; PY = the prior-year ledger. The
model hands rows over; nothing here touches the database. As in the source these read the rows,
not the projection, with this file's own date reader (see QUESTIONS.md).
"""
import math
import re

from ._js import date_parts, date_utc, js_date_parse, js_round, js_sum, js_trim, to_iso_date, weekday as utc_day
from .errors import ServiceError

ROLE_KEYS = ("recordedBy", "preparedBy", "approvedBy")
LAG_KEYS = ("d0", "d1_7", "d8_30", "d31_90", "over90")

_DMY = re.compile(r"^([0-9]{1,2})[/.-]([0-9]{1,2})[/.-]([0-9]{2,4})$")
_CLASS = re.compile(r"^[1-7]$")
_PREFIX = re.compile(r"^[0-9]{2,4}$")
_DAY_MS = 86_400_000


def parse_date(value):
    """The time value of a raw cell, or None. dd/mm/yyyy always, and it rolls 31/02 over."""
    raw = js_trim("" if value is None else str(value))
    if not raw:
        return None
    match = _DMY.match(raw)
    if match:
        year = int("20" + match[3] if len(match[3]) == 2 else match[3])
        parsed = date_utc(year, int(match[2]) - 1, int(match[1]))
    else:
        parsed = js_date_parse(raw)
    return None if parsed is None or math.isnan(parsed) else int(parsed)


def role_insight(key, cy_names, py_names):
    """cy_names None: the column is not mapped on the CY ledger. py_names None: no comparison."""
    if cy_names is None:
        return {"key": key, "mapped": False, "cyCount": None, "pyCount": None, "onlyCy": [], "onlyPy": []}
    py_set = set(py_names or [])
    cy_set = set(cy_names)
    return {
        "key": key,
        "mapped": True,
        "cyCount": len(cy_names),
        "pyCount": None if py_names is None else len(py_names),
        "onlyCy": [] if py_names is None else [name for name in cy_names if name not in py_set],
        "onlyPy": [] if py_names is None else [name for name in py_names if name not in cy_set],
    }


def class_totals(rows):
    """{cls: {lines, gross}} from (cls, lines, gross text): classes 1 to 7 only."""
    return {
        row["cls"]: {"lines": row["lines"], "gross": js_round(float(row["gross"]))}
        for row in rows if _CLASS.match(row["cls"] or "")
    }


def _change(now, base):
    return None if base is None or base == 0 else js_round(((now - base) / base) * 1000) / 10


def class_volume_rows(cy_totals, py_totals):
    rows = []
    for cls in "1234567":
        current = cy_totals.get(cls) or {"lines": 0, "gross": 0}
        prior = None if py_totals is None else py_totals.get(cls) or {"lines": 0, "gross": 0}
        rows.append({
            "cls": cls,
            "cyLines": current["lines"],
            "cyGross": current["gross"],
            "pyLines": None if prior is None else prior["lines"],
            "pyGross": None if prior is None else prior["gross"],
            "linesPct": _change(current["lines"], None if prior is None else prior["lines"]),
            "grossPct": _change(current["gross"], None if prior is None else prior["gross"]),
        })
    return {"rows": rows, "hasPy": py_totals is not None}


def weekday_analysis(lines):
    """``lines``: (journal date, je, gross text). dow 0 is Monday."""
    rows = [{"dow": dow, "journals": 0, "lines": 0, "gross": 0} for dow in range(7)]
    journals = [set() for _dow in range(7)]
    undated = 0
    for raw_date, je, gross in lines:
        date = parse_date(raw_date)
        if date is None:
            undated += 1
            continue
        dow = (utc_day(date) + 6) % 7
        rows[dow]["lines"] += 1
        rows[dow]["gross"] += float(gross or 0)
        identity = js_trim(str(je or ""))
        if identity:
            journals[dow].add(identity)
    for row in rows:
        row["journals"] = len(journals[row["dow"]])
        row["gross"] = js_round(row["gross"])
    return {"rows": rows, "undated": undated}


def entry_lag(lines):
    """``lines``: (je, journal date, entry date). The first readable date pair of each journal."""
    lags = {}
    for je, raw_journal, raw_entry in lines:
        identity = js_trim(str(je or ""))
        if not identity or identity in lags:
            continue
        effective, entered = parse_date(raw_journal), parse_date(raw_entry)
        if effective is None or entered is None:
            continue
        lags[identity] = js_round((entered - effective) / _DAY_MS)
    values = list(lags.values())
    counts = dict.fromkeys(LAG_KEYS, 0)
    for lag in values:
        counts["d0" if lag <= 0 else "d1_7" if lag <= 7 else "d8_30" if lag <= 30 else "d31_90" if lag <= 90 else "over90"] += 1
    average = js_sum(values) / len(values) if values else 0
    return {
        "avgDays": js_round(average * 10) / 10,
        "maxDays": max(values) if values else 0,
        "journals": len(values),
        "buckets": [{"key": key, "journals": counts[key]} for key in LAG_KEYS],
    }


def pearson(xs, ys):
    """This file's own Pearson: two points suffice, two decimals. Not gl-analytics' one."""
    n = len(xs)
    if n < 2:
        return None
    mean_x = js_sum(xs) / n
    mean_y = js_sum(ys) / n
    cov = var_x = var_y = 0
    for index in range(n):
        cov += (xs[index] - mean_x) * (ys[index] - mean_y)
        var_x += (xs[index] - mean_x) ** 2
        var_y += (ys[index] - mean_y) ** 2
    if var_x == 0 or var_y == 0:
        return None
    return js_round((cov / math.sqrt(var_x * var_y)) * 100) / 100


def read_prefixes(accounts):
    cleaned = list(dict.fromkeys(js_trim(str(account)) for account in accounts))
    if len(cleaned) < 2 or len(cleaned) > 6 or not all(_PREFIX.match(prefix) for prefix in cleaned):
        raise ServiceError("invalid-accounts")
    return cleaned


def correlation_matrix(lines, cleaned):
    """``lines``: (account, je, journal date, gross text). Which journals touch every prefix, when
    they land (month x day of month), and how the prefixes' daily line volumes co-move."""
    totals = {prefix: {"lines": 0, "gross": 0} for prefix in cleaned}
    journals_by_prefix = {prefix: set() for prefix in cleaned}
    daily_by_prefix = {prefix: {} for prefix in cleaned}
    all_dates = set()
    journal_date = {}
    for raw_account, raw_je, raw_date, gross in lines:
        account = js_trim(str(raw_account or ""))
        je = js_trim(str(raw_je or ""))
        date = parse_date(raw_date)
        if je and date is not None and je not in journal_date:
            journal_date[je] = date
        for prefix in cleaned:
            if not account.startswith(prefix):
                continue
            totals[prefix]["lines"] += 1
            totals[prefix]["gross"] += float(gross or 0)
            if je:
                journals_by_prefix[prefix].add(je)
            if date is not None:
                iso = to_iso_date(date)
                all_dates.add(iso)
                daily = daily_by_prefix[prefix]
                daily[iso] = daily.get(iso, 0) + 1
    shared = None
    for prefix in cleaned:
        shared = set(journals_by_prefix[prefix]) if shared is None else shared & journals_by_prefix[prefix]
    shared = shared or set()
    matrix = [[0] * 31 for _month in range(12)]
    for je in shared:
        date = journal_date.get(je)
        if date is None:
            continue
        _year, month0, day = date_parts(date)
        matrix[month0][day - 1] += 1
    dates = sorted(all_dates)
    vectors = {prefix: [daily_by_prefix[prefix].get(iso, 0) for iso in dates] for prefix in cleaned}
    pairs = [
        {"a": cleaned[i], "b": cleaned[j], "r": pearson(vectors[cleaned[i]], vectors[cleaned[j]])}
        for i in range(len(cleaned)) for j in range(i + 1, len(cleaned))
    ]
    return {
        "prefixes": [{"prefix": prefix, "lines": totals[prefix]["lines"], "gross": js_round(totals[prefix]["gross"])} for prefix in cleaned],
        "sharedJournals": len(shared),
        "matrix": matrix,
        "pairs": pairs,
    }
