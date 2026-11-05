"""lib/gl-line.ts's pure half, by the source's own rules."""
import pytest

from services.errors import ServiceError
from services.gl_line import mapped_fields, nf, parse_date_iso, population_checks, projector, safe_text


@pytest.mark.parametrize("raw,expected", [
    ("2025-03-04", "2025-03-04"),
    ("2025/03/04", "2025-03-04"),
    ("2025-03-04T10:00:00", "2025-03-04"),
    ("04/03/2025", "2025-03-04"),
    ("04.03.25", "2025-03-04"),
    ("03/25/2025", "2025-03-25"),
    ("31/02/2025", None),
    (45000, "2023-03-15"),
    ("45000", "2023-03-15"),
    (0, None),
    ("", None),
    (None, None),
    ("rubbish", None),
])
def test_parse_date(raw, expected):
    assert parse_date_iso(raw) == expected


def test_safe_text_neutralises_formulas():
    assert safe_text("=SUM(A1)") == "'=SUM(A1)"
    assert safe_text("-12") == "'-12"
    assert safe_text("  ok ") == "ok"
    assert safe_text("   ") is None
    assert safe_text(None) is None


def test_mapped_fields_derives():
    assert {"preparer", "signedAmount"} <= mapped_fields({"recordedBy": "R", "amount": "A"})
    assert "signedAmount" not in mapped_fields({"debit": "D"})
    assert "jeNumber" in mapped_fields({"jeKey": "J\u001fV"})


def test_projector_pair_single_and_identity():
    project = projector({"account": "A", "jeNumber": "J", "debit": "D", "credit": "C", "amount": "M"})
    line = project({"A": "411", "J": "1", "D": "1 000,50", "C": "", "M": "9"})
    assert (line["debit"], line["credit"], line["signed"]) == (1000.5, 0, 1000.5)
    assert project({"A": "", "J": "1"}) is None
    single = projector({"account": "A", "jeNumber": "J", "amount": "M"})
    assert single({"A": "411", "J": "1", "M": "(10)"})["credit"] == 10
    keyed = projector({"account": "A", "jeKey": "J\u001fV"})
    assert keyed({"A": "411", "J": "VE", "V": "7"})["je_number"] == "VE · 7"
    with pytest.raises(ServiceError):
        projector({"account": "A"})


def test_nf():
    assert nf(1234567.5) == "1,234,567.5"
    assert nf(0) == "0"
    assert nf(-1.5) == "-1.5"


def _aggregate(**over):
    base = {
        "fields": {"account", "jeNumber", "jeDescription", "journalDate", "signedAmount"}, "mapping": {"jeNumber": "J"},
        "source_rows": 10, "lines": 10, "entries": 5, "no_account": 0, "no_je": 0, "no_date": 0, "zero_amount": 0,
        "total_debit": 100.0, "total_credit": 100.0, "out_of_period": 0, "period_start": "2025-01-01", "period_end": "2025-12-31",
        "unbalanced": 0, "dup_groups": 0, "dup_extra": 0,
    }
    base.update(over)
    return base


def test_all_clear():
    result = population_checks(_aggregate())
    assert result["status"] == "passed" and result["passed"] == 11


def test_dates_bands():
    status = lambda **over: {c["key"]: c["status"] for c in population_checks(_aggregate(**over))["checks"]}  # noqa: E731
    assert status(lines=1000, no_date=5)["dates-parsed"] == "warning"
    assert status(lines=1000, no_date=10)["dates-parsed"] == "failed"
    assert status(period_start=None)["dates-in-period"] == "warning"


def test_a_journal_code_is_not_an_entry_number():
    result = population_checks(_aggregate(lines=1000, entries=5))
    assert result["status"] == "failed"
    same = population_checks(_aggregate(fields={"journalCode", "account", "jeNumber", "jeDescription", "journalDate", "signedAmount"}, mapping={"jeNumber": "J", "journalCode": "J"}))
    assert next(c for c in same["checks"] if c["key"] == "je-distinguishes")["status"] == "failed"


def test_tolerance_is_half_a_cent():
    within = population_checks(_aggregate(total_debit=100.004))
    assert next(c for c in within["checks"] if c["key"] == "debit-credit-reconcile")["status"] == "passed"
    beyond = population_checks(_aggregate(total_debit=100.01))
    assert next(c for c in beyond["checks"] if c["key"] == "debit-credit-reconcile")["status"] == "failed"
