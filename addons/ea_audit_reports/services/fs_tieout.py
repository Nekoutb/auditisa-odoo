"""lib/fs-tieout.ts: the Compte de résultat's SIG cascade and the Bilan's key aggregates recomputed
from the closings, the equilibrium checks, and the comparison with the client's statements. TB
closings carry natural signs (charges debit-positive, produits credit-negative), so income lines
are negated to read positively and charge lines subtract. TFT recomputation is out of scope, as
in the source. No ORM here."""
from odoo.tools.translate import LazyTranslate

from odoo.addons.ea_audit_tools.services._js import js_round

_lt = LazyTranslate("ea_audit_reports")

# The captions, read through env._ by whoever shows them. French in i18n/fr.po.
CR_LABELS = {
    "TA": _lt("Sales of goods"),
    "RA": _lt("Purchases of goods"),
    "RB": _lt("Change in goods inventory"),
    "XA": _lt("GROSS TRADING MARGIN"),
    "TB": _lt("Sales of manufactured goods"),
    "TC": _lt("Work and services sold"),
    "TD": _lt("Ancillary income"),
    "XB": _lt("REVENUE"),
    "TE": _lt("Production held in inventory"),
    "TF": _lt("Capitalised production"),
    "TG": _lt("Operating subsidies"),
    "TH": _lt("Other income"),
    "TI": _lt("Operating expense transfers"),
    "RC": _lt("Purchases of raw materials"),
    "RD": _lt("Change in raw materials inventory"),
    "RE": _lt("Other purchases"),
    "RF": _lt("Change in other supplies inventory"),
    "RG": _lt("Transport"),
    "RH": _lt("External services"),
    "RI": _lt("Taxes and duties"),
    "RJ": _lt("Other expenses"),
    "XC": _lt("VALUE ADDED"),
    "RK": _lt("Personnel expenses"),
    "XD": _lt("GROSS OPERATING SURPLUS"),
    "TJ": _lt("Operating reversals"),
    "RL": _lt("Operating allowances"),
    "XE": _lt("OPERATING RESULT"),
    "TK": _lt("Financial income"),
    "TL": _lt("Financial reversals"),
    "TM": _lt("Financial expense transfers"),
    "RM": _lt("Financial expenses"),
    "RN": _lt("Financial allowances"),
    "XF": _lt("FINANCIAL RESULT"),
    "XG": _lt("RESULT OF ORDINARY ACTIVITIES"),
    "TN": _lt("Disposal proceeds"),
    "TO": _lt("Other non-ordinary income"),
    "RO": _lt("Carrying value of disposals"),
    "RP": _lt("Other non-ordinary expenses"),
    "XH": _lt("NON-ORDINARY RESULT"),
    "RQ": _lt("Employee profit sharing"),
    "RS": _lt("Income tax"),
    "XI": _lt("NET RESULT"),
}
BILAN_LABELS = {
    "AZ~": _lt("Net fixed assets (2x incl. 28/29)"),
    "BB": _lt("Net inventories and work in progress (3x)"),
    "B~": _lt("Net third-party balances (4x — sign-split at FS presentation)"),
    "BT~": _lt("Net cash (5x)"),
    "BU": _lt("Translation difference — assets (478)"),
    "CP": _lt("Equity (10–15, excluding the result)"),
    "CJ": _lt("Net result for the year (from the income statement)"),
    "DF~": _lt("Financial debt (16–18)"),
    "DC": _lt("Provisions for risks and charges (19)"),
    "DV": _lt("Translation difference — liabilities (479)"),
}


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


def compute_cr(closings):
    """Appendix B.3, the full cascade: (lines, result). A line is {ref, label, amount}."""
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
        ("TA", ta),
        ("RA", -ra),
        ("RB", -rb),
        ("XA", xa),
        ("TB", tb),
        ("TC", tc),
        ("TD", td),
        ("XB", xb),
        ("TE", te),
        ("TF", tf),
        ("TG", tg),
        ("TH", th),
        ("TI", ti),
        ("RC", -rc),
        ("RD", -rd),
        ("RE", -re_),
        ("RF", -rf),
        ("RG", -rg),
        ("RH", -rh),
        ("RI", -ri),
        ("RJ", -rj),
        ("XC", xc),
        ("RK", -rk),
        ("XD", xd),
        ("TJ", tj),
        ("RL", -rl),
        ("XE", xe),
        ("TK", tk),
        ("TL", tl),
        ("TM", tm),
        ("RM", -rm),
        ("RN", -rn),
        ("XF", xf),
        ("XG", xg),
        ("TN", tn),
        ("TO", to),
        ("RO", -ro),
        ("RP", -rp),
        ("XH", xh),
        ("RQ", -rq),
        ("RS", -rs),
        ("XI", xi),
    ]
    return [{"ref": ref, "label": CR_LABELS[ref], "amount": amount} for ref, amount in lines], xi


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
        ("AZ~", fixed + financial), ("BB", stocks), ("B~", third - gap_assets), ("BT~", cash), ("BU", gap_assets),
        ("CP", equity), ("CJ", cr_result), ("DF~", debt), ("DC", provisions), ("DV", -gap_liabilities),
    ]
    checks = [
        # a balanced TB: classes 1-8 sum to nil
        {"key": "tb_balanced", "ok": abs(class15 + class68) < 1, "amount": class15 + class68},
        # net assets of classes 1-5 equal the result, the P&L not being closed to 13x yet
        {"key": "bilan_equilibrium", "ok": abs(class15 - cr_result) < 1, "amount": class15 - cr_result},
    ]
    return [{"ref": ref, "label": BILAN_LABELS[ref], "amount": amount} for ref, amount in lines], checks


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
