import { useId } from "react";
import type { DemoUser } from "../api/types";
import { DEMO_USER_LABELS, DEMO_USERS, isDemoUser } from "../auth/permissions";

export interface DemoUserSelectProps {
  value: DemoUser;
  onChange: (user: DemoUser) => void;
}

export function DemoUserSelect({ value, onChange }: DemoUserSelectProps) {
  const id = useId();
  return (
    <div className="flex flex-col gap-0.5">
      <label htmlFor={id} className="text-xs text-slate-300">
        Demo identity (not authentication)
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => {
          if (isDemoUser(e.target.value)) onChange(e.target.value);
        }}
        className="rounded-md border border-slate-600 bg-slate-800 px-2 py-1 text-sm text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400"
      >
        {DEMO_USERS.map((u) => (
          <option key={u} value={u}>
            {DEMO_USER_LABELS[u]}
          </option>
        ))}
      </select>
    </div>
  );
}
