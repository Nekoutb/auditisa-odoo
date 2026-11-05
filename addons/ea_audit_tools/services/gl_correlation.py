"""lib/gl-correlation.ts and the route's readers: what is decided without the database.

The aggregates run in models/gl_console.py. Amount convention: signed = debit - credit. Ratios
keep that sign and are None, never Infinity, when the denominator is nil.
"""
import math
import re

from ._js import is_number, js_date_parse, js_floor, js_round, js_str, js_sum, js_trim, to_iso_date, u16_slice
from .errors import ServiceError
from .gl_analytics import js_number, pearson, round2

#: Account codes reach SQL as parameters, but they also reach LIKE patterns.
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$", re.ASCII)
ACCOUNT_CAP = 500
ALL_CAP = 200
DRILL_CAP = 500
PAGE = 100
MAX_ENTRY_ACCOUNTS = 25
MAX_DRILL_ACCOUNTS = 50

RANK_SQL = {
    "abs": "gross DESC, account",
    "net": "net DESC, account",
    "postings": "postings DESC, account",
    "entries": "entries DESC, account",
    "account": "account",
}
MONTH = "coalesce(to_char(journal_date, 'YYYY-MM'), 'n/a')"
WEEKDAY = "coalesce(extract(isodow FROM journal_date)::int::text, 'n/a')"
PERIOD_SQL = {"month": MONTH, "weekday": WEEKDAY}

_MONTH_RE = re.compile(r"^([0-9]{4}-(0[1-9]|1[0-2])|n/a)$")
_WEEKDAY_RE = re.compile(r"^([1-7]|n/a)$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_LIKE_ESCAPE = re.compile(r"([%_\\])")
_URL_ACCOUNT = re.compile(r"^[0-9]{1,12}$")
_TO_HIT = re.compile(r"\bl\.")


def ratio(numerator, denominator):
    """Keeps its sign and refuses to become Infinity."""
    if denominator == 0 or not math.isfinite(denominator):
        return None
    value = numerator / denominator
    return js_round(value * 10000) / 10000 if math.isfinite(value) else None


def clean_accounts(value, maximum):
    """lib: the valid ones, distinct, cut at the maximum; none left refuses."""
    raw = value if isinstance(value, (list, tuple)) else []
    cleaned = list(dict.fromkeys(
        account for account in (js_trim(js_str(item)) for item in raw) if ACCOUNT_RE.match(account)
    ))
    if not cleaned:
        raise ServiceError("invalid-accounts")
    return cleaned[:maximum]


def read_accounts(value, maximum):
    """The route: stricter than the lib, one invalid code or one too many refuses the lot."""
    if not isinstance(value, (list, tuple)):
        raise ServiceError("invalid-accounts")
    cleaned = list(dict.fromkeys(js_trim(js_str(item)) for item in value))
    if not cleaned or len(cleaned) > maximum or not all(ACCOUNT_RE.match(account) for account in cleaned):
        raise ServiceError("invalid-accounts")
    return cleaned


def split_accounts(text):
    """The line filter's text input: /[\\s,;]+/."""
    return [part for part in re.split(r"[\s,;]+", text or "") if part]


def arrival_accounts(value):
    """?accounts= from a lead-schedule figure: digits only, silently filtered, 50 at most."""
    parts = value if isinstance(value, (list, tuple)) else (value or "").split(",")
    return [part for part in (js_trim(js_str(item)) for item in parts) if _URL_ACCOUNT.match(part)][:MAX_DRILL_ACCOUNTS]


def like_term(search):
    """% and _ are LIKE wildcards; a user typing them means the literal character."""
    return _LIKE_ESCAPE.sub(r"\\\1", u16_slice(js_trim(js_str("" if search is None else search)), 0, 60))


def entry_args(mode="any", rank="abs", limit=20, period="month"):
    """Whatever arrives falls back to the source's defaults."""
    cap = ALL_CAP if limit == "all" else js_number(limit) if js_number(limit) in (10, 20, 50) else 20
    return {
        "mode": "all" if mode == "all" else "any",
        "rank": rank if rank in RANK_SQL else "abs",
        "limit": limit if limit == "all" else int(cap),
        "cap": int(cap),
        "period": "weekday" if period == "weekday" else "month",
    }


def shape_accounts(rows, total):
    return {
        "accounts": [
            {
                "account": row["account"], "name": row["name"], "lines": row["lines"], "entries": row["entries"],
                "debit": round2(row["debit"]), "credit": round2(row["credit"]), "signed": round2(row["signed"]),
            }
            for row in rows
        ],
        "total": total,
        "truncated": total > ACCOUNT_CAP,
    }


def shape_entry(selected, args, head, tops, grid):
    shown = [row["account"] for row in tops]
    index = {account: position for position, account in enumerate(shown)}
    by_month = {}
    for row in grid:
        cells = by_month.setdefault(row["m"], [None] * len(shown))
        position = index.get(row["account"])
        if position is not None:
            cells[position] = round2((cells[position] or 0) + row["v"])
    head = head or {}
    return {
        "accounts": selected,
        "mode": args["mode"],
        "rank": args["rank"],
        "period": args["period"],
        "linkedEntries": head.get("entries") or 0,
        "counterpartAccounts": [
            {
                "account": row["account"], "name": row["name"], "net": round2(row["net"]),
                "gross": round2(row["gross"]), "postings": row["postings"], "entries": row["entries"],
            }
            for row in tops
        ],
        "months": [
            {"month": month, "cells": by_month[month], "total": round2(js_sum(value or 0 for value in by_month[month]))}
            for month in sorted(by_month)
        ],
        "totalDebit": round2(head.get("debit") or 0),
        "totalCredit": round2(head.get("credit") or 0),
        "net": round2(head.get("net") or 0),
        "hiddenAccounts": max(0, (head.get("accounts") or 0) - len(shown)),
    }


def read_pair(a, b):
    account_a = js_trim(js_str("" if a is None else a))
    account_b = js_trim(js_str("" if b is None else b))
    if not ACCOUNT_RE.match(account_a) or not ACCOUNT_RE.match(account_b):
        raise ServiceError("invalid-accounts")
    if account_a == account_b:
        raise ServiceError("same-account")
    return account_a, account_b


def shape_correlation(account_a, account_b, rows, common):
    months = [
        {
            "month": row["m"], "aTotal": round2(row["a"]), "bTotal": round2(row["b"]),
            "ratio": ratio(row["a"], row["b"]), "difference": round2(row["a"] - row["b"]),
        }
        for row in rows
    ]
    largest = 0
    largest_month = None
    for month in months:
        if abs(month["difference"]) > abs(largest):
            largest, largest_month = month["difference"], month["month"]
    return {
        "a": account_a,
        "b": account_b,
        "months": months,
        "pearson": pearson([row["a"] for row in rows], [row["b"] for row in rows]),
        "pearsonAbs": pearson([abs(row["a"]) for row in rows], [abs(row["b"]) for row in rows]),
        "commonEntries": common,
        "monthsWithActivity": len([month for month in months if month["aTotal"] != 0 or month["bTotal"] != 0]),
        "totalA": round2(js_sum(row["a"] for row in rows)),
        "totalB": round2(js_sum(row["b"] for row in rows)),
        "largestDifference": round2(largest),
        "largestDifferenceMonth": largest_month,
    }


# ---------------------------------------------------------------------------
# drill-down


def read_drill_filter(raw):
    """The route's whitelist: everything else is dropped. An undefined key stays absent."""
    raw = raw or {}
    filter_ = {"limit": js_number(raw["limit"]) if raw.get("limit") is not None else 100,
               "offset": js_number(raw["offset"]) if raw.get("offset") is not None else 0}
    if "accounts" in raw:
        filter_["accounts"] = read_accounts(raw["accounts"], MAX_DRILL_ACCOUNTS)
    if "entryAccounts" in raw:
        filter_["entryAccounts"] = read_accounts(raw["entryAccounts"], MAX_ENTRY_ACCOUNTS)
    if "entryMode" in raw:
        filter_["entryMode"] = "all" if raw["entryMode"] == "all" else "any"
    for key in ("month", "weekday", "jeNumber", "preparer", "reviewer", "approver", "dateFrom", "dateTo", "journalCode"):
        if key in raw:
            filter_[key] = js_str(raw[key])
    for key in ("wholeEntries", "weekendOnly", "missingReference"):
        if key in raw:
            filter_[key] = raw[key] is True
    for key in ("minAbs", "maxAbs"):
        if key in raw:
            filter_[key] = js_number(raw[key])
    return filter_


def _valid_date(text):
    parsed = js_date_parse("%sT00:00:00Z" % text)
    return parsed is not None and not math.isnan(parsed) and to_iso_date(parsed) == text


def drill_page(filter_):
    limit = js_number(filter_.get("limit", PAGE))
    limit = (js_floor(limit) if math.isfinite(limit) else 0) or PAGE
    offset = js_number(filter_.get("offset", 0))
    offset = (js_floor(offset) if math.isfinite(offset) else 0) or 0
    return int(min(DRILL_CAP, max(1, limit))), int(max(0, offset))


def drill_where(filter_, dataset_id, engagement_id):
    """(join, where, order, params) of the lines behind a cell. Parameter-bound, refusals under
    the source's codes. ``l`` is the alias of ea_audit_gl_line."""
    where = ["l.dataset_id = %(dataset)s", "l.engagement_id = %(engagement)s"]
    params = {"dataset": dataset_id, "engagement": engagement_id}

    def add(value):
        name = "p%d" % len(params)
        params[name] = value
        return "%%(%s)s" % name

    if "accounts" in filter_:
        where.append("l.account = ANY(%s::text[])" % add(clean_accounts(filter_["accounts"], MAX_DRILL_ACCOUNTS)))
    if "month" in filter_:
        month = js_trim(js_str(filter_["month"]))
        if not _MONTH_RE.match(month):
            raise ServiceError("invalid-month")
        where.append("coalesce(to_char(l.journal_date, 'YYYY-MM'), 'n/a') = %s" % add(month))
    if "weekday" in filter_:
        weekday = js_trim(js_str(filter_["weekday"]))
        if not _WEEKDAY_RE.match(weekday):
            raise ServiceError("invalid-weekday")
        where.append("%s = %s" % (WEEKDAY.replace("journal_date", "l.journal_date"), add(weekday)))
    if "jeNumber" in filter_:
        where.append("l.je_number = %s" % add(u16_slice(js_trim(js_str(filter_["jeNumber"])), 0, 100)))
    for key in ("preparer", "reviewer", "approver"):
        if key in filter_:
            where.append("coalesce(trim(l.%s), '') = %s" % (key, add(u16_slice(js_trim(js_str(filter_[key])), 0, 200))))
    for key, operator in (("minAbs", ">="), ("maxAbs", "<=")):
        if key in filter_:
            amount = js_number(filter_[key])
            if not math.isfinite(amount) or amount < 0:
                raise ServiceError("invalid-amount")
            where.append("abs(l.signed) %s %s::numeric" % (operator, add(amount)))
    for key, operator in (("dateFrom", ">="), ("dateTo", "<=")):
        if key in filter_:
            text = js_trim(js_str(filter_[key]))
            if not _DATE_RE.match(text) or not _valid_date(text):
                raise ServiceError("invalid-date")
            where.append("l.journal_date %s %s::date" % (operator, add(text)))
    if "journalCode" in filter_:
        where.append("coalesce(trim(l.journal_code), '') = %s" % add(u16_slice(js_trim(js_str(filter_["journalCode"])), 0, 50)))
    if filter_.get("weekendOnly"):
        where.append("extract(isodow FROM l.journal_date) IN (6, 7)")
    if filter_.get("missingReference"):
        where.append("coalesce(trim(l.reference), '') = ''")

    # entry-level: keep every line of the entries touching the chosen accounts
    join = ""
    if "entryAccounts" in filter_:
        accounts = clean_accounts(filter_["entryAccounts"], MAX_ENTRY_ACCOUNTS)
        need = len(accounts) if filter_.get("entryMode") == "all" else 1
        accounts_param, need_param = add(accounts), add(need)
        join = (
            "JOIN (SELECT je_number FROM ea_audit_gl_line"
            " WHERE dataset_id = %%(dataset)s AND engagement_id = %%(engagement)s GROUP BY je_number"
            " HAVING count(DISTINCT account) FILTER (WHERE account = ANY(%s::text[])) >= %s::int"
            ") ent ON ent.je_number = l.je_number"
        ) % (accounts_param, need_param)

    # whole entries: the filter finds the hit lines, the page shows every line of their entries
    if filter_.get("wholeEntries"):
        inner_join = _TO_HIT.sub("h.", join)
        inner_where = _TO_HIT.sub("h.", " AND ".join(where))
        clause = (
            "l.dataset_id = %%(dataset)s AND l.engagement_id = %%(engagement)s AND l.je_number IN"
            " (SELECT h.je_number FROM ea_audit_gl_line h %s WHERE %s)"
        ) % (inner_join, inner_where)
        return "", clause, "l.je_number, l.line_no", params
    return join, " AND ".join(where), "l.journal_date NULLS LAST, l.je_number, l.line_no", params


def shape_drill(rows, total, sum_signed, limit, offset):
    return {
        "lines": [
            {
                "lineNo": row["line_no"], "account": row["account"], "accountName": row["account_name"],
                "jeNumber": row["je_number"], "journalCode": row["journal_code"], "journalDate": row["journal_date"],
                "entryDate": row["entry_date"], "reference": row["reference"], "lineDescription": row["line_description"],
                "thirdPartyCode": row["third_party_code"], "thirdPartyName": row["third_party_name"],
                "preparer": row["preparer"], "reviewer": row["reviewer"],
                "debit": round2(row["debit"]), "credit": round2(row["credit"]), "signed": round2(row["signed"]),
            }
            for row in rows
        ],
        "total": total,
        "sumSigned": round2(sum_signed),
        "limit": limit,
        "offset": offset,
    }


def reconcile_figure(opening, closing, sum_signed, lines):
    """UAT run 2 B68: opening + every matching movement must give the balance clicked."""
    computed = opening + sum_signed
    return {
        "opening": opening, "movements": sum_signed, "lines": lines, "computed": computed,
        "closing": closing, "gap": js_round(closing - computed),
    }


def amount_input(text):
    """The line filter's amount box: spaces out, a decimal comma, None when it is not a number."""
    number = js_number(re.sub(r"\s", "", js_str(text)).replace(",", "."))
    return number if is_number(number) and math.isfinite(number) else None
