// The answer sheet behind the lib/db.ts stub. First matching pattern answers;
// everything else gets no rows. Every call is logged for the case to inspect.
export type Answer =
  | { rows: any[]; rowCount?: number }
  | ((text: string, values?: unknown[]) => { rows: any[]; rowCount?: number });

export class FakeDb {
  log: { text: string; values?: unknown[] }[] = [];
  constructor(private rules: [RegExp, Answer][] = []) {
    (globalThis as any).__fakeQuery = async (text: string, values?: unknown[]) => {
      this.log.push({ text, values });
      for (const [re, answer] of this.rules) {
        if (re.test(text)) return typeof answer === "function" ? answer(text, values) : answer;
      }
      return { rows: [], rowCount: 0 };
    };
    (globalThis as any).__findings = [];
  }
  /** The values of the first logged query matching `re`. */
  values(re: RegExp): unknown[] | undefined {
    return this.log.find((l) => re.test(l.text))?.values;
  }
  get findings(): any[] {
    return (globalThis as any).__findings;
  }
}
