"""The findings and SAD pages (owner's mock-ups of 2026-11-16): stages, totals and effects."""
from services.worksheet_pages import (
    after_tax,
    finding_stage,
    findings_summary,
    materiality_bar,
    sad_effects,
    sad_totals,
    stage_steps,
)


def test_a_deficiency_walks_the_five_stages():
    stage = lambda **k: finding_stage(**{  # noqa: E731
        "route": "c1", "status": "open", "severity": "deficiency", "has_evaluation": False,
        "has_answer": False, "communicated": False, **k,
    })
    assert stage() == "raised"
    assert stage(has_evaluation=True) == "assessed"
    assert stage(has_evaluation=True, has_answer=True) == "discussed"
    assert stage(has_evaluation=True, has_answer=True, communicated=True) == "reported"
    assert stage(communicated=True, status="cleared") == "closed"


def test_a_misstatement_is_assessed_on_the_sad_and_is_never_reported_in_writing():
    assert finding_stage("b5", "open", False, False, False, False) == "assessed"
    assert finding_stage("b5", "open", False, False, True, True) == "discussed"
    assert finding_stage("b4", "open", False, False, False, False) == "raised"
    assert finding_stage("b4", "open", "observation", False, False, False) == "assessed"
    steps = {s["key"]: s["state"] for s in stage_steps("b5", "discussed")}
    assert steps == {"raised": "done", "assessed": "done", "discussed": "current", "reported": "skipped", "closed": "todo"}
    assert stage_steps("c1", "closed")[-1] == {"key": "closed", "state": "done"}


def test_the_cards_and_counts():
    rows = [
        {"route": "c1", "severity": "significant_deficiency", "stage": "assessed"},
        {"route": "c1", "severity": "significant_deficiency", "stage": "reported"},
        {"route": "c1", "severity": "deficiency", "stage": "closed"},
        {"route": "b5", "severity": False, "stage": "assessed"},
        {"route": "b4", "severity": False, "stage": "raised"},
    ]
    summary = findings_summary(rows)
    assert summary["total"] == 5
    assert summary["stages"] == {"raised": 1, "assessed": 2, "discussed": 0, "reported": 1, "closed": 1}
    assert (summary["significant"], summary["significantNotReported"]) == (2, 1)
    assert (summary["waiting"], summary["notReported"], summary["linked"], summary["closed"]) == (2, 1, 1, 1)


def _entry(dr, cr, dr_caption, cr_caption):
    return {"drAmount": dr, "crAmount": cr, "drCaption": dr_caption, "crCaption": cr_caption}


def test_the_effect_of_each_difference_as_in_the_mock_up():
    # Dr customers / Cr sales: profit and assets up
    assert sad_effects(_entry(18450000, 18450000, "current_asset", "income")) == {
        "profit": 18450000, "assets": 18450000, "liabilities": 0, "equity": 0,
    }
    # Dr change in stock / Cr stock: profit and assets down
    assert sad_effects(_entry(2300000, 2300000, "expense", "current_asset")) == {
        "profit": -2300000, "assets": -2300000, "liabilities": 0, "equity": 0,
    }
    # Dr invoices to receive (a liability) / Cr fees: profit up, liabilities down
    effect = sad_effects(_entry(125000000, 125000000, "current_liability", "expense"))
    assert (effect["profit"], effect["liabilities"], effect["assets"]) == (125000000, -125000000, 0)
    assert str(effect["assets"]) == "0.0"  # never -0


def test_totals_and_after_tax():
    effects = [
        sad_effects(_entry(18450000, 18450000, "current_asset", "income")),
        sad_effects(_entry(2300000, 2300000, "expense", "current_asset")),
        sad_effects(_entry(105290000, 105290000, "expense", "current_asset")),
        sad_effects(_entry(125000000, 125000000, "current_liability", "expense")),
        sad_effects(_entry(155000000, 155000000, "expense", "non_current_asset")),
    ]
    totals = sad_totals(effects)
    assert totals == {"profit": -119140000, "assets": -244140000, "liabilities": -125000000, "equity": 0}
    assert after_tax(totals["profit"], 33) == -79823800
    assert after_tax(1000, None) == 670


def test_the_bar_reads_the_iza_450_threshold():
    materiality = {"overall": 180, "performance": 135, "trivial": 9}
    bar = materiality_bar(40, materiality, 45)
    assert bar["level"] == "close" and bar["share"] == 89
    assert bar["overall"] == 100 and bar["performance"] == 75 and bar["trivial"] == 5
    assert materiality_bar(46, materiality, 45)["level"] == "over"
    assert materiality_bar(10, materiality, 45)["level"] == "under"
    assert materiality_bar(400, materiality, 45)["fill"] == 100
    assert materiality_bar(10, None, None) is None
