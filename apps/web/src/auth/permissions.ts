/**
 * Client-side mirror of the server's demo permissions. UX only: it decides what to enable or explain.
 * The server enforces every permission; a 403 from it is always authoritative.
 */
import { DEMO_USERS, type DemoUser } from "../api/types";

export const PERMISSIONS = [
  "incident:read",
  "incident:write",
  "alert:ingest",
  "investigation:create",
  "action:review",
] as const;
export type Permission = (typeof PERMISSIONS)[number];

const GRANTS: Record<DemoUser, readonly Permission[]> = {
  "demo-viewer": ["incident:read"],
  "demo-responder": ["incident:read", "incident:write", "alert:ingest", "investigation:create"],
  "payments-lead": ["incident:read", "incident:write", "investigation:create", "action:review"],
};

const ROLES: Record<DemoUser, readonly string[]> = {
  "demo-viewer": [],
  "demo-responder": ["oncall:checkout"],
  "payments-lead": ["approver:payment"],
};

export const DEMO_USER_LABELS: Record<DemoUser, string> = {
  "demo-viewer": "demo-viewer (read only)",
  "demo-responder": "demo-responder (on-call, checkout)",
  "payments-lead": "payments-lead (payment approver)",
};

export { DEMO_USERS };
export const DEFAULT_DEMO_USER: DemoUser = "demo-viewer";

export function isDemoUser(value: unknown): value is DemoUser {
  return typeof value === "string" && (DEMO_USERS as readonly string[]).includes(value);
}

export function can(user: DemoUser, permission: Permission): boolean {
  return GRANTS[user].includes(permission);
}

export function permissionsFor(user: DemoUser): readonly Permission[] {
  return GRANTS[user];
}

/** Responder roles, e.g. "approver:payment". Compare with DecisionRef.required_approver_role. */
export function rolesFor(user: DemoUser): readonly string[] {
  return ROLES[user];
}

/** Which demo users hold a permission; handy for "switch to X to do this" hints. */
export function usersWith(permission: Permission): DemoUser[] {
  return DEMO_USERS.filter((u) => can(u, permission));
}
