"""lib/financial-analysis.ts: the ratio battery, computed twice.

Current Y from the working TB's closing balances; Prior Y from the prior-year TB's
closing balances when one is uploaded, else from the working TB's openings. DSO and
DPO draw the last three months of sales and purchases from the general ledger
(current year only). Balances are debit-positive, so credit-natured aggregates
(equity, liabilities, revenue) are negated.
"""
import re

from ._js import add_utc, cell_str, date_parts, date_utc, js_date_parse, js_round, js_trim
from .amount import amount_or
from .fs_captions import bilan_totals, income_from_tb

DEFS = [
    {
        "key": "current",
        "label": "Current ratio",
        "labelFr": "Ratio de liquidité générale",
        "group": "Liquidity",
        "unit": "x",
    },
    {
        "key": "quick",
        "label": "Quick ratio",
        "labelFr": "Ratio de liquidité réduite",
        "group": "Liquidity",
        "unit": "x",
    },
    {
        "key": "cash",
        "label": "Cash ratio",
        "labelFr": "Ratio de liquidité immédiate",
        "group": "Liquidity",
        "unit": "x",
    },
    {
        "key": "wc",
        "label": "Working capital",
        "labelFr": "Fonds de roulement",
        "group": "Liquidity",
        "unit": "FCFA",
    },
    {
        "key": "dso",
        "label": "DSO (days sales outstanding)",
        "labelFr": "Délai de règlement clients (jours)",
        "group": "Activity",
        "unit": "days",
    },
    {
        "key": "dpo",
        "label": "DPO (days payables outstanding)",
        "labelFr": "Délai de règlement fournisseurs (jours)",
        "group": "Activity",
        "unit": "days",
    },
    {
        "key": "inv_turn",
        "label": "Inventory turnover",
        "labelFr": "Rotation des stocks",
        "group": "Activity",
        "unit": "x",
    },
    {
        "key": "rec_turn",
        "label": "Receivables turnover",
        "labelFr": "Rotation des créances clients",
        "group": "Activity",
        "unit": "x",
    },
    {
        "key": "pay_turn",
        "label": "Payables turnover",
        "labelFr": "Rotation des dettes fournisseurs",
        "group": "Activity",
        "unit": "x",
    },
    {
        "key": "asset_turn",
        "label": "Asset turnover",
        "labelFr": "Rotation de l'actif",
        "group": "Activity",
        "unit": "x",
    },
    {
        "key": "gross",
        "label": "Gross margin",
        "labelFr": "Marge brute",
        "group": "Profitability",
        "unit": "%",
    },
    {
        "key": "ebitda",
        "label": "EBITDA margin",
        "labelFr": "Marge d'EBE",
        "group": "Profitability",
        "unit": "%",
    },
    {
        "key": "net",
        "label": "Net margin (PBT)",
        "labelFr": "Marge nette (résultat avant impôt)",
        "group": "Profitability",
        "unit": "%",
    },
    {
        "key": "gearing",
        "label": "Gearing",
        "labelFr": "Taux d'endettement (gearing)",
        "group": "Leverage",
        "unit": "%",
    },
    {
        "key": "dte",
        "label": "Debt to equity",
        "labelFr": "Dettes financières / capitaux propres",
        "group": "Leverage",
        "unit": "x",
    },
    {
        "key": "equity_ratio",
        "label": "Equity ratio",
        "labelFr": "Ratio d'autonomie financière",
        "group": "Leverage",
        "unit": "%",
    },
    {
        "key": "int_cover",
        "label": "Interest cover",
        "labelFr": "Couverture des charges financières",
        "group": "Leverage",
        "unit": "x",
    },
    {
        "key": "roa",
        "label": "Return on assets (after tax)",
        "labelFr": "Rentabilité de l'actif (après impôt)",
        "group": "Investment",
        "unit": "%",
    },
    {
        "key": "roe",
        "label": "Return on equity (after tax)",
        "labelFr": "Rentabilité des capitaux propres (après impôt)",
        "group": "Investment",
        "unit": "%",
    },
    {
        "key": "roce",
        "label": "Return on capital employed (after tax)",
        "labelFr": "Rentabilité des capitaux engagés (après impôt)",
        "group": "Investment",
        "unit": "%",
    },
]

#: The commentary keys the financial-analysis grid saves under index "FA".
RATIO_KEYS = [d["key"] for d in DEFS]

#: What each ratio divides by what, for the tooltip (F064): key -> (English, French).
FORMULAS = {
    "current": ("Current assets / current liabilities", "Actif circulant / passif circulant"),
    "quick": ("(Current assets - inventory) / current liabilities", "(Actif circulant - stocks) / passif circulant"),
    "cash": ("Cash and cash equivalents / current liabilities", "Trésorerie et équivalents / passif circulant"),
    "wc": ("Current assets - current liabilities", "Actif circulant - passif circulant"),
    "dso": ("Trade receivables / sales of the last 3 months of the year (from the general ledger) x 90", "Créances clients / ventes des 3 derniers mois de l'exercice (au grand livre) x 90"),
    "dpo": ("Trade payables / purchases of the last 3 months of the year (from the general ledger) x 90", "Dettes fournisseurs / achats des 3 derniers mois de l'exercice (au grand livre) x 90"),
    "inv_turn": ("Cost of sales / inventory", "Coût des ventes / stocks"),
    "rec_turn": ("Revenue / trade receivables", "Chiffre d'affaires / créances clients"),
    "pay_turn": ("Cost of sales / trade payables", "Coût des ventes / dettes fournisseurs"),
    "asset_turn": ("Revenue / total assets (net)", "Chiffre d'affaires / total actif net"),
    "gross": ("(Revenue - cost of sales) / revenue", "(Chiffre d'affaires - coût des ventes) / chiffre d'affaires"),
    "ebitda": ("(Profit before tax + finance costs + depreciation, amortisation and provisions) / revenue", "(Résultat avant impôt + charges financières + dotations aux amortissements et provisions) / chiffre d'affaires"),
    "net": ("Profit before tax / revenue", "Résultat avant impôt / chiffre d'affaires"),
    "gearing": ("Borrowings / (borrowings + equity)", "Emprunts et dettes financières / (emprunts et dettes financières + capitaux propres)"),
    "dte": ("Borrowings / equity", "Emprunts et dettes financières / capitaux propres"),
    "equity_ratio": ("Equity / total assets (net)", "Capitaux propres / total actif net"),
    "int_cover": ("(Profit before tax + finance costs) / finance costs", "(Résultat avant impôt + charges financières) / charges financières"),
    "roa": ("Profit after tax / total assets (net)", "Résultat net après impôt / total actif net"),
    "roe": ("Profit after tax / equity", "Résultat net après impôt / capitaux propres"),
    "roce": ("(Profit after tax + finance costs) / (equity + borrowings)", "(Résultat net après impôt + charges financières) / (capitaux propres + emprunts et dettes financières)"),
}

GL_NOTE = "No general ledger for this year: upload it in the General Ledger Analyzer to work out this ratio."  # i18n: term
GL_NOTE_FR = "Pas de grand livre pour cet exercice : l'importer dans l'analyseur de grand livre pour calculer ce ratio."
PRIOR_NOTE = "Prior year: no prior-year general ledger uploaded."  # i18n: term
PRIOR_NOTE_FR = "Exercice précédent : aucun grand livre N-1 importé."
# The ledger is there but holds nothing in the last 3 months of the year: the period and the data do not match.
MISMATCH_NOTE = ("The audit period and the data do not match: this year ends on %(end)s, but the general ledger "
                 "uploaded runs from %(first)s to %(last)s. Check the engagement's year or upload the ledger of this period.")  # i18n: term
MISMATCH_NOTE_FR = ("La période auditée et les données ne concordent pas : l'exercice se termine le %(end)s, mais le grand "
                    "livre importé couvre du %(first)s au %(last)s. Vérifier l'exercice de la mission ou importer le grand livre de cette période.")
PRIOR_MISMATCH_NOTE = ("Prior year: the period and the data do not match: the prior year ends on %(end)s, but the prior-year "
                       "general ledger runs from %(first)s to %(last)s.")  # i18n: term
PRIOR_MISMATCH_NOTE_FR = ("Exercice précédent : la période et les données ne concordent pas : l'exercice précédent se termine le "
                          "%(end)s, mais le grand livre N-1 couvre du %(first)s au %(last)s.")
# A ledger with nothing to divide by leaves a blank too; the source does not say why (F064).
NO_SALES_NOTE = "No sales in the general ledger for the last 3 months of the year: nothing to divide by."  # i18n: term
NO_SALES_NOTE_FR = "Aucune vente au grand livre sur les 3 derniers mois de l'exercice : rien à diviser."
NO_PURCHASES_NOTE = "No purchases in the general ledger for the last 3 months of the year: nothing to divide by."  # i18n: term
NO_PURCHASES_NOTE_FR = "Aucun achat au grand livre sur les 3 derniers mois de l'exercice : rien à diviser."

_DMY = re.compile(r"([0-9]{1,2})[/.-]([0-9]{1,2})[/.-]([0-9]{4})")
_EQUITY = re.compile(r"1[0-5]")
_DEBT = re.compile(r"1[6-8]")
_PURCHASES = re.compile(r"6[0-2]")


def aggregate(rows, override_of=None):
    """The balances of a {account, value} list. A client's corrected lead-index mapping
    re-homes an account for the ratio buckets too (UAT B65); accounts without an
    override keep the SYSCOHADA prefix rules."""
    override_of = override_of or (lambda account: None)

    def total(test):
        result = 0
        for row in rows:
            if test(row):
                result += row["value"]
        return result

    def bucket(prefix_rule, index_rule):
        def test(row):
            code = override_of(row["account"])
            return index_rule(code) if code else prefix_rule(row)
        return test

    def starts(*prefixes):
        return lambda row: row["account"].startswith(prefixes)

    inventory = total(bucket(starts("3"), lambda c: c == "F"))
    cash = total(bucket(lambda r: r["account"].startswith("5") and not r["account"].startswith("59"), lambda c: c == "C"))
    bilan = bilan_totals(rows)
    revenue = -total(starts("7"))
    expenses = total(starts("6"))
    cogs = total(bucket(starts("60"), lambda c: c.startswith("VA")))
    finance_costs = total(starts("67"))
    depreciation = total(starts("68", "69"))
    pbt = revenue - expenses
    # Net of income tax (89), as the SAD reads it. A pre-closing TB carries the year's result
    # in classes 6/7, not in a 13x account: equity then includes that result, or every equity
    # ratio is misstated.
    net_result = income_from_tb(rows)["netResult"]
    has_result_account = any(r["account"].startswith("13") and r["value"] != 0 for r in rows)
    payables_bucket = bucket(starts("40"), lambda c: c == "N")
    return {
        "inventory": inventory,
        "receivables": total(bucket(starts("41"), lambda c: c == "E")),
        "cash": cash,
        "currentAssets": bilan["currentAssets"],
        "currentLiabilities": bilan["currentLiabilities"],
        "payables": -total(lambda r: r["value"] < 0 and payables_bucket(r)),
        "equity": -total(lambda r: _EQUITY.match(r["account"]) is not None) + (0 if has_result_account else net_result),
        "financialDebt": -total(lambda r: _DEBT.match(r["account"]) is not None),
        "totalAssets": bilan["totalAssets"],
        "revenue": revenue,
        "expenses": expenses,
        "cogs": cogs,
        "financeCosts": finance_costs,
        "depreciation": depreciation,
        "pbt": pbt,
        "netResult": net_result,
        "ebitda": pbt + finance_costs + depreciation,
    }


def _r2(value):
    return js_round(value * 100) / 100


def _div(a, b):
    return _r2(a / b) if b != 0 else None


def _pct(a, b):
    return _r2((a / b) * 100) if b != 0 else None


def ratio_set(b):
    """The ratio set for one balance state; P&L ratios go None when there is no activity."""
    no_pl = b["revenue"] == 0 and b["expenses"] == 0
    return {
        "current": _div(b["currentAssets"], b["currentLiabilities"]),
        "quick": _div(b["currentAssets"] - b["inventory"], b["currentLiabilities"]),
        "cash": _div(max(b["cash"], 0), b["currentLiabilities"]),
        "wc": js_round(b["currentAssets"] - b["currentLiabilities"]),
        "inv_turn": None if no_pl else _div(b["cogs"], b["inventory"]),
        "rec_turn": None if no_pl else _div(b["revenue"], b["receivables"]),
        "pay_turn": None if no_pl else _div(b["cogs"], b["payables"]),
        "asset_turn": None if no_pl else _div(b["revenue"], b["totalAssets"]),
        "gross": None if no_pl else _pct(b["revenue"] - b["cogs"], b["revenue"]),
        "ebitda": None if no_pl else _pct(b["ebitda"], b["revenue"]),
        "net": None if no_pl else _pct(b["pbt"], b["revenue"]),
        "gearing": _pct(b["financialDebt"], b["financialDebt"] + b["equity"]),
        "dte": _div(b["financialDebt"], b["equity"]),
        "equity_ratio": _pct(b["equity"], b["totalAssets"]),
        "int_cover": None if no_pl else _div(b["pbt"] + b["financeCosts"], b["financeCosts"]),
        "roa": None if no_pl else _pct(b["netResult"], b["totalAssets"]),
        "roe": None if no_pl else _pct(b["netResult"], b["equity"]),
        "roce": None if no_pl else _pct(b["netResult"] + b["financeCosts"], b["equity"] + b["financialDebt"]),
    }


def _parse_gl_date(value):
    """dd/mm/yyyy (or . or -) first, else whatever ``new Date`` makes of the text."""
    raw = js_trim(cell_str(value))
    match = _DMY.fullmatch(raw)
    if match:
        return date_utc(int(match.group(3)), int(match.group(2)) - 1, int(match.group(1)))
    return js_date_parse(raw)


def _fmt(ms):
    year, month0, day = date_parts(ms)
    return "%02d/%02d/%04d" % (day, month0 + 1, year)


def _days(balance, flow):
    return js_round((balance / flow) * 90) if flow is not None and flow > 0 else None


def _ledger_window(mapping, gl_rows, end):
    """Sales and purchases of the 3 months to ``end`` (None when the ledger has no entry in
    them), with the ledger's first and last dates so a blank can say why."""
    out = {"sales": None, "purchases": None, "end": end, "first": None, "last": None, "present": False}
    # a ledger stated as a debit/credit pair carries no amount column: the row value
    # is debit - credit, exactly as the importer derives it
    use_pair = bool(mapping and mapping.get("debit") and mapping.get("credit"))
    if not (mapping and mapping.get("account") and (mapping.get("amount") or use_pair) and mapping.get("journalDate")):
        return out
    # setUTCMonth rolls over: 31 May less three months is 3 March, not 28 February
    start = add_utc(end, months=-3)
    sales = purchases = 0
    in_window = 0
    for data in gl_rows:
        d = _parse_gl_date(data.get(mapping["journalDate"]))
        if d is None:
            continue
        out["present"] = True
        out["first"] = d if out["first"] is None else min(out["first"], d)
        out["last"] = d if out["last"] is None else max(out["last"], d)
        if d < start or d > end:
            continue
        in_window += 1
        account = cell_str(data.get(mapping["account"]))
        if mapping.get("amount"):
            amount = abs(amount_or(data.get(mapping["amount"]), 0))
        else:
            amount = abs(amount_or(data.get(mapping["debit"]), 0) - amount_or(data.get(mapping["credit"]), 0))
        if account.startswith("70"):
            sales += amount
        if _PURCHASES.match(account):
            purchases += amount
    if in_window > 0:
        out["sales"], out["purchases"] = sales, purchases
    return out


def _why_blank(window, prior):
    """(English, French) reason for a blank ratio of that year, or ("", "") when it is worked out."""
    if window["sales"] is not None:
        return "", ""
    if not window["present"]:
        return (PRIOR_NOTE, PRIOR_NOTE_FR) if prior else (GL_NOTE, GL_NOTE_FR)
    words = {"end": _fmt(window["end"]), "first": _fmt(window["first"]), "last": _fmt(window["last"])}
    en, fr = (PRIOR_MISMATCH_NOTE, PRIOR_MISMATCH_NOTE_FR) if prior else (MISMATCH_NOTE, MISMATCH_NOTE_FR)
    return en % words, fr % words


def financial_analysis(tb_rows, period_end, prior_rows=None, overrides=(), gl_mapping=None, gl_rows=(),
                       prior_gl_mapping=None, prior_gl_rows=()):
    """{rows, glAvailable, periodEnd}, None without a TB.

    ``tb_rows``: {account_code, opening, closing}. ``prior_rows``: {account_code, closing}
    of the prior-year TB. ``overrides``: (prefix, index_code) pairs. ``gl_mapping`` and
    ``gl_rows``: the journal-entries dataset's mapping and its rows' data. ``prior_gl_*``: the same for
    the prior-year ledger, which gives the prior year its DSO and DPO.
    """
    if not tb_rows:
        return None
    ordered = sorted(overrides, key=lambda pair: -len(pair[0]))

    def override_of(account):
        for prefix, code in ordered:
            if account.startswith(prefix):
                return code
        return None

    current_b = aggregate([{"account": r["account_code"], "value": r["closing"]} for r in tb_rows], override_of)
    if prior_rows:
        prior_b = aggregate([{"account": r["account_code"], "value": r["closing"]} for r in prior_rows], override_of)
    else:
        prior_b = aggregate([{"account": r["account_code"], "value": r["opening"]} for r in tb_rows], override_of)
    cur = ratio_set(current_b)
    pri = ratio_set(prior_b)

    end = js_date_parse(period_end + "T00:00:00Z")
    current_gl = _ledger_window(gl_mapping, gl_rows, end)
    prior_gl = _ledger_window(prior_gl_mapping, prior_gl_rows, add_utc(end, years=-1))
    sales_3m, purchases_3m = current_gl["sales"], current_gl["purchases"]
    cur["dso"] = _days(current_b["receivables"], sales_3m)
    cur["dpo"] = _days(current_b["payables"], purchases_3m)
    pri["dso"] = _days(prior_b["receivables"], prior_gl["sales"])
    pri["dpo"] = _days(prior_b["payables"], prior_gl["purchases"])

    rows = []
    for definition in DEFS:
        row = dict(definition)
        row["current"] = cur.get(definition["key"])
        row["prior"] = pri.get(definition["key"])
        row["formula"], row["formulaFr"] = FORMULAS[definition["key"]]
        if definition["key"] in ("dso", "dpo"):
            # A blank here is always explained (F064), in plain words.
            notes = (_why_blank(current_gl, False), _why_blank(prior_gl, True))
            row["note"] = " ".join(n[0] for n in notes if n[0])
            row["noteFr"] = " ".join(n[1] for n in notes if n[1])
            if sales_3m is not None and row["current"] is None:
                row["blank"], row["blankFr"] = (NO_SALES_NOTE, NO_SALES_NOTE_FR) if definition["key"] == "dso" else (NO_PURCHASES_NOTE, NO_PURCHASES_NOTE_FR)
        rows.append(row)
    return {"rows": rows, "glAvailable": sales_3m is not None, "periodEnd": period_end, "totalAssets": js_round(current_b["totalAssets"])}
