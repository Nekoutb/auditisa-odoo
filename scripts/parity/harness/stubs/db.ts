// Parity stub for lib/db.ts: every query goes to the answer sheet in fakedb.ts.
const q = (text: string, values?: unknown[]) => (globalThis as any).__fakeQuery(text, values);
export const pool = { query: q };
export async function withTenant<T>(_tenantId: string, fn: (tx: any) => Promise<T>): Promise<T> {
  return fn({ query: q });
}
export async function closePool(): Promise<void> {}
