"""Procedure design (owner's mock-ups of 2026-11-16, "mock-proc-design"): which library procedures
an account gets, which alternatives the combined risk suggests, and when its design is complete.

A library item is a dict as in data/procedure_library.json: ``code``, ``cycle``, ``kind`` (MSP or
ASP), ``assertions``, ``suggest_levels``, ``suggest_assertions``, ``condition_en``. The levels are
the CRA's: minimal, low, moderate, high, or to_assess while IR or CR is still blank.
"""

ASSERTION_ORDER = ["C", "E", "A", "V", "P", "RO"]
LEVEL_RANK = {"minimal": 0, "low": 1, "moderate": 2, "high": 3}

# Index -> the dataset kind the sample of a test of details is drawn from.
DATASET_KIND = {
    "E": "ar_open_items", "N": "ap_open_items", "K": "fixed_asset_register", "F": "inventory_listing", "C": "bank_statement",
}


def suggestion_level(level):
    """A minimal combined risk takes the Low alternatives; "to assess" suggests nothing."""
    if level == "minimal":
        return "low"
    return level if level in LEVEL_RANK else None


def covered(item, relevant):
    """The relevant assertions of the account that this procedure answers, in the usual order."""
    own = set(item.get("assertions") or ())
    return [code for code in ASSERTION_ORDER if code in own and code in relevant]


def is_locked(item):
    """A mandatory procedure with no condition: ticked on every relevant assertion, never unticked."""
    return item.get("kind") == "MSP" and not item.get("condition_en")


def suggest(item, levels, relevant, failed=()):
    """Why the tool suggests this alternative, or None.

    ``levels`` maps a relevant assertion to its combined level; ``failed`` holds the assertions
    whose tested control was concluded not effective. The highest level wins; a failed control
    suggests the risk-driven alternatives of its assertion that are not Low-only."""
    if item.get("kind") != "ASP":
        return None
    wanted = set(item.get("suggest_assertions") or ())
    rules = set(item.get("suggest_levels") or ())
    best = None
    for code in ASSERTION_ORDER:
        if code not in relevant or code not in wanted:
            continue
        level = suggestion_level(levels.get(code))
        if level in rules and (best is None or LEVEL_RANK[level] > LEVEL_RANK[best["level"]]):
            best = {"why": "risk", "assertion": code, "level": level}
    if best:
        return best
    if rules - {"low"}:
        for code in ASSERTION_ORDER:
            if code in failed and code in relevant and code in wanted:
                return {"why": "control", "assertion": code, "level": None}
    return None


def design_state(levels, relevant, chosen):
    """The account's design: assertions still to assess, High assertions with no alternative yet,
    and whether the design counts as complete.

    ``chosen`` lists the selected procedures as dicts with ``kind`` (MSP, ASP or custom) and
    ``assertions``; a procedure written by the team counts as an alternative."""
    to_assess = [code for code in ASSERTION_ORDER if code in relevant and levels.get(code) not in LEVEL_RANK]
    answered = set()
    for proc in chosen:
        if proc.get("kind") in ("ASP", "custom"):
            answered.update(proc.get("assertions") or ())
    missing = [code for code in ASSERTION_ORDER if code in relevant and levels.get(code) == "high" and code not in answered]
    complete = bool(chosen) and bool(relevant) and not to_assess and not missing
    return {"to_assess": to_assess, "missing_asp": missing, "complete": complete}


def sample_mode(item):
    """What feeds the procedure: a sample to draw, the tool itself (a reconciliation), or nothing."""
    automatable = (item or {}).get("automatable")
    if automatable in ("sample_selection", "cutoff_selection"):
        return "draw"
    if automatable == "reconciliation":
        return "tool"
    return "none"


def dataset_kind(item, index_code):
    """The population a sample is drawn from: the ledger for a cut-off, else the account's sub-ledger."""
    if (item or {}).get("automatable") == "cutoff_selection":
        return "journal_entries"
    return DATASET_KIND.get(index_code)
