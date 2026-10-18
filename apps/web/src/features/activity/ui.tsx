/**
 * Small presentational helpers shared by the activity, memory and review tabs.
 * Ids and synthetic:// source refs are always rendered as code text, never as links.
 */
import type { ReactNode } from "react";
import { ID_WRAP, cx, withWordBreaks } from "../../components/ui";

/** "2026-10-17 14:04:00 UTC", or the raw value when it does not parse. */
export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

export function UtcTime({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-slate-500">—</span>;
  return (
    <time dateTime={value} className="whitespace-nowrap">
      {formatUtc(value)}
    </time>
  );
}

/** Inline monospace id / ref. Wraps at `.` `:` `/` `_` `-` so long refs never cause horizontal page scroll. */
export function Code({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <code className={cx("rounded bg-slate-100 px-1 py-0.5 font-mono text-xs text-slate-800", ID_WRAP, className)}>
      {typeof children === "string" ? withWordBreaks(children) : children}
    </code>
  );
}

/** A two-column definition list that collapses to one column on narrow screens. */
export function Fields({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <dl className={cx("grid grid-cols-1 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[minmax(8rem,max-content)_1fr]", className)}>
      {children}
    </dl>
  );
}

export function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <>
      <dt className="font-medium text-slate-600">{label}</dt>
      <dd className="min-w-0 break-words text-slate-900">{children}</dd>
    </>
  );
}

/** A list of ids as code, or a muted placeholder when empty. */
export function CodeList({ items, empty = "none" }: { items: readonly string[] | null | undefined; empty?: string }) {
  if (!items || items.length === 0) return <span className="text-slate-500">{empty}</span>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <li key={item}>
          <Code>{item}</Code>
        </li>
      ))}
    </ul>
  );
}

/** Human text for an `excluded` reason -> count map, e.g. ["1 draft excluded"]. */
export function excludedLines(excluded: Record<string, number> | null | undefined): string[] {
  return Object.entries(excluded ?? {})
    .filter(([, n]) => n > 0)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([reason, n]) => `${n} ${reason.replace(/_/g, " ")} excluded`);
}
