"""lib/financial-analysis.ts: the ratio battery, computed twice.

Current Y from the working TB's closing balances; Prior Y from the prior-year TB's
closing balances when one is uploaded, else from the working TB's openings. DSO and
DPO draw the last three months of sales and purchases from the general ledger
(current year only). Balances are debit-positive, so credit-natured aggregates
(equity, liabilities, revenue) are negated.
"""
import re

from ._js import add_utc, cell_str, date_utc, js_date_parse, js_round, js_trim
from .amount import amount_or

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
        "label": "Return on assets",
        "labelFr": "Rentabilité de l'actif",
        "group": "Investment",
        "unit": "%",
    },
    {
        "key": "roe",
        "label": "Return on equity",
        "labelFr": "Rentabilité des capitaux propres",
        "group": "Investment",
        "unit": "%",
    },
    {
        "key": "roce",
        "label": "Return on capital employed",
        "labelFr": "Rentabilité des capitaux engagés",
        "group": "Investment",
        "unit": "%",
    },
]

#: The commentary keys the financial-analysis grid saves under index "FA".
RATIO_KEYS = [d["key"] for d in DEFS]

GL_NOTE = "Requires the General Ledger (last 3 months) — upload it in the GL Analyzer"

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
    class4_debit = total(lambda r: r["account"].startswith("4") and r["value"] > 0)
    class4_credit = -total(lambda r: r["account"].startswith("4") and r["value"] < 0)
    revenue = -total(starts("7"))
    expenses = total(starts("6"))
    cogs = total(bucket(starts("60"), lambda c: c.startswith("VA")))
    finance_costs = total(starts("67"))
    depreciation = total(starts("68", "69"))
    pbt = revenue - expenses
    # A pre-closing TB carries the year's result in classes 6/7, not in a 13x account:
    # equity then includes that result, or every equity ratio is misstated.
    has_result_account = any(r["account"].startswith("13") and r["value"] != 0 for r in rows)
    payables_bucket = bucket(starts("40"), lambda c: c == "N")
    return {
        "inventory": inventory,
        "receivables": total(bucket(starts("41"), lambda c: c == "E")),
        "cash": cash,
        "currentAssets": inventory + class4_debit + max(cash, 0),
        "currentLiabilities": class4_credit + max(-cash, 0),
        "payables": -total(lambda r: r["value"] < 0 and payables_bucket(r)),
        "equity": -total(lambda r: _EQUITY.match(r["account"]) is not None) + (0 if has_result_account else pbt),
        "financialDebt": -total(lambda r: _DEBT.match(r["account"]) is not None),
        "totalAssets": total(starts("2")) + inventory + class4_debit + max(cash, 0),
        "revenue": revenue,
        "expenses": expenses,
        "cogs": cogs,
        "financeCosts": finance_costs,
        "depreciation": depreciation,
        "pbt": pbt,
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
        "roa": None if no_pl else _pct(b["pbt"], b["totalAssets"]),
        "roe": None if no_pl else _pct(b["pbt"], b["equity"]),
        "roce": None if no_pl else _pct(b["pbt"] + b["financeCosts"], b["equity"] + b["financialDebt"]),
    }


def _parse_gl_date(value):
    """dd/mm/yyyy (or . or -) first, else whatever ``new Date`` makes of the text."""
    raw = js_trim(cell_str(value))
    match = _DMY.fullmatch(raw)
    if match:
        return date_utc(int(match.group(3)), int(match.group(2)) - 1, int(match.group(1)))
    return js_date_parse(raw)


def financial_analysis(tb_rows, period_end, prior_rows=None, overrides=(), gl_mapping=None, gl_rows=()):
    """{rows, glAvailable, periodEnd}, None without a TB.

    ``tb_rows``: {account_code, opening, closing}. ``prior_rows``: {account_code, closing}
    of the prior-year TB. ``overrides``: (prefix, index_code) pairs. ``gl_mapping`` and
    ``gl_rows``: the journal-entries dataset's mapping and its rows' data.
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

    sales_3m = None
    purchases_3m = None
    mapping = gl_mapping
    # a ledger stated as a debit/credit pair carries no amount column: the row value
    # is debit - credit, exactly as the importer derives it
    use_pair = bool(mapping and mapping.get("debit") and mapping.get("credit"))
    if mapping and mapping.get("account") and (mapping.get("amount") or use_pair) and mapping.get("journalDate"):
        end = js_date_parse(period_end + "T00:00:00Z")
        # setUTCMonth rolls over: 31 May less three months is 3 March, not 28 February
        start = add_utc(end, months=-3)
        sales = 0
        purchases = 0
        in_window = 0
        for data in gl_rows:
            d = _parse_gl_date(data.get(mapping["journalDate"]))
            if d is None or d < start or d > end:
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
            sales_3m = sales
            purchases_3m = purchases
    cur["dso"] = js_round((current_b["receivables"] / sales_3m) * 90) if sales_3m is not None and sales_3m > 0 else None
    cur["dpo"] = js_round((current_b["payables"] / purchases_3m) * 90) if purchases_3m is not None and purchases_3m > 0 else None
    pri["dso"] = None
    pri["dpo"] = None

    rows = []
    for definition in DEFS:
        row = dict(definition)
        row["current"] = cur.get(definition["key"])
        row["prior"] = pri.get(definition["key"])
        if definition["key"] in ("dso", "dpo") and sales_3m is None:
            row["note"] = GL_NOTE
        rows.append(row)
    return {"rows": rows, "glAvailable": sales_3m is not None, "periodEnd": period_end}
