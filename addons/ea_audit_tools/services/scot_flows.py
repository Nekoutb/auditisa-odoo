"""EAGLA, SCOT identification: the significant classes of transactions read from the general ledger.

Four classes, on SYSCOHADA account prefixes: Revenue, Purchases, Fixed assets and Treasury. The
database sums the ledger by journal entry and account group (one row per entry and group); this
module pairs the groups each entry debits with the groups it credits.

A flow runs from the group credited to the group debited, as value moves through the class: sales
(credited) to customers (debited) to bank (debited when the customer pays). Within an entry each
debited group receives from each credited group in proportion to the amounts, so a sale with VAT
gives two flows, sales to customers and VAT on sales to customers. A flow between two groups of
the class that is not on the usual path (sales straight to cash with no customer account,
purchases paid straight from cash with no supplier account) is unusual.
"""
from ._js import _days_from_civil, js_sum

BANK = ("52", "57")

#: key: (prefixes, prefixes left out, English label, French label)
GROUPS = {
    "sales": (("70",), (), "Sales (70)", "Ventes (70)"),
    "cash_sales": (("70",), (), "Cash sales (70)", "Ventes au comptant (70)"),
    "vat_sales": (("443",), (), "VAT on sales (443)", "TVA facturée (443)"),
    "customers": (("411",), (), "Customers (411)", "Clients (411)"),
    "bank": (BANK, (), "Bank and cash (52, 57)", "Banque et caisse (52, 57)"),
    "purchases": (("60", "61", "62"), (), "Purchases (60, 61, 62)", "Achats (60, 61, 62)"),
    "vat_recoverable": (("445",), (), "VAT recoverable (445)", "TVA récupérable (445)"),
    "suppliers": (("401",), (), "Suppliers (401)", "Fournisseurs (401)"),
    "fixed_assets": (("2",), ("28", "29"), "Fixed assets (2, without 28 and 29)", "Immobilisations (2, hors 28 et 29)"),
    "fa_suppliers": (("404", "481"), (), "Fixed asset suppliers (404, 481)", "Fournisseurs d'immobilisations (404, 481)"),
    "loans": (("16",), (), "Loans (16)", "Emprunts (16)"),
    "capital": (("10",), (), "Capital (10)", "Capital (10)"),
    "salaries": (("66", "42"), (), "Salaries (66, 42)", "Salaires (66, 42)"),
    "taxes": (("44",), (), "Taxes (44)", "Impôts et taxes (44)"),
    "other": ((), (), "Other accounts", "Autres comptes"),
}
#: The words a treasury node takes on one side only.
TREASURY_SIDE_LABELS = {
    ("in", "loans"): ("Loans received (16)", "Emprunts reçus (16)"),
    ("out", "loans"): ("Loan repayments (16)", "Remboursements d'emprunts (16)"),
}

#: Each class: its groups (in the order they are tried), the groups that bring an entry into it,
#: the diagram's columns, the usual flows (credited group, debited group), the middle account of
#: "Timing, month by month" and the side on which an amount enters it.
CLASSES = {
    "revenue": {
        "groups": ["sales", "vat_sales", "customers", "bank"],
        "focus": ["sales", "vat_sales", "customers"],
        "columns": [["sales", "vat_sales"], ["customers", "other"], ["bank"]],
        "usual": [("sales", "customers"), ("vat_sales", "customers"), ("customers", "bank")],
        "middle": "customers", "entering": "debit",
    },
    "purchases": {
        "groups": ["purchases", "vat_recoverable", "suppliers", "bank"],
        "focus": ["purchases", "vat_recoverable", "suppliers"],
        "columns": [["bank"], ["suppliers", "other"], ["purchases", "vat_recoverable"]],
        "usual": [("suppliers", "purchases"), ("suppliers", "vat_recoverable"), ("bank", "suppliers")],
        "middle": "suppliers", "entering": "credit",
    },
    "fixed_assets": {
        "groups": ["fixed_assets", "fa_suppliers", "bank"],
        "focus": ["fixed_assets", "fa_suppliers"],
        "columns": [["bank"], ["fa_suppliers", "other"], ["fixed_assets"]],
        "usual": [("fa_suppliers", "fixed_assets"), ("bank", "fa_suppliers")],
        "middle": "fa_suppliers", "entering": "credit",
    },
    "treasury": {
        # 404 before 401 and 44 does not matter (no prefix of one starts another), 70 is cash sales
        "groups": ["bank", "customers", "cash_sales", "loans", "capital", "suppliers", "salaries", "taxes", "fa_suppliers"],
        "focus": ["bank"],
        "sides": ["customers", "cash_sales", "loans", "capital", "suppliers", "salaries", "taxes", "fa_suppliers", "other"],
        # money in: a group credited against the bank; the only unusual one is a sale straight to cash
        "unusual": [("cash_sales", "bank")],
        "middle": "bank", "entering": "debit",
    },
}
CLASS_ORDER = ["revenue", "purchases", "fixed_assets", "treasury"]
CLASS_LABELS = {
    "revenue": ("Revenue", "Chiffre d'affaires"),
    "purchases": ("Purchases", "Achats"),
    "fixed_assets": ("Fixed assets", "Immobilisations"),
    "treasury": ("Treasury", "Trésorerie"),
}
#: The journal entries a pattern keeps for its list.
ENTRY_CAP = 500
#: Below this an amount is a rounding remainder, not a flow.
NIL = 0.005
WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
}


def group_label(key, locale, side=None):
    if side and (side, key) in TREASURY_SIDE_LABELS:
        en, fr = TREASURY_SIDE_LABELS[(side, key)]
    else:
        en, fr = GROUPS[key][2], GROUPS[key][3]
    return fr if locale == "fr" else en


def node_label(node, locale):
    """A node key of the diagram: a group, or for treasury "in:group" and "out:group"."""
    if ":" in node:
        side, key = node.split(":", 1)
        return group_label(key, locale, side)
    return group_label(node, locale)


def classify(account, keys):
    """The group of an account among ``keys``, else "other": the Python twin of ``sql_case``."""
    code = (account or "").strip()
    for key in keys:
        prefixes, left_out = GROUPS[key][0], GROUPS[key][1]
        if code.startswith(prefixes) and not (left_out and code.startswith(left_out)):
            return key
    return "other"


def _like(prefixes):
    return [prefix + "%" for prefix in prefixes]


def sql_case(keys, column="account"):
    """(SQL, params): a CASE naming the group of ``column``. Only constants of this module reach
    the text; the prefixes travel as parameters."""
    parts, params = [], {}
    for position, key in enumerate(keys):
        prefixes, left_out = GROUPS[key][0], GROUPS[key][1]
        params["g%d" % position] = _like(prefixes)
        params["x%d" % position] = _like(left_out)
        parts.append(
            "WHEN {c} LIKE ANY(%(g{n})s::text[]) AND NOT {c} LIKE ANY(%(x{n})s::text[]) THEN '{k}'".format(c=column, n=position, k=key)
        )
    return "CASE %s ELSE 'other' END" % " ".join(parts), params


def sql_focus(class_key, column="account"):
    """(SQL, params): the condition of a line that brings its entry into the class."""
    keys = CLASSES[class_key]["focus"]
    parts, params = [], {}
    for position, key in enumerate(keys):
        prefixes, left_out = GROUPS[key][0], GROUPS[key][1]
        params["f%d" % position] = _like(prefixes)
        params["fx%d" % position] = _like(left_out)
        parts.append("({c} LIKE ANY(%(f{n})s::text[]) AND NOT {c} LIKE ANY(%(fx{n})s::text[]))".format(c=column, n=position))
    return "(%s)" % " OR ".join(parts), params


def sql_middle(class_key, column="account"):
    """(SQL, params): the condition of a line of the class's middle account."""
    key = CLASSES[class_key]["middle"]
    prefixes, left_out = GROUPS[key][0], GROUPS[key][1]
    return (
        "({c} LIKE ANY(%(m0)s::text[]) AND NOT {c} LIKE ANY(%(mx0)s::text[]))".format(c=column),
        {"m0": _like(prefixes), "mx0": _like(left_out)},
    )


def _in_year(line, start, end):
    return bool(line["date"]) and (start is None or start <= line["date"] <= end)


def group_lines(lines, class_key, start=None, end=None):
    """The database's work, in Python, for the tests: ledger lines (je, date, journal, account,
    debit, credit) of the entries with a line of the class dated in the year, summed by entry and
    group."""
    keys = CLASSES[class_key]["groups"]
    focus = CLASSES[class_key]["focus"]
    touched = {line["je"] for line in lines if _in_year(line, start, end) and classify(line["account"], focus) != "other"}
    sums = {}
    for line in lines:
        if line["je"] not in touched:
            continue
        group = classify(line["account"], keys)
        row = sums.setdefault((line["je"], group), {"je": line["je"], "jd": None, "jc": "", "grp": group, "d": 0.0, "c": 0.0})
        if line["date"] and (row["jd"] is None or line["date"] < row["jd"]):
            row["jd"] = line["date"]
        journal = line.get("journal") or ""
        if journal and (not row["jc"] or journal < row["jc"]):
            row["jc"] = journal
        row["d"] += line.get("debit") or 0.0
        row["c"] += line.get("credit") or 0.0
    return list(sums.values())


def middle_pairs(lines, class_key, start=None, end=None):
    """The database's work, in Python, for the tests: the first debit and first credit dates of
    the middle account's lines in the year, by party and reference (a line with no reference is
    left out)."""
    key = CLASSES[class_key]["middle"]
    pairs = {}
    for line in lines:
        reference = (line.get("reference") or "").strip()
        if not reference or not _in_year(line, start, end) or classify(line["account"], [key]) != key:
            continue
        row = pairs.setdefault(((line.get("party") or "").strip(), reference), {"d_first": None, "c_first": None})
        side = "d_first" if (line.get("debit") or 0) > (line.get("credit") or 0) else "c_first" if (line.get("credit") or 0) > (line.get("debit") or 0) else None
        if side and (row[side] is None or line["date"] < row[side]):
            row[side] = line["date"]
    return list(pairs.values())


def entries_of(rows):
    """{je: {"date", "journal", "nets": {group: debit minus credit}}} of the database's rows."""
    entries = {}
    for row in rows:
        entry = entries.setdefault(row["je"], {"date": row["jd"], "journal": "", "nets": {}})
        if row["jd"] and (not entry["date"] or row["jd"] < entry["date"]):
            entry["date"] = row["jd"]
        journal = row["jc"] or ""
        if journal and (not entry["journal"] or journal < entry["journal"]):
            entry["journal"] = journal
        entry["nets"][row["grp"]] = entry["nets"].get(row["grp"], 0.0) + (row["d"] or 0.0) - (row["c"] or 0.0)
    return entries


def pair(nets):
    """The flows of one entry: [(credited group, debited group, amount)], each debited group
    receiving from each credited group in proportion to the amounts."""
    debited = [(group, value) for group, value in sorted(nets.items()) if value > NIL]
    credited = [(group, -value) for group, value in sorted(nets.items()) if value < -NIL]
    total = max(js_sum((value for _group, value in debited), 0.0), js_sum((value for _group, value in credited), 0.0))
    if not total:
        return []
    return [
        (source, target, d_value * c_value / total)
        for source, c_value in credited
        for target, d_value in debited
    ]


def _days(iso):
    return _days_from_civil(int(iso[0:4]), int(iso[5:7]), int(iso[8:10]))


def weekday_of(iso):
    """0 for Monday to 6 for Sunday."""
    return (_days(iso) + 3) % 7


def average_days(rows, entering):
    """The average days from the amount entering the middle account to its settlement, over the
    party and reference pairs that have both; None when no pair can be made. ``rows``: dicts with
    the first debit date ``d_first`` and the first credit date ``c_first`` of each pair."""
    days = []
    for row in rows:
        start, end = (row.get("d_first"), row.get("c_first")) if entering == "debit" else (row.get("c_first"), row.get("d_first"))
        if start and end and end >= start:
            days.append(_days(end) - _days(start))
    if not days:
        return None
    return {"days": js_sum(days, 0) / len(days), "pairs": len(days)}


def _node(class_key, source, target):
    """The diagram's nodes of a flow; for treasury the side of the bank the other group sits on."""
    if class_key != "treasury":
        return source, target
    if target == "bank":
        return "in:%s" % source, "bank"
    return "bank", "out:%s" % target


def analyse(rows, class_key, keys, middle_pairs=None):
    """Flows, nodes, monthly timing, patterns and, for treasury, the table of groups.

    ``rows``: the database's sums by entry and group (je, jd, jc, grp, d, c); ``keys``: the twelve
    (year, month) of the year audited; ``middle_pairs``: the rows for the average days."""
    spec = CLASSES[class_key]
    treasury = class_key == "treasury"
    unusual_pairs = set(spec.get("unusual", []))
    usual = set(spec.get("usual", []))
    groups = set(spec["groups"])
    position = {key: index for index, key in enumerate(keys)}
    entries = entries_of(rows)

    flows, patterns = {}, {}
    entering, leaving = [0.0] * 12, [0.0] * 12
    sides = {}
    for je in sorted(entries):
        entry = entries[je]
        date = entry["date"] or ""
        month = position.get((int(date[0:4]), int(date[5:7]))) if len(date) >= 10 else None
        middle_net = entry["nets"].get(spec["middle"], 0.0)
        if month is not None and abs(middle_net) > NIL:
            debit_side = middle_net > 0
            target = entering if debit_side == (spec["entering"] == "debit") else leaving
            target[month] += abs(middle_net)
        seen, counted = set(), set()
        for source, target_group, amount in pair(entry["nets"]):
            if treasury and "bank" not in (source, target_group):
                continue
            if source == target_group:
                continue
            if treasury:
                strange = (source, target_group) in unusual_pairs
            else:
                strange = source in groups and target_group in groups and (source, target_group) not in usual
            nodes = _node(class_key, source, target_group)
            flow = flows.setdefault(nodes, {"source": nodes[0], "target": nodes[1], "amount": 0.0, "entries": 0, "unusual": strange})
            flow["amount"] += amount
            if nodes not in seen:
                flow["entries"] += 1
                seen.add(nodes)
            key = (target_group, source, entry["journal"])
            pattern = patterns.setdefault(key, {
                "debit": target_group, "credit": source, "journal": entry["journal"], "entries": 0, "amount": 0.0,
                "unusual": strange, "jes": [],
            })
            pattern["amount"] += amount
            if key not in counted:
                counted.add(key)
                pattern["entries"] += 1
                if len(pattern["jes"]) < ENTRY_CAP:
                    pattern["jes"].append(je)
            if treasury and len(date) >= 10:
                other = source if target_group == "bank" else target_group
                side = sides.setdefault(other, {"group": other, "jes": set(), "in": 0.0, "out": 0.0, "days": {}, "weekdays": {}})
                side["jes"].add(je)
                side["in" if target_group == "bank" else "out"] += amount
                day, weekday = int(date[8:10]), weekday_of(date)
                side["days"][day] = side["days"].get(day, 0.0) + amount
                side["weekdays"][weekday] = side["weekdays"].get(weekday, 0.0) + amount

    flow_list = sorted(flows.values(), key=lambda flow: (-flow["amount"], flow["source"], flow["target"]))
    nodes = {}
    for flow in flow_list:
        nodes.setdefault(flow["source"], {"key": flow["source"], "in": 0.0, "out": 0.0})["out"] += flow["amount"]
        nodes.setdefault(flow["target"], {"key": flow["target"], "in": 0.0, "out": 0.0})["in"] += flow["amount"]
    pattern_list = sorted(
        patterns.values(), key=lambda p: (not p["unusual"], -p["amount"], p["debit"], p["credit"], p["journal"]),
    )
    result = {
        "class": class_key, "entries": len(entries), "flows": flow_list,
        "nodes": [nodes[key] for key in _node_order(class_key, nodes)],
        "columns": _columns(class_key, nodes),
        "timing": {"entering": entering, "leaving": leaving, "middle": spec["middle"], "side": spec["entering"]},
        "averageDays": average_days(middle_pairs or [], spec["entering"]),
        "patterns": pattern_list,
    }
    if treasury:
        result["treasury"] = _treasury_table(sides)
    return result


def _columns(class_key, nodes):
    """The diagram's three columns of node keys, the nodes that moved nothing left out."""
    if class_key == "treasury":
        sides = CLASSES["treasury"]["sides"]
        return [
            ["in:%s" % key for key in sides if "in:%s" % key in nodes],
            ["bank"] if "bank" in nodes else [],
            ["out:%s" % key for key in sides if "out:%s" % key in nodes],
        ]
    return [[key for key in column if key in nodes] for column in CLASSES[class_key]["columns"]]


def _node_order(class_key, nodes):
    ordered = [key for column in _columns(class_key, nodes) for key in column]
    return ordered + sorted(key for key in nodes if key not in ordered)


def _busiest(amounts):
    if not amounts:
        return None
    top = max(amounts.values())
    return min(key for key, value in amounts.items() if value == top)


def _treasury_table(sides):
    order = CLASSES["treasury"]["sides"]
    rows = []
    for key in order:
        side = sides.get(key)
        if not side:
            continue
        rows.append({
            "group": key, "entries": len(side["jes"]), "moneyIn": side["in"], "moneyOut": side["out"],
            "busiestDay": _busiest(side["days"]), "busiestWeekday": _busiest(side["weekdays"]),
        })
    return rows


def patterns_line(result, locale):
    """One plain line over the patterns: how many, and how many are unusual."""
    count = len(result["patterns"])
    strange = len([p for p in result["patterns"] if p["unusual"]])
    if locale == "fr":
        return "%d combinaisons débit → crédit, dont %d inhabituelles." % (count, strange)
    return "%d debit → credit combinations, %d of them unusual." % (count, strange)
