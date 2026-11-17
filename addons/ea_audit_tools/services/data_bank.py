"""The Data bank (owner, mock-ups approved 18/11/2026): the client's files, uploads only.

One tile per kind of file, in this order. Bank statements and supplier statements are no longer
offered: the records already uploaded stay in the database and readable, nothing offers them again.
"""
from .subledger_kinds import SUB_LEDGER_KINDS

#: (tile code, kind of file, English name, French name, English line, French line). The name and
#: the English line are the tile's data record (ea.audit.tool.tile.csv), the French its fr.po.
TILES = [
    ("an-tb", "trial_balance", "Trial balance", "Balance générale",
     "Balances of every account, opening and closing.", "Soldes de tous les comptes, à l'ouverture et à la clôture."),
    ("an-gl", "journal_entries", "General ledger", "Grand livre",
     "Every journal entry of the year.", "Toutes les écritures de l'exercice."),
    ("an-ar", "ar_open_items", "Accounts receivable ledger", "Grand livre clients",
     "Open items by customer.", "Opérations non soldées par client."),
    ("an-ap", "ap_open_items", "Accounts payable ledger", "Grand livre fournisseurs",
     "Open items by supplier.", "Opérations non soldées par fournisseur."),
    ("an-inventory", "inventory_listing", "Inventory ledger", "Grand livre des stocks",
     "Items in stock, quantities and values.", "Articles en stock, quantités et valeurs."),
    ("an-fixed", "fixed_asset_register", "Fixed assets register", "Registre des immobilisations",
     "Each asset, its cost and depreciation.", "Chaque immobilisation, son coût et ses amortissements."),
    ("an-payroll", "payroll_register", "Payroll sub-ledger", "Livre de paie",
     "Pay by employee and month.", "Paie par salarié et par mois."),
]
KIND_BY_TILE = {tile[0]: tile[1] for tile in TILES}

#: Kinds of file no screen offers any more (owner, 18/11/2026).
RETIRED_KINDS = ("bank_statement", "supplier_statements")
#: The kinds a person may still upload, in the order of the upload choice.
UPLOAD_KINDS = [kind for kind in SUB_LEDGER_KINDS if kind not in RETIRED_KINDS]

#: The timings in the order a chip names them.
TIMING_ORDER = ["prior_year", "pre_audit", "final", "post_audit", "subsequent"]


def chip(timings, labels, fr=False):
    """The chip of a tile: how many files were uploaded and of which timings, or "Not uploaded".

    ``timings`` holds one timing per upload kept on the file; ``labels`` maps a timing to the
    word the screen shows for it."""
    if not timings:
        return "Non importé" if fr else "Not uploaded"
    count = len(timings)
    seen = [timing for timing in TIMING_ORDER if timing in timings]
    seen += sorted(timing for timing in set(timings) if timing not in TIMING_ORDER)
    names = ", ".join(labels.get(timing, timing) for timing in seen)
    if fr:
        return "%d %s : %s" % (count, "fichier" if count == 1 else "fichiers", names)
    return "%d %s: %s" % (count, "file" if count == 1 else "files", names)
