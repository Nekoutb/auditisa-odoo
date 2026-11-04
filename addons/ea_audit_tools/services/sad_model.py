"""lib/sad-model.ts: the Summary of Audit Differences, its captions and columns."""
import re

SAD_CAPTIONS = [
    "current_asset",
    "non_current_asset",
    "current_liability",
    "non_current_liability",
    "equity",
    "income",
    "expense",
]

#: Income and expense share a column but are distinct captions, with distinct labels.
SAD_CAPTION_LABELS = {
    "current_asset": {"en": "Assets Current", "fr": "Actif courant"},
    "non_current_asset": {"en": "Assets Non-current", "fr": "Actif non courant"},
    "current_liability": {"en": "Liabilities Current", "fr": "Passif courant"},
    "non_current_liability": {"en": "Liabilities Non-current", "fr": "Passif non courant"},
    "equity": {"en": "Equity components", "fr": "Capitaux propres"},
    "income": {"en": "Income statement — income", "fr": "Résultat — produits"},
    "expense": {"en": "Income statement — expenses", "fr": "Résultat — charges"},
}

SAD_TYPES = ["factual", "judgmental", "projected", "classification", "disclosure"]

MISSTATEMENT_TYPE_LABELS = {
    "factual": {"en": "factual", "fr": "avérée"},
    "judgmental": {"en": "judgmental", "fr": "de jugement"},
    "projected": {"en": "projected", "fr": "extrapolée"},
    "classification": {"en": "reclassification", "fr": "reclassement"},
    "disclosure": {"en": "disclosure", "fr": "information annexe"},
}

#: The six columns of the workbook's caption grid.
SAD_COLUMN_COUNT = 6

#: Qualitative factors the conclusion tab walks through (ISA 450 A21).
SAD_QUAL_FACTORS = ["sensitivity", "subtotals", "balance_sheet", "covenants", "loss_reversal", "segments", "trend_mask", "bias"]

_COLUMNS = {
    "current_asset": 0,
    "non_current_asset": 1,
    "current_liability": 2,
    "non_current_liability": 3,
    "equity": 4,
    "income": 5,
    "expense": 5,
}


def caption_column(caption):
    """The grid column a caption lands in; None for an unknown caption."""
    return _COLUMNS.get(caption)


def suggest_caption(account):
    """SYSCOHADA caption suggestion from the account number's leading digits.
    A suggestion only: the preparer's recorded caption always wins."""
    a = re.sub(r"[^0-9]", "", account)
    if not a:
        return "current_asset"
    d1 = a[0]
    d2 = a[:2]
    if d1 == "1":
        return "equity" if d2 in ("10", "11", "12", "13", "14", "15") else "non_current_liability"
    if d1 == "2":
        return "non_current_asset"
    if d1 == "3":
        return "current_asset"
    if d1 == "4":
        return "current_asset" if d2 in ("41", "45", "47", "49") else "current_liability"
    if d1 == "5":
        return "current_liability" if d2 == "56" else "current_asset"
    if d1 == "6":
        return "expense"
    if d1 == "7":
        return "income"
    if d1 == "8":
        second = int(d2[1]) if len(d2) > 1 else 1
        return "expense" if second % 2 == 1 else "income"
    return "current_asset"
