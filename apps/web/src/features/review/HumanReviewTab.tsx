import { useId, useState, type ReactNode } from "react";
import { toApiError, useApi, type ApiError } from "../../api/client";
import type { MemoryOut, ProposedActionOut, ReviewDecision, ReviewOut, ReviewResult } from "../../api/types";
import { can, rolesFor } from "../../auth/permissions";
import {
  ArrowLink,
  Badge,
  EmptyState,
  ErrorBanner,
  FactRow,
  Kicker,
  ProposalStatusBadge,
  SectionCard,
} from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { shortId } from "../../lib/time";
import ReviewTab from "./ReviewTab";
import { useNavigateTab } from "../NavContext";
import { useInvestigationSession } from "../investigation/InvestigationSession";
import type { FindingsModel, RecommendedAction } from "../investigation/model";
import { LazyDetails, RelativeTime } from "../investigation/ui";
import { UtcTime } from "../activity/ui";
import { DECISIONS } from "./candidates";

const DECISION_LABELS: Record<ReviewDecision, string> = {
  APPROVE: "Approve",
  REJECT: "Reject",
  REQUEST_REVISION: "Request revision",
  ESCALATE: "Escalate",
};

const DECISION_PAST: Record<ReviewDecision, string> = {
  APPROVE: "Approved",
  REJECT: "Rejected",
  REQUEST_REVISION: "Revision requested",
  ESCALATE: "Escalated",
};

/** Why the signed-in demo user could not decide. The server enforces the same rules; this only explains them early. */
export function userBlockers(user: Parameters<typeof can>[0], requiredRoles: readonly string[]): string[] {
  if (!can(user, "action:review")) return [`${user} lacks the action:review permission.`];
  const held = rolesFor(user);
  return requiredRoles.filter((r) => !held.includes(r)).map((r) => `Requires the ${r} role.`);
}

/** Human-readable reason the action cannot be decided right now, or null when it can. */
export function actionBlocker(proposal: ProposedActionOut | null): string | null {
  if (!proposal) return "Only a proposal from an investigation run can be reviewed. Start an investigation first.";
  if (proposal.status === "pending_review") return null;
  if (proposal.status === "proposed" && proposal.mode === "recommendation_only")
    return "This run was recommendation-only, so its proposal cannot be approved. Start a simulation run to enable approval.";
  return `This action is already ${proposal.status.replace(/_/g, " ")}; no further decision is possible.`;
}

/** Short name of the execution kind, for the header chip. Never claims more than the proposal's own mode. */
function executionKind(action: RecommendedAction): { chip: string; fact: string; tone: "info" | "neutral" } {
  const p = action.proposal;
  if (!p) {
    return {
      chip: "Allowed by runbook · not proposed by an agent",
      fact: "Nothing is scheduled to run. This is a preview of what the runbook permits.",
      tone: "neutral",
    };
  }
  if (p.mode === "simulation") {
    return { chip: "Simulated execution", fact: "Simulation only — nothing real is changed.", tone: "info" };
  }
  return { chip: "Recommendation only", fact: "Recommendation only — this run cannot execute anything.", tone: "neutral" };
}

export default function HumanReviewTab() {
  const { client } = useApi();
  const { incident, run, user, view, reloadAll } = useInvestigationSession();
  const action = view.findings.primaryAction;
  const proposal = action?.proposal ?? null;
  const roles = action?.requiredApprovals ?? [];
  const blockers = userBlockers(user, roles);
  const stateBlocker = action ? actionBlocker(proposal) : null;
  const enabled = !!proposal && stateBlocker === null && blockers.length === 0;

  const commentId = useId();
  const [comment, setComment] = useState("");
  const [pending, setPending] = useState<ReviewDecision | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<ReviewResult | null>(null);

  async function decide(decision: ReviewDecision) {
    if (!proposal || pending) return;
    setPending(decision);
    setError(null);
    try {
      const out = await client.reviewAction(proposal.id, { decision, comment: comment.trim() || null });
      setResult(out);
      setComment("");
      await reloadAll();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setPending(null);
    }
  }

  const decidedStatuses = ["executed_simulated", "rejected", "revision_requested", "approved"];
  const status =
    view.phase === "awaiting_review"
      ? { tone: "warning" as const, text: "Waiting for human approval of the proposed action. Nothing has been executed." }
      : view.phase === "escalated"
        ? {
            tone: "warning" as const,
            text:
              proposal?.status === "escalated"
                ? "A reviewer escalated this action to another person. Nothing has been executed."
                : "Escalated: the agents found no safe recommendation, so a human must decide how to proceed.",
          }
        : view.phase === "none"
          ? { tone: "neutral" as const, text: "No investigation has run, so there is nothing to review. The action below is only what stored runbooks allow." }
          : view.phase === "queued" || view.phase === "running"
            ? { tone: "info" as const, text: "The investigation is still running. A recommendation, if any, will appear here." }
            : view.phase === "failed"
              ? { tone: "danger" as const, text: "The investigation failed. There is nothing to approve." }
              : proposal && decidedStatuses.includes(proposal.status)
                ? { tone: "success" as const, text: "A decision has been recorded for the proposed action." }
                : { tone: "neutral" as const, text: action ? "The run finished without requesting approval." : "The run finished and proposed no action." };

  const badge =
    view.phase === "awaiting_review"
      ? "Awaiting approval"
      : view.phase === "escalated"
        ? "Escalated"
        : proposal && decidedStatuses.includes(proposal.status)
          ? "Decided"
          : "No approval pending";

  const held = rolesFor(user);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-xl font-bold leading-tight text-ink">Human review</h3>
          <p className="mt-1.5 text-sm text-muted">
            A person decides. Agents never execute actions on their own, and approved actions are only ever simulated.
          </p>
        </div>
        <Badge tone={status.tone} variant="soft">
          {badge}
        </Badge>
      </div>
      <p role="status" className="text-sm text-muted">
        {status.text}
      </p>

      {action ? (
        <>
          <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,62fr)_minmax(0,38fr)]">
            <ProposedActionCard action={action} findings={view.findings} />

            <SectionCard
              title="Human decision"
              className="min-w-0"
              actions={
                proposal ? (
                  <ProposalStatusBadge status={proposal.status} />
                ) : (
                  <Badge tone={status.tone} variant="soft">
                    {badge}
                  </Badge>
                )
              }
              bodyClassName="flex flex-col gap-4"
            >
              <dl className="border-y border-line">
                <FactRow term="Reviewer">
                  <span className="[overflow-wrap:anywhere]">{user}</span>
                  <span className="ml-2 font-normal text-muted">
                    {held.length > 0 ? held.join(", ") : "no approver roles"}
                  </span>
                </FactRow>
              </dl>

              <div>
                <label htmlFor={commentId} className="kicker mb-1.5 block">
                  Decision note
                </label>
                <textarea
                  id={commentId}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  maxLength={1000}
                  rows={3}
                  disabled={!enabled}
                  placeholder="Add a reason or request more evidence..."
                  className="block w-full rounded-md border border-line bg-surface p-2.5 text-sm text-ink placeholder:text-faint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-faint"
                />
                <p className="mt-1.5 text-xs text-muted">Optional. Recorded with the decision.</p>
              </div>

              <div className="flex flex-wrap gap-2" role="group" aria-label="Review decision">
                {DECISIONS.map((d) => (
                  <button
                    key={d}
                    type="button"
                    className={d === "APPROVE" ? "btn-primary" : "btn-secondary"}
                    disabled={!enabled || pending !== null}
                    onClick={() => void decide(d)}
                  >
                    {pending === d ? "Sending…" : DECISION_LABELS[d]}
                  </button>
                ))}
              </div>

              {!enabled && (stateBlocker || blockers.length > 0) ? (
                <section
                  aria-label="Why this decision is blocked"
                  className="rounded-md border border-warn-line bg-warn-tint p-3.5"
                >
                  <Kicker>
                    <span aria-hidden="true" className="mr-1.5">
                      ⊘
                    </span>
                    Why these controls are blocked right now
                  </Kicker>
                  <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[13px] text-ink">
                    {stateBlocker ? <li>{stateBlocker}</li> : null}
                    {blockers.map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <ErrorBanner error={error} title="The decision was not recorded" />
              {result ? (
                <p role="status" className="rounded-md border border-good-line bg-good-tint p-2.5 text-[13px] text-good">
                  {DECISION_PAST[result.review.decision]}. {result.message}
                </p>
              ) : null}

              {proposal ? <DecisionRecord proposal={proposal} /> : null}
              {proposal?.execution ? <OutcomeVerification proposal={proposal} /> : null}
            </SectionCard>
          </div>

          <EvidenceUsedCard action={action} />
        </>
      ) : (
        <EmptyState title={view.phase === "escalated" ? "No recommended action" : "No action to review"}>
          {view.phase === "escalated" ? "The incident was escalated. Review the findings and decide manually." : "When an investigation proposes an action it appears here for approval."}
        </EmptyState>
      )}

      <LazyDetails summary="Raw proposal details (exact arguments, spec hash, role checks)" className="card p-5">
        <ReviewTab incident={incident} investigation={run.investigation} user={user} reloadIncident={() => void reloadAll()} />
      </LazyDetails>
    </div>
  );
}

/** The mockup's left card: what is proposed, where it came from, and why it is only a recommendation. */
function ProposedActionCard({ action, findings }: { action: RecommendedAction; findings: FindingsModel }) {
  const navigate = useNavigateTab();
  const kind = executionKind(action);
  const cause = findings.cause;
  const evidenceCount = findings.evidence.length;

  const reasons: string[] = [];
  if (action.rationale) reasons.push(action.rationale);
  else if (cause) reasons.push(cause.text);
  if (evidenceCount > 0) {
    reasons.push(
      `${evidenceCount} evidence item${evidenceCount === 1 ? "" : "s"} attached.` +
        (cause && cause.claim !== "confirmed"
          ? " The cause is not confirmed; check the evidence before approving."
          : ""),
    );
  }
  reasons.push("These are supporting signals, not proof that this action will resolve the incident.");

  return (
    <SectionCard
      title="Proposed action"
      className="min-w-0"
      actions={
        <Badge tone={kind.tone} variant={action.proposal ? "soft" : "dashed"}>
          {kind.chip}
        </Badge>
      }
      bodyClassName="flex flex-col gap-4"
    >
      <div>
        <p className="text-lg font-bold leading-tight text-ink [overflow-wrap:anywhere]">{action.title}</p>
        <p className="mt-1.5 text-sm text-muted">
          {action.runbook ? "Based on the retrieved runbook." : "No runbook was recorded for this action."} Requires
          authorized approval; nothing is executed until a person approves it.
        </p>
      </div>

      <dl className="divide-y divide-line border-y border-line">
        <FactRow term="Service">
          <span className="[overflow-wrap:anywhere]">{action.targetService}</span>
        </FactRow>
        <FactRow term="Runbook">
          <span className="[overflow-wrap:anywhere]">{action.runbook ?? "none recorded"}</span>
        </FactRow>
        <FactRow term="Execution">{kind.fact}</FactRow>
        <FactRow term="Required role">
          {action.requiredApprovals.length > 0 ? (
            <span className="[overflow-wrap:anywhere]">{action.requiredApprovals.join(", ")}</span>
          ) : (
            <span className="font-normal text-muted">
              {action.policy ?? "No approver is defined; this would escalate."}
            </span>
          )}
        </FactRow>
        {action.risk ? <FactRow term="Risk">{action.risk}</FactRow> : null}
      </dl>

      <div>
        <h4 className="text-sm font-bold text-ink">Why this action?</h4>
        <ul className="mt-1.5 space-y-1 text-sm text-muted">
          {reasons.map((r) => (
            <li key={r} className="[overflow-wrap:anywhere]">
              {r}
            </li>
          ))}
        </ul>
        <div className="mt-3">
          <ArrowLink onClick={() => navigate("evidence")}>View evidence path</ArrowLink>
        </div>
      </div>
    </SectionCard>
  );
}

/** The mockup's full-width footer card. Each column is omitted when the graph recorded nothing for it. */
function EvidenceUsedCard({ action }: { action: RecommendedAction }) {
  const path = action.path;
  const deployment = path?.deployment ?? null;
  const dependencies = (path?.hops ?? [])
    .filter((h) => h.rel === "DEPENDS_ON")
    .map((h) => `${shortId(h.from_id)} → ${shortId(h.to_id)}`);
  const decision = path?.governing_decisions?.[0] ?? null;
  const policyText = decision
    ? `${decision.title}${decision.required_approver_role ? ` · requires ${decision.required_approver_role}` : ""}`
    : action.policy;

  const columns: Array<{ label: string; value: ReactNode }> = [];
  if (deployment) {
    columns.push({
      label: "Deployment evidence",
      value: (
        <>
          {deployment.version} deployed <UtcTime value={deployment.deployed_at} />
        </>
      ),
    });
  }
  if (dependencies.length > 0) {
    columns.push({ label: "Graph connection", value: [...new Set(dependencies)].join(", ") + " dependency" });
  }
  if (policyText) columns.push({ label: "Company policy", value: policyText });
  if (columns.length === 0) return null;

  return (
    <SectionCard title="Evidence used for review" className="min-w-0">
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3 sm:gap-0 sm:divide-x sm:divide-line">
        {columns.map((c) => (
          <div key={c.label} className="min-w-0 sm:px-5 sm:first:pl-0 sm:last:pr-0">
            <dt className="text-sm font-bold text-ink">{c.label}</dt>
            <dd className="mt-1 text-sm text-muted [overflow-wrap:anywhere]">{c.value}</dd>
          </div>
        ))}
      </dl>
    </SectionCard>
  );
}

function ReviewLine({ review }: { review: ReviewOut }) {
  return (
    <li className="rounded-md border border-line p-2.5 text-sm">
      <p className="font-semibold text-ink">
        {DECISION_PAST[review.decision]} by {review.approver_handle ?? review.approver_id}{" "}
        <span className="font-normal text-muted">
          <RelativeTime iso={review.decided_at} />
        </span>
      </p>
      {review.comment ? <p className="text-ink">“{review.comment}”</p> : null}
      <p className="text-xs text-muted [overflow-wrap:anywhere]">
        Bound to action version {review.action_version}, spec hash {review.spec_hash.slice(0, 12)}…
        {review.expires_at ? (
          <>
            {" "}
            · expires <RelativeTime iso={review.expires_at} />
          </>
        ) : null}
      </p>
    </li>
  );
}

function DecisionRecord({ proposal }: { proposal: ProposedActionOut }) {
  const reviews = proposal.reviews ?? [];
  const exec = proposal.execution;
  if (reviews.length === 0 && !exec) return null;
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3.5">
      {reviews.length > 0 ? (
        <>
          <h4 className="text-sm font-bold text-ink">Decision record</h4>
          <ul className="flex flex-col gap-2" aria-label="Decision record">
            {reviews.map((r) => (
              <ReviewLine key={r.id} review={r} />
            ))}
          </ul>
        </>
      ) : null}
      {exec ? (
        <section aria-label="Simulated execution" className="rounded-md border border-brand-line bg-brand-tint p-2.5 text-brand">
          <h4 className="text-sm font-bold">Simulated execution: {exec.result}</h4>
          <p className="text-xs">
            Nothing real was changed.
            {exec.ticket ? <> Ticket {exec.ticket}.</> : null} Executed <RelativeTime iso={exec.executed_at} />.
          </p>
          {exec.note ? <p className="text-xs">{exec.note}</p> : null}
        </section>
      ) : null}
    </div>
  );
}

/** After a simulated execution a draft memory exists. It informs later runs only once a person verifies the outcome. */
function OutcomeVerification({ proposal }: { proposal: ProposedActionOut }) {
  const { client, user } = useApi();
  const { incident, reloadMemories } = useInvestigationSession();
  const drafts = useAsync(
    (signal) => client.getMemories(incident.id, { includeUnverified: true }, signal),
    [client, incident.id, user, proposal.status],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const draft: MemoryOut | undefined = drafts.data?.memories?.find(
    (m) => m.verification_status === "draft" && m.derived_from_action_ids.includes(proposal.id),
  );
  const allowed = can(user, "action:review");

  async function act(kind: "successful" | "failed" | "reject") {
    if (!draft || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (kind === "reject") await client.rejectMemory(draft.id);
      else await client.validateMemory(draft.id, kind);
      setDone(kind === "reject" ? "The draft memory was discarded." : `Outcome recorded as ${kind}. It now informs future investigations.`);
      drafts.reload();
      reloadMemories();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (drafts.error) return <ErrorBanner error={drafts.error} title="Could not load the draft memory" onRetry={drafts.reload} />;
  if (!draft && !done) return null;
  return (
    <section aria-label="Verify the outcome" className="flex flex-col gap-2 rounded-md border border-line bg-surface-muted p-3">
      <h4 className="text-sm font-bold text-ink">Verify the outcome</h4>
      {draft ? (
        <>
          <p className="text-xs text-muted">
            A draft memory was written from this simulated run. It is not used by future investigations until a person verifies what actually happened.
          </p>
          <p className="text-xs text-ink [overflow-wrap:anywhere]">{draft.summary}</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary" disabled={!allowed || busy} onClick={() => void act("successful")}>
              Mark successful
            </button>
            <button type="button" className="btn-secondary" disabled={!allowed || busy} onClick={() => void act("failed")}>
              Mark failed
            </button>
            <button type="button" className="btn-secondary" disabled={!allowed || busy} onClick={() => void act("reject")}>
              Discard memory
            </button>
          </div>
          {!allowed ? <p className="text-xs text-muted">{user} lacks the action:review permission.</p> : null}
        </>
      ) : null}
      <ErrorBanner error={error} title="Could not update the memory" />
      {done ? (
        <p role="status" className="text-xs text-good">
          {done}
        </p>
      ) : null}
    </section>
  );
}
