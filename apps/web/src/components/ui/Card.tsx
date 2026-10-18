import type { ReactNode } from "react";
import { cx } from "./cx";

export interface CardProps {
  title?: ReactNode;
  /** Right-aligned header content (buttons, badges). */
  actions?: ReactNode;
  /** Small text under the title. */
  subtitle?: ReactNode;
  className?: string;
  children?: ReactNode;
  /** Heading level for the title. Default 3. */
  headingLevel?: 2 | 3 | 4;
}

export function Card({ title, actions, subtitle, className, children, headingLevel = 3 }: CardProps) {
  const H = `h${headingLevel}` as "h2" | "h3" | "h4";
  return (
    <section className={cx("card p-5", className)}>
      {title || actions ? (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            {title ? <H className="text-lg font-bold leading-tight text-ink">{title}</H> : null}
            {subtitle ? <p className="mt-1.5 text-sm text-muted">{subtitle}</p> : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}
