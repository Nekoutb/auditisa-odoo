"""lib/lead-classes.ts: the lead-schedule taxonomy, with the F059/F060 mapping.

Every index carries its account type and class and breaks into the workbook's
sub-totals. A SYSCOHADA longest-prefix map assigns an index and a sub-total to
every account of an uploaded trial balance; the user can override per client.
"""

LEAD_INDEXES = [
    {
        "code": "T",
        "accountType": "Equity",
        "accountClass": "Equity",
        "labelEn": "Share Capital & Reserves",
        "labelFr": "Capital & réserves",
    },
    {
        "code": "Q",
        "accountType": "Liabilities",
        "accountClass": "Other LT Liabilities",
        "labelEn": "Borrowings",
        "labelFr": "Emprunts",
    },
    {
        "code": "P1",
        "accountType": "Liabilities",
        "accountClass": "Other LT Liabilities",
        "labelEn": "Provisions for Risks & Charges",
        "labelFr": "Provisions pour risques & charges",
    },
    {
        "code": "P2",
        "accountType": "Liabilities",
        "accountClass": "Other Current Liabilities",
        "labelEn": "Social & Payroll Liabilities",
        "labelFr": "Dettes sociales",
    },
    {
        "code": "P3",
        "accountType": "Liabilities",
        "accountClass": "Other Current Liabilities",
        "labelEn": "Suspense & Deferred Income",
        "labelFr": "Comptes d'attente & produits constatés d'avance",
    },
    {
        "code": "P4",
        "accountType": "Liabilities",
        "accountClass": "Other LT Liabilities",
        "labelEn": "Translation Difference — Liabilities",
        "labelFr": "Écarts de conversion — passif",
    },
    {
        "code": "L",
        "accountType": "Assets",
        "accountClass": "Intangible Assets",
        "labelEn": "Intangible Assets",
        "labelFr": "Immobilisations incorporelles",
    },
    {
        "code": "K",
        "accountType": "Assets",
        "accountClass": "Fixed Assets",
        "labelEn": "Property, Plant & Equipment",
        "labelFr": "Immobilisations corporelles",
    },
    {
        "code": "J",
        "accountType": "Assets",
        "accountClass": "Other LT Assets",
        "labelEn": "Financial Assets",
        "labelFr": "Immobilisations financières",
    },
    {
        "code": "F",
        "accountType": "Assets",
        "accountClass": "Inventory",
        "labelEn": "Inventories",
        "labelFr": "Stocks",
    },
    {
        "code": "N",
        "accountType": "Liabilities",
        "accountClass": "Accounts Payable",
        "labelEn": "Trade Payables",
        "labelFr": "Fournisseurs",
    },
    {
        "code": "E",
        "accountType": "Assets",
        "accountClass": "Accounts Receivable",
        "labelEn": "Trade Receivables",
        "labelFr": "Clients",
    },
    {
        "code": "O1",
        "accountType": "Assets",
        "accountClass": "Other Assets/Liabilities",
        "labelEn": "Tax Receivables",
        "labelFr": "Créances fiscales",
    },
    {
        "code": "O2",
        "accountType": "Liabilities",
        "accountClass": "Other Assets/Liabilities",
        "labelEn": "Tax Payables",
        "labelFr": "Dettes fiscales",
    },
    {
        "code": "O4",
        "accountType": "Expenses",
        "accountClass": "Taxes Expense",
        "labelEn": "Income Tax & Profit-Sharing",
        "labelFr": "Impôt sur le résultat & participation",
    },
    {
        "code": "I1",
        "accountType": "Assets",
        "accountClass": "Other Assets/Liabilities",
        "labelEn": "Group & Associates — Short Term",
        "labelFr": "Groupe & associés — court terme",
    },
    {
        "code": "I2",
        "accountType": "Assets",
        "accountClass": "Other Assets/Liabilities",
        "labelEn": "Group & Associates",
        "labelFr": "Groupe & associés",
    },
    {
        "code": "G2",
        "accountType": "Assets",
        "accountClass": "Other Current Assets",
        "labelEn": "Other Current Assets",
        "labelFr": "Autres actifs circulants",
    },
    {
        "code": "G3",
        "accountType": "Assets",
        "accountClass": "Other Current Assets",
        "labelEn": "Translation Difference — Assets",
        "labelFr": "Écarts de conversion — actif",
    },
    {
        "code": "C",
        "accountType": "Assets",
        "accountClass": "Cash",
        "labelEn": "Cash & Cash Equivalents",
        "labelFr": "Trésorerie",
    },
    {
        "code": "UA",
        "accountType": "Revenues",
        "accountClass": "Revenue",
        "labelEn": "Revenue",
        "labelFr": "Chiffre d'affaires",
    },
    {
        "code": "UB2",
        "accountType": "Revenues",
        "accountClass": "Other Income/Expense",
        "labelEn": "Other Income",
        "labelFr": "Autres produits",
    },
    {
        "code": "UC",
        "accountType": "Revenues",
        "accountClass": "Interest Income/Expense",
        "labelEn": "Finance Income",
        "labelFr": "Produits financiers",
    },
    {
        "code": "U1",
        "accountType": "Revenues",
        "accountClass": "Extraordinary Income/Expense",
        "labelEn": "Exceptional Income",
        "labelFr": "Produits exceptionnels",
    },
    {
        "code": "VA1",
        "accountType": "Expenses",
        "accountClass": "Cost of Goods Sold",
        "labelEn": "Purchases",
        "labelFr": "Achats",
    },
    {
        "code": "VA2",
        "accountType": "Expenses",
        "accountClass": "Cost of Goods Sold",
        "labelEn": "Change in Inventories",
        "labelFr": "Variation de stocks",
    },
    {
        "code": "VB",
        "accountType": "Expenses",
        "accountClass": "Other Operating Expenses",
        "labelEn": "Personnel Costs",
        "labelFr": "Charges de personnel",
    },
    {
        "code": "VO",
        "accountType": "Expenses",
        "accountClass": "Other Operating Expenses",
        "labelEn": "Taxes & Duties",
        "labelFr": "Impôts & taxes",
    },
    {
        "code": "VD1",
        "accountType": "Expenses",
        "accountClass": "Other Operating Expenses",
        "labelEn": "Non-Stored Purchases, Transport & External Services",
        "labelFr": "Achats non stockés, transports & services extérieurs",
    },
    {
        "code": "VD2",
        "accountType": "Expenses",
        "accountClass": "Other Operating Expenses",
        "labelEn": "Depreciation & Provisions",
        "labelFr": "Dotations aux amortissements & provisions",
    },
    {
        "code": "VD3",
        "accountType": "Expenses",
        "accountClass": "Other Operating Expenses",
        "labelEn": "Provision Reversals & Expense Transfers",
        "labelFr": "Reprises de provisions & transferts de charges",
    },
    {
        "code": "VD4",
        "accountType": "Expenses",
        "accountClass": "Other Operating Expenses",
        "labelEn": "Other Expenses",
        "labelFr": "Autres charges",
    },
    {
        "code": "VD5",
        "accountType": "Expenses",
        "accountClass": "Interest Income/Expense",
        "labelEn": "Finance Costs",
        "labelFr": "Charges financières",
    },
    {
        "code": "V1",
        "accountType": "Expenses",
        "accountClass": "Extraordinary Income/Expense",
        "labelEn": "Exceptional Expenses",
        "labelFr": "Charges exceptionnelles",
    },
]

LEAD_INDEX_BY_CODE = {d["code"]: d for d in LEAD_INDEXES}

ACCOUNT_TYPE_FR = {
    "Assets": "Actif",
    "Liabilities": "Passif",
    "Equity": "Capitaux propres",
    "Revenues": "Produits",
    "Expenses": "Charges",
}

ACCOUNT_CLASS_FR = {
    "Equity": "Capitaux propres",
    "Other LT Liabilities": "Autres dettes à long terme",
    "Other Current Liabilities": "Autres passifs circulants",
    "Intangible Assets": "Immobilisations incorporelles",
    "Fixed Assets": "Immobilisations corporelles",
    "Other LT Assets": "Autres actifs à long terme",
    "Inventory": "Stocks",
    "Accounts Payable": "Dettes fournisseurs",
    "Accounts Receivable": "Créances clients",
    "Other Assets/Liabilities": "Autres actifs/passifs",
    "Taxes Expense": "Charge d'impôt",
    "Other Current Assets": "Autres actifs circulants",
    "Cash": "Trésorerie",
    "Revenue": "Chiffre d'affaires",
    "Other Income/Expense": "Autres produits/charges",
    "Interest Income/Expense": "Produits/charges financiers",
    "Extraordinary Income/Expense": "Produits/charges hors activités ordinaires",
    "Cost of Goods Sold": "Coût des ventes",
    "Other Operating Expenses": "Autres charges d'exploitation",
}

#: Distinct account classes, for the analyzer's class dropdown.
ACCOUNT_CLASSES = list(dict.fromkeys(d["accountClass"] for d in LEAD_INDEXES))

#: SYSCOHADA prefix to index, longest prefix wins.
PREFIX_INDEX = [
    ["10", "T"],
    ["11", "T"],
    ["12", "T"],
    ["13", "T"],
    ["14", "T"],
    ["15", "T"],
    ["16", "Q"],
    ["17", "Q"],
    ["18", "Q"],
    ["19", "P1"],
    ["20", "L"],
    ["21", "L"],
    ["22", "K"],
    ["23", "K"],
    ["24", "K"],
    ["25", "K"],
    ["26", "J"],
    ["27", "J"],
    ["28", "K"],
    ["281", "L"],
    ["29", "J"],
    ["291", "L"],
    ["292", "K"],
    ["293", "K"],
    ["294", "K"],
    ["295", "K"],
    ["3", "F"],
    ["40", "N"],
    ["41", "E"],
    ["42", "P2"],
    ["43", "P2"],
    ["44", "O2"],
    ["444", "O1"],
    ["445", "O1"],
    ["449", "O1"],
    ["45", "I2"],
    ["46", "I2"],
    ["462", "I1"],
    ["47", "G2"],
    ["476", "G2"],
    ["477", "P3"],
    ["478", "G3"],
    ["479", "P4"],
    ["48", "P3"],
    ["481", "N"],
    ["49", "G2"],
    ["490", "N"],
    ["491", "E"],
    ["499", "P1"],
    ["5", "C"],
    ["60", "VA1"],
    ["603", "VA2"],
    ["604", "VD1"],
    ["605", "VD1"],
    ["608", "VD1"],
    ["61", "VD1"],
    ["62", "VD1"],
    ["63", "VD1"],
    ["64", "VO"],
    ["65", "VD4"],
    ["66", "VB"],
    ["67", "VD5"],
    ["68", "VD2"],
    ["69", "VD2"],
    ["70", "UA"],
    ["71", "UB2"],
    ["72", "UB2"],
    ["73", "UB2"],
    ["75", "UB2"],
    ["77", "UC"],
    ["78", "VD3"],
    ["79", "VD3"],
    ["81", "V1"],
    ["82", "V1"],
    ["83", "V1"],
    ["84", "U1"],
    ["85", "U1"],
    ["86", "U1"],
    ["88", "U1"],
    ["89", "O4"],
]

#: The workbook's sub-totals within each index.
SUB_INDEXES = [
    {"code": "T-1", "index": "T", "labelEn": "Share capital & reserves"},
    {"code": "Q-1", "index": "Q", "labelEn": "Borrowings"},
    {"code": "P1-1", "index": "P1", "labelEn": "Provisions for risks & charges"},
    {
        "code": "P1-2",
        "index": "P1",
        "labelEn": "Short-term risk provisions (499)",
        "labelFr": "Risques provisionnés (499)",
    },
    {"code": "P2-1", "index": "P2", "labelEn": "Social & payroll liabilities"},
    {"code": "P3-1", "index": "P3", "labelEn": "Suspense accounts"},
    {"code": "P3-3", "index": "P3", "labelEn": "Deferred income"},
    {"code": "P4-1", "index": "P4", "labelEn": "Translation difference — liabilities"},
    {
        "code": "L-1",
        "index": "L",
        "labelEn": "Legacy class 20 — non-compliant with the revised SYSCOHADA",
        "labelFr": "Charges immobilisées (classe 20, supprimée)",
    },
    {"code": "L-2", "index": "L", "labelEn": "Intangible assets, gross"},
    {"code": "L-4", "index": "L", "labelEn": "Amortisation & impairment"},
    {"code": "K-1", "index": "K", "labelEn": "Land"},
    {"code": "K-2", "index": "K", "labelEn": "Buildings, technical installations & fittings"},
    {"code": "K-3", "index": "K", "labelEn": "Equipment"},
    {"code": "K-4", "index": "K", "labelEn": "Assets under construction & advances"},
    {"code": "K-6", "index": "K", "labelEn": "Depreciation & impairment"},
    {"code": "J-1", "index": "J", "labelEn": "Financial assets, gross"},
    {"code": "J-2", "index": "J", "labelEn": "Impairment of financial assets"},
    {"code": "F-1", "index": "F", "labelEn": "Inventories, gross"},
    {"code": "F-2", "index": "F", "labelEn": "Impairment of inventories"},
    {"code": "N-1", "index": "N", "labelEn": "Trade payables & related accounts"},
    {"code": "N-2", "index": "N", "labelEn": "Capital-expenditure payables"},
    {
        "code": "N-3",
        "index": "N",
        "labelEn": "Impairment of supplier debit balances",
        "labelFr": "Dépréciations des comptes fournisseurs",
    },
    {"code": "E-1", "index": "E", "labelEn": "Trade receivables, gross"},
    {"code": "E-2", "index": "E", "labelEn": "Impairment of trade receivables"},
    {"code": "O1-1", "index": "O1", "labelEn": "Tax receivables"},
    {"code": "O2-1", "index": "O2", "labelEn": "Tax payables"},
    {"code": "O4-1", "index": "O4", "labelEn": "Income tax & profit-sharing"},
    {"code": "I1-1", "index": "I1", "labelEn": "Group & associates — short term"},
    {"code": "I2-1", "index": "I2", "labelEn": "Group & associates"},
    {"code": "G2-1", "index": "G2", "labelEn": "Suspense accounts"},
    {"code": "G2-3", "index": "G2", "labelEn": "Prepaid expenses"},
    {"code": "G2-4", "index": "G2", "labelEn": "Impairment of other current accounts"},
    {"code": "G3-1", "index": "G3", "labelEn": "Translation difference — assets"},
    {"code": "C-1", "index": "C", "labelEn": "Cash & banks"},
    {"code": "C-3", "index": "C", "labelEn": "Provisioned financial risks"},
    {"code": "UA-1", "index": "UA", "labelEn": "Revenue"},
    {"code": "UB2-1", "index": "UB2", "labelEn": "Other income"},
    {"code": "UC-1", "index": "UC", "labelEn": "Finance income"},
    {"code": "U1-1", "index": "U1", "labelEn": "Exceptional income"},
    {"code": "VA1-1", "index": "VA1", "labelEn": "Purchases"},
    {"code": "VA2-1", "index": "VA2", "labelEn": "Change in inventories"},
    {"code": "VB-1", "index": "VB", "labelEn": "Personnel costs"},
    {"code": "VO-3", "index": "VO", "labelEn": "Taxes & duties"},
    {"code": "VD1-1", "index": "VD1", "labelEn": "Non-stored purchases"},
    {"code": "VD1-2", "index": "VD1", "labelEn": "Transport"},
    {"code": "VD1-3", "index": "VD1", "labelEn": "External services"},
    {"code": "VD2-1", "index": "VD2", "labelEn": "Depreciation charges"},
    {"code": "VD2-2", "index": "VD2", "labelEn": "Provision charges"},
    {"code": "VD3-1", "index": "VD3", "labelEn": "Provision reversals & expense transfers"},
    {"code": "VD4-1", "index": "VD4", "labelEn": "Other expenses"},
    {"code": "VD5-1", "index": "VD5", "labelEn": "Finance costs"},
    {"code": "V1-1", "index": "V1", "labelEn": "Exceptional expenses"},
]

SUB_INDEX_BY_CODE = {d["code"]: d for d in SUB_INDEXES}

#: Account prefix to sub-total, longest prefix wins.
PREFIX_SUB = [
    ["1", "T-1"],
    ["16", "Q-1"],
    ["17", "Q-1"],
    ["18", "Q-1"],
    ["19", "P1-1"],
    ["20", "L-1"],
    ["21", "L-2"],
    ["281", "L-4"],
    ["291", "L-4"],
    ["22", "K-1"],
    ["23", "K-2"],
    ["24", "K-3"],
    ["25", "K-4"],
    ["28", "K-6"],
    ["292", "K-6"],
    ["293", "K-6"],
    ["294", "K-6"],
    ["295", "K-6"],
    ["26", "J-1"],
    ["27", "J-1"],
    ["29", "J-2"],
    ["3", "F-1"],
    ["39", "F-2"],
    ["40", "N-1"],
    ["481", "N-2"],
    ["490", "N-3"],
    ["41", "E-1"],
    ["491", "E-2"],
    ["42", "P2-1"],
    ["43", "P2-1"],
    ["44", "O2-1"],
    ["444", "O1-1"],
    ["445", "O1-1"],
    ["449", "O1-1"],
    ["45", "I2-1"],
    ["46", "I2-1"],
    ["462", "I1-1"],
    ["47", "G2-1"],
    ["476", "G2-3"],
    ["477", "P3-3"],
    ["478", "G3-1"],
    ["479", "P4-1"],
    ["48", "P3-1"],
    ["49", "G2-4"],
    ["499", "P1-2"],
    ["5", "C-1"],
    ["59", "C-3"],
    ["60", "VA1-1"],
    ["603", "VA2-1"],
    ["604", "VD1-1"],
    ["605", "VD1-1"],
    ["608", "VD1-1"],
    ["61", "VD1-2"],
    ["62", "VD1-3"],
    ["63", "VD1-3"],
    ["64", "VO-3"],
    ["65", "VD4-1"],
    ["66", "VB-1"],
    ["67", "VD5-1"],
    ["68", "VD2-1"],
    ["69", "VD2-2"],
    ["70", "UA-1"],
    ["71", "UB2-1"],
    ["72", "UB2-1"],
    ["73", "UB2-1"],
    ["75", "UB2-1"],
    ["77", "UC-1"],
    ["78", "VD3-1"],
    ["79", "VD3-1"],
    ["81", "V1-1"],
    ["82", "V1-1"],
    ["83", "V1-1"],
    ["84", "U1-1"],
    ["85", "U1-1"],
    ["86", "U1-1"],
    ["88", "U1-1"],
    ["89", "O4-1"],
]

#: The internal working-paper section each index feeds: never chosen by the user.
INDEX_SECTION = {
    "E": "E4.1",
    "N": "E4.2",
    "F": "E4.3",
    "K": "E4.4",
    "L": "E4.5",
    "J": "E4.6",
    "C": "E4.7",
    "Q": "E4.8",
    "T": "E4.9",
    "P1": "E4.10",
    "P2": "E4.11",
    "P3": "E4.12",
    "P4": "E4.13",
    "O1": "E4.14",
    "O2": "E4.15",
    "I1": "E4.16",
    "I2": "E4.17",
    "G2": "E4.18",
    "G3": "E4.19",
    "UA": "E4.20",
    "UB2": "E4.21",
    "UC": "E4.22",
    "U1": "E4.23",
    "VA1": "E4.24",
    "VA2": "E4.25",
    "VB": "E4.26",
    "VO": "E4.27",
    "VD1": "E4.28",
    "VD2": "E4.29",
    "VD3": "E4.30",
    "VD4": "E4.31",
    "VD5": "E4.32",
    "V1": "E4.33",
    "O4": "E4.34",
}


def lead_index_label(definition, locale):
    return definition["labelFr"] if locale == "fr" else definition["labelEn"]


def account_type_label(account_type, locale):
    return ACCOUNT_TYPE_FR.get(account_type, account_type) if locale == "fr" else account_type


def account_class_label(account_class, locale):
    return ACCOUNT_CLASS_FR.get(account_class, account_class) if locale == "fr" else account_class


def default_index_for_class(account_class):
    """First index of an account class: the default when the user picks a class."""
    for definition in LEAD_INDEXES:
        if definition["accountClass"] == account_class:
            return definition["code"]
    return None


def _longest_prefix(rules, account):
    best = None
    for rule in rules:
        if not account.startswith(rule[0]):
            continue
        if best is None or len(rule[0]) > len(best[0]):
            best = rule
    return best[1] if best else None


def lead_index_for(account_or_prefix):
    """The index a SYSCOHADA account (or class prefix) maps to; None when unknown."""
    return _longest_prefix(PREFIX_INDEX, account_or_prefix)


def sub_index_for(account):
    """The workbook sub-total an account belongs to; None when unknown."""
    return _longest_prefix(PREFIX_SUB, account)


def sub_index_label(definition, locale):
    """French where the firm named the sub-total, else the workbook's English."""
    if locale == "fr" and definition.get("labelFr"):
        return definition["labelFr"]
    return definition["labelEn"]


def lead_schedule_alerts(accounts):
    """What a lead schedule warns about from its balances (F059 / F060): a balance
    on 490 (impaired supplier debit balances), a balance on class 20 (removed by
    the SYSCOHADA révisé)."""
    out = []
    with490 = [a["account"] for a in accounts if a["account"].startswith("490") and a["closing"] != 0]
    if with490:
        listed = ", ".join(with490)
        out.append({
            "code": "supplier_debit_impairment",
            "accounts": with490,
            "en": "Account 490 carries a balance (%s): supplier debit balances are impaired — check the reclassification of debit suppliers on E6.10 and the basis of the impairment." % listed,
            "fr": "Le compte 490 porte un solde (%s) : des comptes fournisseurs débiteurs sont dépréciés — vérifier le reclassement des fournisseurs débiteurs en E6.10 et le fondement de la dépréciation." % listed,
        })
    class20 = [a["account"] for a in accounts if a["account"].startswith("20") and a["closing"] != 0]
    if class20:
        listed = ", ".join(class20)
        out.append({
            "code": "legacy_class_20",
            "accounts": class20,
            "en": "Class 20 (capitalised charges) carries a balance (%s): the class was removed by the revised SYSCOHADA — the balance is non-compliant and must be reclassified or written off, and the finding carried to C1.1." % listed,
            "fr": "La classe 20 (charges immobilisées) porte un solde (%s) : la classe a été supprimée par le SYSCOHADA révisé — le solde est non conforme et doit être reclassé ou sorti, et le constat porté en C1.1." % listed,
        })
    return out
