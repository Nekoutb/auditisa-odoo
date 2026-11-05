"""lib/gl-analytics.ts, lib/gl-correlation.ts and lib/gl-insights.ts: their pure halves."""
import math

import pytest

from services import gl_analytics as ga
from services import gl_correlation as gc
from services import gl_insights as gi
from services.errors import ServiceError

FULL_MAPPING = {
    "account": "a", "jeNumber": "j", "jeDescription": "d", "journalDate": "dt", "jeDate": "ed", "debit": "dr", "credit": "cr",
    "reference": "r", "journalCode": "c", "preparedBy": "p", "approvedBy": "ap", "reviewer": "rv", "thirdPartyCode": "t",
}


def code_of(function, *args):
    with pytest.raises(ServiceError) as caught:
        function(*args)
    return caught.value.code


def test_the_catalogue_is_thirty_in_order_and_bilingual():
    assert [d["id"] for d in ga.ANALYTICS] == list(range(1, 31))
    assert len(ga.ANALYTIC_BY_KEY) == 30
    for d in ga.ANALYTICS:
        for key in ("titleEn", "titleFr", "objectiveEn", "objectiveFr", "exceptionEn", "exceptionFr"):
            assert d[key]
        text = " ".join(str(v) for v in d.values()).lower()
        assert "fraud" not in text and "fraude" not in text


def test_five_are_declared_but_not_computed():
    assert set(ga.ANALYTIC_BY_KEY) - set(ga.BODIES) == {
        "near-duplicates", "out-of-hours-postings", "sequence-gaps", "manual-vs-automated", "post-period-postings",
    }


def test_status_the_mapping_comes_before_the_analytics_own_reason():
    d = ga.ANALYTIC_BY_KEY["out-of-hours-postings"]
    assert ga.status_of(d, {"account": "a"}, "en") == "Unavailable — required field not mapped: jeDate"
    assert ga.status_of(d, {"account": "a"}, "fr") == "Indisponible — champ requis non mappé: jeDate"
    assert ga.status_of(d, FULL_MAPPING, "en") == "Unavailable — the import carries no posting timestamp"
    assert ga.status_of(ga.ANALYTIC_BY_KEY["sequence-gaps"], FULL_MAPPING, "fr") == ga.NOT_BUILT_FR
    assert ga.status_of(ga.ANALYTIC_BY_KEY["benford"], FULL_MAPPING, "en") is None


def test_a_debit_credit_pair_is_an_amount_but_a_lone_debit_is_not():
    d = ga.ANALYTIC_BY_KEY["benford"]
    assert ga.status_of(d, {"journalDate": "x", "debit": "d", "credit": "c"}, "en") is None
    assert "amount" in ga.status_of(d, {"journalDate": "x", "debit": "d"}, "en")
    assert ga.status_of(d, {"journalDate": "x", "amount": "m"}, "en") is None


def test_catalogue_entries():
    entries = ga.catalogue(FULL_MAPPING, "fr")
    assert entries[0]["title"] == "Rapprochement du grand livre"
    assert entries[0]["unavailable"] is None
    assert entries[3]["unavailable"] == ga.NOT_BUILT_FR


def test_benford_shares():
    assert [ga.round2(v) for v in ga.BENFORD] == [30.1, 17.61, 12.49, 9.69, 7.92, 6.69, 5.8, 5.12, 4.58]


def test_mad_of():
    assert ga.mad_of([0] * 9) is None
    # all on digit 1: (69.9 + the other eight shares, 69.9 again) / 9
    assert ga.mad_of([1, 0, 0, 0, 0, 0, 0, 0, 0]) == 15.53


def test_benford_body_flags_a_month_above_1_5_points():
    rows = [
        {"m": "2025-01", "digit": "1", "n": 9}, {"m": "2025-01", "digit": "", "n": 3},
        {"m": "2025-02", "digit": "1", "n": 301}, {"m": "2025-02", "digit": "2", "n": 176}, {"m": "2025-02", "digit": "3", "n": 125},
        {"m": "2025-02", "digit": "4", "n": 97}, {"m": "2025-02", "digit": "5", "n": 79}, {"m": "2025-02", "digit": "6", "n": 67},
        {"m": "2025-02", "digit": "7", "n": 58}, {"m": "2025-02", "digit": "8", "n": 51}, {"m": "2025-02", "digit": "9", "n": 46},
    ]
    result = ga.BODIES["benford"]({"rows": rows}, "en", ga.clamped({}))
    assert [row["month"] for row in result["rows"]] == ["2025-01", "2025-02"]
    assert result["rows"][0]["cells"][0] == 100
    assert result["rows"][0]["cells"][9] == 9  # the unreadable digit is not a line of the population
    assert result["rows"][1]["cells"][10] < 1.5
    assert (result["exceptions"], result["population"]) == (1, 2)
    assert "1=30.1%" in result["note"]


def test_pearson():
    assert ga.pearson([1, 2, 3], [2, 4, 6]) == 1
    assert ga.pearson([1, 2, 3], [3, 2, 1]) == -1
    assert ga.pearson([1, 2], [1, 2]) is None  # fewer than three points
    assert ga.pearson([1, 1, 1], [1, 2, 3]) is None  # a flat series


def test_insights_pearson_is_its_own():
    assert gi.pearson([1, 2], [1, 2]) == 1
    assert gi.pearson([1], [1]) is None


@pytest.mark.parametrize("params,key,expected", [
    ({}, "days", 15), ({"yearEndDays": 0}, "days", 1), ({"yearEndDays": 500}, "days", 90), ({"yearEndDays": 7.5}, "days", 8),
    ({}, "factor", 2), ({"sdFactor": 0.1}, "factor", 0.5), ({"sdFactor": 99}, "factor", 6),
    ({}, "percentile", 0.99), ({"percentile": 0.1}, "percentile", 0.5), ({"percentile": 1}, "percentile", 0.9999),
    ({}, "min", 100000), ({"roundMin": 0}, "min", 1), ({"roundStep": 1e20}, "step", 1e15),
    ({}, "minOcc", 10), ({"minOccurrences": 1}, "minOcc", 2), ({"minOccurrences": 1e6}, "minOcc", 10000),
    ({}, "rareMax", 3), ({"rareMax": 0}, "rareMax", 1), ({"rareMax": 101}, "rareMax", 100),
    ({}, "pairMax", 3), ({}, "topN", 10), ({"topN": 0}, "topN", 1), ({"topN": 31}, "topN", 30),
])
def test_clamps(params, key, expected):
    assert ga.clamped(ga.read_params(params) if key != "pairMax" else params)[key] == expected


def test_the_route_drops_what_it_does_not_declare():
    assert ga.read_params({"pairMax": 9, "nonsense": 1, "topN": "x", "percentile": "0.9"}) == {"percentile": 0.9}
    assert ga.clamped(ga.read_params({"pairMax": 9}))["pairMax"] == 3


def test_clean_prefixes():
    assert ga.clean_prefixes(None) == ["40", "41"]
    assert ga.clean_prefixes(["x", "4'"]) == ["40", "41"]
    assert ga.clean_prefixes([" 52 ", "52", "1234567", "6"]) == ["52", "6"]
    assert len(ga.clean_prefixes([str(i) for i in range(20)])) == 12


def test_js_number():
    assert ga.js_number(None) == 0
    assert ga.js_number("") == 0
    assert ga.js_number(" 12.5 ") == 12.5
    assert ga.js_number(True) == 1
    assert math.isnan(ga.js_number("1_000"))
    assert math.isnan(ga.js_number("x"))


def test_year_end_totals_and_notes():
    rows = [{"m": "2025-12", "lines": 2, "value": 300.0, "wlines": 1, "wvalue": 100.0}, {"m": "2025-01", "lines": 1, "value": 100.0, "wlines": 0, "wvalue": 0.0}]
    result = ga.BODIES["year-end-concentration"]({"rows": rows}, "fr", ga.clamped({"yearEndDays": 20}))
    assert result["rows"][0]["cells"] == [2, 300, 75, 1, 100]
    assert result["totals"] == [3, 400, 100, 1, 100]
    assert result["columns"][3]["label"] == "Lignes des 20 derniers jours"


def test_monthly_spike_threshold():
    rows = [{"m": "2025-01", "lines": 1, "value": 10.0, "mu": 20.0, "sd": 5.0}, {"m": "2025-02", "lines": 1, "value": 31.0, "mu": 20.0, "sd": 5.0}]
    result = ga.BODIES["monthly-spikes"]({"rows": rows}, "en", ga.clamped({"sdFactor": 2}))
    assert [row["cells"][5] for row in result["rows"]] == [0, 1]
    assert result["rows"][0]["cells"][4] == 30
    assert result["columns"][4]["label"] == "Mean + 2 sd"
    assert result["totals"][2:5] == [None, None, None]


def test_by_person_folds_the_rest_and_keeps_the_gap():
    results = {
        "top": [{"person": "Awa", "v": 3.0}],
        "grid": [
            {"m": "2025-01", "person": "Awa", "v": 3.0}, {"m": "2025-01", "person": "Ben", "v": 1.0},
            {"m": "2025-01", "person": "Cid", "v": 1.0}, {"m": "2025-01", "person": None, "v": 2.0},
        ],
        "gap": [{"missing": 2, "lines": 7}],
    }
    result = ga.BODIES["preparer-volume"](results, "en", ga.clamped({}))
    assert [c["label"] for c in result["columns"]] == ["Awa", "Other", "Unattributed", "Total"]
    assert result["rows"][0]["cells"] == [3, 2, 2, 7]
    assert (result["exceptions"], result["population"]) == (2, 7)


def test_column_kinds():
    assert ga.column_kind("ledger-reconciliation", "debit") == "money"
    assert ga.column_kind("ledger-reconciliation", "lines") == "count"
    assert ga.column_kind("benford", "d3") == "decimal"
    assert ga.column_kind("weekend-postings", "d3") == "count"
    assert ga.column_kind("preparer-value", "p0") == "money"


# ---- correlation ---------------------------------------------------------


def test_ratio_keeps_its_sign_and_refuses_infinity():
    assert gc.ratio(-1, 4) == -0.25
    assert gc.ratio(1, 3) == 0.3333
    assert gc.ratio(1, 0) is None


def test_accounts_the_route_refuses_what_the_lib_cuts():
    assert gc.clean_accounts(["a b", " 411 "], 25) == ["411"]
    assert code_of(gc.clean_accounts, ["a b"], 25) == "invalid-accounts"
    assert gc.read_accounts([" 411 ", "411"], 25) == ["411"]
    assert code_of(gc.read_accounts, ["a b", "411"], 25) == "invalid-accounts"
    assert code_of(gc.read_accounts, "411", 25) == "invalid-accounts"
    assert code_of(gc.read_accounts, [], 25) == "invalid-accounts"
    assert code_of(gc.read_accounts, [str(i) for i in range(26)], 25) == "invalid-accounts"
    assert code_of(gc.read_accounts, ["4" * 41], 25) == "invalid-accounts"
    assert code_of(gc.read_accounts, ["411\n"[:3] + "\n" + "x"], 25) == "invalid-accounts"


def test_read_pair():
    assert gc.read_pair(" 411 ", "521") == ("411", "521")
    assert code_of(gc.read_pair, "411", "411") == "same-account"
    assert code_of(gc.read_pair, "", "411") == "invalid-accounts"
    assert code_of(gc.read_pair, None, "411") == "invalid-accounts"


def test_arrival_accounts():
    assert gc.arrival_accounts("411000, 521x,701") == ["411000", "701"]
    assert gc.arrival_accounts(["1" * 13, "12"]) == ["12"]
    assert len(gc.arrival_accounts([str(i) for i in range(60)])) == 50


def test_like_term():
    assert gc.like_term(" 50%_\\ ") == "50\\%\\_\\\\"
    assert gc.like_term(None) == ""
    assert len(gc.like_term("x" * 80)) == 60


@pytest.mark.parametrize("args,expected", [
    (("all", "net", 50, "weekday"), ("all", "net", 50, "weekday")),
    (("x", "x", 7, "x"), ("any", "abs", 20, "month")),
    (("any", "abs", "all", "month"), ("any", "abs", "all", "month")),
    (("any", "abs", "10", "month"), ("any", "abs", 10, "month")),
])
def test_entry_args(args, expected):
    result = gc.entry_args(*args)
    assert (result["mode"], result["rank"], result["limit"], result["period"]) == expected
    assert result["cap"] == (200 if expected[2] == "all" else expected[2])


def test_shape_entry_aligns_cells_with_counterparts():
    tops = [{"account": "A", "name": None, "net": 1.0, "gross": 1.0, "postings": 1, "entries": 1}, {"account": "B", "name": "b", "net": -2.0, "gross": 2.0, "postings": 1, "entries": 1}]
    grid = [{"m": "2025-02", "account": "B", "v": -2.0}, {"m": "2025-01", "account": "A", "v": 1.0}]
    head = {"entries": 2, "accounts": 5, "debit": 1.0, "credit": 2.0, "net": -1.0}
    result = gc.shape_entry(["X"], gc.entry_args(), head, tops, grid)
    assert result["months"] == [{"month": "2025-01", "cells": [1, None], "total": 1}, {"month": "2025-02", "cells": [None, -2], "total": -2}]
    assert result["hiddenAccounts"] == 3
    assert result["linkedEntries"] == 2


def test_shape_correlation():
    rows = [{"m": "2025-01", "a": 100.0, "b": -100.0}, {"m": "2025-02", "a": 300.0, "b": 0.0}, {"m": "2025-03", "a": 200.0, "b": -200.0}]
    result = gc.shape_correlation("A", "B", rows, 3)
    assert [month["ratio"] for month in result["months"]] == [-1, None, -1]
    assert (result["largestDifference"], result["largestDifferenceMonth"]) == (400, "2025-03")
    assert (result["totalA"], result["totalB"]) == (600, -300)
    assert result["monthsWithActivity"] == 3
    assert result["pearson"] is not None
    assert result["pearsonAbs"] is not None


def test_drill_page_caps():
    assert gc.drill_page({}) == (100, 0)
    assert gc.drill_page({"limit": 99999, "offset": 5.9}) == (500, 5)
    assert gc.drill_page({"limit": 0, "offset": -3}) == (100, 0)
    assert gc.drill_page({"limit": "x", "offset": "x"}) == (100, 0)
    assert gc.drill_page({"limit": -5}) == (1, 0)


@pytest.mark.parametrize("filter_,code", [
    ({"month": "2025-13"}, "invalid-month"),
    ({"month": "2025-1"}, "invalid-month"),
    ({"weekday": "0"}, "invalid-weekday"),
    ({"minAbs": -1}, "invalid-amount"),
    ({"maxAbs": math.nan}, "invalid-amount"),
    ({"dateFrom": "2025/01/01"}, "invalid-date"),
    ({"dateTo": "2025-02-31"}, "invalid-date"),
    ({"accounts": ["a b"]}, "invalid-accounts"),
    ({"entryAccounts": []}, "invalid-accounts"),
])
def test_drill_refusals(filter_, code):
    assert code_of(gc.drill_where, filter_, 1, 2) == code


def test_drill_where_binds_every_value():
    join, where, order, params = gc.drill_where({
        "accounts": ["411"], "month": "n/a", "weekday": "n/a", "jeNumber": " J' ", "preparer": "x", "minAbs": 1,
        "dateFrom": "2025-01-01", "journalCode": "VE", "weekendOnly": True, "missingReference": True,
    }, 1, 2)
    assert join == ""
    assert "'J" not in where
    assert " J'" not in where
    assert params["dataset"] == 1 and params["engagement"] == 2
    assert "J'" in params.values()
    assert order.startswith("l.journal_date")


def test_drill_whole_entries_finds_hits_then_shows_their_entries():
    join, where, order, params = gc.drill_where({
        "accounts": ["701"], "entryAccounts": ["411", "521"], "entryMode": "all", "wholeEntries": True,
    }, 1, 2)
    assert join == ""
    assert "l.je_number IN (SELECT h.je_number FROM ea_audit_gl_line h JOIN" in where
    assert "ent.je_number = h.je_number" in where
    assert "h.account = ANY" in where
    assert order == "l.je_number, l.line_no"
    assert 2 in params.values()


def test_read_drill_filter_whitelist():
    cleaned = gc.read_drill_filter({"nonsense": 1, "wholeEntries": "yes", "weekendOnly": True, "entryMode": "x", "month": 5})
    assert "nonsense" not in cleaned
    assert cleaned["wholeEntries"] is False
    assert cleaned["weekendOnly"] is True
    assert cleaned["entryMode"] == "any"
    assert cleaned["month"] == "5"
    assert cleaned["limit"] == 100


def test_reconcile_figure():
    assert gc.reconcile_figure(800, 900, 100, 2) == {"opening": 800, "movements": 100, "lines": 2, "computed": 900, "closing": 900, "gap": 0}
    assert gc.reconcile_figure(800, 1000.6, 100, 2)["gap"] == 101


def test_inputs():
    assert gc.split_accounts(" 411, 521;\n701 ") == ["411", "521", "701"]
    assert gc.amount_input("1 000,50") == 1000.5
    assert gc.amount_input("x") is None


# ---- insights ------------------------------------------------------------


@pytest.mark.parametrize("raw,iso", [
    ("15/01/2025", "2025-01-15"),
    ("15.01.25", "2025-01-15"),
    ("31/02/2025", "2025-03-03"),  # rolls over, as Date.UTC does
    ("2025-01-15", "2025-01-15"),
])
def test_insights_date_reader(raw, iso):
    assert gi.to_iso_date(gi.parse_date(raw)) == iso


@pytest.mark.parametrize("raw", ["", None, "  ", "rubbish"])
def test_insights_date_reader_refuses(raw):
    assert gi.parse_date(raw) is None


def test_role_insight():
    assert gi.role_insight("preparedBy", None, ["x"])["mapped"] is False
    role = gi.role_insight("preparedBy", ["a", "b"], ["b", "c"])
    assert (role["cyCount"], role["pyCount"], role["onlyCy"], role["onlyPy"]) == (2, 2, ["a"], ["c"])
    role = gi.role_insight("preparedBy", ["a"], None)
    assert (role["pyCount"], role["onlyCy"], role["onlyPy"]) == (None, [], [])


def test_class_volumes():
    current = gi.class_totals([{"cls": "4", "lines": 2, "gross": "100.4"}, {"cls": "9", "lines": 1, "gross": "1"}, {"cls": None, "lines": 1, "gross": "1"}])
    assert current == {"4": {"lines": 2, "gross": 100}}
    prior = gi.class_totals([{"cls": "4", "lines": 1, "gross": "50"}])
    result = gi.class_volume_rows(current, prior)
    four = result["rows"][3]
    assert (four["linesPct"], four["grossPct"]) == (100, 100)
    one = result["rows"][0]
    assert (one["pyLines"], one["linesPct"]) == (0, None)  # no base
    assert gi.class_volume_rows(current, None)["rows"][3]["pyLines"] is None


def test_weekday_analysis():
    result = gi.weekday_analysis([("01/02/2025", "J1", "10.6"), ("01/02/2025", "J1", "1"), ("02/02/2025", " ", "1"), ("nope", "J2", "9")])
    assert (result["rows"][5]["journals"], result["rows"][5]["lines"], result["rows"][5]["gross"]) == (1, 2, 12)
    assert (result["rows"][6]["journals"], result["rows"][6]["lines"]) == (0, 1)
    assert result["undated"] == 1


def test_entry_lag_takes_the_first_readable_pair_of_a_journal():
    result = gi.entry_lag([
        ("J1", "nope", "02/01/2025"), ("J1", "01/01/2025", "03/01/2025"), ("J1", "01/01/2025", "30/01/2025"),
        ("J2", "10/01/2025", "01/01/2025"), ("J3", "01/01/2025", "15/01/2025"), ("J4", "01/01/2025", "15/02/2025"), ("J5", "01/01/2025", "15/06/2025"),
    ])
    assert result["journals"] == 5
    assert [b["journals"] for b in result["buckets"]] == [1, 1, 1, 1, 1]
    assert result["maxDays"] == 165
    assert gi.entry_lag([])["avgDays"] == 0


def test_correlation_matrix():
    cleaned = gi.read_prefixes(["41", "52", "41"])
    assert cleaned == ["41", "52"]
    result = gi.correlation_matrix([
        ("411", "J1", "03/02/2025", "10"), ("521", "J1", "03/02/2025", "10"),
        ("411", "J2", "04/02/2025", "5"), ("601", "J2", "04/02/2025", "5"),
    ], cleaned)
    assert result["sharedJournals"] == 1
    assert result["matrix"][1][2] == 1
    assert result["prefixes"] == [{"prefix": "41", "lines": 2, "gross": 15}, {"prefix": "52", "lines": 1, "gross": 10}]
    assert result["pairs"][0]["a"] == "41"


@pytest.mark.parametrize("bad", [["41"], ["4", "52"], ["41a", "52"], [str(10 + i) for i in range(7)]])
def test_read_prefixes_refusals(bad):
    assert code_of(gi.read_prefixes, bad) == "invalid-accounts"
