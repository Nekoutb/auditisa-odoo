"""lib/sampling-params.ts: the A2 sampling parameters (ISA 530).

MUS for tests of details, attribute plans for tests of controls. Sample size is
computed, not typed (R17); every exception projects (R18).
"""
from ._js import is_number, js_ceil, js_round, js_str
from .errors import ServiceError
from .toc_sampling import FREQUENCY_SIZES, LARGE_POPULATION_SIZES

#: Required confidence to MUS confidence factor (section 4.1).
CONFIDENCE_FACTORS = {
    99: 4.6, 98: 3.7, 95: 3.0, 90: 2.3, 85: 1.9, 80: 1.6,
    75: 1.4, 70: 1.2, 65: 1.1, 60: 0.9, 55: 0.8, 50: 0.7,
}

RISK_BAND_CONFIDENCE = {"high": 95, "moderate": 85, "low": 70}

#: Minimum sample by control frequency, read from the single table in toc_sampling (owner's
#: ruling of 2026-11-16). The A2 attribute plan keeps its keys and takes the heavy-reliance
#: column, as it always took the top of each band; many-times-daily uses the > 250 plan.
ATTRIBUTE_SAMPLE_SIZES = {
    "daily": LARGE_POPULATION_SIZES["heavy"],
    "weekly": FREQUENCY_SIZES["weekly"][1],
    "monthly": FREQUENCY_SIZES["monthly"][1],
    "quarterly": FREQUENCY_SIZES["quarterly"][1],
    "annual": FREQUENCY_SIZES["annually"][1],
    "automated": 1,
}

_BY_KEY = {js_str(k): v for k, v in CONFIDENCE_FACTORS.items()}


def confidence_factor(confidence):
    """``CONFIDENCE_FACTORS[confidence]``: JavaScript keys are strings, "95" finds 95."""
    if confidence is None:
        return None
    return _BY_KEY.get(js_str(confidence))


def risk_band_to_confidence(band):
    return RISK_BAND_CONFIDENCE[band]


def _positive(value):
    return is_number(value) and value > 0


def mus_plan(plan_input):
    """Section 4.1 MUS extent. Takes {populationValue, tolerable, expected?, confidence}."""
    tolerable = plan_input.get("tolerable")
    population = plan_input.get("populationValue")
    if not _positive(tolerable):
        raise ServiceError("tolerable-required")
    if not _positive(population):
        raise ServiceError("empty-population")
    factor = confidence_factor(plan_input.get("confidence"))
    if not factor:
        raise ServiceError("invalid-confidence")
    expected = plan_input.get("expected")
    if (0 if expected is None else expected) >= tolerable:
        raise ServiceError("expected-exceeds-tolerable")
    interval = tolerable / factor
    return {"interval": interval, "sampleSize": max(1, js_ceil(population / interval)), "factor": factor}


def attribute_plan(frequency, reliance="heavy"):
    """The A2 attribute plan. ``reliance="normal"`` reads the normal column of the same table."""
    if reliance == "normal":
        if frequency == "daily":
            return {"sampleSize": LARGE_POPULATION_SIZES["normal"]}
        key = "annually" if frequency == "annual" else frequency
        if key in FREQUENCY_SIZES:
            return {"sampleSize": FREQUENCY_SIZES[key][0]}
    return {"sampleSize": ATTRIBUTE_SAMPLE_SIZES[frequency]}


def evaluate_attribute(sample_size, deviations):
    """Section 4.2 deviation evaluation at 95%: "high", "moderate" or "none"."""
    if sample_size >= 60:
        if deviations <= 1:
            return "high"
        return "moderate" if deviations == 2 else "none"
    if sample_size >= 30:
        if deviations == 0:
            return "high"
        return "moderate" if deviations == 1 else "none"
    return "moderate" if deviations == 0 else "none"


def project_mle(items, population_value, sampled_value):
    """Most likely error: per-item misstatement rate, averaged, over the population.
    Items without a book value fall back to the ratio method over the sampled value."""
    rated = [item for item in items if item["bookValue"] != 0]
    if rated:
        total = 0
        for item in rated:
            total += (item["bookValue"] - item["auditedValue"]) / item["bookValue"]
        avg = total / len(rated)
        return {"mle": js_round(avg * population_value), "percentMisstated": avg * 100}
    if not _positive(sampled_value):
        return {"mle": 0, "percentMisstated": 0}
    total = 0
    for item in items:
        total += item["bookValue"] - item["auditedValue"]
    ratio = total / sampled_value
    return {"mle": js_round(ratio * population_value), "percentMisstated": ratio * 100}
