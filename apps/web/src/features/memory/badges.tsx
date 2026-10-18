import type { MatchedBy as MatchedByStep, MemoryApplicability, Precedent, VerificationStatus } from "../../api/types";
import { Badge } from "../../components/ui";

export interface CredibilityBadgeProps {
  verificationStatus: VerificationStatus;
  precedent: Precedent;
  /** Reached only by text similarity: it can never support or warn. */
  textOnly?: boolean;
}

/**
 * What a memory may be used for. Only a verified memory carries precedent:
 * supports = verified success, warns against = verified failure (do not repeat it).
 */
export function CredibilityBadge({ verificationStatus, precedent, textOnly = false }: CredibilityBadgeProps) {
  if (verificationStatus === "draft") {
    return (
      <Badge tone="warning" variant="dashed" icon="✎" title="Unverified draft. It cannot support or warn against an action.">
        Draft — not usable as precedent
      </Badge>
    );
  }
  if (verificationStatus !== "verified") {
    return (
      <Badge tone="neutral" variant="dashed" title="Only verified memories carry precedent.">
        {verificationStatus === "rejected" ? "Rejected" : "Superseded"} — not usable as precedent
      </Badge>
    );
  }
  if (textOnly) {
    return (
      <Badge tone="neutral" variant="outline" title="Similar text is never a cause.">
        Text similarity only — cannot support or warn
      </Badge>
    );
  }
  if (precedent === "supports") {
    return (
      <Badge tone="success" variant="solid" icon="✓" title="Verified successful outcome: supports this action.">
        Supports
      </Badge>
    );
  }
  if (precedent === "warns_against") {
    return (
      <Badge tone="danger" variant="solid" icon="⚠" title="Verified failed outcome: do not repeat this action.">
        Warns against — do not repeat
      </Badge>
    );
  }
  return (
    <Badge tone="neutral" variant="outline" title="This memory neither supports nor warns against an action.">
      No precedent
    </Badge>
  );
}

const APPLICABILITY_LABEL: Record<MemoryApplicability, string> = {
  same_incident: "same incident",
  shared_service: "shared service",
  dependency_related: "dependency related",
  text_similarity_only: "text similarity only",
};

export function ApplicabilityBadge({ applicability }: { applicability: MemoryApplicability }) {
  return (
    <Badge tone={applicability === "text_similarity_only" ? "neutral" : "accent"} variant="outline" title="Applicability">
      applies: {APPLICABILITY_LABEL[applicability] ?? applicability}
    </Badge>
  );
}

export function MatchedBy({ steps }: { steps: readonly MatchedByStep[] }) {
  if (steps.length === 0) return <span className="text-slate-500">—</span>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {steps.map((s) => (
        <li key={s}>
          <Badge variant="outline">{s}</Badge>
        </li>
      ))}
    </ul>
  );
}
