import { Badge, CodeBlock, Kicker, MetaLine, SectionCard, cx } from "../../components/ui";
import { CredibilityBadge } from "../memory/badges";
import { PROVENANCE_LABELS, type KnowledgeProvenance, type MemoryCardModel, type MemoryGroup } from "./model";

export function KnowledgeBadge({ provenance }: { provenance: KnowledgeProvenance }) {
  const tone = provenance === "official_policy" ? "info" : provenance === "company_document" ? "neutral" : "neutral";
  return (
    <Badge tone={tone} variant={provenance === "text_match" ? "dashed" : "soft"}>
      {PROVENANCE_LABELS[provenance]}
    </Badge>
  );
}

const OUTCOME_LABEL: Record<MemoryCardModel["outcome"], string> = {
  successful: "Recovered",
  failed: "Did not help",
  unknown: "Outcome unknown",
};

function OutcomeGlyph({ outcome }: { outcome: MemoryCardModel["outcome"] }) {
  const style =
    outcome === "successful"
      ? "bg-good-tint text-good ring-good-line"
      : outcome === "failed"
        ? "bg-warn-tint text-warn ring-warn-line"
        : "bg-surface-muted text-muted ring-line";
  return (
    <span aria-hidden="true" className={cx("flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold ring-1", style)}>
      {outcome === "successful" ? "✓" : outcome === "failed" ? "!" : "?"}
    </span>
  );
}

/** One recorded response within a historical incident. Verified status is always taken from the data. */
function ResponseRow({ memory: m }: { memory: MemoryCardModel }) {
  const verified = m.verification.status === "verified";
  return (
    <li
      aria-label={`Memory of ${m.incidentKey ?? m.id}`}
      data-outcome={m.outcome}
      className={cx("flex min-w-0 flex-col gap-2 rounded-lg border p-3.5", m.warning ? "border-warn-line bg-warn-tint" : "border-line bg-surface-sunken")}
    >
      <div className="flex min-w-0 items-start gap-3">
        <OutcomeGlyph outcome={m.outcome} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="min-w-0 text-sm font-bold text-ink">
              {m.actionIds.length > 0 ? m.actionIds.map((id) => <CodeBlock key={id} inline value={id} className="mr-1" />) : "Recorded response"}
            </p>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={m.outcome === "successful" ? "success" : m.outcome === "failed" ? "warning" : "neutral"} variant="soft" icon={m.outcome === "successful" ? "✓" : m.outcome === "failed" ? "!" : "?"}>
                {OUTCOME_LABEL[m.outcome]}
              </Badge>
              <CredibilityBadge verificationStatus="verified" precedent={m.precedent} textOnly={m.textOnly} />
            </div>
          </div>
          <p className="mt-1 text-sm text-muted">{m.summary}</p>
          {m.actionIds.length === 0 ? <p className="mt-1 text-xs text-faint">No structured action record; see the summary.</p> : null}
        </div>
      </div>
      {m.warning ? (
        <p role="note" className="rounded-md bg-bad-tint px-2 py-1 text-xs font-medium text-bad">
          Warning: this approach did not work before. Do not treat it as a recommendation.
        </p>
      ) : null}
      <p className="text-xs text-muted">
        Verified: {verified ? "Yes" : m.verification.status}
        {m.verification.method ? ` · by ${m.verification.method.replace(/_/g, " ")}` : ""}
        {m.verification.by.length > 0 ? ` (${m.verification.by.join(", ")})` : ""}
      </p>
      <details className="text-sm">
        <summary className="cursor-pointer rounded text-xs font-semibold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
          Evidence ({m.evidence.length}) and why it was retrieved
        </summary>
        <div className="mt-2 flex flex-col gap-2">
          {m.evidence.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {m.evidence.map((e) => (
                <li key={e.id} className="rounded border border-line bg-surface p-2 text-xs">
                  <span className="font-medium">{e.kind}</span>: {e.excerpt ?? "no excerpt"}
                  <span className="block text-faint">
                    <CodeBlock inline value={e.source_ref} />
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted">No grounding evidence recorded.</p>
          )}
          <ul className="list-disc pl-4 text-xs text-muted">
            {m.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      </details>
    </li>
  );
}

/** Related historical incident: all verified recorded responses for one earlier incident. */
export function HistoricalIncidentCard({ group }: { group: MemoryGroup }) {
  const verifiers = [...new Set(group.memories.flatMap((m) => m.verification.by))];
  return (
    <SectionCard
      kicker="Related historical incident"
      title={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>{group.incidentKey ?? "Earlier incident"}</span>
          <Badge tone="success" variant="soft" icon="✓">Verified</Badge>
        </span>
      }
      subtitle={`${group.memories.length} recorded ${group.memories.length === 1 ? "response" : "responses"}. These are past observations, not instructions.`}
      footer={<MetaLine items={[verifiers.length > 0 ? `Verified by ${verifiers.join(", ")}` : "Verified by a human or ground truth", "Outcome recorded in incident timeline"]} className="text-xs" />}
    >
      <ul className="flex flex-col gap-3" aria-label="Historical memories">
        {group.memories.map((m) => (
          <ResponseRow key={m.id} memory={m} />
        ))}
      </ul>
    </SectionCard>
  );
}

/** Why the leading memory matched, from the retrieval's own applicability, matchers and recorded outcome. */
export function RetrievalExplanationCard({ memory: m }: { memory: MemoryCardModel }) {
  const items: Array<{ label: string; value: string }> = [
    { label: "How it applies", value: m.applicability },
    { label: "Matched by", value: m.matchedBy.length > 0 ? m.matchedBy.join(", ") : "recorded against this incident" },
    { label: "Recorded outcome", value: m.impact },
  ];
  return (
    <SectionCard kicker="Retrieval explanation" title="Why this memory matched" subtitle="The match is grounded in shared incident context, not just keyword similarity.">
      <ol className="flex flex-col gap-4" aria-label="Reasons this memory matched">
        {items.map((it, i) => (
          <li key={it.label} className="flex gap-3">
            <span aria-hidden="true" className="pt-0.5 font-mono text-xs text-faint">{String(i + 1).padStart(2, "0")}</span>
            <div className="min-w-0">
              <p className="text-sm font-bold text-ink">{it.label}</p>
              <p className="text-sm text-muted">{it.value}</p>
            </div>
          </li>
        ))}
      </ol>
      {m.score !== null ? <Kicker className="mt-4">Relevance {m.score.toFixed(2)}</Kicker> : null}
    </SectionCard>
  );
}
