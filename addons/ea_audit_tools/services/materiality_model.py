"""lib/materiality-model.ts: the materiality thresholds, with no database behind them."""

#: The firm's ranges for the two derived thresholds, as a percentage of overall
#: materiality. F033 narrowed the clearly trivial range to 3-5%: only new versions
#: are constrained, a stored value outside the range keeps displaying.
PERFORMANCE_PCT_RANGE = {"min": 60, "max": 85, "default": 75}
TRIVIAL_PCT_RANGE = {"min": 3, "max": 5, "default": 5}

_BENCHMARKS = {
    "pbt": ("Profit before tax", "Résultat avant impôt"),
    "revenue": ("Revenue", "Chiffre d'affaires"),
    "total_assets": ("Total assets", "Total de l'actif"),
    "equity": ("Equity", "Capitaux propres"),
    "expenses": ("Total expenses", "Total des charges"),
}


def uncorrected_misstatement_threshold(mat):
    """UMT = overall - performance, never negative; None without a materiality."""
    if not mat:
        return None
    return max(0, mat["overall"] - mat["performance"])


def benchmark_label(benchmark, fr):
    """A materiality benchmark's name in the reader's language."""
    pair = _BENCHMARKS.get(benchmark)
    if not pair:
        return benchmark
    return pair[1] if fr else pair[0]
