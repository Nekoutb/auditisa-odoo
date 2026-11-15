"""Every case recorded from the real TypeScript (scripts/parity), against the Python port.

The comparison is exact: floats to the last bit, the same refusal code, the same text.
A recorded function with no adapter below fails, so nothing recorded goes untested.
"""
import json
import math
import os

import pytest

from services import (
    _js, alerte, amount, assertions, complexity, control_labels, cra_model, dataset_mapping, design_procedures_model,
    email_domains, engines, financial_analysis, itgc_model, lead_classes, leadsheets, legal, materiality_model, retention,
    sad_model, sampling_params, sap_model, standards_edition, subledger_kinds, subledgers, tb, tb_reasons, toc_grid,
    toc_sampling, tod_plan,
)
from services.errors import ServiceError

_SOURCE_NOTES = {
    False: ("Requires the General Ledger (last 3 months): upload it in the GL Analyzer. Prior year: blank because the prior-year General Ledger is not imported.",
            "Nécessite le grand livre (3 derniers mois) : à importer dans l'analyseur de grand livre. Exercice précédent : vide car le grand livre N-1 n'est pas importé."),
    True: ("Prior year: blank because the prior-year General Ledger is not imported.",
           "Exercice précédent : vide car le grand livre N-1 n'est pas importé."),
}


def _financial_analysis_as_source(rows, end, prior, overrides, mapping, gl):
    """What the source returns: the formula, the reason for a blank (F064) and the wording of the
    notes (owner's ruling of 2026-11-15: say when the audit period and the data do not match) are this port's."""
    view = financial_analysis.financial_analysis(rows, end, prior, overrides, mapping, gl)
    if view:
        for row in view["rows"]:
            row.pop("formula")
            row.pop("formulaFr")
            row.pop("blank", None)
            row.pop("blankFr", None)
            if "note" in row:
                # the source's own wording, which the port replaced
                row["note"], row["noteFr"] = _SOURCE_NOTES[view["glAvailable"]]
    return view


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TODAY = "2026-11-04"


def dec(value):
    """Undo the recorder's tags. An undefined argument becomes None."""
    if isinstance(value, list):
        return [dec(v) for v in value]
    if isinstance(value, dict):
        if "$js" in value:
            return {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf, "undefined": None}[value["$js"]]
        if "$map" in value:
            return {dec(k): dec(v) for k, v in value["$map"]}
        return {k: dec(v) for k, v in value.items()}
    return value


def same(actual, expected, path="$"):
    """Exact equality with int and float comparing by value, and nothing else mixed."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        assert actual is expected, "%s: %r != %r" % (path, actual, expected)
    elif isinstance(expected, (int, float)):
        assert isinstance(actual, (int, float)), "%s: %r != %r" % (path, actual, expected)
        if isinstance(expected, float) and math.isnan(expected):
            assert isinstance(actual, float) and math.isnan(actual), "%s: %r != NaN" % (path, actual)
        else:
            # JSON writes 1.2345678901234568e20 as an integer of 21 digits: the double it names
            wanted = float(expected) if abs(expected) >= 2 ** 53 else expected
            got = float(actual) if abs(actual) >= 2 ** 53 else actual
            assert got == wanted, "%s: %r != %r" % (path, actual, expected)
    elif isinstance(expected, list):
        assert isinstance(actual, (list, tuple)), "%s: %r != %r" % (path, actual, expected)
        assert len(actual) == len(expected), "%s: length %d != %d: %r != %r" % (path, len(actual), len(expected), actual, expected)
        for i, (a, e) in enumerate(zip(actual, expected)):
            same(a, e, "%s[%d]" % (path, i))
    elif isinstance(expected, dict):
        assert isinstance(actual, dict), "%s: %r != %r" % (path, actual, expected)
        assert set(actual) == set(expected), "%s: keys %r != %r" % (path, sorted(map(str, actual)), sorted(map(str, expected)))
        for key, e in expected.items():
            same(actual[key], e, "%s.%s" % (path, key))
    else:
        assert actual == expected, "%s: %r != %r" % (path, actual, expected)


def constant(value):
    return lambda *args: value


def table(arg):
    """A recorded table: rows with the physical file row carried beside them."""
    rows = []
    for raw, row_no in zip(arg["rows"], arg["rowNos"]):
        row = subledgers.TabularRow(raw)
        row.source_row = row_no
        rows.append(row)
    return {"headers": arg["headers"], "rows": rows}


def table_out(result):
    return {
        "headers": result["headers"],
        "rows": [dict(row) for row in result["rows"]],
        "rowNos": [subledgers.source_row_of(row) for row in result["rows"]],
    }


def _text(value):
    return None if value is None or value == "" else _js.js_str(value)


def _validate_tb(arg, mapping, known, prior, readability):
    # the rows come through the same port, which the extractTbRows cases hold to the source
    return tb.validate_tb_rows(tb.extract_tb_rows(table(arg), mapping), known, prior, mapping, readability)


def _extract(arg, mapping):
    return tb.extract_tb_rows(table(arg), mapping)


def _toc_draw(population, size, seed):
    return toc_sampling.draw_toc_sample(population, size, toc_sampling.seeded_rng(seed, engines.seeded_random))


def _place_held(held):
    retention.assert_can_place_hold(held)
    return None


def _set_years(years):
    retention.assert_retention_years(years)
    return None


def _start(form, is_open, date, today):
    out = alerte.start_alerte(form, is_open, date, today)
    return {"variant": out["variant"], "stageDeadline": out["stageDeadline"]}


def _advance(variant, stage, discontinued, to, last, today, opt):
    out = alerte.advance_alerte(variant, stage, discontinued, to, last, today, satisfactory=opt.get("satisfactory", False), event_date=opt.get("eventDate"))
    return {"stage": out["stage"], "stageDeadline": out["stageDeadline"], "discontinued": out["discontinued"]}


def _recon(kind, rows, tb_total, trivial, stale_days, period_end):
    out = engines.run_reconciliation(kind, rows, tb_total, trivial, stale_days, period_end)
    return {"engine": out["engine"], "summary": out["summary"], "finding": out["finding"]}


def _preview(arg, mapping, overrides, global_rules, index_overrides):
    return tb.preview_trial_balance(table(arg), mapping, overrides, global_rules, index_overrides)


def _unsupported(_name):
    with pytest.raises(ServiceError) as caught:
        subledgers.parse_tabular_file("x.pdf", b"")
    return caught.value.code


def _journal(description, lines):
    tb.validate_journal(description, lines)
    return None


ADAPTERS = {
    "js_helpers": {
        "Math.round": _js.js_round,
        "Math.floor": _js.js_floor,
        "Math.ceil": _js.js_ceil,
        "String": _js.js_number_str,
        "nf_fr": _js.format_fr,
        "trim": _js.js_trim,
        "Date.parse": lambda s: math.nan if (ms := _js.js_date_parse(s)) is None else ms,
        "toISOString": lambda s: _js.to_iso(_js.js_date_parse(s)),
        "getDay": lambda s: _js.weekday(_js.js_date_parse(s)),
        "localeCompare": _js.locale_compare,
        "localeCompare_numeric": lambda a, b: _js.locale_compare(a, b, numeric=True),
        "replaceAll": lambda s: _js.js_replace_all("a{K}b{K}c", "{K}", s),
    },
    "amount": {"parseAmount": amount.parse_amount, "amountOr": amount.amount_or},
    "materiality_model": {
        "PERFORMANCE_PCT_RANGE": constant(materiality_model.PERFORMANCE_PCT_RANGE),
        "TRIVIAL_PCT_RANGE": constant(materiality_model.TRIVIAL_PCT_RANGE),
        "uncorrectedMisstatementThreshold": materiality_model.uncorrected_misstatement_threshold,
        "benchmarkLabel": materiality_model.benchmark_label,
    },
    "sad_model": {
        **{n: constant(getattr(sad_model, n)) for n in ("SAD_CAPTIONS", "SAD_CAPTION_LABELS", "SAD_TYPES", "MISSTATEMENT_TYPE_LABELS", "SAD_COLUMN_COUNT", "SAD_QUAL_FACTORS")},
        "captionColumn": sad_model.caption_column,
        "suggestCaption": sad_model.suggest_caption,
    },
    "cra_model": {
        "CR_DEFICIENT_BASIS": constant(cra_model.CR_DEFICIENT_BASIS),
        "craOf": cra_model.cra_of,
        "toTod": cra_model.to_tod,
        "craTone": cra_model.cra_tone,
        "craLevelLabel": cra_model.cra_level_label,
        "thresholdSuggestion": cra_model.threshold_suggestion,
        "timingSuggestion": cra_model.timing_suggestion,
        "todLabel": cra_model.tod_label,
        "worstTod": cra_model.worst_tod,
        "crBasisLabel": cra_model.cr_basis_label,
        "cellsToAssess": cra_model.cells_to_assess,
    },
    "design_procedures_model": {
        **{n: constant(getattr(design_procedures_model, n)) for n in ("NATURE_OPTIONS", "TIMING_OPTIONS", "NATURE_VALUES", "TIMING_VALUES", "OSP_MAX", "OSP_TEXT_MAX", "OSP_EXTENT_MAX", "ASSERTIONS")},
        "timingAllowed": design_procedures_model.timing_allowed,
        "craLevelOf": design_procedures_model.cra_level_of,
        "OSP_ID.test": lambda s: design_procedures_model.OSP_ID.match(s) is not None,
    },
    "sap_model": {
        **{n: constant(getattr(sap_model, n)) for n in ("DEFAULT_SAP_THRESHOLDS", "SAP_PCT_MIN", "SAP_PCT_MAX", "SAP_ASSERTIONS")},
        "sapAssertionLabel": sap_model.sap_assertion_label,
        "isSapAssertion": sap_model.is_sap_assertion,
        "isSapPct": sap_model.is_sap_pct,
        "thresholdPctFor": sap_model.threshold_pct_for,
        "evaluateSap": sap_model.evaluate_sap,
    },
    "control_labels": {
        "CONTROL_FREQUENCIES": constant(control_labels.CONTROL_FREQUENCIES),
        "freqLabel": control_labels.freq_label,
        "typeShort": control_labels.type_short,
        "objectiveLabel": control_labels.objective_label,
        "transactionTypeLabel": control_labels.transaction_type_label,
    },
    "assertions": {
        "ASSERTIONS": constant(assertions.ASSERTIONS),
        "ASSERTION_LABELS": constant(assertions.ASSERTION_LABELS),
        "isAssertion": assertions.is_assertion,
        "cleanAssertions": assertions.clean_assertions,
        "assertionName": assertions.assertion_name,
        "assertionLabel": assertions.assertion_label,
        "assertionLabels": assertions.assertion_labels,
    },
    "toc_sampling": {
        "TOC_EXTENDED_SIZE": constant(toc_sampling.TOC_EXTENDED_SIZE),
        "normFreq": toc_sampling.norm_freq,
        "tocSuggested": toc_sampling.toc_suggested,
        "tocEvaluate": toc_sampling.toc_evaluate,
        "tocTestingStarted": toc_sampling.toc_testing_started,
        "drawTocSample": _toc_draw,
    },
    "toc_grid": {"tocRowsPlanned": toc_grid.toc_rows_planned, "tocRowsTested": toc_grid.toc_rows_tested},
    "sampling_params": {
        "RISK_BAND_CONFIDENCE": constant(sampling_params.RISK_BAND_CONFIDENCE),
        "ATTRIBUTE_SAMPLE_SIZES": constant(sampling_params.ATTRIBUTE_SAMPLE_SIZES),
        "CONFIDENCE_FACTORS": lambda k: sampling_params.CONFIDENCE_FACTORS[k],
        "riskBandToConfidence": sampling_params.risk_band_to_confidence,
        "attributePlan": sampling_params.attribute_plan,
        "evaluateAttribute": sampling_params.evaluate_attribute,
        "musPlan": sampling_params.mus_plan,
        "projectMLE": sampling_params.project_mle,
    },
    "tod_plan": {
        **{n: constant(getattr(tod_plan, n)) for n in ("TOD_CRAS", "TOD_ASSURANCES", "ART_COLS", "ART_MUS")},
        "stableStartFraction": tod_plan.stable_start_fraction,
        "planTod": tod_plan.plan_tod,
    },
    "lead_classes": {
        **{n: constant(getattr(lead_classes, n)) for n in ("LEAD_INDEXES", "ACCOUNT_CLASSES", "PREFIX_INDEX", "SUB_INDEXES", "PREFIX_SUB", "INDEX_SECTION", "ACCOUNT_TYPE_FR", "ACCOUNT_CLASS_FR")},
        "leadIndexFor": lead_classes.lead_index_for,
        "subIndexFor": lead_classes.sub_index_for,
        "leadIndexLabel": lead_classes.lead_index_label,
        "accountTypeLabel": lead_classes.account_type_label,
        "accountClassLabel": lead_classes.account_class_label,
        "subIndexLabel": lead_classes.sub_index_label,
        "defaultIndexForClass": lead_classes.default_index_for_class,
        "leadScheduleAlerts": lead_classes.lead_schedule_alerts,
    },
    "complexity": {
        **{n: constant(getattr(complexity, n)) for n in ("COMPLEXITY_QUESTIONS", "DEFAULT_ENGAGEMENT_NAMING", "YEAR_END_OPTIONS", "DURATION_OPTIONS", "NATURE_OPTIONS", "ENGAGEMENT_PHASE_OPTIONS", "FRAMEWORK_OPTIONS")},
        "classifyComplexity": complexity.classify_complexity,
        "answersFromForm": lambda names: complexity.answers_from_form(lambda n: "on" if n in names else None),
        "applyNamingConvention": complexity.apply_naming_convention,
        "generateEngagementName": complexity.generate_engagement_name,
        "periodEndLabel": complexity.period_end_label,
        "natureLabel": complexity.nature_label,
    },
    "standards_edition": {
        "STANDARDS_EDITIONS": constant(standards_edition.STANDARDS_EDITIONS),
        "REVISED_2026_FROM": constant(standards_edition.REVISED_2026_FROM),
        "ISA_REF_KEYS": constant(standards_edition.ISA_REF_KEYS),
        "isStandardsEdition": standards_edition.is_standards_edition,
        "periodStartOf": standards_edition.period_start_of,
        "editionForPeriod": standards_edition.edition_for_period,
        "defaultStandardsEdition": standards_edition.default_standards_edition,
        "editionLabel": standards_edition.edition_label,
        "editionLine": standards_edition.edition_line,
        "isaRef": standards_edition.isa_ref,
        "resolveText": standards_edition.resolve_text,
        "hasUnresolvedToken": standards_edition.has_unresolved_token,
        "resolvePaper": standards_edition.resolve_paper,
    },
    "email_domains": {
        "parseDomainList": email_domains.parse_domain_list,
        "emailDomain": email_domains.email_domain,
        "emailDomainAllowed": email_domains.email_domain_allowed,
    },
    "retention": {
        "RETENTION_MIN_YEARS": constant(retention.RETENTION_MIN_YEARS),
        "RETENTION_MAX_YEARS": constant(retention.RETENTION_MAX_YEARS),
        "retentionDate": retention.retention_date,
        "setRetentionYears": _set_years,
        "placeLegalHold.reason": retention.clean_hold_reason,
        "placeLegalHold.held": _place_held,
        "retentionReport.due": retention.due_for_destruction,
    },
    "legal": {"addMonthsClamped": legal.add_months_clamped, "addDaysIso": legal.add_days_iso},
    "alerte": {
        "FIRST_REPLY_DAYS": constant(alerte.FIRST_REPLY_DAYS),
        "FLOWS": constant(alerte.FLOWS),
        "flowOf": alerte.flow_of,
        "nextStagesOf": alerte.next_stages_of,
        "eventDateOrToday": lambda raw: alerte.event_date_or_today(raw, TODAY),
        "startAlerte": _start,
        "advanceAlerte": _advance,
        "resumeAlerte": alerte.resume_alerte,
    },
    "financial_analysis": {
        "RATIO_KEYS": constant(financial_analysis.RATIO_KEYS),
        "DEFS": constant(financial_analysis.DEFS),
        "financialAnalysis": _financial_analysis_as_source,
        "aggregate": financial_analysis.aggregate,
        "ratioSet": financial_analysis.ratio_set,
    },
    "dataset_mapping": {
        **{n: constant(getattr(dataset_mapping, n)) for n in ("FIELDS", "JE_KEY", "JE_KEY_SEP", "JE_KEY_JOIN", "JE_KEY_MAX")},
        "autoMap": dataset_mapping.auto_map,
        "norm": dataset_mapping.norm,
        "jeKeyColumns": dataset_mapping.je_key_columns,
        "encodeJeKey": dataset_mapping.encode_je_key,
        "jeNumberLooksLikeJournalCode": dataset_mapping.je_number_looks_like_journal_code,
        "jeIdentity": lambda data, cols, header: dataset_mapping.je_identity(data, cols, header, _text),
    },
    "subledger_kinds": {
        "SUB_LEDGER_KINDS": constant(subledger_kinds.SUB_LEDGER_KINDS),
        "isSubLedgerKind": subledger_kinds.is_sub_ledger_kind,
    },
    "itgc_model": {"IT_STRATEGIES": constant(itgc_model.IT_STRATEGIES), "newAppKey": itgc_model.new_app_key},
    "leadsheets": {"resolveSection": leadsheets.resolve_section},
    "subledgers": {
        "parseCsv": lambda text, header: table_out(subledgers.parse_csv(text, header)),
        "detectCsvDelimiter": subledgers.detect_csv_delimiter,
        "splitCsvLine": subledgers.split_csv_line,
        "detectAmountColumn": subledgers.detect_amount_column,
        "parseTabularFile.unsupported": _unsupported,
    },
    "tb": {
        "ALIASES": constant(tb.ALIASES),
        "RESULT_CARRIED_FORWARD": constant(tb.RESULT_CARRIED_FORWARD),
        "inferTbMapping": tb.infer_tb_mapping,
        "normalizeHeader": tb.normalize_header,
        "isAccountCell": tb.is_account_cell,
        "validateMapping": lambda mapping: tb.validate_mapping(mapping),
        "heuristicFill": lambda arg, mapping: tb.heuristic_fill(table(arg), mapping),
        "readabilityOf": lambda arg, mapping: tb.readability_of(table(arg), mapping),
        "extractTbRows": _extract,
        "validateTbRows": _validate_tb,
        "previewTrialBalance": _preview,
        "leadSchedules": tb.lead_schedules,
        "createJournal": _journal,
        "diffTbVersions": tb.diff_tb_versions,
    },
    "tb_reasons": {
        "COLUMN_LABEL": constant(tb_reasons.COLUMN_LABEL),
        "tbStatusLabel": tb_reasons.tb_status_label,
        "explainTbSummary": tb_reasons.explain_tb_summary,
    },
    "engines": {
        "RECON_PREFIXES": constant(engines.RECON_PREFIXES),
        "seededRandom": engines.seeded_random,
        "selectSample": engines.select_sample,
        "evaluateSampling": engines.evaluate_sampling,
        "recordTodResult": engines.record_tod_result,
        "runReconciliation": _recon,
        "reconPreview": engines.recon_preview,
        "runSupplierRecon": engines.run_supplier_recon,
        "runJeTesting": engines.run_je_testing,
        "runSubstantiveAnalytic": engines.run_substantive_analytic,
    },
}


def _load():
    params = []
    for name in sorted(os.listdir(FIXTURES)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
            data = json.load(handle)
        for i, case in enumerate(data["cases"]):
            params.append(pytest.param(data["module"], case, id="%s-%s-%d" % (data["module"], case["fn"], i)))
    return params


@pytest.mark.parametrize("module,case", _load())
def test_parity(module, case):
    adapter = ADAPTERS[module][case["fn"]]
    args = dec(case["args"])
    if "throws" in case:
        with pytest.raises(Exception) as caught:
            adapter(*args)
        assert str(caught.value) == case["throws"]
    else:
        same(adapter(*args), dec(case["out"]))


def test_every_adapter_is_exercised():
    """An adapter nothing recorded for would be a port the fixtures never touched."""
    seen = {}
    for name in sorted(os.listdir(FIXTURES)):
        if name.endswith(".json"):
            with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
                data = json.load(handle)
            seen[data["module"]] = {case["fn"] for case in data["cases"]}
    assert set(seen) == set(ADAPTERS)
    for module, adapters in ADAPTERS.items():
        assert set(adapters) == seen[module], module
