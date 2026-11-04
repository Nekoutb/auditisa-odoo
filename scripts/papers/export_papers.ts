// Exports the working-paper definitions of AuditISA to addons/ea_audit_papers/data.
//
//   tsx --tsconfig <platform>/tsconfig.json scripts/papers/export_papers.ts --platform <platform>
//
// One JSON per task code, UNRESOLVED ({{ISA...}} and [[lf.x]] tokens and `forms`
// filters kept, draft marks untouched), plus the index, the token tables and the
// group-derived default paper. scripts/papers/run_baseline.sh sets up a clean
// checkout and runs this. Exits non-zero on anything that is not plain data.

import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import {
  ADDON_DIR, REGISTRY_MAPS, baselineCommit, canonical, digest, fail, load, platformDir, registryEntries, sourceOf,
  type Entry, type PaperDef,
} from "./platform";

const EDITION_TOKEN = /\{\{([A-Za-z0-9_.]+)\}\}/g;
const FORM_TOKEN = /\[\[lf\.([a-z]+)\]\]/g;
const MARKS = ["[Projet]", "[Draft]", "(à valider)"] as const;

/* ---- what may be exported: plain data, nothing else ---- */

function nonSerialisable(value: unknown, where: string, seen: Set<object>, out: string[]): void {
  switch (typeof value) {
    case "string":
    case "boolean":
      return;
    case "number":
      if (!Number.isInteger(value)) out.push(`${where}: number ${value} has no canonical form across TS and Python`);
      return;
    case "function":
      out.push(`${where}: function ${(value as { name?: string }).name || "(anonymous)"}`);
      return;
    case "symbol":
    case "bigint":
      out.push(`${where}: ${typeof value}`);
      return;
  }
  if (value === null) return;
  if (value === undefined) {
    out.push(`${where}: undefined inside an array`);
    return;
  }
  const obj = value as object;
  if (seen.has(obj)) {
    out.push(`${where}: circular reference`);
    return;
  }
  seen.add(obj);
  if (Array.isArray(obj)) {
    obj.forEach((v, i) => nonSerialisable(v, `${where}[${i}]`, seen, out));
  } else {
    const proto = Object.getPrototypeOf(obj);
    if (proto !== Object.prototype && proto !== null) out.push(`${where}: instance of ${proto.constructor?.name}`);
    for (const key of Reflect.ownKeys(obj)) {
      if (typeof key === "symbol") {
        out.push(`${where}: symbol key`);
        continue;
      }
      const d = Object.getOwnPropertyDescriptor(obj, key)!;
      if (d.get || d.set) {
        out.push(`${where}.${key}: accessor`);
        continue;
      }
      if (d.value !== undefined) nonSerialisable(d.value, `${where}.${key}`, seen, out); // absent optional: dropped
    }
  }
  seen.delete(obj);
}

function walkStrings(value: unknown, visit: (s: string) => void): void {
  if (typeof value === "string") visit(value);
  else if (Array.isArray(value)) value.forEach((v) => walkStrings(v, visit));
  else if (value && typeof value === "object") Object.values(value).forEach((v) => walkStrings(v, visit));
}

function writeJson(file: string, value: unknown): void {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(value, null, 1)}\n`, "utf8");
}

/** GROUP_DEFAULT is private to working-papers.ts and holds tokens paperFor resolves away. */
function groupDefaultFromSource(dir: string): Record<string, { std: string; en: string; fr: string }> {
  const src = sourceOf(dir, "lib/working-papers.ts");
  const m = /const GROUP_DEFAULT:[^=]*=\s*(\{[\s\S]*?\n\});/.exec(src);
  if (!m) fail("GROUP_DEFAULT not found in lib/working-papers.ts");
  return new Function(`return (${m[1]});`)();
}

async function main(): Promise<void> {
  const dir = platformDir();
  const commit = baselineCommit(dir);

  const entries = await registryEntries(dir);
  const active = entries.filter((e) => e.active);
  const shadowed = entries.filter((e) => !e.active);

  /* ---- fail loudly on anything that is not data ---- */
  const problems: string[] = [];
  for (const e of entries) nonSerialisable(e.def, `${e.code} (${e.source})`, new Set(), problems);
  if (problems.length) fail(`${problems.length} non-serialisable value(s):\n${problems.join("\n")}`);

  /* ---- the real registry, against what this script is about to write ---- */
  const wp = await load(dir, "lib/working-papers");
  const se = await load(dir, "lib/standards-edition");
  const lf = await load(dir, "lib/legal-forms");
  const tg = await load(dir, "lib/task-groups");
  const fi = await load(dir, "lib/file-index");

  const taskCodes: string[] = fi.DEFAULT_FILE_INDEX.map((t: { code: string }) => t.code);
  const activeByCode = new Map(active.map((e) => [e.code, e]));
  for (const code of activeByCode.keys()) {
    if (!wp.hasBespokePaper(code)) fail(`${code} is in a map but hasBespokePaper() denies it`);
  }
  const bespokeTasks = taskCodes.filter((c) => wp.hasBespokePaper(c));
  for (const c of bespokeTasks) if (!activeByCode.has(c)) fail(`hasBespokePaper(${c}) with no definition found`);
  const defaultTasks = taskCodes.filter((c) => !wp.hasBespokePaper(c));
  const unindexed = [...activeByCode.keys()].filter((c) => !taskCodes.includes(c));

  const editions: string[] = [...se.STANDARDS_EDITIONS];
  const forms: string[] = [...lf.LEGAL_FORMS];
  for (const e of active) {
    for (const ed of editions) {
      for (const form of forms) {
        const viaRegistry = canonical(wp.paperFor(e.code, ed, form));
        const viaEntry = canonical(lf.resolveLegalFormPaper(se.resolvePaper(e.def, ed), form));
        if (viaRegistry !== viaEntry) fail(`${e.code}: paperFor() does not return this definition (${ed}, ${form})`);
      }
    }
  }

  /* ---- the group-derived default paper ---- */
  const groupDefault = groupDefaultFromSource(dir);
  const generic = wp.paperFor("ZZ.0") as PaperDef; // outside every group: the fallback
  const groupsOf: Record<string, string> = {};
  for (const g of tg.TASK_GROUPS as { id: string; code: string; members: string[] }[]) {
    for (const member of g.members) groupsOf[member] = g.id;
  }
  const prefixes = Object.fromEntries((tg.TASK_GROUPS as { id: string; code: string }[]).map((g) => [g.code, g.id]));
  const defaults = {
    fields: generic.fields,
    groups: Object.fromEntries(
      Object.entries(groupDefault).map(([id, d]) => [id, { std: d.std, ownsEn: d.en, ownsFr: d.fr }]),
    ),
    fallback: { std: generic.std, ownsEn: generic.ownsEn, ownsFr: generic.ownsFr },
    members: groupsOf,
    prefixes,
  };
  const defaultOf = (code: string): PaperDef => {
    const gid: string | undefined = tg.groupOfTask(code)?.id;
    const head = (gid && (defaults.groups as Record<string, object>)[gid]) || defaults.fallback;
    return { ...head, fields: defaults.fields } as PaperDef;
  };
  for (const code of defaultTasks) {
    for (const ed of editions) {
      const viaRegistry = canonical(wp.paperFor(code, ed, "OTHER"));
      const viaData = canonical(lf.resolveLegalFormPaper(se.resolvePaper(defaultOf(code), ed), "OTHER"));
      if (viaRegistry !== viaData) fail(`${code}: the exported default paper differs from paperFor() under ${ed}`);
    }
  }

  /* ---- token tables, read through the modules' own accessors ---- */
  const refs: Record<string, Record<string, [string, string]>> = {};
  for (const key of se.ISA_REF_KEYS as string[]) {
    refs[key] = {};
    for (const ed of editions) refs[key][ed] = [se.isaRef(ed, key, "en"), se.isaRef(ed, key, "fr")];
  }
  const iface = /interface LegalFormVocabulary \{([\s\S]*?)\n\}/.exec(sourceOf(dir, "lib/legal-forms.ts"));
  if (!iface) fail("LegalFormVocabulary not found in lib/legal-forms.ts");
  const organKeys = [...iface[1].matchAll(/^\s*([a-z]+): Pair;/gm)].map((m) => m[1]);
  if (organKeys.length === 0) fail("no organ keys parsed from LegalFormVocabulary");
  const vocabulary: Record<string, Record<string, [string, string]>> = {};
  for (const form of forms) {
    vocabulary[form] = {};
    for (const k of organKeys) vocabulary[form][k] = [lf.organName(form, k, "en"), lf.organName(form, k, "fr")];
  }
  const taskExclusions: Record<string, string[]> = {};
  for (const code of taskCodes) {
    const out = forms.filter((f) => !lf.taskAppliesToForm(code, f));
    if (out.length) taskExclusions[code] = out;
  }

  /* ---- findings the export reports without refusing ---- */
  const lint: string[] = [];
  const marks: Record<string, number> = Object.fromEntries(MARKS.map((m) => [m, 0]));
  const usedEdition = new Set<string>();
  const usedForm = new Set<string>();
  for (const e of entries) {
    const def = e.def as Record<string, any>;
    walkStrings(def, (s) => {
      for (const m of s.matchAll(EDITION_TOKEN)) usedEdition.add(m[1]);
      for (const m of s.matchAll(FORM_TOKEN)) usedForm.add(m[1]);
      for (const mark of MARKS) marks[mark] += s.split(mark).length - 1;
    });
    const label = `${e.code} (${e.source})`;
    for (const [en, fr] of [["reqEn", "reqFr"], ["conclEn", "conclFr"]]) {
      if ((def[en]?.length ?? 0) !== (def[fr]?.length ?? 0)) lint.push(`${label}: ${en} has ${def[en]?.length ?? 0} entries, ${fr} ${def[fr]?.length ?? 0}`);
    }
    const required: string[] = (await load(dir, "lib/papers/types")).requiredKeys(def);
    const dupes = required.filter((k, i) => required.indexOf(k) !== i);
    if (dupes.length) lint.push(`${label}: duplicate required keys ${[...new Set(dupes)].join(", ")}`);
    if (e.active && required.length === 0) lint.push(`${label}: no required key at all`);
  }
  for (const t of usedEdition) if (!(t in refs)) lint.push(`unknown edition token {{${t}}} stays visible on screen`);
  for (const t of usedForm) if (!organKeys.includes(t)) lint.push(`unknown legal-form token [[lf.${t}]] stays visible on screen`);

  // Keys that exist on some form but not under paperFor(code), which savePaper
  // uses as its allow-list (lf absent reads as OTHER): answers there do not save.
  const types = await load(dir, "lib/papers/types");
  const lostOnSave: Record<string, string[]> = {};
  for (const e of active) {
    const bare = new Set<string>(types.paperKeys(wp.paperFor(e.code)));
    const lost = new Set<string>();
    for (const form of forms) {
      for (const k of types.paperKeys(wp.paperFor(e.code, "current", form)) as Set<string>) {
        if (!bare.has(k)) lost.add(k);
      }
    }
    if (lost.size) lostOnSave[e.code] = [...lost];
  }

  /* ---- write ---- */
  const dataDir = path.join(ADDON_DIR, "data");
  const papersDir = path.join(dataDir, "papers");
  const shadowDir = path.join(dataDir, "papers_shadowed");
  rmSync(papersDir, { recursive: true, force: true });
  rmSync(shadowDir, { recursive: true, force: true });

  const record = (e: Entry) => ({ code: e.code, source: `lib/papers/${e.source}.ts`, definition: e.def });
  for (const e of active) writeJson(path.join(papersDir, `${e.code}.json`), record(e));
  for (const e of shadowed) writeJson(path.join(shadowDir, `${e.code}__${e.source}.json`), record(e));
  writeJson(path.join(dataDir, "group_defaults.json"), defaults);
  writeJson(path.join(dataDir, "standards_refs.json"), {
    editions,
    revised_2026_from: se.REVISED_2026_FROM,
    refs,
  });
  writeJson(path.join(dataDir, "legal_forms.json"), {
    forms,
    organ_keys: organKeys,
    vocabulary,
    task_exclusions: taskExclusions,
  });
  const index = {
    baseline_commit: commit,
    counts: {
      definitions: entries.length,
      codes: active.length,
      shadowed: shadowed.length,
      task_codes: taskCodes.length,
      tasks_on_default_paper: defaultTasks.length,
    },
    marks,
    papers: Object.fromEntries(
      active
        .slice()
        .sort((a, b) => a.code.localeCompare(b.code, "en", { numeric: true }))
        .map((e) => [e.code, { source: `lib/papers/${e.source}.ts`, definition_hash: digest(e.def) }]),
    ),
    shadowed: shadowed.map((e) => {
      const winner = activeByCode.get(e.code)!;
      return {
        code: e.code,
        file: `${e.code}__${e.source}.json`,
        source: `lib/papers/${e.source}.ts`,
        shadowed_by: `lib/papers/${winner.source}.ts`,
        definition_hash: digest(e.def),
      };
    }),
    tasks_on_default_paper: defaultTasks,
    bespoke_outside_file_index: unindexed,
    lint,
    keys_refused_by_save_allow_list: lostOnSave,
  };
  writeJson(path.join(papersDir, "index.json"), index);

  /* ---- read it all back: what is on disk is what the source says ---- */
  for (const e of active) {
    const back = JSON.parse(readFileSync(path.join(papersDir, `${e.code}.json`), "utf8"));
    if (canonical(back.definition) !== canonical(e.def)) fail(`${e.code}: file on disk differs from the definition`);
  }
  const written = readdirSync(papersDir).filter((f) => f !== "index.json").length;
  if (written !== activeByCode.size) fail(`wrote ${written} files for ${activeByCode.size} codes`);

  const expected = REGISTRY_MAPS.length && 95;
  console.log(`baseline ${commit}`);
  console.log(`definitions ${entries.length} (expected ${expected}), codes ${active.length}, shadowed ${shadowed.map((e) => `${e.code}@${e.source}`).join(", ") || "none"}`);
  console.log(`file index: ${taskCodes.length} codes, ${bespokeTasks.length} bespoke, ${defaultTasks.length} on the default paper; bespoke outside the index: ${unindexed.join(", ") || "none"}`);
  console.log(`tokens used: ${usedEdition.size} edition, ${usedForm.size} legal-form; marks ${JSON.stringify(marks)}`);
  console.log(`lint (${lint.length}):`);
  lint.forEach((l) => console.log(`  ${l}`));
  console.log(`save allow-list loses keys on ${Object.keys(lostOnSave).length} paper(s): ${Object.entries(lostOnSave).map(([c, k]) => `${c}[${k.length}]`).join(" ")}`);
  if (entries.length !== expected) fail(`${entries.length} definitions, expected ${expected}`);
  process.exit(0); // the imported pool module holds nothing open, but do not wait on it
}

main().catch((err) => fail(err instanceof Error ? err.stack ?? err.message : String(err)));
