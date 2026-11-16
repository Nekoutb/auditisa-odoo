"""Execution of the designed procedures (owner's mock-ups of 2026-11-16, mock-proc-exec-*): the
overview counts, the reconciliation, the cut-off and unrecorded-liability selections, the item
results, and the confirmations."""
from services.procedure_execution import (
    CUTOFF_FAMILIES, clean_cutoff_patch, clean_explanation, clean_selection_params, confirmation_difference,
    confirmation_state, cutoff_select, cutoff_window, default_threshold, gl_accounts, is_confirmation, largest_parties,
    progress, recon_compare, selection_counts, split_steps, unrecorded_select,
)


def line(key, date, account, signed, je, label="", third=""):
    return {"key": key, "date": date, "account": account, "signed": signed, "je_number": je, "label": label, "third": third}


def test_progress_counts_the_states():
    assert progress(["done", "started", "draft", "done"]) == {"done": 2, "started": 1, "total": 4}
    assert progress([]) == {"done": 0, "started": 0, "total": 0}


def test_confirmation_type_and_steps():
    assert is_confirmation("E-M2", "Customer balance confirmations")
    assert is_confirmation("C-M1", "Bank confirmations")
    assert not is_confirmation("E-M3", "Sales cut-off")
    assert split_steps("Agree the totals; explain every difference. Then conclude.") == [
        "Agree the totals", "explain every difference.", "Then conclude.",
    ]
    assert split_steps("") == []


def test_default_threshold_is_ten_percent_of_performance_materiality():
    assert default_threshold(20_000_000) == 2_000_000
    assert default_threshold(None) is None


def test_reconciliation_totals_and_missing_states():
    accounts = gl_accounts([("411100", "Clients", 1000), ("416000", "Douteux", 200), ("401000", "Fournisseurs", -50)], ("41",), 1)
    assert [row["account"] for row in accounts] == ["411100", "416000"]
    result = recon_compare(accounts, 1150.0)
    assert (result["gl"], result["sub"], result["difference"], result["state"]) == (1200, 1150.0, -50, "difference")
    explained = recon_compare(accounts, 1150.0, [{"amount": -50}])
    assert (explained["unexplained"], explained["state"]) == (0, "explained")
    assert recon_compare(accounts, 1200.0)["state"] == "agrees"
    assert recon_compare([], 1200.0)["state"] == "no-gl"
    assert recon_compare(accounts, None)["state"] == "no-subledger"
    # payables: the credit balance reads as the sub-ledger's positive total
    payables = gl_accounts([("401000", "Fournisseurs", -500)], ("40",), -1)
    assert recon_compare(payables, 500.0)["state"] == "agrees"


def test_largest_parties_and_explanations():
    ranked = largest_parties([("C1", "Alpha", 100), ("C2", "Beta", 250), ("C1", "Alpha", 50), ("", "", 5)])
    assert [(p["party"], p["amount"], p["items"]) for p in ranked] == [("C2", 250, 1), ("C1", 150, 2)]
    assert clean_explanation({"text": "Timing", "amount": "1 250,5", "cleared": True}) == {"text": "Timing", "amount": 1250.5, "cleared": True}
    assert clean_explanation({"text": "x", "amount": "abc"}) is None
    assert clean_explanation({"other": 1}) is None


CURRENT = [
    # a sale on 28/12: receivable and revenue, counted once, as a positive sale
    line("c1", "2025-12-28", "411000", 900, "VE10", "Sale", "Alpha"),
    line("c2", "2025-12-28", "701000", -900, "VE10", "Sale", "Alpha"),
    # a credit note on 30/12: negative, picked for its size
    line("c3", "2025-12-30", "701000", 700, "AV01", "Credit note"),
    line("c4", "2025-12-30", "411000", -700, "AV01", "Credit note"),
    # below the threshold
    line("c5", "2025-12-29", "701000", -50, "VE11"),
    line("c6", "2025-12-29", "411000", 50, "VE11"),
    # before the window
    line("c7", "2025-12-01", "701000", -5000, "VE01"),
    line("c8", "2025-12-01", "411000", 5000, "VE01"),
    # an account the test does not read
    line("c9", "2025-12-31", "601000", 9000, "AC01"),
]
NEXT = [
    line("s1", "2026-01-03", "701000", -1200, "VE20", "Sale", "Beta"),
    line("s2", "2026-01-03", "411000", 1200, "VE20", "Sale", "Beta"),
    line("s3", "2026-01-20", "701000", -3000, "VE30"),  # after the window
    line("s4", "2026-01-05", "401000", 800, "BQ05", "Payment", "Supplier"),
    line("s5", "2026-01-05", "521000", -800, "BQ05", "Payment", "Supplier"),
    line("s6", "2026-02-10", "604000", 4000, "AC09", "Late invoice"),
]


def test_cutoff_window():
    first, last = cutoff_window("2025-12-31", 10)
    assert last - first == 19


def test_cutoff_selection_reads_both_ledgers_around_year_end():
    result = cutoff_select(CURRENT, NEXT, "2025-12-31", 10, 100, CUTOFF_FAMILIES["E"])
    picks = [(p["side"], p["entry"], p["amount"]) for p in result["picks"]]
    assert picks == [("before", "VE10", 900), ("before", "AV01", -700), ("after", "VE20", 1200)]
    assert result["population"] == {"before": 3, "after": 1, "total": 4, "value": 2850}
    assert result["window"] == {"from": "2025-12-22", "to": "2026-01-10"}
    assert result["picks"][0]["third"] == "Alpha"


def test_cutoff_selection_without_a_next_year_ledger():
    result = cutoff_select(CURRENT, None, "2025-12-31", 10, 100, CUTOFF_FAMILIES["E"])
    assert [p["side"] for p in result["picks"]] == ["before", "before"]
    assert result["population"]["after"] == 0


def test_a_wider_window_and_a_lower_threshold():
    result = cutoff_select(CURRENT, NEXT, "2025-12-31", 31, 0, CUTOFF_FAMILIES["E"])
    assert [p["entry"] for p in result["picks"]] == ["VE01", "VE10", "VE11", "AV01", "VE20", "VE30"]


def test_unrecorded_liabilities_read_the_next_year_only():
    result = unrecorded_select(NEXT, "2025-12-31", 60, 500)
    assert [(p["entry"], p["amount"]) for p in result["picks"]] == [("BQ05", 800), ("AC09", 4000)]
    assert unrecorded_select(NEXT, "2025-12-31", 20, 500)["picks"][0]["entry"] == "BQ05"
    assert unrecorded_select([], "2025-12-31", 60, 500)["picks"] == []


def test_selection_params_and_item_patch():
    assert clean_selection_params("10", "2 000 000") == (10, 2_000_000)
    assert clean_selection_params(0, 10) is None
    assert clean_selection_params(10, -1) is None
    assert clean_selection_params(10, "") is None
    assert clean_cutoff_patch({"period": "no", "doc": 1, "note": " late "}) == {"period": "no", "doc": True, "note": "late"}
    assert clean_cutoff_patch({"period": "maybe"}) is None
    assert clean_cutoff_patch({"audited": 1}) is None
    assert clean_cutoff_patch({}) is None


def test_selection_counts():
    results = {"c1": {"period": "yes"}, "c3": {"period": "no"}, "s1": {"note": "x"}}
    assert selection_counts(["c1", "c3", "s1"], results) == {"done": 2, "wrong": 1, "total": 3}


def test_confirmation_difference_and_state():
    assert confirmation_difference(1000, 900, "received") == -100
    assert confirmation_difference(1000, None, "received") is None
    assert confirmation_difference(1000, 900, "sent") is None
    assert confirmation_state(1000, 900, "received", "") == "difference"
    assert confirmation_state(1000, 900, "received", "Goods in transit") == "explained"
    assert confirmation_state(1000, 1000, "received", "") == "agrees"
    assert confirmation_state(1000, None, "no_reply", "") == "alternative"
    assert confirmation_state(1000, None, "sent", "") == "waiting"
