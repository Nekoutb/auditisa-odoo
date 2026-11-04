"""The pure assertions of platform/tests/lib/*.test.ts, carried over one for one.

Source files: cra-model, materiality-model, tod-plan, dataset-mapping, tb-readability,
parse-tabular (CSV), standards-edition (F045), f070-email-domains (pure), f061-toc-draws
(pure), toc-sample, retention (pure), tb (mapping inference), batch6-ohada (F059/F060),
legal (date helpers). Cases needing a database, ExcelJS or the paper catalogue are not here.
"""
import pytest

from services import alerte, cra_model, dataset_mapping, email_domains, engines, lead_classes, legal, materiality_model, retention, standards_edition, subledgers, tb, tb_reasons, toc_sampling, tod_plan
from services.errors import LegalError, RetentionError, ServiceError, SubLedgerError, TbError


# ---- cra-model.test.ts -------------------------------------------------------

def test_combines_ir_and_cr_per_the_four_cell_matrix():
    assert cra_model.cra_of("lower", "rely") == "minimal"
    assert cra_model.cra_of("lower", "not_rely") == "moderate"
    assert cra_model.cra_of("higher", "rely") == "low"
    assert cra_model.cra_of("higher", "not_rely") == "high"


def test_overlays_significant_risk_without_creating_a_fifth_level():
    assert cra_model.to_tod("low", True) == "low_sr"
    assert cra_model.to_tod("high", True) == "high_sr"
    assert cra_model.to_tod("minimal", True) == "low_sr"
    assert cra_model.to_tod("moderate", True) == "high_sr"
    assert cra_model.to_tod("moderate", False) == "moderate"


def test_rolls_a_set_of_cells_up_to_the_worst():
    assert cra_model.worst_tod(["minimal", "moderate", "low"]) == "moderate"
    assert cra_model.worst_tod(["low_sr", "high", "minimal"]) == "high"
    assert cra_model.worst_tod(["high", "high_sr"]) == "high_sr"
    assert cra_model.worst_tod([]) is None


def test_labels_the_overlay():
    assert cra_model.tod_label("high_sr", "en") == "High +SR"
    assert cra_model.tod_label("moderate", "fr") == "Modéré"


def test_tightens_key_item_thresholds_as_the_cra_rises():
    assert "75–100%" in cra_model.threshold_suggestion("minimal", "en")
    assert "10–25%" in cra_model.threshold_suggestion("high", "en")
    assert "5–10%" in cra_model.threshold_suggestion("high", "en")


def test_shrinks_the_interim_window_as_the_cra_rises():
    assert "6 months" in cra_model.timing_suggestion("minimal", "en")
    assert "3 months" in cra_model.timing_suggestion("low", "en")
    assert "period end" in cra_model.timing_suggestion("high", "en")


# ---- materiality-model.test.ts -----------------------------------------------

def test_umt_is_pm_minus_te():
    assert materiality_model.uncorrected_misstatement_threshold({"overall": 1_000_000, "performance": 750_000}) == 250_000
    assert materiality_model.uncorrected_misstatement_threshold({"overall": 1_000_000, "performance": 500_000}) == 500_000


def test_umt_never_goes_negative_and_is_none_without_a_materiality():
    assert materiality_model.uncorrected_misstatement_threshold({"overall": 400_000, "performance": 500_000}) == 0
    assert materiality_model.uncorrected_misstatement_threshold(None) is None


# ---- tod-plan.test.ts --------------------------------------------------------

def _line(ref, amount, account="411100"):
    return {"ref": ref, "account": account, "amount": amount}


LINES = [_line("A", 5_000_000), _line("B", 2_000_000)] + [_line("S%d" % (i + 1), 100_000 * (i + 1)) for i in range(30)]


def test_splits_key_items_and_sizes_the_sample_from_te():
    p = tod_plan.plan_tod({"lines": LINES, "te": 1_500_000, "threshold": 1_000_000, "cra": "moderate", "assurance": "little", "startFraction": 0.5})
    assert p["threshold"] == 1_000_000
    assert [l["ref"] for l in p["keyItems"]] == ["A", "B"] + ["S%d" % (i + 10) for i in range(21)]
    assert p["remainingCount"] == 9
    assert p["remainingValue"] == 4_500_000
    assert p["baseSize"] == 3
    assert p["coverageColumn"] == 90
    assert p["factor"] is None
    assert p["sampleSize"] == 0
    assert p["sample"] == []


def test_caps_the_size_at_the_population():
    p = tod_plan.plan_tod({"lines": LINES, "te": 1_000_000, "threshold": 4_000_000, "cra": "high_sr", "assurance": "little", "startFraction": 0.25})
    assert [l["ref"] for l in p["keyItems"]] == ["A"]
    assert p["factor"] == tod_plan.ART_MUS["high_sr"]["little"][0]
    assert p["computedSize"] == 146
    assert p["remainingCount"] == 31
    assert p["sampleSize"] == 31
    assert p["fullPopulation"] is True
    assert p["itemsDrawn"] == 31
    assert len({l["ref"] for l in p["sample"]}) == 31
    assert all(l["amount"] < 4_000_000 for l in p["sample"])


def test_reports_the_distinct_items_when_hooks_share_a_line():
    lines = [_line("BIG", 9_000_000)] + [_line("S%d" % (i + 1), 10_000) for i in range(30)]
    p = tod_plan.plan_tod({"lines": lines, "te": 1_000_000, "threshold": 20_000_000, "cra": "high_sr", "assurance": "little", "startFraction": 0.1})
    assert p["computedSize"] == 28
    assert p["sampleSize"] == 28
    assert p["fullPopulation"] is False
    assert p["sample"][0]["ref"] == "BIG"
    assert p["itemsDrawn"] == len(p["sample"])
    assert p["itemsDrawn"] < p["sampleSize"]
    assert len({l["ref"] for l in p["sample"]}) == len(p["sample"])


def test_places_exactly_the_requested_hooks_inside_the_population():
    lines = [_line("L%d" % (i + 1), 1_000_000) for i in range(11)]
    p = tod_plan.plan_tod({"lines": lines, "te": 1_375_000, "threshold": 2_000_000, "cra": "minimal", "assurance": "little", "startFraction": 0.9})
    assert p["sampleSize"] == 4
    assert p["fullPopulation"] is False
    assert p["interval"] == 2_750_000
    assert [l["ref"] for l in p["sample"]] == ["L3", "L6", "L8", "L11"]
    assert p["itemsDrawn"] == 4


def test_defaults_the_threshold_to_te_and_ignores_zero_or_negative_lines():
    p = tod_plan.plan_tod({"lines": LINES + [_line("Z", 0), _line("N", -5)], "te": 2_500_000, "cra": "low", "assurance": "some", "startFraction": 0})
    assert p["threshold"] == 2_500_000
    assert p["populationCount"] == 32
    assert [l["ref"] for l in p["keyItems"]] == ["A", "S25", "S26", "S27", "S28", "S29", "S30"]


def test_is_reproducible_for_a_given_start_fraction():
    args = {"lines": LINES, "te": 500_000, "threshold": 10_000_000, "cra": "moderate", "assurance": "some", "startFraction": 0.4}
    a = tod_plan.plan_tod(args)
    b = tod_plan.plan_tod(args)
    assert [l["ref"] for l in a["sample"]] == [l["ref"] for l in b["sample"]]
    assert len(a["sample"]) > 0


# ---- dataset-mapping.test.ts -------------------------------------------------

ELIMELEC = ["C.j", "Let", "Date", "Amount", "JE N°", "N° pièce", "N° de compte", "Mouvement débit", "Mouvement crédit", "Libellé écriture", "Intitulé du compte"]


def test_puts_the_entry_number_on_je_n_and_the_journal_code_on_cj():
    m = dataset_mapping.auto_map("journal_entries", ELIMELEC)
    assert m["jeNumber"] == "JE N°"
    assert m["journalCode"] == "C.j"
    assert m["account"] == "N° de compte"
    assert m["accountName"] == "Intitulé du compte"
    assert m["jeDescription"] == "Libellé écriture"
    assert m["journalDate"] == "Date"
    assert m["amount"] == "Amount"
    assert m["debit"] == "Mouvement débit"
    assert m["credit"] == "Mouvement crédit"
    assert m["reference"] == "N° pièce"


def test_never_maps_one_header_twice():
    headers = list(dataset_mapping.auto_map("journal_entries", ELIMELEC).values())
    assert len(set(headers)) == len(headers)


def test_still_finds_the_french_spellings():
    m = dataset_mapping.auto_map("journal_entries", ["Journal", "N° écriture", "Compte", "Libellé", "Débit", "Crédit", "Date opération"])
    assert m["journalCode"] == "Journal"
    assert m["jeNumber"] == "N° écriture"
    assert m["account"] == "Compte"
    assert m["journalDate"] == "Date opération"


def test_je_number_looks_like_journal_code():
    assert dataset_mapping.je_number_looks_like_journal_code(33_336, 11) is True
    assert dataset_mapping.je_number_looks_like_journal_code(33_336, 8_059) is False
    assert dataset_mapping.je_number_looks_like_journal_code(60, 2) is False


# ---- tb-readability.test.ts --------------------------------------------------

HEADERS = ["Compte", "Libellé", "Débit", "Crédit"]


def _rows(*rows):
    return {"headers": HEADERS, "rows": list(rows)}


def test_names_the_column_row_account_and_value_that_could_not_be_read():
    table = _rows(
        {"Compte": "411100", "Libellé": "Clients", "Débit": "1 500 000", "Crédit": ""},
        {"Compte": "701100", "Libellé": "Ventes", "Débit": "", "Crédit": "1 500 000"},
        {"Compte": "521100", "Libellé": "Banque", "Débit": "N/A", "Crédit": ""},
        {"Compte": "601100", "Libellé": "Achats", "Débit": "12.345,67 FCFA", "Crédit": ""},
        {"Compte": "", "Libellé": "TOTAL", "Débit": "1 512 345", "Crédit": "1 500 000"},
    )
    r = tb.readability_of(table, tb.infer_tb_mapping(HEADERS))
    assert r["rows"] == 5
    assert r["rowsWithoutAccount"] == 1
    assert len(r["unreadable"]) == 1
    u = r["unreadable"][0]
    assert u["column"] == "debit"
    assert u["header"] == "Débit"
    assert u["count"] == 1
    assert u["examples"] == [{"row": 3, "account": "521100", "value": "N/A"}]


def test_makes_the_import_invalid_and_explains_it():
    table = _rows(
        {"Compte": "411100", "Libellé": "Clients", "Débit": "abc", "Crédit": ""},
        {"Compte": "701100", "Libellé": "Ventes", "Débit": "", "Crédit": "100"},
    )
    mapping = tb.infer_tb_mapping(HEADERS)
    summary = tb.validate_tb_rows(tb.extract_tb_rows(table, mapping), ["41", "70"], None, mapping, tb.readability_of(table, mapping))
    assert summary["status"] == "invalid"
    en = tb_reasons.explain_tb_summary(summary, "en")
    assert any(l["blocking"] and 'Column "Débit"' in l["text"] and "row 1 (411100)" in l["text"] and '"abc"' in l["text"] for l in en)
    assert any(l["text"].startswith("Movements do not balance") and "difference" in l["text"] for l in en)
    assert any("Colonne « Débit »" in l["text"] for l in tb_reasons.explain_tb_summary(summary, "fr"))


def test_ties_pl_and_result_accounts_to_the_prior_year_in_one_check():
    mapping = {"account": "c", "openingDebit": "od", "openingCredit": "oc", "debit": "d", "credit": "c2"}

    def row(account, od, oc):
        return {"account": account, "label": None, "openingDebit": od, "openingCredit": oc, "debit": 0, "credit": 0, "raw": {}}

    prior = {"521000": 2_000_000, "601000": 33_000_000, "701000": -45_000_000}
    ok = tb.validate_tb_rows(
        [row("521000", 2_000_000, 0), row("601000", 0, 0), row("701000", 0, 0), row("130000", 0, 12_000_000)],
        ["52", "60", "70", "13"], prior, mapping,
    )
    assert ok["checks"]["openingTiesToPrior"]["exceptions"] == []
    off = tb.validate_tb_rows([row("521000", 2_000_000, 0), row("130000", 0, 10_000_000)], ["52", "13"], prior, mapping)
    assert off["checks"]["openingTiesToPrior"]["exceptions"] == [{"account": "12x/13x", "opening": -10_000_000, "priorClosing": -12_000_000}]
    assert any("résultat reporté 12x/13x" in l["text"] for l in tb_reasons.explain_tb_summary(off, "fr"))


def test_points_unreadable_amounts_at_the_physical_csv_line():
    table = subledgers.parse_tabular_file("t.csv", "BALANCE\n\nCompte;Libellé;Débit;Crédit\n411100;Clients;100;\n\n521100;Banque;n/a;\n701100;Ventes;;100\n".encode())
    r = tb.readability_of(table, tb.infer_tb_mapping(table["headers"]))
    assert r["unreadable"][0]["examples"] == [{"row": 6, "account": "521100", "value": "n/a"}]


def test_says_nothing_about_a_clean_file():
    table = _rows(
        {"Compte": "411100", "Libellé": "Clients", "Débit": "100", "Crédit": ""},
        {"Compte": "701100", "Libellé": "Ventes", "Débit": "", "Crédit": "100"},
    )
    mapping = tb.infer_tb_mapping(HEADERS)
    summary = tb.validate_tb_rows(tb.extract_tb_rows(table, mapping), ["41", "70"], None, mapping, tb.readability_of(table, mapping))
    assert summary["status"] == "valid"
    assert tb_reasons.explain_tb_summary(summary, "en") == []


# ---- parse-tabular.test.ts (CSV) ---------------------------------------------

def test_first_row_as_headers():
    t = subledgers.parse_tabular_file("tb.csv", "Compte,Intitulé,Solde\n411000,Clients,1500\n701000,Ventes,-1500\n".encode())
    assert t["headers"] == ["Compte", "Intitulé", "Solde"]
    assert len(t["rows"]) == 2
    assert t["rows"][0]["Compte"] == "411000"


def test_header_row_false_keeps_row_one_as_data():
    t = subledgers.parse_tabular_file("tb.csv", b"411000,Clients,1500\n701000,Ventes,-1500\n", False)
    assert t["headers"] == ["col_1", "col_2", "col_3"]
    assert len(t["rows"]) == 2
    assert t["rows"][0]["col_1"] == "411000"
    assert len(subledgers.parse_tabular_file("tb.csv", b"411000,Clients,1500\n", False)["rows"]) == 1


def test_semicolon_file_with_decimal_commas_keeps_each_amount_whole():
    t = subledgers.parse_tabular_file("tb_semi.csv", "Compte;Intitulé;Débit;Crédit\n411000;Clients;10 000 000,00;\n701000;Ventes;;10 000 000,00\n".encode())
    assert t["headers"] == ["Compte", "Intitulé", "Débit", "Crédit"]
    assert t["rows"][0]["Débit"] == "10 000 000,00"
    assert t["rows"][1]["Crédit"] == "10 000 000,00"


def test_banner_lines_are_skipped_to_the_real_header():
    t = subledgers.parse_tabular_file("tb_sage.csv", "BALANCE GENERALE\nExercice du 01/01/2025 au 31/12/2025\nCompte;Intitulé;Solde\n411000;Clients;1500\n".encode())
    assert t["headers"] == ["Compte", "Intitulé", "Solde"]
    assert len(t["rows"]) == 1
    assert t["rows"][0]["Compte"] == "411000"


def test_refusals_of_the_reader():
    with pytest.raises(SubLedgerError, match="unsupported-file"):
        subledgers.parse_tabular_file("x.pdf", b"")
    with pytest.raises(SubLedgerError, match="empty-file"):
        subledgers.parse_tabular_file("x.csv", b"\n\n")


# ---- tb.test.ts (mapping inference) ------------------------------------------

def test_recognises_fr_balance_generale_headers():
    mapping = tb.infer_tb_mapping("Compte;Libellé;Solde initial débit;Solde initial crédit;Mouvement débit;Mouvement crédit".split(";"))
    assert mapping["account"] == "Compte"
    assert mapping["openingDebit"] == "Solde initial débit"
    assert mapping["debit"] == "Mouvement débit"


def test_accepts_closing_only_files_and_rejects_unmappable_ones():
    assert tb.infer_tb_mapping(["Account", "Balance"])["closing"] == "Balance"
    with pytest.raises(TbError, match="missing-account-column"):
        tb.infer_tb_mapping(["foo", "bar"])


# ---- standards-edition.test.ts (F045) ----------------------------------------

def test_computes_the_first_day_of_the_period():
    start = standards_edition.period_start_of
    assert start("2026-12-31") == "2026-01-01"
    assert start("2026-12-31", 12) == "2026-01-01"
    assert start("2027-06-30", 6) == "2027-01-01"
    assert start("2027-06-30", 18) == "2026-01-01"
    assert start("2027-03-31", None) == "2026-04-01"
    assert start("2027-03-31", 0) == "2026-04-01"
    assert start("2027-03-31", 1) == "2027-03-01"
    assert start("2027-05-30", 3) == "2027-02-28"
    with pytest.raises(ServiceError, match="invalid-period-end"):
        start("not a date")


def test_switches_to_the_revised_standards_on_15_december_2026():
    from datetime import date

    edition = standards_edition.default_standards_edition
    assert standards_edition.REVISED_2026_FROM == "2026-12-15"
    assert edition("2026-12-14") == "current"
    assert edition("2026-12-15") == "revised_2026"
    assert edition("2027-01-01") == "revised_2026"
    assert edition(date(2026, 12, 15)) == "revised_2026"
    assert edition(None) == "current"
    period = standards_edition.edition_for_period
    assert period("2026-12-31", 12) == "current"
    assert period("2027-11-30", 12) == "current"
    assert period("2027-12-14", 12) == "revised_2026"
    assert period("2027-12-31", None) == "revised_2026"
    assert period("2027-06-30", 6) == "revised_2026"


def test_labels_the_edition_in_both_languages():
    assert standards_edition.edition_label("current", "fr") == "ISA en vigueur"
    assert standards_edition.edition_label("revised_2026", "fr") == "ISA révisées (périodes ouvertes à partir du 15/12/2026)"
    assert standards_edition.edition_line("current", "fr") == "Édition des normes : ISA en vigueur"
    assert standards_edition.edition_line("revised_2026", "en") == "Standards edition: Revised ISAs (periods beginning on or after 15/12/2026)"


def test_renders_isa_240_and_570_references_per_edition():
    ref = standards_edition.isa_ref
    assert ref("current", "ISA240.jeTesting") == "ISA 240 ¶32"
    assert ref("revised_2026", "ISA240.jeTesting").startswith("ISA 240 (Revised) ¶")
    assert ref("revised_2026", "ISA240.jeTesting", "fr").startswith("ISA 240 révisée ¶")
    assert ref("current", "ISA240.commMgmt") == "ISA 240 ¶40"
    assert ref("current", "ISA240.authorities") == "ISA 240 ¶43"
    assert ref("current", "ISA570.conclusions") == "ISA 570 (Revised) ¶21–24"
    assert ref("revised_2026", "ISA570.conclusions") == "ISA 570 (Revised 2024) ¶21–24"
    assert "twelve months from the date of the financial statements" in ref("current", "ISA570.horizon")
    assert "twelve months from the date of approval of the financial statements" in ref("revised_2026", "ISA570.horizon")
    assert "douze mois à compter de la date d'approbation" in ref("revised_2026", "ISA570.horizon", "fr")
    assert "douze mois à compter de la date de clôture" in ref("current", "ISA570.horizon", "fr")


def test_names_every_edition_dependent_standard():
    for key in standards_edition.ISA_REF_KEYS:
        for edition in ("current", "revised_2026"):
            for locale in ("en", "fr"):
                text = standards_edition.isa_ref(edition, key, locale)
                assert len(text) > 0
                assert standards_edition.has_unresolved_token(text) is False


def test_substitutes_tokens_and_leaves_an_unknown_one_visible():
    resolve = standards_edition.resolve_text
    assert resolve("see {{ISA240.jeTesting}} and {{ISA570}}", "current", "en") == "see ISA 240 ¶32 and ISA 570 (Revised)"
    assert resolve("voir {{ISA570}}", "revised_2026", "fr") == "voir ISA 570 révisée 2024"
    assert resolve("{{Nope.key}}", "current", "en") == "{{Nope.key}}"
    assert resolve("plain", "current", "en") == "plain"


def test_a_token_naming_an_inherited_member_fails_as_in_the_source():
    with pytest.raises(TypeError):
        standards_edition.resolve_text("{{constructor}}", "current", "en")


# ---- f070-email-domains.test.ts (pure) ---------------------------------------

def test_parses_one_or_several_domains():
    assert email_domains.parse_domain_list("ECA.com\n@eca-cm.com, eca.com") == ["eca-cm.com", "eca.com"]
    assert email_domains.parse_domain_list("  ") == []
    with pytest.raises(ServiceError, match="invalid-email-domain"):
        email_domains.parse_domain_list("not a domain!")


def test_matches_a_domain_exactly_and_case_insensitively():
    allowed = email_domains.email_domain_allowed
    assert allowed("x@ECA.com", ["eca.com"]) is True
    assert allowed("x@audit.eca.com", ["eca.com"]) is False
    assert allowed("x@eca.com.attacker.net", ["eca.com"]) is False
    assert allowed("anyone@any.org", []) is True
    assert email_domains.email_domain("no-at-sign") is None


# ---- f061-toc-draws.test.ts (pure), toc-sample.test.ts ------------------------

def test_the_seeded_draw_is_reproducible_from_its_seed():
    draw = toc_sampling.draw_toc_sample
    rng = toc_sampling.seeded_rng
    a = draw(650, 25, rng("seed-1", engines.seeded_random))
    b = draw(650, 25, rng("seed-1", engines.seeded_random))
    assert a == b
    assert a != draw(650, 25, rng("seed-2", engines.seeded_random))


def test_draws_distinct_occurrences_inside_the_population():
    items = toc_sampling.draw_toc_sample(650, 25)
    assert len(items) == 25
    assert len(set(items)) == 25
    assert all(1 <= v <= 650 for v in items)
    assert sorted(items) == items


def test_takes_the_whole_population_or_nothing():
    assert toc_sampling.draw_toc_sample(3, 5) == [1, 2, 3]
    assert toc_sampling.draw_toc_sample(0, 5) == []
    assert toc_sampling.draw_toc_sample(10, 0) == []


def test_testing_started_needs_a_recorded_result():
    assert toc_sampling.toc_testing_started(None) is False
    assert toc_sampling.toc_testing_started({"rows": [{"results": {"a": ""}}]}) is False
    assert toc_sampling.toc_testing_started({"rows": [{"results": {"a": "pass"}}]}) is True


# ---- retention.test.ts (pure) ------------------------------------------------

def test_counts_from_the_report_date_or_falls_back_to_the_period_end():
    assert retention.retention_date("2026-04-30", "2025-12-31", 10) == "2036-04-30"
    assert retention.retention_date(None, "2025-12-31", 10) == "2035-12-31"


def test_refuses_a_period_below_the_floor():
    for years in (3, 9):
        with pytest.raises(RetentionError, match="out-of-range"):
            retention.assert_retention_years(years)


def test_the_sql_stamp_clamps_where_the_javascript_rolls_over():
    """No parity fixture for this one: it reads what Postgres documents, there being no
    database in these tests. The two disagree on the source, and the port keeps both."""
    assert retention.retention_date("2024-02-29", "2024-12-31", 10) == "2034-03-01"
    assert retention.retention_until_sql("2024-02-29", "2024-12-31", 10) == "2034-02-28"
    assert retention.retention_until_sql(None, "2024-12-31", 10) == "2034-12-31"
    assert retention.retention_until_sql("2024-02-29", "2024-12-31", 12) == "2036-02-29"


# ---- batch6-ohada.test.ts (F059 / F060), the lines that exercise lead-classes ---

def test_f059_prefix_mapping():
    index = lead_classes.lead_index_for
    sub = lead_classes.sub_index_for
    assert index("490") == "N"
    assert index("4901000") == "N"
    assert sub("4901000") == "N-3"
    assert index("491") == "E"
    assert sub("4911") == "E-2"
    assert index("292") == "K"
    assert index("295") == "K"
    assert sub("2921") == "K-6"
    assert sub("2951") == "K-6"
    assert index("291") == "L"
    assert index("296") == "J"
    assert index("499") == "P1"
    assert sub("4991") == "P1-2"
    assert index("498") == "G2"


def test_f060_alerts_on_class_20_and_490():
    assert lead_classes.sub_index_for("2010000") == "L-1"
    assert lead_classes.lead_schedule_alerts([{"account": "2110000", "closing": 8_000_000}]) == []
    assert lead_classes.lead_schedule_alerts([{"account": "4901000", "closing": 0}, {"account": "4011000", "closing": 5}]) == []
    alerts = lead_classes.lead_schedule_alerts([{"account": "4901000", "closing": 5}, {"account": "2010000", "closing": 7}])
    assert [a["code"] for a in alerts] == ["supplier_debit_impairment", "legacy_class_20"]
    assert alerts[1]["accounts"] == ["2010000"]


# ---- legal.test.ts (date helpers, the alerte clock) ----------------------------

def test_date_helpers():
    assert legal.add_months_clamped("2025-12-31", 4) == "2026-04-30"
    assert legal.add_months_clamped("2025-12-31", 6) == "2026-06-30"
    assert legal.add_months_clamped("2025-01-15", 1) == "2025-02-15"
    assert legal.add_days_iso("2026-06-15", -45) == "2026-05-01"


def test_the_alerte_clock_runs_from_the_event_date():
    start = alerte.start_alerte("SA", False, "2026-01-31", "2026-11-04")
    assert start == {"variant": "sa", "stage": "request_sent", "stageDeadline": "2026-03-02", "eventDate": "2026-01-31"}
    assert alerte.start_alerte("SARL", False, None, "2026-11-04")["stageDeadline"] == legal.add_days_iso("2026-11-04", alerte.FIRST_REPLY_DAYS)
    with pytest.raises(LegalError, match="invalid-event-date"):
        alerte.start_alerte("SA", False, "2026-11-05", "2026-11-04")
    with pytest.raises(LegalError, match="alerte-open"):
        alerte.start_alerte("SA", True, None, "2026-11-04")
