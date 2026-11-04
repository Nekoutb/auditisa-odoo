// Records { fn, args, out } / { fn, args, throws } per call and writes one JSON
// file per module. JS values JSON cannot carry are tagged; the pytest side
// decodes the same tags. -0 goes through as 0, as JSON.stringify writes it.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export function enc(v: unknown): unknown {
  if (v === undefined) return { $js: "undefined" };
  if (typeof v === "number") {
    if (Number.isNaN(v)) return { $js: "NaN" };
    if (v === Infinity) return { $js: "Infinity" };
    if (v === -Infinity) return { $js: "-Infinity" };
    return v;
  }
  if (v === null || typeof v === "string" || typeof v === "boolean") return v;
  if (v instanceof Map) return { $map: [...v.entries()].map(([k, x]) => [enc(k), enc(x)]) };
  if (v instanceof Set) return { $set: [...v.values()].map(enc) };
  if (v instanceof Date) return { $date: v.getTime() };
  if (Array.isArray(v)) return v.map(enc);
  if (typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v as object)) if (x !== undefined) out[k] = enc(x);
    return out;
  }
  throw new Error(`cannot encode ${typeof v}`);
}

export class Recorder {
  cases: unknown[] = [];
  constructor(public module: string) {}
  /** Record one call of a sync function. */
  call(fn: string, f: (...a: any[]) => unknown, ...args: unknown[]): void {
    const encoded = args.map(enc);
    try {
      this.cases.push({ fn, args: encoded, out: enc(f(...args)) });
    } catch (e) {
      this.cases.push({ fn, args: encoded, throws: (e as Error).message });
    }
  }
  /** Record one call of an async function, with the args the Python side will take. */
  async acall(fn: string, f: () => Promise<unknown>, args: unknown[]): Promise<void> {
    const encoded = args.map(enc);
    try {
      this.cases.push({ fn, args: encoded, out: enc(await f()) });
    } catch (e) {
      this.cases.push({ fn, args: encoded, throws: (e as Error).message });
    }
  }
  /** A constant table or a value computed outside `call`. */
  value(fn: string, args: unknown[], out: unknown): void {
    this.cases.push({ fn, args: args.map(enc), out: enc(out) });
  }
  write(): number {
    const dir = process.env.PARITY_OUT!;
    mkdirSync(dir, { recursive: true });
    const body = this.cases.map((c) => JSON.stringify(c)).join(",\n");
    writeFileSync(
      join(dir, `${this.module}.json`),
      `{"module":${JSON.stringify(this.module)},"baseline":${JSON.stringify(process.env.PARITY_BASELINE)},"node":${JSON.stringify(process.version)},"cases":[\n${body}\n]}\n`,
    );
    console.log(`${this.module}: ${this.cases.length}`);
    return this.cases.length;
  }
}
