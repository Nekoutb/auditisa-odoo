"""Port of tests/lib/upload-safety.test.ts. fileResponseHeaders has no port: Odoo's
/web/content serves the bytes, with download=true on the links the renderer writes."""

import pytest
from services import UnsafeFile, allowed_extensions, check_upload, extension_of, safe_filename

ZIP = b"PK\x03\x04"
OOXML = ZIP + b"....[Content_Types].xml...."
PDF = b"%PDF-1.7\nstuff"
PNG = b"\x89PNG\r\n\x1a\n\x00"
CSV = "Compte;Libelle;Montant\n411;Client;1 500 000,75\n".encode()


def refusal(name, content):
    with pytest.raises(UnsafeFile) as caught:
        check_upload(name, content)
    return caught.value.code


def test_accepts_the_formats_an_audit_file_needs():
    assert check_upload("lead.xlsx", OOXML)[1] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert check_upload("memo.docx", OOXML)[1] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert check_upload("confirmation.pdf", PDF)[1] == "application/pdf"
    assert check_upload("scan.png", PNG)[1] == "image/png"
    assert check_upload("ledger.csv", CSV)[1] == "text/csv"


def test_names_the_extension_it_kept():
    assert check_upload("Trade Receivables.xlsx", OOXML)[2] == "xlsx"


@pytest.mark.parametrize("name", ["payload.exe", "run.bat", "a.ps1", "x.vbs", "setup.msi", "link.lnk", "page.hta"])
def test_refuses_executables_and_scripts_by_name(name):
    assert refusal(name, PDF) == "executable-refused"


@pytest.mark.parametrize("name", ["book.xlsm", "doc.docm", "deck.pptm"])
def test_refuses_macro_enabled_office_formats(name):
    assert refusal(name, OOXML) == "executable-refused"


def test_refuses_svg_and_html():
    assert refusal("logo.svg", b"<svg onload=alert(1)>") == "executable-refused"
    assert refusal("evil.html", b"<script>x</script>") == "executable-refused"


def test_refuses_anything_not_on_the_allowlist():
    assert refusal("archive.7z", PDF) == "extension-not-allowed"
    assert refusal("db.sqlite", PDF) == "extension-not-allowed"


def test_refuses_a_file_with_no_extension():
    assert refusal("README", PDF) == "no-extension"


@pytest.mark.parametrize("name", ["invoice.pdf", "sheet.xlsx", "photo.png"])
def test_refuses_an_executable_renamed_to_a_permitted_extension(name):
    assert refusal(name, b"MZ\x90\x00\x03") == "content-mismatch"


def test_refuses_a_plain_zip_wearing_an_office_extension():
    assert refusal("book.xlsx", ZIP + b"just-some-files") == "not-an-office-file"


def test_refuses_binary_content_claiming_to_be_a_csv():
    assert refusal("ledger.csv", b"\x00\x01\x02\x00") == "content-mismatch"


def test_refuses_an_empty_file():
    assert refusal("empty.pdf", b"") == "empty-file"


def test_accepts_a_latin1_csv():
    assert check_upload("export.csv", "Compte;Libellé;Montant\n411;Client;100\n".encode("latin-1"))[2] == "csv"


def test_finds_the_ooxml_marker_anywhere():
    assert check_upload("odd.xlsx", ZIP + b"A" * 600 + b"[Content_Types].xml")[2] == "xlsx"


def test_safe_filename_keeps_only_the_basename():
    assert safe_filename("C:\\Users\\x\\lead.xlsx") == "lead.xlsx"
    assert safe_filename("../../etc/passwd.txt") == "passwd.txt"


def test_safe_filename_strips_the_rtl_override():
    assert safe_filename("invoice\u202Excod.exe") == "invoicexcod.exe"


def test_safe_filename_strips_control_characters_and_leading_dots():
    assert safe_filename("...hidden.pdf") == "hidden.pdf"
    assert safe_filename("bad\u0000name.pdf") == "badname.pdf"


def test_safe_filename_never_returns_empty():
    assert safe_filename("") == "attachment"
    assert safe_filename("...") == "attachment"


def test_extension_of():
    assert extension_of("Report.FINAL.PDF") == "pdf"
    assert extension_of("noext") == ""
    assert extension_of(".gitignore") == ""


def test_allowed_extensions():
    allowed = allowed_extensions()
    assert "xlsx" in allowed and "pdf" in allowed
    assert "exe" not in allowed and "xlsm" not in allowed
