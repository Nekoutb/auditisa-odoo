"""The pure part of lib/deficiencies.ts and of evaluateB5 in lib/execution.ts."""
from .materiality_model import uncorrected_misstatement_threshold

FINDING_SEVERITIES = ("significant_deficiency", "deficiency", "observation")
LIKELIHOODS = ("remote", "reasonably_possible", "probable")
MAGNITUDES = ("inconsequential", "significant", "material")


def suggested_grade(likelihood, magnitude):
    """ISA 265 A5. A suggestion the preparer confirms or overrides."""
    if not likelihood or not magnitude:
        return None
    if magnitude == "material" and likelihood != "remote":
        return "significant_deficiency"
    if magnitude == "inconsequential" and likelihood == "remote":
        return "observation"
    return "deficiency"


def evaluate_b5(items, materiality):
    """``items``: {amount, corrected, trivial}; ``materiality``: {overall, performance, trivial} or None.

    One threshold everywhere: uncorrected misstatements against UMT = overall - performance
    (UAT B50). As the source, signed amounts are summed, so opposite items net.
    """
    uncorrected = 0
    corrected = 0
    trivial_count = 0
    for item in items:
        if item["trivial"]:
            trivial_count += 1
        elif item["corrected"]:
            corrected += item["amount"]
        else:
            uncorrected += item["amount"]
    final = uncorrected_misstatement_threshold(materiality)
    return {
        "uncorrectedTotal": uncorrected,
        "correctedTotal": corrected,
        "trivialCount": trivial_count,
        "finalMateriality": final,
        "trivialThreshold": materiality["trivial"] if materiality else None,
        "exceedsMateriality": None if final is None else abs(uncorrected) > final,
    }
