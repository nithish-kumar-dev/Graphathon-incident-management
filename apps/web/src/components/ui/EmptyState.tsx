import type { ReactNode } from "react";
import { cx } from "./cx";

export interface EmptyStateProps {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ title, children, action, className }: EmptyStateProps) {
  return (
    <div className={cx("rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-center", className)}>
      <p className="font-medium text-slate-800">{title}</p>
      {children ? <div className="mt-1 text-sm text-slate-600">{children}</div> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}
