import hashlib
import io
import json
import zipfile
from datetime import date

from services.archive_seal import (
    ARCHIVE_CONFIRMS, QUESTIONS, answer_key, answers_digest, assembly_status, build_seal, destruction_refusal,
    note_key, question_rows, ready_to_sign, retention_end, seal_index, validate_answer, verify_seal,
)


def answered(value="yes", note="Seen."):
    values = {}
    for q in QUESTIONS:
        values[answer_key(q["key"])] = value
        values[note_key(q["key"])] = note
    return values


def test_thirteen_questions_two_confirmations():
    assert len(QUESTIONS) == 13 and len(ARCHIVE_CONFIRMS) == 2
    assert all(q["en"] and q["fr"] for q in QUESTIONS + ARCHIVE_CONFIRMS)
    assert len({q["key"] for q in QUESTIONS + ARCHIVE_CONFIRMS}) == 15


def test_a_note_is_required_for_every_answer():
    assert validate_answer("yes", "  ") == "note-required"
    assert validate_answer("no", "") == "note-required"
    assert validate_answer("maybe", "x") == "invalid-value"
    assert validate_answer("yes", "Minutes read") is None
    assert validate_answer("no", "Not applicable: no other information") is None


def test_only_yes_with_a_note_is_green():
    values = answered()
    values[note_key("cl05")] = ""
    values[answer_key("cl06")] = "no"
    rows = {row["key"]: row for row in question_rows(QUESTIONS, values)}
    assert not rows["cl05"]["answered"] and not rows["cl05"]["ok"]
    assert rows["cl06"]["answered"] and not rows["cl06"]["ok"]
    assert rows["cl01"]["ok"]
    assert question_rows(QUESTIONS, values, fr=True)[0]["label"].startswith("Événements")


def test_ready_needs_every_check_and_every_answer():
    checks = [{"key": "a", "ok": True}]
    assert ready_to_sign(checks, question_rows(QUESTIONS, answered()))
    assert not ready_to_sign([{"key": "a", "ok": False}], question_rows(QUESTIONS, answered()))
    assert not ready_to_sign(checks, question_rows(QUESTIONS, answered("no")))
    assert not ready_to_sign(checks, question_rows(QUESTIONS, {}))


def test_digest_moves_with_an_answer():
    values = answered()
    before = answers_digest(QUESTIONS, values)
    values[note_key("cl02")] = "Letter dated the report date"
    assert answers_digest(QUESTIONS, values) != before


def test_assembly_clock():
    report = date(2026, 3, 12)
    assert assembly_status(None, report) is None
    start = assembly_status(report, date(2026, 3, 12))
    assert (start["deadline"], start["days_left"], start["tone"]) == (date(2026, 5, 11), 60, "green")
    assert assembly_status(report, date(2026, 4, 3))["days_left"] == 38
    assert assembly_status(report, date(2026, 4, 27))["tone"] == "amber"
    late = assembly_status(report, date(2026, 5, 12))
    assert late["overdue"] and late["tone"] == "red" and late["elapsed_pct"] == 100


def test_retention_and_destruction():
    assert retention_end(date(2026, 3, 12)) == date(2036, 3, 12)
    assert retention_end(date(2028, 2, 29)) == date(2038, 2, 28)
    assert destruction_refusal(date(2036, 3, 12), False, date(2030, 1, 1)) == "retention-not-reached"
    assert destruction_refusal(None, False, date(2030, 1, 1)) == "retention-not-reached"
    assert destruction_refusal(date(2036, 3, 12), True, date(2040, 1, 1)) == "legal-hold"
    assert destruction_refusal(date(2036, 3, 12), False, date(2036, 3, 12)) is None


def test_seal_manifest_hashes_match_the_bytes():
    files = [("papers/E4.1.html", b"<p>work</p>"), ("evidence/E4.1/bank.pdf", b"%PDF-1.4 bank"), ("papers/C1.1.html", "é".encode())]
    data, overall, rows = build_seal(files, {"engagement": "DEMO SA 2025", "render": "html"})
    archive = zipfile.ZipFile(io.BytesIO(data))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["overallSha256"] == overall and manifest["fileCount"] == 3
    for row in manifest["files"]:
        assert hashlib.sha256(archive.read(row["path"])).hexdigest() == row["sha256"]
        assert len(archive.read(row["path"])) == row["bytes"]
    assert hashlib.sha256(archive.read("SHA256SUMS")).hexdigest() == overall
    assert archive.read("manifest.csv").decode().splitlines()[0] == "path,bytes,sha256"
    assert verify_seal(data) == (True, overall)
    # the same files give the same fingerprint, whatever their order
    assert seal_index(list(reversed(files)))[2] == overall


def test_a_changed_file_breaks_the_seal():
    data, _overall, _rows = build_seal([("a.txt", b"one"), ("b.txt", b"two")], {})
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as copy:
        for name in source.namelist():
            copy.writestr(name, b"tampered" if name == "b.txt" else source.read(name))
    assert verify_seal(out.getvalue())[0] is False


def test_duplicate_paths_refused():
    try:
        seal_index([("a", b"1"), ("a", b"2")])
    except ValueError:
        return
    raise AssertionError("duplicate accepted")
