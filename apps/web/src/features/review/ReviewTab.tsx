import { useApi } from "../../api/client";
import type { EvidenceRef, ExplanationPath, FindingOut, InvestigationOut, ProposedActionOut } from "../../api/types";
import {
  Badge,
  Card,
  ClaimTypeBadge,
  CodeBlock,
  EmptyState,
  ErrorBanner,
  ProposalStatusBadge,
  Spinner,
} from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { Code, Field, Fields, UtcTime } from "../activity/ui";
import { pathForProposal } from "../proposals";
import type { TabProps } from "../types";
import {
  candidateArgs,
  deriveCandidates,
  riskFor,
  type CandidateAction,
} from "./candidates";

export default function ReviewTab({ incident, investigation }: TabProps) {
  const paths = incident.explanation_paths ?? [];
  const proposals = investigation?.proposed_actions ?? [];
  const candidates = deriveCandidates(paths);
  const unconfirmed = (investigation?.findings ?? []).filter((f) => f.claim_type !== "confirmed");

  return (
    <div className="flex flex-col gap-4">
      <p className="rounded-md border border-slate-300 bg-slate-50 p-3 text-sm text-slate-700">
        <span className="font-semibold">Raw proposal details.</span>{" "}
        {proposals.length > 0
          ? "These are the exact proposals from the investigation run. Decisions are recorded in the Human Review section above; nothing can be decided here."
          : "Candidate actions below are previews derived from graph evidence. Start an investigation to get a real proposal that can be reviewed."}
      </p>

      {investigation?.status === "awaiting_review" ? (
        <div role="status" className="rounded-md border border-violet-300 bg-violet-50 p-3 text-sm text-violet-900">
          <p className="font-semibold">Pending your approval</p>
          <p>
            Investigation <Code>{investigation.id}</Code> is awaiting human review. Record the decision in the Human Review section above.
          </p>
        </div>
      ) : null}

      {proposals.length > 0 ? (
        <ul className="flex flex-col gap-4" aria-label="Proposals">
          {proposals.map((p) => (
            <li key={p.id}>
              <ProposalCard
                proposal={p}
                path={pathForProposal(paths, p)}
                unconfirmed={unconfirmed}
                investigation={investigation}
              />
            </li>
          ))}
        </ul>
      ) : candidates.length === 0 ? (
        <EmptyState title="No evidence-backed candidate action — nothing to review">
          {(incident.explanation_paths ?? []).length > 0
            ? "Explanation paths exist, but none of their runbooks allows an action type."
            : "The graph has no explanation path for this incident."}
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-4" aria-label="Candidate actions">
          {candidates.map((c) => (
            <li key={c.key}>
              <CandidateCard candidate={c} unconfirmed={unconfirmed} investigation={investigation} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CandidateCard({
  candidate: c,
  unconfirmed,
  investigation,
}: {
  candidate: CandidateAction;
  unconfirmed: FindingOut[];
  investigation: InvestigationOut | null;
}) {
  const path = c.path;
  const target = path.target_service_id;
  return (
    <Card
      title={
        <>
          Candidate action: <Code className="text-sm">{c.actionType}</Code>
        </>
      }
      subtitle="Preview only"
      actions={<ClaimTypeBadge claimType={path.claim_type} />}
    >
      <div className="flex flex-col gap-4">
        <Fields>
          <Field label="Action type">
            <Code>{c.actionType}</Code>
          </Field>
          <Field label="Target service">
            <Code>{target}</Code>
          </Field>
          <Field label="Deployment">
            <Code>{path.deployment.id}</Code> version <Code>{path.deployment.version}</Code>
            {path.deployment.deployed_at ? (
              <span className="text-slate-600">
                {" "}
                deployed <UtcTime value={path.deployment.deployed_at} />
              </span>
            ) : null}
          </Field>
          <Field label="Runbook">
            {c.runbook.title} <Code>{c.runbook.id}</Code> <span className="text-slate-600">v{c.runbook.version}</span>
          </Field>
          <Field label="Risk">{riskFor(c.actionType)}</Field>
          <Field label="Owner team">
            <OwnerTeam serviceId={target} />
          </Field>
          <Field label="Approval policy">
            <ApprovalPolicy path={path} />
          </Field>
        </Fields>

        <div>
          <h4 className="mb-1 text-sm font-semibold text-slate-800">Exact arguments</h4>
          <CodeBlock value={candidateArgs(c)} label={`Exact arguments for ${c.actionType}`} />
          <p className="mt-1 text-xs text-slate-600">
            Preview derived from graph evidence. A real proposal with its SHA-256 spec hash is created server-side when
            an investigation runs.
          </p>
        </div>

        <SupportingEvidence evidence={path.evidence} empty="No evidence attached to this path." />
        <UnconfirmedFindings investigation={investigation} unconfirmed={unconfirmed} />
      </div>
    </Card>
  );
}

/** A real proposal from the investigation run: exact spec and its SHA-256 hash, never executed here. */
function ProposalCard({
  proposal: p,
  path,
  unconfirmed,
  investigation,
}: {
  proposal: ProposedActionOut;
  path: ExplanationPath | undefined;
  unconfirmed: FindingOut[];
  investigation: InvestigationOut | null;
}) {
  const runbook = path?.runbooks.find((r) => r.id === p.runbook_id);
  return (
    <Card
      title={
        <>
          Proposal: <Code className="text-sm">{p.action_type}</Code>
        </>
      }
      subtitle="Proposed by the investigation run · not executed"
      actions={<ProposalStatusBadge status={p.status} />}
    >
      <div className="flex flex-col gap-4">
        <Fields>
          <Field label="Proposal id">
            <Code>{p.id}</Code>
          </Field>
          <Field label="Proposal">
            <Code>{p.proposal_id}</Code> version {p.version}
          </Field>
          <Field label="Status">
            <ProposalStatusBadge status={p.status} />
          </Field>
          <Field label="Mode">
            <Code>{p.mode}</Code>
          </Field>
          <Field label="Action type">
            <Code>{p.action_type}</Code>
          </Field>
          <Field label="Target service">
            <Code>{p.target_service_id}</Code>
          </Field>
          <Field label="Deployment">
            {p.deployment_id ? <Code>{p.deployment_id}</Code> : <span className="text-slate-500">none</span>}
          </Field>
          <Field label="Runbook">
            {runbook ? <>{runbook.title} </> : null}
            <Code>{p.runbook_id}</Code>
            {runbook ? <span className="text-slate-600"> v{runbook.version}</span> : null}
          </Field>
          <Field label="Risk">{p.risk}</Field>
          <Field label="Owner team">
            <OwnerTeam serviceId={p.target_service_id} />
          </Field>
          <Field label="Approval policy">
            {path ? (
              <ApprovalPolicy path={path} />
            ) : (
              <span className="text-slate-600">No explanation path matches this proposal; no governing decision found.</span>
            )}
          </Field>
          <Field label="Rationale">{p.rationale}</Field>
        </Fields>

        <div>
          <h4 className="mb-1 text-sm font-semibold text-slate-800">Exact spec</h4>
          <CodeBlock value={p.spec} label={`Exact spec for ${p.action_type}`} />
          <h4 className="mt-3 mb-1 text-sm font-semibold text-slate-800">Spec hash (SHA-256)</h4>
          <CodeBlock inline value={p.spec_hash} label="Spec hash" className="[overflow-wrap:anywhere]" />
          <p className="mt-1 text-xs text-slate-600">
            An approval binds to this exact spec and hash.
          </p>
        </div>

        <SupportingEvidence evidence={p.evidence} empty="No evidence attached to this proposal." />
        <UnconfirmedFindings investigation={investigation} unconfirmed={unconfirmed} />
      </div>
    </Card>
  );
}

function ApprovalPolicy({ path }: { path: ExplanationPath }) {
  if (path.approval_policy === "no_active_policy_escalate") {
    return (
      <Badge tone="warning" variant="solid">
        No active policy — escalate
      </Badge>
    );
  }
  if ((path.governing_decisions ?? []).length === 0) {
    return <span className="text-slate-500">policy in force, no governing decision recorded</span>;
  }
  return (
    <ul className="space-y-1">
      {path.governing_decisions.map((d) => (
        <li key={d.id}>
          {d.required_approver_role ? (
            <>
              Requires role <Code>{d.required_approver_role}</Code>
            </>
          ) : (
            <span className="text-slate-600">no approver role recorded</span>
          )}{" "}
          — {d.title}{" "}
          {d.documented_in?.map((doc) => (
            <span key={doc.id} className="text-slate-600">
              ({doc.title ?? doc.id})
            </span>
          ))}
        </li>
      ))}
    </ul>
  );
}

function SupportingEvidence({ evidence, empty }: { evidence: EvidenceRef[]; empty: string }) {
  return (
    <div>
      <h4 className="mb-1 text-sm font-semibold text-slate-800">Supporting evidence</h4>
      {evidence.length === 0 ? (
        <p className="text-sm text-slate-500">{empty}</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {evidence.map((ev) => (
            <li key={ev.id} className="flex min-w-0 flex-wrap items-center gap-1.5">
              <Code>{ev.id}</Code>
              <Badge variant="outline">{ev.kind}</Badge>
              <Code className="text-slate-600">{ev.source_ref}</Code>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function UnconfirmedFindings({
  investigation,
  unconfirmed,
}: {
  investigation: InvestigationOut | null;
  unconfirmed: FindingOut[];
}) {
  return (
    <div>
      <h4 className="mb-1 text-sm font-semibold text-slate-800">Contradictory or unconfirmed findings</h4>
      {!investigation ? (
        <p className="text-sm text-slate-500">No investigation started, so there are no findings yet.</p>
      ) : unconfirmed.length === 0 ? (
        <p className="text-sm text-slate-500">None: every finding of this investigation is confirmed.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {unconfirmed.map((f, i) => (
            <li key={`${i}-${f.statement}`} className="flex flex-col gap-1">
              <span>
                <ClaimTypeBadge claimType={f.claim_type} />
              </span>
              <span className="break-words">{f.statement}</span>
              {(f.contradicting_evidence ?? []).length > 0 ? (
                <span className="text-xs text-red-900">
                  Contradicted by{" "}
                  {(f.contradicting_evidence ?? []).map((e, j) => (
                    <span key={e.id}>
                      {j > 0 ? ", " : null}
                      <Code>{e.id}</Code>
                    </span>
                  ))}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function OwnerTeam({ serviceId }: { serviceId: string }) {
  const { client, user } = useApi();
  const ctx = useAsync((signal) => client.getServiceContext(serviceId, {}, signal), [client, serviceId, user]);
  if (ctx.error) return <ErrorBanner error={ctx.error} title="Could not load owner team" onRetry={ctx.reload} />;
  if (!ctx.data) return <Spinner size="sm" label="Loading owner team" />;
  if (ctx.data.owners.length === 0) return <span className="text-slate-500">no owning team recorded</span>;
  return (
    <ul className="space-y-0.5">
      {ctx.data.owners.map((t) => (
        <li key={t.id}>
          {t.name} <Code>{t.id}</Code>
        </li>
      ))}
    </ul>
  );
}
