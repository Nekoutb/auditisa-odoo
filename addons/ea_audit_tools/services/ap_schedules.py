"""apLeadSchedules of lib/analytical-procedures.ts: the Lead Schedule tool, account by account."""
from ._js import js_round
from .lead_classes import LEAD_INDEXES, lead_index_for


def _pct(movement, prior):
    return js_round((movement / abs(prior)) * 1000) / 10 if prior != 0 else None


def index_resolver(overrides):
    """Longest client prefix wins, else the SYSCOHADA map. ``overrides``: (prefix, code) pairs."""
    ordered = sorted(overrides, key=lambda pair: -len(pair[0]))

    def index_of(account):
        for prefix, code in ordered:
            if account.startswith(prefix):
                return code
        return lead_index_for(account)

    return index_of


def ap_lead_schedules(rows, prior_closings, overrides=()):
    """``rows``: {account, name, opening, closing} sorted by account; ``prior_closings``:
    {account: closing} of a valid prior-year TB. An empty map means the current TB's
    opening balances stand in (UAT B81). Accounts with no index are left out."""
    index_of = index_resolver(overrides)
    use_prior_tb = bool(prior_closings)
    by_index = {}
    for row in rows:
        index = index_of(row["account"])
        if not index:
            continue
        closing = js_round(row["closing"])
        prior = js_round(prior_closings.get(row["account"], 0) if use_prior_tb else row["opening"])
        by_index.setdefault(index, []).append({
            "account": row["account"],
            "name": row.get("name") or "—",
            "closing": closing,
            "prior": prior,
            "opening": js_round(row["opening"]),
            "movement": closing - prior,
            "variancePct": _pct(closing - prior, prior),
        })
    out = []
    for definition in LEAD_INDEXES:
        accounts = by_index.get(definition["code"])
        if not accounts:
            continue
        closing = 0
        prior = 0
        for account in accounts:
            closing += account["closing"]
            prior += account["prior"]
        out.append({
            "index": definition["code"],
            "definition": definition,
            "accounts": accounts,
            "closing": closing,
            "prior": prior,
            "movement": closing - prior,
            "variancePct": _pct(closing - prior, prior),
            "priorSource": "prior_year_tb" if use_prior_tb else "opening",
        })
    return out
