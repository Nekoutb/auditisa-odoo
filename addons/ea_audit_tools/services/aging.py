"""lib/aging.ts: every transaction bucketed by the age of its date at the period end, per party.
Current 0-30 days, then 31-60, 61-90 and over 90."""
import re

from ._js import date_utc, js_date_parse, js_floor, js_round, js_str, js_trim
from .amount import amount_or

_DMY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$")
_DAY_MS = 86_400_000


def parse_date_ms(value):
    """dd/mm/yyyy, else what the JavaScript Date reads; None when unreadable. A day above the
    month rolls over, as in the source."""
    raw = js_trim(js_str(value if value is not None else ""))
    if not raw:
        return None
    match = _DMY.match(raw)
    if match:
        year = int("20" + match[3] if len(match[3]) == 2 else match[3])
        return date_utc(year, int(match[2]) - 1, int(match[1]))
    stamp = js_date_parse(raw)
    return None if stamp is None or stamp != stamp else stamp


def aging(rows, mapping, period_end_ms):
    """{rows, totals, transactionCount, undated, hasTerms}; None when the mapping lacks party,
    amount or date. ``rows`` are the dataset's data dicts."""
    if not (mapping or {}).get("party") or not mapping.get("amount") or not mapping.get("date"):
        return None
    terms_column = mapping.get("paymentTerms")
    by_party = {}
    undated = 0
    for data in rows:
        party = js_trim(js_str(data.get(mapping["party"]) if data.get(mapping["party"]) is not None else ""))
        if not party:
            continue
        date = parse_date_ms(data.get(mapping["date"]))
        if date is None:
            undated += 1
            continue
        amount = amount_or(data.get(mapping["amount"]), 0)
        age = js_floor((period_end_ms - date) / _DAY_MS)
        entry = by_party.get(party)
        if entry is None:
            name = js_trim(js_str(data.get(mapping["partyName"]) or "")) if mapping.get("partyName") else ""
            entry = {"party": party, "name": name or party, "terms": None, "current": 0, "d31_60": 0, "d61_90": 0, "over90": 0, "total": 0}
            by_party[party] = entry
        if terms_column and entry["terms"] is None:
            terms = js_trim(js_str(data.get(terms_column) or ""))
            if terms:
                entry["terms"] = terms
        bucket = "current" if age <= 30 else "d31_60" if age <= 60 else "d61_90" if age <= 90 else "over90"
        entry[bucket] += amount
        entry["total"] += amount
    keys = ("current", "d31_60", "d61_90", "over90", "total")
    out = []
    for entry in by_party.values():
        out.append({**entry, **{key: js_round(entry[key]) for key in keys}})
    out.sort(key=lambda row: -abs(row["total"]))
    totals = dict.fromkeys(keys, 0)
    for row in out:
        for key in keys:
            totals[key] += row[key]
    return {"rows": out, "totals": totals, "transactionCount": len(rows), "undated": undated, "hasTerms": bool(terms_column)}
