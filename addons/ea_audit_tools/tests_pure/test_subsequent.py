"""The next-year general ledger: how far it reaches, and the sentence the pages show."""
import pytest

from services.errors import ServiceError
from services.subsequent import (
    CURRENT_YEAR_TIMINGS, SUBSEQUENT, SUBSEQUENT_KINDS, SUBSEQUENT_MIN_DAYS, coverage_of, coverage_sentence, coverage_short,
    coverage_warning, empty_coverage, ledger_coverage,
)

MAPPING = {"account": "Compte", "jeNumber": "N°", "journalDate": "Date", "debit": "D", "credit": "C"}
ROWS = [
    {"Compte": "401000", "N°": "AC1", "Date": "10/01/2026", "D": "", "C": "500"},
    {"Compte": "601000", "N°": "AC1", "Date": "10/01/2026", "D": "500", "C": ""},
    {"Compte": "521000", "N°": "BQ1", "Date": "2026-02-14", "D": "", "C": "500"},
    {"Compte": "401000", "N°": "BQ1", "Date": "2026-02-14", "D": "500", "C": ""},
    {"Compte": "", "N°": "XX", "Date": "31/12/2026", "D": "1", "C": ""},  # no account: no entry
    {"Compte": "601000", "N°": "OD1", "Date": "", "D": "0", "C": "0"},  # no date: counted, no date
]


def test_the_coverage_runs_from_the_first_to_the_last_dated_line():
    coverage = ledger_coverage(ROWS, MAPPING, "2025-12-31")
    assert coverage == {"first_date": "2026-01-10", "last_date": "2026-02-14", "days_after_year_end": 45, "entries": 3}


def test_the_entry_date_stands_in_when_no_posting_date_is_mapped():
    mapping = {"account": "Compte", "jeNumber": "N°", "jeDate": "Date", "debit": "D", "credit": "C"}
    assert ledger_coverage(ROWS[:2], mapping, "2025-12-31")["last_date"] == "2026-01-10"


def test_a_mapping_without_the_spine_is_refused():
    with pytest.raises(ServiceError):
        ledger_coverage(ROWS, {"account": "Compte"}, "2025-12-31")


def test_the_sentence_in_english_and_in_french():
    coverage = coverage_of("2026-01-02", "2026-03-31", 12, "2025-12-31")
    assert coverage["days_after_year_end"] == 90
    assert coverage_sentence(coverage) == "Next-year general ledger provided up to 31/03/2026 (90 days after year end)."
    assert coverage_sentence(coverage, fr=True) == "Grand livre de l'exercice suivant fourni jusqu'au 31/03/2026 (90 jours après la clôture)."
    assert coverage_sentence(empty_coverage()) == "No next-year general ledger uploaded."
    assert coverage_sentence(None, fr=True) == "Aucun grand livre de l'exercice suivant importé."
    assert "no readable date" in coverage_sentence(coverage_of(None, None, 4, "2025-12-31"))


def test_a_short_ledger_is_warned_about_at_the_threshold():
    assert SUBSEQUENT_MIN_DAYS == 30
    short = coverage_of("2026-01-01", "2026-01-29", 3, "2025-12-31")  # 29 days
    enough = coverage_of("2026-01-01", "2026-01-30", 3, "2025-12-31")  # 30 days
    assert coverage_short(short) and not coverage_short(enough)
    assert "30" in coverage_warning(short) and "30" in coverage_warning(short, fr=True)
    assert coverage_warning(enough) is None
    # nothing uploaded: nothing to warn about, the sentence says it
    assert not coverage_short(empty_coverage()) and coverage_warning(empty_coverage()) is None
    # uploaded but with no readable date: warned
    assert coverage_short(coverage_of(None, None, 2, "2025-12-31"))


def test_the_kinds_and_the_timings():
    assert SUBSEQUENT not in CURRENT_YEAR_TIMINGS
    assert set(SUBSEQUENT_KINDS) == {"journal_entries", "ar_open_items", "ap_open_items", "inventory_listing"}
