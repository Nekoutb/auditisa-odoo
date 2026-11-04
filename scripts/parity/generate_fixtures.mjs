#!/usr/bin/env node
// Parity fixtures: run the REAL TypeScript on a broad input set and record the
// outputs as JSON, so pytest holds the Python ports to TypeScript's actual
// results, float rounding and seeded draws included.
//
// Run it from the platform folder of the source repo:
//
//   cd "EA AUDIT TOOL/platform"
//   node "../../auditisa-odoo-services/scripts/parity/generate_fixtures.mjs"
//
// Nothing is written to the source repo. The baseline commit's lib/ and
// messages/ are checked out into a temp directory (through a throwaway git
// index), so edits made in the platform working tree cannot move the fixtures.
//
// That temp copy differs from the baseline in two ways only:
//   - lib/db.ts, lib/tenant.ts and lib/execution.ts are stubs, so functions that
//     mix logic with queries run against an in-memory answer sheet (no database,
//     no session). Every other line of the logic under test is the real code.
//   - a few private helpers get an `export { ... }` line appended (EXPOSE below).
//
// TZ is forced to UTC: `new Date("2025-01-15 10:00")` and getDay() depend on it.
import { execFileSync, spawnSync } from "node:child_process";
import { appendFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const BASELINE = process.env.PARITY_BASELINE ?? "bd3af7e";
const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../../addons/ea_audit_tools/tests_pure/fixtures");
const platform = process.cwd();

if (!existsSync(join(platform, "node_modules/tsx/dist/cli.mjs"))) {
  console.error("Run this from the platform folder (node_modules/tsx not found here).");
  process.exit(1);
}

/** Private helpers the fixtures need, appended as exports to the temp copy only. */
const EXPOSE = {
  "lib/alerte.ts": ["FLOWS", "flowOf", "nextStagesOf", "eventDateOrToday"],
  "lib/complexity.ts": ["periodEndLabel", "natureLabel"],
  "lib/financial-analysis.ts": ["aggregate", "ratioSet", "DEFS"],
  "lib/lead-classes.ts": ["PREFIX_INDEX", "PREFIX_SUB", "ACCOUNT_TYPE_FR", "ACCOUNT_CLASS_FR"],
  "lib/standards-edition.ts": ["REFS"],
  "lib/subledgers.ts": ["parseCsv"],
  "lib/tb.ts": ["ALIASES", "heuristicFill", "validateMapping", "normalizeHeader"],
  "lib/tb-reasons.ts": ["COLUMN_LABEL"],
};

const git = (args, env = {}) =>
  execFileSync("git", args, { cwd: platform, encoding: "utf8", env: { ...process.env, ...env }, maxBuffer: 1 << 26 }).trim();

const tmp = mkdtempSync(join(tmpdir(), "auditisa-parity-"));
const junction = join(tmp, "node_modules");
let status = 1;
try {
  const commit = git(["rev-parse", "--short", `${BASELINE}^{commit}`]);
  const env = { GIT_INDEX_FILE: join(tmp, ".parity-index") };
  git(["read-tree", "--empty"], env);
  git(["read-tree", "--prefix=lib/", `${commit}:platform/lib`], env);
  git(["read-tree", "--prefix=messages/", `${commit}:platform/messages`], env);
  // from the top of the repo: below it, checkout-index -a keeps only that subfolder's paths
  const top = git(["rev-parse", "--show-toplevel"]);
  git(["-C", top, "checkout-index", "-a", `--prefix=${tmp.replace(/\\/g, "/")}/`], env);
  rmSync(env.GIT_INDEX_FILE, { force: true });

  for (const [file, names] of Object.entries(EXPOSE)) {
    appendFileSync(join(tmp, file), `\nexport { ${names.join(", ")} };\n`);
  }
  const harness = join(here, "harness");
  for (const name of ["db", "tenant", "execution"]) {
    cpSync(join(harness, "stubs", `${name}.ts`), join(tmp, "lib", `${name}.ts`));
  }
  writeFileSync(join(tmp, "auth.ts"), "export const auth = async () => null;\nexport const signIn = async () => null;\nexport const signOut = async () => null;\n");
  cpSync(harness, join(tmp, "_parity"), { recursive: true });
  writeFileSync(
    join(tmp, "tsconfig.json"),
    JSON.stringify({
      compilerOptions: {
        target: "ES2022", module: "esnext", moduleResolution: "bundler", esModuleInterop: true,
        resolveJsonModule: true, jsx: "react-jsx", baseUrl: ".", paths: { "@/*": ["./*"] },
      },
    }),
  );
  symlinkSync(join(platform, "node_modules"), junction, "junction");

  mkdirSync(outDir, { recursive: true });
  const run = spawnSync(
    process.execPath,
    [join(platform, "node_modules/tsx/dist/cli.mjs"), "--tsconfig", join(tmp, "tsconfig.json"), join(tmp, "_parity", process.argv[2] ?? "main.ts")],
    {
      cwd: tmp,
      stdio: "inherit",
      // A clean environment on purpose: no DATABASE_URL, no secrets, nothing from any .env.
      env: {
        PATH: process.env.PATH,
        SystemRoot: process.env.SystemRoot,
        TEMP: process.env.TEMP,
        TMP: process.env.TMP,
        TZ: "UTC",
        LANG: "en_US.UTF-8",
        NODE_OPTIONS: "--max-old-space-size=512",
        PARITY_OUT: outDir,
        PARITY_BASELINE: commit,
      },
    },
  );
  status = run.status ?? 1;
} finally {
  try { unlinkSync(junction); } catch { /* never created */ }
  rmSync(tmp, { recursive: true, force: true });
}
process.exit(status);
