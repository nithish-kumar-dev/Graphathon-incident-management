import type { BranchStatus, ClaimType, IncidentStatus, InvestigationStatus, Severity } from "../../api/types";
import { Badge, type BadgeTone, type BadgeVariant } from "./Badge";

const INCIDENT_STATUS: Record<IncidentStatus, { tone: BadgeTone; label: string }> = {
  open: { tone: "danger", label: "Open" },
  investigating: { tone: "warning", label: "Investigating" },
  mitigated: { tone: "info", label: "Mitigated" },
  resolved: { tone: "success", label: "Resolved" },
};

export function StatusBadge({ status }: { status: IncidentStatus }) {
  const s = INCIDENT_STATUS[status] ?? { tone: "neutral" as const, label: status };
  return (
    <Badge tone={s.tone} title={`Incident status: ${s.label}`}>
      {s.label}
    </Badge>
  );
}

const SEVERITY: Record<Severity, { tone: BadgeTone; variant: BadgeVariant }> = {
  sev1: { tone: "danger", variant: "solid" },
  sev2: { tone: "warning", variant: "solid" },
  sev3: { tone: "warning", variant: "soft" },
  sev4: { tone: "neutral", variant: "soft" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity] ?? { tone: "neutral" as const, variant: "soft" as const };
  return (
    <Badge tone={s.tone} variant={s.variant} title={`Severity ${severity.toUpperCase()}`}>
      {severity.toUpperCase()}
    </Badge>
  );
}

const CLAIM: Record<ClaimType, { tone: BadgeTone; variant: BadgeVariant; icon: string; label: string; help: string }> = {
  observed: {
    tone: "info",
    variant: "soft",
    icon: "◉",
    label: "Observed",
    help: "Directly observed in telemetry or records.",
  },
  correlated: {
    tone: "warning",
    variant: "dashed",
    icon: "≈",
    label: "Correlated · not confirmed",
    help: "A graph correlation. Evidence for a hypothesis, not a confirmed cause.",
  },
  hypothesis: {
    tone: "accent",
    variant: "dashed",
    icon: "?",
    label: "Hypothesis · not confirmed",
    help: "A proposed explanation that has not been confirmed.",
  },
  confirmed: {
    tone: "success",
    variant: "solid",
    icon: "✓",
    label: "Confirmed",
    help: "Confirmed by a human or by ground truth.",
  },
};

/** Distinct style per claim type. Correlated and hypothesis are dashed and say "not confirmed" in text. */
export function ClaimTypeBadge({ claimType }: { claimType: ClaimType }) {
  const c = CLAIM[claimType] ?? { tone: "neutral" as const, variant: "outline" as const, icon: "", label: claimType, help: "" };
  return (
    <Badge tone={c.tone} variant={c.variant} icon={c.icon} title={c.help}>
      {c.label}
    </Badge>
  );
}

const INVESTIGATION: Record<InvestigationStatus, { tone: BadgeTone; label: string }> = {
  queued: { tone: "neutral", label: "Queued" },
  running: { tone: "info", label: "Running" },
  awaiting_review: { tone: "accent", label: "Awaiting review" },
  completed: { tone: "success", label: "Completed" },
  failed: { tone: "danger", label: "Failed" },
  escalated: { tone: "warning", label: "Escalated" },
  inconclusive: { tone: "neutral", label: "Inconclusive" },
  timed_out: { tone: "danger", label: "Timed out" },
};

export function InvestigationStatusBadge({ status }: { status: InvestigationStatus }) {
  const s = INVESTIGATION[status] ?? { tone: "neutral" as const, label: status };
  return (
    <Badge tone={s.tone} title={`Investigation status: ${s.label}`}>
      {s.label}
    </Badge>
  );
}

const BRANCH: Record<BranchStatus, BadgeTone> = {
  pending: "neutral",
  running: "info",
  completed: "success",
  failed: "danger",
  skipped: "neutral",
  not_recorded: "neutral",
};

export function BranchStatusBadge({ status }: { status: BranchStatus }) {
  return (
    <Badge tone={BRANCH[status] ?? "neutral"} variant={status === "skipped" || status === "not_recorded" ? "outline" : "soft"}>
      {status.replace("_", " ")}
    </Badge>
  );
}

/** True for a "stub-fallback(...)" investigator: the configured LLM failed and a deterministic stub ran instead. */
export function isFallbackInvestigator(investigator: string | null | undefined): boolean {
  return Boolean(investigator && investigator.startsWith("stub-fallback"));
}

/** Which investigator produced the run. A fallback is flagged loudly, since it is not the configured model. */
export function InvestigatorBadge({ investigator }: { investigator: string }) {
  if (isFallbackInvestigator(investigator)) {
    return (
      <Badge
        tone="warning"
        variant="solid"
        icon="⚠"
        title="Fallback: the configured LLM investigator was unavailable, so a deterministic stub produced this result."
      >
        {investigator}
      </Badge>
    );
  }
  return (
    <Badge tone="neutral" variant="outline" title={`Investigator: ${investigator}`}>
      {investigator}
    </Badge>
  );
}

const PROPOSAL_STATUS: Record<string, BadgeTone> = {
  proposed: "info",
  pending_review: "accent",
  approved: "success",
  executed_simulated: "success",
  rejected: "danger",
  revision_requested: "warning",
  escalated: "warning",
  expired: "neutral",
  superseded: "neutral",
};

/** Lifecycle state of a proposed action. A proposal is never an executed action. */
export function ProposalStatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={PROPOSAL_STATUS[status] ?? "neutral"} title={`Proposal status: ${status}`}>
      {status.replace(/_/g, " ")}
    </Badge>
  );
}
