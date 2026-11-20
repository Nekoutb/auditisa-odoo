"""Opening Balance Testing's grouping and comparison (owner's mock-ups "obt" and SYSCOHADA table, 20/11/2026)."""
import pytest

from services import obt

FORM = obt.load_form()

# ELIMELEC SARL's opening balances on staging (balance-generale-2025.csv), debit minus credit.
ELIMELEC = [
    ("101300", -150000000), ("111000", -14000000), ("121000", -61983749), ("131000", -88400000),
    ("162000", -100279259), ("166200", -630789), ("213100", 9000000), ("235000", 28000000),
    ("241100", 46000000), ("244200", 9500000), ("244400", 7200000), ("245100", 64000000),
    ("275100", 6000000), ("281300", -5500000), ("283500", -8400000), ("284100", -17250000),
    ("284420", -3562500), ("284440", -2160000), ("284500", -33000000), ("311100", 109468720),
    ("401100", -132956015), ("408100", -4817700), ("411100", 217833850), ("428100", -4150000),
    ("431100", -419300), ("431200", -131075), ("431300", -503160), ("441000", -8650000),
    ("444100", -15640000), ("445500", 777700), ("447200", -1034573), ("447820", -262150),
    ("476000", 2400000), ("521100", 152300000), ("571100", 1250000),
]


def accounts(rows=ELIMELEC):
    return [{"account": account, "name": "", "opening": opening} for account, opening in rows]


def test_the_form_is_the_owners_table():
    refs = [row["ref"] for row in FORM]
    assert len(refs) == 57 and refs[0] == "AD" and refs[-1] == "DZ"
    assert len([row for row in FORM if row["kind"] == "line"]) == 43
    assert {row["ref"]: row["balance"] for row in FORM if row["balance"]} == {
        "BJ": obt.DEBIT_ONLY, "BS": obt.DEBIT_ONLY, "DK": obt.CREDIT_ONLY, "DM": obt.CREDIT_ONLY, "DR": obt.CREDIT_ONLY,
    }


def test_parse_accounts():
    assert obt.parse_accounts("24 (sauf 245 et 2495), 2949p") == [
        {"prefix": "24", "excludes": ["245", "2495"], "partial": False},
        {"prefix": "2949", "excludes": [], "partial": True},
    ]
    assert obt.parse_accounts("12 (121 ou 129)") == [{"prefix": "12", "excludes": [], "partial": False}]
    assert obt.parse_accounts("2811, 2818p, 2919 p") == [
        {"prefix": "2811", "excludes": [], "partial": False},
        {"prefix": "2818", "excludes": [], "partial": True},
        {"prefix": "2919", "excludes": [], "partial": True},
    ]


def test_elimelec_ties_and_every_account_finds_its_line():
    lines, unmapped, to_choose = obt.group(accounts(), FORM)
    assert unmapped == [] and to_choose == []
    amounts = {ref: round(line["amount"]) for ref, line in lines.items()}
    assert amounts == {
        "AF": 3500000, "AL": 19600000, "AM": 39727500, "AN": 31000000, "AS": 6000000, "BB": 109468720,
        "BI": 217833850, "BJ": 3177700, "BS": 153550000, "CA": 150000000, "CF": 14000000, "CH": 61983749,
        "CJ": 88400000, "DA": 100910048, "DJ": 137773715, "DK": 30790258,
    }
    totals = obt.with_totals({ref: line["amount"] for ref, line in lines.items()}, FORM)
    assert round(totals["BZ"]) == round(totals["DZ"]) == 583857770
    assert round(totals["AZ"]) == 99827500 and round(totals["CP"]) == 314383749


@pytest.mark.parametrize("account, balance, ref", [
    ("445500", 777700, "BJ"),     # VAT recoverable in debit
    ("445500", -777700, "DK"),    # the same account in credit
    ("476000", 100, "BJ"), ("476000", -100, "DM"),
    ("478000", 100, "BU"), ("479000", -100, "DV"),
    ("521100", 5, "BS"), ("521100", -5, "DR"),
    ("409000", 5, "BH"), ("401000", -5, "DJ"), ("419000", -5, "DI"), ("411000", 5, "BI"),
    ("4998", -5, "DH"), ("4991", -5, "DN"),
    ("109000", 5, "CB"), ("129000", 5, "CH"),
])
def test_balance_rules_and_exceptions(account, balance, ref):
    assert obt.place(account, balance, FORM)[0] == ref


@pytest.mark.parametrize("account, ref", [
    ("28181", "AE"),   # with 2181, development costs
    ("28185", "AH"),   # the rest of 218
    ("2818", "AH"),
    ("29193", "AF"), ("29191", "AE"), ("29198", "AH"),
    ("29391", "AK"), ("29392", "AL"),
    ("29495", "AN"), ("29491", "AM"),
])
def test_p_accounts_go_with_the_asset_they_depreciate(account, ref):
    found, how, _refs = obt.place(account, -100, FORM)
    assert (found, how) == (ref, "asset")


def test_a_p_account_the_rule_cannot_place_is_left_to_choose_then_chosen():
    # 2919 alone names no asset sub-account of one line only: AE, AF and AH all hold 219x
    found, how, refs = obt.place("2919", -100, FORM)
    assert (found, how) == (None, "choose") and refs == ["AE", "AF", "AH"]
    assert obt.place("2919", -100, FORM, chosen={"2919": "AF"})[:2] == ("AF", "chosen")
    lines, unmapped, to_choose = obt.group([{"account": "2919", "name": "x", "opening": -100}], FORM)
    assert lines == {} and unmapped == [] and to_choose[0]["choices"] == ["AE", "AF", "AH"]


def test_an_account_no_line_takes_is_unmapped():
    lines, unmapped, _ = obt.group([{"account": "541000", "name": "Caisse", "opening": -5}], FORM)
    assert lines == {} and unmapped[0]["account"] == "541000"
    assert obt.group([{"account": "601000", "name": "Achats", "opening": 10}], FORM)[1][0]["account"] == "601000"


def test_compare_with_tolerance_and_summary():
    opening = {"BI": 217833850, "DJ": 137773715, "CA": 80061135}
    statements = {"BI": 219833850, "DJ": 139773715, "CA": 80061135.6}
    rows = {row["ref"]: row for row in obt.compare(statements, opening, FORM)}
    assert rows["BI"]["difference"] == -2000000 and not rows["BI"]["agrees"]
    assert rows["CA"]["agrees"]                       # 0.60 FCFA is within the 1 FCFA tolerance
    assert rows["AE"]["empty"] and not rows["BZ"]["empty"]
    result = obt.summary(list(rows.values()))
    assert result["lines"] == 3 and result["agree"] == 1 and result["differences"] == 2
    assert result["by_side"] == {"asset": {"lines": 1, "agree": 0}, "liability": {"lines": 2, "agree": 1}}
    assert result["assets_difference"] == -2000000 and round(result["liabilities_difference"]) == -2000001


def test_arithmetic_checks_catch_a_misread_figure():
    read = {"BI": 219833850, "BJ": 3177700, "BG": 223011550, "BZ": 223011550, "DJ": 223011550, "DZ": 223011550,
            "BK": 223011550, "DP": 223011550}
    assert all(check["ok"] for check in obt.arithmetic_checks(read, FORM))
    read["BJ"] = 3177070   # a digit swapped
    failed = [check for check in obt.arithmetic_checks(read, FORM) if not check["ok"]]
    assert [check["refs"] for check in failed] == [["BG"]]


def test_parse_reading_converts_units_and_drops_unknown_references():
    data = {
        "year_end": "2025-12-31", "unit": "thousands", "signed": True, "column": "Net 2025",
        "lines": [{"ref": "bi", "amount": 219833.85, "page": 2}, {"ref": "ZZ", "amount": 1, "page": 1},
                  {"ref": "DJ", "amount": True, "page": 3}],
        "net_result_income_statement": 88400,
    }
    read = obt.parse_reading(data, FORM)
    assert read["lines"] == {"BI": {"amount": 219833850.0, "page": 2}}
    assert (read["unit"], read["multiplier"], read["year_end"], read["signed"], read["net_result"]) == (
        "thousands", 1000, "2025-12-31", True, 88400000.0)
    assert obt.parse_reading({"unit": "dozens", "year_end": "31/12/2025"}, FORM)["year_end"] == ""
    with pytest.raises(ValueError):
        obt.parse_reading([], FORM)


def test_the_reading_schema_is_closed():
    schema = obt.reading_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert "BZ" in obt.reading_instructions(FORM)
