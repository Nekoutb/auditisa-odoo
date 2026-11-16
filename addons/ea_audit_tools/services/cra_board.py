"""craBoard of lib/cra.ts, without its queries: which cells each row carries, and the suggestions."""
from .assertions import ASSERTIONS
from .cra_model import cra_of, to_tod, worst_tod

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


def cell_level(ir, cr):
    """The combined level of a cell: "to_assess" until someone has chosen BOTH risks.
    A suggestion is a hint shown beside the choice, never a level (owner, 2026-11-16)."""
    if not ir or not cr:
        return "to_assess"
    return cra_of(ir, cr)


def row_worst_tod(cells):
    """The account's level for sampling: the worst of its kept cells, or None while one of them
    is still to assess (a partial worst would understate the account).

    ``cells`` are dicts with ir, cr, significant and kept (relevant, and not the RO that sits
    on the row only by default and unassessed, F041)."""
    kept = [cell for cell in cells if cell["kept"]]
    if not kept or any(not cell["ir"] or not cell["cr"] for cell in kept):
        return None
    return worst_tod([cell_tod(cell["ir"], cell["cr"], cell["significant"]) for cell in kept])


def page_progress(cells):
    """(assessed, total) over the cells the page shows: the relevant ones."""
    shown = [cell for cell in cells if cell["relevant"]]
    return len([cell for cell in shown if cell["ir"] and cell["cr"]]), len(shown)
