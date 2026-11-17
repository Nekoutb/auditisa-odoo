"""The matching step of an import: mandatory fields alone or one of several, the guess from the
file, the remembered matching, and the reading options a person sets over the readers' guesses."""
from services.amount import parse_amount
from services.dataset_mapping import JE_KEY, auto_map, encode_je_key
from services.gl_line import parse_date_iso
from services.import_matching import (
    IMPORT_KINDS, TB_KIND, amount_check, apply_reading_options, clean_mapping, detect_mapping, fields_of, forced_amount_text,
    forced_date_text, found_date_format, found_decimal, gl_population, mandatory_marks, missing_fields, remember_payload,
    required_keys, starred_keys,
)
from services.subledgers import parse_csv
from services.tb import alias_tb_mapping, infer_tb_mapping, left_out_rows

LEDGER = """Compte;N° écriture;Libellé;Date;Débit;Crédit;Journal
411000;VE001;Facture 1;15/01/2025;1 000,00;;VE
701000;VE001;Facture 1;15/01/2025;;1 000,00;VE
601000;;Sans numero;03/03/2025;50,00;;OD
411000;VE009;Hors periode;15/01/2024;10,00;;VE
"""
GL = {"account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "debit": "Débit", "credit": "Crédit"}


def keys(missing):
    return [entry["key"] for entry in missing]


def test_nine_kinds_each_with_its_fields():
    assert len(IMPORT_KINDS) == 9 and IMPORT_KINDS[0] == TB_KIND
    assert [field["key"] for field in fields_of(TB_KIND)][:2] == ["account", "label"]
    for kind in IMPORT_KINDS:
        assert all(field["en"] and field["fr"] for field in fields_of(kind)), kind
        assert required_keys(kind) or kind == TB_KIND and required_keys(kind) == ["account"]


def test_a_trial_balance_states_its_amounts_one_of_three_ways():
    assert keys(missing_fields(TB_KIND, {})) == ["account", "amounts"]
    assert keys(missing_fields(TB_KIND, {"account": "A", "debit": "D"})) == ["amounts"]
    assert keys(missing_fields(TB_KIND, {"account": "A", "closingDebit": "D"})) == ["amounts"]
    for amounts in ({"debit": "D", "credit": "C"}, {"closingDebit": "D", "closingCredit": "C"}, {"closing": "S"}):
        assert missing_fields(TB_KIND, dict(amounts, account="A")) == []
    assert missing_fields(TB_KIND, {"account": "A", "closing": " "})[0]["alternatives"] == [["debit", "credit"], ["closingDebit", "closingCredit"], ["closing"]]


def test_a_ledger_needs_its_five_with_the_amount_and_the_entry_one_way_or_the_other():
    assert keys(missing_fields("journal_entries", {})) == ["account", "jeDescription", "journalDate", "entry", "amount"]
    assert missing_fields("journal_entries", GL) == []
    single = {key: header for key, header in GL.items() if key not in ("debit", "credit")}
    assert keys(missing_fields("journal_entries", dict(single, debit="Débit"))) == ["amount"]
    assert missing_fields("journal_entries", dict(single, amount="Montant")) == []
    composite = {key: header for key, header in GL.items() if key != "jeNumber"}
    assert keys(missing_fields("journal_entries", composite)) == ["entry"]
    assert missing_fields("journal_entries", dict(composite, **{JE_KEY: encode_je_key(["Journal", "N° écriture"])})) == []


def test_the_other_kinds_follow_the_catalogue():
    assert keys(missing_fields("bank_statement", {"date": "Date"})) == ["description", "amount"]
    assert keys(missing_fields("supplier_statements", {"party": "F", "amount": "M"})) == []
    assert "paymentTerms" not in required_keys("ar_open_items")


def test_the_marks_follow_what_is_matched():
    assert starred_keys(TB_KIND) == {"account", "debit", "credit"}
    assert starred_keys("journal_entries") == {"account", "jeNumber", "jeDescription", "journalDate", "amount"}
    assert mandatory_marks(TB_KIND, {"account": "A", "closing": "S", "label": "L"}) == {"account", "closing"}
    assert mandatory_marks(TB_KIND, {"account": "A", "debit": "D", "credit": "C", "closing": "S"}) == {"account", "debit", "credit"}
    assert mandatory_marks("journal_entries", GL) == {"account", "jeDescription", "journalDate", "jeNumber", "debit", "credit"}


def test_a_matching_names_only_columns_the_file_holds():
    headers = ["Compte", "Débit", "Crédit", "Journal", "N° écriture"]
    assert clean_mapping(TB_KIND, {"account": "Compte", "debit": "Nowhere", "other": "Débit"}, headers) == {"account": "Compte"}
    kept = clean_mapping("journal_entries", {"account": "Compte", JE_KEY: encode_je_key(["Journal", "N° écriture"])}, headers)
    assert kept == {"account": "Compte", JE_KEY: encode_je_key(["Journal", "N° écriture"])}
    assert JE_KEY not in clean_mapping("journal_entries", {JE_KEY: encode_je_key(["Journal", "Absent"])}, headers)


def test_the_aliases_guess_as_they_did():
    headers = ["Compte", "Libellé", "Solde ouverture débit", "Solde ouverture crédit", "Mouvement débit", "Mouvement crédit"]
    assert alias_tb_mapping(headers) == infer_tb_mapping(headers)
    assert alias_tb_mapping(["Mvt D", "Mvt C"]) == {}
    assert alias_tb_mapping(headers, {"label": "Compte"})["label"] == "Compte"
    seeded = auto_map("journal_entries", ["Compte", "Date", "Montant"], {"account": "Montant"})
    assert seeded == {"account": "Montant", "journalDate": "Date"}
    assert auto_map("journal_entries", ["Compte", "Date"]) == {"account": "Compte", "journalDate": "Date"}


def test_the_guess_of_a_trial_balance():
    table = parse_csv("Compte;Libellé;Mouvement débit;Mouvement crédit;Notes\n411000;Clients;10;0;x\n701000;Ventes;0;10;\n")
    mapping, sources = detect_mapping(TB_KIND, table)
    assert mapping == {"account": "Compte", "label": "Libellé", "debit": "Mouvement débit", "credit": "Mouvement crédit"}
    assert set(sources.values()) == {"alias"} and "Notes" not in sources


def test_unknown_titles_give_the_account_and_the_description_by_their_values_and_no_amount():
    table = parse_csv("N°;Nom;Mvt D;Mvt C\n101000;Capital;0;5000\n521000;Banque;5000;0\n411000;Clients;700;700\n")
    mapping, sources = detect_mapping(TB_KIND, table)
    assert mapping == {"account": "N°", "label": "Nom"}
    assert sources == {"N°": "data", "Nom": "data"}
    assert keys(missing_fields(TB_KIND, mapping)) == ["amounts"]


def test_a_remembered_matching_comes_first_and_keeps_what_was_set_aside():
    table = parse_csv("N°;Désignation;Mvt D;Mvt C\n101000;Capital;0;5000\n521000;Banque;5000;0\n")
    chosen = {"account": "N°", "debit": "Mvt D", "credit": "Mvt C"}
    remembered = remember_payload(table["headers"], chosen)
    assert remembered == {"fields": chosen, "skipped": ["Désignation"]}
    mapping, sources = detect_mapping(TB_KIND, table, remembered)
    assert mapping == chosen
    assert set(sources.values()) == {"remembered"}
    # the titles are compared as the aliases compare them, and a column that is gone is not matched
    other = parse_csv("n° ;DESIGNATION;mvt d\n101000;Capital;0\n521000;Banque;5000\n")
    mapping, _sources = detect_mapping(TB_KIND, other, remembered)
    assert mapping == {"account": "n°", "debit": "mvt d"}
    # nothing remembered for these titles: the aliases alone
    plain = parse_csv("Compte;Libellé;Débit;Crédit\n1;a;0;1\n2;b;1;0\n")
    assert detect_mapping(TB_KIND, plain, remembered)[0] == detect_mapping(TB_KIND, plain)[0]


def test_a_ledgers_entry_columns_are_remembered():
    table = parse_csv(LEDGER)
    chosen = dict({key: header for key, header in GL.items() if key != "jeNumber"}, **{JE_KEY: encode_je_key(["Journal", "N° écriture"])})
    remembered = remember_payload(table["headers"], chosen)
    assert remembered["skipped"] == []
    mapping, _sources = detect_mapping("journal_entries", table, remembered)
    assert mapping[JE_KEY] == encode_je_key(["Journal", "N° écriture"])
    assert missing_fields("journal_entries", mapping) == []


def test_the_decimal_mark_a_person_chooses():
    assert parse_amount("1,500") == 1500 and parse_amount("1.500") == 1500
    assert parse_amount(forced_amount_text("1,500", "comma")) == 1.5
    assert parse_amount(forced_amount_text("1.500", "point")) == 1.5
    assert parse_amount(forced_amount_text("1.500", "comma")) == 1500
    assert parse_amount(forced_amount_text("1,500", "point")) == 1500
    assert parse_amount(forced_amount_text("1.234,567", "comma")) == 1234.567
    assert parse_amount(forced_amount_text("(1 234,50)", "comma")) == -1234.5
    assert parse_amount(forced_amount_text("1 234,5 XAF", "comma")) == 1234.5
    assert parse_amount(forced_amount_text("1,234.5-", "point")) == -1234.5
    assert forced_amount_text("n/d", "comma") == "n/d"
    assert forced_amount_text(None, "comma") is None and forced_amount_text(12.5, "comma") == 12.5


def test_the_date_order_a_person_chooses():
    assert parse_date_iso("03/04/2025") == "2025-04-03"
    assert forced_date_text("03/04/2025", "mdy") == "2025-03-04"
    assert forced_date_text("03/04/2025", "dmy") == "2025-04-03"
    assert forced_date_text("25-12-31", "ymd") == "2025-12-31"
    assert forced_date_text("31/02/2025", "dmy") == "31/02/2025"
    assert forced_date_text("someday", "dmy") == "someday"


def test_the_options_touch_only_the_matched_columns_and_nothing_when_automatic():
    table = parse_csv(LEDGER.replace("1 000,00", "1,500").replace("15/01/2025", "03/04/2025"))
    untouched = [dict(row) for row in table["rows"]]
    assert [dict(row) for row in apply_reading_options(table, "journal_entries", GL)["rows"]] == untouched
    apply_reading_options(table, "journal_entries", GL, decimal="comma", date_format="mdy")
    first = table["rows"][0]
    assert parse_amount(first["Débit"]) == 1.5 and first["Date"] == "2025-03-04"
    assert first["Compte"] == "411000" and first["Journal"] == "VE"
    assert found_decimal(parse_csv(LEDGER), ["Débit", "Crédit"]) == "comma"
    assert found_decimal(parse_csv(LEDGER), ["Compte"]) is None
    assert found_date_format(parse_csv(LEDGER), ["Date"]) == "dmy"
    assert found_date_format(parse_csv(LEDGER.replace("15/01/2025", "2025-01-15")), ["Date"]) == "ymd"


def test_a_separator_chosen_over_the_one_the_lines_suggest():
    text = "a;b,c;d\n1;2,3;4\n5;6,7;8\n"
    assert parse_csv(text)["headers"] == ["a", "b,c", "d"]
    assert parse_csv(text, True, ",")["headers"] == ["a;b", "c;d"]
    assert parse_csv(text, True, "nonsense")["headers"] == ["a", "b,c", "d"]


def test_the_check_of_a_ledger_reads_the_file_as_the_projection_will():
    found = gl_population(parse_csv(LEDGER), GL, "2025-01-01", "2025-12-31")
    assert (found["fileRows"], found["lines"], found["leftOut"]) == (4, 3, [4])
    assert (found["totalDebit"], found["totalCredit"]) == (1010, 1000)
    assert found["balanced"] is False
    assert found["unbalancedEntries"] == [{"entry": "VE009", "date": "2024-01-15", "debit": 10, "credit": 0, "rows": [5], "difference": 10}]
    balanced = gl_population(parse_csv(LEDGER + "701000;VE009;Hors periode;15/01/2024;;10,00;VE\n"), GL, "2025-01-01", "2025-12-31")
    assert balanced["balanced"] is True and balanced["unbalancedEntries"] == []
    status = {check["key"]: check["status"] for check in found["validation"]["checks"]}
    assert status["mandatory-mapped"] == "passed"
    assert status["debit-credit-reconcile"] == "failed" and status["entries-balance"] == "failed"
    assert status["dates-in-period"] == "warning" and status["row-count"] == "warning"


def test_the_check_of_a_trial_balance_names_the_rows_left_out():
    table = parse_csv("Compte;Libellé;Débit;Crédit\n411000;Clients;10;0\nTOTAL CLASSE 4;;10;0\n;;;\nNotes;;;\n701000;Ventes;0;10\n")
    assert left_out_rows(table, infer_tb_mapping(table["headers"])) == [
        {"row": 3, "text": "TOTAL CLASSE 4"}, {"row": 4, "text": ""}, {"row": 5, "text": "Notes"},
    ]


def test_the_check_of_a_sub_ledger():
    table = parse_csv("Client;Montant\nA;100\nB;n/d\nC;\nD;250,50\n")
    found = amount_check(table, {"amount": "Montant"})
    assert (found["fileRows"], found["total"], found["header"]) == (4, 350.5, "Montant")
    assert found["unreadable"] == [{"row": 3, "value": "n/d"}]
    assert amount_check(table, {})["total"] is None


# ---- the fixed asset register's mandatory columns (owner's request of 2026-11-16) ----------

def test_the_register_needs_its_category_acquisition_date_and_rate():
    from services.import_matching import missing_fields as missing
    base = {"item": "N", "itemDescription": "D", "amount": "C"}
    assert [f["key"] for f in missing("fixed_asset_register", base)] == ["category", "acquisitionDate", "depreciationRate"]
    full = dict(base, category="Cat", acquisitionDate="Dt", depreciationRate="T")
    assert missing("fixed_asset_register", full) == []
    labels = {f["key"]: (f["en"], f["fr"]) for f in fields_of("fixed_asset_register")}
    assert labels["category"] == ("Category", "Catégorie")
    assert "optionnel" not in labels["depreciationRate"][1] and "optional" not in labels["acquisitionDate"][0]


def test_an_exact_title_of_an_added_column_is_not_taken_by_a_loose_guess():
    from services.dataset_mapping import guess_map
    headers = ["Code", "Désignation", "Date de mise en service", "Valeur brute", "Taux d'amortissement", "Amortissements cumulés", "Famille"]
    mapping = guess_map("fixed_asset_register", headers)
    assert mapping["depreciationRate"] == "Taux d'amortissement"
    assert mapping["depreciation"] == "Amortissements cumulés"
    assert (mapping["acquisitionDate"], mapping["category"]) == ("Date de mise en service", "Famille")


def test_a_rate_is_a_percentage_and_a_fraction_reads_as_one():
    from services.import_matching import depreciation_rate
    assert [depreciation_rate(v) for v in ("20%", "20 %", "20", "0,2", 0.2, "12,5", "1%", 0)] == [20, 20, 20, 20, 20, 12.5, 1, 0]
    assert [depreciation_rate(v) for v in ("150", "-5", "n/d", "", None)] == [None] * 5


def test_the_register_rows_are_checked_one_by_one():
    from services.import_matching import far_check
    mapping = {"category": "Cat", "acquisitionDate": "Dt", "depreciationRate": "T"}
    rows = [
        {"Cat": "Bâtiments", "Dt": "15/03/2020", "T": "5%"},
        {"Cat": " ", "Dt": "31/03/2026", "T": "0,2"},
        {"Cat": "Info", "Dt": "n/d", "T": "150"},
    ]
    found = far_check({"headers": list(mapping.values()), "rows": rows}, mapping, "2025-12-31")
    rows_of = {key: [item["row"] for item in items] for key, items in found.items()}
    assert rows_of == {"noCategory": [2], "badDate": [3], "futureDate": [2], "badRate": [3], "fractionRate": [2]}


# ---- the register's optional account and disposals columns (owner's request of 2026-11-17) ----

def test_the_three_account_columns_are_optional_and_kept_apart():
    from services.dataset_mapping import guess_map
    from services.import_matching import missing_fields as missing
    labels = {f["key"]: (f["en"], f["fr"], f.get("required")) for f in fields_of("fixed_asset_register")}
    assert labels["account"][:2] == ("Cost account (optional)", "Compte d'immobilisation (optionnel)")
    assert labels["depAccount"][1] == "Compte d'amortissement (optionnel)" and labels["chargeAccount"][1] == "Compte de dotation (optionnel)"
    assert not any(labels[key][2] for key in ("account", "depAccount", "chargeAccount", "disposalsCost"))
    full = {"item": "N", "itemDescription": "D", "amount": "C", "category": "Cat", "acquisitionDate": "Dt", "depreciationRate": "T"}
    assert missing("fixed_asset_register", full) == []
    base = ["Code", "Désignation", "Valeur brute", "Date d'acquisition", "Taux", "Famille"]
    mapping = guess_map("fixed_asset_register", base + ["Compte", "Compte d'amortissement", "Compte de dotation"])
    assert (mapping["account"], mapping["depAccount"], mapping["chargeAccount"]) == ("Compte", "Compte d'amortissement", "Compte de dotation")
    loose = guess_map("fixed_asset_register", base + ["Compte amort. cumulés", "Compte dotation 2025", "N° compte"])
    assert loose["account"] == "N° compte" and loose.get("chargeAccount") == "Compte dotation 2025"
    assert loose.get("account") != "Compte amort. cumulés"


def test_the_two_disposals_columns_are_kept_apart():
    from services.dataset_mapping import guess_map
    labels = {f["key"]: (f["en"], f["fr"]) for f in fields_of("fixed_asset_register")}
    assert labels["disposals"] == ("Disposals at net book value (optional)", "Cessions à la valeur nette comptable (optionnel)")
    assert labels["disposalsCost"] == ("Disposals at cost (optional)", "Cessions à la valeur brute (optionnel)")
    base = ["Code", "Désignation", "Valeur brute", "Date d'acquisition", "Taux", "Famille"]
    mapping = guess_map("fixed_asset_register", base + ["Cessions brutes", "Cessions VNC", "Acquisitions"])
    assert (mapping["disposalsCost"], mapping["disposals"], mapping["additions"]) == ("Cessions brutes", "Cessions VNC", "Acquisitions")
    loose = guess_map("fixed_asset_register", base + ["Cessions de l'exercice (brut)", "Cessions"])
    assert loose["disposals"] == "Cessions" and loose.get("disposalsCost") != "Cessions"
