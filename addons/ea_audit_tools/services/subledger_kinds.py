"""lib/subledger-kinds.ts: the dataset kinds."""

SUB_LEDGER_KINDS = [
    "ar_open_items",
    "ap_open_items",
    "fixed_asset_register",
    "inventory_listing",
    "payroll_register",
    "bank_statement",
    "journal_entries",
    "supplier_statements",
]


def is_sub_ledger_kind(value):
    return isinstance(value, str) and value in SUB_LEDGER_KINDS
