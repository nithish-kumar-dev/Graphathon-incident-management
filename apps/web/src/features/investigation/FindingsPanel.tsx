import { ArrowLink, Badge, ClaimTypeBadge, CodeBlock, EmptyState, SectionCard, cx } from "../../components/ui";
import type { FindingOut } from "../../api/types";
import { shortId } from "../../lib/time";
import { formatConfidence } from "../proposals";
import { useNavigateTab } from "../NavContext";
import { useInvestigationSession } from "./InvestigationSession";
import { CLAIM_LABELS, isActivePhase, type EvidenceCard, type RecommendedAction } from "./model";
import { CollapsibleCard, RelativeTime } from "./ui";

function EvidenceItem({ e }: { e: EvidenceCard }) {
  return (
    <li className="flex min-w-0 flex-col gap-1 rounded-md border border-line bg-surface p-2.5 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-ink">{e.title}</span>
        {e.observedAt ? <RelativeTime iso={e.observedAt} className="text-xs text-faint" /> : null}
      </div>
      <p className="text-ink [overflow-wrap:anywhere]">{e.text}</p>
      <p className="text-xs text-faint">
        Source: <CodeBlock inline value={e.sourceRef} />
      </p>
    </li>
  );
}

function FindingItem({ f, contradicted }: { f: FindingOut; contradicted: boolean }) {
  const against = f.contradicting_evidence ?? [];
  return (
    <li className={cx("flex flex-col gap-1.5 rounded-md border p-2.5 text-sm", contradicted ? "border-bad-line bg-bad-tint" : "border-line bg-surface")}>
      <div className="flex flex-wrap items-center gap-2">
        <ClaimTypeBadge claimType={f.claim_type} />
        {contradicted ? <Badge tone="danger" variant="outline">✕ Contradicted by evidence</Badge> : null}
        <span className="text-xs text-muted">
          {typeof f.confidence === "number" ? `Confidence ${formatConfidence(f.confidence)} (reported by the investigator)` : "No confidence reported"}
        </span>
      </div>
      <p className="text-ink">{f.statement}</p>
      <p className="text-xs text-muted">
        {f.evidence.length} supporting evidence item{f.evidence.length === 1 ? "" : "s"}
        {against.length > 0 ? `, ${against.length} contradicting` : ""}
        {f.uncertainty ? ` · Uncertainty: ${f.uncertainty}` : ""}
      </p>
    </li>
  );
}

export function ActionSummary({ action, primary, showReviewLink = primary }: { action: RecommendedAction; primary: boolean; showReviewLink?: boolean }) {
  const navigate = useNavigateTab();
  return (
    <div className={cx("flex flex-col gap-2 rounded-md border p-3 text-sm", primary ? "border-brand-line bg-brand-tint" : "border-line bg-surface")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h5 className="font-semibold text-ink">{action.title}</h5>
        <Badge tone={action.fromRun ? "info" : "neutral"} variant={action.fromRun ? "soft" : "dashed"}>
          {action.fromRun ? "Proposed by investigation" : "Allowed by runbook · not proposed by an agent"}
        </Badge>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="font-medium text-muted">Target</dt>
        <dd>{shortId(action.targetService)}</dd>
        {action.deployment ? (
          <>
            <dt className="font-medium text-muted">Deployment</dt>
            <dd>
              <CodeBlock inline value={action.deployment} />
            </dd>
          </>
        ) : null}
        <dt className="font-medium text-muted">Risk</dt>
        <dd>{action.risk ?? "Not assessed (no investigation proposed this)"}</dd>
        <dt className="font-medium text-muted">Runbook</dt>
        <dd>{action.runbook ?? "none"}</dd>
        <dt className="font-medium text-muted">Approval</dt>
        <dd>{action.requiredApprovals.length > 0 ? `Requires ${action.requiredApprovals.join(", ")}` : (action.policy ?? "Unknown")}</dd>
      </dl>
      {action.rationale ? <p className="text-ink">{action.rationale}</p> : null}
      {showReviewLink ? (
        <div>
          <button type="button" className="btn-secondary" onClick={() => navigate("review")}>
            Open Human Review
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function FindingsPanel() {
  const { view, run } = useInvestigationSession();
  const f = view.findings;
  const active = isActivePhase(view.phase) && view.phase !== "awaiting_review";

  return (
    <CollapsibleCard
      className="min-w-0"
      title="What we found"
      subtitle={
        f.origin === "run"
          ? "From the investigation run. Confidence is shown only when the investigator reported it."
          : f.origin === "graph"
            ? "No agent has investigated yet. This is stored graph evidence."
            : undefined
      }
    >
      {f.origin === "none" ? (
        <EmptyState
          title={
            active
              ? "Findings will appear when the investigator finishes"
              : view.phase === "none"
                ? "No findings yet"
                : view.phase === "failed"
                  ? "The run failed before producing findings"
                  : "The run produced no findings"
          }
        >
          {active
            ? "The agents are still working. Nothing is concluded until the run completes."
            : view.phase === "none"
              ? "Start an investigation, or open Evidence Graph to browse stored evidence."
              : "A failed or inconclusive run is not evidence of a cause."}
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          {f.warnings.length > 0 ? (
            <div role="alert" className="rounded-md border border-warn-line bg-warn-tint p-2 text-sm text-warn">
              <p className="font-semibold">Integrity warnings</p>
              <ul className="list-disc pl-5">
                {f.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {f.cause ? (
            <section aria-label="Most likely cause" className="rounded-md border border-line-strong bg-surface-muted p-3">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <h4 className="text-sm font-semibold uppercase tracking-wide text-muted">Most likely cause</h4>
                {f.cause.claim === "stored_correlation" ? (
                  <Badge tone="warning" variant="dashed" icon="≈">
                    Stored correlation · not investigated
                  </Badge>
                ) : (
                  <ClaimTypeBadge claimType={f.cause.claim} />
                )}
              </div>
              <p className="text-base text-ink">{f.cause.text}</p>
              <p className="mt-1 text-xs text-muted">
                {f.cause.confidence !== null ? `Confidence ${formatConfidence(f.cause.confidence)} (reported by the investigator)` : "No confidence score was reported."}
                {f.cause.uncertainty ? ` Uncertainty: ${f.cause.uncertainty}` : ""}
              </p>
            </section>
          ) : null}

          {run.investigation && run.investigation.findings.length > 0 ? (
            <section aria-label="Findings">
              <h4 className="mb-1 text-sm font-semibold text-ink">Findings</h4>
              <p className="mb-2 text-xs text-muted">
                {(["confirmed", "correlated", "hypothesis", "observed"] as const)
                  .filter((c) => f.byClaim[c].length > 0)
                  .map((c) => `${f.byClaim[c].length} ${CLAIM_LABELS[c].toLowerCase()}`)
                  .join(" · ")}
                {f.contradicted.length > 0 ? ` · ${f.contradicted.length} contradicted` : ""}
              </p>
              <ul className="flex flex-col gap-2">
                {run.investigation.findings.map((x, i) => (
                  <FindingItem key={i} f={x} contradicted={(x.contradicting_evidence ?? []).length > 0} />
                ))}
              </ul>
            </section>
          ) : null}

          {f.evidence.length > 0 ? (
            <section aria-label="Evidence">
              <h4 className="mb-2 text-sm font-semibold text-ink">Evidence</h4>
              <ul className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                {f.evidence.map((e) => (
                  <EvidenceItem key={e.id} e={e} />
                ))}
              </ul>
            </section>
          ) : null}

          <section aria-label="Recommended next action">
            <h4 className="mb-2 text-sm font-semibold text-ink">Recommended next action</h4>
            {f.primaryAction ? (
              <div className="flex flex-col gap-2">
                <ActionSummary action={f.primaryAction} primary />
                {f.alternatives.length > 0 ? (
                  <details className="text-sm">
                    <summary className="cursor-pointer text-xs font-medium text-brand hover:underline">
                      {f.alternatives.length} other option{f.alternatives.length === 1 ? "" : "s"} allowed by runbooks
                    </summary>
                    <div className="mt-2 flex flex-col gap-2">
                      {f.alternatives.map((a) => (
                        <ActionSummary key={a.key} action={a} primary={false} />
                      ))}
                    </div>
                  </details>
                ) : (
                  <p className="text-xs text-muted">No alternative actions are recorded for this incident.</p>
                )}
              </div>
            ) : (
              <p className="text-sm text-ink">
                {view.phase === "escalated"
                  ? "No action is recommended. The incident was escalated to a human."
                  : "No action is recommended."}
              </p>
            )}
          </section>
        </div>
      )}
    </CollapsibleCard>
  );
}

/** "Current assessment": the lead claim, labelled by what kind of claim it actually is. */
export function AssessmentCard() {
  const { view } = useInvestigationSession();
  const navigate = useNavigateTab();
  const cause = view.findings.cause;
  const hypothesis = cause?.claim === "hypothesis";
  const chip = !cause ? null : hypothesis ? (
    <Badge tone="warning" variant="soft">Hypothesis · not confirmed</Badge>
  ) : cause.claim === "stored_correlation" ? (
    <Badge tone="warning" variant="dashed" icon="≈">Stored correlation · not investigated</Badge>
  ) : (
    <ClaimTypeBadge claimType={cause.claim} />
  );
  const active = isActivePhase(view.phase) && view.phase !== "awaiting_review";
  return (
    <SectionCard className="min-w-0" title="Current assessment" actions={chip} headingLevel={3}>
      {cause ? (
        <div className="flex h-full flex-col gap-2">
          <p className="text-[15px] font-semibold leading-snug text-ink [overflow-wrap:anywhere]">{cause.text}</p>
          <p className="text-sm text-muted">
            {cause.confidence !== null ? `Confidence ${formatConfidence(cause.confidence)} (reported by the investigator). ` : "No confidence score was reported. "}
            {cause.uncertainty ?? ""}
          </p>
          <div className="mt-1">
            <ArrowLink onClick={() => navigate("evidence")}>Examine evidence</ArrowLink>
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted">
          {active
            ? "Nothing is concluded until the investigator finishes."
            : view.phase === "failed"
              ? "The run failed before producing an assessment."
              : "No assessment yet."}
        </p>
      )}
    </SectionCard>
  );
}

/** "Next decision": what a human has to do next, from the run's proposed action and situation. */
export function NextDecisionCard() {
  const { view } = useInvestigationSession();
  const navigate = useNavigateTab();
  const a = view.findings.primaryAction;
  const status = view.situation.key === "awaiting_approval" ? "Human approval is pending." : a?.fromRun ? "An action was proposed." : "No human approval is pending yet.";
  return (
    <SectionCard className="min-w-0" title="Next decision" headingLevel={3}>
      <div className="flex flex-col gap-2">
        <p className="text-sm font-semibold text-ink">{status}</p>
        {a ? (
          <p className="text-xs text-muted">
            {a.title}
            {a.requiredApprovals.length > 0 ? ` requires ${a.requiredApprovals.join(", ")}.` : a.policy ? `. ${a.policy}` : "."}
            {a.fromRun ? "" : " Allowed by runbook, not proposed by an agent."}
          </p>
        ) : (
          <p className="text-xs text-muted">{view.situation.description}</p>
        )}
        <div className="mt-1">
          <ArrowLink onClick={() => navigate("review")}>Review policy</ArrowLink>
        </div>
      </div>
    </SectionCard>
  );
}
