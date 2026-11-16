"""The journal-entry and sampling worksheets (owner's mock-ups of 2026-11-16): what each page
shows, worked out from what the engines already return. Nothing here selects, sizes, draws or
projects: those stay in je_selection, toc_sampling, sampling_params and engines."""

from ._js import js_round

REVIEW_STATES = ("to_clear", "cleared", "problem")
STEP_KEYS = ("population", "size", "draw", "test", "result")
# within half a franc an item agrees: the ledger keeps hundredths, the auditor types francs
AGREE_TOLERANCE = 0.5
TOC_GOOD = ("high", "moderate", "rely")
TOC_BAD = ("extend", "none")


def _text(value):
    return str(value).strip() if value not in (None, False) else ""


def group_entries(lines, reviews=None):
    """The selected lines as entries, in the order the engine ranked them (the entry caught most
    ways first). ``reviews``: {je_number: {status, note, finding, files}}. An entry's amount is
    half its gross value: the debits of a balanced entry."""
    reviews = reviews or {}
    order, by_number = [], {}
    for line in lines:
        number = line["jeNumber"]
        entry = by_number.get(number)
        if entry is None:
            review = reviews.get(number) or {}
            entry = {
                "je": number, "date": line.get("journalDate") or "", "journal": line.get("journalCode") or "",
                "description": _text(line.get("jeDescription")) or _text(line.get("lineDescription")),
                "postedBy": _text(line.get("preparer")),
                "amount": js_round((line.get("entryGrossValue") or 0) / 2),
                "reasons": [], "criteria": [], "lines": [],
                "status": review.get("status") or "to_clear", "note": review.get("note") or "",
                "finding": review.get("finding") or False, "files": review.get("files") or 0,
                "reviewId": review.get("id") or False,
            }
            by_number[number] = entry
            order.append(entry)
        for reason in line.get("reasons") or []:
            if reason["criterion"] not in entry["criteria"]:
                entry["criteria"].append(reason["criterion"])
                entry["reasons"].append(reason["label"])
        entry["lines"].append({
            "account": line.get("account") or "", "accountName": line.get("accountName") or "",
            "debit": line.get("debit") or 0, "credit": line.get("credit") or 0,
            "description": _text(line.get("lineDescription")),
        })
    return order


def je_progress(entries, selected_total=None):
    """{total, cleared, problems, open}: ``selected_total`` is the engine's count of entries,
    which can exceed the entries listed when the page shows only the first lines."""
    cleared = len([e for e in entries if e["status"] == "cleared"])
    problems = len([e for e in entries if e["status"] == "problem"])
    total = selected_total if selected_total is not None else len(entries)
    return {"total": total, "cleared": cleared, "problems": problems, "open": max(0, total - cleared - problems)}


def _chain(done, bad=None, labels=None):
    """Five steps from five booleans: done ones green, the first open one current, then to do.
    ``bad``: the steps that went wrong (red). ``labels``: a step's own text, such as Test 18/30."""
    bad, labels = bad or set(), labels or {}
    steps, current = [], False
    for key, finished in zip(STEP_KEYS, done):
        if key in bad:
            state = "bad"
        elif finished:
            state = "done"
        elif not current:
            state, current = "now", True
        else:
            state = "todo"
        steps.append({"key": key, "state": state, "label": labels.get(key) or ""})
    return steps


def card_state(steps):
    """The colour of a sample's card: red if a step went wrong, green when all are done, else amber."""
    if any(step["state"] == "bad" for step in steps):
        return "bad"
    if all(step["state"] == "done" for step in steps):
        return "done"
    return "now"


def toc_steps(population, size, drawn, tested, evaluation, operating_eval=None):
    """A test of controls: occurrences counted, size set, items drawn, items tested, evaluated."""
    size = size or 0
    tested = tested or 0
    finished_testing = bool(size) and tested >= size
    concluded = bool(evaluation) and finished_testing
    bad = set()
    if concluded and (evaluation in TOC_BAD or operating_eval == "not_effective"):
        bad.add("result")
    labels = {}
    if size and 0 < tested < size:
        labels["test"] = "%d/%d" % (tested, size)
    return _chain([bool(population), bool(size), bool(drawn), finished_testing, concluded], bad, labels)


def tod_steps(population_rows, size, drawn, tested, picked, projected, exceeds):
    """A test of details drawn from a dataset: the projection is the result."""
    picked = picked or 0
    tested = tested or 0
    finished_testing = picked > 0 and tested >= picked
    concluded = projected is not None
    labels = {}
    if picked and 0 < tested < picked:
        labels["test"] = "%d/%d" % (tested, picked)
    return _chain(
        [bool(population_rows), bool(size), bool(drawn), finished_testing or concluded, concluded],
        {"result"} if concluded and exceeds else set(), labels,
    )


def tod_result_steps(exceeds):
    """A test of details recorded as totals (sample value, misstatement, remaining population)."""
    return _chain([True, True, True, True, True], {"result"} if exceeds else set())


def sample_items(picks, book, results):
    """The items of a drawn sample with what the auditor found. ``picks``: [(row_no, reason,
    label)]; ``book``: {row_no: amount}; ``results``: {str(row_no): {audited, how, note}}.
    Returns (rows, totals); an item without an audited value is still to test."""
    rows = []
    totals = {"book": 0, "audited": 0, "difference": 0, "tested": 0, "errors": 0, "count": 0}
    for position, (row_no, reason, label) in enumerate(picks, start=1):
        found = results.get(str(row_no)) or {}
        value = book.get(row_no)
        audited = found.get("audited")
        difference = None
        if audited is not None and value is not None:
            difference = js_round((audited - value) * 100) / 100
        if audited is None:
            result = "to_test"
        elif difference is not None and abs(difference) >= AGREE_TOLERANCE:
            result = "error"
        else:
            result = "agreed"
        rows.append({
            "position": position, "rowNo": row_no, "reason": reason, "label": label, "book": value,
            "audited": audited, "difference": difference, "how": found.get("how") or "", "note": found.get("note") or "",
            "result": result,
        })
        totals["count"] += 1
        if value is not None:
            totals["book"] += value
        if audited is not None:
            totals["tested"] += 1
            totals["audited"] += audited
            if difference is not None:
                totals["difference"] += difference
            if result == "error":
                totals["errors"] += 1
    totals["difference"] = js_round(totals["difference"] * 100) / 100
    return rows, totals


def clean_item_patch(patch):
    """What a person may set on one tested item: the audited value (a number, or nothing to
    clear it), how it was tested and a note. Anything else is refused by the caller (None)."""
    if not isinstance(patch, dict) or set(patch) - {"audited", "how", "note"}:
        return None
    out = {}
    if "audited" in patch:
        value = patch["audited"]
        if value in (None, "", False):
            out["audited"] = None
        else:
            try:
                number = float(str(value).replace(" ", "").replace(" ", "").replace(",", "."))
            except ValueError:
                return None
            if number != number or number in (float("inf"), float("-inf")):
                return None
            out["audited"] = number
    if "how" in patch:
        out["how"] = _text(patch["how"])[:120]
    if "note" in patch:
        out["note"] = _text(patch["note"])[:2000]
    return out


def exceeds_tolerable(projected, tolerable):
    """The projected misstatement against the tolerable one (ISA 530 ¶14). None when either is missing."""
    if projected is None or tolerable is None:
        return None
    return abs(projected) > tolerable
