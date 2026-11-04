"""lib/cra-model.ts: the Combined Risk Assessment model.

Inherent and control risk are assessed per relevant assertion (ISA 315 para 34)
and combine into one of four levels that calibrate the substantive response
(ISA 330 para 7). A significant risk overlays the level, it adds no fifth one.
"""

#: Stored as this one English constant; the board renders it in the reader's language.
CR_DEFICIENT_BASIS = "Not rely — due to deficient control conclusion under E1.2"

_TOD_RANK = {"minimal": 0, "low": 1, "low_sr": 2, "moderate": 3, "high": 4, "high_sr": 5}
_MISSING = object()


def cr_basis_label(basis, locale):
    """The stored basis text in the reader's language."""
    if locale != "fr":
        return basis
    fr = "Sans appui — conclusion de contrôle déficiente en E1.2"
    return " · ".join(fr if part == CR_DEFICIENT_BASIS else part for part in basis.split(" · "))


def cra_of(ir, cr):
    """The IR x CR matrix. Rows: lower/higher inherent risk. Columns: rely/not rely."""
    if ir == "lower":
        return "minimal" if cr == "rely" else "moderate"
    return "low" if cr == "rely" else "high"


def to_tod(level, significant):
    """Sampling-tool value with the significant-risk overlay."""
    if not significant:
        return level
    if level in ("minimal", "low"):
        return "low_sr"
    return "high_sr"


def worst_tod(values):
    """The most severe value of a set; None for an empty set."""
    if not values:
        return None
    worst = values[0]
    for value in values[1:]:
        if _TOD_RANK[value] > _TOD_RANK[worst]:
            worst = value
    return worst


def cells_to_assess(rows):
    """The relevant cells with no inherent or no control risk recorded (null, not absent)."""
    out = []
    for row in rows:
        for cell in row["cells"]:
            if cell.get("relevant") and (cell.get("ir", _MISSING) is None or cell.get("cr", _MISSING) is None):
                out.append({"indexCode": row["indexCode"], "assertion": cell["assertion"]})
    return out


def cra_level_label(level, locale):
    if locale == "fr":
        return {"minimal": "Minimal", "low": "Faible", "moderate": "Modéré", "high": "Élevé"}.get(level)
    return {"minimal": "Minimal", "low": "Low", "moderate": "Moderate", "high": "High"}.get(level)


def tod_label(value, locale):
    base = cra_level_label(value.replace("_sr", "", 1), locale)
    return "%s +SR" % base if value.endswith("_sr") else base


def cra_tone(level):
    """Chip tone per level, shared by the matrix, S5.5 and the E4 header."""
    if level in ("minimal", "low"):
        return "good"
    if level == "moderate":
        return "warn"
    return "rose"


_THRESHOLDS = {
    "minimal": ("75–100%", "25–50%"),
    "low": ("50–75%", "15–25%"),
    "moderate": ("25–50%", "10–15%"),
    "high": ("10–25%", "5–10%"),
}


def threshold_suggestion(level, locale):
    """Key-item testing threshold guidance, as a fraction of tolerable error."""
    ai, le = _THRESHOLDS[level]
    if locale == "fr":
        return "Éléments clés — actif/produits : seuil ≈ %s de l'ET · passif/charges : ≈ %s" % (ai, le)
    return "Key items — assets/income: threshold ≈ %s of TE · liabilities/expense: ≈ %s" % (ai, le)


_TIMING_EN = {
    "minimal": "Interim possible up to ~6 months before the period end, with rollforward",
    "low": "Interim possible up to ~3 months before the period end, with rollforward",
    "moderate": "At or near the period end (interim at most ~1 month before)",
    "high": "At or near the period end (interim at most ~1 month before)",
}
_TIMING_FR = {
    "minimal": "Intercalaire possible jusqu'à ~6 mois avant la clôture, avec travaux de liaison",
    "low": "Intercalaire possible jusqu'à ~3 mois avant la clôture, avec travaux de liaison",
    "moderate": "À la clôture ou près de la clôture (intercalaire ≤ ~1 mois)",
    "high": "À la clôture ou près de la clôture (intercalaire ≤ ~1 mois)",
}


def timing_suggestion(level, locale):
    """Timing window guidance: the interim date shrinks as the CRA rises."""
    return (_TIMING_FR if locale == "fr" else _TIMING_EN).get(level)
