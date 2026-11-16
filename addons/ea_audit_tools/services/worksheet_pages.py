"""The findings page and the SAD page (owner's mock-ups of 2026-11-16): where each finding
stands, and what each audit difference does to profit, assets, liabilities and equity.
Pure, so the tests read the rules without Odoo."""
from ._js import js_round
from .sad_view import grid_totals

#: The five stages, in order. Each is read from what is already recorded, never stored.
STAGES = ("raised", "assessed", "discussed", "reported", "closed")


def finding_stage(route, status, severity, has_evaluation, has_answer, communicated):
    """Where a finding stands.

    - closed: cleared with a response;
    - reported: an ISA 265 deficiency communicated in writing (date recorded);
    - discussed: management's answer is written;
    - assessed: a deficiency with its ISA 265 evaluation, a misstatement (it stands on the SAD
      with its amount and type), or a matter for attention with a grade;
    - raised: otherwise.
    """
    if status == "cleared":
        return "closed"
    if route == "c1" and communicated:
        return "reported"
    if has_answer:
        return "discussed"
    if (route == "c1" and has_evaluation) or route == "b5" or (route == "b4" and severity):
        return "assessed"
    return "raised"


def stage_steps(route, stage):
    """The five chips of one finding: done, current, to do, or skipped (only a deficiency is
    reported in writing under ISA 265)."""
    reached = STAGES.index(stage)
    steps = []
    for index, key in enumerate(STAGES):
        if key == "reported" and route != "c1":
            state = "skipped"
        elif index < reached:
            state = "done"
        elif index == reached:
            state = "done" if key == "closed" else "current"
        else:
            state = "todo"
        steps.append({"key": key, "state": state})
    return steps


def findings_summary(rows):
    """``rows``: {route, severity, stage}. The cards, the progress bar and the tab counts."""
    counts = {key: 0 for key in STAGES}
    significant = significant_open = not_reported = linked = 0
    for row in rows:
        counts[row["stage"]] += 1
        if row["severity"] == "significant_deficiency":
            significant += 1
            if row["stage"] not in ("reported", "closed"):
                significant_open += 1
        if row["route"] == "c1" and row["stage"] not in ("reported", "closed"):
            not_reported += 1
        if row["route"] == "b5":
            linked += 1
    return {
        "total": len(rows),
        "stages": counts,
        "closed": counts["closed"],
        "waiting": counts["assessed"],
        "significant": significant,
        "significantNotReported": significant_open,
        "notReported": not_reported,
        "linked": linked,
    }


def _clean(value):
    """-0 reads 0."""
    return value + 0.0


def sad_effects(entry):
    """``entry``: {drAmount, crAmount, drCaption, crCaption}. What the difference does, each
    figure positive when it raises the item: profit before tax, assets, liabilities, equity.
    A debit raises an asset and an expense, a credit raises a liability, equity and income."""
    columns = grid_totals([entry])
    return {
        "profit": _clean(-columns[5]),
        "assets": _clean(columns[0] + columns[1]),
        "liabilities": _clean(-(columns[2] + columns[3])),
        "equity": _clean(-columns[4]),
    }


def sad_totals(effects):
    totals = {"profit": 0.0, "assets": 0.0, "liabilities": 0.0, "equity": 0.0}
    for effect in effects:
        for key in totals:
            totals[key] += effect[key]
    return {key: _clean(value) for key, value in totals.items()}


def after_tax(profit, tax_rate):
    """The profit effect after tax, at the SAD's rate (per cent; 33 when none is entered)."""
    rate = (tax_rate if tax_rate is not None else 33) / 100
    return _clean(js_round(profit * (1 - rate) * 100) / 100)


def materiality_bar(uncorrected, materiality, threshold):
    """The bar at the top of the SAD: the uncorrected total against the clearly trivial,
    performance and overall levels, as percentages of the bar's width. ``threshold`` is the
    one the archive and C1.1 read (ISA 450, overall - performance); its verdict is the level:
    over when above it, close from three quarters of it, under below. None without an
    approved materiality."""
    if not materiality:
        return None
    total = abs(uncorrected or 0)
    top = max(materiality["overall"] or 0, total) or 1

    def at(value):
        return min(100.0, max(0.0, 100.0 * (value or 0) / top))

    if threshold is None:
        level = "under"
    elif total > threshold:
        level = "over"
    elif threshold and total >= 0.75 * threshold:
        level = "close"
    else:
        level = "under"
    return {
        "fill": at(total),
        "trivial": at(materiality["trivial"]),
        "threshold": at(threshold) if threshold is not None else None,
        "performance": at(materiality["performance"]),
        "overall": at(materiality["overall"]),
        "level": level,
        "share": int(100.0 * total / threshold + 0.5) if threshold else None,
    }
