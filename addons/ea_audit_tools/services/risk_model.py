"""The pure part of lib/risks.ts: titles and the inherent-risk spectrum."""

PRESUMED_TITLES = {
    "revenue_fraud": {
        "en": "Presumed fraud risk in revenue recognition (ISA 240)",
        "fr": "Risque présumé de fraude dans la comptabilisation des produits (ISA 240)",
    },
    "mgmt_override": {
        "en": "Management override of controls (ISA 240)",
        "fr": "Contournement des contrôles par la direction (ISA 240)",
    },
}

#: Seeded on every engagement with an audit programme: section and assertions.
PRESUMED_SEED = (
    ("revenue_fraud", "E4.20", ("E", "A")),
    ("mgmt_override", "E3.1", ("C", "E", "A")),
)

#: The response ISA 240 prescribes to the presumed override risk: E3.1's opening step.
MGMT_OVERRIDE_PROCEDURE = (
    "Test the appropriateness of journal entries and other adjustments made in the preparation of the "
    "financial statements, review accounting estimates for bias, and evaluate the business rationale of "
    "significant unusual transactions (ISA 240 ¶32)."
)

_SCORE = {"low": 1, "medium": 2, "high": 3}


def inherent_rating(likelihood, magnitude):
    """Inherent risk = likelihood x magnitude."""
    product = _SCORE[likelihood] * _SCORE[magnitude]
    if product >= 6:
        return "high"
    if product >= 3:
        return "medium"
    return "low"


def risk_title(description, presumed_type, locale):
    presumed = PRESUMED_TITLES.get(presumed_type) if presumed_type else None
    return presumed[locale] if presumed else description


RATING_LEVELS = ("low", "medium", "high")


def risk_overview(rows):
    """One risk page (owner's mock-up of 2026-11-16): the heat map above the register and a
    short summary. rows: one dict per risk of the register, with likelihood, magnitude,
    significant, rebutted, indexes (lead indexes linked) and steps (program steps linked).
    The grid reads likelihood from high (top row) to low, magnitude from low to high. A
    rebutted risk needs no lead index nor step, so it is not counted as missing them."""
    grid = []
    for likelihood in reversed(RATING_LEVELS):
        cells = []
        for magnitude in RATING_LEVELS:
            here = [r for r in rows if r["likelihood"] == likelihood and r["magnitude"] == magnitude]
            cells.append({
                "likelihood": likelihood,
                "magnitude": magnitude,
                "rating": inherent_rating(likelihood, magnitude),
                "count": len(here),
                "significant": len([r for r in here if r["significant"]]),
            })
        grid.append({"likelihood": likelihood, "cells": cells})
    live = [r for r in rows if not r["rebutted"]]
    return {
        "grid": grid,
        "summary": {
            "total": len(rows),
            "significant": len([r for r in rows if r["significant"]]),
            "rebutted": len([r for r in rows if r["rebutted"]]),
            "no_index": len([r for r in live if not r["indexes"]]),
            "no_step": len([r for r in live if not r["steps"]]),
        },
    }
