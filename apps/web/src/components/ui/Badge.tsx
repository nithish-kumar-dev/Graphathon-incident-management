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
  neutral: "bg-slate-100 text-slate-800 ring-slate-300",
  info: "bg-sky-50 text-sky-900 ring-sky-300",
  success: "bg-emerald-50 text-emerald-900 ring-emerald-300",
  warning: "bg-amber-50 text-amber-900 ring-amber-400",
  danger: "bg-red-50 text-red-900 ring-red-300",
  accent: "bg-violet-50 text-violet-900 ring-violet-300",
};

const SOLID: Record<BadgeTone, string> = {
  neutral: "bg-slate-700 text-white ring-slate-700",
  info: "bg-sky-700 text-white ring-sky-700",
  success: "bg-emerald-700 text-white ring-emerald-700",
  warning: "bg-amber-600 text-white ring-amber-600",
  danger: "bg-red-700 text-white ring-red-700",
  accent: "bg-violet-700 text-white ring-violet-700",
};

const OUTLINE: Record<BadgeTone, string> = {
  neutral: "bg-white text-slate-800 border-slate-400",
  info: "bg-white text-sky-900 border-sky-500",
  success: "bg-white text-emerald-900 border-emerald-600",
  warning: "bg-white text-amber-900 border-amber-500",
  danger: "bg-white text-red-900 border-red-500",
  accent: "bg-white text-violet-900 border-violet-500",
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
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium",
        style,
        className,
      )}
    >
      {icon ? <span aria-hidden="true">{icon}</span> : null}
      {children}
    </span>
  );
}
