"""lib/fs-captions.ts: the one SYSCOHADA balance sheet (F013).

Materiality, the financial analysis and the SAD all read their totals from here. Net
of 28, 29, 39, 49, 59; class 4 by the sign of each account's balance; 56 on the passif;
490 and 499 on the passif whatever their sign, because lead_classes files them under
liability indexes (N and P1) (F059).
"""


def bilan_totals(rows):
    """``rows``: {account, value}, closing balance with debit positive."""
    fixed_assets = 0
    inventory = 0
    debit4 = 0
    credit4 = 0
    prov49 = 0
    cash_debit = 0
    cash_credit = 0
    prov59 = 0
    class1 = 0
    result_accounts = 0
    for row in rows:
        account = row["account"]
        value = row["value"]
        c1 = account[:1]
        c2 = account[:2]
        if c1 == "1":
            class1 -= value
        elif c1 == "2":
            fixed_assets += value
        elif c1 == "3":
            inventory += value
        elif c1 == "4":
            if account.startswith("490") or account.startswith("499"):
                credit4 -= value
            elif c2 == "49":
                prov49 += value
            elif value > 0:
                debit4 += value
            else:
                credit4 -= value
        elif c1 == "5":
            if c2 == "59":
                prov59 += value
            elif c2 == "56":
                cash_credit -= value
            elif value > 0:
                cash_debit += value
            else:
                cash_credit -= value
        elif c1 in ("6", "7", "8"):
            result_accounts -= value
    receivables = debit4 + prov49
    cash_assets = cash_debit + prov59
    current_assets = inventory + receivables + cash_assets
    total_assets = fixed_assets + current_assets
    current_liabilities = credit4 + cash_credit
    return {
        "fixedAssets": fixed_assets,
        "inventory": inventory,
        "receivables": receivables,
        "cashAssets": cash_assets,
        "currentAssets": current_assets,
        "totalAssets": total_assets,
        "class4Credit": credit4,
        "cashLiabilities": cash_credit,
        "currentLiabilities": current_liabilities,
        "class1": class1,
        "netResult": result_accounts,
        "totalLiabilitiesAndEquity": class1 + current_liabilities + result_accounts,
    }


def income_from_tb(rows):
    """Result before tax is classes 7 and 8 (without 89) less class 6; net takes 89 off."""
    before_tax = 0
    income_tax = 0
    for row in rows:
        account = row["account"]
        if account.startswith("89"):
            income_tax += row["value"]
        elif account[:1] in ("6", "7", "8"):
            before_tax -= row["value"]
    return {"beforeTax": before_tax, "incomeTax": income_tax, "netResult": before_tax - income_tax}


def asset_basis_label(locale, tb_version):
    """The label beside every total-assets figure (F013)."""
    if tb_version is None:
        suffix = ""
    else:
        suffix = ", %s v%s" % ("balance" if locale == "fr" else "TB", tb_version)
    return ("Total actif net (SYSCOHADA)%s" if locale == "fr" else "Total net assets (SYSCOHADA)%s") % suffix
