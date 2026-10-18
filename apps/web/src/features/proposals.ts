/** Pure helpers for real (Phase 4) proposed actions, shared by the Overview and Human review tabs. */
import type { ExplanationPath, ProposedActionOut } from "../api/types";

/** The explanation path a real proposal acts on (same target and deployment, else same target), for its approval policy. */
export function pathForProposal(paths: readonly ExplanationPath[], p: ProposedActionOut): ExplanationPath | undefined {
  return (
    paths.find((path) => path.target_service_id === p.target_service_id && path.deployment.id === p.deployment_id) ??
    paths.find((path) => path.target_service_id === p.target_service_id)
  );
}

/** First `length` characters of a hex digest plus an ellipsis, e.g. "efa915179908…". Show the full value in a title. */
export function shortHash(hash: string, length = 12): string {
  return hash.length > length ? `${hash.slice(0, length)}…` : hash;
}

/** 0.7 -> "70%". */
export function formatConfidence(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}
