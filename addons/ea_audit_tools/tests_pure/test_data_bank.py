"""The Data bank and EAGLA tiles (owner's mock-ups of 18/11/2026), read from the addon's files:
seven upload tiles with no "analyzer", bank and supplier statements gone from every screen, and
financial analysis and analytical procedures moved to EAGLA."""
import csv
import glob
import json
import os
import re

import pytest

from services import data_bank
from services import ipe_checks
from services.subledger_kinds import SUB_LEDGER_KINDS

ADDON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ADDON, "data", "ea.audit.tool.tile.csv"), encoding="utf-8", newline="") as handle:
    TILES = {row["id"]: row for row in csv.DictReader(handle)}
BY_CODE = {row["code"]: row for row in TILES.values()}


def _po(path):
    """[(references, msgstr)] of a fr.po, read without polib (the pure tests have no polib)."""
    entries = []
    with open(path, encoding="utf-8") as handle:
        blocks = handle.read().split("\n\n")
    for block in blocks:
        refs, msgstr, active = [], [], False
        for line in block.split("\n"):
            if line.startswith("#: "):
                refs.append(line[3:])
            elif line.startswith("msgstr "):
                msgstr, active = [json.loads(line[7:])], True
            elif active and line.startswith('"'):
                msgstr.append(json.loads(line))
        entries.append((refs, "".join(msgstr)))
    return entries


PO = _po(os.path.join(ADDON, "i18n", "fr.po"))


def french(ref):
    found = [msgstr for refs, msgstr in PO if ref in refs]
    assert len(found) == 1, (ref, found)
    return found[0]


def test_the_data_bank_holds_seven_upload_tiles_in_order():
    shown = sorted((row for row in TILES.values() if row["section"] == "analyzers"), key=lambda row: int(row["sequence"]))
    assert [row["code"] for row in shown] == [tile[0] for tile in data_bank.TILES]
    for code, kind, name, name_fr, line, line_fr in data_bank.TILES:
        row = BY_CODE[code]
        assert (row["name"], row["description"]) == (name, line)
        assert french("model:ea.audit.tool.tile,name:ea_audit_tools.%s" % row["id"]) == name_fr
        assert french("model:ea.audit.tool.tile,description:ea_audit_tools.%s" % row["id"]) == line_fr
        assert row["method"], code
    assert [tile[2] for tile in data_bank.TILES] == [
        "Trial balance", "General ledger", "Accounts receivable ledger", "Accounts payable ledger",
        "Inventory ledger", "Fixed assets register", "Payroll sub-ledger",
    ]
    assert [tile[3] for tile in data_bank.TILES] == [
        "Balance générale", "Grand livre", "Grand livre clients", "Grand livre fournisseurs",
        "Grand livre des stocks", "Registre des immobilisations", "Livre de paie",
    ]


def test_no_tile_shown_says_analyzer():
    for row in TILES.values():
        if row["section"] != "retired":
            assert not re.search(r"analy[sz]er", row["name"] + row["description"], re.I), row["code"]


def test_the_data_bank_and_eagla_tiles():
    bank = TILES["tile_data_analytics"]
    assert (bank["name"], bank["section"]) == ("Data bank", "hub")
    assert french("model:ea.audit.tool.tile,name:ea_audit_tools.tile_data_analytics") == "Banque de données"
    eagla = TILES["tile_gl_console"]
    assert (eagla["name"], eagla["method"], eagla["section"]) == ("EAGLA", "action_tool_eagla", "hub")
    assert french("model:ea.audit.tool.tile,description:ea_audit_tools.tile_gl_console") == "Analyse augmentée du grand livre Elite Advisors."


@pytest.mark.parametrize("code", ["an-bank", "an-supplier", "an-financial", "an-analytics", "an-ipe"])
def test_tiles_that_left_the_data_bank_are_retired_not_deleted(code):
    assert BY_CODE[code]["section"] == "retired"


def test_bank_and_supplier_statements_are_no_upload_choice():
    assert data_bank.UPLOAD_KINDS == [kind for kind in SUB_LEDGER_KINDS if kind not in ("bank_statement", "supplier_statements")]
    assert set(data_bank.KIND_BY_TILE.values()) == set(data_bank.UPLOAD_KINDS) | {"trial_balance"}
    # the records kept from before stay readable: the kinds remain known to the models
    assert "bank_statement" in SUB_LEDGER_KINDS and "supplier_statements" in SUB_LEDGER_KINDS
    with open(os.path.join(ADDON, "wizards", "import_wizard.py"), encoding="utf-8") as handle:
        assert "fields.Selection(UPLOAD_KIND_SELECTION" in handle.read()


def test_no_screen_offers_the_removed_kinds():
    assert not set(data_bank.RETIRED_KINDS) & set(ipe_checks.KINDS)
    assert not any(kind in ipe_checks.PAPERS for kind in data_bank.RETIRED_KINDS)
    screens = glob.glob(os.path.join(ADDON, "views", "*.xml")) + glob.glob(os.path.join(ADDON, "static", "src", "**", "*.*"), recursive=True)
    for path in screens:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for word in ("supplier_statements", "bank_statement", "action_tool_bank", "action_tool_supplier", "action_open_supplier_recon"):
            assert word not in text, (os.path.basename(path), word)
    with open(os.path.join(ADDON, "models", "analyzer.py"), encoding="utf-8") as handle:
        source = handle.read()
    assert "def action_tool_bank" not in source and "def action_tool_supplier" not in source


def test_the_chip_says_what_was_uploaded():
    labels = {"pre_audit": "Pre-audit", "prior_year": "Prior year", "post_audit": "Post-audit"}
    assert data_bank.chip([], labels) == "Not uploaded"
    assert data_bank.chip([], labels, fr=True) == "Non importé"
    assert data_bank.chip(["pre_audit"], labels) == "1 file: Pre-audit"
    assert data_bank.chip(["post_audit", "pre_audit", "prior_year", "pre_audit"], labels) == "4 files: Prior year, Pre-audit, Post-audit"
    assert data_bank.chip(["pre_audit", "pre_audit"], {"pre_audit": "Préaudit"}, fr=True) == "2 fichiers : Préaudit"
