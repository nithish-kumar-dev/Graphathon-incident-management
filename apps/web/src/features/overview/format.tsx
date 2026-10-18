import type { ReactNode } from "react";
import { Badge, cx } from "../../components/ui";

/** "2026-10-17 14:05 UTC" (seconds only when non-zero). Unparseable input is returned unchanged. */
export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const s = d.toISOString();
  const seconds = s.slice(17, 19);
  return `${s.slice(0, 10)} ${s.slice(11, 16)}${seconds === "00" ? "" : `:${seconds}`} UTC`;
}

/** A UTC timestamp in a <time> element, or an em dash when missing. */
export function UtcTime({ iso, className }: { iso: string | null | undefined; className?: string }) {
  if (!iso) return <span className={className}>—</span>;
  return (
    <time dateTime={iso} className={cx("whitespace-nowrap", className)}>
      {formatUtc(iso)}
    </time>
  );
}

/** Graph node label rendered as a small text tag (e.g. "Service"). Not an id, so never monospace. */
export function NodeLabel({ children }: { children: ReactNode }) {
  return (
    <span className="rounded border border-slate-300 bg-white px-1 py-px text-[11px] font-medium uppercase tracking-wide text-slate-600">
      {children}
    </span>
  );
}

/** A stored relationship arrow, e.g. "—DEPENDS_ON→". */
export function RelArrow({ rel }: { rel: string }) {
  return (
    <span className="whitespace-nowrap text-xs font-semibold text-slate-700">
      —<span className="font-mono">{rel}</span>→
    </span>
  );
}

/** Wrap a table so it scrolls horizontally inside its container instead of widening the page. */
export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className="max-w-full overflow-x-auto rounded-md border border-slate-200">
      {children}
    </div>
  );
}

export const TH = "border-b border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-600";
export const TD = "border-b border-slate-100 px-3 py-2 align-top text-sm text-slate-800";
/** Cell holding an id or fingerprint: wide enough that it wraps at `.`/`:`/`_` into a few readable lines. */
export const TD_ID = `${TD} min-w-40`;
/** Cell holding a synthetic:// source ref. */
export const TD_REF = `${TD} min-w-52`;

export const HYPOTHESIS_LABEL = "Hypothesis — correlated, not confirmed";
export const HYPOTHESIS_HELP = "A graph correlation. Evidence for a hypothesis, not a confirmed cause.";

/** The one label for a graph explanation path: a correlation, never a confirmed cause. Styled like the correlated claim badge. */
export function HypothesisNote() {
  return (
    <Badge tone="warning" variant="dashed" icon="≈" title={HYPOTHESIS_HELP}>
      {HYPOTHESIS_LABEL}
    </Badge>
  );
}
