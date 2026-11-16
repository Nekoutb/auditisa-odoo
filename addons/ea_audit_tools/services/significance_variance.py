"""Significant accounts: the prior year, the variance and the flag (owner's mock-up of 2026-11-16).

The prior year of a lead index is summed from the file's one comparative (a prior-year trial
balance, else the prior file's closings, else this year's opening balances), with the same
index resolver as the current year. A movement is flagged when its change passes the
thresholds the team set on the file: the percentage AND the amount, or either one (mode "or").
An account with no prior-year balance is "new": it counts as passing the percentage.
"""
from ._js import js_round

FLAG_MODES = ("and", "or")
DEFAULT_FLAG_MODE = "and"
DEFAULT_FLAG_PCT = 10.0
DEFAULT_FLAG_AMOUNT = 10000000.0


def sums_by_index(balances, index_of):
    """``balances``: (account, amount) pairs. {index: total}; accounts with no index are left out."""
    out = {}
    for account, value in balances:
        index = index_of(account or "")
        if index:
            out[index] = out.get(index, 0) + (value or 0)
    return out


def variance(current, prior):
    """{prior, variance, pct, new} of one index. ``pct``: the change over the prior year's
    size, x 100, to one decimal, None when the prior year is nil. ``new``: no prior-year
    balance, but one this year."""
    current = js_round(current or 0)
    prior = js_round(prior or 0)
    change = current - prior
    pct = None if prior == 0 else js_round(change / abs(prior) * 1000) / 10
    return {"prior": prior, "variance": change, "pct": pct, "new": prior == 0 and current != 0}


def is_flagged(row, mode, pct_limit, amount_limit):
    """``row``: a variance(). Strictly more than each limit; a new account passes the percentage."""
    if row["variance"] == 0:
        return False
    over_pct = row["new"] or (row["pct"] is not None and abs(row["pct"]) > (pct_limit or 0))
    over_amount = abs(row["variance"]) > (amount_limit or 0)
    if mode == "or":
        return over_pct or over_amount
    return over_pct and over_amount
