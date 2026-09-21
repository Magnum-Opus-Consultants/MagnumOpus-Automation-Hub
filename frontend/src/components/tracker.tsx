"use client";

/**
 * Shared pieces for the Project Tracker: types, date maths, time roll-ups and
 * the small presentational bits. Split out of page.tsx to keep that file about
 * layout rather than arithmetic.
 */
import { Icon } from "@/components/Sidebar";

export type Task = {
  id: number; title: string; description: string; status: string; priority: string;
  project_name: string; list_name: string; company: string; company_display: string;
  parent: number | null;
  start_date: string | null; end_date: string | null;
  start_time: string | null; end_time: string | null;
  // Set while a timer is running on this task; null when it is not.
  timer_started_at?: string | null;
  // Who it belongs to. Empty means unassigned, which the workload view
  // reports as its own row rather than hiding.
  assignees?: { id: number; name: string }[];
  estimated_hours: number | null; actual_hours: number | null;
  duration_days: number | null;
  created_at: string | null; updated_at: string | null;
};
export type Choice = [string, string];
export type Payload = {
  tasks: Task[]; counts: Record<string, number>; projects: string[];
  lists: Record<string, string[]>;
  statuses: Choice[]; priorities: Choice[]; companies: Choice[]; total: number;
  /** Everyone a task can be assigned to. */
  people?: { id: number; name: string; username?: string }[];
};

export const BUCKETS = ["backlog", "todo", "in_progress", "review", "done"] as const;

export const STATE_DOT: Record<string, string> = {
  backlog: "bg-ink-3", todo: "bg-infox", in_progress: "bg-brand",
  review: "bg-warnx", done: "bg-good",
};
export const PRIORITY_STRIP: Record<string, string> = {
  critical: "bg-bad", high: "bg-warnx", medium: "bg-infox", low: "bg-ink-3",
};
export const PRIORITY_TEXT: Record<string, string> = {
  critical: "text-bad", high: "text-warnx", medium: "text-infox", low: "text-ink-3",
};
export const PRIORITY_ORDER: Record<string, number> = {
  critical: 0, high: 1, medium: 2, low: 3,
};
export const STATUS_ORDER: Record<string, number> = {
  in_progress: 0, review: 1, todo: 2, backlog: 3, done: 4,
};

export const NO_PROJECT = "No project";
export const NO_LIST = "General";

// ── dates ───────────────────────────────────────────────────────────────────
const DAY_MS = 86_400_000;
export const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];
export const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Parse "YYYY-MM-DD" as a local date, avoiding the UTC shift `new Date(s)` applies. */
export function parseISO(s: string | null): Date | null {
  if (!s) return null;
  const [y, m, d] = s.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}
export function toISO(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
export function addDays(d: Date, n: number) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
export function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}
export function dayDiff(a: Date, b: Date) {
  return Math.round((startOfDay(b).getTime() - startOfDay(a).getTime()) / DAY_MS);
}
/** Weeks (Mon-first) covering the whole month. */
export function monthMatrix(year: number, month: number) {
  const first = new Date(year, month, 1);
  const lead = (first.getDay() + 6) % 7;
  const start = addDays(first, -lead);
  const weeks: Date[][] = [];
  for (let w = 0; w < 6; w++) {
    const row = Array.from({ length: 7 }, (_, i) => addDays(start, w * 7 + i));
    weeks.push(row);
    if (w >= 4 && addDays(row[6], 1).getMonth() !== month) break;
  }
  return weeks;
}
export function shortDate(iso: string | null) {
  const d = parseISO(iso);
  return d ? `${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}` : "";
}
/**
 * "3 Sep → 9 Sep · 7 days", or a single date when there is no range.
 *
 * A time is appended to the date it belongs to when one is set - "3 Sep 09:00
 * → 9 Sep 17:30" - because a task booked to an hour should say so. Tasks
 * without times read exactly as they did before.
 */
export function periodLabel(t: Task) {
  const s = parseISO(t.start_date);
  const e = parseISO(t.end_date);
  if (!s && !e) return "";
  const at = (date: string, time?: string | null) =>
    time ? `${date} ${time}` : date;
  if (s && e && t.start_date !== t.end_date) {
    return `${at(shortDate(t.start_date), t.start_time)} → `
         + `${at(shortDate(t.end_date), t.end_time)} · `
         + `${t.duration_days ?? dayDiff(s, e) + 1} days`;
  }
  const only = shortDate(t.end_date ?? t.start_date);
  // One day with both times is a span within that day, not a whole day.
  if (t.start_time && t.end_time) {
    return `${only} · ${t.start_time} → ${t.end_time}`;
  }
  return `${at(only, t.start_time ?? t.end_time)} · 1 day`;
}

export function labelOf(choices: Choice[], key: string) {
  return choices.find(([k]) => k === key)?.[1] ?? key;
}
export function fmtHours(n: number | null | undefined) {
  if (n == null) return "—";
  return Number.isInteger(n) ? `${n}h` : `${n.toFixed(1)}h`;
}

// ── time roll-ups ───────────────────────────────────────────────────────────
export type Totals = { est: number; act: number; hasEst: boolean; hasAct: boolean };

/**
 * Estimated / actual hours for a task including its subtasks.
 *
 * A parent's own figure wins when set - that is the quote for the whole piece
 * of work. Only when it is blank do the children add up, so a parent with an
 * estimate is never double-counted against its own subtasks.
 */
export function rollUp(t: Task, kids: Task[]): Totals {
  const kidEst = kids.reduce((s, k) => s + (k.estimated_hours ?? 0), 0);
  const kidAct = kids.reduce((s, k) => s + (k.actual_hours ?? 0), 0);
  const est = t.estimated_hours ?? kidEst;
  const act = t.actual_hours ?? kidAct;
  return {
    est, act,
    hasEst: t.estimated_hours != null || kids.some((k) => k.estimated_hours != null),
    hasAct: t.actual_hours != null || kids.some((k) => k.actual_hours != null),
  };
}

export function sumTotals(list: Totals[]): Totals {
  return list.reduce<Totals>((a, b) => ({
    est: a.est + b.est, act: a.act + b.act,
    hasEst: a.hasEst || b.hasEst, hasAct: a.hasAct || b.hasAct,
  }), { est: 0, act: 0, hasEst: false, hasAct: false });
}

// ── presentational ──────────────────────────────────────────────────────────

/** Due-date chip. Overdue and today read differently, as Planner does. */
export function DueChip({ date, done }: { date: string | null; done: boolean }) {
  const d = parseISO(date);
  if (!d) return null;
  const diff = dayDiff(new Date(), d);
  const tone = done ? "bg-subtle text-ink-3"
    : diff < 0 ? "bg-bad-bg text-bad"
    : diff === 0 ? "bg-warnx-bg text-warnx"
    : diff <= 3 ? "bg-infox-bg text-infox"
    : "bg-subtle text-ink-2";
  // A completed task is never "late" - once it is done the date is just a date.
  const text = done ? shortDate(date)
    : diff === 0 ? "Due today"
    : diff === -1 ? "1 day late"
    : diff < 0 ? `${Math.abs(diff)} days late`
    : diff === 1 ? "Due tomorrow"
    : shortDate(date);
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ${tone}`}>
      <Icon name="calendar" className="h-3 w-3" />
      {text}
    </span>
  );
}

/**
 * Estimated vs actual, ClickUp-style. Over-run is what matters for planning,
 * so it is the only state that gets a colour.
 */
export function TimeChip({ totals, compact = false }: { totals: Totals; compact?: boolean }) {
  const { est, act, hasEst, hasAct } = totals;
  if (!hasEst && !hasAct) return null;
  const over = hasEst && hasAct && act > est;
  const under = hasEst && hasAct && act > 0 && act <= est;
  const tone = over ? "bg-bad-bg text-bad" : under ? "bg-good-bg text-good" : "bg-subtle text-ink-2";
  const pct = hasEst && est > 0 ? Math.round((act / est) * 100) : null;
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ${tone}`}
          title={`Estimated ${fmtHours(hasEst ? est : null)} · actual ${fmtHours(hasAct ? act : null)}${
            pct != null ? ` · ${pct}% of estimate` : ""}`}>
      <Icon name="clock" className="h-3 w-3" />
      {hasAct ? fmtHours(act) : "0h"}
      <span className="opacity-70">/ {hasEst ? fmtHours(est) : "—"}</span>
      {!compact && over && <span className="font-semibold">+{fmtHours(Math.round((act - est) * 10) / 10)}</span>}
    </span>
  );
}

/** Actual / estimated hours as a compact block. Renders nothing when neither
 *  figure exists, since "— / —" is just noise. */
export function HoursBlock({ totals, title }: { totals: Totals; title?: string }) {
  if (!totals.hasEst && !totals.hasAct) return null;
  const over = totals.hasEst && totals.hasAct && totals.act > totals.est;
  return (
    <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-medium ${
      over ? "bg-bad-bg text-bad" : "bg-subtle text-ink-2"
    }`} title={title}>
      {fmtHours(totals.hasAct ? totals.act : null)} / {fmtHours(totals.hasEst ? totals.est : null)}
    </span>
  );
}

/** Thin progress bar: share of subtasks completed. */
export function ProgressBar({ done, total }: { done: number; total: number }) {
  if (total === 0) return null;
  const pct = Math.round((done / total) * 100);
  return (
    <span className="flex items-center gap-1.5">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-subtle">
        <span className={`block h-full rounded-full transition-all ${pct === 100 ? "bg-good" : "bg-brand"}`}
              style={{ width: `${pct}%` }} />
      </span>
      <span className="text-[11px] text-ink-3">{done}/{total}</span>
    </span>
  );
}
