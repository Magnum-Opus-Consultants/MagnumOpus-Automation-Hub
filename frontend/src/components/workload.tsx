"use client";

/**
 * Workload: who has what, and when.
 *
 * ## Two ways to measure
 *
 * Tasks - how many open tasks each person has on each day. A task counts on
 * every day from its start to its due date. This needs nothing but dates, so
 * it works for teams that don't estimate.
 *
 * Hours - the task's estimate spread evenly over the days it spans: a 12-hour
 * task running Monday to Wednesday shows 4h on each. That is an assumption
 * (the same one ClickUp's "daily scheduled" makes) and the difference between
 * this chart and a timesheet: it shows what is *planned*, not what happened.
 * Tasks with no estimate add nothing to the hours and are counted instead.
 *
 * A task with several assignees counts in full for each of them - splitting
 * it would claim knowledge of a division nobody recorded.
 *
 * ## Work with no dates
 *
 * An open task with no start or due date can't sit on a day, but it is still
 * somebody's work, so it is counted against the person ("12 open · 9 not
 * scheduled") and listed under the chart, where a click opens it to give it
 * dates. Without that, a team that hasn't dated its tasks saw an empty chart
 * and a view that looked broken.
 *
 * ## Reading the colour
 *
 * A full day is 8 hours, or 5 tasks. Under it a cell is quiet; at or over it
 * the cell takes the status scale, because being over capacity is a state
 * somebody has to act on, not a category.
 */
import { useMemo, useState } from "react";
import { Icon } from "@/components/Sidebar";
import { parseISO, toISO, addDays, startOfDay, type Task } from "@/components/tracker";

const UNASSIGNED = "Unassigned";
const CAPACITY = { hours: 8, tasks: 5 } as const;
type Measure = keyof typeof CAPACITY;

type Row = {
  key: string;
  name: string;
  /** ISO day -> hours or tasks booked that day. */
  days: Map<string, number>;
  total: number;
  open: number;
  unscheduled: Task[];
  /** Hours mode only: dated tasks with no estimate. */
  unestimated: number;
};

function eachDay(from: Date, count: number) {
  return Array.from({ length: count }, (_, i) => addDays(from, i));
}

export function Workload({ tasks, days = 14, onOpen }: {
  tasks: Task[]; days?: number; onOpen?: (t: Task) => void;
}) {
  const [offset, setOffset] = useState(0);
  // Hours only mean something once tasks carry estimates; until then the
  // task count is the useful measure.
  const [measure, setMeasure] = useState<Measure>(
    () => (tasks.some((t) => t.estimated_hours != null) ? "hours" : "tasks"));
  const [showUnscheduled, setShowUnscheduled] = useState(true);
  const capacity = CAPACITY[measure];

  const start = useMemo(() => {
    const today = startOfDay(new Date());
    // Start on the Sunday of the week in view, so columns line up with how
    // people read a calendar rather than starting mid-week.
    const sunday = addDays(today, -today.getDay());
    return addDays(sunday, offset * days);
  }, [offset, days]);

  const range = useMemo(() => eachDay(start, days), [start, days]);
  const rangeKeys = useMemo(() => range.map(toISO), [range]);

  const { rows, peak, unscheduledTotal, unestimatedTotal } = useMemo(() => {
    const byPerson = new Map<string, Row>();
    const first = range[0];
    const last = range[range.length - 1];
    let unscheduledCount = 0;
    let unestimated = 0;

    const row = (key: string, name: string) => {
      let r = byPerson.get(key);
      if (!r) {
        r = { key, name, days: new Map(), total: 0, open: 0, unscheduled: [], unestimated: 0 };
        byPerson.set(key, r);
      }
      return r;
    };

    for (const t of tasks) {
      // Done work is not a claim on anybody's future time.
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
        unscheduledCount += 1;
        continue;
      }

      // Only the days inside the window are walked, so a task running for
      // years costs no more than one running for a week.
      const from = startOfDay(s) < first ? first : startOfDay(s);
      const to = startOfDay(e) > last ? last : startOfDay(e);
      const span: string[] = [];
      for (let d = from; d <= to; d = addDays(d, 1)) span.push(toISO(d));

      // Hours spread over the task's whole length, not just the part on
      // screen - otherwise a long task would pile its entire estimate onto
      // whichever days happen to be showing.
      const length = Math.max(1, Math.round(
        (startOfDay(e).getTime() - startOfDay(s).getTime()) / 86_400_000) + 1);
      const perDay = measure === "tasks" ? 1
        : t.estimated_hours != null ? t.estimated_hours / length : 0;

      for (const p of people) {
        const r = row(p.key, p.name);
        r.open += 1;
        if (span.length === 0) continue;
        if (measure === "hours" && t.estimated_hours == null) {
          r.unestimated += 1;
          unestimated += 1;
          continue;
        }
        for (const iso of span) {
          r.days.set(iso, (r.days.get(iso) ?? 0) + perDay);
          r.total += perDay;
        }
      }
    }

    const list = [...byPerson.values()].sort((a, b) =>
      a.key === UNASSIGNED ? 1 : b.key === UNASSIGNED ? -1
        : b.total - a.total || b.open - a.open || a.name.localeCompare(b.name));
    return {
      rows: list,
      peak: Math.max(capacity, ...list.flatMap((r) => [...r.days.values()])),
      unscheduledTotal: unscheduledCount,
      unestimatedTotal: unestimated,
    };
  }, [tasks, range, measure, capacity]);

  const today = toISO(startOfDay(new Date()));
  const label = `${range[0].getDate()} ${range[0].toLocaleString("en", { month: "short" })}`
              + ` – ${range[days - 1].getDate()} `
              + `${range[days - 1].toLocaleString("en", { month: "short" })}`;
  const fmt = (n: number) => (measure === "hours" ? `${round(n)}h` : `${round(n)}`);
  const peopleWithUnscheduled = rows.filter((r) => r.unscheduled.length > 0);

  return (
    <section className="overflow-hidden rounded-xl bg-surface ring-panel">
      <header className="flex flex-wrap items-center gap-3 border-b border-stroke px-4 py-3">
        <div className="flex items-center gap-1">
          <button onClick={() => setOffset((o) => o - 1)} aria-label="Previous period"
                  className="flex h-7 w-7 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring">
            <Icon name="chevron" className="h-4 w-4 -rotate-90" />
          </button>
          <button onClick={() => setOffset(0)}
                  className="rounded-md px-2 py-1 text-xs font-medium text-ink-2 transition hover:bg-subtle hover:text-ink focus-ring">
            Today
          </button>
          <button onClick={() => setOffset((o) => o + 1)} aria-label="Next period"
                  className="flex h-7 w-7 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring">
            <Icon name="chevron" className="h-4 w-4 rotate-90" />
          </button>
        </div>
        <span className="text-sm font-medium text-ink">{label}</span>
        <div role="group" aria-label="Measure workload in"
             className="ml-auto inline-flex overflow-hidden rounded-md ring-1 ring-stroke">
          {(["tasks", "hours"] as const).map((m, i) => (
            <button key={m} type="button" aria-pressed={measure === m} onClick={() => setMeasure(m)}
                    className={`px-2.5 py-1 text-xs font-medium transition ${i ? "border-l border-stroke" : ""} ${
                      measure === m ? "bg-brand-tint text-brand" : "bg-surface text-ink-2 hover:bg-subtle hover:text-ink"}`}>
              {m === "tasks" ? "Tasks" : "Hours"}
            </button>
          ))}
        </div>
        <span className="text-xs text-ink-3">
          {measure === "hours" ? "Estimated hours per day · 8h is a full day" : "Open tasks per day · 5 is a full day"}
        </span>
      </header>

      {rows.length === 0 ? (
        <p className="px-5 py-10 text-center text-sm text-ink-2">No open tasks.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] border-separate" style={{ borderSpacing: 0 }}>
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-surface px-4 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                  Person
                </th>
                {range.map((d) => {
                  const iso = toISO(d);
                  const weekend = d.getDay() === 0 || d.getDay() === 6;
                  return (
                    <th key={iso}
                        className={`px-1 py-2 text-center text-[11px] font-medium ${
                          iso === today ? "text-brand"
                          : weekend ? "text-ink-3/60" : "text-ink-3"}`}>
                      <span className="block">{"SMTWTFS"[d.getDay()]}</span>
                      <span className={`mx-auto mt-0.5 flex h-5 w-5 items-center justify-center rounded-full ${
                        iso === today ? "bg-brand font-semibold text-white" : ""}`}>
                        {d.getDate()}
                      </span>
                    </th>
                  );
                })}
                <th className="px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                  {measure === "hours" ? "Hours" : "Task-days"}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="sticky left-0 z-10 border-t border-stroke bg-surface px-4 py-2">
                    <span className="flex items-center gap-2">
                      <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                        r.key === UNASSIGNED ? "bg-subtle text-ink-3" : "bg-brand text-white"}`}>
                        {r.key === UNASSIGNED ? "?" : initials(r.name)}
                      </span>
                      <span className="truncate text-[13px] text-ink">{r.name}</span>
                    </span>
                    <span className="mt-0.5 block pl-8 text-[11px] text-ink-3">
                      {r.open} open
                      {r.unscheduled.length > 0 && <> · <span className="text-warnx">{r.unscheduled.length} not scheduled</span></>}
                      {r.unestimated > 0 && <> · {r.unestimated} with no estimate</>}
                    </span>
                  </td>
                  {rangeKeys.map((iso) => (
                    <Cell key={iso} value={r.days.get(iso) ?? 0} capacity={capacity} peak={peak} fmt={fmt}
                          title={`${fmt(r.days.get(iso) ?? 0)} of ${fmt(capacity)}`} />
                  ))}
                  <td className="border-t border-stroke px-3 py-2 text-right text-[13px] font-semibold tabular-nums text-ink">
                    {r.total ? fmt(r.total) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {unestimatedTotal > 0 && (
        <p className="border-t border-stroke px-4 py-2.5 text-xs text-ink-3">
          {unestimatedTotal} scheduled task{unestimatedTotal === 1 ? " has" : "s have"} no estimate, so{" "}
          {unestimatedTotal === 1 ? "it is" : "they are"} not in these hours - switch to Tasks to see them,
          or set an estimate on the task.
        </p>
      )}

      {unscheduledTotal > 0 && (
        <div className="border-t border-stroke">
          <button onClick={() => setShowUnscheduled(!showUnscheduled)} aria-expanded={showUnscheduled}
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs font-medium text-ink-2 hover:bg-subtle/60">
            <Icon name="chevron" className={`h-3.5 w-3.5 transition-transform ${showUnscheduled ? "rotate-180" : "rotate-90"}`} />
            Not scheduled · {unscheduledTotal} open task{unscheduledTotal === 1 ? "" : "s"} with no start or due date
            <span className="ml-auto font-normal text-ink-3">Give a task dates to place it on the chart</span>
          </button>
          {showUnscheduled && (
            <div className="grid gap-x-6 gap-y-4 px-4 pb-4 sm:grid-cols-2 xl:grid-cols-3">
              {peopleWithUnscheduled.map((r) => (
                <div key={r.key} className="min-w-0">
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                    {r.name} · {r.unscheduled.length}
                  </p>
                  <ul className="space-y-0.5">
                    {r.unscheduled.map((t) => (
                      <li key={t.id}>
                        <button onClick={() => onOpen?.(t)} disabled={!onOpen}
                                className="w-full truncate rounded px-1.5 py-1 text-left text-[13px] text-ink hover:bg-subtle disabled:cursor-default">
                          {t.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function Cell({ value, capacity, peak, fmt, title }: {
  value: number; capacity: number; peak: number; fmt: (n: number) => string; title: string;
}) {
  if (!value) {
    return <td className="border-t border-stroke px-1 py-2" />;
  }
  const over = value > capacity;
  const full = value >= capacity;
  return (
    <td className="border-t border-stroke px-1 py-2 text-center">
      <span
        title={title}
        className={`mx-auto flex h-8 min-w-11 items-center justify-center rounded-md px-1 text-xs font-semibold tabular-nums ${
          over ? "bg-bad-bg text-bad"
          : full ? "bg-warnx-bg text-warnx"
          : "bg-brand-tint text-ink"}`}
        style={!full ? { opacity: 0.5 + 0.5 * Math.min(1, value / peak) } : undefined}
      >
        {fmt(value)}
      </span>
    </td>
  );
}

const round = (n: number) => (Math.round(n * 10) / 10).toString();

function initials(name: string) {
  return name.split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "")
    .join("") || "?";
}
