"""craBoard of lib/cra.ts, without its queries: which cells each row carries, and the suggestions."""
from .assertions import ASSERTIONS
from .cra_model import cra_of, to_tod

_FALLBACK = ("C", "E", "A", "V")


def default_relevance(recorded, risk_assertions):
    """(relevant, defaulted-only) per assertion for a row with no saved cell.

    Assertions recorded on P6.2 or carried by a linked risk are relevant; with neither,
    C, E, A and V by default; RO sits on every row until assessed (F041)."""
    explicit = set(recorded) | set(risk_assertions)
    relevant = set(explicit)
    if not explicit:
        relevant.update(_FALLBACK)
    relevant.add("RO")
    return {code: (code in relevant, code in relevant and code not in explicit) for code in ASSERTIONS}


def suggested_ir(risk_count):
    return "higher" if risk_count else "lower"


def suggested_cr(covering, failed, itgc_state):
    return "rely" if covering > 0 and failed == 0 and itgc_state != "not_support" else "not_rely"


def is_rely_unsupported(covering, itgc_state, basis):
    """ISA 330 para 8: rely with no covering control, or with ITGCs not supporting, needs a basis."""
    return (covering == 0 or itgc_state == "not_support") and not (basis or "").strip()


def cell_tod(ir, cr, significant):
    return to_tod(cra_of(ir, cr), significant)
