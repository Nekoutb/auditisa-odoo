// Parity stub for lib/execution.ts: routeFinding only records what it was asked to route.
export async function routeFinding(input: unknown) {
  ((globalThis as any).__findings ??= []).push(input);
  return { findingId: "finding-1" };
}
