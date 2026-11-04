"""lib/dataset-mapping.ts: the columns each sub-ledger kind needs, and the guess that
maps a file's headers onto them.

The guess matters most for the general ledger's entry number: a ledger whose "JE
number" is really its journal code turns every journal into one entry.
"""
import re
import unicodedata

from ._js import js_trim

#: Mandatory fields per dataset kind: the audit-relevant columns of each file.
FIELDS = {
    "journal_entries": [
        {
            "key": "account",
            "en": "Account number",
            "fr": "Numéro de compte",
            "required": True,
            "aliases": ["compte", "account", "code"],
        },
        {
            "key": "accountName",
            "en": "Account name",
            "fr": "Intitulé du compte",
            "aliases": ["intitule", "libellecompte", "accountname", "designation"],
        },
        {
            "key": "jeNumber",
            "en": "JE number",
            "fr": "Numéro d'écriture",
            "required": True,
            "aliases": [
                "jen",
                "jenumber",
                "jeno",
                "numeroecriture",
                "numecriture",
                "noecriture",
                "necriture",
                "npiece",
                "nopiece",
                "numeropiece",
                "piece",
                "entrynumber",
                "voucher",
                "entry",
                "numero",
            ],
        },
        {
            "key": "jeDescription",
            "en": "Transaction description",
            "fr": "Libellé de l'écriture",
            "required": True,
            "aliases": ["libelleecriture", "description", "narration", "libelle"],
        },
        {
            "key": "amount",
            "en": "Amount",
            "fr": "Montant",
            "required": True,
            "aliases": ["montant", "amount", "valeur"],
        },
        {
            "key": "journalDate",
            "en": "Journal date (period)",
            "fr": "Date du journal (période)",
            "required": True,
            "aliases": ["datejournal", "journaldate", "dateoperation", "date"],
        },
        {
            "key": "jeDate",
            "en": "JE date (entered)",
            "fr": "Date de saisie",
            "aliases": ["datesaisie", "dateecriture", "jedate", "entrydate"],
        },
        {
            "key": "costCenter",
            "en": "Cost centre",
            "fr": "Centre de coût",
            "aliases": ["centredecout", "centrecout", "costcenter", "costcentre", "section", "analytique"],
        },
        {
            "key": "recordedBy",
            "en": "Recorded by",
            "fr": "Saisi par",
            "aliases": ["saisipar", "recordedby", "utilisateur", "user", "operateur"],
        },
        {
            "key": "preparedBy",
            "en": "Prepared by",
            "fr": "Préparé par",
            "aliases": ["preparepar", "preparedby", "auteur"],
        },
        {
            "key": "approvedBy",
            "en": "Approved by",
            "fr": "Approuvé par",
            "aliases": ["approuvepar", "approvedby", "validepar", "validation"],
        },
        {"key": "debit", "en": "Debit", "fr": "Débit", "aliases": ["debit", "debitamount", "mouvementdebit"]},
        {
            "key": "credit",
            "en": "Credit",
            "fr": "Crédit",
            "aliases": ["credit", "creditamount", "mouvementcredit"],
        },
        {
            "key": "journalCode",
            "en": "Journal code",
            "fr": "Code journal",
            "aliases": ["cj", "codej", "jrn", "journal", "codejournal", "journalcode"],
        },
        {
            "key": "reference",
            "en": "Reference",
            "fr": "Référence",
            "aliases": ["reference", "piecejustificative", "piece", "ref", "docref"],
        },
        {
            "key": "thirdPartyCode",
            "en": "Third-party code",
            "fr": "Code tiers",
            "aliases": ["tiers", "codetiers", "thirdparty", "partner"],
        },
        {
            "key": "thirdPartyName",
            "en": "Third-party name",
            "fr": "Nom du tiers",
            "aliases": ["nomtiers", "thirdpartyname", "partnername"],
        },
        {
            "key": "reviewer",
            "en": "Reviewer",
            "fr": "Réviseur",
            "aliases": ["revisepar", "reviewer", "controlepar"],
        },
    ],
    "ap_open_items": [
        {
            "key": "party",
            "en": "Supplier number",
            "fr": "Numéro fournisseur",
            "required": True,
            "aliases": ["code", "numero", "compte", "fournisseur", "supplier", "vendor"],
        },
        {
            "key": "partyName",
            "en": "Supplier name",
            "fr": "Nom du fournisseur",
            "required": True,
            "aliases": [
                "nomfournisseur",
                "suppliername",
                "vendorname",
                "supplier",
                "fournisseur",
                "nom",
                "name",
                "intitule",
            ],
        },
        {
            "key": "reference",
            "en": "Transaction reference",
            "fr": "Référence de la transaction",
            "required": True,
            "aliases": ["reference", "piece", "facture", "invoice", "numerofacture", "document"],
        },
        {
            "key": "date",
            "en": "Transaction date",
            "fr": "Date de la transaction",
            "required": True,
            "aliases": ["datefacture", "invoicedate", "datepiece", "date"],
        },
        {
            "key": "amount",
            "en": "Transaction amount",
            "fr": "Montant de la transaction",
            "required": True,
            "aliases": ["montant", "amount", "solde", "balance", "valeur"],
        },
        {
            "key": "transactionType",
            "en": "Transaction type",
            "fr": "Type de transaction",
            "aliases": ["type", "typepiece", "nature", "sens"],
        },
        {
            "key": "location",
            "en": "Supplier location",
            "fr": "Localisation du fournisseur",
            "aliases": ["ville", "pays", "location", "region", "adresse"],
        },
        {
            "key": "paymentTerms",
            "en": "Payment terms (optional)",
            "fr": "Conditions de paiement (optionnel)",
            "aliases": ["terms", "term", "delai", "echeance", "paiement", "payment"],
        },
    ],
    "ar_open_items": [
        {
            "key": "party",
            "en": "Customer number",
            "fr": "Numéro client",
            "required": True,
            "aliases": ["code", "numero", "compte", "client", "customer"],
        },
        {
            "key": "partyName",
            "en": "Customer name",
            "fr": "Nom du client",
            "required": True,
            "aliases": ["nomclient", "customername", "customer", "client", "nom", "name", "intitule"],
        },
        {
            "key": "reference",
            "en": "Invoice reference",
            "fr": "Référence de la facture",
            "required": True,
            "aliases": ["reference", "facture", "invoice", "numerofacture", "piece", "document"],
        },
        {
            "key": "date",
            "en": "Invoice date",
            "fr": "Date de la facture",
            "required": True,
            "aliases": ["datefacture", "invoicedate", "datepiece", "date"],
        },
        {
            "key": "amount",
            "en": "Transaction amount",
            "fr": "Montant de la transaction",
            "required": True,
            "aliases": ["montant", "amount", "solde", "balance", "valeur"],
        },
        {
            "key": "transactionType",
            "en": "Transaction type",
            "fr": "Type de transaction",
            "aliases": ["type", "typepiece", "nature", "sens"],
        },
        {
            "key": "location",
            "en": "Customer location",
            "fr": "Localisation du client",
            "aliases": ["ville", "pays", "location", "region", "adresse"],
        },
        {
            "key": "paymentTerms",
            "en": "Payment terms (optional)",
            "fr": "Conditions de paiement (optionnel)",
            "aliases": ["terms", "term", "delai", "echeance", "paiement", "payment"],
        },
    ],
    "inventory_listing": [
        {
            "key": "item",
            "en": "Item number",
            "fr": "Numéro d'article",
            "required": True,
            "aliases": ["article", "item", "reference", "code", "sku"],
        },
        {
            "key": "itemDescription",
            "en": "Item description",
            "fr": "Désignation de l'article",
            "required": True,
            "aliases": ["designation", "description", "libelle", "intitule"],
        },
        {
            "key": "quantity",
            "en": "Quantity",
            "fr": "Quantité",
            "required": True,
            "aliases": ["quantite", "quantity", "qte", "qty"],
        },
        {
            "key": "unitPrice",
            "en": "Unit price",
            "fr": "Prix unitaire",
            "required": True,
            "aliases": ["prixunitaire", "unitprice", "pu", "cout"],
        },
        {
            "key": "amount",
            "en": "Amount",
            "fr": "Montant",
            "required": True,
            "aliases": ["montant", "amount", "valeur", "total"],
        },
    ],
    "fixed_asset_register": [
        {
            "key": "item",
            "en": "Asset number",
            "fr": "Numéro d'immobilisation",
            "required": True,
            "aliases": ["immobilisation", "asset", "reference", "code"],
        },
        {
            "key": "itemDescription",
            "en": "Description",
            "fr": "Désignation",
            "required": True,
            "aliases": ["designation", "description", "libelle"],
        },
        {
            "key": "amount",
            "en": "Cost",
            "fr": "Coût d'acquisition",
            "required": True,
            "aliases": ["cout", "cost", "valeurbrute", "montant"],
        },
        {
            "key": "depreciation",
            "en": "Accumulated depreciation",
            "fr": "Amortissements cumulés",
            "aliases": ["amortissement", "depreciation", "cumul"],
        },
        {
            "key": "nbv",
            "en": "Net book value",
            "fr": "Valeur nette comptable",
            "aliases": ["vnc", "netbookvalue", "valeurnette"],
        },
    ],
    "payroll_register": [
        {
            "key": "party",
            "en": "Employee number",
            "fr": "Matricule",
            "required": True,
            "aliases": ["matricule", "employee", "code"],
        },
        {
            "key": "partyName",
            "en": "Employee name",
            "fr": "Nom du salarié",
            "required": True,
            "aliases": ["nom", "name", "salarie", "employeename"],
        },
        {
            "key": "amount",
            "en": "Gross pay",
            "fr": "Salaire brut",
            "required": True,
            "aliases": ["brut", "gross", "salaire", "montant"],
        },
        {"key": "net", "en": "Net pay", "fr": "Salaire net", "aliases": ["net", "netapayer"]},
    ],
    "bank_statement": [
        {"key": "date", "en": "Date", "fr": "Date", "required": True, "aliases": ["date"]},
        {
            "key": "description",
            "en": "Description",
            "fr": "Libellé",
            "required": True,
            "aliases": ["libelle", "description", "narration"],
        },
        {
            "key": "amount",
            "en": "Amount",
            "fr": "Montant",
            "required": True,
            "aliases": ["montant", "amount", "valeur"],
        },
    ],
    "supplier_statements": [
        {
            "key": "party",
            "en": "Supplier number",
            "fr": "Numéro fournisseur",
            "required": True,
            "aliases": ["fournisseur", "supplier", "compte", "code"],
        },
        {
            "key": "partyName",
            "en": "Supplier name",
            "fr": "Nom du fournisseur",
            "aliases": ["nomfournisseur", "suppliername", "nom", "name"],
        },
        {
            "key": "amount",
            "en": "Amount",
            "fr": "Montant",
            "required": True,
            "aliases": ["montant", "amount", "solde", "balance"],
        },
    ],
}

JE_KEY = "jeKey"
JE_KEY_SEP = "\u001f"
JE_KEY_JOIN = " · "
JE_KEY_MAX = 4

_COMBINING = re.compile("[̀-ͯ]")
_NOT_ALNUM = re.compile(r"[^a-z0-9]")


def _clean_columns(columns):
    trimmed = (js_trim(h) for h in columns)
    return list(dict.fromkeys(h for h in trimmed if h))[:JE_KEY_MAX]


def je_key_columns(mapping):
    raw = (mapping or {}).get(JE_KEY)
    if not isinstance(raw, str) or not js_trim(raw):
        return []
    return _clean_columns(raw.split(JE_KEY_SEP))


def encode_je_key(columns):
    return JE_KEY_SEP.join(_clean_columns(columns))


def je_identity(data, key_columns, je_number_header, text):
    """The entry identity of one row: the composite key, else the JE number."""
    if key_columns:
        parts = []
        for header in key_columns:
            value = text(data.get(header))
            parts.append("" if value is None else value)
        return JE_KEY_JOIN.join(parts) if any(p != "" for p in parts) else None
    return text(data.get(je_number_header)) if je_number_header else None


def norm(value):
    return _NOT_ALNUM.sub("", _COMBINING.sub("", unicodedata.normalize("NFD", js_trim(value).lower())))


def auto_map(kind, headers):
    """Map a file's headers onto the kind's fields. Exact alias matches claim their
    header first, then substring matches fill in; a header is claimed once."""
    mapping = {}
    normalized = [(h, norm(h)) for h in headers]
    for exact in (True, False):
        for field in FIELDS[kind]:
            if mapping.get(field["key"]):
                continue
            for alias in field["aliases"]:
                hit = next(
                    (h for h, n in normalized if (n == alias if exact else alias in n) and h not in mapping.values()),
                    None,
                )
                if hit is not None:
                    mapping[field["key"]] = hit
                    break
    return mapping


def je_number_looks_like_journal_code(lines, entries):
    """A handful of distinct values over thousands of lines is not how entries are numbered."""
    if lines < 100 or entries <= 0:
        return False
    return lines / entries > 40 or (lines > 500 and entries < 20)
