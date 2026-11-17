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
    assert result["byAccount"] and [row["label"] for row in cost["rows"]] == ["231000", "245000"]
    assert [row["categories"] for row in cost["rows"]] == [["Bâtiments"], ["Transport"]]
    assert [(row["label"], row["ledger"]) for row in dep["rows"]] == [("2831", 400), ("2845", 90)]
    assert [(row["label"], row["ledger"]) for row in nbv["rows"]] == [("231000", 3600), ("245000", 810)]
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


# ---- 2026-11-17: the dates decide, at the year's edges ----------------------------------------

def test_the_dates_at_the_edges_of_the_year():
    on_first = asset_year(truck(acquired="2025-01-01"), *YEAR)
    assert (on_first["costOpening"], on_first["additions"]) == (0, 900) and abs(on_first["charge"] - 180) < 1e-9
    on_last = asset_year(truck(acquired="2025-12-31"), *YEAR)
    assert (on_last["costOpening"], on_last["additions"]) == (0, 900) and abs(on_last["charge"] - 180 / 365) < 1e-9
    year_before = asset_year(truck(acquired="2024-12-31"), *YEAR)
    assert (year_before["costOpening"], year_before["additions"]) == (900, 0)
    assert asset_year(truck(acquired="2026-01-01"), *YEAR) is None
    for day in ("2025-01-01", "2025-12-31"):
        sold = asset_year(truck(acquired="2024-06-01", disposed=day), *YEAR)
        assert sold["disposed"] and (sold["costOpening"], sold["additions"], sold["costDisposals"]) == (900, 0, 900)
    assert asset_year(truck(acquired="2024-06-01", disposed="2024-12-31"), *YEAR) is None
    kept = asset_year(truck(acquired="2024-06-01", disposed="2026-01-01"), *YEAR)
    assert not kept["disposed"] and kept["costDisposals"] == 0 and abs(kept["charge"] - 180) < 1e-9
    # acquired in an earlier year, disposed of in this one: an opening balance and a disposal, never an addition
    old = asset_year(building(disposed="2025-06-30"), *YEAR)
    assert (old["costOpening"], old["additions"], old["costDisposals"]) == (4000, 0, 4000)


def test_the_movements_at_the_edges_of_the_year():
    assets = [
        truck(row=1, acquired="2025-01-01"), truck(row=2, acquired="2025-12-31"), truck(row=3, acquired="2024-12-31"),
        truck(row=4, acquired="2026-01-01"), building(row=5, disposed="2025-01-01"), building(row=6, disposed="2025-12-31"),
        building(row=7, disposed="2024-12-31"), building(row=8, disposed="2026-01-01"),
        truck(row=9, acquired="2025-02-01", disposed="2025-11-30"),
    ]
    keys = [m["key"] for m in far_movements(assets, *YEAR)]
    assert keys == ["A1", "A2", "D5", "D6", "A9", "D9"]


# ---- 2026-11-17: the register's own additions and disposals at cost --------------------------

def test_the_register_amounts_replace_the_dates_and_a_disagreement_is_noticed():
    agreed = asset_year(truck(additions=900.0), *YEAR)
    assert agreed["additions"] == 900 and agreed["notices"] == []
    odd = asset_year(building(additions=250.0, disposalsCost=1000.0), *YEAR)
    assert (odd["additions"], odd["costDisposals"]) == (250, 1000) and odd["notices"] == ["additions", "disposals"]
    result = far_schedule([building(additions=250.0, item="B1"), truck()], LEDGER, *YEAR)
    cost = result["sections"]["cost"]
    assert cost["rows"][0]["additions"] == 250 and cost["rows"][0]["closing"] == 4250 and cost["rows"][0]["notices"] == ["B1"]
    assert result["notices"] == ["B1"] and cost["state"] == "difference"
    moves = far_movements([building(additions=250.0), truck(additions=0.0), building(row=3, disposalsCost=1500.0)], *YEAR)
    assert [(m["key"], m["amount"], m["notice"]) for m in moves] == [("A1", 250, True), ("D3", 1500, True)]
    sold = far_movements([building(disposed="2025-03-31", disposalsCost=4000.0)], *YEAR)[0]
    assert (sold["amount"], sold["notice"], sold["nbv"] is not None) == (4000, False, True)


# ---- 2026-11-17: rows by general ledger account ----------------------------------------------

def test_the_depreciation_account_of_a_cost_account():
    from services.far_schedule import depreciation_account
    assert [depreciation_account(a) for a in ("2441", "2311", "2154", "245000", "411", "")] == ["2844", "2831", "2815", "2845", "", ""]


def test_rows_by_account_with_ledger_only_accounts_and_shared_depreciation():
    ledger = [
        ("244100", "Mobilier", 1000.0), ("244200", "Informatique", 600.0), ("284400", "Amort. 244", -320.0),
        ("231000", "Bâtiments", 4000.0), ("283100", "Amort. bâtiments", -400.0),
        ("222000", "Terrains", 700.0), ("291000", "Dépréciation", -50.0), ("681100", "Dotations", 400.0),
    ]
    assets = [
        building(row=1, account="231000", depAccount="2831"),
        dict(building(row=2, category="Mobilier", account="2441", cost=1000.0, acquired="2024-01-01", rate=10.0)),
        dict(building(row=3, category="Informatique", account="2442", cost=600.0, acquired="2024-01-01", rate=20.0)),
    ]
    result = far_schedule(assets, ledger, *YEAR)
    cost, dep, nbv = (result["sections"][name] for name in ("cost", "depreciation", "nbv"))
    assert [(r["label"], r["ledger"], r["ledgerOnly"]) for r in cost["rows"]] == [
        ("222000", 700, True), ("231000", 4000, False), ("2441", 1000, False), ("2442", 600, False)]
    assert cost["rows"][0]["difference"] == -700 and cost["state"] == "difference"
    assert [(r["label"], r["ledger"], r["ledgerOnly"]) for r in dep["rows"]] == [
        ("2831", 400, False), ("2844", 320, False), ("291000", 50, True)]
    assert dep["rows"][1]["costAccounts"] == ["2441", "2442"]
    labels = [r["label"] for r in nbv["rows"]]
    assert "2441 + 2442" in labels and "222000" in labels and "291000" in labels
    shared = nbv["rows"][labels.index("2441 + 2442")]
    assert shared["ledger"] == 1280 and shared["categories"] == ["Mobilier", "Informatique"]
    # the ledger-only rows keep the totals whole: rows and total agree on the ledger
    assert sum(r["ledger"] for r in cost["rows"]) == cost["total"]["ledger"] == 6300
    assert round(sum(r["ledger"] for r in dep["rows"]), 2) == dep["total"]["ledger"] == 770


def test_the_longest_account_takes_the_ledger_balance_once():
    ledger = [("244100", "A", 100.0), ("244110", "B", 50.0), ("244200", "C", 30.0)]
    assets = [building(row=1, account="2441", cost=100.0), building(row=2, account="24411", cost=50.0),
              building(row=3, account="244", cost=30.0)]
    rows = far_schedule(assets, ledger, *YEAR)["sections"]["cost"]["rows"]
    assert [(r["label"], r["ledger"]) for r in rows] == [("244", 30), ("2441", 100), ("24411", 50)]


def test_without_the_account_column_the_categories_stay_with_a_note():
    result = far_schedule([building(), truck()], LEDGER, *YEAR, columns={"account": False})
    assert not result["byAccount"]
    assert [row["label"] for row in result["sections"]["cost"]["rows"]] == ["Bâtiments", "Transport"]
    assert result["sections"]["cost"]["total"]["ledger"] == 4900
    unmapped = far_schedule([building(account=""), truck(account="")], LEDGER, *YEAR)
    assert not unmapped["byAccount"] and not unmapped["linked"]


def test_the_charge_by_the_register_expense_accounts():
    ledger = LEDGER + [("681300", "Dotations transport", 80.0), ("681900", "Autres", 5.0)]
    assets = [building(chargeAccount="6811"), truck(chargeAccount="6813")]
    charge = far_schedule(assets, ledger, *YEAR)["sections"]["depreciation"]["charge"]
    assert [(r["label"], r["ledger"], r["ledgerOnly"]) for r in charge["rows"]] == [
        ("6811", 90, False), ("6813", 80, False), ("681900", 5, True)]
    assert charge["ledger"] == 175 and charge["rows"][0]["difference"] == 10
    plain = far_schedule([building(), truck()], ledger, *YEAR)["sections"]["depreciation"]["charge"]
    assert plain["rows"] is None and plain["ledger"] == 175
