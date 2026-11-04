"""The calculation half of lib/materiality.ts. Versions and approval stay in the model."""
from ._js import js_round
from .fs_captions import bilan_totals
from .materiality_model import PERFORMANCE_PCT_RANGE, TRIVIAL_PCT_RANGE

BENCHMARKS = ("pbt", "revenue", "total_assets", "equity", "expenses")

BENCHMARK_RANGES = {
    "pbt": {"min": 5, "max": 10},
    "revenue": {"min": 0.5, "max": 2},
    "total_assets": {"min": 0.5, "max": 2},
    "equity": {"min": 1, "max": 5},
    "expenses": {"min": 0.5, "max": 2},
}

_EQUITY_PREFIXES = ("10", "11", "12", "13", "14", "15")


def compute_materiality(benchmark_amount, percentage, performance_pct, trivial_pct):
    overall = js_round(benchmark_amount * (percentage / 100))
    return {
        "overall": overall,
        "performance": js_round(overall * (performance_pct / 100)),
        "trivial": js_round(overall * (trivial_pct / 100)),
    }


def materiality_deviations(benchmark, benchmark_amount, percentage, tb_bases):
    """The percentage outside the benchmark's range; the amount more than 0.5 % from the TB base."""
    bounds = BENCHMARK_RANGES.get(benchmark)
    out_of_range = bool(bounds) and (percentage < bounds["min"] or percentage > bounds["max"])
    base = abs(tb_bases.get(benchmark) or 0) if tb_bases else 0
    mismatch = base > 0 and abs(abs(benchmark_amount) - base) > max(1, base * 0.005)
    return {"outOfRange": out_of_range, "basisMismatch": mismatch}


def tb_benchmark_amounts(rows):
    """Benchmark bases from {account, value} closings. None without rows.

    As the source: PBT is class 7 less class 6, where the SAD's income before tax
    (fs_captions.income_from_tb) also takes class 8. See QUESTIONS.md.
    """
    if not rows:
        return None
    cl6 = 0
    cl7 = 0
    equity = 0
    for row in rows:
        account = row["account"]
        if account[:1] == "6":
            cl6 += row["value"]
        elif account[:1] == "7":
            cl7 += row["value"]
        if account[:2] in _EQUITY_PREFIXES:
            equity += row["value"]
    revenue = js_round(-cl7)
    expenses = js_round(cl6)
    return {
        "revenue": max(0, revenue),
        "expenses": max(0, expenses),
        "pbt": revenue - expenses,
        "equity": max(0, js_round(-equity)),
        "total_assets": js_round(bilan_totals(rows)["totalAssets"]),
    }


def validate_version(benchmark_amount, percentage, performance_pct, trivial_pct):
    """The refusal of the version's range check, or None. New versions only."""
    if (
        benchmark_amount <= 0
        or percentage <= 0
        or percentage > 100
        or performance_pct < PERFORMANCE_PCT_RANGE["min"]
        or performance_pct > PERFORMANCE_PCT_RANGE["max"]
        or trivial_pct < TRIVIAL_PCT_RANGE["min"]
        or trivial_pct > TRIVIAL_PCT_RANGE["max"]
    ):
        return "invalid-materiality"
    return None


def midpoint(benchmark):
    bounds = BENCHMARK_RANGES[benchmark]
    return (bounds["min"] + bounds["max"]) / 2
