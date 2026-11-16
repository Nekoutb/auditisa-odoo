"""K-M1 worked out by date, and K-M2's population (owner's request of 2026-11-16)."""
from services.far_schedule import asset_year, clean_vouch_patch, far_movements, far_schedule, vouch_state

YEAR = ("2025-01-01", "2025-12-31")
LEDGER = [
    ("231000", "Bâtiments", 4000.0), ("283100", "Amort. bâtiments", -400.0),
    ("245000", "Matériel de transport", 900.0), ("284500", "Amort. transport", -90.0),
    ("681100", "Dotations", 90.0), ("411000", "Clients", 800.0),
]


def building(**extra):
    return dict({"row": 1, "category": "Bâtiments", "account": "231000", "cost": 4000.0, "acquired": "2021-01-02",
                 "disposed": None, "rate": 2.5, "charge": None}, **extra)


def truck(**extra):
    return dict({"row": 2, "category": "Transport", "account": "245000", "cost": 900.0, "acquired": "2025-07-02",
                 "disposed": None, "rate": 20.0, "charge": None}, **extra)


def test_an_asset_held_all_year_and_one_bought_in_the_year():
    old = asset_year(building(), *YEAR)
    assert (old["costOpening"], old["additions"], old["depOpening"], old["charge"]) == (4000, 0, 400, 100)
    new = asset_year(truck(), *YEAR)
    # 2 July to 31 December: 183 days of 365
    assert (new["costOpening"], new["additions"], new["depOpening"]) == (0, 900, 0)
    assert abs(new["charge"] - 900 * 0.2 * 183 / 365) < 1e-9


def test_disposals_and_assets_out_of_the_year():
    sold = asset_year(building(disposed="2025-03-31"), *YEAR)
    assert sold["disposed"] and sold["costDisposals"] == 4000
    assert abs(sold["depDisposals"] - (400 + 100 * 90 / 365)) < 1e-9
    assert asset_year(building(disposed="2024-12-31"), *YEAR) is None
    assert asset_year(truck(acquired="2026-01-05"), *YEAR) is None
    assert asset_year(truck(rate=None), *YEAR) is None


def test_depreciation_never_exceeds_the_cost():
    old = asset_year(building(acquired="1980-01-01"), *YEAR)
    assert (old["depOpening"], old["charge"]) == (4000, 0)


def test_three_parts_against_the_ledger():
    result = far_schedule([building(charge=100.0), truck()], LEDGER, *YEAR)
    cost, dep, nbv = (result["sections"][name] for name in ("cost", "depreciation", "nbv"))
    assert cost["total"]["closing"] == 4900 and cost["total"]["ledger"] == 4900 and cost["state"] == "agrees"
    assert [row["label"] for row in cost["rows"]] == ["Bâtiments", "Transport"]
    assert dep["rows"][0]["difference"] == 100 and dep["state"] == "difference"
    assert dep["charge"]["register"] == 100 and dep["charge"]["ledger"] == 90
    assert nbv["total"]["ledger"] == 4410 and nbv["state"] == "difference"
    assert result["linked"] and result["state"] == "difference"
    explained = far_schedule([building(), truck()], LEDGER, *YEAR, {"depreciation": "Charge not booked", "nbv": "Same"})
    assert explained["sections"]["depreciation"]["state"] == "explained" and explained["state"] == "explained"


def test_missing_data_states():
    assert far_schedule([], LEDGER, *YEAR)["state"] == "no-register"
    assert far_schedule([building()], [], *YEAR)["state"] == "no-gl"
    result = far_schedule([building(), truck(acquired=None, row=7)], LEDGER, *YEAR)
    assert result["incomplete"] == [7] and result["used"] == 1


def test_the_additions_and_disposals_of_the_year():
    moves = far_movements([building(), truck(), building(row=3, disposed="2025-03-31", proceeds=3000.0)], *YEAR)
    assert [(m["key"], m["side"]) for m in moves] == [("A2", "addition"), ("D3", "disposal")]
    sold = moves[1]
    assert sold["nbv"] == round(4000 - 400 - 100 * 90 / 365, 2) and sold["gainLoss"] == round(3000 - sold["nbv"], 2)


def test_vouching_answers():
    assert clean_vouch_patch("addition", {"cost": "no", "note": " x "}) == {"cost": "no", "note": "x"}
    assert clean_vouch_patch("addition", {"removed": "yes"}) is None
    assert clean_vouch_patch("disposal", {"proceeds": "maybe"}) is None
    assert vouch_state("addition", {"cost": "no"}) == "exception"
    assert vouch_state("disposal", {k: "yes" for k in ("authorised", "removed", "proceeds")}) == "todo"
    assert vouch_state("disposal", {k: "na" for k in ("authorised", "removed", "proceeds", "gainloss")}) == "done"
