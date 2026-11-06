"""The client's findings on the tools, with a computed example for each number."""
from services.ap_schedules import ap_lead_schedules
from services.financial_analysis import FORMULAS, RATIO_KEYS, financial_analysis
from services.gl_line import population_checks
from services.sad_view import effective_income_after_tax, fs_caption_amounts


def _tb(**closing):
    return [{"account_code": code[1:], "opening": 0, "closing": value} for code, value in closing.items()]


def _ratios(view, column="current"):
    return {row["key"]: row[column] for row in view["rows"]}


def test_f064_return_ratios_are_after_tax():
    # Revenue 10M, costs 5M, tax 1M: net 4M. Capital 1M + net 4M = equity 5M, all held in the bank.
    view = financial_analysis(_tb(a101000=-1_000_000, a521000=5_000_000, a601000=5_000_000, a701000=-10_000_000, a891000=1_000_000), "2025-12-31")
    ratios = _ratios(view)
    assert ratios["roe"] == 80  # 4M / 5M; before tax it read 83.33 = 5M / 6M
    assert ratios["roa"] == 80  # 4M / 5M
    assert ratios["roce"] == 80  # (4M + 0) / (5M + 0)
    assert ratios["net"] == 50  # the margin stays before tax, and says so: 5M / 10M
    labels = {row["key"]: row for row in view["rows"]}
    assert labels["roe"]["label"].endswith("(after tax)")
    assert labels["roe"]["labelFr"].endswith("(après impôt)")


def test_f064_return_ratios_add_back_finance_costs_on_capital_employed():
    # Revenue 1000, finance costs 100, tax 200: net 700. Capital 300 + net 700 = equity 1000, debt 500.
    view = financial_analysis(_tb(a101000=-300, a162000=-500, a521000=1500, a671000=100, a701000=-1000, a891000=200), "2025-12-31")
    assert _ratios(view)["roce"] == 53.33  # (700 + 100) / (1000 + 500)


def test_f064_every_ratio_has_a_formula_in_both_languages():
    assert set(FORMULAS) == set(RATIO_KEYS)
    view = financial_analysis(_tb(a521000=100, a701000=-100), "2025-12-31")
    for row in view["rows"]:
        assert row["formula"] and row["formulaFr"]


def test_f064_a_blank_dso_or_dpo_says_why():
    no_ledger = financial_analysis(_tb(a411000=100, a701000=-100), "2025-12-31")
    rows = {row["key"]: row for row in no_ledger["rows"]}
    assert rows["dso"]["current"] is None
    assert "General Ledger" in rows["dso"]["note"]
    assert "grand livre" in rows["dpo"]["noteFr"]
    # A ledger in the window with sales but no purchases: DSO 45 days = 100 / 200 x 90, DPO blank.
    mapping = {"account": "A", "amount": "M", "journalDate": "D"}
    gl = [{"A": "701000", "M": "200", "D": "15/12/2025"}]
    view = financial_analysis(_tb(a411000=100, a701000=-100), "2025-12-31", gl_mapping=mapping, gl_rows=gl)
    rows = {row["key"]: row for row in view["rows"]}
    assert rows["dso"]["current"] == 45
    assert "blank" not in rows["dso"]
    assert rows["dpo"]["current"] is None
    assert "No purchases" in rows["dpo"]["blank"]
    assert "Aucun achat" in rows["dpo"]["blankFr"]


def test_f012_a_prior_closing_gives_the_income_statement_its_comparative():
    rows = [
        {"account": "121000", "name": "RAN", "opening": -30, "closing": -30},
        {"account": "701000", "name": "Sales", "opening": 0, "closing": -175},
    ]
    # the openings have no income statement, whatever the year did
    by_index = {s["index"]: s for s in ap_lead_schedules(rows, {})}
    assert {s["prior"] for s in by_index.values() if s["accounts"][0]["account"] == "701000"} == {0}
    # the prior file does: 150 of sales, and 8 of retained earnings before last year's result is carried
    prior = ap_lead_schedules(rows, {"121000": -8, "701000": -150}, source="prior_file")
    assert {s["accounts"][0]["account"]: s["prior"] for s in prior} == {"121000": -8, "701000": -150}
    assert {s["priorSource"] for s in prior} == {"prior_file"}


def test_f012_prior_closing_keeps_equity_and_result_together():
    # Prior year as in the demo file: 50 + 8 in class 1, 22 of result still in classes 6 and 7. The
    # analysis reads 80 of equity, which is the 80 the openings carried.
    view = financial_analysis(
        _tb(a101000=-50, a121000=-30, a521000=80),
        "2025-12-31",
        [{"account_code": "101000", "closing": -50}, {"account_code": "121000", "closing": -8},
         {"account_code": "521000", "closing": 58 + 22}, {"account_code": "601000", "closing": 128}, {"account_code": "701000", "closing": -150}],
    )
    ratios = _ratios(view, "prior")
    assert ratios["net"] == 14.67  # 22 / 150: no longer blank for the prior year
    assert ratios["dte"] == 0
    assert ratios["equity_ratio"] == 100  # 80 / 80


def test_f019_result_from_the_trial_balance_with_an_override():
    # Revenue 175, costs 147, no tax account: 28 after tax, as Négoce 2025 in millions.
    fs = fs_caption_amounts([{"account": "601000", "value": 147}, {"account": "701000", "value": -175}])
    assert fs["netResultAfterTax"] == 28
    assert effective_income_after_tax(0, fs["netResultAfterTax"]) == 28
    assert effective_income_after_tax(30, fs["netResultAfterTax"]) == 30
    assert effective_income_after_tax(0, None) is None


def test_m12_french_checks_group_as_french():
    checks = population_checks({
        "fields": {"account", "jeNumber", "jeDescription", "journalDate", "signedAmount"}, "mapping": {}, "source_rows": 1000,
        "lines": 1000, "entries": 500, "no_account": 0, "no_je": 0, "no_date": 0, "zero_amount": 0,
        "total_debit": 471936000, "total_credit": 471936000, "out_of_period": 0, "period_start": "2025-01-01",
        "period_end": "2025-12-31", "unbalanced": 0, "dup_groups": 0, "dup_extra": 0,
    })["checks"]
    balance = next(check for check in checks if "471" in check["detailEn"])
    assert balance["detailEn"].startswith("Debits 471,936,000 vs credits 471,936,000")
    assert "471,936,000" not in balance["detailFr"]
    assert balance["detailFr"].replace(" ", " ").startswith("Débits 471 936 000 contre crédits 471 936 000")
