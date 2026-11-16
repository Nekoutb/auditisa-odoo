"""Substantive procedures, second build (mock-sub2-*): working order, the fixed asset register
against the ledger (K-M1), the attendance at the count (F-M1) and the parties to confirm."""
from services.dataset_mapping import FIELDS, all_fields, auto_map, auto_map_extra
from services.import_matching import detect_mapping, fields_of
from services.procedure_tools import (
    COUNT_CHECK_KEYS, account_state, clean_count_patch, clean_count_size, clean_floor_item, clean_rollforward,
    confirmation_pick, count_item, count_left, count_sample, far_prefix, far_recon, is_far_account, rollforward,
    working_order,
)


def test_working_order_puts_mandatory_first():
    procs = [
        {"code": "K-A1", "kind": "ASP", "sequence": 40}, {"code": "X1", "kind": "custom", "sequence": 1},
        {"code": "K-M2", "kind": "MSP", "sequence": 39}, {"code": "K-M1", "kind": "MSP", "sequence": 38},
    ]
    assert [p["code"] for p in working_order(procs)] == ["K-M1", "K-M2", "K-A1", "X1"]


def test_account_colour():
    assert account_state(5, 0, 5) == "done"
    assert account_state(1, 0, 5) == "started"
    assert account_state(0, 1, 5) == "started"
    assert account_state(0, 0, 5) == "open"
    assert account_state(0, 0, 0) == "open"


# ---- K-M1 ----------------------------------------------------------------

LEDGER = [
    ("231000", "Bâtiments", 60_000_000), ("283100", "Amort. bâtiments", -3_000_000),
    ("245100", "Matériel de transport", 18_000_000), ("284510", "Amort. matériel de transport", -3_650_833),
    ("411000", "Clients", 5_000_000), ("261000", "Titres", 1_000_000),
]


def test_fixed_asset_accounts():
    assert far_prefix("245100") == "245"
    assert far_prefix("2451 Vehicles") == "245"
    assert far_prefix("Vehicles") is None
    assert far_prefix("411000") is None
    assert is_far_account("284510") and is_far_account("231000") and is_far_account("2931")
    assert not is_far_account("261000") and not is_far_account("2961") and not is_far_account("411")


def test_register_against_ledger_by_class():
    rows = [
        {"category": "Buildings", "account": "231000", "opening": 60_000_000, "additions": 0, "disposals": 0, "charge": 3_000_000, "closing": 57_000_000},
        {"category": "Vehicles", "account": "245100", "opening": 10_300_000, "additions": 6_500_000, "disposals": 1_800_000, "charge": 2_100_000, "closing": 12_900_000},
    ]
    result = far_recon(rows, LEDGER)
    by = {r["label"]: r for r in result["rows"]}
    assert by["Buildings"]["ledger"] == 57_000_000 and by["Buildings"]["difference"] == 0
    assert by["Vehicles"]["disposals"] == -1_800_000 and by["Vehicles"]["charge"] == -2_100_000
    assert by["Vehicles"]["ledger"] == 14_349_167
    assert by["Vehicles"]["difference"] == -1_449_167
    assert by["Vehicles"]["moveDifference"] == 0
    assert result["total"]["closing"] == 69_900_000
    assert result["total"]["ledger"] == 71_349_167
    assert result["total"]["difference"] == -1_449_167
    assert result["linked"] and result["state"] == "difference" and result["needsExplanation"]
    assert result["gaps"] == [{"label": "Vehicles", "difference": -1_449_167}]
    assert far_recon(rows, LEDGER, "Vehicle bought 28/12, not yet in the register")["state"] == "explained"


def test_register_without_accounts_compares_the_total_only():
    rows = [{"category": "All", "account": "", "opening": None, "additions": None, "disposals": None, "charge": None, "closing": 71_349_167}]
    result = far_recon(rows, LEDGER)
    assert not result["linked"] and result["rows"][0]["ledger"] is None
    assert result["state"] == "agrees" and not result["hasMovements"]


def test_ledger_accounts_missing_from_the_register_show_as_a_line():
    rows = [{"category": "Buildings", "account": "231", "opening": None, "additions": None, "disposals": None, "charge": None, "closing": 57_000_000}]
    result = far_recon(rows, LEDGER)
    rest = [r for r in result["rows"] if r.get("rest")]
    assert rest and rest[0]["ledger"] == 14_349_167 and rest[0]["difference"] == -14_349_167


def test_far_missing_data():
    assert far_recon([], LEDGER)["state"] == "no-register"
    rows = [{"category": "A", "account": "", "opening": None, "additions": None, "disposals": None, "charge": None, "closing": 1}]
    assert far_recon(rows, [("411", "Clients", 3)])["state"] == "no-gl"


def test_movements_that_do_not_add_up_are_flagged():
    rows = [{"category": "Buildings", "account": "231", "opening": 60_000_000, "additions": 0, "disposals": 0, "charge": 3_000_000, "closing": 56_000_000}]
    result = far_recon(rows, [("231", "B", 56_000_000)])
    assert result["moved"] == [{"label": "Buildings", "difference": -1_000_000}]
    assert result["state"] == "difference"


# ---- F-M1 ----------------------------------------------------------------

def test_count_sample_takes_the_highest_values_then_random():
    rows = [(n, float(n * 100)) for n in range(1, 51)]
    picks = count_sample(rows, 10, "seed")
    assert [p for p in picks if p[1] == "top"] == [(50, "top"), (49, "top"), (48, "top"), (47, "top"), (46, "top")]
    randoms = [n for n, reason in picks if reason == "random"]
    assert len(randoms) == 5 and all(n < 46 for n in randoms)
    assert count_sample(rows, 10, "seed") == picks  # the same seed draws the same items
    assert len(count_sample(rows[:3], 10, "s")) == 3


def test_count_items_and_what_is_left():
    assert count_item(1200, None) == (None, "todo")
    assert count_item(1200, 1200) == (0.0, "ok")
    assert count_item(4, 3) == (-1, "diff")
    assert count_item(None, 85) == (None, "missing")
    assert clean_count_size("15") == 15 and clean_count_size(0) is None and clean_count_size("x") is None
    assert clean_count_patch({"counted": "1 200"}) == {"counted": 1200.0}
    assert clean_count_patch({"counted": "-1"}) is None
    assert clean_count_patch({"other": 1}) is None
    assert clean_floor_item({"item": "MB-02", "counted": "85"}, adding=True) == {"item": "MB-02", "counted": 85.0}
    assert clean_floor_item({"counted": "85"}, adding=True) is None
    left = count_left({COUNT_CHECK_KEYS[0]: {"by": "A"}}, [{"counted": None}, {"counted": 3}], [{"counted": None}])
    assert left == {"checks": len(COUNT_CHECK_KEYS) - 1, "items": 2}


def test_rollforward_from_the_count_date():
    result = rollforward(104_200_000, 9_300_000, 3_755_460, 109_744_540)
    assert result == {"expected": 109_744_540, "difference": 0, "state": "agrees"}
    assert rollforward(100, 10, 5, 100)["difference"] == -5
    assert rollforward(None, 1, 1, 1)["state"] == "incomplete"
    assert clean_rollforward({"countDate": "2025-12-15", "count": "104 200 000"}) == {"countDate": "2025-12-15", "count": 104_200_000.0}
    assert clean_rollforward({"countDate": "15/12/2025"}) is None
    assert clean_rollforward({"other": 1}) is None


# ---- confirmations, uploads ---------------------------------------------------

def test_parties_proposed_for_confirmation():
    parties = [{"party": "C%02d" % n, "name": "Client %d" % n, "amount": float(1000 - n), "items": 1} for n in range(30)]
    picked = confirmation_pick(parties, ["client 0", "C01"], "s", top=3, extra=2)
    names = [p["party"] for p in picked]
    assert names[:3] == ["C02", "C03", "C04"]
    assert len(names) == 5 and not {"C00", "C01"} & set(names)
    assert confirmation_pick(parties[:2], ["C00", "C01"], "s") == []


def test_optional_columns_of_the_register_and_the_listing():
    assert all_fields("fixed_asset_register")[: len(FIELDS["fixed_asset_register"])] == FIELDS["fixed_asset_register"]
    keys = [f["key"] for f in fields_of("fixed_asset_register")]
    assert {"category", "account", "openingNbv", "additions", "disposals", "charge"} <= set(keys)
    assert "location" in [f["key"] for f in fields_of("inventory_listing")]
    headers = ["N° immobilisation", "Désignation", "Catégorie", "Coût", "Acquisitions", "Cessions", "Dotation", "VNC"]
    mapping = auto_map_extra("fixed_asset_register", headers, auto_map("fixed_asset_register", headers))
    assert mapping["category"] == "Catégorie" and mapping["additions"] == "Acquisitions" and mapping["charge"] == "Dotation"
    guessed, _sources = detect_mapping("inventory_listing", {"headers": ["Article", "Désignation", "Quantité", "PU", "Montant", "Magasin"], "rows": []})
    assert guessed["location"] == "Magasin"
