"""lib/fs-tieout.ts: the Compte de résultat's SIG cascade and the Bilan's key aggregates recomputed
from the closings, the equilibrium checks, and the comparison with the client's statements. TB
closings carry natural signs (charges debit-positive, produits credit-negative), so income lines
are negated to read positively and charge lines subtract. TFT recomputation is out of scope, as
in the source. No ORM here."""
from odoo.addons.ea_audit_tools.services._js import js_round


class Closings:
    def __init__(self, rows):
        self.rows = rows

    def get(self, prefixes, exclude=()):
        total = 0
        for account, closing in self.rows:
            if any(account.startswith(prefix) for prefix in exclude):
                continue
            if any(account.startswith(prefix) for prefix in prefixes):
                total += closing
        return total


CR_FR = {
    "TA": "Ventes de marchandises",
    "RA": "Achats de marchandises",
    "RB": "Variation stocks marchandises",
    "XA": "MARGE COMMERCIALE",
    "TB": "Ventes de produits fabriqués",
    "TC": "Travaux, services vendus",
    "TD": "Produits accessoires",
    "XB": "CHIFFRE D'AFFAIRES",
    "TE": "Production stockée",
    "TF": "Production immobilisée",
    "TG": "Subventions d'exploitation",
    "TH": "Autres produits",
    "TI": "Transferts de charges d'exploitation",
    "RC": "Achats de MP",
    "RD": "Variation stocks MP",
    "RE": "Autres achats",
    "RF": "Variation stocks autres appro.",
    "RG": "Transports",
    "RH": "Services extérieurs",
    "RI": "Impôts et taxes",
    "RJ": "Autres charges",
    "XC": "VALEUR AJOUTÉE",
    "RK": "Charges de personnel",
    "XD": "EXCÉDENT BRUT D'EXPLOITATION",
    "TJ": "Reprises d'exploitation",
    "RL": "Dotations d'exploitation",
    "XE": "RÉSULTAT D'EXPLOITATION",
    "TK": "Revenus financiers",
    "TL": "Reprises financières",
    "TM": "Transferts de charges financières",
    "RM": "Frais financiers",
    "RN": "Dotations financières",
    "XF": "RÉSULTAT FINANCIER",
    "XG": "RÉSULTAT DES ACTIVITÉS ORDINAIRES",
    "TN": "Produits des cessions",
    "TO": "Autres produits HAO",
    "RO": "Valeurs comptables des cessions",
    "RP": "Autres charges HAO",
    "XH": "RÉSULTAT HAO",
    "RQ": "Participation des travailleurs",
    "RS": "Impôts sur le résultat",
    "XI": "RÉSULTAT NET",
}
CR_EN = {
    "TA": "Sales of goods",
    "RA": "Purchases of goods",
    "RB": "Change in goods inventory",
    "XA": "GROSS MARGIN",
    "TB": "Sales of manufactured products",
    "TC": "Work and services sold",
    "TD": "Ancillary income",
    "XB": "REVENUE",
    "TE": "Inventoried production",
    "TF": "Capitalised production",
    "TG": "Operating subsidies",
    "TH": "Other income",
    "TI": "Transfers of operating charges",
    "RC": "Purchases of raw materials",
    "RD": "Change in raw materials inventory",
    "RE": "Other purchases",
    "RF": "Change in other supplies",
    "RG": "Transport",
    "RH": "External services",
    "RI": "Taxes and duties",
    "RJ": "Other charges",
    "XC": "VALUE ADDED",
    "RK": "Staff costs",
    "XD": "GROSS OPERATING SURPLUS",
    "TJ": "Operating reversals",
    "RL": "Operating allowances",
    "XE": "OPERATING RESULT",
    "TK": "Financial income",
    "TL": "Financial reversals",
    "TM": "Transfers of financial charges",
    "RM": "Financial expenses",
    "RN": "Financial allowances",
    "XF": "FINANCIAL RESULT",
    "XG": "RESULT FROM ORDINARY ACTIVITIES",
    "TN": "Proceeds of disposals",
    "TO": "Other non-ordinary income",
    "RO": "Carrying amounts of disposals",
    "RP": "Other non-ordinary charges",
    "XH": "NON-ORDINARY RESULT",
    "RQ": "Workers' profit-sharing",
    "RS": "Income tax",
    "XI": "NET RESULT",
}


def compute_cr(closings):
    """Appendix B.3, the full cascade: (lines, result). A line is (ref, label, label_en, amount)."""
    income = lambda *prefixes: -closings.get(prefixes)  # noqa: E731
    charge = lambda *prefixes: closings.get(prefixes)  # noqa: E731

    ta, ra, rb = income("701"), charge("601"), charge("6031")
    xa = ta - ra - rb
    tb, tc, td = income("702", "703", "704"), income("705", "706"), income("707")
    xb = ta + tb + tc + td
    te, tf, tg, th, ti = income("73"), income("72"), income("71"), income("75"), income("781")
    rc, rd, re_, rf = charge("602"), charge("6032"), charge("604", "605", "608"), charge("6033")
    rg, rh, ri, rj = charge("61"), charge("62", "63"), charge("64"), charge("65")
    xc = xa + tb + tc + td + te + tf + tg + th + ti - rc - rd - re_ - rf - rg - rh - ri - rj
    rk = charge("66")
    xd = xc - rk
    tj, rl = income("791", "798", "799"), charge("681", "691")
    xe = xd + tj - rl
    tk, tl, tm, rm, rn = income("77"), income("797"), income("787"), charge("67"), charge("697")
    xf = tk + tl + tm - rm - rn
    xg = xe + xf
    tn, to, ro, rp = income("82"), income("84", "86", "88"), charge("81"), charge("83", "85")
    xh = tn + to - ro - rp
    rq, rs = charge("87"), charge("89")
    xi = xg + xh - rq - rs
    lines = [
        ("TA", ta), ("RA", -ra),
        ("RB", -rb), ("XA", xa),
        ("TB", tb), ("TC", tc),
        ("TD", td), ("XB", xb),
        ("TE", te), ("TF", tf),
        ("TG", tg), ("TH", th),
        ("TI", ti), ("RC", -rc),
        ("RD", -rd), ("RE", -re_),
        ("RF", -rf), ("RG", -rg),
        ("RH", -rh), ("RI", -ri), ("RJ", -rj),
        ("XC", xc), ("RK", -rk),
        ("XD", xd), ("TJ", tj),
        ("RL", -rl), ("XE", xe),
        ("TK", tk), ("TL", tl),
        ("TM", tm), ("RM", -rm),
        ("RN", -rn), ("XF", xf),
        ("XG", xg), ("TN", tn),
        ("TO", to), ("RO", -ro),
        ("RP", -rp), ("XH", xh),
        ("RQ", -rq), ("RS", -rs),
        ("XI", xi),
    ]
    return [{"ref": ref, "label": CR_FR[ref], "labelEn": CR_EN[ref], "amount": amount} for ref, amount in lines], xi


def compute_bilan(closings, cr_result):
    """The Bilan's key aggregates and the two equilibrium checks."""
    get = closings.get
    fixed = get(("21", "22", "23", "24", "25", "28", "29"))
    financial = get(("26", "27", "296", "297"))
    stocks = get(("31", "32", "33", "34", "35", "36", "37", "38", "39"))
    third = get(("40", "41", "42", "43", "44", "45", "46", "47", "48", "49", "185"))
    cash = get(("50", "51", "52", "53", "54", "55", "56", "57", "58", "59"))
    gap_assets, gap_liabilities = get(("478",)), get(("479",))
    equity = -get(("10", "11", "12", "13", "14", "15"))
    debt = -get(("16", "17", "18"))
    provisions = -get(("19",))
    class15 = get(("1", "2", "3", "4", "5"))
    class68 = get(("6", "7", "8"))
    lines = [
        ("AZ~", "Actif immobilisé net (2x, y compris 28/29)", "Net fixed assets (2x incl. 28/29)", fixed + financial),
        ("BB", "Stocks et encours nets (3x)", "Net inventories and work in progress (3x)", stocks),
        ("B~", "Tiers nets (4x — ventilés par signe à la présentation des états)", "Net third-party balances (4x — sign-split at FS presentation)", third - gap_assets),
        ("BT~", "Trésorerie nette (5x)", "Net cash (5x)", cash),
        ("BU", "Écart de conversion — Actif (478)", "Translation difference — assets (478)", gap_assets),
        ("CP", "Capitaux propres (10–15, hors résultat)", "Equity (10–15, excluding the result)", equity),
        ("CJ", "Résultat net de l'exercice (du CR)", "Net result for the year (from the income statement)", cr_result),
        ("DF~", "Dettes financières (16–18)", "Financial debt (16–18)", debt),
        ("DC", "Provisions pour risques et charges (19)", "Provisions for risks and charges (19)", provisions),
        ("DV", "Écart de conversion — Passif (479)", "Translation difference — liabilities (479)", -gap_liabilities),
    ]
    checks = [
        # a balanced TB: classes 1-8 sum to nil
        {"key": "tb_balanced", "ok": abs(class15 + class68) < 1, "amount": class15 + class68},
        # net assets of classes 1-5 equal the result, the P&L not being closed to 13x yet
        {"key": "bilan_equilibrium", "ok": abs(class15 - cr_result) < 1, "amount": class15 - cr_result},
    ]
    return [{"ref": ref, "label": label, "labelEn": label_en, "amount": amount} for ref, label, label_en, amount in lines], checks


def parse_client_fs(content):
    """ref;amount, one a line. What does not read as an amount is skipped, as in the source."""
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    out = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split(";")]
        if len(cells) < 2 or not cells[0] or not cells[1]:
            continue
        try:
            out[cells[0].upper()] = float(cells[1])
        except ValueError:
            continue
    return out


def client_diffs(client_lines, recomputed_lines, threshold):
    """What the client's statements say against the recomputation, above the trivial line."""
    recomputed = {line["ref"]: line["amount"] for line in recomputed_lines}
    out = []
    for ref, client_amount in client_lines.items():
        ours = recomputed.get(ref)
        if ours is None:
            continue
        difference = js_round(ours - client_amount)
        if abs(difference) > threshold:
            out.append({"ref": ref, "recomputed": js_round(ours), "client": client_amount, "difference": difference})
    return out


def run_tieout(rows, threshold=0, client_fs=None):
    """rows: [(account, closing)]."""
    closings = Closings(rows)
    cr, result = compute_cr(closings)
    bilan, checks = compute_bilan(closings, result)
    diffs = client_diffs(parse_client_fs(client_fs), cr + bilan, threshold) if client_fs else []
    return {
        "cr": cr, "bilan": bilan, "checks": checks, "crResult": result, "clientDiffs": diffs,
        "pass": bool(rows) and all(check["ok"] for check in checks) and not diffs,
    }
