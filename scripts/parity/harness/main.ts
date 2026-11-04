// Every fixture file: the real TypeScript, on a broad input set. Run through
// generate_fixtures.mjs, one module at a time.
import { Recorder } from "./recorder";
import { FakeDb } from "./fakedb";

import * as amount from "@/lib/amount";
import * as mm from "@/lib/materiality-model";
import * as sad from "@/lib/sad-model";
import * as cra from "@/lib/cra-model";
import * as dp from "@/lib/design-procedures-model";
import * as sap from "@/lib/sap-model";
import * as toc from "@/lib/toc-sampling";
import * as tocGrid from "@/lib/toc-grid";
import * as labels from "@/lib/control-labels";
import * as asrt from "@/lib/assertions";
import * as sp from "@/lib/sampling-params";
import * as tod from "@/lib/tod-plan";
import * as lc from "@/lib/lead-classes";
import * as cx from "@/lib/complexity";
import * as std from "@/lib/standards-edition";
import * as em from "@/lib/email-domains";
import * as ret from "@/lib/retention";
import * as legal from "@/lib/legal";
import * as al from "@/lib/alerte";
import * as fa from "@/lib/financial-analysis";
import * as tb from "@/lib/tb";
import * as tr from "@/lib/tb-reasons";
import * as sl from "@/lib/subledgers";
import * as ls from "@/lib/leadsheets";
import * as dm from "@/lib/dataset-mapping";
import * as sk from "@/lib/subledger-kinds";
import * as itgc from "@/lib/itgc-model";
import * as eng from "@/lib/engines";

// A fixed clock, so "today" in the source and in the fixtures is the same day.
const FIXED = Date.UTC(2026, 10, 4, 12, 0, 0);
const RealDate = Date;
class FrozenDate extends RealDate {
  constructor(...args: any[]) {
    if (args.length === 0) super(FIXED);
    else super(...(args as [any]));
  }
  static now() { return FIXED; }
}
(globalThis as any).Date = FrozenDate;

const LOCALES = ["en", "fr"] as const;
const SEEDS = ["seed-1", "E4.1-2025", "", "é€", "a very long seed ".repeat(20)];

/** mulberry32: a plain PRNG, so the broad inputs are the same on every generation. */
function prng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---- JavaScript behaviour the helpers reproduce -----------------------------

function jsHelpers() {
  const r = new Recorder("js_helpers");
  const nums = [0, 0.5, 1.5, 2.5, -0.5, -1.5, -2.5, 0.49999999999999994, 1.005, 1234.565, -1234.565, 4503599627370495.5, 9007199254740993, 1e21, -1e21, 1e-7, 123456789012345680000, 1.7976931348623157e308, 5e-324, 0.1 + 0.2, NaN, Infinity, -Infinity, 1e20, 100, 1.5e300, 0.000001, 1.23e-5];
  const rnd = prng(11);
  for (let i = 0; i < 150; i += 1) nums.push((rnd() - 0.5) * 10 ** Math.floor(rnd() * 14), Math.floor(rnd() * 1e9) / 100);
  for (const n of nums) {
    r.call("Math.round", Math.round, n);
    r.call("Math.floor", Math.floor, n);
    r.call("Math.ceil", Math.ceil, n);
    r.call("String", String, n);
    if (Number.isFinite(n)) r.call("nf_fr", (v: number) => new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(v), n);
  }
  for (const n of [1.005, 2.675, 0.125, 0.375, 1000, 999999.995, 1234567.891, -1234.5, -0.001, 0.004, 0.005, 12, 1e15, 1234.5]) {
    r.call("nf_fr", (v: number) => new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(v), n);
  }
  const ws = "\t\n\u000b\f\r                  　﻿";
  for (const s of [`${ws}abc${ws}`, "\u0085abc\u0085", "\u001cabc\u001f", "​abc", " a b "]) r.call("trim", (x: string) => x.trim(), s);
  const dates = [
    "2025-01-15", "2025-01", "2025", "2025-13-01", "2025-00-10", "2025-02-30", "2025-02-31", "2025-04-31", "2025-01-32", "2024-02-29", "2023-02-29",
    "2025-01-15T10:30:00Z", "2025-01-15T10:30:00", "2025-01-15T10:30", "2025-01-15T10:30:00.123Z", "2025-01-15T10:30:00.1Z", "2025-01-15T10:30:00.12345Z",
    "2025-01-15T24:00:00Z", "2025-01-15T24:00:01Z", "2025-01-15T25:00:00Z", "2025-01-15T10:30:00+01:00", "2025-01-15T10:30:00-0500", "2025-01-15T10:60:00Z",
    "2025-01-15 10:30", "2025-01-15 10:30:45", "2025-01-15 10:30:45 PM", "2025-01-15 22:30 PM", "2025/01/15", "2025/1/5", "01/15/2025", "1/5/2025", "15/01/2025", "13/13/2025", "1/5", "1/5/25", "1/5/75",
    "Jan 15 2025", "January 15, 2025", "15 Jan 2025", "15 January 2025", "15-Jan-2025", "Jan-15-2025", "2025 Jan 15", "Janvier 15 2025", "Mars 2025", "15 Foo 2025", "Foo 15 2025", "Fev 15 2025",
    "Mon Jan 15 2025", "Wed, 15 Jan 2025 10:30:00 GMT", "Wed, 15 Jan 2025 10:30:00 +0100", "15 Jan 2025 10:30 UTC", "15 Jan 2025 10:30 PST", "Jan 15 2025 10:30 pm", "Jan 15 2025 12:30 am",
    "", " ", "abc", "null", "undefined", "12", "0", "1", "13", "32", "2025-1-5", "2025-01-5", "20250115", "2025.01.15", "15.01.2025", "1.5.2025", "2025-01-15T", "2025-01-15Z", "2025-01-15 Z",
    "+002025-01-15", "-000001-01-01", "-000000-01-01", "+275760-09-13T00:00:00.000Z", "+275760-09-13T00:00:00.001Z", " 2025-01-15", "2025-01-15 ", "(comment) 2025-01-15", "2025-01-15 (comment)",
    "12:30", "10:30 2025-01-15", "1 2 3 4", "2025-01-15-05", "Sat Mar 1", "T10:00", "1e3", "45000", "12/31/99", "12/31/1999 23:59:59", "00/00/2000", "2000-00-00",
    "2025-06-15T00:00:00.000+00:00", "0099-01-01", "0000-01-01", "0049-12-31",
  ];
  for (const s of dates) r.call("Date.parse", (x: string) => Date.parse(x), s);
  for (const s of ["2024-02-29T00:00:00Z", "2025-01-15T12:00:00Z", "0050-06-15T00:00:00Z"]) {
    r.call("toISOString", (x: string) => new Date(x).toISOString(), s);
    r.call("getDay", (x: string) => new Date(x).getDay(), s);
  }
  const words = ["a", "b", "A", "B", "é", "e", "E", "É", "1", "2", "10", "9", "-", "_", " ", "a1", "a10", "a2", "K-1", "K-10", "K-2", "K-6", "E-1", "VD1-1", "VD1-2", "VD2-1", "T-1", "P1-1", "P1-2", "1000", "2100", "ABCD", "abcd", "Comp", "x-1", "411", "4111", "41 1"];
  for (const a of words) for (const b of words) {
    r.call("localeCompare", (x: string, y: string) => x.localeCompare(y), a, b);
    r.call("localeCompare_numeric", (x: string, y: string) => x.localeCompare(y, undefined, { numeric: true }), a, b);
  }
  for (const s of ["A$&B", "$$", "$`x$'", "plain", "$1", "$"]) r.call("replaceAll", (x: string) => "a{K}b{K}c".replaceAll("{K}", x), s);
  r.write();
}

function amountCases() {
  const r = new Recorder("amount");
  const inputs: unknown[] = [
    "1 500 000,75", "1,500,000.75", "1.500.000,75", "12 345,678", "1,500", "1.500", "1,5", "1.5", "1.50", "1,50", "1 500", "1 500,75", "1 500,75", "1 500", "1\t500",
    "(1 234,56)", "(1,234.56)", "1 234,56-", "-1 234,56", "+1 234,56", "−1 234,56", "(-5)", "(5)-", "-(5)", "--5", "5+", "5-3", "1-2-3", "(5", "5)",
    "N/A", "n/a", "voir note 3", "abc", "1,5 FCFA", "1 500 FCFA", "F CFA 1 500", "FCFA1500", "XAF 1 500", "XOF1500", "EUR 12,50", "12,50 €", "$1,234.56", "£12", "USD 5", "gbp 7", "F 12", "1500F", "1500 f", "CFA 5", "fcfa 5", "12 EURO", "12 kg", "é5", "5é",
    "", " ", " ", ".", ",", ",,", "..", ".,", "0", "0.0", "-0", "0,00", "000", "007", ".5", ",5", "5.", "5,", "1.", "1,", "1.,", "1,.", "1.2.3", "1,2,3", "1.2,3", "1,2.3", "1,234,567", "1.234.567", "1,234.567,89",
    "1,000.5", "1.000,5", "1000,000", "1000.000", "1 000,000", "1 000.000", "1,2345", "1.2345", "12,34,56", "%", "50%", "12%", "#", "1#2", "1/2", "1:2", "(", ")", "()", "( )", "(1)(2)", "1e5", "1E5", "1e", "Infinity", "NaN",
    "1".repeat(400), "9".repeat(20), "0." + "1".repeat(30), "99999999999999999999,99",
    "\n5\n", "(1\n2)", " 5 ", "﻿5", "\u00855", "​5", "٣", "५", "１２", "5 ",
    0, 1, -1, 1.5, -1.5, 1e21, NaN, Infinity, -Infinity, 1234567.891, null, undefined, true, false, [5], [], ["1", "2"], {},
  ];
  const rnd = prng(7);
  for (let i = 0; i < 120; i += 1) {
    const v = (rnd() * 10 ** Math.floor(rnd() * 10)).toFixed(Math.floor(rnd() * 4));
    const [w, f] = v.split(".");
    const grouped = (sep: string) => w.replace(/\B(?=(\d{3})+(?!\d))/g, sep);
    inputs.push(`${grouped(" ")}${f ? "," + f : ""}`, `${grouped(",")}${f ? "." + f : ""}`, `${grouped(".")}${f ? "," + f : ""}`, `(${grouped(" ")}${f ? "," + f : ""})`, `${grouped(" ")}${f ? "." + f : ""}-`);
  }
  for (const v of inputs) {
    r.call("parseAmount", amount.parseAmount, v);
    r.call("amountOr", amount.amountOr, v, 42);
  }
  r.write();
}

function materialityCases() {
  const r = new Recorder("materiality_model");
  r.value("PERFORMANCE_PCT_RANGE", [], mm.PERFORMANCE_PCT_RANGE);
  r.value("TRIVIAL_PCT_RANGE", [], mm.TRIVIAL_PCT_RANGE);
  for (const m of [null, undefined, { overall: 1000000, performance: 750000 }, { overall: 400000, performance: 500000 }, { overall: 1000.1, performance: 750.2 }, { overall: 0.3, performance: 0.1 }, { overall: 0, performance: 0 }]) {
    r.call("uncorrectedMisstatementThreshold", mm.uncorrectedMisstatementThreshold, m);
  }
  for (const b of ["pbt", "revenue", "total_assets", "equity", "expenses", "other", ""]) for (const fr of [true, false]) r.call("benchmarkLabel", mm.benchmarkLabel, b, fr);
  r.write();
}

function sadCases() {
  const r = new Recorder("sad_model");
  for (const name of ["SAD_CAPTIONS", "SAD_CAPTION_LABELS", "SAD_TYPES", "MISSTATEMENT_TYPE_LABELS", "SAD_COLUMN_COUNT", "SAD_QUAL_FACTORS"]) r.value(name, [], (sad as any)[name]);
  for (const c of sad.SAD_CAPTIONS) r.call("captionColumn", sad.captionColumn, c);
  const accounts = ["", "abc", "0", "9", "90", "8", "80", "81", "82", "83", "84", "85", "86", "87", "88", "89", "8-1", "  41-1 ", "A4 1"];
  for (let d = 10; d < 100; d += 1) accounts.push(String(d), `${d}1000`);
  for (const a of accounts) r.call("suggestCaption", sad.suggestCaption, a);
  r.write();
}

function craCases() {
  const r = new Recorder("cra_model");
  r.value("CR_DEFICIENT_BASIS", [], cra.CR_DEFICIENT_BASIS);
  for (const ir of ["lower", "higher"] as const) for (const c of ["rely", "not_rely"] as const) r.call("craOf", cra.craOf, ir, c);
  const levels = ["minimal", "low", "moderate", "high"] as const;
  const tods = ["minimal", "low", "low_sr", "moderate", "high", "high_sr"] as const;
  for (const l of levels) {
    for (const s of [true, false]) r.call("toTod", cra.toTod, l, s);
    r.call("craTone", cra.craTone, l);
    for (const loc of LOCALES) {
      r.call("craLevelLabel", cra.craLevelLabel, l, loc);
      r.call("thresholdSuggestion", cra.thresholdSuggestion, l, loc);
      r.call("timingSuggestion", cra.timingSuggestion, l, loc);
    }
  }
  for (const t of tods) for (const loc of LOCALES) r.call("todLabel", cra.todLabel, t, loc);
  for (const a of tods) for (const b of tods) r.call("worstTod", cra.worstTod, [a, b]);
  r.call("worstTod", cra.worstTod, []);
  r.call("worstTod", cra.worstTod, ["minimal", "moderate", "low"]);
  r.call("worstTod", cra.worstTod, ["low_sr", "high", "minimal", "high_sr", "low"]);
  for (const b of [cra.CR_DEFICIENT_BASIS, `x · ${cra.CR_DEFICIENT_BASIS} · y`, "free text", ""]) for (const loc of LOCALES) r.call("crBasisLabel", cra.crBasisLabel, b, loc);
  r.call("cellsToAssess", cra.cellsToAssess, []);
  r.call("cellsToAssess", cra.cellsToAssess, [
    { indexCode: "E", cells: [{ assertion: "C", relevant: true, ir: null, cr: "rely" }, { assertion: "E", relevant: true, ir: "lower", cr: null }, { assertion: "A", relevant: false, ir: null, cr: null }, { assertion: "V", relevant: true, ir: "lower", cr: "rely" }] },
    { indexCode: "K", cells: [{ assertion: "RO", relevant: true, ir: null, cr: null }, { assertion: "P", relevant: true }] },
  ]);
  r.write();
}

function designCases() {
  const r = new Recorder("design_procedures_model");
  for (const name of ["NATURE_OPTIONS", "TIMING_OPTIONS", "NATURE_VALUES", "TIMING_VALUES", "OSP_MAX", "OSP_TEXT_MAX", "OSP_EXTENT_MAX", "ASSERTIONS"]) r.value(name, [], (dp as any)[name]);
  for (const l of ["minimal", "low", "moderate", "high", null]) r.call("timingAllowed", dp.timingAllowed, l);
  for (const t of ["minimal", "low", "low_sr", "moderate", "high", "high_sr"]) r.call("craLevelOf", dp.craLevelOf, t);
  for (const id of ["abc", "A_b-9", "", "a".repeat(40), "a".repeat(41), "a b", "é", "abc\n", "a.b"]) r.call("OSP_ID.test", (x: string) => dp.OSP_ID.test(x), id);
  r.write();
}

function sapCases() {
  const r = new Recorder("sap_model");
  for (const name of ["DEFAULT_SAP_THRESHOLDS", "SAP_PCT_MIN", "SAP_PCT_MAX", "SAP_ASSERTIONS"]) r.value(name, [], (sap as any)[name]);
  for (const a of sap.SAP_ASSERTIONS) for (const loc of LOCALES) r.call("sapAssertionLabel", sap.sapAssertionLabel, a, loc);
  for (const v of ["C", "E", "A", "V", "P", "RO", "", null, 1]) r.call("isSapAssertion", sap.isSapAssertion, v);
  for (const v of [0, 1, 50, 100, 101, 1.5, 50.0, -1, "50", null, true, NaN, Infinity]) r.call("isSapPct", sap.isSapPct, v);
  for (const l of ["minimal", "low", "moderate", "high", null]) {
    r.call("thresholdPctFor", sap.thresholdPctFor, l, sap.DEFAULT_SAP_THRESHOLDS);
    r.call("thresholdPctFor", sap.thresholdPctFor, l, { low: 60, moderate: 40, high: 10 });
  }
  const rnd = prng(23);
  const args: any[] = [
    { expected: 100, actual: null, performanceMateriality: 1000, pct: 50 },
    { expected: 100, actual: 200, performanceMateriality: null, pct: 50 },
    { expected: 100, actual: null, performanceMateriality: null, pct: 50 },
    { expected: 0, actual: 500, performanceMateriality: 1000, pct: 50 },
    { expected: 0, actual: 501, performanceMateriality: 1000, pct: 50 },
    { expected: 0.5, actual: 1, performanceMateriality: 1, pct: 50 },
    { expected: 1, actual: 0.5, performanceMateriality: 3, pct: 50 },
    { expected: 2.5, actual: 0, performanceMateriality: 3, pct: 25 },
  ];
  for (let i = 0; i < 120; i += 1) args.push({ expected: Math.round(rnd() * 1e9) / 100, actual: Math.round(rnd() * 1e9) / 100, performanceMateriality: Math.round(rnd() * 1e8) / 10, pct: 1 + Math.floor(rnd() * 100) });
  for (const a of args) r.call("evaluateSap", sap.evaluateSap, a);
  r.write();
}

function labelsCases() {
  const r = new Recorder("control_labels");
  r.value("CONTROL_FREQUENCIES", [], labels.CONTROL_FREQUENCIES);
  for (const fr of [true, false]) {
    for (const v of ["daily", "weekly", "monthly", "quarterly", "semi_annually", "annually", "x", null, undefined]) r.call("freqLabel", labels.freqLabel, v, fr);
    for (const v of ["manual", "it_dependent", "automated", "x", null]) r.call("typeShort", labels.typeShort, v, fr);
    for (const v of ["prevent", "detect", "x", null]) r.call("objectiveLabel", labels.objectiveLabel, v, fr);
    for (const v of ["routine", "non_routine", "estimation", "x", null]) r.call("transactionTypeLabel", labels.transactionTypeLabel, v, fr);
  }
  r.write();
}

function assertionsCases() {
  const r = new Recorder("assertions");
  r.value("ASSERTIONS", [], asrt.ASSERTIONS);
  r.value("ASSERTION_LABELS", [], asrt.ASSERTION_LABELS);
  for (const v of ["C", "RO", "X", "", null, 1]) r.call("isAssertion", asrt.isAssertion, v);
  for (const v of [["C", "E", "C", "X", "RO", 1, null], [], "C", null]) r.call("cleanAssertions", asrt.cleanAssertions, v);
  for (const c of ["C", "E", "A", "V", "P", "RO", "X"]) for (const loc of LOCALES) {
    r.call("assertionName", asrt.assertionName, c, loc);
    r.call("assertionLabel", asrt.assertionLabel, c, loc);
  }
  for (const loc of LOCALES) r.call("assertionLabels", asrt.assertionLabels, ["C", "X", "RO"], loc);
  r.write();
}

function tocCases() {
  const r = new Recorder("toc_sampling");
  r.value("TOC_EXTENDED_SIZE", [], toc.TOC_EXTENDED_SIZE);
  const freqs = ["daily", "Daily", "weekly", "Hebdomadaire", "monthly", "Mensuel", "quarterly", "Trimestriel", "semi_annually", "Semestriel", "Semi-annually", "annually", "Annuel", "Journalier", "Many times a day", "continuous", "bimensuel", "biannually", "semi-monthly", "x", "", null, "AD HOC"];
  for (const f of freqs) r.call("normFreq", toc.normFreq, f);
  for (const t of ["automated", "manual", "it_dependent"]) for (const f of freqs) for (const p of [null, 0, 1, 3, 4, 5, 49, 50, 110, 250, 251, 650, 2.5]) for (const sole of [true, false]) for (const fr of [true, false]) {
    r.call("tocSuggested", toc.tocSuggested, t, f, p, sole, fr);
  }
  // the 10% band across the whole range: a float product can land just above the integer
  for (let p = 50; p <= 250; p += 1) r.call("tocSuggested", toc.tocSuggested, "manual", "daily", p, false, false);
  for (const plan of [0, 1, 2, 5, 25, 26, 60]) for (const tested of [0, 5, 25, 59, 60, 61]) for (const dev of [-1, 0, 1, 2, 3]) r.call("tocEvaluate", toc.tocEvaluate, plan, tested, dev);
  for (const g of [null, undefined, {}, { rows: "x" }, { rows: [] }, { rows: [{}] }, { rows: [{ results: {} }] }, { rows: [{ results: { a: "" } }] }, { rows: [{ results: { a: "pass" } }] }, { rows: [{ results: { a: "" } }, { results: { b: "fail" } }] }, { rows: [{ results: { a: 1 } }] }, { rows: [null, { results: { a: "x" } }] }]) {
    r.call("tocTestingStarted", toc.tocTestingStarted, g);
  }
  // seeded draws through the real generator chain
  for (const seed of SEEDS) for (const [population, size] of [[650, 25], [100, 10], [3, 5], [0, 5], [10, 0], [1, 1], [2.9, 1.9], [60, 60], [1000000, 60], [250, 25], [-3, 2]]) {
    r.call("drawTocSample", (p: number, s: number, sd: string) => toc.drawTocSample(p, s, toc.seededRng(sd, eng.seededRandom)), population, size, seed);
  }
  r.write();
}

function tocGridCases() {
  const r = new Recorder("toc_grid");
  for (const v of [null, undefined, 0, -1, 5, 2.5, 3.5, NaN, Infinity, "5"]) r.call("tocRowsPlanned", tocGrid.tocRowsPlanned, v);
  for (const g of [null, undefined, {}, { attributes: [], rows: [] }, { attributes: ["a"], rows: "x" }, { rows: [{ results: {} }] }, { attributes: ["a"], rows: [{ results: {} }] }, { attributes: ["a", "b"], rows: [{ results: { a: "pass", b: "fail" } }, { results: { a: "pass", b: "" } }, { results: { a: "n/a" } }, {}] }]) {
    r.call("tocRowsTested", tocGrid.tocRowsTested, g);
  }
  r.write();
}

function samplingParamsCases() {
  const r = new Recorder("sampling_params");
  for (const name of ["RISK_BAND_CONFIDENCE", "ATTRIBUTE_SAMPLE_SIZES"]) r.value(name, [], (sp as any)[name]);
  for (const [k, v] of Object.entries(sp.CONFIDENCE_FACTORS)) r.value("CONFIDENCE_FACTORS", [Number(k)], v);
  for (const b of ["high", "moderate", "low"] as const) r.call("riskBandToConfidence", sp.riskBandToConfidence, b);
  for (const f of ["daily", "weekly", "monthly", "quarterly", "annual", "automated"] as const) r.call("attributePlan", sp.attributePlan, f);
  for (const s of [1, 9, 10, 29, 30, 59, 60, 100]) for (const d of [0, 1, 2, 3, 10]) r.call("evaluateAttribute", sp.evaluateAttribute, s, d);
  const rnd = prng(31);
  const plans: any[] = [
    { populationValue: 1000, tolerable: 0, confidence: 95 }, { populationValue: 0, tolerable: 100, confidence: 95 }, { populationValue: -1, tolerable: 100, confidence: 95 },
    { populationValue: 1000, tolerable: 100, confidence: 94 }, { populationValue: 1000, tolerable: 100, expected: 100, confidence: 95 }, { populationValue: 1000, tolerable: 100, expected: 99, confidence: 95 },
    { populationValue: 1, tolerable: 1000000, confidence: 50 }, { populationValue: 1000, tolerable: 100, confidence: 95 }, { populationValue: 12345678.9, tolerable: 1500000, confidence: 85 },
    { populationValue: 3, tolerable: 1, confidence: 99 }, { tolerable: 100, confidence: 95 }, { populationValue: 100, confidence: 95 },
    { populationValue: 100, tolerable: 10, confidence: "95" },
  ];
  const confs = Object.keys(sp.CONFIDENCE_FACTORS).map(Number);
  for (let i = 0; i < 200; i += 1) plans.push({ populationValue: Math.round(rnd() * 1e11) / 100, tolerable: 1 + Math.round(rnd() * 1e8) / 10, expected: i % 3 === 0 ? Math.round(rnd() * 1000) : undefined, confidence: confs[i % confs.length] });
  for (const p of plans) r.call("musPlan", sp.musPlan, p);
  r.call("projectMLE", sp.projectMLE, [], 1000, 100);
  r.call("projectMLE", sp.projectMLE, [], 1000, 0);
  r.call("projectMLE", sp.projectMLE, [{ bookValue: 0, auditedValue: 50 }], 1000, 100);
  r.call("projectMLE", sp.projectMLE, [{ bookValue: 0, auditedValue: 50 }], 1000, 0);
  r.call("projectMLE", sp.projectMLE, [{ bookValue: 100, auditedValue: 90 }, { bookValue: 0, auditedValue: 5 }], 1000, 100);
  r.call("projectMLE", sp.projectMLE, [{ bookValue: 1, auditedValue: 0.5 }], 3, 0);
  for (let i = 0; i < 80; i += 1) {
    const items = Array.from({ length: 1 + Math.floor(rnd() * 8) }, () => ({ bookValue: Math.round(rnd() * 1e7) / 100, auditedValue: Math.round(rnd() * 1e7) / 100 }));
    r.call("projectMLE", sp.projectMLE, items, Math.round(rnd() * 1e10) / 100, Math.round(rnd() * 1e7) / 100);
  }
  r.write();
}

function todCases() {
  const r = new Recorder("tod_plan");
  for (const name of ["TOD_CRAS", "TOD_ASSURANCES", "ART_COLS", "ART_MUS"]) r.value(name, [], (tod as any)[name]);
  for (const parts of [[], ["a"], ["a", "b"], ["engagement-1", "E", "abcdef"], ["é€", "😀"], ["", ""], ["x".repeat(500)]]) r.call("stableStartFraction", (...p: string[]) => tod.stableStartFraction(...p), ...parts);
  const rnd = prng(41);
  for (let i = 0; i < 200; i += 1) r.call("stableStartFraction", (...p: string[]) => tod.stableStartFraction(...p), String(rnd()), String(i));
  const line = (ref: string, amount: number, account = "411100") => ({ ref, account, amount });
  const LINES = [line("A", 5000000), line("B", 2000000), ...Array.from({ length: 30 }, (_, i) => line(`S${i + 1}`, 100000 * (i + 1)))];
  const inputs: any[] = [
    { lines: LINES, te: 1500000, threshold: 1000000, cra: "moderate", assurance: "little", startFraction: 0.5 },
    { lines: LINES, te: 1000000, threshold: 4000000, cra: "high_sr", assurance: "little", startFraction: 0.25 },
    { lines: [line("BIG", 9000000), ...Array.from({ length: 30 }, (_, i) => line(`S${i + 1}`, 10000))], te: 1000000, threshold: 20000000, cra: "high_sr", assurance: "little", startFraction: 0.1 },
    { lines: Array.from({ length: 11 }, (_, i) => line(`L${i + 1}`, 1000000)), te: 1375000, threshold: 2000000, cra: "minimal", assurance: "little", startFraction: 0.9 },
    { lines: [...LINES, line("Z", 0), line("N", -5)], te: 2500000, cra: "low", assurance: "some", startFraction: 0 },
    { lines: LINES, te: 500000, threshold: 10000000, cra: "moderate", assurance: "some", startFraction: 0.4 },
    { lines: [], te: 100, cra: "low", assurance: "little", startFraction: 0 },
    { lines: LINES, te: 0, cra: "low", assurance: "little", startFraction: 0 },
    { lines: LINES, te: 1000, threshold: 1234.5, cra: "high", assurance: "persuasive", startFraction: 5 },
    { lines: LINES, te: 1000, threshold: -5, cra: "high", assurance: "little", startFraction: -1 },
    { lines: [line("n", NaN), line("i", Infinity), line("ok", 10)], te: 1, threshold: 100, cra: "high", assurance: "little", startFraction: 0.3 },
    { lines: [line("a", 0.1), line("b", 0.2), line("c", 0.7)], te: 0.25, threshold: 5, cra: "high_sr", assurance: "little", startFraction: 0.5 },
  ];
  for (let i = 0; i < 150; i += 1) {
    const n = 1 + Math.floor(rnd() * 60);
    const lines = Array.from({ length: n }, (_, k) => line(`R${k}`, Math.round(rnd() * rnd() * 1e9) / 100));
    inputs.push({
      lines,
      te: 1000 + Math.round(rnd() * 1e7),
      threshold: i % 4 === 0 ? undefined : Math.round(rnd() * 1e7 * 100) / 100,
      cra: tod.TOD_CRAS[i % 6],
      assurance: tod.TOD_ASSURANCES[Math.floor(rnd() * 4)],
      startFraction: rnd(),
    });
  }
  for (const input of inputs) r.call("planTod", tod.planTod, input);
  r.write();
}

function leadCases() {
  const r = new Recorder("lead_classes");
  for (const name of ["LEAD_INDEXES", "ACCOUNT_CLASSES", "PREFIX_INDEX", "SUB_INDEXES", "PREFIX_SUB", "INDEX_SECTION", "ACCOUNT_TYPE_FR", "ACCOUNT_CLASS_FR"]) r.value(name, [], (lc as any)[name]);
  const accounts = ["", "x", "0", "9", "3", "5", "39", "59", "490", "4901000", "491", "4911", "292", "295", "2921", "2951", "291", "296", "499", "4991", "498", "2010000", "2110000", "281", "28", "462", "4621", "476", "477", "478", "479", "481", "444", "445", "449", "603", "604", "605", "608"];
  for (let d = 10; d < 100; d += 1) accounts.push(String(d), `${d}0`, `${d}1`, `${d}5`, `${d}9`, `${d}10000`);
  for (const a of accounts) {
    r.call("leadIndexFor", lc.leadIndexFor, a);
    r.call("subIndexFor", lc.subIndexFor, a);
  }
  for (const d of lc.LEAD_INDEXES) for (const loc of LOCALES) {
    r.call("leadIndexLabel", lc.leadIndexLabel, d, loc);
    r.call("accountTypeLabel", lc.accountTypeLabel, d.accountType, loc);
    r.call("accountClassLabel", lc.accountClassLabel, d.accountClass, loc);
  }
  for (const loc of LOCALES) {
    r.call("accountTypeLabel", lc.accountTypeLabel, "Nope", loc);
    r.call("accountClassLabel", lc.accountClassLabel, "Nope", loc);
  }
  for (const d of lc.SUB_INDEXES) for (const loc of LOCALES) r.call("subIndexLabel", lc.subIndexLabel, d, loc);
  for (const c of [...lc.ACCOUNT_CLASSES, "Nope"]) r.call("defaultIndexForClass", lc.defaultIndexForClass, c);
  for (const a of [
    [], [{ account: "4901000", closing: 0 }], [{ account: "4901000", closing: 5 }], [{ account: "2010000", closing: -3 }], [{ account: "2110000", closing: 8000000 }],
    [{ account: "4901000", closing: 5 }, { account: "4902", closing: 1 }, { account: "2010000", closing: 2 }, { account: "20", closing: 0 }, { account: "4011000", closing: 7 }],
  ]) r.call("leadScheduleAlerts", lc.leadScheduleAlerts, a);
  r.write();
}

function complexityCases() {
  const r = new Recorder("complexity");
  for (const name of ["COMPLEXITY_QUESTIONS", "DEFAULT_ENGAGEMENT_NAMING", "YEAR_END_OPTIONS", "DURATION_OPTIONS", "NATURE_OPTIONS", "ENGAGEMENT_PHASE_OPTIONS", "FRAMEWORK_OPTIONS"]) r.value(name, [], (cx as any)[name]);
  const keys = cx.COMPLEXITY_QUESTIONS.map((q) => q.key);
  r.call("classifyComplexity", cx.classifyComplexity, {});
  for (const k of keys) r.call("classifyComplexity", cx.classifyComplexity, { [k]: true });
  const rnd = prng(53);
  for (let i = 0; i < 200; i += 1) {
    const answers: Record<string, boolean> = {};
    for (const k of keys.slice(i % 2 ? 3 : 0)) answers[k] = rnd() < 0.3;
    r.call("classifyComplexity", cx.classifyComplexity, answers);
  }
  r.call("answersFromForm", (set: string[]) => cx.answersFromForm((n) => (set.includes(n) ? "on" : null)), ["q_listed", "q_estimates", "q_other"]);
  const clients = ["Zoeden", "  acme sa  ", "é ß", "A$&B", "$$", "x".repeat(130), "", "😀".repeat(70)];
  const patterns = ["", "{CLIENT}_{PERIOD_END}_{NATURE}", "{YEAR}-{CLIENT}", "{CLIENT} {CLIENT}", "plain", "  {NATURE}  ", "{PERIOD_END}"];
  const parts = [undefined, {}, { periodEnd: "2026-12-31" }, { periodEnd: "2026-06-30", nature: "agreed_procedures" }, { periodEnd: "2026-02-28", nature: "free_text" }, { periodEnd: "2026-13-40" }, { periodEnd: "12-31" }, { periodEnd: "garbage" }, { nature: "other" }];
  for (const c of clients) for (const pat of patterns) for (const p of parts) for (const loc of LOCALES) for (const y of [2026, "2026"]) {
    r.call("applyNamingConvention", cx.applyNamingConvention, pat, c, y, p, loc);
  }
  for (const c of clients) for (const ye of ["12-31", "06-30", "07-31", "03-31", "02-28", "00-10", "13-01", "1-1", "x"]) for (const n of ["statutory_audit", "agreed_procedures", "other", "free_text_here", ""]) {
    r.call("generateEngagementName", cx.generateEngagementName, c, ye, 2026, n);
  }
  for (const md of ["12-31", "06-30", "01-05", "00-05", "13-05", "abc", "", "02-30"]) for (const loc of LOCALES) r.call("periodEndLabel", cx.periodEndLabel, md, loc);
  for (const n of ["statutory_audit", "agreed_procedures", "other", "a_b_c"]) for (const loc of LOCALES) r.call("natureLabel", cx.natureLabel, n, loc);
  r.write();
}

function standardsCases() {
  const r = new Recorder("standards_edition");
  r.value("STANDARDS_EDITIONS", [], std.STANDARDS_EDITIONS);
  r.value("REVISED_2026_FROM", [], std.REVISED_2026_FROM);
  r.value("ISA_REF_KEYS", [], std.ISA_REF_KEYS);
  for (const v of ["current", "revised_2026", "x", null, 1]) r.call("isStandardsEdition", std.isStandardsEdition, v);
  const ends = ["2026-12-31", "2027-06-30", "2027-03-31", "2027-05-30", "2027-05-31", "2024-02-29", "2024-02-28", "2023-02-28", "2026-12-14", "2027-12-14", "2027-11-30", "2027-08-31", "2028-02-29", "not a date", "", "2026-13-40", "2026-02-30", "2026-12-31T23:59:59Z", "0050-06-15", "2026-1-1"];
  for (const e of ends) for (const d of [undefined, null, 0, -3, 1, 2.9, 3, 6, 12, 13, 18, 24, 120, NaN]) {
    r.call("periodStartOf", std.periodStartOf, e, d);
    r.call("editionForPeriod", std.editionForPeriod, e, d);
  }
  for (const s of ["2026-12-14", "2026-12-15", "2027-01-01", "", null, undefined, "2026-12-15T00:00:00Z", "garbage"]) r.call("defaultStandardsEdition", std.defaultStandardsEdition, s);
  for (const ed of std.STANDARDS_EDITIONS) for (const loc of LOCALES) {
    r.call("editionLabel", std.editionLabel, ed, loc);
    r.call("editionLine", std.editionLine, ed, loc);
    for (const k of std.ISA_REF_KEYS) r.call("isaRef", std.isaRef, ed, k, loc);
    for (const t of ["plain", "see {{ISA240.jeTesting}} and {{ISA570}}", "{{Nope.key}}", "{{}}", "{{ISA570}", "{ {ISA570} }", "{{ISA570}}{{ISA240}}", "{{ isa }}"]) r.call("resolveText", std.resolveText, t, ed, loc);
  }
  for (const t of ["plain", "{{ISA570}}", "{{Nope.key}}", "{{}}", "{{a b}}"]) r.call("hasUnresolvedToken", std.hasUnresolvedToken, t);
  const paper: any = { code: "S4.2", en: "see {{ISA570}}", fr: "voir {{ISA570}}", srcFr: "{{ISA240.jeTesting}}", srcEn: "{{ISA240.jeTesting}}", n: 5, flag: true, none: null, list: ["{{ISA570.horizon}}", { fr: "{{ISA570.horizon}}", tip: "{{ISA570.horizon}}", tipFr: "{{ISA570.horizon}}" }, ["{{ISA240}}"]], nested: { fr: { en: "{{ISA570}}", plain: "{{ISA570}}" }, reqFr: ["{{ISA570}}"] } };
  for (const ed of std.STANDARDS_EDITIONS) r.call("resolvePaper", std.resolvePaper, paper, ed);
  r.write();
}

function emailCases() {
  const r = new Recorder("email_domains");
  for (const raw of ["ECA.com\n@eca-cm.com, eca.com", "  ", "", "not a domain!", "a.b", "a.co;b.co c.co\td.co", ",,a.co,,", "@@a.co", "a.c", "a-.co", "-a.co", "a_b.co", "é.co", "a.co.", ".a.co", "a..co", "1.2.3.co", "a.c0", "x".repeat(64) + ".co", "x".repeat(63) + ".co", (("a".repeat(60) + ".").repeat(4)) + "co", (("a".repeat(62) + ".").repeat(4)) + "com", "z.co\ny.co x.co﻿w.co", "A.CO a.co", "K.co"]) {
    r.call("parseDomainList", em.parseDomainList, raw);
  }
  for (const e of ["a@b.co", "A@B.CO", "  a@b.co  ", "a@", "@b.co", "ab.co", "", "a@b@c.co", "a@B.co ", "😀@x.co", "﻿a@b.co"]) {
    r.call("emailDomain", em.emailDomain, e);
    for (const list of [[], ["b.co"], ["B.CO"], ["c.co", "b.co"], ["eca.com"]]) r.call("emailDomainAllowed", em.emailDomainAllowed, e, list);
  }
  for (const e of ["x@eca.com", "x@ECA.com", "x@audit.eca.com", "x@eca.com.attacker.net", "x@xeca.com"]) r.call("emailDomainAllowed", em.emailDomainAllowed, e, ["eca.com"]);
  r.write();
}

async function retentionCases() {
  const r = new Recorder("retention");
  r.value("RETENTION_MIN_YEARS", [], ret.RETENTION_MIN_YEARS);
  r.value("RETENTION_MAX_YEARS", [], ret.RETENTION_MAX_YEARS);
  const dates = ["2026-04-30", "2025-12-31", "2024-02-29", "2020-02-29", "2023-02-28", "2025-02-30", "garbage", "", "2025-13-01"];
  for (const report of [null, ...dates]) for (const end of ["2025-12-31", "2024-02-29"]) for (const y of [10, 11, 30, 4, 0, -1]) r.call("retentionDate", ret.retentionDate, report, end, y);
  for (const y of [9, 10, 11, 30, 31, 10.5, 10.0, NaN, Infinity, -10, 0]) {
    new FakeDb();
    await r.acall("setRetentionYears", () => ret.setRetentionYears(y), [y]);
  }
  for (const h of ["  ", "", " dispute ", " ﻿"]) {
    new FakeDb([[/^SELECT 1 FROM legal_hold/, { rows: [] }], [/INSERT INTO legal_hold/, { rows: [{ id: "hold-1" }] }]]);
    await r.acall("placeLegalHold.reason", async () => { await ret.placeLegalHold("e", h); return h.trim(); }, [h]);
  }
  new FakeDb([[/^SELECT 1 FROM legal_hold/, { rows: [{}] }]]);
  await r.acall("placeLegalHold.held", async () => ret.placeLegalHold("e", "x"), [true]);
  new FakeDb([[/^SELECT 1 FROM legal_hold/, { rows: [] }], [/INSERT INTO legal_hold/, { rows: [{ id: "hold-1" }] }]]);
  await r.acall("placeLegalHold.held", async () => { await ret.placeLegalHold("e", "x"); return null; }, [false]);
  const report = [
    ["2025-01-01", false], ["2026-11-04", false], ["2026-11-05", false], ["2026-11-04", true], [null, false], ["2020-01-01", true],
  ] as const;
  for (const [until, held] of report) {
    new FakeDb([[/FROM engagement e JOIN client/, { rows: [{ id: "e", client_name: "c", name: null, fiscal_year: 2020, archived_at: null, retention_until: until, held }] }]]);
    await r.acall("retentionReport.due", async () => (await ret.retentionReport())[0].dueForDestruction, [until, held, "2026-11-04"]);
  }
  r.write();
}

function legalCases() {
  const r = new Recorder("legal");
  for (const iso of ["2025-12-31", "2025-01-15", "2024-02-29", "2025-08-31", "2025-01-31", "2025-02-30"]) for (const m of [0, 1, 2, 4, 6, 12, -1, -13, 25]) r.call("addMonthsClamped", legal.addMonthsClamped, iso, m);
  for (const iso of ["2026-06-15", "2024-02-29", "2025-12-31", "2025-02-30", "2025-02-31", "2025-13-01", "garbage", ""]) for (const d of [0, 1, 8, 15, 30, -45, 366]) r.call("addDaysIso", legal.addDaysIso, iso, d);
  r.write();
}

const TODAY = "2026-11-04";

/** What the real buildStageLetter and fileUnderCode read while filing a letter. */
const LETTER_RULES: [RegExp, { rows: any[] }][] = [
  [/FROM tenant WHERE id/, { rows: [{ name: "Firm", branding: {} }] }],
  [/FROM file_item/, { rows: [{ id: "fi-1" }] }],
  [/coalesce\(max\(version_no\)/, { rows: [{ v: 1 }] }],
  [/RETURNING id/, { rows: [{ id: "doc-1" }] }],
];

async function alerteCases() {
  const r = new Recorder("alerte");
  r.value("FIRST_REPLY_DAYS", [], al.FIRST_REPLY_DAYS);
  r.value("FLOWS", [], al.FLOWS);
  const allStages = ["request_sent", "reply_recorded", "court_informed", "board_invited", "board_deliberated", "rapport_special", "ag_communicated", "closed", "nope", "resumed"];
  for (const v of ["sa", "non_sa"] as const) {
    r.call("flowOf", al.flowOf, v);
    for (const s of allStages) for (const d of [true, false]) r.call("nextStagesOf", al.nextStagesOf, v, s, d);
  }
  for (const raw of [undefined, "", "  ", "2026-11-04", "2026-11-05", "2025-02-30", "2025-02-31", "2025-13-01", "2025-1-1", " 2026-01-15 ", "garbage", "2026-11-04T00:00:00Z", "0000-01-01"]) {
    r.call("eventDateOrToday", al.eventDateOrToday, raw);
  }
  for (const form of ["SA", "SA_AG", "SAS", "SARL", "SNC", null]) for (const date of [undefined, "2026-01-31", "2024-02-29", "2026-12-01"]) {
    const db = new FakeDb([
      [/FROM engagement e JOIN client c/, { rows: [{ legal_form: form, client_name: "Client", fiscal_year: 2025, partner_name: "P" }] }],
      [/^SELECT 1 FROM alerte/, { rows: [] }],
      [/INSERT INTO alerte \(/, { rows: [{ id: "alerte-1" }] }],
      ...LETTER_RULES,
    ]);
    await r.acall("startAlerte", async () => {
      await al.startAlerte("e", "note", date);
      const v = db.values(/INSERT INTO alerte \(/)!;
      return { variant: v[2], stageDeadline: v[3] };
    }, [form, false, date, TODAY]);
  }
  {
    new FakeDb([
      [/FROM engagement e JOIN client c/, { rows: [{ legal_form: "SA", client_name: "Client", fiscal_year: 2025, partner_name: "P" }] }],
      [/^SELECT 1 FROM alerte/, { rows: [{}] }],
    ]);
    await r.acall("startAlerte", async () => al.startAlerte("e", "note"), ["SA", true, undefined, TODAY]);
  }
  for (const variant of ["sa", "non_sa"] as const) for (const stage of ["request_sent", "reply_recorded", "court_informed", "board_invited", "board_deliberated", "rapport_special", "ag_communicated", "closed"]) for (const to of allStages) {
    for (const opt of [{}, { satisfactory: true }, { eventDate: "2026-01-31" }, { eventDate: "2024-02-29" }]) for (const last of [null, "2025-06-01", "2026-06-01"]) {
      const db = new FakeDb([
        [/FROM alerte a/, { rows: [{ id: "a", engagement_id: "e", variant, stage, discontinued_at: null, client_name: "c", fiscal_year: 2025, partner_name: "p", legal_form: "SA" }] }],
        [/max\(event_date\)/, { rows: [{ d: last }] }],
        ...LETTER_RULES,
      ]);
      await r.acall("advanceAlerte", async () => {
        await al.advanceAlerte("a", to, "n", opt);
        const update = db.log.find((l) => /^UPDATE alerte SET stage/.test(l.text))!;
        if (/discontinued_at = now\(\)/.test(update.text)) return { stage: "reply_recorded", stageDeadline: null, discontinued: true };
        return { stage: update.values![1], stageDeadline: update.values![2], discontinued: false };
      }, [variant, stage, null, to, last, TODAY, opt]);
    }
  }
  {
    new FakeDb([[/FROM alerte a/, { rows: [{ id: "a", engagement_id: "e", variant: "sa", stage: "reply_recorded", discontinued_at: "2026-01-01", client_name: "c", fiscal_year: 2025, partner_name: "p", legal_form: "SA" }] }]]);
    await r.acall("advanceAlerte", async () => al.advanceAlerte("a", "board_invited", "n"), ["sa", "reply_recorded", "2026-01-01", "board_invited", null, TODAY, {}]);
  }
  for (const disc of [null, "2026-05-04", "2026-05-03", "2026-04-30", "2025-08-31", "2026-11-04"]) {
    const db = new FakeDb([[/^SELECT variant, to_char\(discontinued_at/, { rows: [{ variant: "sa", discontinued_at: disc }] }]]);
    await r.acall("resumeAlerte", async () => {
      await al.resumeAlerte("a", "n");
      const update = db.log.find((l) => /^UPDATE alerte SET discontinued_at = NULL/.test(l.text))!;
      return { stage: "request_sent", stageDeadline: update.values![1], discontinued: false };
    }, [disc, TODAY]);
  }
  r.write();
}

function faCases() {
  const r = new Recorder("financial_analysis");
  r.value("RATIO_KEYS", [], fa.RATIO_KEYS);
  r.value("DEFS", [], fa.DEFS);
  return r;
}

const FA_BASE = [
  ["101000", -5000000, -5000000], ["130000", 0, 0], ["162000", -2000000, -3000000], ["211000", 800000, 900000], ["241000", 1500000, 1200000], ["311000", 700000, 650000], ["391000", -50000, -40000],
  ["401000", -900000, -700000], ["409000", 20000, 10000], ["411000", 1200000.55, 1100000.1], ["421000", -150000, -100000], ["445000", 90000, 40000], ["521000", 3300000.25, 2100000.75], ["561000", -10000, -5000], ["591000", -3000, -2000],
  ["601000", 0, 2100000], ["622000", 0, 300000.33], ["661000", 0, 950000], ["671000", 0, 120000], ["681000", 0, 200000], ["691000", 0, 15000], ["701000", 0, -4200000.77], ["771000", 0, -5000], ["891000", 0, 50000],
] as const;

async function financialCases() {
  const r = faCases();
  const rnd = prng(61);
  const mk = (rows: readonly (readonly [string, number, number])[]) => rows.map(([account_code, opening, closing]) => ({ account_code, opening, closing }));
  type C = { tb: any[]; prior?: any[]; overrides?: [string, string][]; mapping?: any; gl?: any[]; periodEnd?: string };
  const glRows = [
    { Date: "15/12/2025", Compte: "701000", Montant: "1 000 000,50", D: "", C: "1 000 000,50" }, { Date: "2025-11-20", Compte: "701100", Montant: "-200000", D: "", C: "200000" },
    { Date: "31.10.2025", Compte: "601000", Montant: "300000", D: "300000", C: "" }, { Date: "01-10-2025", Compte: "622000", Montant: "(50 000)", D: "50000", C: "" }, { Date: "30/09/2025", Compte: "701000", Montant: "999", D: "", C: "999" },
    { Date: "Dec 5 2025", Compte: "631000", Montant: "77", D: "77", C: "" }, { Date: "garbage", Compte: "701000", Montant: "5", D: "", C: "5" }, { Date: "", Compte: "701000", Montant: "5", D: "", C: "5" }, { Date: "2026-01-01", Compte: "701000", Montant: "5", D: "", C: "5" },
    { Date: "31/12/2025", Compte: "411000", Montant: "12", D: "12", C: "" }, { Date: "45/13/2025", Compte: "701000", Montant: "6", D: "", C: "6" }, { Compte: "701000", Montant: "6" }, { Date: "01/10/2025", Montant: "6" }, { Date: "2025-12-31T23:59:59Z", Compte: "701000", Montant: "8" }, { Date: "2025-12-31", Compte: 701000, Montant: 9.5 },
  ];
  const cases: C[] = [
    { tb: mk(FA_BASE) },
    { tb: mk(FA_BASE), prior: [{ account_code: "411000", closing: 500 }, { account_code: "701000", closing: -1000 }, { account_code: "601000", closing: 400 }] },
    { tb: mk(FA_BASE), overrides: [["4110", "C"], ["41", "N"], ["70", "UA"], ["601", "VB"], ["622", "VA1"], ["311", "K"], ["521", "E"], ["5610", "F"]] },
    { tb: mk(FA_BASE), mapping: { account: "Compte", amount: "Montant", journalDate: "Date" }, gl: glRows },
    { tb: mk(FA_BASE), mapping: { account: "Compte", debit: "D", credit: "C", journalDate: "Date" }, gl: glRows },
    { tb: mk(FA_BASE), mapping: { account: "Compte", amount: "Montant", journalDate: "Date" }, gl: glRows, periodEnd: "2026-05-31" },
    { tb: mk(FA_BASE), mapping: { account: "Compte", amount: "Montant", journalDate: "Date" }, gl: [{ Date: "01/01/2000", Compte: "70", Montant: "1" }] },
    { tb: mk(FA_BASE), mapping: { account: "Compte", amount: "Montant", journalDate: "Date" }, gl: [{ Date: "15/12/2025", Compte: "411", Montant: "1" }] },
    { tb: mk(FA_BASE), mapping: { account: "Compte", journalDate: "Date" }, gl: glRows },
    { tb: mk(FA_BASE), mapping: { amount: "Montant", journalDate: "Date" }, gl: glRows },
    { tb: mk([["411000", 0, 0]]) },
    { tb: mk([["130000", 0, 500], ["101000", 0, -500]]) },
    { tb: mk([["601000", 100, 200], ["701000", -300, -400], ["521000", 200, -100]]) },
    { tb: mk([["x", 1, 2]]) },
    { tb: [] },
  ];
  for (let i = 0; i < 60; i += 1) {
    cases.push({
      tb: mk(FA_BASE.map(([a]) => [a, Math.round((rnd() - 0.4) * 1e10) / 100, Math.round((rnd() - 0.4) * 1e10) / 100] as const)),
      prior: i % 3 === 0 ? FA_BASE.map(([a]) => ({ account_code: a, closing: Math.round((rnd() - 0.4) * 1e9) / 100 })) : undefined,
      overrides: i % 4 === 0 ? [["41", "N"], ["60", "VA2"]] : undefined,
    });
  }
  const PERIOD = "2025-12-31";
  for (const c of cases) {
    const periodEnd = c.periodEnd ?? PERIOD;
    new FakeDb([
      [/to_char\(period_end/, { rows: [{ period_end: periodEnd, client_id: "c" }] }],
      [/client_lead_index_override/, { rows: (c.overrides ?? []).map(([account_prefix, index_code]) => ({ account_prefix, index_code })) }],
      [/timing = 'prior_year'/, { rows: (c.prior ?? []).map((p) => ({ account_code: p.account_code, closing: String(p.closing) })) }],
      [/current_version_no/, { rows: c.tb.map((t) => ({ account_code: t.account_code, opening: String(t.opening), closing: String(t.closing) })) }],
      [/FROM sub_ledger_dataset/, { rows: c.mapping ? [{ id: "gl", mapping: c.mapping }] : [] }],
      [/FROM sub_ledger_row/, { rows: (c.gl ?? []).map((data) => ({ data })) }],
    ]);
    await r.acall("financialAnalysis", () => fa.financialAnalysis("e"), [c.tb, periodEnd, c.prior ?? null, c.overrides ?? [], c.mapping ?? null, c.gl ?? []]);
  }
  for (let i = 0; i < 40; i += 1) {
    const rows = FA_BASE.map(([account]) => ({ account, value: Math.round((rnd() - 0.45) * 1e9) / 100 }));
    const b = (fa as any).aggregate(rows);
    r.value("aggregate", [rows], b);
    r.value("ratioSet", [b], (fa as any).ratioSet(b));
  }
  r.write();
}

function dmCases() {
  const r = new Recorder("dataset_mapping");
  r.value("FIELDS", [], dm.FIELDS);
  for (const name of ["JE_KEY", "JE_KEY_SEP", "JE_KEY_JOIN", "JE_KEY_MAX"]) r.value(name, [], (dm as any)[name]);
  const headerSets = [
    ["C.j", "Let", "Date", "Amount", "JE N°", "N° pièce", "N° de compte", "Mouvement débit", "Mouvement crédit", "Libellé écriture", "Intitulé du compte"],
    ["Journal", "N° écriture", "Compte", "Libellé", "Débit", "Crédit", "Date opération"],
    ["Compte", "Libellé", "Date", "Montant"], ["Customer", "Amount"], ["Date", "Account", "Amount"], ["foo", "bar"], [], ["", " "], ["Code", "Code", "Nom", "Solde", "Date facture", "Référence", "Type", "Ville", "Echéance"],
    ["Article", "Désignation", "Quantité", "Prix unitaire", "Montant"], ["Immobilisation", "Libellé", "Coût", "Amortissement", "VNC"], ["Matricule", "Nom", "Brut", "Net à payer"], ["Date", "Narration", "Valeur"], ["Fournisseur", "Nom fournisseur", "Solde"],
  ];
  for (const kind of sk.SUB_LEDGER_KINDS) for (const h of headerSets) r.call("autoMap", dm.autoMap, kind, h);
  for (const s of ["N° pièce", " Débit ", "ÉCRITURE", "a_b-c d", "", "ß", "١"]) r.call("norm", dm.norm, s);
  for (const m of [null, undefined, {}, { jeKey: "" }, { jeKey: "  " }, { jeKey: "a\u001fb\u001f a \u001f\u001fc\u001fd\u001fe" }, { jeKey: 5 }]) r.call("jeKeyColumns", dm.jeKeyColumns, m);
  for (const c of [[], ["a"], ["a", " a ", "", "b", "c", "d", "e"]]) r.call("encodeJeKey", dm.encodeJeKey, c);
  for (const [lines, entries] of [[33336, 11], [33336, 8059], [60, 2], [100, 2], [100, 3], [99, 1], [501, 19], [501, 20], [500, 19], [1000, 0], [1000, -1], [4000, 100], [4001, 100]]) r.call("jeNumberLooksLikeJournalCode", dm.jeNumberLooksLikeJournalCode, lines, entries);
  const text = (v: unknown) => (v === undefined || v === null || v === "" ? null : String(v));
  for (const [data, cols, header] of [
    [{ j: "AC", n: 12 }, ["j", "n"], null], [{ j: "AC" }, ["j", "n"], "x"], [{}, ["j", "n"], "x"], [{ x: 5 }, [], "x"], [{ x: 5 }, [], null], [{}, [], "x"],
  ] as const) r.call("jeIdentity", (d: any, c: any, h: any) => dm.jeIdentity(d, c, h, text), data, cols, header);
  r.write();
}

function miscCases() {
  const r = new Recorder("subledger_kinds");
  r.value("SUB_LEDGER_KINDS", [], sk.SUB_LEDGER_KINDS);
  for (const v of ["ar_open_items", "journal_entries", "nope", null, 1]) r.call("isSubLedgerKind", sk.isSubLedgerKind, v);
  r.write();
  const i = new Recorder("itgc_model");
  i.value("IT_STRATEGIES", [], itgc.IT_STRATEGIES);
  for (const n of ["SAP ERP", "  Sage 100 ", "", "---", "é", "A".repeat(50), "a b c", "Élan vital", "x".repeat(39) + "-y"]) i.call("newAppKey", itgc.newAppKey, n);
  i.write();
  const l = new Recorder("leadsheets");
  const overrides = [{ prefix: "411", sectionCode: "O1", exact: false, priority: 100 }, { prefix: "4111", sectionCode: "O2", exact: true, priority: 100 }];
  const global = [{ prefix: "4", sectionCode: "G1", exact: false, priority: 1 }, { prefix: "41", sectionCode: "G2", exact: false, priority: 1 }, { prefix: "41", sectionCode: "G3", exact: false, priority: 5 }, { prefix: "41", sectionCode: "G4", exact: false, priority: 5 }];
  for (const a of ["4", "41", "411", "4111", "41110", "5", ""]) {
    l.call("resolveSection", ls.resolveSection, a, overrides, global);
    l.call("resolveSection", ls.resolveSection, a, [], global);
    l.call("resolveSection", ls.resolveSection, a, overrides, []);
  }
  l.write();
}

const csvBuf = (s: string) => Buffer.from(s, "utf8");
function tableArg(t: { headers: string[]; rows: Record<string, unknown>[] }) {
  return { headers: t.headers, rows: t.rows.map((row) => ({ ...row })), rowNos: t.rows.map((row) => sl.sourceRowOf(row)) };
}

const CSVS = [
  "Compte,Intitulé,Solde\n411000,Clients,1500\n701000,Ventes,-1500\n",
  "411000,Clients,1500\n701000,Ventes,-1500\n",
  "411000,Clients,1500\n",
  "Compte;Intitulé;Débit;Crédit\n411000;Clients;10 000 000,00;\n701000;Ventes;;10 000 000,00\n",
  "BALANCE GENERALE\nExercice du 01/01/2025 au 31/12/2025\nCompte;Intitulé;Solde\n411000;Clients;1500\n",
  "BALANCE\n\nCompte;Libellé;Débit;Crédit\n411100;Clients;100;\n\n521100;Banque;n/a;\n701100;Ventes;;100\n",
  "﻿Compte;Libellé\r\n1;a\r\n2;b\r\n",
  "a\tb\tc\n1\t2\t3\n",
  "a|b\n1|2\n",
  '"a,b",c\n"1,5","x ""q"" y"\n',
  '"a;b";c;d\n1;2;3\n',
  "",
  "\n\n",
  "one\n",
  "one\ntwo\nthree\n",
  ",,\n1,2,3\n",
  "a,,c\n1,2,3,4\n5\n",
  "a,a\n1,2\n",
  " a , b \n 1 , 2 \n",
  "x;y,z\n1;2,3\n4;5,6\n",
  "a,b\r1,2\r3,4",
  '"unterminated,x\n1,2\n',
];

function subledgerCases() {
  const r = new Recorder("subledgers");
  for (const s of CSVS) for (const h of [true, false]) {
    r.call("parseCsv", (t: string, hr: boolean) => tableArg((sl as any).parseCsv(t, hr)), s, h);
  }
  for (const lines of [["a,b", "c,d"], ["a;b,c", "d;e,f"], [], ["plain"], ["1 000,5;2", "3,5;4"], ['"a;b",c'], ["a\tb|c", "d\te|f"], Array.from({ length: 40 }, (_, i) => (i < 25 ? "a,b" : "a;b;c;d"))]) {
    r.call("detectCsvDelimiter", sl.detectCsvDelimiter, lines);
  }
  for (const [line, d] of [["a,b", ","], ['"a,b",c', ","], ['"a""b",c', ","], [' a , b ', ","], ["a;b", ","], ["", ","], ['"a', ","], ['a"b"c,d', ","], [',', ","]] as const) r.call("splitCsvLine", sl.splitCsvLine, line, d);
  for (const t of [
    { headers: ["Montant", "x"], rows: [] }, { headers: ["x", "Total TTC"], rows: [] }, { headers: ["a", "b"], rows: [{ a: "x", b: "1" }, { a: "y", b: "2" }] }, { headers: ["a", "b"], rows: [{ a: "x", b: "1" }, { a: "y", b: "n" }, { a: "z", b: "m" }] },
    { headers: ["a"], rows: [] }, { headers: [], rows: [] }, { headers: ["MONTÁNT"], rows: [] }, { headers: ["a", "b"], rows: [{ a: "1", b: "2" }, { a: "", b: "" }] },
  ]) r.call("detectAmountColumn", sl.detectAmountColumn, t);
  r.value("parseTabularFile.unsupported", ["x.pdf"], "unsupported-file");
  r.write();
}

const HEADER_SETS = [
  ["Compte", "Libellé", "Solde initial débit", "Solde initial crédit", "Mouvement débit", "Mouvement crédit"], ["Account", "Balance"], ["foo", "bar"], ["Compte", "Libellé", "Débit", "Crédit"], ["Compte"], ["Compte", "Débit"], ["Account", "Closing Debit", "Closing Credit"], ["Account", "Closing Debit"],
  ["N° Compte", "Intitulé", "Solde d'ouverture", "Solde"], ["Numéro", "Label", "Opening", "Debit", "Credit", "Closing"], ["Code", "Description", "A nouveau débit", "A nouveau crédit", "Débit", "Crédit", "Solde débit", "Solde crédit"], [], ["", ""], ["Compte", "compte", "COMPTE", "Solde"], ["Compte", "Numero", "Solde", "Net", "Balance"],
];

function tbTables() {
  const CL = "Compte;Libellé;Solde initial débit;Solde initial crédit;Mouvement débit;Mouvement crédit;Solde débit;Solde crédit";
  return [
    "Compte;Libellé;Débit;Crédit\n411100;Clients;1 500 000;\n701100;Ventes;;1 500 000\n521100;Banque;N/A;\n601100;Achats;12.345,67 FCFA;\n;TOTAL;1 512 345;1 500 000\n",
    `${CL}\n411100;Clients;100;;50;;150;\n701100;Ventes;;100;;50;;150\n999;Bad;;;;;5;\n`,
    `${CL}\n101000;Capital;;1000;;;;1000\n521000;Banque;1000;;;;1000;\nTotal general;;1000;1000;;;;\nCompte;Libellé;;;;;;\nTITRE;x;n/a;;;;;\nABC;Mis-coded;5;;;;5;\n012345;Zero;;;;;;\n123456789;Long;;;;;;\n`,
    "Account;Balance\n411000;1500\n701000;-1500\nTOTAL;0\nsous-total 4;5\nSub total;5\nGrand Total;5\nTotalement;5\ntotal;\n",
    "Account;Opening;Closing\n411000;100;250,50\n401000;-100;-250,50\n",
    "Account;Closing Debit;Closing Credit\n411000;100;\n401000;;100\n",
    "Compte;Solde initial débit;Solde initial crédit;Solde\n411000;100;;150\n401000;;100;-150\n",
    "col1;col2;col3;col4\n411000;Clients;10;20\n701000;Ventes;30;40\n521000;Banque;5;6\n",
    "n;name;x\n1;a;b\n2;c;d\n",
    "411000;Clients;10;20\n701000;Ventes;30;40\n",
    "Code;Texte;V1\n411000;Clients ordinaires;10,5\n401000;Fournisseurs divers;-10,5\n4;x;\nabcd;zz;\n",
    "A;B;C\n1;2;3\n4;5;6\n",
    "Compte;Libellé;Débit;Crédit\nTOTAL;;1;1\n",
    "Compte;Libellé;Débit;Crédit\n411;a;0.1;\n412;a;0.2;\n413;a;;0.3\n",
    "Compte;Libellé;Débit;Crédit\n411;a;0.1;\n412;a;0.2;\n413;a;;0.31\n",
    "Compte;Libellé;Débit;Crédit\n411;a;0.1;\n412;a;0.2;\n413;a;;0.32\n",
  ].map((s) => (sl as any).parseCsv(s, true));
}

const PRIORS: (Map<string, number> | null)[] = [
  null, new Map(), new Map([["521000", 2000000], ["601000", 33000000], ["701000", -45000000]]), new Map([["411100", 100], ["701100", -100], ["130000", 7], ["120000", 8.5], ["601100", 0.1], ["801", 0.2]]), new Map([["411000", 100], ["401000", -100]]),
];

async function tbCases() {
  const r = new Recorder("tb");
  r.value("ALIASES", [], (tb as any).ALIASES);
  r.value("RESULT_CARRIED_FORWARD", [], tb.RESULT_CARRIED_FORWARD);
  for (const h of HEADER_SETS) r.call("inferTbMapping", tb.inferTbMapping, h);
  for (const s of ["Solde initial débit", " N° Compte ", "ÉCRITURE", "", "a_b", "ß"]) r.call("normalizeHeader", (tb as any).normalizeHeader, s);
  for (const s of ["411", "4", "0", "", "a1", " 1", "١"]) r.call("isAccountCell", tb.isAccountCell, s);
  for (const m of [{}, { account: "a" }, { account: "a", debit: "d" }, { account: "a", debit: "d", credit: "c" }, { account: "a", closing: "x" }, { account: "a", closingDebit: "x" }, { account: "a", closingDebit: "x", closingCredit: "y" }]) r.call("validateMapping", (tb as any).validateMapping, m);

  const tables = tbTables();
  const prefixes = [[], ["4", "7"], ["41", "70", "52", "60", "13"], ["1", "2", "3", "4", "5", "6", "7", "8"]];
  for (const table of tables) {
    const arg = tableArg(table);
    let inferred: any = null;
    try { inferred = tb.inferTbMapping(table.headers); } catch { /* the heuristic's case */ }
    const heur = (tb as any).heuristicFill(table, inferred ?? {});
    r.value("heuristicFill", [arg, inferred ?? {}], heur);
    for (const mapping of [inferred, heur, { account: table.headers[0], closing: table.headers[table.headers.length - 1] }].filter(Boolean)) {
      r.call("readabilityOf", tb.readabilityOf, table, mapping);
      (r.cases[r.cases.length - 1] as any).args[0] = arg;
      r.call("extractTbRows", tb.extractTbRows, table, mapping);
      (r.cases[r.cases.length - 1] as any).args[0] = arg;
      let rows: any[] | null = null;
      try { rows = tb.extractTbRows(table, mapping); } catch { /* recorded above */ }
      if (!rows) continue;
      const readability = tb.readabilityOf(table, mapping);
      for (const known of prefixes) for (const prior of PRIORS) for (const rd of [readability, undefined]) {
        if (rd === undefined && known !== prefixes[2]) continue;
        const summary = tb.validateTbRows(rows, known, prior, mapping, rd);
        r.value("validateTbRows", [arg, mapping, known, prior, rd === undefined ? null : rd], summary);
      }
    }
  }
  // the private branches of preview: the real function, on real parsed files
  const over = [{ account_prefix: "411", section_code: "O1", match_type: "prefix" }, { account_prefix: "411000", section_code: "O2", match_type: "exact" }];
  const glob = [{ account_prefix: "4", section_code: "G4", priority: 1 }, { account_prefix: "7", section_code: "G7", priority: 1 }, { account_prefix: "41", section_code: "G41", priority: 2 }];
  const idx = [{ account_prefix: "4110", index_code: "E" }, { account_prefix: "7010", index_code: "UB2" }];
  const sources = [
    "Compte;Libellé;Débit;Crédit\n411000;Clients;100;\n411100;Autres;50;\n701000;Ventes;;150\nABC;Mis;1;\n",
    "col1;col2;col3;col4\n411000;Clients;10;20\n701000;Ventes;30;40\n521000;Banque;5;6\n",
    "n;name;x\n1;a;b\n2;c;d\n",
    "Compte;Libellé;Débit;Crédit\nTOTAL;;1;1\n",
    "Account;Balance\n411000;1500,5\n401000;-1500,5\n4110;2\nabcd;3\nABCD;3\nÉ001;1\n1000;1\n",
    "Num;Lib;Val\n4110001;Clients ordinaires;1\n4110002;Clients douteux;2\n7010;Ventes;3\n4111;x;4\n4112;y;5\n4113;z;6\n4114;q;7\n",
  ];
  for (const src of sources) for (const mo of [undefined, { account: "foo", debit: "d", credit: "c" }, {}] as any[]) for (const o of [[], over]) {
    new FakeDb([
      [/FROM engagement WHERE id/, { rows: [{ client_id: "c" }] }],
      [/FROM client_grouping_override/, { rows: o }],
      [/client_lead_index_override/, { rows: idx }],
      [/FROM syscohada_grouping_rule/, { rows: glob }],
    ]);
    const table = (sl as any).parseCsv(src, true);
    const overrides = o.map((x: any) => ({ prefix: x.account_prefix, sectionCode: x.section_code, exact: x.match_type === "exact", priority: 100 }));
    const global = glob.map((x) => ({ prefix: x.account_prefix, sectionCode: x.section_code, exact: false, priority: x.priority }));
    await r.acall("previewTrialBalance", () => tb.previewTrialBalance("e", "t.csv", csvBuf(src), mo), [tableArg(table), mo === undefined ? null : mo, overrides, global, Object.fromEntries(idx.map((x) => [x.account_prefix, x.index_code]))]);
  }
  // lead schedules on real rows, overrides and prior years
  const rnd = prng(71);
  const accounts = ["101000", "130000", "162000", "191000", "201000", "211000", "221000", "241000", "281000", "291000", "292000", "311000", "391000", "401000", "411000", "421000", "441000", "444000", "462000", "476000", "477000", "478000", "479000", "481000", "490000", "491000", "499000", "521000", "591000", "601000", "603000", "622000", "641000", "661000", "671000", "681000", "691000", "701000", "711000", "771000", "781000", "741000", "811000", "841000", "871000", "891000", "999000"];
  const leadCases: any[] = [
    { rows: [], prior: null, overrides: [] },
    { rows: [{ account_code: "411000", closing: 100.5 }], prior: null, overrides: [] },
    { rows: [{ account_code: "411000", closing: 0.5 }, { account_code: "411100", closing: 0.5 }], prior: new Map([["411000", 2.5], ["401000", -3.5]]), overrides: [] },
    { rows: [{ account_code: "411000", closing: 1000 }, { account_code: "281000", closing: -50 }, { account_code: "221000", closing: 70 }], prior: new Map([["411000", 800]]), overrides: [["41", "K"], ["411", "K"], ["22", "E"]] },
  ];
  for (let i = 0; i < 40; i += 1) {
    leadCases.push({
      rows: accounts.filter(() => rnd() < 0.7).map((account_code) => ({ account_code, closing: Math.round((rnd() - 0.5) * 1e9) / 100 })),
      prior: i % 3 === 2 ? null : new Map(accounts.filter(() => rnd() < 0.6).map((a) => [a, Math.round((rnd() - 0.5) * 1e9) / 100] as [string, number])),
      overrides: i % 5 === 0 ? [["41", "N"], ["4110", "K"], ["60", "VB"]] : [],
    });
  }
  for (const c of leadCases) {
    new FakeDb([
      [/FROM engagement WHERE id/, { rows: [{ client_id: "c" }] }],
      [/JOIN engagement p ON/, { rows: c.prior ? [{ id: "prior" }] : [] }],
      [/COALESCE\(/, { rows: c.prior ? [...c.prior.entries()].map(([account_code, closing]: [string, number]) => ({ account_code, closing: String(closing) })) : [] }],
      [/current_version_no/, { rows: c.rows.map((x: any) => ({ account_code: x.account_code, closing: String(x.closing) })) }],
      [/client_lead_index_override/, { rows: c.overrides.map(([account_prefix, index_code]: [string, string]) => ({ account_prefix, index_code })) }],
    ]);
    await r.acall("leadSchedules", () => tb.leadSchedules("e"), [c.rows, c.prior, c.overrides]);
  }
  // journals
  for (const [desc, lines] of [
    ["", [{ debit: 1, credit: 0 }, { debit: 0, credit: 1 }]], ["  ", []], ["x", []], ["x", [{ debit: 1, credit: 0 }]], ["x", [{ debit: 1, credit: 0 }, { debit: 0, credit: 1 }]],
    ["x", [{ debit: 0.1, credit: 0 }, { debit: 0.2, credit: 0 }, { debit: 0, credit: 0.3 }]], ["x", [{ debit: 1, credit: 0 }, { debit: 0, credit: 1.01 }]], ["x", [{ debit: 1, credit: 0 }, { debit: 0, credit: 1.02 }]],
  ] as [string, any[]][]) {
    new FakeDb([[/^SELECT id FROM trial_balance/, { rows: [] }]]);
    await r.acall("createJournal", async () => {
      try { await tb.createJournal("e", desc, lines); } catch (e) {
        if ((e as Error).message === "no-tb") return null; // past the checks under test
        throw e;
      }
      return null;
    }, [desc, lines]);
  }
  const diffs: any[][] = [
    [], [{ account: "411", a: "100", b: "100.01" }, { account: "412", a: "100", b: "100.011" }, { account: "413", a: null, b: "5" }, { account: "414", a: "5", b: null }, { account: "415", a: "0.1", b: "0.3" }],
  ];
  for (const rows of diffs) {
    new FakeDb([[/WITH balances AS/, { rows }]]);
    await r.acall("diffTbVersions", () => tb.diffTbVersions("e", 1, 2), [rows.map((x) => ({ account: x.account, a: x.a === null ? null : Number(x.a), b: x.b === null ? null : Number(x.b) }))]);
  }
  r.write();
}

function tbReasonsCases() {
  const r = new Recorder("tb_reasons");
  r.value("COLUMN_LABEL", [], (tr as any).COLUMN_LABEL);
  for (const s of ["valid", "invalid", "pending", "other", "", null, undefined]) for (const loc of LOCALES) r.call("tbStatusLabel", tr.tbStatusLabel, s, loc);
  const known = ["41", "70", "52", "60", "13"];
  for (const table of tbTables()) {
    let mapping: any;
    try { mapping = tb.inferTbMapping(table.headers); } catch { continue; }
    let rows: any[];
    try { rows = tb.extractTbRows(table, mapping); } catch { continue; }
    for (const prior of PRIORS) for (const rd of [tb.readabilityOf(table, mapping), undefined]) {
      const summary = tb.validateTbRows(rows, known, prior, mapping, rd);
      for (const loc of LOCALES) r.call("explainTbSummary", tr.explainTbSummary, summary, loc);
    }
  }
  const many = Array.from({ length: 12 }, (_, i) => `4${i}`);
  const s = {
    status: "invalid",
    checks: {
      balanced: { ok: false, totalDebit: 1234567.891, totalCredit: 0.005 },
      openingBalanced: { ok: false, totalDebit: 1000.5, totalCredit: 2000.25 },
      closingEquation: { ok: false, failures: many },
      codification: { ok: false, badAccounts: many },
      unknownAccounts: many,
      openingTiesToPrior: { checked: true, exceptions: Array.from({ length: 7 }, (_, i) => ({ account: i === 0 ? "12x/13x" : `5${i}`, opening: i * 1234.5, priorClosing: -(i + 1) * 0.125 })) },
    },
    mapping: {},
    readability: { rows: 1500, rowsWithoutAccount: 1500, unreadable: [{ column: "debit", header: "D", count: 12000, examples: [{ row: 3, account: "411", value: "x" }, { row: 1000000, account: "412", value: 'y"' }] }, { column: "closing", header: "S", count: 1, examples: [] }] },
  };
  for (const loc of LOCALES) r.call("explainTbSummary", tr.explainTbSummary, s, loc);
  r.write();
}

// ---- engines: the real runSampling and friends, on the answer sheet ----------

function datasetDb(rows: any[], kind: string, thresholds: { performance: number; trivial: number } | null, tbTotal: number | null = 0) {
  return new FakeDb([
    [/FROM sub_ledger_dataset WHERE id/, { rows: [{ engagement_id: "eng", kind }] }],
    [/FROM sub_ledger_row/, { rows: rows.map((x) => ({ row_no: x.rowNo, data: x.data, amount: x.amount === null ? null : String(x.amount) })) }],
    [/FROM materiality/, { rows: thresholds ? [{ performance: String(thresholds.performance), trivial: String(thresholds.trivial) }] : [] }],
    [/AS total\s+FROM trial_balance/, { rows: [{ total: tbTotal === null ? null : String(tbTotal) }] }],
    [/INSERT INTO document \(/, { rows: [{ id: "doc-1" }] }],
    [/INSERT INTO automation_run/, { rows: [{ id: "run-12345678-x" }] }],
    [/FROM automation_run/, { rows: [] }],
  ]);
}

function randomRows(rnd: () => number, n: number, kind: "wide" | "round" | "zeros" = "wide") {
  return Array.from({ length: n }, (_, i) => {
    const raw = kind === "round" ? Math.round(rnd() * 20) * 100000 : kind === "zeros" && i % 3 === 0 ? 0 : (rnd() - 0.2) * 10 ** (1 + Math.floor(rnd() * 8));
    return { rowNo: i + 1, data: { Customer: `C${i}`, Amount: raw }, amount: i % 17 === 16 ? null : Math.round(raw * 100) / 100 };
  });
}

async function storedPicks(db: FakeDb): Promise<{ rowNo: number; reason: string }[]> {
  // the workbook the real storeRun built: read it back rather than trust a re-derivation
  const ExcelJS = (await import("exceljs")).default;
  const content = db.values(/INSERT INTO document_version/)![5] as Buffer;
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.load(content as any);
  const ws = wb.worksheets[0];
  const picks: { rowNo: number; reason: string }[] = [];
  ws.eachRow((row, n) => {
    if (n > 5) picks.push({ rowNo: row.getCell(1).value as number, reason: row.getCell(2).value as string });
  });
  return picks;
}

async function engineCases() {
  const r = new Recorder("engines");
  r.value("RECON_PREFIXES", [], eng.RECON_PREFIXES);
  for (const seed of SEEDS) for (let i = 0; i < 60; i += 1) r.call("seededRandom", eng.seededRandom, seed, i);
  for (const i of [1000, 123456789, 1e21, 1.5, -1]) r.call("seededRandom", eng.seededRandom, "seed-1", i);
  const rnd = prng(83);
  const populations: any[][] = [
    [], randomRows(rnd, 1), randomRows(rnd, 8), randomRows(rnd, 40), randomRows(rnd, 40, "zeros"), randomRows(rnd, 60, "round"), randomRows(rnd, 90),
    ["ACME:5000000", "Beta:2500000", "Gamma:1800000", "Delta:1200000", "Epsilon:900000", "Zeta:700000", "Eta:300000", "Theta:200000"].map((s, i) => ({ rowNo: i + 1, data: { Customer: s.split(":")[0], Amount: s.split(":")[1] }, amount: Number(s.split(":")[1]) })),
    Array.from({ length: 6 }, (_, i) => ({ rowNo: i + 1, data: {}, amount: null })),
    [{ rowNo: 3, data: { a: 1 }, amount: 0.1 }, { rowNo: 7, data: { a: 2 }, amount: 0.2 }, { rowNo: 9, data: { a: 3 }, amount: 0.7 }],
  ];
  const inputs: any[] = [];
  for (const method of ["random", "systematic", "mus", "criteria"]) for (const size of [1, 3, 25, 500, 2.5]) for (const seed of ["seed-1", "E4.1-2025"]) {
    inputs.push({ method, sampleSize: size, seed, threshold: method === "criteria" ? 2000000 : undefined });
  }
  inputs.push(
    { method: "random", sampleSize: 0, seed: "s" }, { method: "random", sampleSize: 3, seed: "  " }, { method: "criteria", sampleSize: 3, seed: "s" }, { method: "criteria", sampleSize: 3, seed: "s", threshold: 0 }, { method: "criteria", sampleSize: 3, seed: "s", threshold: 1 },
    { method: "mus", sampleSize: 3, seed: "s", confidence: 94 }, { method: "mus", sampleSize: 3, seed: "s", confidence: 95 }, { method: "mus", sampleSize: 3, seed: "s", confidence: 85, expectedMisstatement: 1000 }, { method: "mus", sampleSize: 3, seed: "s", confidence: 70, expectedMisstatement: 99999999 },
    { method: "mus", sampleSize: 3, seed: "s", confidence: 95, overrideSize: 7, overrideRationale: "  because  " }, { method: "mus", sampleSize: 3, seed: "s", overrideSize: 7 }, { method: "random", sampleSize: 3, seed: "s", overrideSize: 0, overrideRationale: "x" }, { method: "random", sampleSize: 3, seed: "s", overrideSize: 2, overrideRationale: " " }, { method: "systematic", sampleSize: 3, seed: "s", overrideSize: 2, overrideRationale: "x" },
    { method: "random", sampleSize: 3, seed: "s", confidence: 95 },
  );
  let n = 0;
  for (const rows of populations) for (const input of inputs) for (const th of [{ performance: 1500000, trivial: 100000 }, null]) {
    n += 1;
    if (th === null && input.confidence === undefined && n % 2) continue; // thresholds only reach MUS planning
    const db = datasetDb(rows, "ar_open_items", th);
    await r.acall("selectSample", async () => {
      await eng.runSampling({ fileItemId: "fi", datasetId: "ds", ...input });
      return { picks: await storedPicks(db), summary: JSON.parse(db.values(/INSERT INTO automation_run/)![6] as string) };
    }, [rows, input, th ? th.performance : null]);
  }
  // evaluate
  const evals: any[] = [
    [0, 100, 5, 10], [-1, 100, 5, 10], [100, 1000, 10, 100], [100, 1000, 9.99, 100], [100, -1000, -10, 100], [3, 10, 1, null], [1, 0.5, 1, 0], [7, 1000000.5, 3.3, 500000],
  ];
  for (let i = 0; i < 80; i += 1) evals.push([Math.round(rnd() * 1e8) / 100, Math.round((rnd() - 0.5) * 1e10) / 100, Math.round((rnd() - 0.5) * 1e6) / 100, i % 5 === 0 ? null : Math.round(rnd() * 1e6)]);
  for (const [sampled, total, found, trivial] of evals) for (const locale of LOCALES) {
    const db = new FakeDb([
      [/^SELECT engagement_id, file_item_id, result_summary/, { rows: [{ engagement_id: "eng", file_item_id: "fi", result_summary: { sampledValue: sampled, populationTotal: total } }] }],
      [/FROM materiality/, { rows: trivial === null ? [] : [{ performance: "1", trivial: String(trivial) }] }],
    ]);
    await r.acall("evaluateSampling", async () => {
      const out = await eng.evaluateSampling("run-12345678-x", found, locale);
      const f = db.findings[0];
      return { ...out, finding: f ? { route: f.route, title: f.title, amount: f.amount, mtype: f.mtype } : null };
    }, [sampled, total, found, trivial, "run-12345678-x", locale]);
  }
  // ToD results
  const tods: any[] = [
    { indexCode: " e ", sampleValue: 1000, sampleMisstatement: 10, keyMisstatement: 0, remainingValue: 5000 }, { indexCode: "VD1", sampleValue: 1000, sampleMisstatement: 10, keyMisstatement: 2.5, remainingValue: 100000, locale: "fr" }, { indexCode: "ZZZ", sampleValue: 1000, sampleMisstatement: 0, keyMisstatement: -2.5, remainingValue: 100000 },
    { indexCode: "toolong", sampleValue: 1, sampleMisstatement: 0, keyMisstatement: 0, remainingValue: 0 }, { indexCode: "1A", sampleValue: 1, sampleMisstatement: 0, keyMisstatement: 0, remainingValue: 0 }, { indexCode: "E", sampleValue: 0, sampleMisstatement: 0, keyMisstatement: 0, remainingValue: 0 },
    { indexCode: "E", sampleValue: -1, sampleMisstatement: 0, keyMisstatement: 0, remainingValue: 0 }, { indexCode: "E", sampleValue: 1, sampleMisstatement: 0, keyMisstatement: 0, remainingValue: -1 }, { indexCode: "E", sampleValue: NaN, sampleMisstatement: 0, keyMisstatement: 0, remainingValue: 0 }, { indexCode: "E", sampleValue: 1, sampleMisstatement: Infinity, keyMisstatement: 0, remainingValue: 0 },
    { indexCode: "E", sampleValue: 7, sampleMisstatement: 3, keyMisstatement: 1000.5, remainingValue: 1000.5, locale: "en" },
  ];
  for (const t of tods) for (const trivial of [100, null]) {
    let summary: any = null;
    const db = new FakeDb([
      [/FROM file_item WHERE engagement_id/, { rows: [{ id: "fi" }] }],
      [/INSERT INTO document \(/, { rows: [{ id: "doc-1" }] }],
      [/INSERT INTO automation_run/, (_t, v) => { summary = JSON.parse(v![6] as string); return { rows: [{ id: "run-12345678-x" }] }; }],
      [/^SELECT engagement_id, file_item_id, result_summary/, () => ({ rows: [{ engagement_id: "eng", file_item_id: "fi", result_summary: summary }] })],
      [/FROM materiality/, { rows: trivial === null ? [] : [{ performance: "1", trivial: String(trivial) }] }],
    ]);
    await r.acall("recordTodResult", async () => {
      const out = await eng.recordTodResult({ engagementId: "eng", ...t });
      const section = db.values(/FROM file_item WHERE engagement_id/)![1];
      return {
        indexCode: summary.indexCode, section, summary, projected: out.projected, raisedToB5: out.raisedToB5,
        findings: db.findings.map(({ engagementId: _e, fileItemId: _f, ...rest }: any) => rest),
      };
    }, [t, trivial, "run-12345678-x"]);
  }
  // reconciliations
  const reconRows = [
    { rowNo: 1, data: { Date: "2025-12-01", Amount: 100 }, amount: 100.1 }, { rowNo: 2, data: { Date: "2025-12-30", Amount: 200 }, amount: 200.2 }, { rowNo: 3, data: { Date: "garbage", Amount: 1 }, amount: 1 }, { rowNo: 4, data: { Date: null, Amount: 1 }, amount: null }, { rowNo: 5, data: { Date: "12/01/2025", Amount: 5 }, amount: 5 },
    { rowNo: 6, data: { Date: "2025-11-01 10:00", Amount: 5 }, amount: -5.5 },
  ];
  const noDate = [{ rowNo: 1, data: { Amount: 100 }, amount: 12600000 }];
  const numericKeys = [{ rowNo: 1, data: { Zdate: "2024-01-01", "2024": "x", "10": "y" }, amount: 3 }];
  for (const kind of ["ar_open_items", "ap_open_items", "inventory_listing", "payroll_register", "fixed_asset_register", "bank_statement", "journal_entries"]) for (const rows of [reconRows, noDate, numericKeys, []]) for (const tbTotal of [10000000, -305.8, 0, null]) for (const trivial of [100000, 0.5, null]) for (const opt of [{}, { periodEnd: "2025-12-31" }, { periodEnd: "2025-12-31", staleDays: 2 }, { periodEnd: "garbage" }] as any[]) {
    if (opt.periodEnd && kind !== "bank_statement") continue;
    const db = datasetDb(rows, kind, trivial === null ? null : { performance: 1, trivial }, tbTotal);
    await r.acall("runReconciliation", async () => {
      await eng.runReconciliation({ fileItemId: "fi", datasetId: "ds", ...opt });
      const run = db.values(/INSERT INTO automation_run/)!;
      const f = db.findings[0];
      return { engine: run[3], summary: JSON.parse(run[6] as string), finding: f ? { route: f.route, title: f.title, detail: f.detail } : null };
    }, [kind, rows, tbTotal ?? 0, trivial, opt.staleDays ?? null, opt.periodEnd ?? null]);
    datasetDb(rows, kind, null, tbTotal);
    await r.acall("reconPreview", () => eng.reconPreview("ds"), [kind, rows, tbTotal ?? 0]);
  }
  // supplier statements
  const st = [{ rowNo: 1, data: { Fournisseur: "ACME", Amount: 1 }, amount: 100 }, { rowNo: 2, data: { Fournisseur: " ACME ", Amount: 1 }, amount: 0.1 }, { rowNo: 3, data: { Fournisseur: "Beta" }, amount: 0.2 }, { rowNo: 4, data: { Fournisseur: "" }, amount: 5 }, { rowNo: 5, data: {}, amount: 5 }, { rowNo: 6, data: { Fournisseur: "é" }, amount: null }, { rowNo: 7, data: { Fournisseur: "Z" }, amount: 1 }, { rowNo: 8, data: { Fournisseur: 12 }, amount: 1 }];
  const le = [{ rowNo: 1, data: { Name: "ACME" }, amount: 100.1 }, { rowNo: 2, data: { Name: "Beta" }, amount: 0.21 }, { rowNo: 3, data: { Name: "a" }, amount: 3 }, { rowNo: 4, data: { Name: "Z" }, amount: 1.011 }, { rowNo: 5, data: { Name: "😀" }, amount: 1 }, { rowNo: 6, data: { Name: "～" }, amount: 1 }];
  for (const [a, b] of [[st, le], [le, st], [[{ rowNo: 1, data: { x: 1 }, amount: 1 }], le], [st, [{ rowNo: 1, data: { x: 1 }, amount: 1 }]], [[], le]] as any[][]) {
    const db = new FakeDb([
      [/FROM sub_ledger_dataset WHERE id/, { rows: [{ engagement_id: "eng", kind: "ap_open_items" }] }],
      [/FROM sub_ledger_row/, (_t, v) => ({ rows: (v![0] === "st" ? a : b).map((x: any) => ({ row_no: x.rowNo, data: x.data, amount: x.amount === null ? null : String(x.amount) })) })],
      [/INSERT INTO document \(/, { rows: [{ id: "doc-1" }] }],
      [/INSERT INTO automation_run/, { rows: [{ id: "run" }] }],
    ]);
    await r.acall("runSupplierRecon", async () => {
      const out = await eng.runSupplierRecon({ fileItemId: "fi", statementsDatasetId: "st", ledgerDatasetId: "le" });
      const ExcelJS = (await import("exceljs")).default;
      const wb = new ExcelJS.Workbook();
      await wb.xlsx.load(db.values(/INSERT INTO document_version/)![5] as any);
      const lines: unknown[][] = [];
      wb.worksheets[0].eachRow((row, i) => { if (i > 5) lines.push([1, 2, 3, 4].map((c) => row.getCell(c).value)); });
      return { suppliersCompared: out.suppliersCompared, differences: out.differences, lines };
    }, [a, b]);
  }
  // journal entries
  const je = [
    { rowNo: 1, data: { Date: "2025-12-30", Account: "701000", Amount: "3000000" }, amount: 3000000 }, { rowNo: 2, data: { Date: "2025-12-28", Account: "521000", Amount: "1234567" }, amount: 1234567 }, { rowNo: 3, data: { Date: "2025-06-16", Account: "601000", Amount: "500" }, amount: 500 }, { rowNo: 4, data: { Date: "2025-07-19", Account: "601000", Amount: "2000000" }, amount: -2000000 },
    { rowNo: 5, data: { Date: "2025-12-31", Account: "x" }, amount: null }, { rowNo: 6, data: { Date: "2026-01-03", Account: "x" }, amount: 0 }, { rowNo: 7, data: { Date: "garbage" }, amount: 1000000.5 }, { rowNo: 8, data: {}, amount: 2000000 }, { rowNo: 9, data: { Date: "12/26/2025 23:00" }, amount: 5 }, { rowNo: 10, data: { Date: "2025-12-26T23:00:00-05:00" }, amount: 5 },
  ];
  const jeSets = [je, [], [{ rowNo: 1, data: { Other: "2025-12-28" }, amount: 1000000 }], Array.from({ length: 60 }, (_, i) => ({ rowNo: i + 1, data: { "Date écriture": `2025-12-${String(1 + (i % 31)).padStart(2, "0")}`, N: i }, amount: (i % 7) * 500000 }))];
  for (const rows of jeSets) for (const pe of ["2025-12-31", "garbage"]) for (const large of [undefined, 0, 1500000]) for (const perf of [1500000, null]) {
    const db = datasetDb(rows, "journal_entries", perf === null ? null : { performance: perf, trivial: 1 });
    await r.acall("runJeTesting", async () => {
      const out = await eng.runJeTesting({ fileItemId: "fi", datasetId: "ds", periodEnd: pe, largeThreshold: large });
      const params = JSON.parse(db.values(/INSERT INTO automation_run/)![4] as string);
      const ExcelJS = (await import("exceljs")).default;
      const wb = new ExcelJS.Workbook();
      await wb.xlsx.load(db.values(/INSERT INTO document_version/)![5] as any);
      const scores: unknown[] = [];
      wb.worksheets[0].eachRow((row, i) => {
        if (i > 5) scores.push({ rowNo: row.getCell(1).value, score: row.getCell(2).value, flags: String(row.getCell(3).value ?? "").split("+").filter(Boolean) });
      });
      return { largeThreshold: params.largeThreshold, scored: out.scored, flagged: out.flagged, scores };
    }, [rows, pe, large === undefined ? null : large, perf]);
  }
  // substantive analytics
  for (const [actual, expectation, tolerance] of [[100, 90, 5], [100, 95, 5], [100.5, 90.25, 10.25], [100.5, 90.25, 10.24], [0, 0, 1], [5, 5, 0], [5, 5, -1], [0.3, 0.1, 0.2], [-2.5, 0, 1], [2.5, 0, 1]]) {
    const db = new FakeDb([
      [/^SELECT engagement_id, code FROM file_item/, { rows: [{ engagement_id: "eng", code: "E4.1" }] }],
      [/^SELECT client_id FROM engagement/, { rows: [{ client_id: "c" }] }],
      [/FROM syscohada_grouping_rule/, { rows: [{ account_prefix: "41" }] }],
      [/AS total\s+FROM trial_balance/, { rows: [{ total: String(actual) }] }],
      [/INSERT INTO document \(/, { rows: [{ id: "doc-1" }] }],
      [/INSERT INTO automation_run/, { rows: [{ id: "run" }] }],
    ]);
    await r.acall("runSubstantiveAnalytic", async () => {
      const out = await eng.runSubstantiveAnalytic({ fileItemId: "fi", expectation, tolerance, basis: "Basis" });
      const f = db.findings[0];
      return { actual: out.actual, variance: out.variance, unexplained: out.raisedToB5, finding: f ? { route: f.route, title: f.title, amount: f.amount, mtype: f.mtype, trivialConfirmed: f.trivialConfirmed } : null };
    }, [actual, expectation, tolerance, "Basis"]);
  }
  r.write();
}

async function main() {
  jsHelpers();
  amountCases();
  materialityCases();
  sadCases();
  craCases();
  designCases();
  sapCases();
  labelsCases();
  assertionsCases();
  tocCases();
  tocGridCases();
  samplingParamsCases();
  todCases();
  leadCases();
  complexityCases();
  standardsCases();
  emailCases();
  await retentionCases();
  legalCases();
  await alerteCases();
  await financialCases();
  dmCases();
  miscCases();
  subledgerCases();
  await tbCases();
  tbReasonsCases();
  await engineCases();
}

main().then(() => process.exit(0), (e) => { console.error(e); process.exit(1); });
