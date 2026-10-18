import { useState } from "react";
import { Badge, ArrowLink, CodeBlock, EmptyState, ErrorBanner, FactRow, Kicker, SectionCard, Spinner, cx } from "../../components/ui";
import MemoryTab from "../memory/MemoryTab";
import { useInvestigationSession } from "../investigation/InvestigationSession";
import { LazyDetails } from "../investigation/ui";
import { HistoricalIncidentCard, KnowledgeBadge, RetrievalExplanationCard } from "./cards";
import { groupMemories, knowledgeEntries, memoryCards, type KnowledgeEntry } from "./model";
import { actionTitle } from "../investigation/model";

export default function KnowledgeMemoryTab() {
  const { incident, bundle, bundleError, bundleLoading, memories, memoriesError, run, user, reloadIncident, view } = useInvestigationSession();
  const proposal = run.investigation?.proposed_actions?.[0] ?? null;
  const actionName = proposal ? actionTitle(proposal.action_type) : (view.findings.primaryAction?.title ?? null);

  const cards = memoryCards(bundle, memories, actionName);
  const groups = groupMemories(cards);
  const entries = knowledgeEntries(bundle);
  const excludedMem = Object.entries(bundle?.memory_context.excluded ?? {}).filter(([, n]) => n > 0);
  const excludedKnow = Object.entries(bundle?.knowledge_context.excluded ?? {}).filter(([, n]) => n > 0);

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const selected = entries.find((e) => e.key === selectedKey) ?? entries[0] ?? null;
  const loadingNothing = bundleLoading && !bundle;

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <ErrorBanner error={bundleError} title="Could not load retrieval context" />

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-xl font-bold text-ink">Knowledge &amp; memory</h2>
          <p className="mt-1 text-sm text-muted">Retrieved context is useful only when its source, outcome and authority are clear.</p>
        </div>
        <Badge tone="neutral" variant="outline" title="Drafts and unverified memories are never shown as evidence.">
          Verified memories only
        </Badge>
      </header>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,13fr)_minmax(0,7fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <ErrorBanner error={memoriesError} title="Could not load stored memories" />
          {loadingNothing && !memories ? <Spinner label="Loading memories…" /> : null}
          {groups.length === 0 && !loadingNothing ? (
            <SectionCard kicker="Related historical incident" title="Historical memory">
              <EmptyState title="No verified memories apply to this incident">Memories become available once a human has verified the outcome of an earlier incident.</EmptyState>
            </SectionCard>
          ) : (
            groups.map((g) => <HistoricalIncidentCard key={g.key} group={g} />)
          )}
          {excludedMem.length > 0 ? (
            <p className="text-xs text-muted">Not shown, because they cannot be evidence: {excludedMem.map(([k, n]) => `${n} ${k}`).join(", ")}.</p>
          ) : null}
        </div>

        {cards.length > 0 ? <RetrievalExplanationCard memory={cards[0]!} /> : <div className="hidden lg:block" />}

        <SectionCard title="Company knowledge" subtitle="Authoritative policies are separated from supporting documents. Matched documents are context, never a conclusion.">
          {entries.length === 0 ? (
            loadingNothing ? (
              <Spinner label="Loading documents…" />
            ) : (
              <EmptyState title="No company documents matched" />
            )
          ) : (
            <ul className="flex flex-col gap-3" aria-label="Company knowledge">
              {entries.map((e) => (
                <DocRow key={e.key} entry={e} selected={selected?.key === e.key} onSelect={() => setSelectedKey(e.key)} />
              ))}
            </ul>
          )}
          {excludedKnow.length > 0 ? <p className="mt-3 text-xs text-muted">Not shown: {excludedKnow.map(([k, n]) => `${n} ${k}`).join(", ")}.</p> : null}
        </SectionCard>

        {selected ? <SourcePreview entry={selected} /> : <div className="hidden lg:block" />}
      </div>

      <LazyDetails summary="Raw technical records (ranked retrieval, scoring, ids)" className="rounded-lg border border-line bg-surface p-3">
        <MemoryTab incident={incident} investigation={run.investigation} user={user} reloadIncident={reloadIncident} />
      </LazyDetails>
    </div>
  );
}

function DocRow({ entry: e, selected, onSelect }: { entry: KnowledgeEntry; selected: boolean; onSelect: () => void }) {
  return (
    <li className="min-w-0">
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={cx(
          "flex w-full min-w-0 flex-col gap-1 rounded-lg border p-3.5 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand",
          e.official ? "border-brand-line bg-brand-tint" : "border-line bg-surface hover:bg-surface-muted",
          selected && !e.official ? "ring-2 ring-brand-line" : "",
        )}
      >
        <span className="flex flex-wrap items-start justify-between gap-2">
          <Kicker>{e.kicker}</Kicker>
          <span className="flex flex-wrap items-center gap-1.5">
            {e.official ? <Badge tone="info" variant="soft">Official policy</Badge> : null}
            {e.provenance && !e.official ? <KnowledgeBadge provenance={e.provenance} /> : null}
            <Badge tone={e.official ? "success" : e.status === "Context" ? "neutral" : "info"} variant="soft">
              {e.status.charAt(0).toUpperCase() + e.status.slice(1)}
            </Badge>
          </span>
        </span>
        <span className="text-sm font-bold text-ink">{e.title}</span>
        <span className="text-xs text-muted">{e.typeLabel}</span>
      </button>
    </li>
  );
}

function SourcePreview({ entry: e }: { entry: KnowledgeEntry }) {
  return (
    <SectionCard
      kicker="Source preview"
      title={<span className="break-words">{e.previewId}</span>}
      subtitle={e.title}
      actions={e.official ? <Badge tone="info" variant="soft">Official policy</Badge> : e.provenance ? <KnowledgeBadge provenance={e.provenance} /> : null}
      footer={<p className="text-xs text-faint">Context source · not an AI finding</p>}
    >
      {e.previewText ? <p className="line-clamp-6 whitespace-pre-line text-sm text-muted">{e.previewText}</p> : null}
      <dl className="mt-3 divide-y divide-line border-t border-line">
        {e.statusLine ? <FactRow term="Status">{e.statusLine}</FactRow> : null}
      </dl>
      {e.uri ? (
        <div className="mt-3 text-sm">
          {/^https?:\/\//.test(e.uri) ? <ArrowLink href={e.uri}>View original document</ArrowLink> : <CodeBlock inline value={e.uri} />}
        </div>
      ) : null}
    </SectionCard>
  );
}
