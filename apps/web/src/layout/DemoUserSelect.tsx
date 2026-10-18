import { useId } from "react";
import type { DemoUser } from "../api/types";
import { DEMO_USER_LABELS, DEMO_USERS, isDemoUser } from "../auth/permissions";

export interface DemoUserSelectProps {
  value: DemoUser;
  onChange: (user: DemoUser) => void;
}

export function DemoUserSelect({ value, onChange }: DemoUserSelectProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <label htmlFor={id} className="text-sm font-semibold text-ink">
        Viewing as
      </label>
      <select
        id={id}
        value={value}
        aria-describedby={hintId}
        onChange={(e) => {
          if (isDemoUser(e.target.value)) onChange(e.target.value);
        }}
        className="rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-semibold text-ink shadow-sm hover:border-line-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
      >
        {DEMO_USERS.map((u) => (
          <option key={u} value={u}>
            {DEMO_USER_LABELS[u]}
          </option>
        ))}
      </select>
      <span id={hintId} className="text-xs text-muted">
        Switches the demo identity and its permissions. Not authentication.
      </span>
    </div>
  );
}
