"""EAGLA (owner's mock-ups of 18/11/2026): the correlations 31 and 32, SCOT identification and
the drawings, on a small SYSCOHADA ledger of 2025 (eagla_ledger.json, beside this file: the
fixtures folder holds the parity recordings only)."""
import json
import os
import re

import pytest

from services import eagla_correlation as corr
from services import eagla_svg as svg
from services import scot_flows as scot
from services.errors import ServiceError

with open(os.path.join(os.path.dirname(__file__), "eagla_ledger.json"), encoding="utf-8") as handle:
    LINES = json.load(handle)["lines"]
START, END = "2025-01-01", "2025-12-31"
KEYS = corr.month_keys(2025, 1)
ROWS = corr.month_rows(LINES, START, END)


def analyse(class_key):
    return scot.analyse(
        scot.group_lines(LINES, class_key, START, END), class_key, KEYS, scot.middle_pairs(LINES, class_key, START, END),
    )


def flows(result):
    return {(f["source"], f["target"]): (pytest.approx(f["amount"]), f["entries"], f["unusual"]) for f in result["flows"]}


# ----------------------------------------------------------------------
# The sign convention
# ----------------------------------------------------------------------

@pytest.mark.parametrize("account,credit", [
    ("101000", True), ("162000", True), ("244100", False), ("284400", False), ("311000", False),
    ("401100", True), ("409000", False), ("411100", False), ("419000", True), ("422000", True),
    ("443100", True), ("445200", False), ("449000", False), ("481000", True),
    ("521000", False), ("571000", False), ("601000", False), ("701000", True),
    ("812000", False), ("822000", True), ("841000", True), ("891000", False),
])
def test_each_account_counts_on_its_natural_side(account, credit):
    assert corr.credit_normal(account) is credit
    assert corr.natural(account, -100.0) == (100.0 if credit else -100.0)


def test_the_sign_line_is_short_and_in_both_languages():
    for locale in ("en", "fr"):
        assert len(corr.SIGN_LINE[locale]) < 200 and "\n" not in corr.SIGN_LINE[locale]


# ----------------------------------------------------------------------
# 31. Two-way correlation
# ----------------------------------------------------------------------

def test_two_way_by_calendar_month():
    result = corr.two_way(ROWS, ["443"], ["70"], KEYS)
    assert result["numerator"][:3] == [180.0, 180.0, 0.0]
    assert result["denominator"][:3] == [1000.0, 1000.0, 500.0]
    assert result["numeratorYear"] == 360.0 and result["denominatorYear"] == 2500.0
    assert result["ratios"][:3] == [pytest.approx(18.0), pytest.approx(18.0), pytest.approx(0.0)]
    assert result["ratios"][3:] == [None] * 9
    assert result["yearRatio"] == pytest.approx(14.4)
    # 18 % is 3.6 points from 14.4 %, 0 % is 14.4 points away: all three stand apart at 1.5
    assert result["apart"] == [0, 1, 2]
    # the 2026 sale is outside the year audited
    assert corr.two_way(ROWS, ["443"], ["70"], KEYS, tolerance=4)["apart"] == [2]


def test_two_way_numbers_and_prefixes_mix():
    result = corr.two_way(ROWS, ["443100", "445"], ["70"], KEYS)
    assert result["numerator"][0] == 360.0  # VAT collected (a credit) and VAT recoverable (a debit), each on its side
    assert corr.two_way(ROWS, ["445"], ["60"], KEYS)["ratios"][0] == pytest.approx(18.0)


def test_a_nil_denominator_gives_no_ratio():
    result = corr.two_way(ROWS, ["443"], ["99"], KEYS)
    assert result["yearRatio"] is None and result["apart"] == []
    assert corr.apart_line(result["apart"], corr.month_labels(KEYS, "en"), None, "en").startswith("No yearly ratio")


def test_the_line_names_the_months_apart():
    labels = corr.month_labels(KEYS, "en")
    assert corr.apart_line([0, 1, 2], labels, 14.4, "en") == "Jan, Feb and Mar stand apart from the yearly average."
    assert corr.apart_line([2], labels, 14.4, "en") == "Mar stands apart from the yearly average."
    assert corr.apart_line([], labels, 14.4, "en") == "No month stands apart from the yearly average."
    assert corr.apart_line([0, 2], corr.month_labels(KEYS, "fr"), 14.4, "fr") == "janv. et mars s'écartent de la moyenne annuelle."


def test_the_year_audited_may_start_in_another_month():
    keys = corr.month_keys(2024, 7)
    assert keys[0] == (2024, 7) and keys[5] == (2024, 12) and keys[6] == (2025, 1) and keys[11] == (2025, 6)
    assert corr.month_labels(keys, "en")[0] == "Jul"


def test_accounts_are_read_with_care():
    assert corr.read_prefixes("443, 70;  411 70") == ["443", "70", "411"]
    for bad in ("", "  ", "70%", "4_1", ",".join(str(n) for n in range(21))):
        with pytest.raises(ServiceError):
            corr.read_prefixes(bad)


# ----------------------------------------------------------------------
# 32. Three-way correlation
# ----------------------------------------------------------------------

def test_three_way():
    result = corr.three_way(ROWS, ["70"], ["443"], ["411"], KEYS)
    assert result["a"][0] == 1000.0 and result["b"][0] == 180.0 and result["c"][0] == 1180.0
    assert result["c"][1] == 0.0  # February: invoiced 1 180, received 1 180
    assert result["ratios"]["ba"][0] == pytest.approx(18.0)
    assert result["ratios"]["ac"][0] == pytest.approx(1000 / 1180 * 100)
    assert result["ratios"]["bc"][0] == pytest.approx(180 / 1180 * 100)
    assert result["ratios"]["ac"][1] is None
    assert result["yearRatios"]["ba"] == pytest.approx(14.4)
    assert result["yearRatios"]["ac"] == pytest.approx(2500 / 1180 * 100)


def test_circles_follow_the_totals():
    big, small = corr.radii([2500.0, 360.0])
    assert big == 70.0 and small == pytest.approx(70.0 * (360 / 2500) ** 0.5)
    assert corr.radii([0.0, 0.0]) == [8.0, 8.0]
    drawing = svg.two_way_svg(2500.0, 360.0, "14.40 %", ["Denominator: 70", "Numerator: 443"], "Two-way")
    assert drawing.count("<circle") == 2 and svg.YELLOW in drawing and svg.ORANGE in drawing and "14.40 %" in drawing
    drawing = svg.three_way_svg([2500.0, 360.0, 1180.0], ["A: 70", "B: 443", "C: 411"], "Three-way")
    assert drawing.count("<circle") == 3 and svg.BLUE in drawing


def test_the_drawings_escape_what_they_show():
    assert "<b>" not in svg.two_way_svg(1, 1, "x", ["<b>", "&"], "<b>")
    assert svg.spaced(1234567.4) == "1 234 567"


# ----------------------------------------------------------------------
# SCOT identification
# ----------------------------------------------------------------------

def test_accounts_fall_in_their_groups():
    revenue = scot.CLASSES["revenue"]["groups"]
    assert scot.classify("701000", revenue) == "sales"
    assert scot.classify("443100", revenue) == "vat_sales"
    assert scot.classify("411100", revenue) == "customers"
    assert scot.classify("571000", revenue) == "bank"
    assert scot.classify("601000", revenue) == "other"
    assets = scot.CLASSES["fixed_assets"]["groups"]
    assert scot.classify("244100", assets) == "fixed_assets"
    assert scot.classify("284400", assets) == "other"  # depreciation is left out
    assert scot.classify("481000", assets) == "fa_suppliers"


def test_the_sql_names_the_same_groups():
    sql, params = scot.sql_case(scot.CLASSES["fixed_assets"]["groups"], "l.account")
    assert sql.startswith("CASE WHEN l.account LIKE ANY(%(g0)s::text[]) AND NOT l.account LIKE ANY(%(x0)s::text[]) THEN 'fixed_assets'")
    assert params["g0"] == ["2%"] and params["x0"] == ["28%", "29%"] and params["x1"] == []
    focus, params = scot.sql_focus("revenue", "f.account")
    assert focus.count("LIKE ANY") == 6 and params["f2"] == ["411%"]
    middle, params = scot.sql_middle("purchases")
    assert params["m0"] == ["401%"] and "%(mx0)s" in middle
    # nothing typed by a person reaches the text of the statement
    assert not re.search(r"'[0-9]", sql + focus + middle)


def test_an_entry_pairs_in_proportion():
    flows_ = scot.pair({"customers": 1180.0, "sales": -1000.0, "vat_sales": -180.0})
    assert sorted((s, t, round(a, 2)) for s, t, a in flows_) == [("sales", "customers", 1000.0), ("vat_sales", "customers", 180.0)]
    assert scot.pair({"bank": 0.0}) == []


def test_revenue_flows_timing_and_patterns():
    result = analyse("revenue")
    assert result["entries"] == 4  # VE1, VE2, BQ1, CA1: the 2026 sale is not of the year
    assert flows(result) == {
        ("sales", "customers"): (pytest.approx(2000.0), 2, False),
        ("vat_sales", "customers"): (pytest.approx(360.0), 2, False),
        ("customers", "bank"): (pytest.approx(1180.0), 1, False),
        ("sales", "bank"): (pytest.approx(500.0), 1, True),  # a sale straight to cash, no customer account
    }
    assert result["columns"] == [["sales", "vat_sales"], ["customers"], ["bank"]]
    assert result["timing"]["entering"][:3] == [1180.0, 1180.0, 0.0]  # invoiced to customers
    assert result["timing"]["leaving"][:3] == [0.0, 1180.0, 0.0]  # received in bank
    assert result["averageDays"] == {"days": 30.0, "pairs": 1}  # F1: 10 January to 9 February
    first = result["patterns"][0]
    assert (first["debit"], first["credit"], first["journal"], first["entries"], first["unusual"]) == ("bank", "sales", "CA", 1, True)
    assert first["jes"] == ["CA1"]
    keyed = {(p["debit"], p["credit"], p["journal"]): (p["entries"], round(p["amount"], 2)) for p in result["patterns"]}
    assert keyed[("customers", "sales", "VE")] == (2, 2000.0)
    assert keyed[("bank", "customers", "BQ")] == (1, 1180.0)
    assert scot.patterns_line(result, "en") == "4 debit → credit combinations, 1 of them unusual."


def test_purchases_paid_straight_from_cash_are_unusual():
    result = analyse("purchases")
    assert flows(result)[("bank", "purchases")] == (pytest.approx(50.0), 1, True)
    assert flows(result)[("suppliers", "purchases")][2] is False
    assert flows(result)[("bank", "suppliers")][2] is False
    assert result["timing"]["entering"][0] == 1180.0 and result["timing"]["leaving"][2] == 1180.0
    assert result["averageDays"] == {"days": 40.0, "pairs": 1}  # A1: 20 January to 1 March


def test_fixed_assets_leave_depreciation_out():
    result = analyse("fixed_assets")
    assert result["entries"] == 2
    assert set(flows(result)) == {("fa_suppliers", "fixed_assets"), ("bank", "fa_suppliers")}
    assert not any(f["unusual"] for f in result["flows"])


def test_no_pair_no_average():
    assert scot.average_days([{"d_first": "2025-01-10", "c_first": None}], "debit") is None
    assert scot.average_days([{"d_first": "2025-03-10", "c_first": "2025-01-01"}], "debit") is None


def test_treasury_money_in_and_out():
    result = analyse("treasury")
    assert result["entries"] == 9
    found = flows(result)
    assert found[("in:loans", "bank")] == (pytest.approx(10000.0), 1, False)
    assert found[("bank", "out:loans")] == (pytest.approx(1000.0), 1, False)
    assert found[("bank", "out:other")] == (pytest.approx(150.0), 2, False)
    assert found[("in:cash_sales", "bank")][2] is True
    assert result["columns"][0] == ["in:customers", "in:cash_sales", "in:loans", "in:capital"]
    assert result["columns"][2] == ["out:loans", "out:suppliers", "out:salaries", "out:fa_suppliers", "out:other"]
    table = {row["group"]: row for row in result["treasury"]}
    assert [row["group"] for row in result["treasury"]] == ["customers", "cash_sales", "loans", "capital", "suppliers", "salaries", "fa_suppliers", "other"]
    loans = table["loans"]
    assert (loans["entries"], loans["moneyIn"], loans["moneyOut"]) == (2, pytest.approx(10000.0), pytest.approx(1000.0))
    assert loans["busiestDay"] == 2 and loans["busiestWeekday"] == 4  # the 2nd; Friday 2 May 2025
    assert result["averageDays"] is None
    assert result["timing"]["entering"][4] == 10000.0 and result["timing"]["leaving"][5] == 1900.0


def test_treasury_labels_take_their_side():
    assert scot.node_label("in:loans", "en") == "Loans received (16)"
    assert scot.node_label("out:loans", "fr") == "Remboursements d'emprunts (16)"
    assert scot.node_label("bank", "en") == "Bank and cash (52, 57)"
    assert scot.weekday_of("2025-05-02") == 4 and scot.weekday_of("2025-06-02") == 0


def test_the_flow_diagram_draws_every_band():
    result = analyse("revenue")
    drawing = svg.flow_svg(result, "en", ("entry", "entries"), "Flows")
    assert drawing.count("<path") == 4 and drawing.count("<rect") == 4
    assert drawing.count(svg.UNUSUAL) == 1
    assert "2 000 · 2 entries" in drawing and "500 · 1 entry" in drawing
    assert "Sales (70)" in drawing and "Bank and cash (52, 57)" in drawing
    treasury = svg.flow_svg(analyse("treasury"), "fr", ("écriture", "écritures"), "Flux")
    assert "Emprunts reçus (16)" in treasury and "Remboursements d&#39;emprunts (16)" in treasury
    bars = svg.timing_svg(result["timing"]["entering"], result["timing"]["leaving"], corr.month_labels(KEYS, "en"), ["In", "Out"], "Timing")
    assert bars.count("<rect") == 24 + 2 and ">Dec<" in bars


def test_a_large_ledger_stays_quick():
    """100 000 lines summed as the database would (one row per entry and group), then paired."""
    rows = []
    for number in range(25000):
        je = "E%d" % number
        month = number % 12 + 1
        date = "2025-%02d-%02d" % (month, number % 28 + 1)
        rows += [
            {"je": je, "jd": date, "jc": "VE", "grp": "customers", "d": 1180.0, "c": 0.0},
            {"je": je, "jd": date, "jc": "VE", "grp": "sales", "d": 0.0, "c": 1000.0},
            {"je": je, "jd": date, "jc": "VE", "grp": "vat_sales", "d": 0.0, "c": 180.0},
            {"je": je, "jd": date, "jc": "VE", "grp": "other", "d": 0.0, "c": 0.0},
        ]
    import time

    began = time.perf_counter()
    result = scot.analyse(rows, "revenue", KEYS, [])
    assert time.perf_counter() - began < 10
    assert result["entries"] == 25000
    assert result["patterns"][0]["entries"] == 25000 and len(result["patterns"][0]["jes"]) == scot.ENTRY_CAP
