"""The picker of the engagement's existing documents: latest versions only, and a search that
looks in the name, type, task code, uploader and date."""

from services.document_library import latest_versions, library, search_rows

ROWS = [
    {"id": 1, "item_id": 10, "name": "Relevé bancaire.pdf", "version": 1, "code": "E4.1", "task": "Cash",
     "type": "", "by": "Awa Staff", "date": "02/11/2026"},
    {"id": 2, "item_id": 10, "name": "Relevé bancaire.pdf", "version": 2, "code": "E4.1", "task": "Cash",
     "type": "", "by": "Awa Staff", "date": "03/11/2026"},
    {"id": 3, "item_id": 11, "name": "flow.png", "version": 1, "code": "C3.1", "task": "Sales SCOT",
     "type": "Flowchart", "by": "Ben Senior", "date": "05/11/2026"},
    {"id": 4, "item_id": 12, "name": "contract.docx", "version": 1, "code": "B2", "task": "Contracts",
     "type": "", "by": "Ben Senior", "date": "05/11/2026"},
]


def ids(rows):
    return sorted(row["id"] for row in rows)


def test_only_the_latest_version_of_a_chain_is_offered():
    assert ids(latest_versions(ROWS)) == [2, 3, 4]


def test_an_empty_search_lists_everything():
    assert ids(library(ROWS, "")) == [2, 3, 4]
    assert ids(library(ROWS, None)) == [2, 3, 4]


def test_search_by_name_without_accents_or_case():
    assert ids(search_rows(ROWS, "RELEVE")) == [1, 2]


def test_search_by_type_task_code_uploader_and_date():
    assert ids(library(ROWS, "flowchart")) == [3]
    assert ids(library(ROWS, "B2")) == [4]
    assert ids(library(ROWS, "ben")) == [3, 4]
    assert ids(library(ROWS, "03/11")) == [2]


def test_every_word_must_match():
    assert ids(library(ROWS, "ben contract")) == [4]
    assert ids(library(ROWS, "ben cash")) == []


def test_sorted_by_task_code_then_name():
    assert [row["code"] for row in library(ROWS)] == ["B2", "C3.1", "E4.1"]
