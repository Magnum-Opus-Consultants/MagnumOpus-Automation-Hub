"use client";

/**
 * Workload: who is booked for how much, day by day.
 *
 * ## How a task becomes hours on a day
 *
 * A task carries one estimate and a date range, not a per-day plan. So the
 * estimate is spread evenly across the days it spans - a 12-hour task running
 * Monday to Wednesday shows 4h on each. That is an assumption, and it is the
 * same one ClickUp's "daily scheduled" makes, but it is worth saying out loud
 * because it is the difference between this chart and a timesheet: it shows
 * what is *planned*, not what happened.
 *
 * Tasks with no estimate contribute nothing to the numbers. They would
 * otherwise have to be guessed at, and a guess that looks like a measurement
 * is worse than a gap - so they are counted separately and reported, rather
 * than quietly dropped.
 *
 * A task with several assignees books its full estimate against each of them.
 * Splitting it would claim knowledge of a division nobody recorded.
 *
 * ## Reading the colour
 *
 * Capacity is a working day's hours. Under it a cell is quiet; at or over it
 * the cell takes the status scale, because being over capacity is a state
 * somebody has to act on, not a category.
 */
import { useMemo, useState } from "react";
import { Icon } from "@/components/Sidebar";
import { parseISO, toISO, addDays, startOfDay, type Task } from "@/components/tracker";

const UNASSIGNED = "Unassigned";

/** A working day. Used as the capacity line, and configurable per view. */
const DEFAULT_CAPACITY = 8;

type Row = {
  key: string;
  name: string;
  /** ISO day -> hours booked. */
  days: Map<string, number>;
  total: number;
  /** Tasks that land in the window with no estimate on them. */
  unestimated: number;
};

function eachDay(from: Date, count: number) {
  return Array.from({ length: count }, (_, i) => addDays(from, i));
}

export function Workload({ tasks, days = 14, capacity = DEFAULT_CAPACITY }: {
  tasks: Task[]; days?: number; capacity?: number;
}) {
  const [offset, setOffset] = useState(0);

  const start = useMemo(() => {
    const today = startOfDay(new Date());
    // Start on the Sunday of the week in view, so columns line up with how
    // people read a calendar rather than starting mid-week.
    const sunday = addDays(today, -today.getDay());
    return addDays(sunday, offset * days);
  }, [offset, days]);

  const window = useMemo(() => eachDay(start, days), [start, days]);
  const windowKeys = useMemo(() => window.map(toISO), [window]);

  const { rows, busiest, unestimatedTotal } = useMemo(() => {
    const byPerson = new Map<string, Row>();
    const inWindow = new Set(windowKeys);
    let unestimated = 0;

    const row = (key: string, name: string) => {
      let r = byPerson.get(key);
      if (!r) {
        r = { key, name, days: new Map(), total: 0, unestimated: 0 };
        byPerson.set(key, r);
      }
      return r;
    };

    for (const t of tasks) {
      // Done work is not a claim on anybody's future time.
      if (t.status === "done" || t.status === "cancelled") continue;

      const s = parseISO(t.start_date) ?? parseISO(t.end_date);
      const e = parseISO(t.end_date) ?? parseISO(t.start_date);
      if (!s || !e) continue;

      const span: string[] = [];
      for (let d = startOfDay(s); d <= e; d = addDays(d, 1)) {
        const iso = toISO(d);
        if (inWindow.has(iso)) span.push(iso);
        // A task running for years should not walk a year of days.
        if (span.length > days) break;
      }
      if (span.length === 0) continue;

      // The estimate spreads over the task's whole length, not just the part
      // inside the window - otherwise a long task would pile its entire
      // estimate onto whichever days happen to be on screen.
      const totalDays = Math.max(
        1, Math.round((startOfDay(e).getTime() - startOfDay(s).getTime())
                      / 86_400_000) + 1);
      const perDay = t.estimated_hours != null
        ? t.estimated_hours / totalDays : 0;

      const people = t.assignees?.length
        ? t.assignees.map((a) => ({ key: String(a.id), name: a.name }))
        : [{ key: UNASSIGNED, name: UNASSIGNED }];

      for (const person of people) {
        const r = row(person.key, person.name);
        if (t.estimated_hours == null) {
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
        : b.total - a.total || a.name.localeCompare(b.name));
    const peak = Math.max(capacity, ...list.flatMap((r) => [...r.days.values()]));
    return { rows: list, busiest: peak, unestimatedTotal: unestimated };
  }, [tasks, windowKeys, days, capacity]);

  const today = toISO(startOfDay(new Date()));
  const label = `${window[0].getDate()} ${window[0].toLocaleString("en", { month: "short" })}`
              + ` – ${window[days - 1].getDate()} `
              + `${window[days - 1].toLocaleString("en", { month: "short" })}`;

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
        <span className="ml-auto text-xs text-ink-3">
          Estimated hours per day · {capacity}h is a full day
        </span>
      </header>

      {rows.length === 0 ? (
        <p className="px-5 py-10 text-center text-sm text-ink-2">
          Nothing scheduled in this period.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-separate" style={{ borderSpacing: 0 }}>
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-surface px-4 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                  Person
                </th>
                {window.map((d) => {
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
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className="border-t border-stroke">
                  <td className="sticky left-0 z-10 border-t border-stroke bg-surface px-4 py-2">
                    <span className="flex items-center gap-2">
                      <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                        r.key === UNASSIGNED
                          ? "bg-subtle text-ink-3" : "bg-brand text-white"}`}>
                        {r.key === UNASSIGNED ? "?" : initials(r.name)}
                      </span>
                      <span className="truncate text-[13px] text-ink">{r.name}</span>
                    </span>
                    {r.unestimated > 0 && (
                      <span className="mt-0.5 block pl-8 text-[11px] text-ink-3">
                        {r.unestimated} task{r.unestimated === 1 ? "" : "s"} with no estimate
                      </span>
                    )}
                  </td>
                  {windowKeys.map((iso) => (
                    <Cell key={iso} hours={r.days.get(iso) ?? 0}
                          capacity={capacity} peak={busiest} />
                  ))}
                  <td className="border-t border-stroke px-3 py-2 text-right text-[13px] font-semibold tabular-nums text-ink">
                    {r.total ? `${round(r.total)}h` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {unestimatedTotal > 0 && (
        <p className="border-t border-stroke px-4 py-2.5 text-xs text-ink-3">
          {unestimatedTotal} scheduled task{unestimatedTotal === 1 ? " has" : "s have"} no
          estimate, so {unestimatedTotal === 1 ? "it is" : "they are"} not counted in these
          hours. Set an estimate on the task and it appears here.
        </p>
      )}
    </section>
  );
}

function Cell({ hours, capacity, peak }: {
  hours: number; capacity: number; peak: number;
}) {
  if (!hours) {
    return <td className="border-t border-stroke px-1 py-2" />;
  }
  const over = hours > capacity;
  const full = hours >= capacity;
  return (
    <td className="border-t border-stroke px-1 py-2 text-center">
      <span
        title={`${round(hours)}h of ${capacity}h`}
        className={`mx-auto flex h-8 min-w-11 items-center justify-center rounded-md px-1 text-xs font-semibold tabular-nums ${
          over ? "bg-bad-bg text-bad"
          : full ? "bg-warnx-bg text-warnx"
          : "bg-brand-tint text-ink"}`}
        style={!full ? { opacity: 0.5 + 0.5 * Math.min(1, hours / peak) } : undefined}
      >
        {round(hours)}h
      </span>
    </td>
  );
}

const round = (n: number) => (Math.round(n * 10) / 10).toString();

function initials(name: string) {
  return name.split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "")
    .join("") || "?";
}
