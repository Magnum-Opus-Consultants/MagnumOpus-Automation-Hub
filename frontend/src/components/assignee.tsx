"use client";

/**
 * Who a task belongs to.
 *
 * A dropdown: closed it shows who holds the task, open it lists everyone to
 * pick from. Several people can still hold one task, so the rows toggle rather
 * than choosing one and closing - the workload view books the full estimate
 * against each of them, because splitting it would invent a division nobody
 * recorded, which is worth knowing before putting three people on a 40-hour
 * job.
 */
import { useEffect, useRef, useState } from "react";
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
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  const toggle = (id: number) =>
    onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);

  /* Closing on a click anywhere else and on Escape: the list stays open while
     several people are picked, so it needs a way out that is not a second
     click on the button. */
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  const chosen = people.filter((p) => value.includes(p.id));

  return (
    <div ref={wrap} className="relative">
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
        <>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-haspopup="listbox"
            className="flex h-9 w-full items-center gap-2 rounded-lg bg-canvas px-2.5 text-left text-[13px] text-ink ring-control focus-ring"
          >
            {chosen.length === 0 ? (
              <span className="flex-1 text-ink-3">Unassigned</span>
            ) : (
              <>
                <AssigneeStack people={chosen} />
                <span className="min-w-0 flex-1 truncate">
                  {chosen.map((p) => p.name).join(", ")}
                </span>
              </>
            )}
            <Icon name="chevron" className={`h-4 w-4 shrink-0 text-ink-3 transition ${open ? "rotate-180" : ""}`} />
          </button>

          {open && (
            <ul role="listbox" aria-multiselectable
                className="absolute z-30 mt-1 max-h-60 w-full overflow-auto rounded-lg bg-surface py-1 shadow-lg ring-1 ring-stroke">
              {people.map((p) => {
                const on = value.includes(p.id);
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={on}
                      onClick={() => toggle(p.id)}
                      className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px] transition hover:bg-subtle"
                    >
                      <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-semibold ${
                        on ? "bg-brand text-white" : "bg-subtle text-ink-3"}`}>
                        {initials(p.name)}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-ink">{p.name}</span>
                      {on && <Icon name="check" className="h-4 w-4 shrink-0 text-brand" />}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </>
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
