// Records what the TypeScript does, for tests/pure/test_parity.py to compare with Python.
//
//   tsx --tsconfig <platform>/tsconfig.json scripts/papers/record_parity.ts --platform <platform>
//
// Every result comes from the platform's own functions (paperFor, requiredKeys,
// paperKeys, paperComplete, paperProgress, paperMissing, unansweredKeys). Answer sets
// are recipes interpreted the same way on both sides, so they stay small on disk and
// follow each paper's keys. Run scripts/papers/run_baseline.sh rather than this directly.

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { ADDON_DIR, baselineCommit, canonical, digest, fail, load, platformDir, registryEntries, sha256, type PaperDef } from "./platform";

/** A value for each kind of required key; an absent property writes nothing. */
type Recipe = {
  name: string;
  stride?: number; // answer only every n-th required key
  q?: string | null; q_x?: string;
  p?: string | null; p_na?: string; p_x?: string;
  c?: string | null; c_x?: string;
  f?: string | null;
};

// Characters on which ECMAScript trim() and Python str.strip() disagree or agree oddly.
const JS_BLANK = " \t\n\u000b\f\r       　﻿";
const PY_ONLY_BLANK = "\u001c\u0085";

const SCENARIOS: Recipe[] = [
  { name: "empty" },
  { name: "all_answered", q: "yes", p: "Done, see E/1", c: "yes", f: "Text" },
  { name: "every_second_key", stride: 2, q: "yes", p: "Done", c: "yes", f: "Text" },
  { name: "every_third_key_no", stride: 3, q: "no", p: "Done", c: "no", f: "Text" },
  { name: "null_values", q: null, p: null, c: null, f: null },
  { name: "js_blank_everywhere", q: JS_BLANK, p: JS_BLANK, c: JS_BLANK, f: JS_BLANK },
  { name: "python_only_blank", q: PY_ONLY_BLANK, p: PY_ONLY_BLANK, c: PY_ONLY_BLANK, f: PY_ONLY_BLANK },
  { name: "no_without_explanation", q: "no", p: "Done", c: "no", f: "Text" },
  { name: "no_with_explanation", q: "no", q_x: "Because", p: "Done", c: "no", c_x: "Because", f: "Text" },
  { name: "no_with_blank_explanation", q: "no", q_x: JS_BLANK, p: "Done", c: "no", c_x: JS_BLANK, f: "Text" },
  { name: "na_without_reason", q: "na", p_na: "na", c: "yes", f: "Text" },
  { name: "na_with_reason", q: "na", q_x: "Reason", p_na: "na", p_x: "Reason", c: "yes", f: "Text" },
  { name: "na_with_blank_reason", q: "na", q_x: JS_BLANK, p_na: "na", p_x: JS_BLANK, c: "yes", f: "Text" },
  { name: "na_padded_marker", q: "  na\t", p_na: " na﻿", c: "yes", f: "Text" },
  { name: "na_uppercase_is_text", q: "NA", p_na: "NA", p: "", c: "NA", f: "Text" },
  { name: "proc_result_but_na_no_reason", q: "yes", p: "Done", p_na: "na", c: "yes", f: "Text" },
  { name: "proc_result_and_na_reason", q: "yes", p: "Done", p_na: "na", p_x: "Reason", c: "yes", f: "Text" },
  { name: "proc_na_marker_not_na", q: "yes", p_na: "n/a", p_x: "Reason", c: "yes", f: "Text" },
  { name: "conclusion_na_no_reason", q: "yes", p: "Done", c: "na", f: "Text" },
  { name: "fields_na_literal", q: "yes", p: "Done", c: "yes", f: "na" },
];

/** The answers one recipe gives one paper. test_parity.py carries the same interpreter. */
function answers(def: PaperDef, types: Record<string, any>, r: Recipe): Record<string, string | null> {
  const procKeys = new Set<string>();
  for (const s of (def.sections ?? []) as any[]) {
    if (s.kind === "proc") for (const p of s.procs) procKeys.add(types.procKey(p.key));
  }
  const out: Record<string, string | null> = {};
  const put = (k: string, v: string | null | undefined) => {
    if (v !== undefined) out[k] = v;
  };
  (types.requiredKeys(def) as string[]).forEach((k, i) => {
    if (r.stride && i % r.stride !== 0) return;
    if (k.startsWith("q_")) {
      put(k, r.q);
      put(`${k}_x`, r.q_x);
    } else if (procKeys.has(k)) {
      put(k, r.p);
      put(`${k}_na`, r.p_na);
      put(`${k}_x`, r.p_x);
    } else if (/^c_\d+$/.test(k)) {
      put(k, r.c);
      put(`${k}_x`, r.c_x);
    } else {
      put(k, r.f);
    }
  });
  return out;
}

const short = (s: string) => s.slice(0, 16);

async function main(): Promise<void> {
  const dir = platformDir();
  const commit = baselineCommit(dir);
  const wp = await load(dir, "lib/working-papers");
  const types = await load(dir, "lib/papers/types");
  const se = await load(dir, "lib/standards-edition");
  const lf = await load(dir, "lib/legal-forms");
  const tg = await load(dir, "lib/task-groups");
  const fi = await load(dir, "lib/file-index");

  const editions: string[] = [...se.STANDARDS_EDITIONS];
  const forms: string[] = [...lf.LEGAL_FORMS];
  const entries = await registryEntries(dir);
  const taskCodes: string[] = fi.DEFAULT_FILE_INDEX.map((t: { code: string }) => t.code);

  // subject id -> how to read it. Shadowed definitions go through the same resolvers.
  const subjects: { id: string; kind: string; read: (ed: string, form: string | null) => PaperDef }[] = [];
  for (const e of entries) {
    if (e.active) subjects.push({ id: e.code, kind: "bespoke", read: (ed, form) => wp.paperFor(e.code, ed, form) });
    else {
      subjects.push({
        id: `${e.code}__${e.source}.json`,
        kind: "shadowed",
        read: (ed, form) => lf.resolveLegalFormPaper(se.resolvePaper(e.def, ed), form),
      });
    }
  }
  for (const code of taskCodes) {
    if (!wp.hasBespokePaper(code)) subjects.push({ id: code, kind: "default", read: (ed, form) => wp.paperFor(code, ed, form) });
  }
  subjects.push({ id: "ZZ.0", kind: "default", read: (ed, form) => wp.paperFor("ZZ.0", ed, form) }); // no group at all

  /* ---- paper x edition x legal form ---- */
  const keysets: Record<string, string[]> = {};
  const keysetId = (keys: string[]) => {
    const id = short(digest(keys));
    keysets[id] = keys;
    return id;
  };
  const resolved: Record<string, unknown> = {};
  let combinations = 0;
  for (const s of subjects) {
    const byEdition: Record<string, Record<string, [string, string, string]>> = {};
    for (const ed of editions) {
      byEdition[ed] = {};
      for (const form of forms) {
        const def = s.read(ed, form);
        byEdition[ed][form] = [digest(def), keysetId(types.requiredKeys(def)), keysetId([...types.paperKeys(def)].sort())];
        combinations += 1;
      }
    }
    for (const form of forms) {
      if (canonical(byEdition.current[form].slice(1)) !== canonical(byEdition.revised_2026[form].slice(1))) {
        fail(`${s.id}/${form}: keys change with the edition, the completeness fixture assumes they do not`);
      }
    }
    // a missing or unknown form must read exactly as OTHER
    const other = byEdition.current.OTHER[0];
    for (const odd of [null, "XYZ", "sa"]) {
      if (digest(s.read("current", odd)) !== other) fail(`${s.id}: form ${odd} does not read as OTHER`);
    }
    resolved[s.id] = { kind: s.kind, results: byEdition };
  }

  /* ---- answer sets ---- */
  const results: Record<string, Record<string, unknown[]>> = {};
  let completeness = 0;
  for (const s of subjects) {
    results[s.id] = {};
    for (const form of forms) {
      const def = s.read("current", form);
      results[s.id][form] = SCENARIOS.map((r) => {
        const values = answers(def, types, r);
        const progress = wp.paperProgress(def, values);
        completeness += 1;
        return [
          wp.paperComplete(def, values) ? 1 : 0,
          progress.done,
          progress.total,
          short(sha256(canonical([types.unansweredKeys(def, values), wp.paperMissing(def, values)]))),
        ];
      });
    }
  }

  /* ---- single strings and lookups ---- */
  const texts = [
    "plain", "{{ISA240}} and {{ISA570.horizon}}", "{{ISA240.jeTesting}}, {{ISA240.jeTesting}}", "{{ISA240.nope}}", "{ {ISA240} }",
    "{{isa240}}", "{{}}", "[[lf.board]] of the [[lf.meeting]]", "[[lf.nope]]", "[[lf.Board]]", "[[lf.]]", "[[LF.board]]",
    "{{ISA240}} [[lf.ceo]] {{ISA570.period}}", "é¶–",
  ];
  const textCases: unknown[] = [];
  for (const t of texts) {
    for (const locale of ["en", "fr"]) {
      for (const ed of editions) textCases.push(["resolve_text", [t, ed, locale], se.resolveText(t, ed, locale)]);
      for (const form of [...forms, null, "XYZ"]) {
        textCases.push(["resolve_legal_form_text", [t, form, locale], lf.resolveLegalFormText(t, form, locale)]);
      }
    }
    textCases.push(["has_unresolved_token", [t], se.hasUnresolvedToken(t)]);
    textCases.push(["has_unresolved_legal_form_token", [t], lf.hasUnresolvedLegalFormToken(t)]);
  }
  for (const list of [[], ["SA"], ["SA", "SA_AG"], ["OTHER"], ["SAS", "GIE", "OTHER"]]) {
    for (const form of [...forms, null, "XYZ"]) textCases.push(["applies_to_form", [list, form], lf.appliesToForm(list, form)]);
  }
  textCases.push(["applies_to_form", [null, "SA"], lf.appliesToForm(undefined, "SA")]);
  for (const code of [...taskCodes, "ZZ.0", "E4.999", "P1"]) {
    textCases.push(["group_of_task", [code], tg.groupOfTask(code)?.id ?? null]);
    textCases.push(["has_bespoke_paper", [code], wp.hasBespokePaper(code)]);
    for (const form of [...forms, null, "XYZ"]) {
      textCases.push(["task_applies_to_form", [code, form], lf.taskAppliesToForm(code, form)]);
    }
  }

  const out = path.join(ADDON_DIR, "tests", "fixtures", "parity");
  mkdirSync(out, { recursive: true });
  const write = (name: string, value: unknown) => writeFileSync(path.join(out, name), `${JSON.stringify(value)}\n`, "utf8");
  write("resolved.json", { baseline_commit: commit, editions, forms, combinations, keysets, subjects: resolved });
  write("completeness.json", { baseline_commit: commit, edition: "current", scenarios: SCENARIOS, comparisons: completeness, results });
  write("cases.json", { baseline_commit: commit, cases: textCases });
  console.log(`baseline ${commit}`);
  console.log(`subjects ${subjects.length} (${entries.length} definitions + ${subjects.length - entries.length} on the default paper)`);
  console.log(`combinations ${combinations}, keysets ${Object.keys(keysets).length}, completeness ${completeness}, cases ${textCases.length}`);
  process.exit(0);
}

main().catch((err) => fail(err instanceof Error ? err.stack ?? err.message : String(err)));
