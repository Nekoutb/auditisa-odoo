"""lib/tod-plan.ts: the tests-of-details sampling plan.

key items   = lines at or above the threshold, examined in full
base sample = (population - key items) / TE
sample size = base x the audit-risk-table factor for the CRA, the assurance from
              other substantive procedures and the key items' coverage
selection   = systematic (MUS) over the remaining population, one hook per interval
"""
import random as _random

from ._js import is_finite, js_ceil, js_floor, js_round

TOD_CRAS = ["minimal", "low", "low_sr", "moderate", "high", "high_sr"]
TOD_ASSURANCES = ["little", "some", "corroborative", "persuasive"]

#: Key-item coverage columns of the audit-risk table (percent of population value).
ART_COLS = [0, 10, 30, 50, 70, 90, 100]
N = None
#: MUS factors: CRA x assurance x coverage column; None = no representative sample required.
ART_MUS = {
    "minimal": {"little": [0.5, 0.4, 0.1, N, N, N, N], "some": [0.2, 0.1, N, N, N, N, N], "corroborative": [N, N, N, N, N, N, N], "persuasive": [N, N, N, N, N, N, N]},
    "low": {"little": [1.0, 0.9, 0.7, 0.3, N, N, N], "some": [0.7, 0.6, 0.4, N, N, N, N], "corroborative": [0.3, 0.2, N, N, N, N, N], "persuasive": [N, N, N, N, N, N, N]},
    "low_sr": {"little": [1.4, 1.3, 1.0, 0.7, 0.2, N, N], "some": [1.1, 1.0, 0.7, 0.4, N, N, N], "corroborative": [0.7, 0.6, 0.3, N, N, N, N], "persuasive": [N, N, N, N, N, N, N]},
    "moderate": {"little": [2.1, 2.0, 1.7, 1.4, 0.9, N, N], "some": [1.8, 1.7, 1.4, 1.1, 0.6, N, N], "corroborative": [1.4, 1.3, 1.0, 0.7, 0.2, N, N], "persuasive": [N, N, N, N, N, N, N]},
    "high": {"little": [2.6, 2.5, 2.3, 1.9, 1.4, 0.3, N], "some": [2.4, 2.2, 2.0, 1.7, 1.1, N, N], "corroborative": [1.9, 1.8, 1.6, 1.3, 0.7, N, N], "persuasive": [0.3, 0.2, N, N, N, N, N]},
    "high_sr": {"little": [3.0, 2.9, 2.6, 2.3, 1.8, 0.7, N], "some": [2.7, 2.6, 2.4, 2.0, 1.5, 0.4, N], "corroborative": [2.3, 2.2, 1.9, 1.6, 1.1, N, N], "persuasive": [0.7, 0.6, 0.3, N, N, N, N]},
}


def stable_start_fraction(*parts):
    """A reproducible start from stable identifiers (UAT B79): 32-bit FNV-1a over the
    joined text, reading the first UTF-16 unit of each code point, modulo 1000."""
    h = 2166136261
    for char in "|".join(parts):
        code = ord(char)
        unit = code if code <= 0xFFFF else 0xD800 + ((code - 0x10000) >> 10)
        h = ((h ^ unit) * 16777619) & 0xFFFFFFFF
    return (h % 1000) / 1000


def _round2(value):
    return js_round(value * 100) / 100


def _total(lines):
    total = 0
    for line in lines:
        total += line["amount"]
    return total


def plan_tod(plan_input):
    """Takes {lines, te, threshold?, cra, assurance, startFraction?}."""
    te = plan_input["te"]
    given = plan_input.get("threshold")
    threshold = js_round(given) if given and given > 0 else te
    lines = [l for l in plan_input["lines"] if is_finite(l["amount"]) and l["amount"] > 0]
    population_value = _total(lines)
    key_items = [l for l in lines if l["amount"] >= threshold]
    rest = [l for l in lines if l["amount"] < threshold]
    key_item_value = _total(key_items)
    remaining = population_value - key_item_value
    coverage_pct = (key_item_value / population_value) * 100 if population_value > 0 else 0
    # nearest coverage column at or below the achieved coverage (conservative)
    col = 0
    for i, column in enumerate(ART_COLS):
        if coverage_pct >= column:
            col = i
    factor = ART_MUS[plan_input["cra"]][plan_input["assurance"]][col]
    base_size = remaining / te if te > 0 else 0
    # The size can never exceed the lines left: at the cap the remaining population
    # is examined in full (UAT B79).
    uncapped = 0 if factor is None or remaining <= 0 else js_ceil(base_size * factor)
    full_population = uncapped > 0 and uncapped >= len(rest)
    sample_size = len(rest) if full_population else uncapped
    # Floored, so sample_size x interval never exceeds the remaining value.
    interval = max(1, js_floor(remaining / sample_size)) if sample_size > 0 else None

    sample = []
    if full_population:
        sample.extend(rest)
    elif interval and sample_size > 0:
        given_start = plan_input.get("startFraction")
        fraction = min(0.999, max(0, given_start)) if given_start is not None else _random.random()
        cumulative = 0
        next_hook = js_floor(fraction * interval) + 1
        for line in rest:
            cumulative += line["amount"]
            while cumulative >= next_hook and len(sample) < sample_size:
                # one line is selected once, however many hooks fall inside it
                if not sample or sample[-1] is not line:
                    sample.append(line)
                next_hook += interval
            if len(sample) >= sample_size:
                break

    return {
        "populationValue": _round2(population_value),
        "populationCount": len(lines),
        "te": te,
        "threshold": threshold,
        "keyItems": key_items,
        "keyItemValue": _round2(key_item_value),
        "coveragePct": js_round(coverage_pct * 10) / 10,
        "coverageColumn": ART_COLS[col],
        "remainingValue": _round2(remaining),
        "remainingCount": len(rest),
        "baseSize": js_round(base_size * 10) / 10,
        "factor": factor,
        "computedSize": uncapped,
        "sampleSize": sample_size,
        "interval": interval,
        "sample": sample,
        "itemsDrawn": len(sample),
        "fullPopulation": full_population,
    }
