import { useState, type ReactNode } from "react";
import { cx } from "../../components/ui";
import { relativeTime } from "../../lib/time";
import { useInvestigationSession } from "./InvestigationSession";
import { STAGE_STATUS_LABELS, type AgentStatus, type StageStatus } from "./model";

export type VisualStatus = StageStatus | AgentStatus;

interface Visual {
  glyph: string;
  label: string;
  /** Pill classes: colour is never the only signal; the glyph and the label carry the meaning too. */
  pill: string;
  dot: string;
  pulse?: boolean;
}

export const VISUAL: Record<VisualStatus, Visual> = {
  pending: { glyph: "○", label: "Not started", pill: "bg-surface-muted text-muted ring-line", dot: "border-line-strong bg-surface text-faint" },
  running: { glyph: "●", label: "In progress", pill: "bg-brand-tint text-brand ring-brand-line", dot: "border-brand bg-brand-tint text-brand", pulse: true },
  completed: { glyph: "✓", label: "Complete", pill: "bg-good-tint text-good ring-good-line", dot: "border-good bg-good-tint text-good" },
  failed: { glyph: "✕", label: "Failed", pill: "bg-bad-tint text-bad ring-bad-line", dot: "border-bad bg-bad-tint text-bad" },
  waiting: { glyph: "‖", label: STAGE_STATUS_LABELS.waiting, pill: "bg-warn-tint text-warn ring-warn-line", dot: "border-warn bg-warn-tint text-warn" },
  skipped: { glyph: "–", label: "Skipped", pill: "bg-surface-muted text-muted ring-line", dot: "border-line-strong border-dashed bg-surface-muted text-faint" },
  unavailable: { glyph: "⊘", label: STAGE_STATUS_LABELS.unavailable, pill: "bg-surface-muted text-muted ring-line", dot: "border-line-strong border-dashed bg-surface-muted text-faint" },
  not_recorded: { glyph: "?", label: "Not recorded", pill: "bg-surface-muted text-muted ring-line", dot: "border-line-strong border-dashed bg-surface-muted text-faint" },
};

const AGENT_LABELS: Partial<Record<VisualStatus, string>> = {
  pending: "Waiting",
  completed: "Completed",
};

export function StatusPill({ status, agent = false }: { status: VisualStatus; agent?: boolean }) {
  const v = VISUAL[status];
  const label = (agent ? AGENT_LABELS[status] : undefined) ?? v.label;
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset", v.pill)}>
      <span aria-hidden="true" className={v.pulse ? "animate-pulse motion-reduce:animate-none" : undefined}>
        {v.glyph}
      </span>
      {label}
    </span>
  );
}

/** Relative time with the exact UTC instant as a tooltip. Ticks with the shared session clock. */
export function RelativeTime({ iso, className }: { iso: string | null | undefined; className?: string }) {
  const { now } = useInvestigationSession();
  if (!iso) return <span className={className}>unknown time</span>;
  return (
    <time dateTime={iso} title={new Date(iso).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC")} className={className}>
      {relativeTime(iso, now)}
    </time>
  );
}

export function SectionTitle({ children, hint, id }: { children: ReactNode; hint?: ReactNode; id?: string }) {
  return (
    <div className="mb-3">
      <h3 id={id} className="text-lg font-bold leading-tight text-ink">
        {children}
      </h3>
      {hint ? <p className="mt-1.5 text-sm text-muted">{hint}</p> : null}
    </div>
  );
}

/**
 * A card-shaped disclosure built on the same `<details>` pattern as `LazyDetails`: the body mounts
 * only once it has been opened, and `<summary>` gives keyboard operation and expanded/collapsed
 * semantics for free. Closed by default unless `defaultOpen` says otherwise.
 */
export function CollapsibleCard({
  title,
  subtitle,
  children,
  className,
  defaultOpen = false,
  headingLevel = 3,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  className?: string;
  defaultOpen?: boolean;
  headingLevel?: 2 | 3 | 4;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [mounted, setMounted] = useState(defaultOpen);
  const H = `h${headingLevel}` as "h2" | "h3" | "h4";
  return (
    <details
      className={cx("card group", className)}
      open={open}
      onToggle={(e) => {
        const isOpen = (e.currentTarget as HTMLDetailsElement).open;
        setOpen(isOpen);
        if (isOpen) setMounted(true);
      }}
    >
      <summary className="flex cursor-pointer list-none flex-wrap items-start justify-between gap-3 rounded-lg p-5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand [&::-webkit-details-marker]:hidden">
        <div className="min-w-0">
          <H className="text-lg font-bold leading-tight text-ink">{title}</H>
          {subtitle ? <p className="mt-1.5 text-sm text-muted">{subtitle}</p> : null}
        </div>
        <span
          aria-hidden="true"
          className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full bg-surface-muted px-2.5 py-1 text-[11px] font-semibold text-muted ring-1 ring-inset ring-line group-hover:text-ink"
        >
          {open ? "Hide" : "Show"}
          <span className={cx("transition-transform motion-reduce:transition-none", open ? "rotate-180" : "")}>▾</span>
        </span>
      </summary>
      <div className="min-w-0 border-t border-line px-5 pb-5 pt-4">{mounted ? children : null}</div>
    </details>
  );
}

/** A <details> whose body mounts only once opened, so collapsed raw views make no requests. */
export function LazyDetails({ summary, children, className }: { summary: ReactNode; children: ReactNode; className?: string }) {
  const [opened, setOpened] = useState(false);
  return (
    <details className={className} onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && setOpened(true)}>
      <summary className="cursor-pointer text-sm font-medium text-slate-800">{summary}</summary>
      <div className="mt-3">{opened ? children : null}</div>
    </details>
  );
}
