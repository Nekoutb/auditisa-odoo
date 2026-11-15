"""The ledger's activity per lead index (owner's request of 2026-11-15)."""
import time

from services.ap_schedules import index_resolver
from services.dataset_mapping import encode_je_key
from services.gl_line import projector
from services.significance_activity import index_activity, line_reader, people_columns

MAPPING = {"account": "Compte", "jeNumber": "Piece", "debit": "D", "credit": "C", "recordedBy": "Saisi", "approvedBy": "Valide"}


def rows():
    return [
        {"Compte": "411000", "Piece": "VE1", "D": "100", "C": "", "Saisi": "Awa", "Valide": "Paul"},
        {"Compte": "701000", "Piece": "VE1", "D": "", "C": "100", "Saisi": "Awa", "Valide": "Paul"},
        {"Compte": "411100", "Piece": "VE2", "D": "50", "C": "", "Saisi": " Ben ", "Valide": ""},
        {"Compte": "701000", "Piece": "VE2", "D": "", "C": "50", "Saisi": "Ben", "Valide": ""},
        {"Compte": "521000", "Piece": "BQ1", "D": "100", "C": "", "Saisi": "Awa", "Valide": "Marie"},
        {"Compte": "411000", "Piece": "BQ1", "D": "", "C": "100", "Saisi": "Awa", "Valide": "Marie"},
        # two lines of one entry on one index count once
        {"Compte": "411000", "Piece": "OD1", "D": "10", "C": "", "Saisi": "", "Valide": ""},
        {"Compte": "411200", "Piece": "OD1", "D": "", "C": "10", "Saisi": "", "Valide": ""},
    ]


def test_distinct_entries_and_people_per_index():
    read = line_reader(MAPPING)
    result = index_activity((read(row) for row in rows()), index_resolver([]))
    assert result["E"] == {"entries": 4, "preparers": 2, "reviewers": 2}
    assert result["UA"] == {"entries": 2, "preparers": 2, "reviewers": 1}
    assert result["C"] == {"entries": 1, "preparers": 1, "reviewers": 1}


def test_the_clients_prefix_moves_the_account_as_on_the_trial_balance():
    read = line_reader(MAPPING)
    result = index_activity((read(row) for row in rows()), index_resolver([("4112", "N")]))
    assert result["N"]["entries"] == 1
    assert result["E"]["entries"] == 4


def test_the_entry_identity_is_the_projections_one():
    mapping = dict(MAPPING, jeNumber="", jeKey=encode_je_key(["Journal", "Num"]))
    data = [
        {"Compte": "411000", "Journal": "VE", "Num": "1"},
        {"Compte": "411000", "Journal": "AC", "Num": "1"},
        {"Compte": "411000", "Journal": "", "Num": ""},
    ]
    read, project = line_reader(mapping), projector(mapping)
    assert [read(row)[1] for row in data] == [(project(row) or {}).get("je_number") for row in data]
    assert index_activity((read(row) for row in data), index_resolver([]))["E"]["entries"] == 2


def test_reviewers_count_approved_by_and_reviewer_together():
    mapping = {"account": "Compte", "jeNumber": "Piece", "approvedBy": "Valide", "reviewer": "Revu"}
    read = line_reader(mapping)
    data = [
        {"Compte": "411000", "Piece": "1", "Valide": "Paul", "Revu": "Paul"},
        {"Compte": "411000", "Piece": "2", "Valide": "", "Revu": "Marie"},
    ]
    assert index_activity((read(row) for row in data), index_resolver([]))["E"]["reviewers"] == 2


def test_which_people_columns_the_import_matched():
    assert people_columns(MAPPING) == (True, True)
    assert people_columns({"account": "A", "jeNumber": "B", "preparedBy": "P"}) == (True, False)
    assert people_columns({"account": "A", "jeNumber": "B", "reviewer": " "}) == (False, False)
    assert people_columns(None) == (False, False)


def test_a_mapping_without_account_or_entry_reads_nothing():
    assert line_reader({"account": "A"}) is None
    assert line_reader({"jeNumber": "B"}) is None


def test_a_large_ledger_is_counted_quickly():
    """Some 186,000 lines, the size of a real client's ledger: well under a few seconds."""
    data = [
        {"Compte": str(401000 + (n % 600) * 500), "Piece": "P%d" % (n // 4), "Saisi": "u%d" % (n % 9), "Valide": "v%d" % (n % 4)}
        for n in range(186000)
    ]
    read = line_reader(MAPPING)
    started = time.perf_counter()
    result = index_activity((read(row) for row in data), index_resolver([]))
    elapsed = time.perf_counter() - started
    print("186,000 lines counted in %.2f s" % elapsed)
    assert result
    assert elapsed < 10
