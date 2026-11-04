// Shared by export_papers.ts and record_parity.ts: loads the real TypeScript
// definitions and rules from a checkout of platform/, never a copy of them.
//
// The registry (lib/working-papers.ts) imports the database module, which refuses
// to load without a connection string. A pool only connects on its first query
// and these scripts issue none, so the variables below point at a reserved name
// that cannot resolve: if anything ever did query, it would fail, not reach a DB.

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

process.env.APP_DATABASE_URL = "postgres://nobody@no-database.invalid/none";
process.env.DATABASE_URL = "postgres://nobody@no-database.invalid/none";

export const REPO_ROOT = path.resolve(__dirname, "..", "..");
export const ADDON_DIR = path.join(REPO_ROOT, "addons", "ea_audit_papers");

/** The maps of lib/working-papers.ts ALL_PAPERS, in its spread order: a later map wins. */
export const REGISTRY_MAPS: readonly (readonly [file: string, exportName: string])[] = [
  ["acceptance", "ACCEPTANCE_PAPERS"],
  ["strategy", "STRATEGY_PAPERS"],
  ["execution", "EXECUTION_PAPERS"],
  ["itgc", "ITGC_PAPERS"],
  ["journal-entries", "JOURNAL_ENTRY_PAPERS"],
  ["financial-statements", "FINANCIAL_STATEMENT_PAPERS"],
  ["statutory-525", "STATUTORY_525_PAPERS"],
  ["conclusion", "CONCLUSION_PAPERS"],
  ["gam", "GAM_PAPERS"],
];

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
export type PaperDef = Record<string, unknown>;

export function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

export function fail(message: string): never {
  console.error(`FAILED: ${message}`);
  process.exit(1);
}

export function platformDir(): string {
  const dir = arg("platform");
  if (!dir) fail("--platform <path to a clean checkout of platform/> is required");
  const resolved = path.resolve(dir);
  if (!existsSync(path.join(resolved, "lib", "papers", "types.ts"))) fail(`no lib/papers/types.ts under ${resolved}`);
  return resolved;
}

/** The commit a checkout is on; refuses a dirty one, so the data has a real baseline. */
export function baselineCommit(dir: string): string {
  const git = (...a: string[]) => execFileSync("git", ["-C", dir, ...a], { encoding: "utf8" }).trim();
  const dirty = git("status", "--porcelain", "--", ".");
  if (dirty && !process.argv.includes("--allow-dirty")) {
    fail(`checkout is not clean, refusing to export from it:\n${dirty.split("\n").slice(0, 10).join("\n")}`);
  }
  return git("rev-parse", "HEAD");
}

export async function load<T = Record<string, any>>(dir: string, relative: string): Promise<T> {
  const mod = await import(pathToFileURL(path.join(dir, `${relative}.ts`)).href);
  // tsx hands a CommonJS-compiled module back under `default`
  return (mod.default && Object.keys(mod).length <= 2 ? { ...mod.default, ...mod } : mod) as T;
}

export function paperFiles(dir: string): string[] {
  return readdirSync(path.join(dir, "lib", "papers"))
    .filter((f) => f.endsWith(".ts") && f !== "types.ts")
    .map((f) => f.slice(0, -3));
}

/** One definition as the registry can reach it (or not). */
export interface Entry {
  code: string;
  source: string; // file of lib/papers
  mapName: string;
  def: PaperDef;
  active: boolean; // false: a later map defines the same code, paperFor never returns this one
}

/** Every entry of every registry map, with the precedence ALL_PAPERS applies. */
export async function registryEntries(dir: string): Promise<Entry[]> {
  const entries: Entry[] = [];
  for (const [file, mapName] of REGISTRY_MAPS) {
    const mod = await load(dir, `lib/papers/${file}`);
    const map = mod[mapName] as Record<string, PaperDef> | undefined;
    if (!map) fail(`lib/papers/${file}.ts does not export ${mapName}`);
    for (const [code, def] of Object.entries(map)) {
      for (const earlier of entries) if (earlier.code === code) earlier.active = false;
      entries.push({ code, source: file, mapName, def, active: true });
    }
  }
  // A new map added to the folder must not be missed silently.
  const known = new Set(REGISTRY_MAPS.map(([, n]) => n));
  for (const file of paperFiles(dir)) {
    const mod = await load(dir, `lib/papers/${file}`);
    for (const name of Object.keys(mod)) {
      if (name.endsWith("_PAPERS") && !known.has(name)) fail(`lib/papers/${file}.ts exports ${name}, unknown to this script`);
    }
  }
  return entries;
}

/**
 * Serialised exactly as the Python side serialises (services/canonical.py):
 * keys sorted, no whitespace, non-ASCII kept, absent optionals left out.
 */
export function canonical(value: unknown): string {
  return JSON.stringify(sortKeys(value));
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(value as object).sort()) {
      const v = (value as Record<string, unknown>)[k];
      if (v !== undefined) out[k] = sortKeys(v);
    }
    return out;
  }
  return value;
}

export function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

export const digest = (value: unknown): string => sha256(canonical(value));

/** Reads a checkout's source as text, for the two tables its module keeps private. */
export function sourceOf(dir: string, relative: string): string {
  return readFileSync(path.join(dir, relative), "utf8");
}
