"""lib/je-selection.ts's pure half, by the source's own rules."""
import pytest

from services.errors import ServiceError
from services.je_selection import (
    CLASS_PREFIXES, CRITERION_BY_KEY, describe_selection_design, expand_terms, filler_regex, is_incomplete_description, is_round_amount,
    iso_weekday, matches_user_rule, normalise_user_rule, reasons_for, resolve_settings, select_from_candidates, selection_class_for,
)


def line(**over):
    base = {
        "id": 1, "lineNo": 1, "jeNumber": "J1", "journalDate": "2025-03-15", "entryDate": None, "account": "411000", "accountName": None,
        "jeDescription": "Facture client", "lineDescription": None, "debit": 10, "credit": 0, "signed": 10, "preparer": "A", "reviewer": "B",
        "approver": "C", "reference": None, "journalCode": None, "thirdPartyCode": None, "thirdPartyName": None, "costCenter": None,
        "entry": {"lines": 2, "grossValue": 20, "classes": [], "yearEndRank": None},
    }
    base.update(over)
    return base


def ctx(criteria, **over):
    base = {"locale": "en", "settings": resolve_settings({}), "criteria": criteria, "userRules": [], "holidays": {}}
    base.update(over)
    return base


def test_ten_criteria():
    assert len(CRITERION_BY_KEY) == 10


def test_classes_and_masking():
    assert selection_class_for("701000") == "Revenue"
    assert selection_class_for("521000") == "Cash"
    assert selection_class_for("601000") == "Expense"
    masked = {row["prefix"]: row["klass"] for row in CLASS_PREFIXES}
    assert any(klass is None for klass in masked.values())


def test_settings_are_clamped():
    settings = resolve_settings({"topEntries": 500, "yearEndDays": -1, "roundMin": 0, "country": "cmr", "pairings": ["nope"], "volumeBasis": "x"})
    assert settings["topEntries"] == 100 and settings["yearEndDays"] == 1 and settings["roundMin"] == 1
    assert settings["country"] == "CM" and len(settings["pairings"]) == 6 and settings["volumeBasis"] == "lines"
    assert resolve_settings({"country": "fr"})["country"] == "FR"


def test_terms_both_spellings():
    terms = expand_terms(["Régularisation", "bad term!"])
    assert terms == ["régularisation", "regularisation"]


@pytest.mark.parametrize("text,expected", [
    ("", False),
    ("OD", True),
    ("Facture", True),
    ("Facture 4471", False),
    ("Divers 12 OD régularisation", True),
    ("Vente de marchandises", False),
    ("123 456 789", True),
])
def test_incomplete(text, expected):
    assert is_incomplete_description(text, resolve_settings({})) is expected


def test_round():
    settings = resolve_settings({})
    assert is_round_amount(-200000, settings)
    assert not is_round_amount(99999, settings)
    assert not is_round_amount(150000, settings)


def test_weekday():
    assert iso_weekday("2025-03-15") == 6
    assert iso_weekday("2025-03-16") == 7
    assert iso_weekday("2025-03-17") == 1
    assert iso_weekday("bad") is None


def test_rule_validation():
    with pytest.raises(ServiceError) as caught:
        normalise_user_rule({"field": "nope", "operator": "equals"}, 0)
    assert caught.value.code == "invalid-rule-field"
    with pytest.raises(ServiceError):
        normalise_user_rule({"field": "debit", "operator": "contains", "value": 1}, 0)
    with pytest.raises(ServiceError):
        normalise_user_rule({"field": "debit", "operator": "between", "value": 1}, 0)
    rule = normalise_user_rule({"field": "account", "operator": "equals", "value": " ABC "}, 2)
    assert rule["key"] == "user:r3" and rule["value"] == "abc"
    assert rule["labelEn"] == "Account is abc" and rule["labelFr"] == "Compte est abc"


def test_rule_matching():
    rule = normalise_user_rule({"field": "absAmount", "operator": "between", "value": "5", "value2": "15"}, 0)
    assert matches_user_rule(line(), rule)
    empty = normalise_user_rule({"field": "reference", "operator": "isEmpty"}, 0)
    assert matches_user_rule(line(), empty)
    equal = normalise_user_rule({"field": "debit", "operator": "equals", "value": "10,004"}, 0)
    assert matches_user_rule(line(), equal)


def test_rules_all_mode_reports_each():
    first = normalise_user_rule({"field": "account", "operator": "startsWith", "value": "41"}, 0)
    second = normalise_user_rule({"field": "debit", "operator": "greaterThan", "value": 5}, 1)
    third = normalise_user_rule({"field": "debit", "operator": "greaterThan", "value": 500}, 2)
    assert len(reasons_for(line(), ctx([], userRules=[first, second], userRulesMode="all"))) == 2
    assert reasons_for(line(), ctx([], userRules=[first, third], userRulesMode="all")) == []
    assert len(reasons_for(line(), ctx([], userRules=[first, third]))) == 1


def test_weekend_uses_the_chosen_date():
    settings = resolve_settings({"dateBasis": "entry"})
    assert reasons_for(line(), ctx(["weekend-posting"], settings=settings)) == []
    assert reasons_for(line(), ctx(["weekend-posting"]))[0]["detail"] == "journal date 2025-03-15 falls on a Saturday"


def test_pairing_lists_each_pair():
    candidate = line(entry={"lines": 2, "grossValue": 20, "classes": ["Revenue", "Cash", "Expense"], "yearEndRank": None})
    keys = [reason["label"] for reason in reasons_for(candidate, ctx(["unusual-pairing"]))]
    assert len(keys) == 3


def test_most_caught_first_and_coverage_once():
    settings = resolve_settings({})
    first = line(lineNo=1, signed=10, jeNumber="A", entry={"lines": 2, "grossValue": 20, "classes": ["Revenue", "Cash", "Expense"], "yearEndRank": None})
    second = line(lineNo=2, signed=99, jeNumber="B", entry={"lines": 2, "grossValue": 20, "classes": ["Revenue", "Cash"], "yearEndRank": None})
    third = line(lineNo=3, jeNumber="C")
    core = select_from_candidates([second, third, first], ctx(["unusual-pairing"], settings=settings))
    assert [item["jeNumber"] for item in core["lines"]] == ["A", "B"]
    assert core["coverage"]["unusual-pairing"] == {"lines": 2, "entries": 2}


def test_filler_regex_escapes():
    assert "a\\.b" in filler_regex(["a.b"])


def test_describe():
    text = describe_selection_design({"criteria": ["round-amount"], "params": {}, "selectedLines": 2, "populationLines": 9, "recordedBy": "Awa"}, "en", "01/01/2026")
    assert "Round-number amount (Minimum absolute amount: 100,000" in text
    assert text.endswith("2 line(s) selected of 9 · by Awa on 01/01/2026")
    assert "règles : 0" in describe_selection_design({"criteria": []}, "fr")
