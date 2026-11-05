import pytest

from services.aging import aging, parse_date_ms
from services.errors import ServiceError
from services.upload_safety import check_upload, extension_of, safe_filename

PERIOD_END = 1767139200000  # 2025-12-31


def test_aging_buckets_at_the_edges():
    mapping = {"party": "P", "amount": "M", "date": "D"}
    rows = [
        {"P": "A", "M": "10", "D": "01/12/2025"},  # 30 days
        {"P": "A", "M": "20", "D": "30/11/2025"},  # 31
        {"P": "A", "M": "30", "D": "01/10/2025"},  # 91
        {"P": "", "M": "99", "D": "01/12/2025"},
        {"P": "B", "M": "5", "D": "nope"},
    ]
    result = aging(rows, mapping, PERIOD_END)
    row = result["rows"][0]
    assert (row["current"], row["d31_60"], row["over90"], row["total"]) == (10, 20, 30, 60)
    assert result["undated"] == 1
    assert aging(rows, {"party": "P"}, PERIOD_END) is None


def test_aging_sorted_by_absolute_total():
    mapping = {"party": "P", "amount": "M", "date": "D"}
    rows = [{"P": "A", "M": "10", "D": "01/12/2025"}, {"P": "B", "M": "-50", "D": "01/12/2025"}]
    assert [r["party"] for r in aging(rows, mapping, PERIOD_END)["rows"]] == ["B", "A"]


def test_date_forms():
    assert parse_date_ms("01/12/25") == parse_date_ms("01/12/2025")
    assert parse_date_ms("") is None
    assert parse_date_ms("rubbish") is None


@pytest.mark.parametrize("name,content", [
    ("a.exe", b"MZ"), ("a.xlsm", b"PK\x03\x04"), ("a.pdf", b"nope"), ("a.xlsx", b"PK\x03\x04 no marker"),
    ("a.csv", b"a\x00b"), ("noext", b"x"),
])
def test_refused(name, content):
    with pytest.raises(ServiceError) as caught:
        check_upload(name, content)
    assert caught.value.code == "file-type"


def test_accepted_and_canonical():
    assert check_upload("a.PDF", b"%PDF-1") == ("a.PDF", "application/pdf")
    assert check_upload("a.xlsx", b"PK\x03\x04[Content_Types].xml")[1].endswith("sheet")
    assert check_upload("a.csv", b"x;y")[1] == "text/csv"


def test_safe_names():
    assert safe_filename("../../x.pdf") == "x.pdf"
    assert safe_filename("in‮cod.exe") == "incod.exe"
    assert safe_filename("...") == "attachment"
    assert extension_of(".bashrc") == ""
