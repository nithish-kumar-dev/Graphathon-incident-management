import { useId, useState } from "react";
import { useApi } from "../../api/client";
import type {
  DecisionOut,
  IncidentDetail,
  KnowledgeContext,
  MemoryContext,
  MemoryOut,
  ScoreComponent,
  ScoredChunk,
  ScoredMemory,
  TeamOut,
} from "../../api/types";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { Code, CodeList, Field, Fields, UtcTime, excludedLines } from "../activity/ui";
import type { TabProps } from "../types";
import { ApplicabilityBadge, CredibilityBadge, MatchedBy } from "./badges";

export default function MemoryTab({ incident, user }: TabProps) {
  const { client } = useApi();
  const [includeUnverified, setIncludeUnverified] = useState(false);
  const toggleId = useId();

  const memories = useAsync(
    (signal) => client.getMemories(incident.id, { includeUnverified }, signal),
    [client, incident.id, user, includeUnverified],
  );
  const retrieval = useAsync((signal) => client.getRetrieval(incident.id, signal), [client, incident.id, user]);

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Verified memory"
        subtitle="Lessons from past incidents. Only verified memories can be used as precedent."
        actions={
          <div className="flex items-center gap-2 text-sm">
            <input
              id={toggleId}
              type="checkbox"
              checked={includeUnverified}
              onChange={(e) => setIncludeUnverified(e.target.checked)}
              className="h-4 w-4 rounded border-line-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
            />
            <label htmlFor={toggleId} className="text-ink">
              Include unverified (drafts)
            </label>
          </div>
        }
      >
        <ErrorBanner error={memories.error} title="Could not load memories" onRetry={memories.reload} />
        {memories.loading && !memories.data ? <Spinner label="Loading memories…" /> : null}
        {memories.data ? (
          <MemoryList
            // A draft must never show up while the toggle is off, even if the server sent one.
            memories={memories.data.memories.filter((m) => includeUnverified || m.verification_status === "verified")}
            includeUnverified={includeUnverified}
          />
        ) : null}
      </Card>

      <Card
        title="Ranked retrieval"
        subtitle="Memories the investigator would receive, scored and explained."
        actions={
          <button type="button" className="btn-secondary" onClick={retrieval.reload} disabled={retrieval.loading}>
            Refresh retrieval
          </button>
        }
      >
        <ErrorBanner error={retrieval.error} title="Could not load ranked retrieval" onRetry={retrieval.reload} />
        {retrieval.loading && !retrieval.data ? <Spinner label="Loading ranked retrieval…" /> : null}
        {retrieval.data ? <RankedMemories context={retrieval.data.memory_context} /> : null}
      </Card>

      <section aria-labelledby={`${toggleId}-brain`} className="flex flex-col gap-4">
        <h3 id={`${toggleId}-brain`} className="text-lg font-semibold text-ink">
          Company brain
        </h3>
        <Card
          title="Knowledge chunks"
          headingLevel={4}
          subtitle="Excerpts from authorised documents. Context for the investigator, never a claim or finding."
        >
          {retrieval.error ? (
            <p className="text-sm text-muted">Unavailable: ranked retrieval failed to load (see above).</p>
          ) : null}
          {retrieval.loading && !retrieval.data ? <Spinner label="Loading knowledge chunks…" /> : null}
          {retrieval.data ? <KnowledgeChunks context={retrieval.data.knowledge_context} /> : null}
        </Card>
        <Card title="Owning team and current policy" headingLevel={4}>
          <ServicePolicies incident={incident} />
        </Card>
      </section>
    </div>
  );
}

// ------------------------------------------------------------------ verified memory

function MemoryList({ memories, includeUnverified }: { memories: MemoryOut[]; includeUnverified: boolean }) {
  if (memories.length === 0) {
    return (
      <EmptyState title={includeUnverified ? "No memories for this incident" : "No verified memories for this incident"}>
        {includeUnverified ? null : "Tick “Include unverified (drafts)” to see drafts."}
      </EmptyState>
    );
  }
  return (
    <ul className="flex flex-col gap-3" aria-label="Memories">
      {memories.map((m) => (
        <MemoryItem key={m.id} memory={m} />
      ))}
    </ul>
  );
}

function MemoryItem({ memory: m }: { memory: MemoryOut }) {
  const verified = m.verification_status === "verified";
  return (
    <li
      className={
        verified
          ? "min-w-0 rounded-md border border-line bg-surface p-3"
          : "min-w-0 rounded-md border border-dashed border-amber-400 bg-amber-50/40 p-3"
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <CredibilityBadge verificationStatus={m.verification_status} precedent={m.precedent} />
        <Badge>{m.memory_type}</Badge>
        <Badge tone={verified ? "success" : "warning"} variant="outline">
          {m.verification_status}
        </Badge>
        <Badge variant="outline">outcome: {m.outcome}</Badge>
      </div>
      <p className="mt-2 font-medium break-words text-ink">{m.summary}</p>
      <p className="mt-0.5">
        <Code>{m.id}</Code>
      </p>
      <Fields className="mt-2">
        <Field label="About">
          <span className="font-medium">{m.about_incident_key ?? m.about_incident_id}</span>{" "}
          <span className="text-muted">({m.relation === "same_incident" ? "same incident" : "shared service"})</span>
        </Field>
        <Field label="Shared services">
          <CodeList items={m.shared_service_ids} />
        </Field>
        <Field label="Validated by">
          {m.validated_by.length === 0 ? (
            <span className="text-faint">not validated</span>
          ) : (
            <ul className="space-y-0.5">
              {m.validated_by.map((r) => (
                <li key={r.id}>
                  <span className="font-medium">{r.handle}</span>{" "}
                  {r.roles?.length ? <span className="text-muted">({r.roles.join(", ")})</span> : null}
                </li>
              ))}
            </ul>
          )}
        </Field>
        <Field label="Validated at">
          <UtcTime value={m.validated_at} />
        </Field>
        <Field label="Validation method">
          {m.validation_method ?? <span className="text-faint">not recorded</span>}
        </Field>
        <Field label="Grounded in">
          {m.grounded_in.length === 0 ? (
            <span className="text-faint">no evidence</span>
          ) : (
            <ul className="space-y-1">
              {m.grounded_in.map((ev) => (
                <li key={ev.id} className="flex flex-wrap items-center gap-1.5">
                  <Code>{ev.id}</Code>
                  <Badge variant="outline">{ev.kind}</Badge>
                  <Code className="text-muted">{ev.source_ref}</Code>
                </li>
              ))}
            </ul>
          )}
        </Field>
        <Field label="Derived from actions">
          <CodeList items={m.derived_from_action_ids} />
        </Field>
        <Field label="Provenance">
          <CodeList items={m.provenance_refs} />
        </Field>
      </Fields>
    </li>
  );
}

// ------------------------------------------------------------------ ranked retrieval

function ExcludedNote({ excluded, label }: { excluded: Record<string, number> | undefined; label: string }) {
  const lines = excludedLines(excluded);
  return (
    <p className="text-sm text-muted" aria-label={label}>
      {lines.length === 0 ? "Nothing excluded." : `Excluded by the filter: ${lines.join(", ")}.`}
    </p>
  );
}

function Components({ components, caption }: { components: ScoreComponent[]; caption: string }) {
  if (components.length === 0) return <span className="text-sm text-faint">no score components</span>;
  return (
    <div className="overflow-x-auto">
      <table className="text-left text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="text-muted">
          <tr>
            <th scope="col" className="pr-4 font-medium">
              Component
            </th>
            <th scope="col" className="font-medium">
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {components.map((c) => (
            <tr key={c.name}>
              <th scope="row" className="pr-4 font-mono font-normal text-ink">
                {c.name}
              </th>
              <td className="tabular-nums text-ink">{c.value.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Rationale({ lines }: { lines: string[] }) {
  if (lines.length === 0) return <span className="text-faint">none</span>;
  return (
    <ul className="list-disc space-y-0.5 pl-5">
      {lines.map((r, i) => (
        <li key={`${i}-${r}`} className="break-words">
          {r}
        </li>
      ))}
    </ul>
  );
}

function RankedMemories({ context }: { context: MemoryContext }) {
  return (
    <div className="flex flex-col gap-3">
      {context.items.length === 0 ? (
        <EmptyState title="No verified memories ranked for this incident" />
      ) : (
        <ol className="flex flex-col gap-3" aria-label="Ranked memories">
          {context.items.map((m, i) => (
            <RankedMemoryItem key={m.id} memory={m} rank={i + 1} />
          ))}
        </ol>
      )}
      <ExcludedNote excluded={context.excluded} label="Excluded memories" />
    </div>
  );
}

function RankedMemoryItem({ memory: m, rank }: { memory: ScoredMemory; rank: number }) {
  return (
    <li className="min-w-0 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-muted">#{rank}</span>
        <Badge tone="info" variant="solid" title="Rerank score">
          score {m.score.toFixed(4)}
        </Badge>
        <ApplicabilityBadge applicability={m.applicability} />
        <CredibilityBadge
          verificationStatus={m.verification_status}
          precedent={m.precedent}
          textOnly={m.applicability === "text_similarity_only"}
        />
      </div>
      <p className="mt-2 font-medium break-words text-ink">{m.summary}</p>
      <p className="mt-0.5">
        <Code>{m.id}</Code>
      </p>
      <Fields className="mt-2">
        <Field label="About">{m.about_incident_key ?? m.about_incident_id ?? "—"}</Field>
        <Field label="Outcome">{m.outcome}</Field>
        <Field label="Matched by">
          <MatchedBy steps={m.matched_by} />
        </Field>
        <Field label="Validated by">
          <CodeList items={m.validated_by} empty="not validated" />
        </Field>
        <Field label="Score components">
          <Components components={m.components} caption={`Score components for ${m.id}`} />
        </Field>
        <Field label="Rationale">
          <Rationale lines={m.rationale} />
        </Field>
      </Fields>
    </li>
  );
}

// ------------------------------------------------------------------ knowledge

function KnowledgeChunks({ context }: { context: KnowledgeContext }) {
  return (
    <div className="flex flex-col gap-3">
      {context.items.length === 0 ? (
        <EmptyState title="No knowledge chunks retrieved" />
      ) : (
        <ol className="flex flex-col gap-3" aria-label="Knowledge chunks">
          {context.items.map((c) => (
            <ChunkItem key={c.id} chunk={c} />
          ))}
        </ol>
      )}
      <ExcludedNote excluded={context.excluded} label="Excluded knowledge chunks" />
    </div>
  );
}

function ChunkItem({ chunk: c }: { chunk: ScoredChunk }) {
  return (
    <li className="min-w-0 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral" variant="dashed" icon="ⓘ" title="Knowledge chunks are context for the investigator, never a claim.">
          Context — not a claim
        </Badge>
        <Badge tone="info" variant="solid" title="Rerank score">
          score {c.score.toFixed(4)}
        </Badge>
        <Badge variant="outline">{c.document_classification}</Badge>
      </div>
      <p className="mt-2 font-medium break-words text-ink">{c.document_title}</p>
      <Fields className="mt-2">
        <Field label="Document">
          <Code>{c.document_id}</Code>
        </Field>
        <Field label="Source">
          <Code>{c.source_ref}</Code>
        </Field>
        <Field label="Excerpt">
          <blockquote className="border-l-2 border-line-strong pl-3 whitespace-pre-line text-ink">
            {c.text_excerpt}
          </blockquote>
        </Field>
        <Field label="Graph links">
          {c.graph_links.length === 0 ? (
            <span className="text-faint">no graph link — text match only</span>
          ) : (
            <ul className="space-y-1">
              {c.graph_links.map((g) => (
                <li key={g}>
                  <Code>{g}</Code>
                </li>
              ))}
            </ul>
          )}
        </Field>
        <Field label="Matched by">
          <MatchedBy steps={c.matched_by} />
        </Field>
        <Field label="Score components">
          <Components components={c.components} caption={`Score components for ${c.id}`} />
        </Field>
        <Field label="Rationale">
          <Rationale lines={c.rationale} />
        </Field>
      </Fields>
    </li>
  );
}

// ------------------------------------------------------------------ owners and policy

/** Target services of the explanation paths, else the first affected service. */
function policyServiceIds(incident: IncidentDetail): string[] {
  const targets = [...new Set(incident.explanation_paths.map((p) => p.target_service_id))];
  if (targets.length > 0) return targets;
  const first = incident.affected_service_ids[0] ?? incident.affected_services[0]?.id;
  return first ? [first] : [];
}

function ServicePolicies({ incident }: { incident: IncidentDetail }) {
  const ids = policyServiceIds(incident);
  if (ids.length === 0) return <EmptyState title="No target or affected service to look up" />;
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        {incident.explanation_paths.length > 0
          ? "For each target service of the explanation paths."
          : "No explanation path yet; showing the first affected service."}
      </p>
      {ids.map((id) => (
        <ServicePolicy key={id} serviceId={id} />
      ))}
    </div>
  );
}

function ServicePolicy({ serviceId }: { serviceId: string }) {
  const { client, user } = useApi();
  const ctx = useAsync((signal) => client.getServiceContext(serviceId, {}, signal), [client, serviceId, user]);
  return (
    <div className="min-w-0 rounded-md border border-line p-3">
      <h5 className="font-semibold text-ink">
        {ctx.data?.service.name ?? serviceId} <Code>{serviceId}</Code>
      </h5>
      <ErrorBanner error={ctx.error} title={`Could not load context for ${serviceId}`} onRetry={ctx.reload} className="mt-2" />
      {ctx.loading && !ctx.data ? <Spinner label={`Loading ${serviceId}…`} className="mt-2" /> : null}
      {ctx.data ? (
        <div className="mt-2 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Owners owners={ctx.data.owners} />
          <Decisions decisions={ctx.data.active_decisions} />
        </div>
      ) : null}
    </div>
  );
}

function Owners({ owners }: { owners: TeamOut[] }) {
  return (
    <div className="min-w-0">
      <p className="text-sm font-medium text-muted">Owning team</p>
      {owners.length === 0 ? (
        <p className="text-sm text-faint">No owning team recorded.</p>
      ) : (
        <ul className="mt-1 space-y-2 text-sm">
          {owners.map((t) => (
            <li key={t.id}>
              <span className="font-medium">{t.name}</span> <Code>{t.id}</Code>
              {t.members.length === 0 ? (
                <p className="text-faint">no members</p>
              ) : (
                <ul className="mt-1 list-disc pl-5">
                  {t.members.map((r) => (
                    <li key={r.id}>
                      {r.handle}{" "}
                      <span className="text-muted">
                        {r.roles?.length ? `(${r.roles.join(", ")})` : "(no roles)"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Decisions({ decisions }: { decisions: DecisionOut[] }) {
  return (
    <div className="min-w-0">
      <p className="text-sm font-medium text-muted">Current policy (active decisions)</p>
      {decisions.length === 0 ? (
        <p className="text-sm text-faint">No active decision — escalate before acting.</p>
      ) : (
        <ul className="mt-1 space-y-3 text-sm">
          {decisions.map((d) => (
            <li key={d.id} className="min-w-0">
              <p className="font-medium text-ink">{d.title}</p>
              <p className="break-words text-ink">{d.statement}</p>
              <Fields className="mt-1">
                <Field label="Decision">
                  <Code>{d.id}</Code>
                </Field>
                <Field label="Approver role">
                  {d.required_approver_role ? <Code>{d.required_approver_role}</Code> : <span className="text-faint">none</span>}
                </Field>
                <Field label="Effective from">
                  <UtcTime value={d.effective_from} />
                </Field>
                <Field label="Supersedes">
                  <CodeList items={d.supersedes} />
                </Field>
                <Field label="Documented in">
                  {d.documented_in.length === 0 ? (
                    <span className="text-faint">no document</span>
                  ) : (
                    <ul className="space-y-1">
                      {d.documented_in.map((doc) => (
                        <li key={doc.id} className="break-words">
                          <span className="font-medium">{doc.title ?? doc.id}</span> <Code>{doc.id}</Code>
                          {doc.uri ? (
                            <>
                              {" "}
                              <Code className="text-muted">{doc.uri}</Code>
                            </>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </Field>
              </Fields>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
