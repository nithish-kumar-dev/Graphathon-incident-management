import type { ReactNode } from "react";
import { cx } from "./cx";

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger" | "accent";
export type BadgeVariant = "soft" | "solid" | "outline" | "dashed";

export interface BadgeProps {
  tone?: BadgeTone;
  variant?: BadgeVariant;
  /** Native tooltip; also used as the accessible description. */
  title?: string;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
}

const SOFT: Record<BadgeTone, string> = {
  neutral: "bg-surface-muted text-muted ring-line",
  info: "bg-brand-tint text-brand ring-brand-line",
  success: "bg-good-tint text-good ring-good-line",
  warning: "bg-warn-tint text-warn ring-warn-line",
  danger: "bg-bad-tint text-bad ring-bad-line",
  accent: "bg-brand-tint text-brand-deep ring-brand-line",
};

const SOLID: Record<BadgeTone, string> = {
  neutral: "bg-muted text-white ring-muted",
  info: "bg-brand text-white ring-brand",
  success: "bg-good text-white ring-good",
  warning: "bg-warn text-white ring-warn",
  danger: "bg-bad text-white ring-bad",
  accent: "bg-brand-deep text-white ring-brand-deep",
};

const OUTLINE: Record<BadgeTone, string> = {
  neutral: "bg-surface text-muted border-line",
  info: "bg-surface text-brand border-brand-line",
  success: "bg-surface text-good border-good-line",
  warning: "bg-surface text-warn border-warn-line",
  danger: "bg-surface text-bad border-bad-line",
  accent: "bg-surface text-brand-deep border-brand-line",
};

export function Badge({ tone = "neutral", variant = "soft", title, icon, className, children }: BadgeProps) {
  const style =
    variant === "soft"
      ? cx("ring-1 ring-inset", SOFT[tone])
      : variant === "solid"
        ? cx("ring-1 ring-inset", SOLID[tone])
        : cx("border", variant === "dashed" ? "border-dashed" : "border-solid", OUTLINE[tone]);
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-semibold",
        style,
        className,
      )}
    >
      {icon ? <span aria-hidden="true">{icon}</span> : null}
      {children}
    </span>
  );
}
