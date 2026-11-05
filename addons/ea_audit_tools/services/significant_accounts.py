"""lib/significant-accounts.ts, without its queries (P6.2)."""
from ._js import js_round
from .lead_classes import LEAD_INDEXES


def significance_rows(closings, tolerable_error, specific, decisions, risk_assertions):
    """One row per lead index carrying a TB balance, in LEAD_INDEXES order.

    ``closings``: {index: closing}; ``specific``: {index: lower threshold};
    ``decisions``: {index: {status, justification}}; ``risk_assertions``: {index: set}.
    A specific materiality replaces TE for the default; a linked live risk makes the
    index significant regardless of size (ISA 315 para 12(k)).
    """
    rows = []
    for definition in LEAD_INDEXES:
        code = definition["code"]
        if code not in closings:
            continue
        closing = js_round(closings[code])
        specific_te = specific.get(code)
        threshold = specific_te if specific_te is not None else tolerable_error
        above_te = threshold is not None and abs(closing) > threshold
        has_risk = code in risk_assertions
        default_status = "significant" if above_te or has_risk else "not_significant"
        decision = decisions.get(code) or {}
        recorded = decision.get("status")
        status = recorded if recorded in ("significant", "not_significant") else default_status
        rows.append({
            "index": code,
            "closing": closing,
            "aboveTe": above_te,
            "specificTe": specific_te,
            "defaultStatus": default_status,
            "status": status,
            "overridden": status != default_status,
            "justification": decision.get("justification") or "",
            "hasRisk": has_risk,
        })
    return rows


def unjustified_count(rows):
    """Departures from the default with no written reason: P6.2 refuses signature on any."""
    return len([row for row in rows if row["overridden"] and not row["justification"].strip()])


def specific_refusal(amount, overall, performance):
    """ISA 320 para 10: a specific materiality sits below overall, and below TE (UAT B43)."""
    if overall is None or not amount or amount <= 0:
        return None
    if amount >= overall:
        return "specific-above-materiality"
    if amount >= performance:
        return "specific-above-te"
    return None
