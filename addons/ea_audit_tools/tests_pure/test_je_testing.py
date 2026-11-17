"""Journal entry testing (ISA 240, owner's mock-up approved 18/11): every criterion on a small
ledger built for it, the filter (a union; nothing ticked shows the whole selection), the test's
conclusion and the export for the client."""
import time

import pytest

from services.je_testing import (
    CRITERIA, CRITERION_KEYS, accounts_summary, build_context, criterion_name, day_number, entry_facts, export_rows,
    filter_selection, resolve_settings, run_criteria, settings_text, spaced, stored_status, entry_conclusion, selection_totals,
    weekday_name, year_holidays,
)

PERIOD_END = "2025-12-31"
HOLIDAYS = [{"date": "2025-05-20", "label": "National Day"}, {"date": "2025-08-15", "label": "Assumption"}]
COMMON = [
    ("601000", "401000"), ("411000", "701000"), ("521000", "411000"), ("401000", "521000"),
    ("601000", "571000"), ("241000", "401000"), ("521000", "101000"),
]


def lines_of(je, date, pairs, preparer="Alice", approver="Bob", description="Supplier invoice 1001", next_period=False):
    """An entry: [(debit account, credit account, amount)] as two lines each."""
    out = []
    for debit, credit, amount in pairs:
        base = {"je_number": je, "journal_date": date, "journal_code": "OD", "je_description": description,
                "preparer": preparer, "approver": approver}
        out.append(dict(base, account=debit, debit=amount, credit=0))
        out.append(dict(base, account=credit, debit=0, credit=amount))
    return out


def weekdays(count):
    """Weekdays of mid-2025 away from the year end and the holidays."""
    out, day = [], day_number("2025-06-02")
    holidays = {day_number(h["date"]) for h in HOLIDAYS}
    while len(out) < count:
        if (day + 3) % 7 < 5 and day not in holidays:  # 1970-01-01 was a Thursday
            out.append(day)
        day += 1
    return [iso(d) for d in out]


def iso(number):
    """The yyyy-mm-dd of a day number of 2025 or 2026."""
    lengths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    for year in (2025, 2026):
        for month, length in enumerate(lengths, 1):
            for dom in range(1, length + 1):
                text = "%d-%02d-%02d" % (year, month, dom)
                if day_number(text) == number:
                    return text
    raise AssertionError(number)


SPECIAL = {
    "SUN": lines_of("SUN", "2025-03-02", [("601000", "401000", 250000)]),
    "SAT": lines_of("SAT", "2025-03-01", [("601000", "401000", 250000)]),
    "HOL": lines_of("HOL", "2025-05-20", [("601000", "401000", 250000)]),
    "YE1": lines_of("YE1", "2025-12-29", [("601000", "401000", 250000)]),
    "YE2": lines_of("YE2", "2026-01-02", [("601000", "401000", 250000)]),
    "OUT": lines_of("OUT", "2026-01-20", [("601000", "401000", 250000)]),
    "SAME": lines_of("SAME", "2025-06-03", [("601000", "401000", 250000)], approver=" alice "),
    "NOAPP": lines_of("NOAPP", "2025-06-03", [("601000", "401000", 250000)], approver=""),
    "RARE": lines_of("RARE", "2025-06-03", [("601000", "401000", 250000)], preparer="Zoe"),
    "ROUND": lines_of("ROUND", "2025-06-03", [("601000", "401000", 3000000)]),
    "BELOW": lines_of("BELOW", "2025-06-03", [("601000", "401000", 4800000)]),
    "VAGUE": lines_of("VAGUE", "2025-06-03", [("601000", "401000", 250000)], description="OD"),
    "VAGUE2": lines_of("VAGUE2", "2025-06-03", [("601000", "401000", 250000)], description="Divers régul."),
    "CLEAR": lines_of("CLEAR", "2025-06-03", [("601000", "401000", 250000)], description="Régularisation stock magasin"),
    "SUSP": lines_of("SUSP", "2025-06-03", [("471000", "401000", 250000)]),
    "ONCE": lines_of("ONCE", "2025-06-03", [("658999", "401000", 250000)]),
    "RCASH": lines_of("RCASH", "2025-06-03", [("571000", "701000", 200000)]),
    "RCASH41": lines_of("RCASH41", "2025-06-03", [("571000", "701000", 100000), ("411000", "701000", 100000)]),
    "CASHX": lines_of("CASHX", "2025-06-03", [("601000", "571000", 750000)]),
    "ASSET": lines_of("ASSET", "2025-06-03", [("241000", "701000", 250000)]),
    "PAYREC": lines_of("PAYREC", "2025-06-03", [("401000", "411000", 250000)]),
    "EQUITY": lines_of("EQUITY", "2025-06-03", [("601000", "101000", 250000)]),
}
NEXT = lines_of("NREV", "2026-01-15", [("701000", "411000", 250000)], next_period=True) + lines_of(
    "NSUN", "2026-02-01", [("601000", "401000", 250000)], next_period=True,
)


def ledger():
    lines = []
    days = weekdays(70)
    for index, day in enumerate(days):
        debit, credit = COMMON[index % len(COMMON)]
        lines += lines_of("B%03d" % index, day, [(debit, credit, 123457)], preparer="Alice" if index % 2 else "Carol")
    for rows in SPECIAL.values():
        lines += rows
    return lines


@pytest.fixture(scope="module")
def run():
    settings = resolve_settings({"holidays": HOLIDAYS})
    entries = entry_facts(ledger()) + entry_facts(NEXT, next_period=True)
    ctx = build_context(entries, settings, PERIOD_END, settings["holidays"])
    found, counts = run_criteria(entries, ctx)
    return found, counts, entries


EXPECTED = {
    "SUN": "sunday", "SAT": "saturday", "HOL": "holiday", "YE1": "year-end", "YE2": "year-end", "SAME": "same-person",
    "NOAPP": "no-approver", "RARE": "rare-poster", "ROUND": "round", "BELOW": "below-limit", "VAGUE": "vague",
    "VAGUE2": "vague", "SUSP": "rare-account", "ONCE": "rare-account", "RCASH": "revenue-cash", "CASHX": "cash-expense",
    "ASSET": "assets-revenue", "PAYREC": "payables-receivables", "EQUITY": "equity-result", "next:NREV": "revenue-after",
}


@pytest.mark.parametrize("je,key", sorted(EXPECTED.items()))
def test_each_criterion_finds_its_entry_and_only_for_that_reason(run, je, key):
    found, _counts, _entries = run
    assert found.get(je) == [key], (je, found.get(je))


@pytest.mark.parametrize("je", ["OUT", "CLEAR", "RCASH41", "next:NSUN", "B000", "B001", "B030"])
def test_ordinary_entries_are_not_selected(run, je):
    found, _counts, _entries = run
    assert je not in found


def test_every_criterion_is_counted_and_one_that_finds_nothing_counts_zero(run):
    _found, counts, _entries = run
    assert set(counts) == set(CRITERION_KEYS)
    assert counts["year-end"] == 2 and counts["vague"] == 2 and counts["rare-account"] == 2 and counts["sunday"] == 1
    entries = entry_facts(lines_of("X1", "2025-06-03", [("601000", "401000", 1234)]) * 1)
    settings = resolve_settings({})
    _found, empty = run_criteria(entries, build_context(entries, settings, PERIOD_END, []))
    assert empty["sunday"] == 0 and empty["revenue-cash"] == 0


def test_a_late_entry_of_the_subsequent_ledger_is_read_only_for_the_after_year_end_criteria(run):
    found, _counts, _entries = run
    assert found["next:NREV"] == ["revenue-after"]
    assert "next:NSUN" not in found  # a Sunday of next year is not this year's concern


def test_revenue_debited_after_year_end_in_the_ledger_itself():
    entries = entry_facts(lines_of("LATE", "2026-01-10", [("701000", "411000", 1000)]))
    settings = resolve_settings({})
    found, _counts = run_criteria(entries, build_context(entries, settings, PERIOD_END, []))
    assert "revenue-after" in found["LATE"]


def test_the_settings_move_the_thresholds():
    entries = entry_facts(
        lines_of("A", "2025-06-03", [("601000", "571000", 400000)], approver="Bob")
        + lines_of("B", "2025-12-20", [("601000", "401000", 200000)], approver="Bob")
    )
    settings = resolve_settings({"cashLimit": 300000, "yearEndDays": 15, "roundStep": 100000})
    found, _counts = run_criteria(entries, build_context(entries, settings, PERIOD_END, []))
    assert "cash-expense" in found["A"] and "round" in found["A"]
    assert "year-end" in found["B"]


def test_the_rare_poster_threshold_is_a_share_of_the_entries(run):
    _found, _counts, entries = run
    settings = resolve_settings({"rarePosterShare": 50})
    ctx = build_context(entries, settings, PERIOD_END, [])
    assert "carol" in ctx["rarePosters"] and "zoe" in ctx["rarePosters"]  # each under half of the entries
    assert "alice" not in ctx["rarePosters"]


def test_settings_are_checked_and_defaulted():
    settings = resolve_settings({"roundStep": "abc", "approvalBand": 500, "yearEndDays": "7", "vagueWords": "Divers, OD ,, xx"})
    assert settings["roundStep"] == 1000000 and settings["approvalBand"] == 10 and settings["yearEndDays"] == 7
    assert settings["vagueWords"] == ["divers", "od", "xx"]
    assert settings["holidays"] is None
    assert resolve_settings({"holidays": [{"date": "2025-13-01"}, {"date": "2025-05-20", "label": "x"}]})["holidays"] == [
        {"date": "2025-05-20", "label": "x"},
    ]


def test_filter_is_a_union_and_nothing_ticked_shows_the_whole_selection():
    rows = [{"je": "1", "reasons": ["sunday"]}, {"je": "2", "reasons": ["round", "vague"]}, {"je": "3", "reasons": ["vague"]}]
    assert filter_selection(rows, []) == rows
    assert filter_selection(rows, None) == rows
    assert [r["je"] for r in filter_selection(rows, ["sunday", "round"])] == ["1", "2"]
    assert [r["je"] for r in filter_selection(rows, ["vague"])] == ["2", "3"]
    assert filter_selection(rows, ["holiday"]) == []
    assert filter_selection(rows, ["not-a-criterion"]) == rows


def test_the_conclusion_of_a_test():
    assert entry_conclusion({}) == "to_test"
    assert entry_conclusion({"attr_document": "yes"}) == "to_test"
    assert entry_conclusion({"attr_document": "yes", "attr_approval": "na", "attr_reason": "yes", "attr_recording": "yes"}) == "no_exception"
    assert entry_conclusion({"attr_document": "no"}) == "exception"
    # a review recorded before the four questions reads its stored status
    assert entry_conclusion({"status": "cleared"}) == "no_exception"
    assert entry_conclusion({"status": "problem"}) == "exception"
    assert entry_conclusion({"status": "to_clear"}) == "to_test"
    assert [stored_status(s) for s in ("to_test", "no_exception", "exception")] == ["to_clear", "cleared", "problem"]
    totals = selection_totals([{"test": "to_test"}, {"test": "no_exception"}, {"test": "exception"}])
    assert totals == {"selected": 3, "tested": 2, "clean": 1, "exceptions": 1}


def test_export_rows_carry_every_reason(run):
    found, _counts, entries = run
    by_key = {e["je"]: e for e in entries if not e["next"]}
    settings = resolve_settings({})
    names = {c["key"]: criterion_name(c, settings, "en") for c in CRITERIA}
    rows = [{
        "je": "ROUND", "date": by_key["ROUND"]["date"], "journal": "OD", "description": "Supplier invoice 1001",
        "accounts": accounts_summary(by_key["ROUND"]), "amount": 3000000, "preparer": "Alice", "approver": "Bob",
        "reasons": ["round", "vague"], "reasonNames": [names["round"], names["vague"]],
    }]
    head, body = export_rows(rows, "en")
    assert head[0] == "Entry" and head[9] == "Why selected" and len(body[0]) == len(head)
    assert body[0][:7] == ["ROUND", "03/06/2025", "Tuesday", "OD", "Supplier invoice 1001", "601000 → 401000", 3000000]
    assert body[0][9] == "7 Round amounts; 10 Missing or vague description"
    head_fr, body_fr = export_rows(rows, "fr")
    assert head_fr[0] == "Écriture" and body_fr[0][2] == "mardi"


def test_labels_and_numbers():
    settings = resolve_settings({"yearEndDays": 5})
    year_end = next(c for c in CRITERIA if c["key"] == "year-end")
    assert criterion_name(year_end, settings, "en") == "Last 5 days of the year or first 5 days after"
    assert criterion_name(year_end, settings, "fr") == "5 derniers jours de l'exercice ou 5 premiers jours suivants"
    assert spaced(1000000) == "1 000 000" and spaced(-1234.5) == "-1 235" and spaced(0) == "0"
    assert "1 000 000" in settings_text(settings, 9, "en") and "9 public holidays" in settings_text(settings, 9, "en")
    assert weekday_name("2025-03-02", "en") == "Sunday"
    assert day_number("1970-01-01") == 0 and day_number("2026-01-01") - day_number("2025-12-31") == 1
    assert year_holidays({"2024-12-25": "x", "2025-05-20": "y", "2026-01-01": "z"}, None, PERIOD_END) == [{"date": "2025-05-20", "label": "y"}]
    assert year_holidays({"2025-01-01": "a", "2025-05-20": "y"}, "2025-02-01", PERIOD_END) == [{"date": "2025-05-20", "label": "y"}]


def test_numbers_and_groups_are_the_owners():
    assert [c["no"] for c in CRITERIA] == ["1", "2", "3", "9", "4", "5", "6", "7", "8", "10", "11", "12", "13", "14", "15", "15a", "15b"]
    assert [c["group"] for c in CRITERIA].count("pairing") == 6


def test_criteria_run_over_a_large_ledger_in_one_pass():
    """100 000 lines (50 000 entries): one pass over the entries, a few seconds at most."""
    lines = []
    for index in range(50000):
        day = "2025-%02d-%02d" % (1 + index % 12, 1 + index % 28)
        lines += lines_of("E%06d" % index, day, [(COMMON[index % 7][0], COMMON[index % 7][1], 1000 + index)],
                          preparer="P%d" % (index % 40))
    entries = entry_facts(lines)
    start = time.time()
    settings = resolve_settings({})
    found, counts = run_criteria(entries, build_context(entries, settings, PERIOD_END, HOLIDAYS))
    assert time.time() - start < 10
    assert counts["sunday"] > 0 and len(found) < len(entries)
