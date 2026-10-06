"use client";

/**
 * Workload, laid out the way ClickUp's Workload view is: people down the side,
 * days across the top, one capacity box per person per day that fills up -
 * green while there is room, red once they are over - and a panel of
 * unscheduled tasks on the right. A person's row opens to show their tasks as
 * bars across the days they span.
 *
 * ## Capacity
 *
 * Tasks - how many open tasks someone has on a day; a task counts on every
 * day from its start to its due date. Needs nothing but dates.
 *
 * Time estimates - the estimate spread evenly over the days the task spans: a
 * 12-hour task running Monday to Wednesday is 4h on each (ClickUp's "daily
 * scheduled" assumption). It shows what is planned, not what happened. Tasks
 * with no estimate add nothing and are counted instead.
 *
 * A full day is 8 hours or 5 tasks. A task with several assignees counts in
 * full for each - splitting it would claim knowledge nobody recorded.
 *
 * ## Unscheduled
 *
 * An open task with no start or due date can't sit on a day, but it is still
 * somebody's work. It is counted on the person ("4 tasks · 3 unscheduled")
 * and listed in the side panel, where a click opens it to give it dates.
 */
import { useMemo, useState } from "react";
import { Icon } from "@/components/Sidebar";
import {
  parseISO, toISO, addDays, startOfDay, STATE_DOT, STATUS_TONE, type Task,
} from "@/components/tracker";

const UNASSIGNED = "Unassigned";
const CAPACITY = { tasks: 5, hours: 8 } as const;
type Measure = keyof typeof CAPACITY;
const PERIODS = [{ days: 7, label: "Week" }, { days: 14, label: "2 weeks" }, { days: 28, label: "Month" }] as const;

// ClickUp's workload colours: green with room to spare, red over capacity,
// purple for today.
const GREEN = "#6BC950";
const RED = "#E44332";
const PURPLE = "#7B68EE";
// ClickUp's avatar palette, picked per person from their name.
const AVATARS = ["#7B68EE", "#FF7FAB", "#0AB4FF", "#1BBC9C", "#FF7800", "#5F55EE", "#E44332", "#3DB88B", "#AF7E2E", "#F9A825"];

type Placed = { task: Task; from: number; to: number };
type Row = {
  key: string;
  name: string;
  /** ISO day -> tasks or hours booked that day. */
  days: Map<string, number>;
  open: number;
  scheduled: Placed[];
  unscheduled: Task[];
  unestimated: number;
};

const eachDay = (from: Date, count: number) => Array.from({ length: count }, (_, i) => addDays(from, i));
const round = (n: number) => (Math.round(n * 10) / 10).toString();

function avatarColour(name: string) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return AVATARS[h % AVATARS.length];
}

function initials(name: string) {
  return name.split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("") || "?";
}

function Avatar({ name, unassigned = false, size = 28 }: { name: string; unassigned?: boolean; size?: number }) {
  return (
    <span aria-hidden
          className="flex shrink-0 items-center justify-center rounded-full font-semibold text-white"
          style={{ width: size, height: size, fontSize: size * 0.38,
                   backgroundColor: unassigned ? "var(--c-ink-3)" : avatarColour(name) }}>
      {unassigned ? "?" : initials(name)}
    </span>
  );
}

export function Workload({ tasks, onOpen }: { tasks: Task[]; onOpen?: (t: Task) => void }) {
  const [days, setDays] = useState<number>(14);
  const [offset, setOffset] = useState(0);
  // Time estimates only mean something once tasks carry them; until then the
  // task count is the useful measure.
  const [measure, setMeasure] = useState<Measure>(
    () => (tasks.some((t) => t.estimated_hours != null) ? "hours" : "tasks"));
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [panel, setPanel] = useState(true);
  const capacity = CAPACITY[measure];

  const start = useMemo(() => {
    const today = startOfDay(new Date());
    // Weeks start on Sunday, as ClickUp's do.
    const sunday = addDays(today, -today.getDay());
    return addDays(sunday, offset * days);
  }, [offset, days]);
  const range = useMemo(() => eachDay(start, days), [start, days]);
  const rangeKeys = useMemo(() => range.map(toISO), [range]);

  const { rows, unscheduled, unestimated } = useMemo(() => {
    const byPerson = new Map<string, Row>();
    const first = range[0];
    const last = range[range.length - 1];
    const loose: Task[] = [];
    let noEstimate = 0;
    const row = (key: string, name: string) => {
      let r = byPerson.get(key);
      if (!r) {
        r = { key, name, days: new Map(), open: 0, scheduled: [], unscheduled: [], unestimated: 0 };
        byPerson.set(key, r);
      }
      return r;
    };

    for (const t of tasks) {
      if (t.status === "done" || t.status === "cancelled") continue;
      const people = t.assignees?.length
        ? t.assignees.map((a) => ({ key: String(a.id), name: a.name }))
        : [{ key: UNASSIGNED, name: UNASSIGNED }];
      const s = parseISO(t.start_date) ?? parseISO(t.end_date);
      const e = parseISO(t.end_date) ?? parseISO(t.start_date);
      if (!s || !e) {
        for (const p of people) {
          const r = row(p.key, p.name);
          r.open += 1;
          r.unscheduled.push(t);
        }
        loose.push(t);
        continue;
      }
      // Only the days in view are walked, so a year-long task costs nothing.
      const from = startOfDay(s) < first ? first : startOfDay(s);
      const to = startOfDay(e) > last ? last : startOfDay(e);
      const span: string[] = [];
      for (let d = from; d <= to; d = addDays(d, 1)) span.push(toISO(d));
      // Hours spread over the task's whole length, not just what is on screen.
      const length = Math.max(1, Math.round(
        (startOfDay(e).getTime() - startOfDay(s).getTime()) / 86_400_000) + 1);
      const perDay = measure === "tasks" ? 1
        : t.estimated_hours != null ? t.estimated_hours / length : 0;

      for (const p of people) {
        const r = row(p.key, p.name);
        r.open += 1;
        if (span.length === 0) continue;
        r.scheduled.push({ task: t, from: rangeKeys.indexOf(span[0]), to: rangeKeys.indexOf(span[span.length - 1]) });
        if (measure === "hours" && t.estimated_hours == null) {
          r.unestimated += 1;
          noEstimate += 1;
          continue;
        }
        for (const iso of span) r.days.set(iso, (r.days.get(iso) ?? 0) + perDay);
      }
    }

    const load = (r: Row) => [...r.days.values()].reduce((a, b) => a + b, 0);
    const list = [...byPerson.values()].sort((a, b) =>
      a.key === UNASSIGNED ? 1 : b.key === UNASSIGNED ? -1
        : load(b) - load(a) || b.open - a.open || a.name.localeCompare(b.name));
    for (const r of list) r.scheduled.sort((a, b) => a.from - b.from || a.to - b.to);
    return { rows: list, unscheduled: loose, unestimated: noEstimate };
  }, [tasks, range, rangeKeys, measure]);

  const today = toISO(startOfDay(new Date()));
  const month = (d: Date) => d.toLocaleString("en-US", { month: "short" });
  const label = range[0].getMonth() === range[days - 1].getMonth()
    ? `${month(range[0])} ${range[0].getDate()} – ${range[days - 1].getDate()}`
    : `${month(range[0])} ${range[0].getDate()} – ${month(range[days - 1])} ${range[days - 1].getDate()}`;
  const fmt = (n: number) => (measure === "hours" ? `${round(n)}h` : round(n));
  const cols = { gridTemplateColumns: `248px repeat(${days}, minmax(${days > 14 ? 34 : 46}px, 1fr))` };
  const toggle = (key: string) => setExpanded((cur) => {
    const next = new Set(cur);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  return (
    <section className="overflow-hidden rounded-xl bg-surface ring-panel">
      {/* ── toolbar ───────────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-center gap-2 border-b border-stroke px-3 py-2">
        <button onClick={() => setOffset(0)}
                className="rounded-md px-2.5 py-1 text-[13px] font-medium text-ink ring-1 ring-stroke transition hover:bg-subtle">
          Today
        </button>
        <div className="flex items-center">
          <button onClick={() => setOffset((o) => o - 1)} aria-label="Previous"
                  className="flex h-7 w-7 items-center justify-center rounded-md text-ink-2 transition hover:bg-subtle hover:text-ink">
            <Icon name="chevron" className="h-4 w-4 -rotate-90" />
          </button>
          <button onClick={() => setOffset((o) => o + 1)} aria-label="Next"
                  className="flex h-7 w-7 items-center justify-center rounded-md text-ink-2 transition hover:bg-subtle hover:text-ink">
            <Icon name="chevron" className="h-4 w-4 rotate-90" />
          </button>
        </div>
        <span className="text-[13px] font-semibold text-ink">{label}</span>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Segmented label="Period" value={days} onChange={(v) => { setDays(v); setOffset(0); }}
                     options={PERIODS.map((p) => ({ value: p.days, label: p.label }))} />
          <span className="text-[12px] text-ink-3">Capacity</span>
          <Segmented label="Capacity" value={measure} onChange={setMeasure}
                     options={[{ value: "tasks" as Measure, label: "Tasks" }, { value: "hours" as Measure, label: "Time estimates" }]} />
          <button onClick={() => setPanel(!panel)} aria-pressed={panel}
                  className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[13px] font-medium ring-1 transition ${
                    panel ? "bg-subtle text-ink ring-stroke" : "text-ink-2 ring-stroke hover:bg-subtle"}`}>
            Unscheduled
            <span className="rounded px-1.5 text-[11px] font-semibold text-white" style={{ backgroundColor: PURPLE }}>
              {unscheduled.length}
            </span>
          </button>
        </div>
      </header>

      <div className="flex">
        {/* ── grid ────────────────────────────────────────────────────── */}
        <div className="min-w-0 flex-1 overflow-x-auto">
          <div style={{ minWidth: 248 + days * (days > 14 ? 34 : 46) }}>
            <div className="grid border-b border-stroke" style={cols}>
              <div className="sticky left-0 z-10 flex items-end bg-surface px-4 pb-2 text-[11px] font-medium text-ink-3">
                Assignees
              </div>
              {range.map((d) => {
                const iso = toISO(d);
                const weekend = d.getDay() === 0 || d.getDay() === 6;
                const isToday = iso === today;
                return (
                  <div key={iso} className={`flex flex-col items-center gap-0.5 py-1.5 ${weekend ? "bg-subtle/60" : ""}`}>
                    <span className="text-[10px] font-medium uppercase text-ink-3">
                      {d.toLocaleString("en-US", { weekday: days > 14 ? "narrow" : "short" })}
                    </span>
                    <span className={`flex h-6 w-6 items-center justify-center rounded-full text-[12px] ${
                      isToday ? "font-semibold text-white" : weekend ? "text-ink-3" : "text-ink"}`}
                          style={isToday ? { backgroundColor: PURPLE } : undefined}>
                      {d.getDate()}
                    </span>
                  </div>
                );
              })}
            </div>

            {rows.length === 0 && (
              <p className="px-5 py-12 text-center text-sm text-ink-3">No open tasks.</p>
            )}

            {rows.map((r) => {
              const open = expanded.has(r.key);
              const isNobody = r.key === UNASSIGNED;
              return (
                <div key={r.key} className="border-b border-stroke last:border-0">
                  <div className="grid" style={cols}>
                    <button onClick={() => toggle(r.key)} aria-expanded={open}
                            className="sticky left-0 z-10 flex items-center gap-2 bg-surface px-2 py-2 text-left hover:bg-subtle/60">
                      <Icon name="chevron" className={`h-3.5 w-3.5 shrink-0 text-ink-3 transition-transform ${open ? "rotate-180" : "rotate-90"}`} />
                      <Avatar name={r.name} unassigned={isNobody} />
                      <span className="min-w-0">
                        <span className="block truncate text-[13px] font-medium text-ink">{r.name}</span>
                        <span className="block truncate text-[11px] text-ink-3">
                          {r.open} task{r.open === 1 ? "" : "s"}
                          {r.unscheduled.length > 0 && ` · ${r.unscheduled.length} unscheduled`}
                          {r.unestimated > 0 && ` · ${r.unestimated} no estimate`}
                        </span>
                      </span>
                    </button>
                    {rangeKeys.map((iso, i) => (
                      <CapacityBox key={iso} value={r.days.get(iso) ?? 0} capacity={capacity} fmt={fmt}
                                   weekend={range[i].getDay() === 0 || range[i].getDay() === 6} />
                    ))}
                  </div>

                  {/* A person opened up: their tasks as bars across the days. */}
                  {open && (
                    <div className="bg-subtle/30 pb-1.5">
                      {r.scheduled.length === 0 ? (
                        <p className="px-12 py-2 text-[12px] text-ink-3">No scheduled tasks in this period.</p>
                      ) : r.scheduled.map(({ task, from, to }) => {
                        const tone = STATUS_TONE[task.status] ?? STATUS_TONE.backlog;
                        return (
                          <div key={task.id} className="grid items-center py-0.5" style={cols}>
                            <span className="sticky left-0 z-10 truncate bg-transparent pl-12 pr-2 text-[11px] text-ink-3">
                              {task.list_name || task.project_name}
                            </span>
                            <button onClick={() => onOpen?.(task)} title={task.title}
                                    className="mx-0.5 flex h-7 min-w-0 items-center gap-1.5 rounded-md px-2 text-left text-[12px] font-medium shadow-sm ring-1 ring-black/5 transition hover:brightness-95"
                                    style={{ gridColumn: `${from + 2} / ${to + 3}`, backgroundColor: tone.bg, color: tone.fg }}>
                              <span className={`h-2 w-2 shrink-0 rounded-full ${STATE_DOT[task.status] ?? "bg-ink-3"}`} />
                              <span className="truncate">{task.title}</span>
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {unestimated > 0 && (
            <p className="border-t border-stroke px-4 py-2 text-[12px] text-ink-3">
              {unestimated} scheduled task{unestimated === 1 ? " has" : "s have"} no time estimate, so{" "}
              {unestimated === 1 ? "it isn't" : "they aren't"} in these hours. Switch Capacity to Tasks to see{" "}
              {unestimated === 1 ? "it" : "them"}.
            </p>
          )}
        </div>

        {/* ── unscheduled ─────────────────────────────────────────────── */}
        {panel && (
          <aside className="w-72 shrink-0 border-l border-stroke">
            <div className="flex items-center gap-2 border-b border-stroke px-3 py-2.5">
              <span className="text-[13px] font-semibold text-ink">Unscheduled</span>
              <span className="text-[12px] text-ink-3">{unscheduled.length}</span>
              <button onClick={() => setPanel(false)} aria-label="Close unscheduled tasks"
                      className="ml-auto rounded p-1 text-ink-3 hover:bg-subtle hover:text-ink">
                <Icon name="x" className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className="px-3 pt-2 text-[11px] text-ink-3">No start or due date. Open a task to schedule it.</p>
            {unscheduled.length === 0 ? (
              <p className="px-3 py-6 text-center text-[12px] text-ink-3">Everything is scheduled.</p>
            ) : (
              <ul className="max-h-[520px] space-y-1.5 overflow-y-auto p-2">
                {unscheduled.map((t) => (
                  <li key={t.id}>
                    <button onClick={() => onOpen?.(t)} disabled={!onOpen}
                            className="w-full rounded-lg bg-surface p-2.5 text-left ring-1 ring-stroke transition hover:ring-brand/40 hover:shadow-sm disabled:cursor-default">
                      <span className="flex items-start gap-2">
                        <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${STATE_DOT[t.status] ?? "bg-ink-3"}`} />
                        <span className="line-clamp-2 text-[13px] font-medium text-ink">{t.title}</span>
                      </span>
                      <span className="mt-1.5 flex items-center gap-1.5 pl-4">
                        {(t.assignees?.length ? t.assignees : [{ id: 0, name: UNASSIGNED }]).slice(0, 3).map((a) => (
                          <Avatar key={a.id} name={a.name} unassigned={!a.id} size={18} />
                        ))}
                        <span className="truncate text-[11px] text-ink-3">{t.list_name || t.project_name}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>
        )}
      </div>
    </section>
  );
}

/* One person's day: a box that fills from the bottom as the day fills up.
   Green with room to spare, red once over capacity. Non-working days are
   hatched, as ClickUp draws them. */
function CapacityBox({ value, capacity, fmt, weekend }: {
  value: number; capacity: number; fmt: (n: number) => string; weekend: boolean;
}) {
  const over = value > capacity;
  const pct = Math.min(100, (value / capacity) * 100);
  return (
    <div className={`px-0.5 py-1.5 ${weekend ? "bg-subtle/60" : ""}`}>
      <div title={value ? `${fmt(value)} of ${fmt(capacity)}` : undefined}
           className="relative h-10 overflow-hidden rounded-md bg-subtle"
           style={weekend && !value ? {
             backgroundImage: "repeating-linear-gradient(135deg, transparent 0 5px, rgba(127,127,127,.12) 5px 10px)",
           } : undefined}>
        {value > 0 && (
          <>
            <div className="absolute inset-x-0 bottom-0 transition-[height]"
                 style={{ height: `${over ? 100 : Math.max(pct, 8)}%`, backgroundColor: over ? RED : GREEN }} />
            <span className={`relative z-[1] flex h-full items-center justify-center text-[12px] font-semibold tabular-nums ${
              over || pct >= 55 ? "text-white" : "text-ink"}`}>
              {fmt(value)}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

function Segmented<T extends string | number>({ label, value, options, onChange }: {
  label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex overflow-hidden rounded-md ring-1 ring-stroke">
      {options.map((o, i) => (
        <button key={String(o.value)} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}
                className={`px-2.5 py-1 text-[12px] font-medium transition ${i ? "border-l border-stroke" : ""} ${
                  value === o.value ? "bg-subtle text-ink" : "bg-surface text-ink-2 hover:bg-subtle/60 hover:text-ink"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
