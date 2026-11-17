"""No abbreviation in the English text a user reads (owner-approved sweep of 2026-11-17).

Read without Odoo: the English source of every screen text (the msgids of each addon's fr.po, which
cover the Python, JavaScript and XML strings and the data records), the task templates and other
data files, and the English keys of the working-paper definitions. French text is not checked.
Kept on purpose: ISA, ISQM, IESBA, IAASB, IFRS, IAS, OHADA, SYSCOHADA, IT, VAT, MSP/ASP.
"""
import csv
import glob
import json
import os
import re

import pytest

ADDONS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The abbreviations the owner asked to spell out, as whole words.
LISTED = re.compile(
    r"(?<![\w/])(Prelim\.?|Rep\.|FS|vs\.?|SCOTs?|WCGWs?|FSCPs?|ITGCs?|ToCs?|ToDs?|JEs?|EQRs?|TCWG|NOCLAR|SAD|CRAs?|IR|CR|"
    r"PBC|TB|GL|AP|RPs?|KAMs?|HR|IPE|CEO|CFO|MD|PCA|DG|PDG|AGO|AGE|AGM|EGM|AUSCGIE|TFT|DSF|CNPS|RCCM|Docs|Ref\.?|Pct|"
    r"Recon|Min\.?|Q[0-9]{1,2})(?![\w/])"
    r"|PP&E|N/A|n/a|(?<=\w) & (?=\w)"
)


CODE_COLUMNS = ("id", "code", "key", "fs_ref", "section_code", "account_prefix", "source")


def allowed(text, hit):
    """Not an abbreviation: a token the user types, or a code of the SYSCOHADA model statements."""
    if hit == "n/a" and "for lines with no date" in text:
        return True  # the value typed in the general ledger console for an undated line
    if text.startswith(("C.2 —", "C.6 —")) and hit in ("AP", "TB", "RP"):
        return True  # line codes of the SYSCOHADA balance sheet and income statement (E6.10)
    return False


def _po_msgids(path):
    out, parts, active = [], None, False
    for line in open(path, encoding="utf-8").read().split("\n"):
        if line.startswith("msgid "):
            parts, active = [json.loads(line[6:])], True
        elif active and line.startswith('"'):
            parts.append(json.loads(line))
        else:
            if active and parts and "".join(parts):
                out.append("".join(parts))
            active = False
    return out


def _english(node, out, english=False):
    if isinstance(node, dict):
        for key, value in node.items():
            is_en = (key.endswith("En") or key in ("en", "label", "title")) and not key.endswith("Fr")
            if isinstance(value, str):
                if is_en or english:
                    out.append(value)
            else:
                _english(value, out, is_en or (english and not key.endswith("Fr")))
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, str):
                if english:
                    out.append(value)
            else:
                _english(value, out, english)


def _texts():
    texts = []
    for path in sorted(glob.glob(os.path.join(ADDONS, "*", "i18n", "fr.po"))):
        texts += [("%s fr.po" % os.path.basename(os.path.dirname(os.path.dirname(path))), t) for t in _po_msgids(path)]
    for path in sorted(glob.glob(os.path.join(ADDONS, "*", "data", "*.csv"))):
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for key, value in row.items():
                    # codes are not text: a task code, a SYSCOHADA line (fs_ref "AP"), a section, an account prefix
                    if not key or key in CODE_COLUMNS or not value or key.endswith(("id", "_fr")):
                        continue
                    texts.append((os.path.basename(path), value))
    papers = os.path.join(ADDONS, "ea_audit_papers", "data")
    files = [p for p in glob.glob(os.path.join(papers, "papers", "*.json")) if not p.endswith("index.json")]
    files += [os.path.join(papers, name) for name in ("group_defaults.json", "legal_forms.json", "standards_refs.json", "isa_links.json")]
    files.append(os.path.join(ADDONS, "ea_audit_tools", "data", "procedure_library.json"))
    for path in sorted(files):
        found = []
        with open(path, encoding="utf-8") as fh:
            _english(json.load(fh), found)
        texts += [(os.path.basename(path), t) for t in found]
    with open(os.path.join(papers, "papers_legacy_2026_11_17.json"), encoding="utf-8") as fh:
        for entry in json.load(fh)["papers"].values():
            texts += [("papers_legacy", t) for t in entry["conclEn"]]
    return texts


TEXTS = _texts()


def test_the_scan_reads_every_source():
    sources = {source.split()[0] for source, _text in TEXTS}
    assert {"ea_audit_core", "ea_audit_tools", "ea_audit_papers", "ea.audit.task.template.csv", "S4.2.json"} <= sources
    assert len(TEXTS) > 10000


@pytest.mark.parametrize("sample", [
    "Design & Execute ITGC Tests", "Q4 Part of a group", "PBC requests", "Equity vs Half-Capital", "N/A",
    "the AUSCGIE", "Final FS Review", "Ref.",
])
def test_the_pattern_catches_the_listed_abbreviations(sample):
    assert LISTED.search(sample)


@pytest.mark.parametrize("sample", ["ISA 315", "IT general controls", "SYSCOHADA", "VAT", "IFRS 16", "OHADA Uniform Act", "MSP"])
def test_kept_names_pass(sample):
    assert not LISTED.search(sample)


def test_no_listed_abbreviation_in_english_display_text():
    left = sorted({
        "%s: [%s] %s" % (source, m.group(0).strip(), text[:100])
        for source, text in TEXTS
        for m in LISTED.finditer(text)
        if not allowed(text, m.group(0).strip())
    })
    assert not left, "\n".join(left[:40])
