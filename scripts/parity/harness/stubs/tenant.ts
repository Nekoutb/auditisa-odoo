// Parity stub for lib/tenant.ts: a fixed signed-in partner, no session.
export interface TenantContext { tenantId: string; userId: string; role: string; isSuper?: boolean }
export class ForbiddenError extends Error {}
const ctx: TenantContext = { tenantId: "tenant-1", userId: "user-1", role: "partner" };
export async function requireTenant() { return ctx; }
export async function requireWrite() { return ctx; }
export async function requireRole(_min: string) { return ctx; }
export async function requirePortalUser() { return { ...ctx, clientId: "client-1" }; }
