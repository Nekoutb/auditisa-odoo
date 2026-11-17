"""The adjustment of a misstatement (owner's mock-ups of 2026-11-16 and 2026-11-17): lines by
heading, balance, effect on the statements, and the summary lines it sends."""
import pytest

from services.finding_adjustment import (
    HEADINGS,
    AdjustmentError,
    accounts_text,
    adjustment_effect,
    adjustment_pairs,
    booking_error,
    clean_lines,
    effect_table,
    heading_effects,
    totals,
)

MOCK = [
    {"heading": "expenditure", "label": "Inventory shortage written off", "debit": "8400000", "credit": ""},
    {"heading": "current_assets", "label": "Inventories reduced", "debit": None, "credit": 8400000},
]


def test_seven_headings_exactly():
    assert HEADINGS == [
        "non_current_assets", "current_assets", "non_current_liabilities", "current_liabilities",
        "equity", "revenue", "expenditure",
    ]


def test_lines_are_cleaned_and_blank_ones_dropped():
    lines = clean_lines(MOCK + [{"heading": "", "label": " ", "debit": "", "credit": ""}])
    assert lines == [
        {"heading": "expenditure", "account": "", "label": "Inventory shortage written off", "debit": 8400000.0, "credit": 0.0},
        {"heading": "current_assets", "account": "", "label": "Inventories reduced", "debit": 0.0, "credit": 8400000.0},
    ]
    # a line being typed (no amount yet) is kept
    assert clean_lines([{"heading": "revenue"}]) == [{"heading": "revenue", "account": "", "label": "", "debit": 0.0, "credit": 0.0}]
    # a line of before 2026-11-17 keeps its account as information, its heading to classify
    old = clean_lines([{"account": "6033", "label": "Shortage", "debit": 10}])
    assert old == [{"heading": "", "account": "6033", "label": "Shortage", "debit": 10.0, "credit": 0.0}]
    assert booking_error(old + clean_lines([{"heading": "current_assets", "credit": 10}])) == "adjustment-line"


@pytest.mark.parametrize("line", [
    {"heading": "expenditure", "debit": 5, "credit": 5},
    {"heading": "expenditure", "debit": -5},
    {"heading": "expenditure", "credit": "abc"},
    {"heading": "6033", "debit": 5},
])
def test_a_wrong_line_is_refused(line):
    with pytest.raises(AdjustmentError) as caught:
        clean_lines([line])
    assert caught.value.code == "adjustment-line"


def test_sending_needs_balanced_lines_with_headings():
    lines = clean_lines(MOCK)
    assert totals(lines) == {"debit": 8400000.0, "credit": 8400000.0, "balanced": True}
    assert booking_error(lines) is None
    assert booking_error([]) == "adjustment-unbalanced"
    assert booking_error(clean_lines([{"heading": "expenditure", "debit": 10}, {"heading": "current_liabilities", "credit": 9}])) == "adjustment-unbalanced"
    assert booking_error(clean_lines([{"heading": "expenditure", "debit": 10}])) == "adjustment-unbalanced"
    assert booking_error(clean_lines([{"label": "x", "debit": 10}, {"heading": "current_liabilities", "credit": 10}])) == "adjustment-line"
    assert booking_error(clean_lines([{"heading": "expenditure"}, {"heading": "current_liabilities", "credit": 10}])) == "adjustment-line"


def test_the_effect_of_the_mock_up():
    """Dr expenditure / Cr current assets: profit, assets and equity all down."""
    assert adjustment_effect(clean_lines(MOCK)) == {
        "profit": -8400000.0, "assets": -8400000.0, "liabilities": 0.0, "equity": -8400000.0,
    }
    by_heading = heading_effects(clean_lines(MOCK))
    assert by_heading["current_assets"] == -8400000.0
    assert by_heading["expenditure"] == 8400000.0
    assert by_heading["equity"] == -8400000.0


def test_the_effect_balances_and_reads_each_heading():
    # an unrecorded supplier invoice: expenditure up, liability up
    effect = adjustment_effect(clean_lines([{"heading": "expenditure", "debit": 50}, {"heading": "current_liabilities", "credit": 50}]))
    assert effect == {"profit": -50.0, "assets": 0.0, "liabilities": 50.0, "equity": -50.0}
    # a dividend not booked: equity down, liability up; profit untouched
    effect = adjustment_effect(clean_lines([{"heading": "equity", "debit": 30}, {"heading": "current_liabilities", "credit": 30}]))
    assert effect == {"profit": 0.0, "assets": 0.0, "liabilities": 30.0, "equity": -30.0}
    assert effect["assets"] == effect["liabilities"] + effect["equity"]
    # revenue overstated: revenue down, receivables down
    effect = adjustment_effect(clean_lines([{"heading": "revenue", "debit": 20}, {"heading": "current_assets", "credit": 20}]))
    assert effect == {"profit": -20.0, "assets": -20.0, "liabilities": 0.0, "equity": -20.0}


def test_pairs_and_accounts_text():
    assert adjustment_pairs(clean_lines(MOCK)) == [{
        "dr": "expenditure", "cr": "current_assets", "amount": 8400000.0,
        "dr_label": "Inventory shortage written off", "cr_label": "Inventories reduced",
    }]
    lines = clean_lines([
        {"heading": "expenditure", "debit": 100}, {"heading": "non_current_assets", "debit": 50},
        {"heading": "current_liabilities", "credit": 150},
    ])
    assert [(p["dr"], p["cr"], p["amount"]) for p in adjustment_pairs(lines)] == [
        ("expenditure", "current_liabilities", 100.0), ("non_current_assets", "current_liabilities", 50.0),
    ]
    assert accounts_text(lines) == "Dr Expenditure, Non-current assets / Cr Current liabilities"
    assert accounts_text(lines, "fr") == "Dr Charges, Actifs non courants / Cr Passifs courants"


def test_the_effect_table_of_the_mock_up():
    """Mock-up 2: AD-01 and AD-02 to review, AD-03 posted."""
    ad1 = clean_lines(MOCK)
    ad2 = clean_lines([{"heading": "expenditure", "debit": 3150000}, {"heading": "non_current_assets", "credit": 3150000}])
    ad3 = clean_lines([{"heading": "expenditure", "debit": 1920000}, {"heading": "current_liabilities", "credit": 1920000}])
    table = {row["heading"]: (row["all"], row["posted"]) for row in effect_table([(ad1, False), (ad2, False), (ad3, True)])}
    assert table == {
        "non_current_assets": (-3150000.0, 0.0),
        "current_assets": (-8400000.0, 0.0),
        "non_current_liabilities": (0.0, 0.0),
        "current_liabilities": (1920000.0, 1920000.0),
        "equity": (-13470000.0, -1920000.0),
        "revenue": (0.0, 0.0),
        "expenditure": (13470000.0, 1920000.0),
    }
