"use client";

/**
 * The project Gantt, built to the structure of the E-Click dashboard.
 *
 * Two levels, which is the whole point of it:
 *
 *   Project ──────────────────────  one bar, coloured by status, progress inside
 *     └ Week 1  ████                tasks that fall in that week, done vs total
 *       Week 2      ██████
 *
 * A project bar says a project runs March to June. The week rows say where the
 * work actually sits inside it — which is the question you open a Gantt to
 * answer, and what a flat list of task bars cannot tell you.
 *
 * Layout: a fixed detail column that does not scroll, and a timeline that does.
 * Bars are positioned as percentages of the overall span rather than in pixels,
 * so the chart survives a resize without recalculating anything.
 */
import { useMemo, useState } from "react";
import { Icon } from "@/components/Sidebar";

export type GanttWeek = {
  week_number: number; iso_week: number;
  start_date: string; end_date: string;
  total_tasks: number; completed_tasks: number; blocked_tasks: number;
  progress: number; is_current: boolean; titles: string[];
};
export type GanttProject = {
  name: string; label: string;
  status: string; status_label: string; color: string;
  client: string; priority: string; icon: string; accent: string;
  workspace: string; development_status: string;
  start_date: string; end_date: string; dates_derived: boolean;
  total_tasks: number; completed_tasks: number;
  blocked_tasks: number; overdue_tasks: number;
  progress: number; weeks: GanttWeek[]; weeks_trimmed: boolean;
};
export type GanttData = {
  today: string; span_start: string; span_end: string; span_days: number;
  projects: GanttProject[];
  legend: { status: string; label: string; color: string }[];
  development_labels: Record<string, string>;
  workspaces: string[];
};

const DAY = 86400000;
const DETAIL_W = 320;

/* Minimum width per column, in pixels. Percentage-width columns divided the
   viewport by however many weeks were in range - thirty-eight of them at 24px
   each, which rendered every label as "D. W". A column now has a floor and the
   chart scrolls sideways instead, which is what makes the scale readable. */
const COL_MIN = { weeks: 68, months: 104 } as const;

/** Minimum bar width in percent, so a one-day task is still clickable. */
const MIN_BAR_PCT = 0.8;

function days(a: string, b: string) {
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / DAY);
}

function fmt(d: string) {
  return new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Where a span sits on the timeline, as percentages of the whole. */
function place(spanStart: string, spanDays: number, start: string, end: string) {
  const left = (days(spanStart, start) / spanDays) * 100;
  const width = ((days(start, end) + 1) / spanDays) * 100;
  return {
    left: `${Math.max(0, Math.min(100, left))}%`,
    width: `${Math.max(MIN_BAR_PCT, Math.min(100 - Math.max(0, left), width))}%`,
  };
}

/** Column headers: one per week, or one per month. */
function useColumns(data: GanttData, scale: "weeks" | "months") {
  return useMemo(() => {
    const out: { label: string; sub: string; left: number; width: number }[] = [];
    const start = new Date(data.span_start);
    const end = new Date(data.span_end);
    if (scale === "weeks") {
      const cursor = new Date(start);
      while (cursor <= end) {
        const next = new Date(cursor.getTime() + 7 * DAY);
        out.push({
          label: cursor.toLocaleDateString(undefined, { day: "numeric", month: "short" }),
          sub: `W${isoWeek(cursor)}`,
          left: (days(data.span_start, cursor.toISOString().slice(0, 10)) / data.span_days) * 100,
          width: (7 / data.span_days) * 100,
        });
        cursor.setTime(next.getTime());
      }
    } else {
      const cursor = new Date(start.getFullYear(), start.getMonth(), 1);
      while (cursor <= end) {
        const next = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
        const from = cursor < start ? start : cursor;
        const to = next > end ? end : next;
        out.push({
          label: cursor.toLocaleDateString(undefined, { month: "long" }),
          sub: String(cursor.getFullYear()),
          left: (days(data.span_start, from.toISOString().slice(0, 10)) / data.span_days) * 100,
          width: (Math.max(1, days(from.toISOString().slice(0, 10), to.toISOString().slice(0, 10))) / data.span_days) * 100,
        });
        cursor.setTime(next.getTime());
      }
    }
    return out;
  }, [data, scale]);
}

function isoWeek(d: Date) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t.getTime() - yearStart.getTime()) / DAY + 1) / 7);
}

export function Gantt({ data }: { data: GanttData }) {
  const [scale, setScale] = useState<"weeks" | "months">("weeks");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  // Zoom is a width multiplier on the timeline, so the detail column keeps its
  // size and only the dated area grows.
  const [zoom, setZoom] = useState(1);
  const columns = useColumns(data, scale);

  const todayLeft = useMemo(
    () => (days(data.span_start, data.today) / data.span_days) * 100,
    [data]);

  // Pixels, not percent: the width follows the number of columns so each one
  // keeps its floor, and zoom multiplies it.
  const timelineWidth = Math.round(
    Math.max(480, columns.length * COL_MIN[scale]) * zoom);
  const rowWidth = DETAIL_W + timelineWidth;

  return (
    <div className="overflow-hidden rounded-xl bg-surface ring-1 ring-stroke">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2 border-b border-stroke px-3 py-2">
        <div className="flex rounded-lg bg-subtle p-0.5">
          {(["weeks", "months"] as const).map((s) => (
            <button key={s} onClick={() => setScale(s)}
                    className={`rounded-md px-2.5 py-1 text-xs font-semibold capitalize transition ${
                      scale === s ? "bg-surface text-ink shadow-sm" : "text-ink-3 hover:text-ink"
                    }`}>
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setZoom((z) => Math.max(1, +(z - 0.5).toFixed(1)))}
                  disabled={zoom <= 1} aria-label="Zoom out"
                  className="flex h-7 w-7 items-center justify-center rounded-md text-ink-2 ring-control transition hover:bg-subtle disabled:opacity-30 focus-ring">
            −
          </button>
          <span className="w-10 text-center text-xs tabular-nums text-ink-3">{zoom}×</span>
          <button onClick={() => setZoom((z) => Math.min(6, +(z + 0.5).toFixed(1)))}
                  disabled={zoom >= 6} aria-label="Zoom in"
                  className="flex h-7 w-7 items-center justify-center rounded-md text-ink-2 ring-control transition hover:bg-subtle disabled:opacity-30 focus-ring">
            +
          </button>
        </div>
        <button
          onClick={() => setOpen(Object.fromEntries(
            data.projects.map((p) => [p.name || p.label,
              !data.projects.every((q) => open[q.name || q.label])])))}
          className="rounded-lg px-2.5 py-1 text-xs font-medium text-ink-2 ring-control transition hover:bg-subtle focus-ring">
          {data.projects.every((p) => open[p.name || p.label]) ? "Collapse all" : "Expand all"}
        </button>

        <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1">
          {data.legend
            .filter((l) => data.projects.some((p) => p.status === l.status))
            .map((l) => (
              <span key={l.status} className="flex items-center gap-1.5 text-[11px] text-ink-3">
                <span aria-hidden className="h-2.5 w-2.5 rounded-sm"
                      style={{ background: l.color }} />
                {l.label}
              </span>
            ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <div style={{ minWidth: `${rowWidth}px` }}>
          {/* Header */}
          <div className="sticky top-0 z-10 flex border-b border-stroke bg-subtle/80 backdrop-blur">
            <div className="sticky left-0 z-[2] shrink-0 border-r border-stroke bg-subtle px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3"
                 style={{ width: DETAIL_W }}>
              Project
            </div>
            <div className="relative shrink-0 overflow-hidden" style={{ width: timelineWidth }}>
              <div className="relative h-full" style={{ width: timelineWidth }}>
                {columns.map((c, i) => (
                  <div key={i}
                       className="absolute top-0 border-l border-stroke px-1.5 py-2 text-[11px] leading-tight"
                       style={{ left: `${c.left}%`, width: `${c.width}%` }}>
                    <span className="block truncate font-semibold text-ink-2">{c.label}</span>
                    <span className="block truncate text-ink-3">{c.sub}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Rows */}
          <div>
            {data.projects.map((p) => {
              const key = p.name || p.label;
              const isOpen = !!open[key];
              const pos = place(data.span_start, data.span_days, p.start_date, p.end_date);
              return (
                <div key={key} className="border-b border-stroke last:border-0">
                  {/* Project row */}
                  <div className="group flex hover:bg-subtle/40">
                    <div className="sticky left-0 z-[2] shrink-0 border-r border-stroke bg-surface px-3 py-3 group-hover:bg-subtle/40"
                         style={{ width: DETAIL_W }}>
                      <div className="flex items-start gap-2">
                        <button
                          onClick={() => setOpen((o) => ({ ...o, [key]: !o[key] }))}
                          disabled={p.weeks.length === 0}
                          aria-label={isOpen ? "Hide weeks" : "Show weeks"}
                          className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-3 transition hover:bg-subtle hover:text-ink disabled:opacity-0 focus-ring">
                          <Icon name="chevron"
                                className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-180" : "rotate-90"}`} />
                        </button>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            {p.icon && <span aria-hidden className="text-sm">{p.icon}</span>}
                            <span className="truncate text-sm font-semibold text-ink">
                              {p.label}
                            </span>
                            <span className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold text-white"
                                  style={{ background: p.color }}>
                              {p.status_label}
                            </span>
                          </div>
                          <div className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-ink-3">
                            <span>
                              {fmt(p.start_date)} – {fmt(p.end_date)}
                              {p.dates_derived && (
                                <span title="Taken from its tasks — the project has no dates of its own"> *</span>
                              )}
                            </span>
                            {p.client && <span>· {p.client}</span>}
                            {p.priority && <span>· {p.priority}</span>}
                          </div>
                          {p.development_status && (
                            <div className="mt-0.5 truncate text-[11px] text-ink-3">
                              {data.development_labels[p.development_status] ?? p.development_status}
                            </div>
                          )}
                          <div className="mt-1.5 flex items-center gap-2">
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-subtle">
                              <div className="h-full rounded-full transition-all"
                                   style={{ width: `${p.progress}%`, background: p.color }} />
                            </div>
                            <span className="w-14 text-right text-[11px] tabular-nums text-ink-3">
                              {p.completed_tasks}/{p.total_tasks}
                            </span>
                          </div>
                          {p.overdue_tasks > 0 && (
                            <div className="mt-1 text-[11px] font-medium text-bad">
                              {p.overdue_tasks} overdue
                            </div>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="relative shrink-0 py-3" style={{ width: timelineWidth }}>
                      <div className="relative h-full" style={{ width: timelineWidth }}>
                        <Grid columns={columns} />
                        <TodayLine left={todayLeft} />
                        <div className="absolute top-1/2 h-5 -translate-y-1/2 overflow-hidden rounded-md shadow-sm ring-1 ring-black/10"
                             style={{ ...pos, background: p.color }}
                             title={`${p.label}: ${fmt(p.start_date)} – ${fmt(p.end_date)}, ${p.progress}% done`}>
                          {/* Progress inside the bar rather than beside it, so the
                              bar reads as one object at a glance. */}
                          <div className="h-full bg-black/25"
                               style={{ width: `${100 - p.progress}%`, marginLeft: `${p.progress}%` }} />
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Week rows */}
                  {isOpen && p.weeks.map((w) => {
                    const wp = place(data.span_start, data.span_days, w.start_date, w.end_date);
                    return (
                      <div key={w.week_number}
                           className={`flex border-t border-stroke/60 ${w.is_current ? "bg-brand-tint/40" : ""}`}>
                        <div className={`sticky left-0 z-[2] shrink-0 border-r border-stroke py-2 pl-10 pr-3 ${
                          w.is_current ? "bg-brand-tint" : "bg-surface"}`}
                             style={{ width: DETAIL_W }}>
                          <div className="flex items-center gap-2">
                            <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full"
                                  style={{ background: p.color }} />
                            <div className="min-w-0 flex-1">
                              <span className="text-xs font-medium text-ink-2">
                                Week {w.week_number}
                                <span className="ml-1 text-ink-3">(W{w.iso_week})</span>
                              </span>
                              <div className="text-[11px] text-ink-3">
                                {fmt(w.start_date)} – {fmt(w.end_date)}
                                <span className="ml-2">{w.completed_tasks}/{w.total_tasks} done</span>
                                {w.blocked_tasks > 0 && (
                                  <span className="ml-2 text-warn">{w.blocked_tasks} blocked</span>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                        <div className="relative shrink-0 py-2" style={{ width: timelineWidth }}>
                          <div className="relative h-full" style={{ width: timelineWidth }}>
                            <Grid columns={columns} />
                            <TodayLine left={todayLeft} />
                            {w.total_tasks > 0 && (
                              <div className="absolute top-1/2 h-3.5 -translate-y-1/2 overflow-hidden rounded"
                                   style={{ ...wp, background: p.color, opacity: 0.55 }}
                                   title={`Week ${w.week_number}: ${w.completed_tasks} of ${w.total_tasks} done${
                                     w.titles.length ? `\n${w.titles.join("\n")}` : ""}`}>
                                <div className="h-full bg-white/45"
                                     style={{ width: `${100 - w.progress}%`, marginLeft: `${w.progress}%` }} />
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                  {isOpen && p.weeks_trimmed && (
                    <p className="border-t border-stroke/60 py-1.5 pl-10 text-[11px] text-ink-3">
                      Only the first {p.weeks.length} weeks are shown.
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The column rules behind the bars. */
function Grid({ columns }: { columns: { left: number }[] }) {
  return (
    <>
      {columns.map((c, i) => (
        <span key={i} aria-hidden
              className="absolute inset-y-0 w-px bg-stroke/50"
              style={{ left: `${c.left}%` }} />
      ))}
    </>
  );
}

function TodayLine({ left }: { left: number }) {
  if (left < 0 || left > 100) return null;
  return (
    <span aria-hidden className="absolute inset-y-0 z-[1] w-0.5 bg-bad/70"
          style={{ left: `${left}%` }} title="Today" />
  );
}
