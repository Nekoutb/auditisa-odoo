"""The arithmetic of lib/sad.ts and of the SAD workbook, shared by the screen and the export."""
from ._js import js_round
from .fs_captions import bilan_totals, income_from_tb
from .sad_model import SAD_COLUMN_COUNT, caption_column, suggest_caption

MAIN_TYPES = ("factual", "judgmental", "projected")


def fs_caption_amounts(balances):
    """One total per grid column, credit-positive for liabilities and equity. None with no TB.
    The balance-sheet columns come from the one bilan (F013), the rest by suggested caption."""
    if not balances:
        return None
    columns = [0] * SAD_COLUMN_COUNT
    for row in balances:
        if row["account"][:1] in ("2", "3", "4", "5"):
            continue
        columns[caption_column(suggest_caption(row["account"]))] -= row["value"]
    bilan = bilan_totals(balances)
    columns[caption_column("current_asset")] = bilan["currentAssets"]
    columns[caption_column("non_current_asset")] = bilan["fixedAssets"]
    columns[caption_column("current_liability")] = bilan["currentLiabilities"]
    income = income_from_tb(balances)
    return {
        "columns": [js_round(value) for value in columns],
        "incomeBeforeTax": js_round(income["beforeTax"]),
        "netResultAfterTax": js_round(income["netResult"]),
    }


def entry_amount(entry):
    return max(abs(entry["drAmount"]), abs(entry["crAmount"]))


def is_trivial(entry, nominal):
    """ISA 450 para 5: clearly trivial items are listed apart, never accumulated (UAT B51)."""
    return nominal is not None and entry_amount(entry) < nominal


def grid_totals(entries):
    totals = [0] * SAD_COLUMN_COUNT
    for entry in entries:
        totals[caption_column(entry["drCaption"])] += entry["drAmount"]
        totals[caption_column(entry["crCaption"])] -= entry["crAmount"]
    return totals


def uncorrected_cascade(income_column_total, meta):
    """The tax and turnaround cascade of the uncorrected tab and the conclusion's four columns."""
    rate = (meta.get("tax_rate") if meta.get("tax_rate") is not None else 33) / 100
    tax_effect = -income_column_total * rate
    after_tax = income_column_total + tax_effect
    turnaround_f = meta.get("turnaround_factual") or 0
    turnaround_j = meta.get("turnaround_judgmental") or 0
    cumulative = after_tax + (turnaround_f + turnaround_j) * (1 - rate)
    return {
        "rate": rate,
        "taxEffect": tax_effect,
        "afterTax": after_tax,
        "turnaroundFactual": turnaround_f,
        "turnaroundJudgmental": turnaround_j,
        "cumulative": cumulative,
        "series": [
            income_column_total,
            income_column_total + turnaround_f + turnaround_j,
            after_tax,
            cumulative,
        ],
    }
