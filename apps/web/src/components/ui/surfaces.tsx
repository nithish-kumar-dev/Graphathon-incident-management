import type { ReactNode } from "react";
import { cx } from "./cx";

export function Kicker({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cx("kicker", className)}>{children}</p>;
}

export interface SectionCardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  /** Small uppercase label above the title. */
  kicker?: ReactNode;
  /** Right-aligned header content (chips, toggles, links). */
  actions?: ReactNode;
  /** Pinned to the bottom of the card, above the padding, with a divider. */
  footer?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children?: ReactNode;
  headingLevel?: 2 | 3 | 4;
}

/** The card used throughout the mockups: kicker, large title, subtitle, body, optional footer. */
export function SectionCard({
  title,
  subtitle,
  kicker,
  actions,
  footer,
  className,
  bodyClassName,
  children,
  headingLevel = 3,
}: SectionCardProps) {
  const H = `h${headingLevel}` as "h2" | "h3" | "h4";
  return (
    <section className={cx("card flex flex-col p-5", className)}>
      {kicker || title || actions ? (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {kicker ? <Kicker className="mb-1.5">{kicker}</Kicker> : null}
            {title ? <H className="text-lg font-bold leading-tight text-ink">{title}</H> : null}
            {subtitle ? <p className="mt-1.5 text-sm text-muted">{subtitle}</p> : null}
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cx("min-w-0 flex-1", bodyClassName)}>{children}</div>
      {footer ? <div className="mt-4 border-t border-line pt-3.5">{footer}</div> : null}
    </section>
  );
}

/** "View workstream →" affordance. Renders a button when given onClick, a link when given href. */
export function ArrowLink({
  children,
  onClick,
  href,
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  href?: string;
  className?: string;
}) {
  const style = cx(
    "inline-flex items-center gap-1.5 text-sm font-bold text-brand hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand",
    className,
  );
  const body = (
    <>
      {children}
      <span aria-hidden="true">→</span>
    </>
  );
  if (href) {
    return (
      <a href={href} className={style}>
        {body}
      </a>
    );
  }
  return (
    <button type="button" onClick={onClick} className={style}>
      {body}
    </button>
  );
}

/** Label/value row used in the proposed-action and run-snapshot panels. */
export function FactRow({ term, children, className }: { term: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cx("flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-2.5", className)}>
      <dt className="text-sm text-muted">{term}</dt>
      <dd className="min-w-0 text-sm font-bold text-ink">{children}</dd>
    </div>
  );
}

/** Dot-separated metadata line ("Checkout service · 2 alerts · Owner: Storefront on-call"). */
export function MetaLine({ items, className }: { items: ReactNode[]; className?: string }) {
  const shown = items.filter(Boolean);
  return (
    <p className={cx("flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted", className)}>
      {shown.map((item, i) => (
        <span key={i} className="inline-flex items-center gap-2">
          {i > 0 ? <span aria-hidden="true" className="text-line-strong">·</span> : null}
          <span>{item}</span>
        </span>
      ))}
    </p>
  );
}
