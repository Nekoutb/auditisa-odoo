"""Significant accounts: prior year, variance and the flag (owner's mock-up of 2026-11-16)."""
from services.ap_schedules import index_resolver
from services.significance_variance import is_flagged, sums_by_index, variance


def test_the_prior_year_is_summed_per_index_with_the_clients_prefixes():
    balances = [("411000", 800), ("411200", 100), ("701000", -50), ("999999", 7)]
    assert sums_by_index(balances, index_resolver([])) == {"E": 900, "UA": -50}
    assert sums_by_index(balances, index_resolver([("4112", "N")])) == {"E": 800, "N": 100, "UA": -50}


def test_variance_and_its_percentage_over_the_prior_years_size():
    assert variance(412560300, 298004100) == {"prior": 298004100, "variance": 114556200, "pct": 38.4, "new": False}
    assert variance(96400000, 158900000)["pct"] == -39.3
    # a credit balance that grew: the change over the size of last year, negative
    row = variance(-980300000, -702100000)
    assert row["variance"] == -278200000 and row["pct"] == -39.6


def test_no_prior_year_is_new_and_has_no_percentage():
    assert variance(-2300000, 0) == {"prior": 0, "variance": -2300000, "pct": None, "new": True}
    assert variance(0, 0) == {"prior": 0, "variance": 0, "pct": None, "new": False}


def test_and_needs_both_limits_or_needs_either():
    big_pct_small_amount = variance(8120000, 4060000)  # 100 %, 4 060 000
    assert not is_flagged(big_pct_small_amount, "and", 10, 10000000)
    assert is_flagged(big_pct_small_amount, "or", 10, 10000000)
    small_pct_big_amount = variance(6230000000, 6180500000)  # 0.8 %, 49 500 000
    assert not is_flagged(small_pct_big_amount, "and", 10, 10000000)
    assert is_flagged(small_pct_big_amount, "or", 10, 10000000)
    both = variance(412560300, 298004100)
    assert is_flagged(both, "and", 10, 10000000)
    # strictly more than: exactly 10 % is not flagged
    assert not is_flagged(variance(110, 100), "or", 10, 1000)


def test_a_new_account_passes_the_percentage_only():
    new = variance(-2300000, 0)
    assert not is_flagged(new, "and", 10, 10000000)
    assert is_flagged(new, "and", 10, 1000000)
    assert is_flagged(new, "or", 10, 10000000)
    assert not is_flagged(variance(0, 0), "or", 0, 0)
