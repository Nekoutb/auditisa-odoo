"""EAGLR's own checks (owner's mock-ups "eaglr" and "gl-journal-types", 20/11/2026)."""
from datetime import date

import pytest

from services import eaglr as e


@pytest.mark.parametrize("code, kind", [
    ("VTE", "sales"), ("vt", "sales"), ("SAL", "sales"), ("ACH", "purchases"), ("PUR", "purchases"),
    ("CAI", "cash"), ("CSH", "cash"), ("BQ", "bank"), ("BQ2", "bank"), ("BNK", "bank"), ("BAN", "bank"),
    ("OD", "manual"), ("MISC", "manual"), ("JNL", "manual"), ("AN", "opening"), ("RAN", "opening"),
    ("OB", "opening"), ("IMMO", "fixed_assets"), ("FA", "fixed_assets"), ("PAIE", "payroll"), ("PAY", "payroll"),
    ("BQ-SGBC", "bank"), ("CAISSE PRINCIPALE", "cash"),
])
def test_journal_codes_are_suggested(code, kind):
    assert e.suggest_type(code) == kind


@pytest.mark.parametrize("code", ["", None, "ZZ", "X1", "SALE7Q"])
def test_an_unknown_code_is_left_blank(code):
    assert e.suggest_type(code) is None


def test_journal_type_classes():
    types = {"OD": "manual", "VTE": "sales", "AN": "opening", " BQ ": "bank", "X": "nonsense", "Y": False}
    assert e.clean_journal_types(types) == {"OD": "manual", "VTE": "sales", "AN": "opening", "BQ": "bank"}
    assert e.codes_of(types, "manual") == ["OD"]
    assert e.codes_of(types, "automatic") == ["BQ", "VTE"]
    assert e.codes_of(types, "opening") == ["AN"]
    assert e.has_types(types) and not e.has_types({}) and not e.has_types(None)
    assert len(e.JOURNAL_TYPES) == 8
    assert [row[3] for row in e.JOURNAL_TYPES].count("automatic") == 6
    assert e.type_label("manual", "fr").startswith("Manuel")


def test_the_description_read_is_the_line_one_then_the_entry_one():
    assert e.description("Loyer janvier", "Entry") == "Loyer janvier"
    assert e.description("  ", "Facture FV25-0025") == "Facture FV25-0025"
    assert e.description(None, None) == ""
    assert e.description("'-", None) == "-"


def test_placeholders():
    for text in ("Import", "IMPORT BATCH 12345", "Saisie 2231", "/", "...", "-", "Écriture comptable", "n/a"):
        assert e.is_placeholder(text), text
    for text in ("Import de marchandises Douala", "Transaction fees bank SGBC", "Loyer mars 2025"):
        assert not e.is_placeholder(text), text


def test_short_and_numeric():
    assert e.is_short("OD") and e.is_short("Fact 12") and e.is_short("1234567890123")
    assert not e.is_short("") and not e.is_short("Facture 4471")


def test_wrong_year_and_month():
    assert e.wrong_year("Loyer 2024", 2025) and not e.wrong_year("Loyer 2025", 2025)
    assert not e.wrong_year("Loyer de janvier", 2025)
    assert not e.wrong_year("Factures 2024 et 2025", 2025)
    assert e.wrong_month("Salaires janvier", 3) and not e.wrong_month("Salaires Mars", 3)
    assert not e.wrong_month("Électricité Février", 2) and e.wrong_month("Rent December", 1)
    assert not e.wrong_month("Facture FV25", 1)


def test_vague_reversal_provisional_encoding():
    assert e.is_vague("Divers") and e.is_vague("Régularisation compte") and e.is_vague("a regulariser")
    assert not e.is_vague("Facture Diversco")
    assert e.reversal_without_reference("Extourne provision")
    assert not e.reversal_without_reference("Extourne OD/2025/0012")
    assert not e.reversal_without_reference("Annulation facture 202512")
    assert not e.reversal_without_reference("Facture annulée")
    assert e.is_provisional("Montant provisoire") and e.is_provisional("TBC") and e.is_provisional("à confirmer")
    assert e.has_encoding_error("Electricit??? janvier") and e.has_encoding_error("DÃ©pense")
    assert e.has_encoding_error("Montant �") and not e.has_encoding_error("Dépense ?")


def test_information_checks():
    assert e.names_currency("Achat 1 200 EUR") and not e.names_currency("Europe Bureau")
    assert e.mixed_languages("Paiement invoice 12") and not e.mixed_languages("Paiement facture 12")
    assert e.tax_without_period("4441", "TVA due") and not e.tax_without_period("4441", "TVA due 2025-03")
    assert not e.tax_without_period("4441", "TVA mars") and not e.tax_without_period("4441", "TVA T1")
    assert not e.tax_without_period("4441", "TVA 03/2025") and not e.tax_without_period("601", "Achat")
    assert e.normalised("Facture  N° 12-A") == "facturen12a"


def test_description_flags_of_a_line():
    assert e.description_flags("", date(2025, 3, 1)) == []
    flags = e.description_flags("Divers provisoire décembre 2024", date(2025, 3, 1))
    assert flags == ["2.6", "2.8", "2.18", "2.19"]
    assert "2.2" in e.description_flags("Import", None)


@pytest.mark.parametrize("account, check", [
    ("571000", "3.2"), ("521000", "3.2"), ("585000", None), ("241000", "3.3"), ("284000", "3.3"),
    ("681000", "3.3"), ("311000", "3.4"), ("391000", None), ("401000", "3.5"), ("411000", "3.5"),
    ("601000", None), ("251000", None),
])
def test_manual_entry_buckets(account, check):
    assert e.manual_check(account) == check


def test_provisions_need_their_counter_leg():
    lines = [
        # a provision credited against 691: fine
        {"id": 1, "je": "A", "account": "491000", "debit": 0, "credit": 100},
        {"id": 2, "je": "A", "account": "691000", "debit": 100, "credit": 0},
        # a provision credited against a customer: no charge
        {"id": 3, "je": "B", "account": "491000", "debit": 0, "credit": 50},
        {"id": 4, "je": "B", "account": "411000", "debit": 50, "credit": 0},
        # a provision released to 759 and one to 86 (HAO): fine
        {"id": 5, "je": "C", "account": "391000", "debit": 30, "credit": 0},
        {"id": 6, "je": "C", "account": "759000", "debit": 0, "credit": 30},
        {"id": 7, "je": "D", "account": "194000", "debit": 20, "credit": 0},
        {"id": 8, "je": "D", "account": "861000", "debit": 0, "credit": 20},
        # a provision debited with no release
        {"id": 9, "je": "E", "account": "594000", "debit": 10, "credit": 0},
        {"id": 10, "je": "E", "account": "521000", "debit": 0, "credit": 10},
        # a provision credited against 659 and one against 85 (HAO)
        {"id": 11, "je": "F", "account": "291000", "debit": 0, "credit": 5},
        {"id": 12, "je": "F", "account": "659000", "debit": 5, "credit": 0},
        {"id": 13, "je": "G", "account": "291000", "debit": 0, "credit": 5},
        {"id": 14, "je": "G", "account": "851000", "debit": 5, "credit": 0},
    ]
    assert e.provision_exceptions(lines) == [3, 9]


def test_interest_rate():
    assert e.implied_rate(-1000000, 80000) == 8.0
    assert e.implied_rate(0, 80000) is None


def test_accuracy():
    assert e.accuracy(0, 0) == 100.0
    assert e.accuracy(100, 100) == 100.0
    assert e.accuracy(100, 90) == 90.0
    assert e.accuracy(0, 500) == 0.0
    assert e.accuracy(-50, 50) == 0.0


def row(section, status, accuracy=None):
    return {"section": section, "status": status, "accuracy": accuracy}


def test_not_run_and_information_never_count():
    rows = [
        row("1", "passed", 100.0), row("1", "exceptions", 90.0), row("1", "not_run"),
        row("2", "passed"), row("2", "exceptions"), row("2", "passed"), row("2", "passed"), row("2", "not_run"),
        row("3", "not_run"), row("3", "not_run"), row("3", "not_applicable"),
        row("4", "passed"), row("4", "passed"),
        row("i", "information"),
    ]
    summary = e.score_summary(rows)
    assert summary["sections"] == {"1": 95.0, "2": 75.0, "3": None, "4": 100.0}
    # section 3 could not run: it is left out, never counted as 100%
    assert summary["overall"] == 90.0
    assert summary["passed"] is False and summary["passMark"] == 96.0


def test_no_score_when_nothing_ran():
    summary = e.score_summary([row("2", "not_run"), row("i", "information")])
    assert summary["overall"] is None and summary["passed"] is None


def test_every_row_has_both_languages_and_a_place():
    keys = [row[0] for row in e.ROWS]
    assert len(keys) == len(set(keys)) == len(e.LABELS)
    for key, section, source, _ref in e.ROWS:
        assert section in e.SECTION_ORDER and source in ("linked", "new", "info")
        assert e.label(key, "en") and e.label(key, "fr") and e.label(key, "en") != e.label(key, "fr")
    # removed by the owner: description against account, abbreviations
    assert "2.9" not in keys and "2.13" not in keys
    assert set(e.SUB_LEDGER_OF) | set(e.EAGLA_OF) <= set(keys)


def test_the_page_words_are_in_both_languages():
    for key, both in e.WORDS.items():
        assert both["en"] and both["fr"], key
    for _key, _section, _source, reference in e.ROWS:
        if reference and not reference.startswith("EAGLA "):
            assert "ref_" + reference in e.WORDS
    for status in (e.PASSED, e.EXCEPTIONS, e.NOT_RUN, e.INFORMATION, e.NOT_APPLICABLE):
        assert e.word(status, "fr")
