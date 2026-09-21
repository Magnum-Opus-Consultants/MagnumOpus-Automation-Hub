"use client";

/**
 * Who a task belongs to.
 *
 * A row of avatars that toggle. With eight or so people a dropdown would be
 * three interactions (open, find, close) for something that should be one, and
 * it would hide who is already on the task behind a closed control.
 *
 * Several people can hold one task. The workload view books the full estimate
 * against each of them, because splitting it would invent a division nobody
 * recorded - worth knowing before assigning three people to a 40-hour job.
 */
import { Icon } from "@/components/Sidebar";

export type Person = { id: number; name: string; username?: string };

export function initials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "").join("") || "?";
}

export function AssigneePicker({ people, value, onChange, label = "Assigned to" }: {
  people: Person[];
  value: number[];
  onChange: (ids: number[]) => void;
  label?: string;
}) {
  const toggle = (id: number) =>
    onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-[13px] font-medium text-ink">{label}</span>
        {value.length > 0 && (
          <button type="button" onClick={() => onChange([])}
                  className="text-[11px] text-ink-3 underline-offset-2 transition hover:text-ink hover:underline focus-ring">
            Clear
          </button>
        )}
      </div>
      {people.length === 0 ? (
        <p className="text-xs text-ink-3">No people to assign to yet.</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {people.map((p) => {
            const on = value.includes(p.id);
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => toggle(p.id)}
                aria-pressed={on}
                title={p.name}
                className={`flex items-center gap-1.5 rounded-full py-1 pl-1 pr-2.5 text-xs transition focus-ring ${
                  on ? "bg-brand text-white"
                     : "bg-subtle text-ink-2 hover:bg-subtle hover:text-ink"}`}
              >
                <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-semibold ${
                  on ? "bg-white/25 text-white" : "bg-surface text-ink-3"}`}>
                  {initials(p.name)}
                </span>
                <span className="max-w-28 truncate">{p.name}</span>
                {on && <Icon name="check" className="h-3 w-3 shrink-0" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** The stack shown on a card or row, where there is no room to pick. */
export function AssigneeStack({ people, max = 3 }: {
  people: { id: number; name: string }[]; max?: number;
}) {
  if (people.length === 0) return null;
  const shown = people.slice(0, max);
  const rest = people.length - shown.length;
  return (
    <span className="flex items-center -space-x-1.5">
      {shown.map((p) => (
        <span key={p.id} title={p.name}
              className="flex h-5 w-5 items-center justify-center rounded-full bg-brand text-[9px] font-semibold text-white ring-2 ring-surface">
          {initials(p.name)}
        </span>
      ))}
      {rest > 0 && (
        <span title={people.slice(max).map((p) => p.name).join(", ")}
              className="flex h-5 w-5 items-center justify-center rounded-full bg-subtle text-[9px] font-semibold text-ink-2 ring-2 ring-surface">
          +{rest}
        </span>
      )}
    </span>
  );
}
