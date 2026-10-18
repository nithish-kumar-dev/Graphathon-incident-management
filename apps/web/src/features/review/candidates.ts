/** Pure helpers for the Human review tab: candidate previews derived from explanation paths. */
import type { ExplanationPath, RunbookRef } from "../../api/types";

export const DECISIONS = ["APPROVE", "REJECT", "REQUEST_REVISION", "ESCALATE"] as const;

export interface CandidateAction {
  key: string;
  actionType: string;
  path: ExplanationPath;
  runbook: RunbookRef;
}

/** One preview per (explanation path, runbook, allowed action type). */
export function deriveCandidates(paths: readonly ExplanationPath[]): CandidateAction[] {
  const out: CandidateAction[] = [];
  paths.forEach((path, i) => {
    for (const runbook of path.runbooks ?? []) {
      for (const actionType of runbook.allowed_action_types ?? []) {
        out.push({ key: `${i}:${runbook.id}:${actionType}`, actionType, path, runbook });
      }
    }
  });
  return out;
}

/** The exact arguments a Phase 5 proposal would carry. tenant_id is the id prefix ("nova.svc.x" -> "nova"). */
export function candidateArgs(c: CandidateAction) {
  const target = c.path.target_service_id;
  return {
    action_type: c.actionType,
    tenant_id: target.split(".")[0] ?? "",
    service_id: target,
    deployment_id: c.path.deployment.id,
    from_version: c.path.deployment.version,
  };
}

export function riskFor(actionType: string): string {
  return actionType.includes("rollback") ? "medium (simulated rollback)" : "unassessed";
}

export function requiredRoles(path: ExplanationPath): string[] {
  if (path.approval_policy === "no_active_policy_escalate") return [];
  return [
    ...new Set(
      (path.governing_decisions ?? []).map((d) => d.required_approver_role).filter((r): r is string => Boolean(r)),
    ),
  ];
}
