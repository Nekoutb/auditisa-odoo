"""The adjustment of a misstatement finding (owner's mock-up of 2026-11-16): lines, balance,
effect on the statements, and the summary lines it books."""
import pytest

from services.finding_adjustment import (
    AdjustmentError,
    accounts_text,
    adjustment_effect,
    adjustment_pairs,
    booking_error,
    clean_lines,
    totals,
)

MOCK = [
    {"account": "6033", "label": "Shortage of one transformer", "debit": "8400000", "credit": ""},
    {"account": "32", "label": "Inventories of materials", "debit": None, "credit": 8400000},
]


def test_lines_are_cleaned_and_blank_ones_dropped():
    lines = clean_lines(MOCK + [{"account": " ", "label": "", "debit": "", "credit": ""}])
    assert lines == [
        {"account": "6033", "label": "Shortage of one transformer", "debit": 8400000.0, "credit": 0.0},
        {"account": "32", "label": "Inventories of materials", "debit": 0.0, "credit": 8400000.0},
    ]
    # a line being typed (no amount yet) is kept
    assert clean_lines([{"account": "601"}]) == [{"account": "601", "label": "", "debit": 0.0, "credit": 0.0}]


@pytest.mark.parametrize("line", [
    {"account": "601", "debit": 5, "credit": 5},
    {"account": "601", "debit": -5},
    {"account": "601", "credit": "abc"},
])
def test_a_wrong_line_is_refused(line):
    with pytest.raises(AdjustmentError) as caught:
        clean_lines([line])
    assert caught.value.code == "adjustment-line"


def test_booking_needs_balanced_lines_with_accounts():
    lines = clean_lines(MOCK)
    assert totals(lines) == {"debit": 8400000.0, "credit": 8400000.0, "balanced": True}
    assert booking_error(lines) is None
    assert booking_error([]) == "adjustment-unbalanced"
    assert booking_error(clean_lines([{"account": "601", "debit": 10}, {"account": "401", "credit": 9}])) == "adjustment-unbalanced"
    assert booking_error(clean_lines([{"account": "601", "debit": 10}])) == "adjustment-unbalanced"
    assert booking_error(clean_lines([{"account": "", "debit": 10}, {"account": "401", "credit": 10}])) == "adjustment-line"
    assert booking_error(clean_lines([{"account": "601"}, {"account": "401", "credit": 10}])) == "adjustment-line"


def test_the_effect_of_the_mock_up():
    """Dr change in inventories / Cr inventories: profit, assets and equity all down."""
    assert adjustment_effect(clean_lines(MOCK)) == {
        "profit": -8400000.0, "assets": -8400000.0, "liabilities": 0.0, "equity": -8400000.0,
    }


def test_the_effect_balances_and_reads_each_caption():
    # an unrecorded supplier invoice: expense up, liability up
    effect = adjustment_effect(clean_lines([{"account": "6011", "debit": 50}, {"account": "401", "credit": 50}]))
    assert effect == {"profit": -50.0, "assets": 0.0, "liabilities": 50.0, "equity": -50.0}
    # a dividend not booked: retained earnings down, liability up; profit untouched
    effect = adjustment_effect(clean_lines([{"account": "121", "debit": 30}, {"account": "465", "credit": 30}]))
    assert effect == {"profit": 0.0, "assets": 0.0, "liabilities": 30.0, "equity": -30.0}
    assert effect["assets"] == effect["liabilities"] + effect["equity"]


def test_pairs_and_accounts_text():
    assert adjustment_pairs(clean_lines(MOCK)) == [{"dr_account": "6033", "cr_account": "32", "amount": 8400000.0}]
    lines = clean_lines([
        {"account": "6011", "debit": 100}, {"account": "6033", "debit": 50}, {"account": "401", "credit": 150},
    ])
    assert adjustment_pairs(lines) == [
        {"dr_account": "6011", "cr_account": "401", "amount": 100.0},
        {"dr_account": "6033", "cr_account": "401", "amount": 50.0},
    ]
    assert accounts_text(lines) == "Dr 6011, 6033 / Cr 401"
    lines = clean_lines([{"account": "601", "debit": 80}, {"account": "401", "credit": 30}, {"account": "521", "credit": 50}])
    assert adjustment_pairs(lines) == [
        {"dr_account": "601", "cr_account": "401", "amount": 30.0},
        {"dr_account": "601", "cr_account": "521", "amount": 50.0},
    ]
