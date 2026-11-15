"""The services added for the tools layer: hand-checked against lib/*.ts, not recorded."""
import pytest

from services.ap_schedules import ap_lead_schedules, index_resolver
from services.assertions import ASSERTIONS
from services.cra_board import cell_tod, default_relevance, is_rely_unsupported, suggested_cr, suggested_ir
from services.deficiency_model import evaluate_b5, suggested_grade
from services.fs_captions import asset_basis_label, bilan_totals, income_from_tb
from services.lead_classes import LEAD_INDEX_BY_CODE, lead_index_for
from services.materiality import (
    BENCHMARK_RANGES,
    compute_materiality,
    materiality_deviations,
    midpoint,
    tb_benchmark_amounts,
    validate_version,
)
from services.risk_model import PRESUMED_SEED, inherent_rating, risk_title
from services.significant_accounts import significance_rows, specific_refusal, unjustified_count

BALANCED = [
    {"account": "101000", "value": -5000},
    {"account": "162000", "value": -1000},
    {"account": "231000", "value": 4000},
    {"account": "283000", "value": -500},
    {"account": "311000", "value": 700},
    {"account": "391000", "value": -100},
    {"account": "411000", "value": 900},
    {"account": "495000", "value": -50},
    {"account": "401000", "value": -600},
    {"account": "521000", "value": 800},
    {"account": "561000", "value": -200},
    {"account": "590000", "value": -50},
    {"account": "601000", "value": 2000},
    {"account": "701000", "value": -3000},
    {"account": "891000", "value": 100},
    {"account": "812000", "value": 2000},
]


def test_the_bilan_nets_and_splits_as_the_source():
    bilan = bilan_totals(BALANCED)
    assert bilan["fixedAssets"] == 3500
    assert bilan["inventory"] == 600
    assert bilan["receivables"] == 850
    assert bilan["cashAssets"] == 750
    assert bilan["totalAssets"] == 5700
    assert bilan["class4Credit"] == 600
    assert bilan["cashLiabilities"] == 200
    assert bilan["class1"] == 6000
    assert bilan["netResult"] == -1100


def test_a_balanced_tb_balances_the_bilan():
    bilan = bilan_totals(BALANCED)
    assert sum(row["value"] for row in BALANCED) == 0
    assert bilan["totalAssets"] == bilan["totalLiabilitiesAndEquity"]


def test_490_and_499_sit_on_the_passif_whatever_their_sign():
    bilan = bilan_totals([{"account": "490100", "value": 40}, {"account": "499000", "value": -30}])
    assert bilan["receivables"] == 0
    assert bilan["class4Credit"] == -40 + 30


def test_class_4_follows_the_sign_of_each_account():
    bilan = bilan_totals([{"account": "401000", "value": 75}, {"account": "411000", "value": -25}])
    assert bilan["receivables"] == 75
    assert bilan["class4Credit"] == 25


@pytest.mark.parametrize("account, index", [
    ("101", "T"), ("161", "Q"), ("191", "P1"), ("231", "K"), ("281", "L"), ("284", "K"), ("291", "L"), ("31", "F"),
    ("401", "N"), ("411", "E"), ("490", "N"), ("491", "E"), ("499", "P1"), ("521", "C"),
])
def test_the_lead_classes_keep_the_map_the_bilan_relies_on(account, index):
    assert lead_index_for(account) == index


@pytest.mark.parametrize("account, kind", [("490", "Liabilities"), ("499", "Liabilities"), ("491", "Assets")])
def test_490_499_on_the_passif_because_their_lead_index_is_a_liability(account, kind):
    assert LEAD_INDEX_BY_CODE[lead_index_for(account)]["accountType"] == kind


def test_the_one_known_exception_to_the_lead_classes_is_56():
    """56 sits on the passif of the bilan and under index C, an asset index. See QUESTIONS.md:
    if the owner rules on it, this test records which side moved."""
    assert LEAD_INDEX_BY_CODE[lead_index_for("561")]["accountType"] == "Assets"
    assert bilan_totals([{"account": "561000", "value": 50}])["cashLiabilities"] == -50


def test_every_account_of_a_balanced_tb_lands_on_a_lead_schedule():
    rows = [dict(account=row["account"], name="", opening=0, closing=row["value"]) for row in BALANCED]
    assert sum(schedule["closing"] for schedule in ap_lead_schedules(rows, {})) == 0


def test_income_takes_class_8_and_keeps_89_apart():
    income = income_from_tb(BALANCED)
    assert income["beforeTax"] == 3000 - 2000 - 2000
    assert income["incomeTax"] == 100
    assert income["netResult"] == -1100


def test_the_label_beside_total_assets():
    assert asset_basis_label("fr", 3) == "Total actif net (SYSCOHADA), balance v3"
    assert asset_basis_label("en", None) == "Total net assets (SYSCOHADA)"
    # on the screens a trial balance is known by the date and time of its upload
    assert asset_basis_label("en", None, imported_on="12/11/2026 09:14") == "Total net assets (SYSCOHADA), TB of 12/11/2026 09:14"
    assert asset_basis_label("fr", 3, imported_on="12/11/2026 09:14") == "Total actif net (SYSCOHADA), balance du 12/11/2026 09:14"


def test_materiality_rounds_as_math_round():
    assert compute_materiality(1690000000, 5, 75, 5) == {"overall": 84500000, "performance": 63375000, "trivial": 4225000}


@pytest.mark.parametrize("amount, pct, perf, triv, expected", [
    (100, 5, 75, 5, None),
    (0, 5, 75, 5, "invalid-materiality"),
    (100, 0, 75, 5, "invalid-materiality"),
    (100, 101, 75, 5, "invalid-materiality"),
    (100, 5, 59.9, 5, "invalid-materiality"),
    (100, 5, 85.1, 5, "invalid-materiality"),
    (100, 5, 60, 3, None),
    (100, 5, 85, 5, None),
    (100, 5, 75, 2.9, "invalid-materiality"),
    (100, 5, 75, 5.1, "invalid-materiality"),
])
def test_the_ranges_of_a_new_version(amount, pct, perf, triv, expected):
    assert validate_version(amount, pct, perf, triv) == expected


def test_deviations():
    bases = {"revenue": 1000000, "pbt": -50000}
    assert materiality_deviations("revenue", 1000000, 1, bases) == {"outOfRange": False, "basisMismatch": False}
    assert materiality_deviations("revenue", 1000000, 3, bases)["outOfRange"]
    assert materiality_deviations("revenue", 1005001, 1, bases)["basisMismatch"]
    assert not materiality_deviations("revenue", 1005000, 1, bases)["basisMismatch"]
    assert materiality_deviations("pbt", 90000, 5, bases)["basisMismatch"]
    assert not materiality_deviations("equity", 90000, 2, None)["basisMismatch"]


def test_benchmark_bases_from_the_tb():
    assert tb_benchmark_amounts([]) is None
    bases = tb_benchmark_amounts(BALANCED)
    assert bases["revenue"] == 3000
    assert bases["expenses"] == 2000
    assert bases["pbt"] == 1000
    assert bases["equity"] == 5000
    assert bases["total_assets"] == 5700


def test_midpoints_fill_the_form():
    assert midpoint("pbt") == 7.5
    assert set(BENCHMARK_RANGES) == {"pbt", "revenue", "total_assets", "equity", "expenses"}


def test_significance_default_comes_from_te_a_specific_threshold_or_a_risk():
    rows = significance_rows(
        {"E": 900, "N": -300, "C": 100, "F": 200},
        500,
        {"C": 50},
        {"F": {"status": "significant", "justification": ""}},
        {"N": {"C"}},
    )
    by = {row["index"]: row for row in rows}
    assert by["E"]["defaultStatus"] == "significant"
    assert by["N"]["defaultStatus"] == "significant" and by["N"]["hasRisk"]
    assert by["C"]["defaultStatus"] == "significant" and by["C"]["specificTe"] == 50
    assert by["F"]["status"] == "significant" and by["F"]["overridden"]
    assert unjustified_count(rows) == 1


def test_a_linked_risk_locks_the_index_at_significant_whatever_was_recorded():
    rows = significance_rows(
        {"UA": -5000, "E": 900}, 10000, {},
        {"UA": {"status": "not_significant", "justification": "Small"}, "E": {"status": "not_significant", "justification": "Small"}},
        {"UA": {"E", "A"}},
    )
    by = {row["index"]: row for row in rows}
    assert by["UA"]["status"] == "significant" and by["UA"]["locked"] and not by["UA"]["overridden"]
    assert by["E"]["status"] == "not_significant" and not by["E"]["locked"]


def test_no_materiality_defaults_to_not_significant():
    assert significance_rows({"E": 900}, None, {}, {}, {})[0]["status"] == "not_significant"


@pytest.mark.parametrize("amount, expected", [
    (0, None), (None, None), (100, None), (700, "specific-above-te"), (750, "specific-above-te"),
    (1000, "specific-above-materiality"), (2000, "specific-above-materiality"),
])
def test_a_specific_materiality_sits_below_te(amount, expected):
    assert specific_refusal(amount, 1000, 700) == expected


def test_no_approved_materiality_no_specific_check():
    assert specific_refusal(5000, None, None) is None


@pytest.mark.parametrize("likelihood, magnitude, rating", [
    ("low", "low", "low"), ("low", "medium", "low"), ("low", "high", "medium"), ("medium", "medium", "medium"),
    ("medium", "high", "high"), ("high", "high", "high"), ("high", "low", "medium"),
])
def test_inherent_rating(likelihood, magnitude, rating):
    assert inherent_rating(likelihood, magnitude) == rating


def test_presumed_risks_read_in_the_readers_language():
    assert "Contournement" in risk_title("x", "mgmt_override", "fr")
    assert risk_title("typed", None, "fr") == "typed"
    assert [code for _p, code, _a in PRESUMED_SEED] == ["E4.20", "E3.1"]


def test_cra_relevance_defaults_and_ro_on_every_row():
    defaults = default_relevance([], [])
    assert [code for code in ASSERTIONS if defaults[code][0]] == ["C", "E", "A", "V", "RO"]
    assert defaults["RO"][1] and defaults["C"][1]
    recorded = default_relevance(["V"], ["E"])
    assert [code for code in ASSERTIONS if recorded[code][0]] == ["E", "V", "RO"]
    assert not recorded["V"][1] and recorded["RO"][1]


def test_cra_suggestions_and_reliance():
    assert suggested_ir(1) == "higher" and suggested_ir(0) == "lower"
    assert suggested_cr(1, 0, None) == "rely"
    assert suggested_cr(1, 1, None) == "not_rely"
    assert suggested_cr(1, 0, "not_support") == "not_rely"
    assert suggested_cr(0, 0, None) == "not_rely"
    assert is_rely_unsupported(0, None, " ")
    assert not is_rely_unsupported(0, None, "written basis")
    assert is_rely_unsupported(2, "not_support", "")
    assert not is_rely_unsupported(2, None, "")


def test_cra_cell_tod_carries_the_significant_overlay():
    assert cell_tod("lower", "rely", False) == "minimal"
    assert cell_tod("higher", "not_rely", True) == "high_sr"


@pytest.mark.parametrize("likelihood, magnitude, grade", [
    ("probable", "material", "significant_deficiency"),
    ("reasonably_possible", "material", "significant_deficiency"),
    ("remote", "material", "deficiency"),
    ("remote", "inconsequential", "observation"),
    ("probable", "inconsequential", "deficiency"),
    ("remote", "significant", "deficiency"),
    (None, "material", None),
    ("remote", None, None),
])
def test_isa_265_suggestion(likelihood, magnitude, grade):
    assert suggested_grade(likelihood, magnitude) == grade


def test_b5_uses_umt_and_leaves_trivial_items_out():
    items = [
        {"amount": 100, "corrected": False, "trivial": False},
        {"amount": 40, "corrected": True, "trivial": False},
        {"amount": 5, "corrected": False, "trivial": True},
    ]
    result = evaluate_b5(items, {"overall": 1000, "performance": 950, "trivial": 10})
    assert result["uncorrectedTotal"] == 100
    assert result["correctedTotal"] == 40
    assert result["trivialCount"] == 1
    assert result["finalMateriality"] == 50
    assert result["exceedsMateriality"] is True
    assert evaluate_b5(items, None)["exceedsMateriality"] is None


def test_prior_comes_from_a_prior_tb_else_the_opening():
    rows = [{"account": "411000", "name": "C", "opening": 80, "closing": 100}]
    assert ap_lead_schedules(rows, {})[0]["prior"] == 80
    with_tb = ap_lead_schedules(rows, {"411000": 50})[0]
    assert with_tb["prior"] == 50 and with_tb["priorSource"] == "prior_year_tb"
    assert with_tb["variancePct"] == 100
    assert ap_lead_schedules([{"account": "999", "name": "", "opening": 0, "closing": 1}], {}) == []


def test_client_override_longest_prefix_wins():
    index_of = index_resolver([("41", "G2"), ("4111", "C")])
    assert index_of("411100") == "C"
    assert index_of("411200") == "G2"
    assert index_of("401000") == "N"
