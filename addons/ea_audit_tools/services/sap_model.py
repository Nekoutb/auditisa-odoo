"""lib/sap-model.ts: substantive analytical procedures (F038), the pure part.

The acceptable difference (ISA 520 para 5(d)) is a share of performance
materiality scaled by the CRA level: the more risk, the smaller the difference.
"""
from ._js import is_integer, js_round

DEFAULT_SAP_THRESHOLDS = {"low": 75, "moderate": 50, "high": 25}

SAP_PCT_MIN = 1
SAP_PCT_MAX = 100

#: The assertions a procedure may address: the S3.1 vocabulary.
SAP_ASSERTIONS = ["C", "E", "A", "V", "P"]

_LABELS_EN = {"C": "Completeness", "E": "Existence / occurrence", "A": "Accuracy / cut-off", "V": "Valuation", "P": "Presentation"}
_LABELS_FR = {"C": "Exhaustivité", "E": "Existence / réalité", "A": "Exactitude / séparation", "V": "Évaluation", "P": "Présentation"}


def sap_assertion_label(assertion, locale):
    return (_LABELS_FR if locale == "fr" else _LABELS_EN).get(assertion)


def is_sap_assertion(value):
    return isinstance(value, str) and value in SAP_ASSERTIONS


def is_sap_pct(value):
    return is_integer(value) and SAP_PCT_MIN <= value <= SAP_PCT_MAX


def threshold_pct_for(level, thresholds):
    """The firm's percentage for a CRA level. No CRA recorded is treated as high."""
    if level in ("minimal", "low"):
        return thresholds["low"]
    if level == "moderate":
        return thresholds["moderate"]
    return thresholds["high"]


def evaluate_sap(args):
    """Takes {expected, actual, performanceMateriality, pct}."""
    performance = args["performanceMateriality"]
    actual = args["actual"]
    threshold = None if performance is None else js_round((performance * args["pct"]) / 100)
    difference = None if actual is None else js_round(actual - args["expected"])
    exceeds = None if threshold is None or difference is None else abs(difference) > threshold
    return {"threshold": threshold, "difference": difference, "exceeds": exceeds}
