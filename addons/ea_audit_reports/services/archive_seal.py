"""The completion checklist (C6.1), the assembly window and the sealed copy of an archived file
(C6.2), without Odoo: what is asked, what counts as answered, the 60-day clock, the retention
refusals, and the ZIP whose every file carries its SHA-256 (owner's mock-ups of 2026-11-16)."""
import csv
import hashlib
import io
import json
import zipfile
from datetime import date, timedelta

#: OHADA practice: an audit file is kept ten years from the report date (ISA 230 A23, ISQM 1 ¶31(f)).
OHADA_RETENTION_YEARS = 10
#: ISA 230 ¶14, A21: the final file is assembled within sixty days of the report date.
ASSEMBLY_DAYS = 60
#: Under this many days left, the clock turns amber.
ASSEMBLY_AMBER_DAYS = 15

# The thirteen questions the team answers before the report is issued (C6.1, "Confirmed by
# the team"). Each answer is Yes or No and carries a note; only Yes with its note is green.
QUESTIONS = (
    {"key": "cl01", "isa": "ISA 560",
     "en": "Subsequent events reviewed up to the report date",
     "fr": "Événements postérieurs revus jusqu'à la date du rapport"},
    {"key": "cl02", "isa": "ISA 580",
     "en": "Representations dated as near as possible to, and not after, the report date",
     "fr": "Déclarations écrites datées au plus près de la date du rapport, et jamais après"},
    {"key": "cl03", "isa": "ISA 570",
     "en": "Going concern concluded; disclosures adequate",
     "fr": "Continuité d'exploitation conclue ; informations fournies adéquates"},
    {"key": "cl04", "isa": "ISA 220",
     "en": "Independence re-confirmed by every team member",
     "fr": "Indépendance reconfirmée par chaque membre de l'équipe"},
    {"key": "cl05", "isa": "",
     "en": "Consultations closed; differences of opinion resolved",
     "fr": "Consultations closes ; divergences d'opinion résolues"},
    {"key": "cl06", "isa": "",
     "en": "Final financial statements read; they agree to the audited figures and the report",
     "fr": "États financiers définitifs lus ; ils concordent avec les chiffres audités et le rapport"},
    {"key": "cl07", "isa": "ISA 720",
     "en": "Other information read",
     "fr": "Autres informations lues"},
    {"key": "cl08", "isa": "ISA 700-706",
     "en": "Report wording final, including any modification, emphasis or key audit matters",
     "fr": "Rédaction du rapport définitive, y compris toute modification, observation ou point clé de l'audit"},
    {"key": "cl09", "isa": "ISA 260/265",
     "en": "Communications to those charged with governance sent",
     "fr": "Communications aux responsables de la gouvernance envoyées"},
    {"key": "cl10", "isa": "ISA 450",
     "en": "Uncorrected misstatements communicated and management's reasons obtained",
     "fr": "Anomalies non corrigées communiquées et raisons de la direction obtenues"},
    {"key": "cl11", "isa": "OHADA",
     "en": "OHADA statutory reports prepared (e.g. special report on regulated agreements)",
     "fr": "Rapports légaux OHADA préparés (par ex. rapport spécial sur les conventions réglementées)"},
    {"key": "cl12", "isa": "",
     "en": "No unpaid fees or other matter threatening independence",
     "fr": "Aucun honoraire impayé ni autre élément menaçant l'indépendance"},
    {"key": "cl13", "isa": "ISA 700",
     "en": "The report is dated when sufficient evidence was obtained and not before the partner's and quality reviewer's reviews",
     "fr": "Le rapport est daté lorsque des éléments suffisants ont été obtenus, et pas avant les revues de l'associé et du réviseur qualité"},
)

# What the team confirms on C6.2 before the file is archived.
ARCHIVE_CONFIRMS = (
    {"key": "ar01", "isa": "ISA 230 ¶14",
     "en": "Signed report, signed financial statements and signed representation letter filed",
     "fr": "Rapport signé, états financiers signés et lettre d'affirmation signée classés"},
    {"key": "ar02", "isa": "ISA 230 A23",
     "en": "Permanent file updated (statutes, key contracts, organisation chart)",
     "fr": "Dossier permanent mis à jour (statuts, contrats importants, organigramme)"},
)

SECTION_TEAM = ("Confirmed by the team", "Confirmé par l'équipe")
SECTION_ARCHIVE = ("Before archiving", "Avant l'archivage")


def answer_key(key):
    """The paper answer that holds a question's Yes or No (the papers' yn convention)."""
    return "q_%s" % key


def note_key(key):
    return "q_%s_x" % key


def extra_section(questions, title, intro):
    """A yes/no section in the papers' own shape: the paper shows the same questions."""
    return {
        "kind": "yn", "titleEn": title[0], "titleFr": title[1], "introEn": intro[0], "introFr": intro[1],
        "items": [{"key": q["key"], "en": q["en"], "fr": q["fr"]} for q in questions],
    }


def _text(value):
    return (value or "").strip()


def question_rows(questions, values, fr=False):
    """Each question with its answer and note. Answered: Yes or No with a note. Green: Yes with a note."""
    rows = []
    for index, question in enumerate(questions, start=1):
        answer = _text(values.get(answer_key(question["key"]))).lower()
        note = _text(values.get(note_key(question["key"])))
        answer = answer if answer in ("yes", "no") else ""
        rows.append({
            "n": index, "key": question["key"], "isa": question["isa"],
            "label": question["fr"] if fr else question["en"],
            "answer": answer, "note": note,
            "answered": bool(answer and note), "ok": answer == "yes" and bool(note),
        })
    return rows


def validate_answer(answer, note):
    """A refusal code, or None. A note is required for every answer, Yes as well as No."""
    if answer not in ("yes", "no"):
        return "invalid-value"
    if not _text(note):
        return "note-required"
    return None


def answers_digest(questions, values):
    """What the partner's "ready to issue" attests to: a later change of an answer voids it."""
    rows = [[q["key"], _text(values.get(answer_key(q["key"]))), _text(values.get(note_key(q["key"])))] for q in questions]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


def ready_to_sign(tool_checks, rows):
    """Everything green: every check of the tool and every question answered Yes with its note."""
    return all(check["ok"] for check in tool_checks) and all(row["ok"] for row in rows)


def assembly_status(report_date, today):
    """The 60-day clock from the report date: days left, and green, amber (under 15) or red (overdue)."""
    if not report_date:
        return None
    deadline = report_date + timedelta(days=ASSEMBLY_DAYS)
    left = (deadline - today).days
    elapsed = max(0, min(ASSEMBLY_DAYS, (today - report_date).days))
    tone = "red" if left < 0 else ("amber" if left < ASSEMBLY_AMBER_DAYS else "green")
    return {
        "deadline": deadline, "days_left": left, "overdue": left < 0, "tone": tone,
        "elapsed_pct": round(100 * elapsed / ASSEMBLY_DAYS),
    }


def retention_end(report_date, years=OHADA_RETENTION_YEARS):
    """Report date plus the period; 29 February lands on 28 February, as Postgres does."""
    year = report_date.year + years
    day = report_date.day
    if report_date.month == 2 and day == 29 and not (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        day = 28
    return date(year, report_date.month, day)


def destruction_refusal(retention_until, held, today):
    """Why an archived file may not be destroyed today, or None. Nothing is ever deleted by itself."""
    if held:
        return "legal-hold"
    if retention_until is None or today < retention_until:
        return "retention-not-reached"
    return None


# ----------------------------------------------------------------------
# The sealed copy
# ----------------------------------------------------------------------

def sha256(data):
    return hashlib.sha256(data).hexdigest()


def seal_index(files):
    """files: [(path, bytes)]. Returns (rows, SHA256SUMS bytes, overall fingerprint). The overall
    fingerprint is the SHA-256 of SHA256SUMS: anyone can recompute it from the files alone."""
    paths = [path for path, _data in files]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate path in the sealed copy")
    rows = [{"path": path, "bytes": len(data), "sha256": sha256(data)} for path, data in sorted(files)]
    sums = "".join("%s  %s\n" % (row["sha256"], row["path"]) for row in rows).encode("utf-8")
    return rows, sums, sha256(sums)


def _csv(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["path", "bytes", "sha256"])
    for row in rows:
        writer.writerow([row["path"], row["bytes"], row["sha256"]])
    return buffer.getvalue().encode("utf-8")


def build_seal(files, header, stamp=(2020, 1, 1, 0, 0, 0)):
    """The sealed copy as ZIP bytes: the files, manifest.json and manifest.csv (one SHA-256 per
    file) and SHA256SUMS. Returns (zip bytes, overall fingerprint, rows)."""
    rows, sums, overall = seal_index(files)
    manifest = dict(header, files=rows, fileCount=len(rows), overallSha256=overall,
                    overallRule="SHA-256 of SHA256SUMS (one line per file: sha256, two spaces, path)")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        def put(path, data):
            info = zipfile.ZipInfo(path, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)

        for path, data in sorted(files):
            put(path, data)
        put("manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))
        put("manifest.csv", _csv(rows))
        put("SHA256SUMS", sums)
    return buffer.getvalue(), overall, rows


def verify_seal(zip_bytes):
    """(ok, overall): every file hashes to its line, and the lines hash to the recorded fingerprint."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        sums = archive.read("SHA256SUMS")
        manifest = json.loads(archive.read("manifest.json"))
        for line in sums.decode("utf-8").splitlines():
            digest, path = line.split("  ", 1)
            if sha256(archive.read(path)) != digest:
                return False, None
        overall = sha256(sums)
        listed = {row["path"] for row in manifest["files"]}
        present = set(archive.namelist()) - {"manifest.json", "manifest.csv", "SHA256SUMS"}
        return overall == manifest["overallSha256"] and listed == present, overall


def safe_name(text, fallback="file"):
    """A path segment that every unzip tool accepts."""
    cleaned = "".join(c if c.isalnum() or c in "._- " else "_" for c in (text or "")).strip(" .")
    return cleaned[:120] or fallback
