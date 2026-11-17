"""Data quality (IPE): every check of every kind of file, on a good file and on a bad one."""
import time

import pytest

from services import ipe_checks as ipe
from services.ipe_checks import EXCEPTIONS, INFO, NA, PASSED, Data

PERIOD = ("2025-01-01", "2025-12-31")


def table(headers, lines, mapping, first_row=2):
    """A file as the model hands it over: columns by header, file line numbers, the mapping."""
    columns = {header: [line[position] for line in lines] for position, header in enumerate(headers)}
    rows = list(range(first_row, first_row + len(lines)))
    return Data(columns, rows, mapping)


def by_code(results):
    return {result["code"]: result for result in results}


def status(results, code):
    return by_code(results)[code]["status"]


def lines(results, code):
    return by_code(results)[code]["lines"]


# ----------------------------------------------------------------------
# References, periods, words
# ----------------------------------------------------------------------

def test_references():
    assert ipe.reference("journal_entries", "pre_audit") == "IPE-GL-PRE"
    assert ipe.reference("trial_balance", "prior_year") == "IPE-TB-PY"
    assert ipe.reference("fixed_asset_register", "final") == "IPE-FA-FIN"
    assert ipe.reference("payroll_register", "subsequent") == "IPE-PR-SUB"
    assert ipe.reference("bank_statement", "post_audit") == "IPE-BK-POST"
    assert {ipe.KIND_CODES[kind] for kind in ipe.KINDS} == {"TB", "GL", "FA", "PR", "AR", "AP", "IN"}
    # bank and supplier statements are no longer uploaded: no checks, no row of the matrix
    assert "bank_statement" not in ipe.KINDS and "supplier_statements" not in ipe.KINDS


def test_periods():
    assert ipe.period_of("pre_audit", "2025-12-31") == PERIOD
    assert ipe.period_of("final", "2025-12-31") == PERIOD
    assert ipe.period_of("prior_year", "2025-12-31") == ("2024-01-01", "2024-12-31")
    assert ipe.period_of("subsequent", "2025-12-31") == ("2026-01-01", "2026-12-31")
    assert ipe.period_of("pre_audit", "2025-06-30") == ("2024-07-01", "2025-06-30")
    assert ipe.period_of("pre_audit", None) == (None, None)
    assert ipe.add_days("2024-02-28", 1) == "2024-02-29"
    assert ipe.add_days("2024-12-31", 1) == "2025-01-01"
    assert ipe.shift_years("2024-02-29", 1) == "2025-02-28"
    assert ipe.day_number("1970-01-01") == 0
    assert ipe.from_day_number(ipe.day_number("2031-07-15")) == "2031-07-15"


def test_amounts_read_with_spaces_and_fcfa():
    assert ipe.amount_text(1234567, "fr") == "1 234 567 FCFA"
    assert ipe.amount_text(1234567, "en") == "1 234 567 FCFA"
    assert ipe.amount_text(-1500.5, "fr") == "(1 500,50 FCFA)"
    assert ipe.amount_text(0.001, "en") == "0 FCFA"


def test_every_kind_has_its_catalogue_and_codes():
    for kind in ipe.KINDS:
        codes = [entry["code"] for entry in ipe.catalogue(kind)]
        assert codes[0] == "%s-01" % ipe.KIND_CODES[kind]
        assert len(codes) == len(set(codes))
        for entry in ipe.catalogue(kind):
            assert entry["en"] and entry["fr"]


def test_papers_map():
    assert ipe.kinds_for_paper("E3.1") == ["journal_entries"]
    assert ipe.kinds_for_paper("E4.1") == ["trial_balance", "ar_open_items"]
    assert ipe.kinds_for_paper("E4.4") == ["trial_balance", "fixed_asset_register"]
    assert "trial_balance" in ipe.kinds_for_paper("E4.20")
    assert ipe.kinds_for_paper("P6.2") == ["trial_balance"]
    assert ipe.kinds_for_paper("C3.1") == []
    assert ipe.papers_for_kind("journal_entries", ["E3.1", "E4.1", "S5.4"]) == ["E3.1", "S5.4"]


def test_chip():
    results = [{"code": "GL-01", "status": PASSED}, {"code": "GL-02", "status": EXCEPTIONS}, {"code": "GL-03", "status": NA}]
    assert ipe.chip(results, False, False, set())["state"] == "not_uploaded"
    assert ipe.chip(results, False, True, set()) == {"state": "to_explain", "tone": "amber", "passed": 1, "applicable": 2, "toExplain": 1}
    assert ipe.chip(results, "reliable", True, {"GL-02"})["state"] == "reliable"
    assert ipe.chip(results, "not_reliable", True, set())["state"] == "not_reliable"
    assert ipe.chip(results, False, True, {"GL-02"})["state"] == "to_conclude"


# ----------------------------------------------------------------------
# General ledger
# ----------------------------------------------------------------------

GL_HEADERS = ["Journal", "Piece", "Date", "Compte", "Libelle compte", "Libelle", "Debit", "Credit", "Saisi par", "Valide par"]
GL_MAPPING = {
    "journalCode": "Journal", "jeNumber": "Piece", "journalDate": "Date", "account": "Compte", "accountName": "Libelle compte",
    "jeDescription": "Libelle", "debit": "Debit", "credit": "Credit", "preparedBy": "Saisi par", "approvedBy": "Valide par",
}
GOOD_GL = [
    ["VE", "VE-0001", "15/01/2025", "411000", "Clients", "Facture 1", "1000", "", "ana", "paul"],
    ["VE", "VE-0001", "15/01/2025", "701000", "Ventes", "Facture 1", "", "1000", "ana", "paul"],
    ["VE", "VE-0002", "20/02/2025", "411000", "Clients", "Facture 2", "500", "", "ana", "paul"],
    ["VE", "VE-0002", "20/02/2025", "701000", "Ventes", "Facture 2", "", "500", "ana", "paul"],
    ["BQ", "BQ-0001", "28/02/2025", "521000", "Banque", "Encaissement", "1000", "", "ana", "paul"],
    ["BQ", "BQ-0001", "28/02/2025", "411000", "Clients", "Encaissement", "", "1000", "ana", "paul"],
]


def gl(lines_, context=None):
    return ipe.run("journal_entries", table(GL_HEADERS, lines_, GL_MAPPING), dict({"period": PERIOD, "timing": "pre_audit", "rows_read": len(lines_), "extraction_date": "2026-01-10"}, **(context or {})))


def test_a_good_ledger_passes():
    results = gl(GOOD_GL)
    failing = {r["code"]: r["lines"][:2] for r in results if r["status"] == EXCEPTIONS}
    assert failing == {}
    assert len(results) == 15
    assert status(results, "GL-15") == INFO
    assert {(line["ref"], line["value"]) for line in lines(results, "GL-15")} >= {("411000", "2025-01"), ("411000", "2025-02")}
    applicable, passed, failing_count = ipe.score(results)
    assert applicable == passed and failing_count == 0


def test_an_unbalanced_entry_and_ledger():
    bad = [list(line) for line in GOOD_GL]
    bad[1][7] = "900"
    results = gl(bad)
    assert status(results, "GL-08") == EXCEPTIONS
    assert lines(results, "GL-08")[0]["ref"] == "VE-0001"
    assert lines(results, "GL-08")[0]["row"] == 2
    assert lines(results, "GL-08")[0]["amount"] == pytest.approx(100)
    assert status(results, "GL-09") == EXCEPTIONS


def test_gaps_and_numbers_used_twice_within_a_journal():
    bad = [list(line) for line in GOOD_GL]
    bad[2][1] = bad[3][1] = "VE-0005"
    bad += [["VE", "VE-0001", "16/03/2025", "411000", "Clients", "Avoir", "", "10", "ana", "paul"],
            ["VE", "VE-0001", "16/03/2025", "701000", "Ventes", "Avoir", "10", "", "ana", "paul"]]
    found = lines(gl(bad), "GL-10")
    texts = [line["en"] for line in found]
    assert "3 number(s) missing: VE-2 to VE-4" in texts or any("missing" in text for text in texts)
    assert any(line["value"] == "VE-2 to VE-4" for line in found)
    assert any(line["ref"] == "VE-0001" and "different dates" in line["en"] for line in found)
    # the bank journal has its own series: no gap there
    assert not any(line["ref"] == "BQ" for line in found)


def test_blank_cells_are_listed_by_column():
    bad = [list(line) for line in GOOD_GL]
    bad[0][5] = ""
    bad[3][2] = ""
    result = by_code(gl(bad))["GL-02"]
    assert result["status"] == EXCEPTIONS and result["count"] == 2
    assert {(line["row"], line["column"]) for line in result["lines"]} == {(2, "Libelle"), (5, "Date")}
    assert "Libelle: 1" in result["note"]["en"]


def test_out_of_period_and_after_extraction():
    bad = [list(line) for line in GOOD_GL]
    bad[4][2] = bad[5][2] = "05/01/2026"
    results = gl(bad)
    assert by_code(results)["GL-04"]["count"] == 2
    assert by_code(results)["GL-13"]["status"] == PASSED
    assert by_code(gl(bad, {"extraction_date": "2026-01-02"}))["GL-13"]["count"] == 2
    assert status(gl(bad, {"extraction_date": None}), "GL-13") == NA


def test_lines_with_both_sides_zero_lines_and_people():
    bad = [list(line) for line in GOOD_GL]
    bad[0][7] = "5"
    bad[1][6] = "5"
    bad[2][6] = "0"
    bad[3][7] = "0"
    bad[4][9] = ""
    results = gl(bad)
    assert by_code(results)["GL-11"]["count"] == 2
    assert by_code(results)["GL-12"]["count"] == 2
    assert by_code(results)["GL-14"]["count"] == 1


def test_values_duplicates_names_and_left_out_lines():
    bad = [list(line) for line in GOOD_GL] + [list(GOOD_GL[0])]
    bad[1][6] = "abc"
    bad[2][4] = "Clients divers"
    bad.append(["VE", "", "15/01/2025", "", "", "", "", "", "", ""])
    bad.append(["", "", "", "", "", "Total", "2500", "2500", "", ""])
    results = gl(bad)
    assert by_code(results)["GL-03"]["count"] == 1
    assert by_code(results)["GL-05"]["count"] == 1
    assert lines(results, "GL-05")[0]["value"] == "2"
    assert by_code(results)["GL-07"]["count"] == 1
    assert by_code(results)["GL-01"]["count"] == 1
    # the file's own total line is set apart and compared with the lines
    down = by_code(results)["GL-06"]
    assert down["status"] == EXCEPTIONS
    assert {line["column"] for line in down["lines"]} == {"Debit"}


def test_a_total_line_that_adds_up():
    good = [list(line) for line in GOOD_GL] + [["", "", "", "", "", "Total", "2500", "2500", "", ""]]
    assert status(gl(good), "GL-06") == PASSED


def test_a_ledger_of_one_amount_column():
    mapping = {"jeNumber": "N", "account": "A", "journalDate": "D", "jeDescription": "L", "amount": "M"}
    data = table(["N", "A", "D", "L", "M"], [["1", "601", "2025-03-01", "x", "100"], ["1", "401", "2025-03-01", "x", "-100"]], mapping)
    results = ipe.run("journal_entries", data, {"period": PERIOD, "rows_read": 2})
    assert status(results, "GL-11") == NA
    assert status(results, "GL-14") == NA
    assert status(results, "GL-08") == PASSED


def test_a_hundred_thousand_line_ledger_is_checked_in_reasonable_time():
    lines_ = []
    for n in range(50000):
        day = "%02d/%02d/2025" % (n % 28 + 1, n % 12 + 1)
        number = "OD-%06d" % (n + 1)
        lines_.append(["OD", number, day, "601000", "Achats", "Achat", "100", "", "ana", "paul"])
        lines_.append(["OD", number, day, "401000", "Fournisseurs", "Achat", "", "100", "ana", "paul"])
    started = time.time()
    results = gl(lines_)
    assert time.time() - started < 60
    assert status(results, "GL-08") == PASSED
    assert status(results, "GL-10") == PASSED


# ----------------------------------------------------------------------
# Trial balance
# ----------------------------------------------------------------------

def tb(rows_, context=None, closing=False):
    """rows: (account, label, od, oc, d, c[, closing])."""
    headers = ["Compte", "Libelle", "OD", "OC", "D", "C"] + (["Solde"] if closing else [])
    mapping = {"account": "Compte", "label": "Libelle", "openingDebit": "OD", "openingCredit": "OC", "debit": "D", "credit": "C"}
    if closing:
        mapping["closing"] = "Solde"
    columns = {header: [row[position] for row in rows_] for position, header in enumerate(headers)}
    columns["account"] = [row[0] for row in rows_]
    columns["label"] = [row[1] for row in rows_]
    for key, position in (("_od", 2), ("_oc", 3), ("_d", 4), ("_c", 5)):
        columns[key] = [float(row[position] or 0) for row in rows_]
    data = Data(columns, list(range(2, 2 + len(rows_))), mapping)
    return ipe.run("trial_balance", data, dict({"rows_read": len(rows_), "left_out": [], "prior_closings": None}, **(context or {})))


GOOD_TB = [
    ("101000", "Capital", "0", "5000", "0", "0"),
    ("231000", "Bâtiments", "4000", "0", "0", "0"),
    ("411000", "Clients", "800", "0", "1000", "900"),
    ("401000", "Fournisseurs", "0", "500", "400", "500"),
    ("521000", "Banque", "700", "0", "900", "900"),
    ("601000", "Achats", "0", "0", "2000", "0"),
    ("701000", "Ventes", "0", "0", "0", "2000"),
]


def test_a_good_trial_balance_passes():
    results = tb(GOOD_TB)
    assert [r["code"] for r in results if r["status"] == EXCEPTIONS] == []
    assert status(results, "TB-06") == NA
    assert status(results, "TB-10") == NA
    assert status(results, "TB-11") == PASSED
    assert status(results, "TB-04") == INFO


def test_an_unbalanced_trial_balance_and_bad_codes():
    bad = list(GOOD_TB) + [("A47", "", "0", "0", "100", "0"), ("471000", "", "0", "0", "50", "0"), ("411000", "Clients bis", "0", "0", "0", "0")]
    results = tb(bad)
    assert status(results, "TB-05") == EXCEPTIONS
    assert by_code(results)["TB-07"]["lines"][0]["ref"] == "411000"
    assert [line["ref"] for line in lines(results, "TB-08")] == ["A47"]
    assert {line["ref"] for line in lines(results, "TB-09")} == {"A47", "471000"}
    assert status(results, "TB-11") == INFO
    assert [line["ref"] for line in lines(results, "TB-11")] == ["471000"]


def test_the_trial_balance_adds_across_and_ties_to_last_year():
    rows_ = [row + (str(float(row[2]) - float(row[3]) + float(row[4]) - float(row[5])),) for row in GOOD_TB]
    rows_[2] = rows_[2][:6] + ("999",)
    prior = {"101000": -5000, "231000": 4000, "411000": 800, "401000": -500, "521000": 600}
    results = tb(rows_, {"prior_closings": prior}, closing=True)
    assert [line["ref"] for line in lines(results, "TB-06")] == ["411000"]
    assert [line["ref"] for line in lines(results, "TB-10")] == ["521000"]


def test_the_trial_balance_lines_left_out_and_its_total_line():
    left = [{"row": 9, "text": "", "total": False, "amounts": {"debit": "100"}},
            {"row": 10, "text": "TOTAL", "total": True, "amounts": {"debit": "4300", "credit": "4200"}}]
    results = tb(GOOD_TB, {"left_out": left, "rows_read": len(GOOD_TB) + 2})
    assert by_code(results)["TB-01"]["count"] == 1
    assert by_code(results)["TB-04"]["count"] == 1
    assert lines(results, "TB-04")[0]["column"] == "C"


# ----------------------------------------------------------------------
# Fixed assets
# ----------------------------------------------------------------------

FA_HEADERS = ["N", "Desc", "Cat", "Date", "Taux", "Brut", "Amort", "VNC", "Ouv", "Dot", "Cession"]
FA_MAPPING = {"item": "N", "itemDescription": "Desc", "category": "Cat", "acquisitionDate": "Date", "depreciationRate": "Taux",
              "amount": "Brut", "depreciation": "Amort", "nbv": "VNC", "openingNbv": "Ouv", "charge": "Dot", "disposalDate": "Cession"}
GOOD_FA = [
    ["IM1", "Camion", "Transport", "01/01/2023", "20", "1000000", "600000", "400000", "600000", "200000", ""],
    ["IM2", "Ordinateur", "Bureau", "01/07/2025", "25", "400000", "50000", "350000", "0", "50000", ""],
]


def fa(lines_):
    data = table(FA_HEADERS, lines_, FA_MAPPING)
    return ipe.run("fixed_asset_register", data, {"period": PERIOD, "rows_read": len(lines_)})


def test_a_good_register_passes():
    results = fa(GOOD_FA)
    failing = {r["code"]: r["lines"] for r in results if r["status"] == EXCEPTIONS}
    # IM2 was acquired in the year, without an additions column: the roll forward misses it
    assert set(failing) == {"FA-09"}
    assert [line["row"] for line in failing["FA-09"]] == [3]


def test_a_bad_register():
    bad = [list(line) for line in GOOD_FA] + [["IM1", "Bureau", "Bureau", "01/02/2026", "150", "100", "200", "-100", "0", "90", "01/01/2024"]]
    results = fa(bad)
    assert by_code(results)["FA-04"]["count"] == 1
    assert by_code(results)["FA-07"]["count"] == 1
    assert by_code(results)["FA-10"]["count"] == 1
    assert by_code(results)["FA-11"]["count"] == 1
    assert by_code(results)["FA-12"]["count"] == 1
    bad = [list(line) for line in GOOD_FA]
    bad[0][7] = "300000"
    bad[0][9] = "250000"
    results = fa(bad)
    assert [line["row"] for line in lines(results, "FA-08")] == [2]
    assert lines(results, "FA-13")[0]["expected"] == pytest.approx(200000)


# ----------------------------------------------------------------------
# Payroll
# ----------------------------------------------------------------------

PR_HEADERS = ["Mat", "Nom", "Mois", "Base", "Primes", "Brut", "IRPP", "CNPS", "Net", "Embauche", "Sortie"]
PR_MAPPING = {"party": "Mat", "partyName": "Nom", "period": "Mois", "baseSalary": "Base", "allowances": "Primes", "amount": "Brut",
              "incomeTax": "IRPP", "socialEmployee": "CNPS", "net": "Net", "hireDate": "Embauche", "leavingDate": "Sortie"}
GOOD_PR = [
    ["E1", "Ana", "2025-01", "300000", "50000", "350000", "20000", "14700", "315300", "01/03/2020", ""],
    ["E1", "Ana", "2025-02", "300000", "50000", "350000", "20000", "14700", "315300", "01/03/2020", ""],
    ["E2", "Paul", "2025-01", "200000", "0", "200000", "8000", "8400", "183600", "01/01/2024", "31/10/2025"],
]


def pr(lines_):
    return ipe.run("payroll_register", table(PR_HEADERS, lines_, PR_MAPPING), {"period": PERIOD, "rows_read": len(lines_)})


def test_a_good_payroll_passes():
    assert [r["code"] for r in pr(GOOD_PR) if r["status"] == EXCEPTIONS] == []


def test_a_bad_payroll():
    bad = [list(line) for line in GOOD_PR] + [["E2", "Paul", "2025-01", "200000", "0", "100", "0", "0", "150", "01/01/2026", "01/01/2019"],
                                              ["E3", "Zoé", "2026-02", "0", "0", "0", "0", "0", "0", "", ""]]
    results = pr(bad)
    assert by_code(results)["PR-04"]["count"] == 1
    assert by_code(results)["PR-08"]["count"] == 1
    assert by_code(results)["PR-09"]["count"] == 1
    assert by_code(results)["PR-10"]["count"] == 1
    assert by_code(results)["PR-11"]["count"] == 1
    assert by_code(results)["PR-12"]["count"] == 1
    assert by_code(results)["PR-13"]["count"] == 1
    assert by_code(results)["PR-14"]["count"] == 1


# ----------------------------------------------------------------------
# Receivables and payables
# ----------------------------------------------------------------------

AR_HEADERS = ["Client", "Nom", "Facture", "Date", "Type", "Montant"]
AR_MAPPING = {"party": "Client", "partyName": "Nom", "reference": "Facture", "date": "Date", "transactionType": "Type", "amount": "Montant"}
GOOD_AR = [
    ["C1", "Alpha", "FA-100", "15/12/2025", "Facture", "1000"],
    ["C1", "Alpha", "FA-101", "16/12/2025", "Facture", "500"],
    ["C2", "Beta", "AV-7", "10/11/2025", "Avoir", "-200"],
]


def ar(lines_, kind="ar_open_items"):
    return ipe.run(kind, table(AR_HEADERS, lines_, AR_MAPPING), {"period": PERIOD, "rows_read": len(lines_), "aged_before": "2024-12-31"})


def test_good_open_items_pass():
    for kind in ("ar_open_items", "ap_open_items"):
        assert [r["code"] for r in ar(GOOD_AR, kind) if r["status"] == EXCEPTIONS] == []


def test_bad_receivables():
    bad = [list(line) for line in GOOD_AR] + [
        ["C1", "Alpha", "FA-104", "15/01/2026", "Facture", "-50"],
        ["C3", "", "FA-100", "01/06/2023", "Avoir", "80"],
        ["C2", "Beta SA", "FA-105", "01/12/2025", "Facture", "0"],
    ]
    results = ar(bad)
    assert by_code(results)["AR-04"]["count"] == 1
    assert by_code(results)["AR-07"]["count"] == 2
    assert by_code(results)["AR-08"]["count"] == 1
    assert status(results, "AR-09") == INFO
    assert any("FA-102 to FA-103" in line["value"] for line in lines(results, "AR-09"))
    assert status(results, "AR-10") == INFO and lines(results, "AR-10")[0]["row"] == 6
    assert by_code(results)["AR-11"]["count"] == 2
    assert by_code(results)["AR-12"]["count"] == 1
    assert status(results, "AR-13") == INFO
    # payables: the same invoice number for two suppliers is no duplicate
    payables = by_code(ar(bad, "ap_open_items"))
    assert payables["AP-08"]["count"] == 0


# ----------------------------------------------------------------------
# Inventory
# ----------------------------------------------------------------------

def test_inventory():
    headers = ["Code", "Desc", "Lieu", "Qte", "PU", "Montant"]
    mapping = {"item": "Code", "itemDescription": "Desc", "location": "Lieu", "quantity": "Qte", "unitPrice": "PU", "amount": "Montant"}
    good = [["A1", "Vis", "Douala", "10", "5", "50"], ["A1", "Vis", "Yaoundé", "2", "5", "10"]]
    results = ipe.run("inventory_listing", table(headers, good, mapping), {"rows_read": 2})
    assert [r["code"] for r in results if r["status"] == EXCEPTIONS] == []
    bad = good + [["A1", "Vis M8", "Douala", "-1", "5", "-7"], ["B2", "Ecrou", "Douala", "4", "0", "0"]]
    results = by_code(ipe.run("inventory_listing", table(headers, bad, mapping), {"rows_read": 4}))
    assert results["IN-06"]["count"] == 1
    assert results["IN-07"]["count"] == 1
    assert results["IN-08"]["count"] == 1
    assert results["IN-09"]["count"] == 1
    assert results["IN-10"]["status"] == INFO
    assert "Qte 15;" in results["IN-05"]["note"]["en"]


def test_a_check_without_its_columns_is_not_applicable():
    data = table(["N", "Desc", "Brut"], [["IM1", "Camion", "100"]], {"item": "N", "itemDescription": "Desc", "amount": "Brut"})
    results = ipe.run("fixed_asset_register", data, {"period": PERIOD, "rows_read": 1})
    for code in ("FA-08", "FA-09", "FA-11", "FA-12", "FA-13"):
        assert status(results, code) == NA
