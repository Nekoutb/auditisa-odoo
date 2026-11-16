"""The journal-entry and sampling worksheets: what the pages show, without Odoo."""
from services.ws_pages import (
    card_state, clean_item_patch, exceeds_tolerable, group_entries, je_progress, sample_items, toc_steps, tod_result_steps,
    tod_steps,
)


def _line(je, criterion, label, **extra):
    base = {
        "jeNumber": je, "journalDate": "2025-12-31", "journalCode": "OD", "jeDescription": "Accrual", "lineDescription": "",
        "preparer": "CFO", "account": "6324", "accountName": "Fees", "debit": 100, "credit": 0, "entryGrossValue": 250000000,
        "reasons": [{"criterion": criterion, "label": label, "detail": ""}],
    }
    base.update(extra)
    return base


def test_lines_become_entries_with_their_reasons_once():
    lines = [
        _line("OD1", "year-end-volume", "Year end"),
        _line("OD1", "round-amount", "Round", account="4081", debit=0, credit=100),
        _line("OD1", "round-amount", "Round"),
        _line("VT2", "weekend-posting", "Weekend", entryGrossValue=10),
    ]
    entries = group_entries(lines, {"OD1": {"id": 7, "status": "problem", "note": "no invoice", "finding": "F-08", "files": 2}})
    assert [e["je"] for e in entries] == ["OD1", "VT2"]
    first = entries[0]
    assert first["reasons"] == ["Year end", "Round"]
    assert first["amount"] == 125000000
    assert len(first["lines"]) == 3
    assert (first["status"], first["note"], first["finding"], first["files"], first["reviewId"]) == ("problem", "no invoice", "F-08", 2, 7)
    assert entries[1]["status"] == "to_clear" and entries[1]["amount"] == 5


def test_progress_counts_against_the_engine_total():
    entries = [{"status": "cleared"}, {"status": "problem"}, {"status": "to_clear"}]
    assert je_progress(entries, 42) == {"total": 42, "cleared": 1, "problems": 1, "open": 40}
    assert je_progress(entries) == {"total": 3, "cleared": 1, "problems": 1, "open": 1}


def _states(steps):
    return [step["state"] for step in steps]


def test_toc_steps_follow_the_work():
    assert _states(toc_steps(0, 0, False, 0, False)) == ["now", "todo", "todo", "todo", "todo"]
    assert _states(toc_steps(120, 25, True, 18, False)) == ["done", "done", "done", "now", "todo"]
    assert toc_steps(120, 25, True, 18, False)[3]["label"] == "18/25"
    done = toc_steps(120, 25, True, 25, "rely")
    assert _states(done) == ["done"] * 5 and card_state(done) == "done"
    failed = toc_steps(120, 25, True, 25, "none")
    assert failed[4]["state"] == "bad" and card_state(failed) == "bad"
    assert toc_steps(120, 25, True, 25, "rely", "not_effective")[4]["state"] == "bad"


def test_tod_steps_and_result_cards():
    assert _states(tod_steps(100, 30, True, 0, 30, None, False)) == ["done", "done", "done", "now", "todo"]
    assert tod_steps(100, 30, True, 18, 30, None, False)[3]["label"] == "18/30"
    assert card_state(tod_steps(100, 30, True, 30, 30, None, False)) == "now"
    assert card_state(tod_steps(100, 30, True, 30, 30, -10, False)) == "done"
    assert card_state(tod_steps(100, 30, True, 30, 30, -10, True)) == "bad"
    assert card_state(tod_result_steps(False)) == "done"
    assert card_state(tod_result_steps(True)) == "bad"


def test_tested_items_compare_audited_with_book():
    picks = [(1, "mus", "ENEO"), (2, "mus", "Camtel"), (3, "random", "Douala")]
    book = {1: 412600000.0, 2: 96300000.0, 3: 58900000.0}
    results = {"1": {"audited": 412600000.0, "how": "Confirmation"}, "2": {"audited": 72150000.0}}
    rows, totals = sample_items(picks, book, results)
    assert [r["result"] for r in rows] == ["agreed", "error", "to_test"]
    assert rows[1]["difference"] == -24150000
    assert rows[0]["how"] == "Confirmation"
    assert totals["tested"] == 2 and totals["errors"] == 1 and totals["count"] == 3
    assert totals["difference"] == -24150000
    assert totals["book"] == 567800000


def test_an_item_within_half_a_franc_agrees():
    rows, _totals = sample_items([(5, "random", "")], {5: 100.4}, {"5": {"audited": 100}})
    assert rows[0]["result"] == "agreed"


def test_item_patches_are_screened():
    assert clean_item_patch({"audited": "1 250,50"}) == {"audited": 1250.5}
    assert clean_item_patch({"audited": ""}) == {"audited": None}
    assert clean_item_patch({"how": "  Invoice  "}) == {"how": "Invoice"}
    assert clean_item_patch({"audited": "abc"}) is None
    assert clean_item_patch({"book": 1}) is None
    assert clean_item_patch("x") is None
    assert clean_item_patch({"audited": "nan"}) is None


def test_projected_against_tolerable():
    assert exceeds_tolerable(-147990000, 135000000) is True
    assert exceeds_tolerable(1000, 135000000) is False
    assert exceeds_tolerable(None, 1) is None
    assert exceeds_tolerable(1, None) is None
