import type { GateDecision, GateViolation } from "../../api/types";
import { Badge, type BadgeTone, type BadgeVariant } from "./Badge";
import { CodeBlock } from "./CodeBlock";

const GATE: Record<GateDecision, { tone: BadgeTone; variant: BadgeVariant; label: string; help: string }> = {
  accept: { tone: "success", variant: "soft", label: "accept", help: "The safety gate accepted the run's output." },
  revise: { tone: "info", variant: "soft", label: "revise", help: "The safety gate asked the investigator to revise its output." },
  recommendation_only: {
    tone: "info",
    variant: "outline",
    label: "recommendation only",
    help: "The safety gate limited the run to recommendations; nothing is staged for execution.",
  },
  escalate: {
    tone: "warning",
    variant: "solid",
    label: "escalate",
    help: "The safety gate escalated to a human: an unsafe or invalid action was proposed and revisions ran out.",
  },
  inconclusive: { tone: "neutral", variant: "outline", label: "inconclusive", help: "No evidence-backed hypothesis passed the gate." },
};

/** The safety gate's verdict on an investigation run. */
export function GateDecisionBadge({ decision }: { decision: GateDecision }) {
  const g = GATE[decision] ?? { tone: "neutral" as const, variant: "outline" as const, label: decision, help: "" };
  return (
    <Badge tone={g.tone} variant={g.variant} title={g.help || `Gate decision: ${decision}`}>
      gate: {g.label}
    </Badge>
  );
}

/** Each gate violation as code, target and detail. */
export function GateViolationList({ violations, label = "Gate violations" }: { violations: GateViolation[]; label?: string }) {
  if (violations.length === 0) return <p className="text-sm text-slate-600">No gate violations.</p>;
  return (
    <ul aria-label={label} className="flex flex-col gap-1.5">
      {violations.map((v, i) => (
        <li key={`${i}-${v.code}-${v.target}`} className="min-w-0 rounded-md border border-amber-400 bg-amber-50 p-2 text-sm text-amber-950">
          <CodeBlock inline value={v.code} className="font-semibold" /> <span className="text-xs text-amber-900">at</span>{" "}
          <CodeBlock inline value={v.target} />
          <p className="mt-0.5 break-words">{v.detail}</p>
        </li>
      ))}
    </ul>
  );
}
