"""lib/engines.ts: the automation engines' logic, without the DB or the workbook.

Each function takes what the source loaded (dataset rows as {rowNo, data, amount},
thresholds) and returns what it stored on the run and routed to the findings system.
"""
import hashlib
import hmac
import math
import re

from ._js import cell_str, is_finite, is_number, js_date_parse, js_floor, js_round, js_sorted, js_str, js_trim, u16_slice, weekday
from .errors import EngineError
from .lead_classes import INDEX_SECTION
from .sampling_params import confidence_factor, mus_plan

RECON_PREFIXES = {
    "ar_open_items": ["41"],
    "ap_open_items": ["40"],
    "inventory_listing": ["31", "32", "33", "34", "35", "36", "37", "38"],
    "payroll_register": ["42", "66"],
    "fixed_asset_register": ["21", "22", "23", "24", "25", "28", "29"],
    "bank_statement": ["52", "53", "55", "56", "57", "58"],
}

_MS_PER_DAY = 86_400_000
_INDEX_CODE = re.compile(r"[A-Z][A-Z0-9]{0,2}")
_DATE_KEY = re.compile("date", re.IGNORECASE | re.ASCII)
_SUPPLIER_KEY = re.compile("supplier|fournisseur|name|nom", re.IGNORECASE | re.ASCII)
_ARRAY_INDEX = re.compile(r"0|[1-9][0-9]*")


def seeded_random(seed, index):
    """Deterministic pseudo-random in [0,1) from a seed + index: reproducible runs.
    HMAC-SHA256(seed, str(index)), first four bytes big-endian over 2**32."""
    digest = hmac.new(seed.encode("utf-8", "replace"), js_str(index).encode("utf-8"), hashlib.sha256).digest()
    return int.from_bytes(digest[:4], "big") / 0x100000000


def _abs_amount(row):
    amount = row.get("amount")
    return abs(amount if amount is not None else 0)


def _abs_total(rows):
    total = 0
    for row in rows:
        total += _abs_amount(row)
    return total


def dataset_total(rows):
    """The dataset's signed total."""
    total = 0
    for row in rows:
        amount = row.get("amount")
        total += amount if amount is not None else 0
    return total


def object_keys(data):
    """``Object.keys``: integer-like keys first, ascending, then insertion order. The
    columns of a dataset whose header is "2024" do come back in that order."""
    numbers = [k for k in data if _ARRAY_INDEX.fullmatch(k) and int(k) < 2 ** 32 - 1]
    return sorted(numbers, key=int) + [k for k in data if k not in numbers]


def _first_row_keys(rows):
    return object_keys(rows[0]["data"]) if rows and rows[0].get("data") else []


def select_sample(rows, sampling, performance=None):
    """5.2 sampling (ISA 530). ``sampling``: {method, sampleSize, seed, threshold?,
    confidence?, expectedMisstatement?, overrideSize?, overrideRationale?}. ``performance``:
    the approved performance materiality, if any.

    Returns {picks: [{rowNo, reason}], summary}. ``summary`` is the run's result_summary.
    """
    method = sampling["method"]
    seed = sampling["seed"]
    if sampling["sampleSize"] < 1:
        raise EngineError("invalid-sample-size")
    if not js_trim(seed):
        raise EngineError("seed-required")

    selected = {}
    # Section 04 arithmetic spine: interval = tolerable / factor; size = population /
    # interval. Falls back to the typed size when no confidence was supplied or
    # materiality is not yet approved (legacy runs keep working).
    effective_size = sampling["sampleSize"]
    size_source = "typed"
    computed = None
    expected = sampling.get("expectedMisstatement")
    expected = 0 if expected is None else expected
    if method == "mus" and sampling.get("confidence") is not None:
        if not confidence_factor(sampling["confidence"]):
            raise EngineError("invalid-confidence")
        if performance is not None and performance > 0:
            population_value = _abs_total(rows)
            if population_value <= 0:
                raise EngineError("empty-population")
            plan = mus_plan({
                "populationValue": population_value,
                "tolerable": performance,
                "expected": expected,
                "confidence": sampling["confidence"],
            })
            computed = {
                "populationValue": population_value,
                "tolerable": performance,
                "expectedMisstatement": expected,
                "confidence": sampling["confidence"],
                "factor": plan["factor"],
                "interval": js_round(plan["interval"]),
                "sampleSize": plan["sampleSize"],
            }
            effective_size = plan["sampleSize"]
            size_source = "computed"
    rationale = sampling.get("overrideRationale")
    if sampling.get("overrideSize") is not None:
        if sampling["overrideSize"] < 1:
            raise EngineError("invalid-sample-size")
        if rationale is None or not js_trim(rationale):
            raise EngineError("override-rationale-required")
        effective_size = sampling["overrideSize"]
        size_source = "override"

    if method == "criteria":
        threshold = sampling.get("threshold")
        threshold = 0 if threshold is None else threshold
        if threshold <= 0:
            raise EngineError("threshold-required")
        for row in rows:
            if _abs_amount(row) > threshold:
                selected[row["rowNo"]] = (row, "key-item")
    remainder = [row for row in rows if row["rowNo"] not in selected]
    remainder_needed = max(0, effective_size)

    if method in ("random", "criteria"):
        pool = list(remainder)
        index = 0
        criteria = method == "criteria"
        while pool:
            # for criteria the bound is always above the count: only the draw count stops it
            bound = len(selected) + min(remainder_needed or effective_size, len(pool)) if criteria else min(effective_size, len(rows))
            if not len(selected) < bound:
                break
            pick = js_floor(seeded_random(seed, index) * len(pool))
            row = pool.pop(pick)
            if row["rowNo"] not in selected:
                selected[row["rowNo"]] = (row, "random")
            index += 1
            if criteria and index >= effective_size:
                break
    elif method == "systematic":
        interval = max(1, js_floor(len(rows) / effective_size))
        i = js_floor(seeded_random(seed, 0) * interval)
        while i < len(rows) and len(selected) < effective_size:
            selected[rows[i]["rowNo"]] = (rows[i], "systematic")
            i += interval
    elif method == "mus":
        total = _abs_total(rows)
        if total <= 0:
            raise EngineError("empty-population")
        interval = total / effective_size
        target = seeded_random(seed, 0) * interval
        cumulative = 0
        for row in rows:
            cumulative += _abs_amount(row)
            while cumulative > target and len(selected) < effective_size:
                selected[row["rowNo"]] = (row, "mus")
                target += interval

    picks = list(selected.values())
    sampled_value = 0
    for row, _reason in picks:
        sampled_value += _abs_amount(row)
    summary = {
        "method": method,
        "populationRows": len(rows),
        "populationTotal": dataset_total(rows),
        "selected": len(picks),
        "sampledValue": sampled_value,
        "keyItems": len([1 for _row, reason in picks if reason == "key-item"]),
        "sampleSize": effective_size,
        "sizeSource": size_source,
    }
    if computed:
        summary["computed"] = computed
    if size_source == "override":
        summary["override"] = True
        summary["overrideRationale"] = js_trim(rationale)
    return {"picks": [{"rowNo": row["rowNo"], "reason": reason} for row, reason in picks], "summary": summary}


def evaluate_sampling(sampled_value, population_total, misstatement_found, trivial, run_id="", locale="en"):
    """5.3: the projected misstatement, and the C1.1 finding it raises when not trivial.
    {projected, raisedToB5, finding}; ``finding`` is None when nothing is raised."""
    if not sampled_value or sampled_value <= 0:
        raise EngineError("empty-population")
    projected = js_round((misstatement_found / sampled_value) * abs(population_total))
    above_trivial = trivial is not None and abs(projected) >= trivial
    finding = None
    if above_trivial:
        short = u16_slice(run_id, 0, 8)
        finding = {
            "route": "b5",
            "title": "Anomalie extrapolée — échantillonnage %s" % short if locale == "fr" else "Projected misstatement from sampling run %s" % short,
            "amount": projected,
            "mtype": "projected",
        }
    return {"projected": projected, "raisedToB5": above_trivial, "finding": finding}


def record_tod_result(tod, trivial, run_id=""):
    """A test-of-details result. ``tod``: {indexCode, sampleValue, sampleMisstatement,
    keyMisstatement, remainingValue, locale?}. Returns {indexCode, section, summary,
    projected, raisedToB5, findings}: the projection's finding if raised, then the key
    items' factual one."""
    index_code = js_trim(tod["indexCode"]).upper()
    if not _INDEX_CODE.fullmatch(index_code):
        raise EngineError("invalid-index")
    for field in ("sampleValue", "sampleMisstatement", "keyMisstatement", "remainingValue"):
        if not is_finite(tod.get(field)):
            raise EngineError("invalid-amount")
    if tod["sampleValue"] <= 0:
        raise EngineError("empty-population")
    if tod["remainingValue"] < 0:
        raise EngineError("invalid-amount")
    fr = tod.get("locale") == "fr"
    evaluation = evaluate_sampling(tod["sampleValue"], tod["remainingValue"], tod["sampleMisstatement"], trivial, run_id, "fr" if fr else "en")
    findings = [evaluation["finding"]] if evaluation["finding"] else []
    if tod["keyMisstatement"] != 0:
        short = u16_slice(run_id, 0, 8)
        findings.append({
            "route": "b5",
            "title": (
                "Anomalie avérée sur les éléments clés — %s (test de détail %s)" % (index_code, short)
                if fr else
                "Factual misstatement in key items — %s (ToD run %s)" % (index_code, short)
            ),
            "amount": js_round(tod["keyMisstatement"]),
            "mtype": "factual",
            "trivialConfirmed": True,
        })
    return {
        "indexCode": index_code,
        "section": INDEX_SECTION.get(index_code, ""),
        "summary": {
            "method": "tod-mus",
            "indexCode": index_code,
            "sampledValue": tod["sampleValue"],
            "populationTotal": tod["remainingValue"],
            "keyMisstatement": tod["keyMisstatement"],
            "sampleMisstatement": tod["sampleMisstatement"],
        },
        "projected": evaluation["projected"],
        "raisedToB5": evaluation["raisedToB5"],
        "findings": findings,
    }


def recon_preview(kind, rows, tb_total):
    """The two figures a reconciliation compares; None when the kind has no mapping.
    ``tb_total``: the TB closing of the kind's RECON_PREFIXES."""
    prefixes = RECON_PREFIXES.get(kind)
    if not prefixes:
        return None
    total = dataset_total(rows)
    book = -tb_total if kind == "ap_open_items" else tb_total
    return {"kind": kind, "datasetTotal": total, "tbTotal": book, "difference": total - book, "prefixes": prefixes}


def run_reconciliation(kind, rows, tb_total, trivial, stale_days=None, period_end=None):
    """5.4-5.6. {engine, summary, staleRows, finding}. AP dataset totals are positive
    listings and the TB closing of a liability negative: compared on sign-adjusted book
    value. Bank rec: rows dated before the period end less ``stale_days`` are stale."""
    if not RECON_PREFIXES.get(kind):
        raise EngineError("unsupported-dataset")
    total = dataset_total(rows)
    book = -tb_total if kind == "ap_open_items" else tb_total
    difference = total - book
    above_trivial = trivial is not None and abs(difference) > trivial

    stale_items = 0
    stale_rows = []
    date_key = next((key for key in _first_row_keys(rows) if _DATE_KEY.search(key)), None)
    if kind == "bank_statement" and date_key and period_end:
        end = js_date_parse(period_end)
        cutoff = None if end is None else end - (30 if stale_days is None else stale_days) * _MS_PER_DAY
        for row in rows:
            text = js_str(row["data"].get(date_key))
            when = js_date_parse(text)
            if when is not None and cutoff is not None and when < cutoff:
                stale_items += 1
                stale_rows.append([row["rowNo"], text, row.get("amount")])

    engine = "recon_far" if kind == "fixed_asset_register" else "recon_bank" if kind == "bank_statement" else "recon_subledger"
    finding = None
    if above_trivial:
        finding = {
            "route": "b4",
            "title": "Unreconciled difference (%s): %s" % (kind, js_str(js_round(difference))),
            "detail": "Dataset %s vs TB %s — investigate." % (js_str(js_round(total)), js_str(js_round(book))),
        }
    return {
        "engine": engine,
        "summary": {"datasetTotal": total, "tbTotal": book, "difference": difference, "aboveTrivial": above_trivial, "staleItems": stale_items},
        "staleRows": stale_rows,
        "finding": finding,
    }


def run_supplier_recon(statement_rows, ledger_rows):
    """5.7 supplier statements against the ledger. {suppliersCompared, differences, lines}."""

    def supplier_key(rows):
        return next((key for key in _first_row_keys(rows) if _SUPPLIER_KEY.search(key)), None)

    statement_key = supplier_key(statement_rows)
    ledger_key = supplier_key(ledger_rows)
    if not statement_key or not ledger_key:
        raise EngineError("supplier-column-missing")

    def sum_by(rows, key):
        totals = {}
        for row in rows:
            supplier = js_trim(cell_str(row["data"].get(key)))
            if not supplier:
                continue
            amount = row.get("amount")
            totals[supplier] = totals.get(supplier, 0) + (amount if amount is not None else 0)
        return totals

    statements = sum_by(statement_rows, statement_key)
    ledger = sum_by(ledger_rows, ledger_key)
    suppliers = set(statements) | set(ledger)
    lines = []
    differences = 0
    for supplier in js_sorted(suppliers):
        statement = statements.get(supplier, 0)
        book = ledger.get(supplier, 0)
        diff = statement - book
        if abs(diff) > 0.01:
            differences += 1
        lines.append([supplier, statement, book, diff])
    return {"suppliersCompared": len(suppliers), "differences": differences, "lines": lines}


def run_je_testing(rows, period_end, large_threshold=None, performance=None):
    """5.8 journal-entry scoring. {largeThreshold, scored, flagged, scores}: ``scores``
    are the flagged rows, highest score first."""
    large = large_threshold if large_threshold is not None else (performance if performance is not None else 0)
    date_key = next((key for key in _first_row_keys(rows) if _DATE_KEY.search(key)), None)
    end = js_date_parse(period_end)

    scores = []
    for row in rows:
        flags = []
        amount = _abs_amount(row)
        if amount > 0 and math.fmod(amount, 1_000_000) == 0:
            flags.append("round-amount")
        if large > 0 and amount >= large:
            flags.append("large")
        if date_key:
            when = js_date_parse(js_str(row["data"].get(date_key)))
            if when is not None:
                # getDay() is local time in the source: this is the UTC reading
                if weekday(when) in (0, 6):
                    flags.append("weekend")
                if end is not None and end - when <= 5 * _MS_PER_DAY and end - when >= 0:
                    flags.append("period-end")
        scores.append({"rowNo": row["rowNo"], "score": len(flags), "flags": flags})
    flagged = sorted((s for s in scores if s["score"] > 0), key=lambda s: -s["score"])
    return {"largeThreshold": large, "scored": len(scores), "flagged": len(flagged), "scores": flagged}


def run_substantive_analytic(actual, expectation, tolerance, basis=""):
    """5.9: actual against expectation. {actual, variance, unexplained, finding}."""
    if not (is_number(tolerance) and tolerance > 0):
        raise EngineError("tolerance-required")
    variance = actual - expectation
    unexplained = abs(variance) > tolerance
    finding = None
    if unexplained:
        finding = {
            "route": "b5",
            "title": "Unresolved analytic variance (%s)" % basis,
            "amount": js_round(variance),
            "mtype": "judgmental",
            "trivialConfirmed": True,
        }
    return {"actual": actual, "variance": variance, "unexplained": unexplained, "finding": finding}
