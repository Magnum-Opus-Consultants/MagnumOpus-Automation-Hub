"use client";

/**
 * One project, with everything about it in one place: who it is for, its
 * tasks, how it is tracking, its website and what has happened on it.
 *
 * The sidebar lists each project with these sections nested underneath it, so
 * a client is somewhere you go rather than a filter on the board. The tabs at
 * the top repeat that navigation for when the rail is collapsed or off-screen.
 */
import {
  Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode,
} from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  canAccess, Icon, PROJECT_SECTIONS, projectHref, type Me,
} from "@/components/Sidebar";
import {
  AppShell, Section, StatTile, Badge, Button, EmptyState, Modal, Pill, Row, ConfirmDialog,
  TextInput, AreaInput, SelectInput, relativeTime, expiryTone, expiryLabel,
  type Tone,
} from "@/components/ui";
import { loadProject, peek, peekProject, put } from "@/lib/page-cache";
import {
  STATE_DOT, statusTone, PRIORITY_TEXT, PRIORITY_ORDER, NO_LIST,
  fmtHours, DueChip, parseISO, dayDiff, labelOf, toISO, addDays, shortDate,
  type Task, type Payload, type Choice,
} from "@/components/tracker";
import { VizTokens, ChartCard, Donut, StackedBars, SERIES } from "@/components/charts";
import {
  TrackerBoard, TRACKER_VIEWS, TRACKER_VIEW_ICON, type TrackerView,
} from "@/components/tracker-board";
import { ServerConsole } from "@/components/server-console";
import { Markdown } from "@/components/markdown";

type Opt = { value: string; label: string };
type Project = {
  name: string; client: string; client_email: string; client_contact: string;
  status: string; status_display: string; priority: string; priority_display: string;
  description: string; start_date: string | null; end_date: string | null;
  quoted_hours: number | null; sprint: string; is_automated: boolean;
  website_url: string; demo_url: string;
  hosting: string; tech_stack: string; website_notes: string;
  color: string; icon: string; logo_url: string; workspace: string;
  assigned: { id: number; name: string }[];
};
type Agreement = {
  id: number; client: string; tier: string; tier_display: string;
  response_hours: number | null; resolution_hours: number | null;
  support_window: string; hosting_provider: string; hosting_notes: string;
  environment_url: string; backup_schedule: string;
  renewal_date: string | null; renews_in_days: number | null; is_active: boolean;
};
type Repo = {
  id: number; name: string; description: string; remote_url: string;
  provider: string; provider_display: string; default_branch: string;
  company: string; project_name: string;
};
type Detail = {
  project: Project; agreements: Agreement[]; repositories: Repo[];
  statuses: Opt[]; priorities: Opt[];
};
/** Whether each site can be shown inside the page; null when not set. */
type SiteCheck = Record<"live" | "demo", {
  url: string; reachable: boolean; embeddable: boolean; reason: string;
} | null>;
type Metrics = {
  totals: {
    tasks: number; tasks_open: number; tasks_done: number; tasks_blocked: number;
    tasks_overdue: number; tasks_due_next_7_days: number; completion_rate: number;
    estimated_hours: number | null; actual_hours: number | null;
    hours_variance: number | null;
  };
  tasks_by_status: Record<string, number>;
  tasks_by_stream: Record<string, { done: number; open: number }>;
  projects: { accepted_rate: number; tasks_accepted: number;
              avg_days_to_complete: number | null }[];
  overdue: { title: string; due: string | null; status: string; days_late: number | null }[];
  blocked: { title: string; status: string; status_display: string }[];
  people: { user: string; changes: number }[];
};
type Activity = { id: number; kind: string; summary: string; task: string; when: string };
type TaskRow = Task & { stream?: string };

/* Finished in the sense the reporting means it: the work stopped, whether or
   not the client has signed it off. Cancelled is neither open nor finished. */
const FINISHED = new Set(["done", "review_pending", "discrepancy"]);
const isClosed = (t: Task) => FINISHED.has(t.status) || t.status === "cancelled";

/* Ten statuses are too many slices for one ring, so the chart groups them by
   what the work is doing - the same grouping the board's status menu uses. */
const STATUS_GROUPS = [
  { label: "Not started", statuses: ["backlog", "todo"] },
  { label: "Working", statuses: ["in_progress", "in_progress_guidance", "review"] },
  { label: "Waiting", statuses: ["on_hold", "review_pending", "discrepancy"] },
  { label: "Closed", statuses: ["done", "cancelled"] },
];

const STREAM_LABEL: Record<string, string> = {
  web: "WEB", app: "APP", api: "API", support: "Support",
  internal: "Internal / Admin", "": "Not labelled",
};

const TASK_FILTERS = ["Open", "All", "Overdue", "Finished"] as const;

type TaskView = "List" | TrackerView;
const TASK_VIEWS: TaskView[] = ["List", ...TRACKER_VIEWS];
const TASK_VIEW_KEY = "sentinel-project-task-view";
const toTaskView = (raw: string | null | undefined): TaskView | null =>
  TASK_VIEWS.find((v) => v.toLowerCase() === (raw ?? "").toLowerCase()) ?? null;

/** A project's task view, as a link. `task` opens that task on the board. */
function taskViewHref(name: string, view: TaskView, task?: number) {
  return `${projectHref(name, "tasks")}&view=${view.toLowerCase()}${task ? `&task=${task}` : ""}`;
}
type TaskFilter = (typeof TASK_FILTERS)[number];

function projectTone(status: string): Tone {
  return status === "completed" ? "good"
    : status === "cancelled" ? "bad"
    : status.startsWith("completed") ? "info"
    : status === "on_hold" || status === "in_progress_guidance" ? "warn"
    : "neutral";
}

/** The route param, decoded once. Next may hand it over encoded or not. */
function decodeParam(raw: string | string[] | undefined) {
  const s = Array.isArray(raw) ? raw.join("/") : raw ?? "";
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

function fmtDate(iso: string | null) {
  const d = parseISO(iso);
  return d ? d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
}

function isOverdue(t: Task) {
  const d = parseISO(t.end_date);
  return !!d && !isClosed(t) && dayDiff(new Date(), d) < 0;
}

function StatusChip({ status, label }: { status: string; label: string }) {
  const tone = statusTone(status);
  return (
    <span className="max-w-full truncate rounded px-1.5 py-0.5 text-[11px] font-medium"
          title={label} style={{ background: tone.bg, color: tone.fg }}>
      {label}
    </span>
  );
}

function Initials({ people }: { people?: { id: number; name: string }[] }) {
  if (!people?.length) return null;
  return (
    <span className="flex shrink-0 -space-x-1.5" title={people.map((p) => p.name).join(", ")}>
      {people.slice(0, 3).map((p) => (
        <span key={p.id}
              className="flex h-5 w-5 items-center justify-center rounded-full bg-brand text-[9px] font-semibold text-white ring-2 ring-surface">
          {p.name.slice(0, 2).toUpperCase()}
        </span>
      ))}
    </span>
  );
}

function ExternalLink({ href }: { href: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer"
       className="inline-flex items-center gap-1 break-all text-brand hover:underline">
      {href.replace(/^https?:\/\//, "").replace(/\/$/, "")}
      <Icon name="link" className="h-3.5 w-3.5 shrink-0" />
    </a>
  );
}

export default function ProjectPage() {
  // Keyed by project so each one starts from its own remembered data rather
  // than showing the last project's while the next one loads.
  const params = useParams<{ name: string }>();
  return (
    <Suspense fallback={<div className="p-6 text-sm text-ink-2">Loading project…</div>}>
      <ProjectInner key={params?.name ?? ""} />
    </Suspense>
  );
}

function ProjectInner() {
  const params = useParams<{ name: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const name = decodeParam(params?.name);
  const tabParam = search?.get("tab") ?? "overview";
  const tab = PROJECT_SECTIONS.some((s) => s.key === tabParam) ? tabParam : "overview";

  // Start from what this tab already loaded for the project (an earlier
  // visit, or a hover in the sidebar) so it opens at once; load() then
  // refreshes it in the background.
  const [me, setMe] = useState<Me | null>(() => peek<Me>("me") ?? null);
  const [cached] = useState(() => peekProject(name));
  const [detail, setDetail] = useState<Detail | null>(
    () => (cached && cached.detail !== "missing" ? (cached.detail as Detail) : null));
  const [missing, setMissing] = useState(() => cached?.detail === "missing");
  const [payload, setPayload] = useState<Payload | null>(() => (cached?.tasks as Payload) ?? null);
  const [metrics, setMetrics] = useState<Metrics | null>(() => (cached?.metrics as Metrics) ?? null);
  const [activity, setActivity] = useState<Activity[] | null>(
    () => (cached ? (cached.activity as Activity[]) : null));
  const [editing, setEditing] = useState<Project | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [sites, setSites] = useState<SiteCheck | null>(null);
  const viewParam = toTaskView(search?.get("view"));
  const [storedView, setStoredView] = useState<TaskView | null>(null);
  useEffect(() => {
    try {
      // Read after mount: the page is rendered on the server first.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStoredView(toTaskView(localStorage.getItem(TASK_VIEW_KEY)));
    } catch {
      // No storage - the board is the default.
    }
  }, []);
  useEffect(() => {
    if (!viewParam) return;
    try {
      localStorage.setItem(TASK_VIEW_KEY, viewParam);
    } catch {
      // Not remembered; nothing else depends on it.
    }
  }, [viewParam]);
  const taskView: TaskView = viewParam ?? storedView ?? "Board";

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        put("me", m);
        setMe(m);
        if (!canAccess(m, "tasks")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
  }, []);

  const load = useCallback(async () => {
    const b = await loadProject(name);
    setMissing(b.detail === "missing");
    setDetail(b.detail && b.detail !== "missing" ? (b.detail as Detail) : null);
    setPayload(b.tasks as Payload);
    setMetrics(b.metrics as Metrics);
    setActivity(b.activity as Activity[]);
  }, [name]);

  useEffect(() => {
    // Fetching on mount and whenever the project in the URL changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // Whether the sites can be shown inside the page is asked of the server,
  // since a blocked frame just stays blank. Re-asked when either URL changes.
  const liveUrl = detail?.project.website_url ?? "";
  const demoUrl = detail?.project.demo_url ?? "";
  useEffect(() => {
    if (!liveUrl && !demoUrl) {
      // Nothing to check: clearing the last project's answer is the point.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSites(null);
      return;
    }
    let stale = false;
    fetch(`/api/projects/${encodeURIComponent(name)}/site-check`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!stale) setSites(d); })
      .catch(() => { if (!stale) setSites(null); });
    return () => { stale = true; };
  }, [name, liveUrl, demoUrl]);

  /** Save fields on the project record. True when it went through. */
  async function patch(body: Partial<Project>) {
    setSaving(true);
    setError("");
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(name)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(d.detail || "Could not save.");
        return false;
      }
      setNote(d.changed?.length
        ? `Saved ${d.changed.length} change${d.changed.length === 1 ? "" : "s"}.`
        : "Nothing changed.");
      await load();
      return true;
    } finally {
      setSaving(false);
    }
  }

  async function saveDetails() {
    if (!editing) return;
    const ok = await patch({
      client: editing.client, client_email: editing.client_email,
      client_contact: editing.client_contact, description: editing.description,
      status: editing.status, priority: editing.priority, sprint: editing.sprint,
      start_date: editing.start_date, end_date: editing.end_date,
      quoted_hours: editing.quoted_hours,
    });
    if (ok) setEditing(null);
  }

  const p = detail?.project;
  const tasks = useMemo(() => (payload?.tasks ?? []) as TaskRow[], [payload]);
  const openCount = tasks.filter((t) => t.parent == null && !isClosed(t)).length;

  if (missing) {
    return (
      <AppShell active="Projects" me={me}>
        <EmptyState icon="folder" title={`No project called "${name}"`}
                    hint="It may have been renamed or deleted."
                    action={<Button onClick={() => router.push("/tasks")}>Back to Projects</Button>} />
      </AppShell>
    );
  }

  return (
    <AppShell active="Projects" me={me} wide>
      <VizTokens />
      <nav aria-label="Breadcrumb" className="mb-2 flex items-center gap-1 text-xs text-ink-3">
        <Link href="/tasks" className="hover:text-ink">Projects</Link>
        {p?.workspace && p.workspace !== "Project Tracker" && (
          <>
            <Icon name="chevron" className="h-3 w-3 rotate-90" />
            <Link href={`/tasks?workspace=${encodeURIComponent(p.workspace)}`}
                  className="hover:text-ink">{p.workspace}</Link>
          </>
        )}
        <Icon name="chevron" className="h-3 w-3 rotate-90" />
        <span className="truncate text-ink-2">{name}</span>
      </nav>

      <header className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          {/* Only a logo someone uploaded; no stand-in icon. */}
          {p?.logo_url && (
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-subtle">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={p.logo_url} alt="" className="h-7 w-7 object-contain" />
            </span>
          )}
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold tracking-tight text-ink">{name}</h1>
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-2">
              <span>{p ? (p.client || "No client set") : "Loading…"}</span>
              {p && <Badge tone={projectTone(p.status)}>{p.status_display}</Badge>}
              {p && <span className="text-xs text-ink-3">{p.priority_display} priority</span>}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <Button icon="board"
                  onClick={() => router.push(taskViewHref(name, "Board"))}>
            Open board
          </Button>
          <Button icon="edit" disabled={!p} onClick={() => p && setEditing({ ...p })}>
            Edit project
          </Button>
        </div>
      </header>

      <div role="tablist" aria-label="Project sections"
           className="mb-4 flex gap-1 overflow-x-auto border-b border-stroke">
        {PROJECT_SECTIONS.map((s) => (
          <Link key={s.key} href={projectHref(name, s.key)} scroll={false}
                role="tab" aria-selected={tab === s.key}
                className={`-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition ${
                  tab === s.key
                    ? "border-brand text-ink"
                    : "border-transparent text-ink-2 hover:text-ink"}`}>
            <Icon name={s.icon} className="h-4 w-4" />
            {s.label}
            {s.key === "tasks" && openCount > 0 && (
              <span className="rounded bg-subtle px-1.5 text-[11px] text-ink-3">{openCount}</span>
            )}
          </Link>
        ))}
      </div>

      {note && (
        <p className="mb-3 flex items-start gap-2 rounded-lg bg-good-bg px-3 py-2 text-xs text-good">
          <Icon name="check" className="mt-px h-4 w-4 shrink-0" />
          <span className="flex-1">{note}</span>
          <button onClick={() => setNote("")} aria-label="Dismiss"
                  className="shrink-0 opacity-60 hover:opacity-100">✕</button>
        </p>
      )}

      {!p || !payload ? (
        <Section><div className="p-2 text-sm text-ink-2">Loading project…</div></Section>
      ) : tab === "tasks" ? (
        <div>
          <div role="tablist" aria-label="Task views" className="mb-3 flex w-fit rounded-lg bg-subtle p-0.5">
            {TASK_VIEWS.map((v) => (
              <Link key={v} href={taskViewHref(name, v)} scroll={false}
                    role="tab" aria-selected={taskView === v}
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-semibold transition focus-ring ${
                      taskView === v ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}>
                <Icon name={v === "List" ? "tasks" : TRACKER_VIEW_ICON[v]} className="h-4 w-4" />
                {v}
              </Link>
            ))}
          </div>
          {taskView === "List" ? (
            <TasksTab name={name} payload={payload} tasks={tasks} onChange={load} />
          ) : (
            <TrackerBoard embedded={{ project: name, view: taskView, onChange: () => void load() }} />
          )}
        </div>
      ) : tab === "reporting" ? (
        <ReportingTab metrics={metrics} quoted={p.quoted_hours} />
      ) : tab === "website" ? (
        <WebsiteTab p={p} agreements={detail.agreements} sites={sites} saving={saving}
                    error={error} onSave={patch} />
      ) : tab === "feedback" ? (
        <FeedbackTab name={name} />
      ) : tab === "docs" ? (
        <DocsTab name={name} />
      ) : tab === "server" ? (
        <ServerTab name={name} />
      ) : tab === "credentials" ? (
        <CredentialsTab name={name} />
      ) : tab === "github" ? (
        <GitHubTab name={name} repos={detail.repositories} onChange={load} />
      ) : tab === "activity" ? (
        <ActivityTab activity={activity} />
      ) : (
        <OverviewTab p={p} tasks={tasks} activity={activity} statuses={payload.statuses}
                     repos={detail.repositories} sites={sites} saving={saving}
                     error={error} onSave={patch} />
      )}

      {editing && detail && (
        <Modal title={`Edit ${editing.name}`} wide onClose={() => { setEditing(null); setError(""); }}
               footer={
                 <>
                   <Button onClick={() => { setEditing(null); setError(""); }}>Cancel</Button>
                   <Button variant="primary" spinning={saving} disabled={saving}
                           onClick={() => void saveDetails()}>
                     Save project
                   </Button>
                 </>
               }>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <SelectInput label="Status" value={editing.status} options={detail.statuses}
                         onChange={(v) => setEditing({ ...editing, status: v })} />
            <SelectInput label="Priority" value={editing.priority} options={detail.priorities}
                         onChange={(v) => setEditing({ ...editing, priority: v })} />
            <TextInput label="Client" value={editing.client}
                       onChange={(v) => setEditing({ ...editing, client: v })} />
            <TextInput label="Client contact" value={editing.client_contact}
                       onChange={(v) => setEditing({ ...editing, client_contact: v })} />
            <TextInput label="Client email" value={editing.client_email}
                       hint="Where a client report would be sent."
                       onChange={(v) => setEditing({ ...editing, client_email: v })} />
            <TextInput label="Sprint" value={editing.sprint}
                       onChange={(v) => setEditing({ ...editing, sprint: v })} />
            <TextInput label="Start date" type="date" value={editing.start_date ?? ""}
                       onChange={(v) => setEditing({ ...editing, start_date: v || null })} />
            <TextInput label="Due date" type="date" value={editing.end_date ?? ""}
                       onChange={(v) => setEditing({ ...editing, end_date: v || null })} />
            <TextInput label="Quoted hours"
                       value={editing.quoted_hours === null ? "" : String(editing.quoted_hours)}
                       hint="What was sold, to measure actuals against."
                       onChange={(v) => setEditing({
                         ...editing, quoted_hours: v.trim() === "" ? null : Number(v) })} />
            <div className="sm:col-span-2">
              <AreaInput label="Description" rows={3} value={editing.description}
                         onChange={(v) => setEditing({ ...editing, description: v })} />
            </div>
          </div>
          {error && <p className="mt-3 text-xs text-bad">{error}</p>}
        </Modal>
      )}
    </AppShell>
  );
}

/* ── Overview ─────────────────────────────────────────────────────────────── */

function OverviewTab({ p, tasks, activity, statuses, repos, sites, saving, error, onSave }: {
  p: Project; tasks: TaskRow[]; activity: Activity[] | null; statuses: Choice[];
  repos: Repo[]; sites: SiteCheck | null; saving: boolean; error: string;
  onSave: (body: Partial<Project>) => Promise<boolean>;
}) {
  const top = useMemo(() => tasks.filter((x) => x.parent == null), [tasks]);

  // Counted from top-level tasks, the same way the Tasks tab and the board
  // count them; hours include subtasks, since that is where time is logged.
  const c = useMemo(() => {
    const open = top.filter((x) => !isClosed(x));
    const now = new Date();
    return {
      total: top.length,
      open: open.length,
      finished: top.filter((x) => FINISHED.has(x.status)).length,
      overdue: open.filter(isOverdue).length,
      dueWeek: open.filter((x) => {
        const d = parseISO(x.end_date);
        const n = d ? dayDiff(now, d) : -1;
        return n >= 0 && n <= 7;
      }).length,
      est: tasks.reduce((n, x) => n + (x.estimated_hours ?? 0), 0),
      act: tasks.reduce((n, x) => n + (x.actual_hours ?? 0), 0),
    };
  }, [top, tasks]);

  const lists = useMemo(() => {
    const by = new Map<string, { total: number; done: number; open: number }>();
    for (const x of top) {
      const key = x.list_name || NO_LIST;
      const e = by.get(key) ?? { total: 0, done: 0, open: 0 };
      e.total += 1;
      if (isClosed(x)) e.done += 1; else e.open += 1;
      by.set(key, e);
    }
    return [...by.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [top]);

  // Late work first, then whatever is due soonest; undated work last.
  const upcoming = top.filter((x) => !isClosed(x)).sort((a, b) => {
    const da = parseISO(a.end_date)?.getTime() ?? Infinity;
    const db = parseISO(b.end_date)?.getTime() ?? Infinity;
    return da - db || (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9);
  }).slice(0, 6);

  const hoursHint = p.quoted_hours
    ? `of ${fmtHours(p.quoted_hours)} quoted`
    : c.est ? `of ${fmtHours(c.est)} estimated` : undefined;
  const overQuote = !!p.quoted_hours && c.act > p.quoted_hours;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Open tasks" icon="tasks" value={c.open}
                  hint={`${c.dueWeek} due this week`} />
        <StatTile label="Finished" icon="check" tone="good"
                  value={c.total ? `${Math.round((c.finished / c.total) * 100)}%` : "—"}
                  hint={`${c.finished} of ${c.total}`} />
        <StatTile label="Overdue" icon="alert" value={c.overdue}
                  tone={c.overdue ? "bad" : "good"}
                  hint={c.overdue ? "past their due date" : "nothing late"} />
        <StatTile label="Hours logged" icon="clock" tone={overQuote ? "bad" : "neutral"}
                  value={fmtHours(c.act)} hint={hoursHint} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Section title="Coming up"
                   right={<Link href={projectHref(p.name, "tasks")}
                                className="text-xs font-medium text-brand hover:underline">All tasks</Link>}>
            {upcoming.length === 0 ? (
              <p className="text-sm text-ink-3">
                {top.length === 0 ? "No tasks yet." : "Nothing open. Every task here is finished."}
              </p>
            ) : (
              <ul className="-my-2 divide-y divide-stroke">
                {upcoming.map((x) => (
                  <li key={x.id}>
                    <Link href={taskViewHref(p.name, "Board", x.id)}
                          className="flex items-center gap-3 py-2 text-sm hover:text-brand">
                      <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${STATE_DOT[x.status] ?? "bg-ink-3"}`} />
                      <span className="min-w-0 flex-1 truncate text-ink">{x.title}</span>
                      <span className="hidden text-xs text-ink-3 sm:inline">{x.list_name || NO_LIST}</span>
                      <StatusChip status={x.status} label={labelOf(statuses, x.status)} />
                      <DueChip date={x.end_date} done={false} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Progress by list">
            {lists.length === 0 ? (
              <p className="text-sm text-ink-3">No tasks yet. Add some from the Tasks tab.</p>
            ) : (
              <ul className="space-y-2.5">
                {lists.map(([list, e]) => (
                  <li key={list} className="flex items-center gap-3 text-sm">
                    <span className="w-44 shrink-0 truncate text-ink">{list}</span>
                    <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-subtle">
                      <span className={`block h-full rounded-full ${e.done === e.total ? "bg-good" : "bg-brand"}`}
                            style={{ width: `${Math.round((e.done / e.total) * 100)}%` }} />
                    </span>
                    <span className="w-24 shrink-0 text-right text-xs tabular-nums text-ink-3">
                      {e.done}/{e.total} finished
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {p.description && (
            <Section title="About this project">
              <p className="whitespace-pre-wrap text-sm text-ink-2">{p.description}</p>
            </Section>
          )}
        </div>

        <div className="space-y-4">
          <Section title="Website"
                   right={<Link href={projectHref(p.name, "website")}
                                className="text-xs font-medium text-brand hover:underline">Preview</Link>}>
            {p.website_url || p.demo_url ? (
              <div className="space-y-3 text-sm">
                {p.website_url && (
                  <Link href={projectHref(p.name, "website")} title="Open the preview"
                        className="block overflow-hidden rounded-lg ring-1 ring-stroke transition hover:ring-brand">
                    <SiteFrame url={p.website_url} check={sites?.live} thumbnail />
                  </Link>
                )}
                {p.website_url && <p><span className="text-ink-3">Live </span><ExternalLink href={p.website_url} /></p>}
                {p.demo_url && <p><span className="text-ink-3">Demo </span><ExternalLink href={p.demo_url} /></p>}
                {repos.length > 0 && (
                  <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <Icon name="git" className="h-3.5 w-3.5 text-ink-3" />
                    {repos.map((r) => (
                      <a key={r.id} href={r.remote_url} target="_blank" rel="noreferrer"
                         className="text-brand hover:underline">{r.name}</a>
                    ))}
                  </p>
                )}
              </div>
            ) : (
              <SiteUrlForm saving={saving} error={error} onSave={onSave} />
            )}
          </Section>

          <Section title="Details">
            <div className="-my-2">
              <Row k="Client" v={p.client || "—"} />
              <Row k="Contact" v={p.client_contact} />
              <Row k="Client email" v={p.client_email} />
              <Row k="Sprint" v={p.sprint} />
              <Row k="Start" v={fmtDate(p.start_date)} />
              <Row k="Due" v={fmtDate(p.end_date)} />
              <Row k="Quoted" v={p.quoted_hours ? fmtHours(p.quoted_hours) : ""} />
              <Row k="Team" v={p.assigned.map((a) => a.name).join(", ")} />
            </div>
          </Section>

          <Section title="Latest activity"
                   right={<Link href={projectHref(p.name, "activity")}
                                className="text-xs font-medium text-brand hover:underline">All activity</Link>}>
            {!activity ? (
              <p className="text-sm text-ink-3">Loading…</p>
            ) : activity.length === 0 ? (
              <p className="text-sm text-ink-3">Nothing recorded yet.</p>
            ) : (
              <ul className="space-y-2">
                {activity.slice(0, 5).map((a) => (
                  <li key={a.id} className="text-xs">
                    <p className="text-ink-2">{a.summary}{a.task && <span className="text-ink-3"> · {a.task}</span>}</p>
                    <p className="text-ink-3">{relativeTime(a.when)}</p>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}

/* ── Tasks ────────────────────────────────────────────────────────────────── */

/* Laid out as ClickUp's list view: each list is a table with the same columns,
   and a task is added in place - an inline row at the foot of the list, or
   under a task for a subtask - rather than through a form somewhere else. */

type Person = { id: number; name: string };
type Draft = { title: string; status: string; assignees: number[]; due: string; priority: string };

/* Shared column widths, so the header, the rows and the add row line up. */
const COL = {
  assignee: "hidden w-24 shrink-0 md:flex",
  due: "flex w-28 shrink-0",
  priority: "hidden w-24 shrink-0 md:flex",
  status: "flex w-28 shrink-0 justify-end lg:w-44",
};

/** A menu that opens under its button and closes on a click elsewhere or Esc. */
function Dropdown({ label, button, children, align = "left", buttonClass = "" }: {
  label: string; button: ReactNode; children: (close: () => void) => ReactNode;
  align?: "left" | "right"; buttonClass?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    // Captured, so Esc closes the menu without also closing the add row.
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); setOpen(false); }
    };
    window.addEventListener("pointerdown", away, true);
    window.addEventListener("keydown", key, true);
    return () => {
      window.removeEventListener("pointerdown", away, true);
      window.removeEventListener("keydown", key, true);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button type="button" aria-label={label} title={label} aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
              className={`flex items-center rounded transition focus-ring ${buttonClass}`}>
        {button}
      </button>
      {open && (
        <div role="menu"
             className={`absolute top-full z-30 mt-1 min-w-48 rounded-lg bg-surface py-1 shadow-2xl ring-panel ${
               align === "right" ? "right-0" : "left-0"}`}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

function MenuRow({ onClick, active, children }: {
  onClick: () => void; active?: boolean; children: ReactNode;
}) {
  return (
    <button type="button" role="menuitem" onClick={onClick}
            className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition hover:bg-subtle ${
              active ? "font-semibold text-ink" : "text-ink-2"}`}>
      {children}
    </button>
  );
}

/** ClickUp's status circle: hollow while open, filled once finished. */
function StatusDot({ status, size = "h-3.5 w-3.5" }: { status: string; size?: string }) {
  const tone = statusTone(status);
  const filled = FINISHED.has(status) || status === "cancelled";
  return (
    <span aria-hidden className={`${size} shrink-0 rounded-full border-2`}
          style={{ borderColor: tone.fg, background: filled ? tone.fg : "transparent" }} />
  );
}

function StatusPicker({ value, statuses, onPick, size }: {
  value: string; statuses: Choice[]; onPick: (s: string) => void; size?: string;
}) {
  return (
    <Dropdown label={`Status: ${labelOf(statuses, value)}`} buttonClass="h-5 w-5 justify-center hover:bg-subtle"
              button={<StatusDot status={value} size={size} />}>
      {(close) => statuses.map(([v, l]) => (
        <MenuRow key={v} active={v === value} onClick={() => { onPick(v); close(); }}>
          <StatusDot status={v} /> {l}
        </MenuRow>
      ))}
    </Dropdown>
  );
}

function Flag({ priority, label }: { priority: string; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${PRIORITY_TEXT[priority] ?? "text-ink-3"}`}>
      <Icon name="flag" className="h-3.5 w-3.5" /> {label}
    </span>
  );
}

/** The inline add row. Enter saves and leaves a fresh row for the next task. */
function QuickAdd({ people, statuses, priorities, sub = false, onSave, onCancel }: {
  people: Person[]; statuses: Choice[]; priorities: Choice[]; sub?: boolean;
  onSave: (d: Draft) => Promise<string | null>; onCancel: () => void;
}) {
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState("todo");
  const [assignees, setAssignees] = useState<number[]>([]);
  const [due, setDue] = useState("");
  const [priority, setPriority] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const chosen = people.filter((p) => assignees.includes(p.id));
  const iconBtn = "h-7 min-w-7 justify-center gap-1 px-1.5 text-ink-3 hover:bg-subtle hover:text-ink";

  async function save() {
    if (!title.trim() || busy) return;
    setBusy(true);
    setError("");
    const problem = await onSave({ title: title.trim(), status, assignees, due, priority });
    setBusy(false);
    if (problem) {
      setError(problem);
      return;
    }
    setTitle("");
    setAssignees([]);
    setDue("");
    setPriority("");
    input.current?.focus();
  }

  const quick = [["Today", 0], ["Tomorrow", 1], ["Next week", 7], ["In two weeks", 14]] as const;

  return (
    <div className={`border-t border-stroke py-1.5 pr-3 ${sub ? "pl-14" : "pl-10"}`}>
      <div className="flex items-center gap-2 rounded-md bg-surface px-2 py-1 ring-2 ring-brand">
        <StatusPicker value={status} statuses={statuses} onPick={setStatus} />
        <input ref={input} autoFocus value={title}
               onChange={(e) => { setTitle(e.target.value); setError(""); }}
               onKeyDown={(e) => {
                 if (e.key === "Enter") { e.preventDefault(); void save(); }
                 if (e.key === "Escape") onCancel();
               }}
               placeholder={sub ? "Subtask Name" : "Task Name"}
               aria-label={sub ? "New subtask name" : "New task name"}
               className="h-7 min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3" />

        <Dropdown label="Assignee" align="right" buttonClass={iconBtn}
                  button={chosen.length ? <Initials people={chosen} /> : <Icon name="user" className="h-4 w-4" />}>
          {() => people.length === 0
            ? <p className="px-3 py-2 text-xs text-ink-3">Nobody to assign.</p>
            : people.map((p) => {
                const on = assignees.includes(p.id);
                return (
                  <MenuRow key={p.id} active={on}
                           onClick={() => setAssignees(on ? assignees.filter((x) => x !== p.id) : [...assignees, p.id])}>
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand text-[9px] font-semibold text-white">
                      {p.name.slice(0, 2).toUpperCase()}
                    </span>
                    <span className="flex-1">{p.name}</span>
                    {on && <Icon name="check" className="h-3.5 w-3.5 text-brand" />}
                  </MenuRow>
                );
              })}
        </Dropdown>

        <Dropdown label="Due date" align="right" buttonClass={iconBtn}
                  button={due
                    ? <span className="text-xs font-medium text-ink">{shortDate(due)}</span>
                    : <Icon name="calendar" className="h-4 w-4" />}>
          {(close) => (
            <>
              {quick.map(([l, n]) => (
                <MenuRow key={l} onClick={() => { setDue(toISO(addDays(new Date(), n))); close(); }}>
                  <span className="flex-1">{l}</span>
                  <span className="text-xs text-ink-3">{shortDate(toISO(addDays(new Date(), n)))}</span>
                </MenuRow>
              ))}
              <div className="border-t border-stroke px-3 py-2">
                <input type="date" value={due} aria-label="Pick a date"
                       onChange={(e) => { setDue(e.target.value); if (e.target.value) close(); }}
                       className="h-8 w-full rounded-md bg-canvas px-2 text-sm text-ink ring-control focus-ring" />
              </div>
              {due && <MenuRow onClick={() => { setDue(""); close(); }}>Clear</MenuRow>}
            </>
          )}
        </Dropdown>

        <Dropdown label="Priority" align="right" buttonClass={iconBtn}
                  button={<Icon name="flag" className={`h-4 w-4 ${priority ? PRIORITY_TEXT[priority] : ""}`} />}>
          {(close) => (
            <>
              {priorities.map(([v, l]) => (
                <MenuRow key={v} active={v === priority} onClick={() => { setPriority(v); close(); }}>
                  <Flag priority={v} label={l} />
                </MenuRow>
              ))}
              {priority && <MenuRow onClick={() => { setPriority(""); close(); }}>Clear</MenuRow>}
            </>
          )}
        </Dropdown>

        <button type="button" onClick={onCancel} aria-label="Cancel" title="Cancel (Esc)"
                className="flex h-7 w-7 items-center justify-center rounded text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring">
          <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"><path d="M5 5l10 10M15 5L5 15" /></svg>
        </button>
        <button type="button" onClick={() => void save()} disabled={busy || !title.trim()}
                className="flex h-7 items-center gap-1.5 rounded-md bg-brand px-2.5 text-xs font-semibold text-white transition hover:bg-brand-hover disabled:opacity-50 focus-ring">
          {busy ? "Saving…" : "Save"} <span aria-hidden className="opacity-80">↵</span>
        </button>
      </div>
      {error && <p className="mt-1 pl-2 text-xs text-bad">{error}</p>}
    </div>
  );
}

function TasksTab({ name, payload, tasks, onChange }: {
  name: string; payload: Payload; tasks: TaskRow[]; onChange: () => Promise<void>;
}) {
  const [filter, setFilter] = useState<TaskFilter>("Open");
  const [q, setQ] = useState("");
  // Where the one open add row is: a list, or under a task for a subtask.
  const [adding, setAdding] = useState<{ list: string; parent: number | null } | null>(null);
  // Lists and tasks folded shut.
  const [foldedLists, setFoldedLists] = useState<Set<string>>(new Set());
  const [foldedTasks, setFoldedTasks] = useState<Set<number>>(new Set());
  const people: Person[] = payload.people ?? [];
  const knownLists = useMemo(() => payload.lists?.[name] ?? [], [payload, name]);

  function flip<T>(set: Set<T>, key: T) {
    const next = new Set(set);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  }

  const kids = useMemo(() => {
    const m = new Map<number, TaskRow[]>();
    for (const t of tasks) {
      if (t.parent != null) m.set(t.parent, [...(m.get(t.parent) ?? []), t]);
    }
    return m;
  }, [tasks]);

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const shown = tasks.filter((t) => t.parent == null)
      .filter((t) => filter === "All" ? true
        : filter === "Open" ? !isClosed(t)
        : filter === "Finished" ? isClosed(t)
        : isOverdue(t))
      .filter((t) => !needle || t.title.toLowerCase().includes(needle));
    const by = new Map<string, TaskRow[]>();
    // Every list shows, empty or not, so there is always somewhere to add to -
    // except while searching or looking at a narrow filter.
    if (!needle && (filter === "Open" || filter === "All")) {
      for (const l of knownLists) by.set(l, []);
      if (knownLists.length === 0) by.set("", []);
    }
    for (const t of shown) {
      const key = t.list_name || "";
      by.set(key, [...(by.get(key) ?? []), t]);
    }
    for (const rows of by.values()) {
      rows.sort((a, b) => (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9)
        || (parseISO(a.end_date)?.getTime() ?? Infinity) - (parseISO(b.end_date)?.getTime() ?? Infinity));
    }
    return [...by.entries()].sort((a, b) =>
      a[0] === "" ? 1 : b[0] === "" ? -1 : a[0].localeCompare(b[0]));
  }, [tasks, filter, q, knownLists]);

  async function create(d: Draft, list: string, parent: number | null) {
    const r = await fetch("/api/tasks/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: d.title, project_name: name, list_name: list, status: d.status,
        parent, assignees: d.assignees,
        ...(d.priority ? { priority: d.priority } : {}),
        ...(d.due ? { end_date: d.due } : {}),
      }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      return body.detail || "Could not create the task.";
    }
    await onChange();
    return null;
  }

  async function setStatus(t: TaskRow, status: string) {
    await fetch(`/api/tasks/${t.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    await onChange();
  }

  function startTask(list: string) {
    setAdding({ list, parent: null });
    setFoldedLists((cur) => { const n = new Set(cur); n.delete(list); return n; });
  }

  function startSub(t: TaskRow) {
    setAdding({ list: t.list_name || "", parent: t.id });
    setFoldedTasks((cur) => { const n = new Set(cur); n.delete(t.id); return n; });
  }

  const boardLink = (id: number) => taskViewHref(name, "Board", id);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {TASK_FILTERS.map((f) => (
          <Pill key={f} active={filter === f} onClick={() => setFilter(f)}>{f}</Pill>
        ))}
        <div className="flex w-full items-center gap-2 sm:ml-auto sm:w-auto">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search tasks"
                 aria-label="Search tasks"
                 className="h-8 min-w-0 flex-1 rounded-lg bg-surface px-3 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring sm:w-56" />
          <Button variant="primary" icon="plus"
                  onClick={() => startTask(groups[0]?.[0] ?? knownLists[0] ?? "")}>
            Task
          </Button>
        </div>
      </div>

      {groups.length === 0 ? (
        <EmptyState icon="tasks"
                    title={filter === "Open" ? "Nothing open" : `No ${filter.toLowerCase()} tasks`}
                    hint={q ? "Nothing matches that search." : "Try another filter."} />
      ) : groups.map(([list, rows]) => {
        const listOpen = !foldedLists.has(list);
        return (
          <section key={list || "__general"} className="rounded-xl bg-surface ring-panel">
            <header className="flex items-center gap-2 px-3 py-2">
              <button onClick={() => setFoldedLists(flip(foldedLists, list))}
                      aria-label={listOpen ? "Collapse list" : "Expand list"} aria-expanded={listOpen}
                      className="flex h-5 w-5 items-center justify-center rounded text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring">
                <Icon name="chevron" className={`h-3 w-3 transition-transform ${listOpen ? "rotate-180" : "rotate-90"}`} />
              </button>
              <h3 className="text-sm font-semibold text-ink">{list || NO_LIST}</h3>
              <span className="text-xs text-ink-3">{rows.length}</span>
              <button onClick={() => startTask(list)} title={`Add a task to ${list || NO_LIST}`}
                      className="ml-1 flex h-5 w-5 items-center justify-center rounded text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring">
                <Icon name="plus" className="h-3.5 w-3.5" />
              </button>
            </header>

            {listOpen && (
              <>
                <div className="flex items-center gap-2 border-t border-stroke py-1.5 pl-10 pr-3 text-[11px] font-medium uppercase tracking-wide text-ink-3">
                  <span className="flex-1">Name</span>
                  <span className={COL.assignee}>Assignee</span>
                  <span className={COL.due}>Due date</span>
                  <span className={COL.priority}>Priority</span>
                  <span className={COL.status}>Status</span>
                </div>

                {rows.map((t) => {
                  const sub = kids.get(t.id) ?? [];
                  const open = !foldedTasks.has(t.id);
                  return (
                    <div key={t.id}>
                      <div className="group flex items-center gap-2 border-t border-stroke py-1.5 pl-3 pr-3 transition hover:bg-subtle/50">
                        <button onClick={() => setFoldedTasks(flip(foldedTasks, t.id))} disabled={!sub.length}
                                aria-label={open ? "Hide subtasks" : "Show subtasks"} aria-expanded={open}
                                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring ${
                                  sub.length ? "" : "invisible"}`}>
                          <Icon name="chevron" className={`h-3 w-3 transition-transform ${open ? "rotate-180" : "rotate-90"}`} />
                        </button>
                        <StatusPicker value={t.status} statuses={payload.statuses}
                                      onPick={(s) => void setStatus(t, s)} />
                        <div className="flex min-w-0 flex-1 items-center gap-2">
                          <Link href={boardLink(t.id)} title="Open on the board"
                                className={`min-w-0 truncate text-sm hover:text-brand ${isClosed(t) ? "text-ink-3 line-through" : "text-ink"}`}>
                            {t.title}
                          </Link>
                          {sub.length > 0 && (
                            <button onClick={() => setFoldedTasks(flip(foldedTasks, t.id))}
                                    title={`${sub.length} subtask${sub.length === 1 ? "" : "s"}`}
                                    className="flex shrink-0 items-center gap-0.5 rounded px-1 text-[11px] text-ink-3 ring-1 ring-stroke transition hover:text-ink">
                              <Icon name="subtasks" className="h-3 w-3" />
                              {sub.filter(isClosed).length}/{sub.length}
                            </button>
                          )}
                          {t.stream && (
                            <span className="hidden shrink-0 rounded bg-subtle px-1.5 text-[10px] font-semibold text-ink-3 sm:inline">
                              {STREAM_LABEL[t.stream] ?? t.stream}
                            </span>
                          )}
                          <button onClick={() => startSub(t)} title="Add subtask"
                                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-3 opacity-0 transition hover:bg-subtle hover:text-ink focus:opacity-100 focus-ring group-hover:opacity-100">
                            <Icon name="plus" className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <span className={COL.assignee}><Initials people={t.assignees} /></span>
                        <span className={COL.due}><DueChip date={t.end_date} done={isClosed(t)} /></span>
                        <span className={COL.priority}>
                          <Flag priority={t.priority} label={labelOf(payload.priorities, t.priority)} />
                        </span>
                        <span className={COL.status}>
                          <StatusChip status={t.status} label={labelOf(payload.statuses, t.status)} />
                        </span>
                      </div>

                      {open && sub.map((x) => (
                        <div key={x.id} className="flex items-center gap-2 border-t border-stroke py-1.5 pl-10 pr-3 transition hover:bg-subtle/50">
                          <span className="w-4 shrink-0" />
                          <StatusPicker value={x.status} statuses={payload.statuses} size="h-3 w-3"
                                        onPick={(s) => void setStatus(x, s)} />
                          <Link href={boardLink(x.id)} title="Open on the board"
                                className={`min-w-0 flex-1 truncate text-[13px] hover:text-brand ${isClosed(x) ? "text-ink-3 line-through" : "text-ink-2"}`}>
                            {x.title}
                          </Link>
                          <span className={COL.assignee}><Initials people={x.assignees} /></span>
                          <span className={COL.due}><DueChip date={x.end_date} done={isClosed(x)} /></span>
                          <span className={COL.priority}>
                            <Flag priority={x.priority} label={labelOf(payload.priorities, x.priority)} />
                          </span>
                          <span className={COL.status}>
                            <StatusChip status={x.status} label={labelOf(payload.statuses, x.status)} />
                          </span>
                        </div>
                      ))}

                      {adding?.parent === t.id && (
                        <QuickAdd sub people={people} statuses={payload.statuses} priorities={payload.priorities}
                                  onCancel={() => setAdding(null)}
                                  onSave={(d) => create(d, t.list_name || "", t.id)} />
                      )}
                    </div>
                  );
                })}

                {adding && adding.parent === null && adding.list === list ? (
                  <QuickAdd people={people} statuses={payload.statuses} priorities={payload.priorities}
                            onCancel={() => setAdding(null)}
                            onSave={(d) => create(d, list, null)} />
                ) : (
                  <button onClick={() => startTask(list)}
                          className="flex w-full items-center gap-2 rounded-b-xl border-t border-stroke py-2 pl-10 pr-3 text-left text-sm text-ink-3 transition hover:bg-subtle/50 hover:text-ink focus-ring">
                    <Icon name="plus" className="h-3.5 w-3.5" /> Add Task
                  </button>
                )}
              </>
            )}
          </section>
        );
      })}
    </div>
  );
}

/* ── Reporting ────────────────────────────────────────────────────────────── */

function ReportingTab({ metrics, quoted }: { metrics: Metrics | null; quoted: number | null }) {
  if (!metrics) {
    return <Section><p className="text-sm text-ink-2">Working out the figures…</p></Section>;
  }
  const t = metrics.totals;
  const row = metrics.projects[0];
  const est = t.estimated_hours ?? 0;
  const act = t.actual_hours ?? 0;
  const over = est > 0 && act > est;
  const burn = quoted ? Math.round((act / quoted) * 100) : null;

  const groups = STATUS_GROUPS.map((g, i) => ({
    label: g.label, color: SERIES[i],
    value: g.statuses.reduce((n, s) => n + (metrics.tasks_by_status[s] ?? 0), 0),
  }));
  const streams = Object.entries(metrics.tasks_by_stream)
    .sort((a, b) => (a[0] === "" ? 1 : b[0] === "" ? -1 : a[0].localeCompare(b[0])));
  const streamSeries = [{ label: "Finished", color: SERIES[0] },
                        { label: "Still open", color: SERIES[1] }];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Finished" icon="check" value={`${Math.round(t.completion_rate)}%`}
                  hint={`${t.tasks_done} of ${t.tasks}, subtasks included`} />
        <StatTile label="Signed off" icon="shield" value={row ? `${Math.round(row.accepted_rate)}%` : "—"}
                  hint="accepted by the client" />
        <StatTile label="Blocked or waiting" icon="pause" value={t.tasks_blocked}
                  tone={t.tasks_blocked ? "warn" : "neutral"} hint="on hold or need guidance" />
        <StatTile label="Overdue" icon="alert" value={t.tasks_overdue}
                  tone={t.tasks_overdue ? "bad" : "good"}
                  hint={`${t.tasks_due_next_7_days} more due this week`} />
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Hours logged" icon="clock" value={fmtHours(act)}
                  tone={over ? "bad" : "neutral"}
                  hint={est ? `of ${fmtHours(est)} estimated` : "nothing estimated"} />
        <StatTile label="Against estimate" icon="analysis"
                  value={t.hours_variance === null ? "—"
                    : `${t.hours_variance > 0 ? "+" : ""}${fmtHours(t.hours_variance)}`}
                  tone={over ? "bad" : t.hours_variance !== null ? "good" : "neutral"}
                  hint={over ? "over estimate" : t.hours_variance !== null ? "within estimate" : undefined} />
        <StatTile label="Quote used" icon="records" value={burn === null ? "—" : `${burn}%`}
                  tone={burn !== null && burn > 100 ? "bad" : "neutral"}
                  hint={quoted ? `of ${fmtHours(quoted)} quoted` : "no quote set"} />
        <StatTile label="Average time to finish" icon="calendar"
                  value={row?.avg_days_to_complete == null ? "—" : `${row.avg_days_to_complete}d`}
                  hint="created to finished" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Where the work stands" hint="Every task and subtask, by what it is doing."
                   table={{ head: ["State", "Tasks"], rows: groups.map((g) => [g.label, g.value]) }}>
          <Donut data={groups} centreLabel="tasks" centreValue={t.tasks} />
        </ChartCard>

        <ChartCard title="Finished and open by stream"
                   hint="WEB, APP and API, as the management report splits them."
                   legend={streamSeries}
                   empty={streams.length === 0 ? "No tasks yet." : undefined}
                   table={{ head: ["Stream", "Finished", "Still open"],
                            rows: streams.map(([k, v]) => [STREAM_LABEL[k] ?? k, v.done, v.open]) }}>
          <StackedBars series={streamSeries}
                       rows={streams.map(([k, v]) => ({
                         label: STREAM_LABEL[k] ?? k, values: [v.done, v.open] }))} />
        </ChartCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title={`Overdue (${metrics.overdue.length})`}>
          {metrics.overdue.length === 0 ? (
            <p className="text-sm text-ink-3">Nothing is late.</p>
          ) : (
            <ul className="-my-2 divide-y divide-stroke">
              {metrics.overdue.map((o, i) => (
                <li key={i} className="flex items-center gap-3 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate text-ink">{o.title}</span>
                  <span className="shrink-0 text-xs text-ink-3">{fmtDate(o.due)}</span>
                  <span className="w-20 shrink-0 text-right text-xs font-medium text-bad">
                    {o.days_late} day{o.days_late === 1 ? "" : "s"} late
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title={`Blocked or waiting (${metrics.blocked.length})`}>
          {metrics.blocked.length === 0 ? (
            <p className="text-sm text-ink-3">Nothing is blocked.</p>
          ) : (
            <ul className="-my-2 divide-y divide-stroke">
              {metrics.blocked.map((b, i) => (
                <li key={i} className="flex items-center gap-3 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate text-ink">{b.title}</span>
                  <StatusChip status={b.status} label={b.status_display} />
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>

      <Section title="Who has worked on it (last 30 days)">
        {metrics.people.length === 0 ? (
          <p className="text-sm text-ink-3">No changes recorded in the last 30 days.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {metrics.people.map((u) => (
              <li key={u.user} className="rounded-lg bg-subtle px-3 py-1.5 text-sm text-ink">
                {u.user} <span className="text-ink-3">· {u.changes} change{u.changes === 1 ? "" : "s"}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

/* ── Website ──────────────────────────────────────────────────────────────── */

/** Why the browser will not show `url` in a frame here, or "" if it will. */
function frameProblem(url: string, check: SiteCheck["live"] | undefined) {
  // An https page may not frame an http one; the server cannot see that.
  if (typeof window !== "undefined" && window.location.protocol === "https:"
      && url.startsWith("http:")) {
    return "This page is served securely and the site is not, so the browser will not show it here.";
  }
  if (check && !check.reachable) return check.reason || "The site did not respond.";
  if (check && !check.embeddable) return check.reason;
  return "";
}

/**
 * A website shown inside the page. `thumbnail` renders it as a still,
 * desktop-width snapshot scaled into its box; otherwise it is a working frame.
 * Sites that refuse to be framed get a sentence and a link instead of the
 * blank box the browser would leave.
 */
function SiteFrame({ url, check, thumbnail = false, mobile = false, reload = 0 }: {
  url: string; check: SiteCheck["live"] | undefined; thumbnail?: boolean;
  mobile?: boolean; reload?: number;
}) {
  const problem = frameProblem(url, check);
  if (problem) {
    return (
      <div className={`flex flex-col items-center justify-center gap-2 bg-subtle/60 px-4 text-center ${
        thumbnail ? "aspect-[16/10]" : "h-[420px]"}`}>
        <Icon name="globe" className="h-5 w-5 text-ink-3" />
        <p className="max-w-sm text-xs text-ink-2">{problem}</p>
        {!thumbnail && (
          <a href={url} target="_blank" rel="noreferrer"
             className="mt-1 inline-flex items-center gap-1.5 rounded-md bg-surface px-2.5 py-1.5 text-sm font-medium text-ink ring-control hover:bg-subtle">
            <Icon name="link" className="h-4 w-4" /> Open in a new tab
          </a>
        )}
      </div>
    );
  }
  if (thumbnail) {
    // Four times the box, scaled to a quarter: the site lays out at desktop
    // width and the whole of its first screen fits the card.
    return (
      <div className="relative aspect-[16/10] overflow-hidden bg-surface">
        <iframe key={reload} src={url} title="Website preview" loading="lazy" tabIndex={-1}
                referrerPolicy="no-referrer"
                sandbox="allow-scripts allow-same-origin"
                className="pointer-events-none absolute left-0 top-0 h-[400%] w-[400%] origin-top-left scale-25 border-0" />
      </div>
    );
  }
  return (
    <div className="flex justify-center bg-subtle/40">
      <iframe key={reload} src={url} title="Website preview"
              referrerPolicy="no-referrer"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
              className={`h-[640px] border-0 bg-white ${mobile ? "w-[390px] shadow-lg" : "w-full"}`} />
    </div>
  );
}

/** A typed address as a full URL: "afma.org.za" -> "https://afma.org.za". */
function asUrl(v: string): string {
  const t = v.trim();
  if (!t) return "";
  return /^https?:\/\//i.test(t) ? t : `https://${t}`;
}

/** The live and demo addresses, for a project that has neither yet. There is
    no Save button: it saves once you leave the two boxes (or press Enter) -
    not on every keystroke, so a half-typed address never gets saved and
    swapped for a broken preview. */
function SiteUrlForm({ saving, error, onSave }: {
  saving: boolean; error: string; onSave: (body: Partial<Project>) => Promise<boolean>;
}) {
  const [live, setLive] = useState("");
  const [demo, setDemo] = useState("");
  const [problem, setProblem] = useState("");
  const commit = () => {
    const url = asUrl(live);
    if (!url || saving) return;
    if (!/^https?:\/\/[^\s/]+\.[^\s/]{2,}/i.test(url)) {
      setProblem("That doesn't look like a web address - for example https://afma.org.za");
      return;
    }
    setProblem("");
    void onSave({ website_url: url, demo_url: asUrl(demo) });
  };
  return (
    <form onSubmit={(e) => { e.preventDefault(); commit(); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
          // Moving from the live box to the demo box stays inside the form, so
          // it only saves once focus leaves both.
          onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) commit(); }}
          className="space-y-3">
      <p className="text-sm text-ink-3">No website yet. Add its address to see it here - it saves by itself.</p>
      <TextInput label="Live site" value={live} placeholder="https://" onChange={setLive} />
      <TextInput label="Demo site (optional)" value={demo} placeholder="https://" onChange={setDemo} />
      {saving && <p className="text-xs text-ink-3">Saving…</p>}
      {(problem || error) && <p className="text-xs text-bad">{problem || error}</p>}
    </form>
  );
}

const WEBSITE_FIELDS = ["website_url", "demo_url", "hosting", "tech_stack",
                        "website_notes"] as const;
type WebsiteForm = Record<(typeof WEBSITE_FIELDS)[number], string>;

function WebsiteTab({ p, agreements, sites, saving, error, onSave }: {
  p: Project; agreements: Agreement[]; sites: SiteCheck | null; saving: boolean;
  error: string; onSave: (body: Partial<Project>) => Promise<boolean>;
}) {
  const [form, setForm] = useState<WebsiteForm | null>(null);
  const available = ([["live", "Live site", p.website_url], ["demo", "Demo site", p.demo_url]] as const)
    .filter(([, , url]) => url);
  const [which, setWhich] = useState<"live" | "demo">(p.website_url ? "live" : "demo");
  const [mobile, setMobile] = useState(false);
  const [reload, setReload] = useState(0);
  const current = available.find(([k]) => k === which) ?? available[0];

  function begin() {
    setForm(Object.fromEntries(WEBSITE_FIELDS.map((f) => [f, p[f]])) as WebsiteForm);
  }

  async function save() {
    if (form && await onSave(form)) setForm(null);
  }

  return (
    <div className="space-y-4">
      {current ? (
        <section className="overflow-hidden rounded-xl bg-surface ring-panel">
          <header className="flex flex-wrap items-center gap-2 border-b border-stroke px-3 py-2">
            <div className="flex rounded-lg bg-subtle p-0.5" role="tablist" aria-label="Which site">
              {available.map(([k, label]) => (
                <button key={k} role="tab" aria-selected={current[0] === k}
                        onClick={() => setWhich(k)}
                        className={`rounded-md px-3 py-1 text-sm font-medium transition focus-ring ${
                          current[0] === k ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}>
                  {label}
                </button>
              ))}
            </div>
            <span className="mx-1 hidden min-w-0 flex-1 truncate rounded-md bg-canvas px-2.5 py-1 text-xs text-ink-2 ring-control sm:block">
              {current[2]}
            </span>
            <div className="ml-auto flex items-center gap-1">
              <div className="flex rounded-lg bg-subtle p-0.5" aria-label="Screen size">
                {(["Desktop", "Mobile"] as const).map((m) => (
                  <button key={m} onClick={() => setMobile(m === "Mobile")}
                          aria-pressed={mobile === (m === "Mobile")}
                          className={`rounded-md px-2.5 py-1 text-xs font-medium transition focus-ring ${
                            mobile === (m === "Mobile") ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}>
                    {m}
                  </button>
                ))}
              </div>
              <Button variant="ghost" icon="sync" title="Reload" aria-label="Reload"
                      onClick={() => setReload((n) => n + 1)} />
              <a href={current[2]} target="_blank" rel="noreferrer"
                 className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium text-ink-2 hover:bg-subtle hover:text-ink">
                <Icon name="link" className="h-4 w-4" /> Open
              </a>
            </div>
          </header>
          <SiteFrame url={current[2]} check={sites?.[current[0]]} mobile={mobile} reload={reload} />
        </section>
      ) : (
        <Section title="Website">
          <SiteUrlForm saving={saving} error={error} onSave={onSave} />
        </Section>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          {form ? (
            <Section title="Website details">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <TextInput label="Live site" value={form.website_url} placeholder="https://"
                           onChange={(v) => setForm({ ...form, website_url: v })} />
                <TextInput label="Demo site" value={form.demo_url} placeholder="https://"
                           onChange={(v) => setForm({ ...form, demo_url: v })} />
                <TextInput label="Hosting" value={form.hosting} placeholder="e.g. Azure VM, IIS"
                           onChange={(v) => setForm({ ...form, hosting: v })} />
                <TextInput label="Tech stack" value={form.tech_stack}
                           placeholder="e.g. Next.js, Django, PostgreSQL"
                           onChange={(v) => setForm({ ...form, tech_stack: v })} />
                <div className="sm:col-span-2">
                  <AreaInput label="Notes" rows={5} value={form.website_notes}
                             hint="Domain, DNS, admin URLs, where the credentials are kept. Not the passwords themselves."
                             onChange={(v) => setForm({ ...form, website_notes: v })} />
                </div>
              </div>
              {error && <p className="mt-3 text-xs text-bad">{error}</p>}
              <div className="mt-4 flex justify-end gap-2">
                <Button onClick={() => setForm(null)}>Cancel</Button>
                <Button variant="primary" spinning={saving} disabled={saving}
                        onClick={() => void save()}>Save website details</Button>
              </div>
            </Section>
          ) : (
            <Section title="Website details"
                     right={<Button variant="ghost" icon="edit" onClick={begin}>Edit</Button>}>
              {!WEBSITE_FIELDS.some((f) => p[f]) ? (
                <p className="text-sm text-ink-3">Nothing recorded yet.</p>
              ) : (
                <>
                  <dl className="-my-2 divide-y divide-stroke text-sm">
                    {([["Live site", p.website_url, true], ["Demo site", p.demo_url, true],
                       ["Hosting", p.hosting, false], ["Tech stack", p.tech_stack, false]] as const)
                      .map(([k, v, link]) => v && (
                        <div key={k} className="flex flex-wrap justify-between gap-x-4 gap-y-1 py-2">
                          <dt className="text-ink-2">{k}</dt>
                          <dd className="text-right font-medium text-ink">
                            {link ? <ExternalLink href={v} /> : v}
                          </dd>
                        </div>
                      ))}
                  </dl>
                  {p.website_notes && (
                    <div className="mt-4 border-t border-stroke pt-3">
                      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-3">Notes</h4>
                      <p className="whitespace-pre-wrap text-sm text-ink-2">{p.website_notes}</p>
                    </div>
                  )}
                </>
              )}
            </Section>
          )}
        </div>

        <Section title="Service agreement">
          {agreements.length === 0 ? (
            <p className="text-sm text-ink-3">
              No service agreement is recorded for this project or its client.
            </p>
          ) : (
            <div className="space-y-4">
              {agreements.map((a) => (
                <div key={a.id} className="-my-2">
                  <div className="flex items-center justify-between gap-2 pb-1 pt-2">
                    <span className="text-sm font-semibold text-ink">{a.tier_display}</span>
                    {!a.is_active && <Badge>Inactive</Badge>}
                  </div>
                  <Row k="Response" v={a.response_hours != null ? `${a.response_hours}h` : ""} />
                  <Row k="Resolution" v={a.resolution_hours != null ? `${a.resolution_hours}h` : ""} />
                  <Row k="Support hours" v={a.support_window} />
                  <Row k="Hosting" v={a.hosting_provider} />
                  <Row k="Backups" v={a.backup_schedule} />
                  {a.environment_url && (
                    <div className="flex justify-between gap-4 border-b border-stroke py-2 text-sm">
                      <span className="text-ink-2">Environment</span>
                      <ExternalLink href={a.environment_url} />
                    </div>
                  )}
                  {a.renewal_date && (
                    <div className="flex items-center justify-between gap-4 py-2 text-sm">
                      <span className="text-ink-2">Renews</span>
                      <Badge tone={expiryTone(a.renews_in_days)}>
                        {fmtDate(a.renewal_date)} · {expiryLabel(a.renews_in_days)}
                      </Badge>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}

/* ── GitHub ───────────────────────────────────────────────────────────────── */

type RepoChoices = {
  tracked: Repo[];
  github: { configured: boolean; ok?: boolean; detail?: string;
            repos?: { name: string; full_name: string; url: string;
                      description: string; private: boolean }[] };
};

function GitHubTab({ name, repos, onChange }: {
  name: string; repos: Repo[]; onChange: () => Promise<void>;
}) {
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const enc = encodeURIComponent(name);

  async function remove(r: Repo) {
    setBusy(r.id);
    try {
      await fetch(`/api/projects/${enc}/repos/${r.id}/remove`, { method: "POST" });
      await onChange();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {repos.length === 0 ? (
        <EmptyState icon="git" title="No repository assigned"
                    hint="Assign the code for this project - a repository already in Sentinel, one from GitHub, or any link."
                    action={<Button variant="primary" icon="plus" onClick={() => setPicking(true)}>
                      Assign repository</Button>} />
      ) : (
        <Section title={`Repositories (${repos.length})`}
                 right={<Button variant="primary" icon="plus" onClick={() => setPicking(true)}>
                   Assign repository</Button>}>
          <ul className="-my-2 divide-y divide-stroke">
            {repos.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 py-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-subtle">
                  <Icon name="git" className="h-4 w-4 text-ink-2" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-ink">{r.name}</p>
                  <p className="truncate text-xs text-ink-3">
                    {r.provider_display}
                    {r.default_branch && ` · ${r.default_branch}`}
                    {r.description && ` · ${r.description}`}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  {r.remote_url && (
                    <a href={r.remote_url} target="_blank" rel="noreferrer"
                       className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium text-ink-2 hover:bg-subtle hover:text-ink">
                      <Icon name="link" className="h-4 w-4" /> Open on {r.provider_display}
                    </a>
                  )}
                  <Link href={`/repos/${r.id}/docs`}
                        className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium text-ink-2 hover:bg-subtle hover:text-ink">
                    <Icon name="docs" className="h-4 w-4" /> Documentation
                  </Link>
                  <Button variant="ghost" spinning={busy === r.id} disabled={busy === r.id}
                          onClick={() => void remove(r)} title="Take it off this project">
                    Remove
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {picking && (
        <RepoPicker name={name} onClose={() => setPicking(false)}
                    onAssigned={async () => { setPicking(false); await onChange(); }} />
      )}
    </div>
  );
}

function RepoPicker({ name, onClose, onAssigned }: {
  name: string; onClose: () => void; onAssigned: () => Promise<void>;
}) {
  const enc = encodeURIComponent(name);
  const [choices, setChoices] = useState<RepoChoices | null>(null);
  const [q, setQ] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`/api/projects/${enc}/repos?github=1`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setChoices(d ?? { tracked: [], github: { configured: false } }));
  }, [enc]);

  async function assign(body: Record<string, unknown>, key: string) {
    setBusy(key);
    setError("");
    try {
      const r = await fetch(`/api/projects/${enc}/repos`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(d.detail || "Could not assign that repository.");
        return;
      }
      await onAssigned();
    } finally {
      setBusy("");
    }
  }

  const needle = q.trim().toLowerCase();
  const match = (s: string) => !needle || s.toLowerCase().includes(needle);
  const tracked = (choices?.tracked ?? []).filter((r) => match(`${r.name} ${r.remote_url}`));
  const fromGitHub = (choices?.github.repos ?? []).filter((r) => match(`${r.full_name} ${r.description}`));

  return (
    <Modal title={`Assign a repository to ${name}`} wide onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (url.trim()) void assign({ url: url.trim() }, "url"); }}
            className="mb-5">
        <span className="block h-6 text-sm font-medium leading-6 text-ink">Paste a repository link</span>
        <div className="mt-1.5 flex gap-2">
          <input value={url} onChange={(e) => { setUrl(e.target.value); setError(""); }}
                 placeholder="https://github.com/your-org/your-repo" aria-label="Repository link"
                 className="h-9 min-w-0 flex-1 rounded-lg bg-surface px-3 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring" />
          <Button type="submit" variant="primary" spinning={busy === "url"}
                  disabled={!!busy || !url.trim()}>Assign</Button>
        </div>
      </form>

      {error && <p className="mb-4 rounded-lg bg-bad-bg px-3 py-2 text-xs text-bad">{error}</p>}

      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search repositories"
             aria-label="Search repositories"
             className="mb-3 h-9 w-full rounded-lg bg-surface px-3 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring" />

      {!choices ? (
        <p className="py-4 text-sm text-ink-3">Loading repositories…</p>
      ) : (
        <div className="space-y-5 pb-4">
          <div>
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">
              Already in Sentinel
            </h3>
            {tracked.length === 0 ? (
              <p className="text-sm text-ink-3">
                {choices.tracked.length === 0 ? "No other repositories are tracked yet." : "Nothing matches."}
              </p>
            ) : (
              <ul className="divide-y divide-stroke rounded-lg ring-1 ring-stroke">
                {tracked.map((r) => (
                  <li key={r.id} className="flex items-center gap-3 px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink">{r.name}</p>
                      <p className="truncate text-xs text-ink-3">
                        {r.project_name ? `On ${r.project_name} - assigning moves it here` : r.remote_url || r.provider_display}
                      </p>
                    </div>
                    <Button spinning={busy === `t${r.id}`} disabled={!!busy}
                            onClick={() => void assign({ repo_id: r.id }, `t${r.id}`)}>Assign</Button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">On GitHub</h3>
            {!choices.github.configured ? (
              <p className="text-sm text-ink-3">
                GitHub is not connected on this server, so its repositories cannot be listed.
                Add <code className="text-ink-2">GITHUB_TOKEN</code> and <code className="text-ink-2">GITHUB_OWNER</code> to
                the server&apos;s environment, or paste a link above.
              </p>
            ) : choices.github.ok === false ? (
              <p className="text-sm text-bad">{choices.github.detail || "GitHub did not answer."}</p>
            ) : fromGitHub.length === 0 ? (
              <p className="text-sm text-ink-3">
                {(choices.github.repos ?? []).length === 0
                  ? "Every repository on the account is already in Sentinel." : "Nothing matches."}
              </p>
            ) : (
              <ul className="divide-y divide-stroke rounded-lg ring-1 ring-stroke">
                {fromGitHub.map((r) => (
                  <li key={r.full_name} className="flex items-center gap-3 px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink">
                        {r.full_name}
                        {r.private && <span className="ml-1.5 text-[11px] font-normal text-ink-3">private</span>}
                      </p>
                      {r.description && <p className="truncate text-xs text-ink-3">{r.description}</p>}
                    </div>
                    <Button spinning={busy === r.full_name} disabled={!!busy}
                            onClick={() => void assign({ full_name: r.full_name }, r.full_name)}>
                      Import &amp; assign
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

/* ── Server ───────────────────────────────────────────────────────────────── */

type ProjectServer = {
  id: number; name: string; vmid: number | null; os: string;
  cores: number; memory_mb: number; disk_gb: number;
  ip: string; username: string; status: string; status_display: string;
  step: string; error: string; created_by: string; created_at: string;
};
type ServersPayload = {
  configured: boolean; can_manage: boolean; os: string;
  size: { cores: number; memory_mb: number; disk_gb: number };
  choices?: { cores: number[]; memory_mb: number[]; max_disk_gb: number };
  servers: ProjectServer[];
};

const SERVER_TONE: Record<string, Tone> = {
  running: "good", provisioning: "info", queued: "info", deleting: "warn",
  stopped: "neutral", failed: "bad",
};

function CopyText({ text, mono = true }: { text: string; mono?: boolean }) {
  const [done, setDone] = useState(false);
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`select-all ${mono ? "font-mono text-[13px]" : ""} text-ink`}>{text}</span>
      <button onClick={() => {
                void navigator.clipboard?.writeText(text);
                setDone(true);
                setTimeout(() => setDone(false), 1500);
              }}
              className="rounded px-1.5 py-0.5 text-[11px] font-medium text-brand ring-1 ring-stroke hover:bg-subtle">
        {done ? "Copied" : "Copy"}
      </button>
    </span>
  );
}

type ServerStats = {
  status: string; cpu_percent: number; cpus: number;
  mem_used: number; mem_total: number; uptime: number;
  net_in: number; net_out: number;
};

function fmtBytes(n: number) {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i >= 3 ? 1 : 0)} ${units[i]}`;
}

function fmtUptime(sec: number) {
  if (!sec) return "just started";
  const d = Math.floor(sec / 86400), h = Math.floor(sec / 3600) % 24, m = Math.floor(sec / 60) % 60;
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

/** What a running server is doing now, refreshed every few seconds. */
function ServerLive({ name, id }: { name: string; id: number }) {
  const [st, setSt] = useState<ServerStats | null>(null);
  useEffect(() => {
    let gone = false;
    const get = () => fetch(`/api/projects/${encodeURIComponent(name)}/servers/${id}/stats`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!gone && d) setSt(d); })
      .catch(() => {});
    void get();
    const t = setInterval(() => void get(), 5000);
    return () => { gone = true; clearInterval(t); };
  }, [name, id]);
  if (!st) return null;
  const memPct = st.mem_total ? Math.round((st.mem_used / st.mem_total) * 100) : 0;
  const tile = "rounded-lg bg-subtle/60 px-3 py-2";
  return (
    <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
      <div className={tile}>
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-3">CPU</p>
        <p className="text-sm font-semibold tabular-nums text-ink">{st.cpu_percent}%
          <span className="font-normal text-ink-3"> of {st.cpus}</span></p>
      </div>
      <div className={tile}>
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Memory</p>
        <p className="text-sm font-semibold tabular-nums text-ink">{fmtBytes(st.mem_used)}
          <span className="font-normal text-ink-3"> / {fmtBytes(st.mem_total)} · {memPct}%</span></p>
      </div>
      <div className={tile}>
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Up for</p>
        <p className="text-sm font-semibold text-ink">{fmtUptime(st.uptime)}</p>
      </div>
      <div className={tile}>
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Network</p>
        <p className="text-sm font-semibold tabular-nums text-ink">↓ {fmtBytes(st.net_in)}
          <span className="font-normal text-ink-3"> · ↑ {fmtBytes(st.net_out)}</span></p>
      </div>
    </div>
  );
}

function ServerTab({ name }: { name: string }) {
  const enc = encodeURIComponent(name);
  const [data, setData] = useState<ServersPayload | null>(null);
  const [creating, setCreating] = useState(false);
  const [sshKey, setSshKey] = useState("");
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState("");
  const [login, setLogin] = useState<
    { server: string; user: string; password: string; saved: boolean } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<ProjectServer | null>(null);
  // The one server whose console is open, if any.
  const [consoleFor, setConsoleFor] = useState<number | null>(null);
  // Changing a server's size: the form, and whether a restart is now due.
  const [sizing, setSizing] = useState<
    { server: ProjectServer; cores: number; memory_mb: number; disk_gb: string;
      restartDue?: boolean } | null>(null);

  async function saveSize() {
    if (!sizing) return;
    setBusy("resize");
    setError("");
    try {
      const r = await fetch(`/api/projects/${enc}/servers/${sizing.server.id}/resize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cores: sizing.cores, memory_mb: sizing.memory_mb,
                               disk_gb: Number(sizing.disk_gb) }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(d.detail || "Could not change the server.");
        return;
      }
      await load();
      if (d.restart_needed) setSizing({ ...sizing, server: d.server, restartDue: true });
      else setSizing(null);
    } finally {
      setBusy("");
    }
  }

  const load = useCallback(async () => {
    const r = await fetch(`/api/projects/${enc}/servers`);
    setData(r.ok ? await r.json() : null);
  }, [enc]);

  useEffect(() => {
    // Fetching on open is the point of this effect.
    void load();
  }, [load]);

  // While a server is being built or removed, its progress is followed.
  const working = (data?.servers ?? []).some((s) =>
    ["queued", "provisioning", "deleting"].includes(s.status));
  useEffect(() => {
    if (!working) return;
    const id = setInterval(() => void load(), 4000);
    return () => clearInterval(id);
  }, [working, load]);

  async function create() {
    setBusy("create");
    setError("");
    try {
      const r = await fetch(`/api/projects/${enc}/servers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ssh_key: sshKey.trim() }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(d.detail || "The server could not be created.");
        return;
      }
      setCreating(false);
      setSshKey("");
      setLogin({ server: d.server.name, user: d.server.username, password: d.password,
                 saved: !!d.saved_to_credentials });
      await load();
    } finally {
      setBusy("");
    }
  }

  async function act(s: ProjectServer, action: string) {
    setBusy(`${action}-${s.id}`);
    setError("");
    try {
      const r = await fetch(`/api/projects/${enc}/servers/${s.id}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(d.detail || `Could not ${action} the server.`);
      }
      await load();
    } finally {
      setBusy("");
    }
  }

  if (!data) return <Section><p className="text-sm text-ink-2">Loading…</p></Section>;

  const size = `${data.size.cores} CPU · ${data.size.memory_mb / 1024} GB RAM · ${data.size.disk_gb} GB disk`;

  if (!data.configured) {
    return (
      <EmptyState icon="server" title="Proxmox is not connected yet"
                  hint={data.can_manage
                    ? "Run scripts/proxmox_setup.sh in the Proxmox host's Shell, add the lines it prints to Sentinel's .env and restart Sentinel."
                    : "An administrator needs to connect Sentinel to the Proxmox host first."} />
    );
  }

  return (
    <div className="space-y-4">
      {error && <p className="rounded-lg bg-bad-bg px-3 py-2 text-xs text-bad">{error}</p>}

      {data.servers.length === 0 ? (
        <EmptyState icon="server" title="No server for this project"
                    hint={`A ${data.os} virtual server on the office Proxmox host: ${size}.`}
                    action={data.can_manage
                      ? <Button variant="primary" icon="plus" onClick={() => setCreating(true)}>Create server</Button>
                      : undefined} />
      ) : (
        data.servers.map((s) => {
          const live = !["queued", "provisioning", "deleting"].includes(s.status);
          return (
            <Section key={s.id}
                     title={s.name}
                     right={<Badge tone={SERVER_TONE[s.status] ?? "neutral"}>
                       {!live && <Icon name="sync" className="h-3 w-3 animate-spin" />}
                       {s.status_display}
                     </Badge>}>
              {s.step && <p className="mb-3 text-sm text-ink-2">{s.step}…</p>}
              {s.status === "failed" && s.error && (
                <p className="mb-3 whitespace-pre-wrap rounded-lg bg-bad-bg px-3 py-2 text-xs text-bad">{s.error}</p>
              )}
              <div className="grid gap-x-8 sm:grid-cols-2">
                <div className="-my-2">
                  <Row k="System" v={s.os} />
                  <Row k="Size" v={`${s.cores} CPU · ${s.memory_mb / 1024} GB RAM · ${s.disk_gb} GB disk`} />
                  <Row k="Proxmox VM" v={s.vmid ? String(s.vmid) : ""} />
                  <Row k="Created" v={`${fmtDate(s.created_at.slice(0, 10))}${s.created_by ? ` by ${s.created_by}` : ""}`} />
                </div>
                <div className="space-y-2.5 py-1 text-sm">
                  <p className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-ink-2">Address</span>
                    {s.ip ? <CopyText text={s.ip} /> : <span className="text-ink-3">{live ? "Not reported yet" : "Assigned on boot"}</span>}
                  </p>
                  <p className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-ink-2">User</span>
                    <span className="font-mono text-[13px] text-ink">{s.username}</span>
                  </p>
                  {s.ip && (
                    <p className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-ink-2">Connect</span>
                      <CopyText text={`ssh ${s.username}@${s.ip}`} />
                    </p>
                  )}
                </div>
              </div>

              {s.status === "running" && <ServerLive name={name} id={s.id} />}

              <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-stroke pt-3">
                {data.can_manage && s.status === "running" && (
                  <Button variant={consoleFor === s.id ? "secondary" : "primary"} icon="server"
                          onClick={() => setConsoleFor(consoleFor === s.id ? null : s.id)}>
                    {consoleFor === s.id ? "Hide console" : "Open console"}
                  </Button>
                )}
                <Button icon="sync" spinning={busy === `refresh-${s.id}`} disabled={!!busy}
                        onClick={() => void act(s, "refresh")}>Refresh</Button>
                {data.can_manage && live && (
                  <>
                    {s.status === "stopped" && (
                      <Button spinning={busy === `start-${s.id}`} disabled={!!busy}
                              onClick={() => void act(s, "start")}>Start</Button>
                    )}
                    <Button icon="edit" disabled={!!busy}
                            onClick={() => { setError(""); setSizing({ server: s, cores: s.cores,
                              memory_mb: s.memory_mb, disk_gb: String(s.disk_gb) }); }}>
                      Change size
                    </Button>
                    {s.status === "running" && (
                      <>
                        <Button spinning={busy === `reboot-${s.id}`} disabled={!!busy}
                                onClick={() => void act(s, "reboot")}>Restart</Button>
                        <Button spinning={busy === `stop-${s.id}`} disabled={!!busy}
                                onClick={() => void act(s, "stop")}>Shut down</Button>
                      </>
                    )}
                    <Button variant="danger" icon="trash" disabled={!!busy} className="ml-auto"
                            onClick={() => setConfirmDelete(s)}>Delete server</Button>
                  </>
                )}
              </div>

              {consoleFor === s.id && s.status === "running" && (
                <div className="mt-4">
                  <ServerConsole project={name} serverId={s.id} />
                  <p className="mt-1.5 text-xs text-ink-3">
                    Log in as <span className="font-mono">{s.username}</span> with the password in this
                    project&apos;s Credentials, or connect with <span className="font-mono">ssh {s.username}@{s.ip || "…"}</span>.
                  </p>
                </div>
              )}
            </Section>
          );
        })
      )}

      {data.servers.length > 0 && data.can_manage && (
        <Button icon="plus" onClick={() => setCreating(true)}>Create another server</Button>
      )}

      {creating && (
        <Modal title={`Create a server for ${name}`} onClose={() => setCreating(false)}
               footer={
                 <>
                   <Button onClick={() => setCreating(false)}>Cancel</Button>
                   <Button variant="primary" spinning={busy === "create"} disabled={busy === "create"}
                           onClick={() => void create()}>Create server</Button>
                 </>
               }>
          <p className="text-sm text-ink-2">
            {data.os} on the office Proxmox host, with {size}. It is ready in a few minutes;
            this page follows its progress.
          </p>
          <div className="mt-4">
            <AreaInput label="Your SSH public key (optional)" rows={3} value={sshKey}
                       hint="Added alongside the team's keys. A password is also made and shown once."
                       onChange={setSshKey} />
          </div>
          {error && <p className="mt-3 text-xs text-bad">{error}</p>}
        </Modal>
      )}

      {login && (
        <Modal title={`Login for ${login.server}`} compact onClose={() => setLogin(null)}
               footer={<Button variant="primary" onClick={() => setLogin(null)}>I have saved it</Button>}>
          <div className="space-y-2 text-sm">
            <p className="flex items-center justify-between gap-2"><span className="text-ink-2">User</span>
              <span className="font-mono text-ink">{login.user}</span></p>
            <p className="flex items-center justify-between gap-2"><span className="text-ink-2">Password</span>
              <CopyText text={login.password} /></p>
          </div>
          <p className={`mt-3 text-xs ${login.saved ? "text-ink-3" : "text-warnx"}`}>
            {login.saved
              ? "It is also saved, encrypted, in this project's Credentials."
              : "Save the password now. Sentinel does not keep it and cannot show it again."}
          </p>
        </Modal>
      )}

      {sizing && (
        <Modal title={`Change the size of ${sizing.server.name}`} onClose={() => setSizing(null)}
               footer={sizing.restartDue ? (
                 <>
                   <Button onClick={() => setSizing(null)}>Later</Button>
                   <Button variant="primary" spinning={busy === `reboot-${sizing.server.id}`}
                           disabled={!!busy}
                           onClick={async () => { await act(sizing.server, "reboot"); setSizing(null); }}>
                     Restart now
                   </Button>
                 </>
               ) : (
                 <>
                   <Button onClick={() => setSizing(null)}>Cancel</Button>
                   <Button variant="primary" spinning={busy === "resize"}
                           disabled={busy === "resize"
                             || !(Number(sizing.disk_gb) >= sizing.server.disk_gb)}
                           onClick={() => void saveSize()}>Save</Button>
                 </>
               )}>
          {sizing.restartDue ? (
            <p className="text-sm text-ink-2">
              Saved: {sizing.server.cores} CPU, {sizing.server.memory_mb / 1024} GB memory,
              {" "}{sizing.server.disk_gb} GB disk. The server applies the new size when it restarts
              {" "}- anything running on it stops for a minute.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <SelectInput label="CPU cores" value={String(sizing.cores)}
                             options={(data.choices?.cores ?? [sizing.cores]).map((c) =>
                               ({ value: String(c), label: `${c} CPU` }))}
                             onChange={(v) => setSizing({ ...sizing, cores: Number(v) })} />
                <SelectInput label="Memory" value={String(sizing.memory_mb)}
                             options={(data.choices?.memory_mb ?? [sizing.memory_mb]).map((m) =>
                               ({ value: String(m), label: `${m / 1024} GB` }))}
                             onChange={(v) => setSizing({ ...sizing, memory_mb: Number(v) })} />
                <TextInput label="Disk (GB)" type="number" value={sizing.disk_gb}
                           hint={`Can grow, not shrink - now ${sizing.server.disk_gb} GB`}
                           onChange={(v) => setSizing({ ...sizing, disk_gb: v })} />
              </div>
              <p className="mt-3 text-xs text-ink-3">
                Sentinel checks the host has the memory and disk free first. A CPU or memory change
                takes effect after a restart; a bigger disk is ready after a restart too.
              </p>
            </>
          )}
          {error && <p className="mt-3 text-xs text-bad">{error}</p>}
        </Modal>
      )}

      {confirmDelete && (
        <ConfirmDialog
          title={`Delete ${confirmDelete.name}?`}
          body={<>Proxmox VM {confirmDelete.vmid} and its disks are deleted for good. Anything on it is lost.</>}
          confirmLabel="Delete server"
          busy={busy === `delete-${confirmDelete.id}`}
          onClose={() => setConfirmDelete(null)}
          onConfirm={async () => {
            await act(confirmDelete, "delete");
            setConfirmDelete(null);
          }}
        />
      )}
    </div>
  );
}

/* ── Credentials ──────────────────────────────────────────────────────────── */

type Credential = {
  id: number; kind: string; kind_display: string; label: string; username: string;
  location: string; notes: string; has_secret: boolean; server: string;
  updated_at: string; updated_by: string;
};
type CredentialsPayload = {
  vault_ready: boolean; can_manage: boolean;
  kinds: { value: string; label: string }[];
  credentials: Credential[];
};
type CredForm = {
  id?: number; kind: string; label: string; username: string; secret: string;
  location: string; notes: string;
};

const KIND_ICON: Record<string, string> = {
  database: "records", server: "server", website: "globe", api: "link", email: "mail", other: "lock",
};

/** A secret, hidden until asked for; it hides itself again after 30 seconds. */
function SecretValue({ name, cred }: { name: string; cred: Credential }) {
  const [value, setValue] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    if (value === null) return;
    const t = setTimeout(() => setValue(null), 30000);
    return () => clearTimeout(t);
  }, [value]);

  async function reveal() {
    setBusy(true);
    setProblem("");
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(name)}/credentials/${cred.id}/reveal`,
                            { method: "POST" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setProblem(d.detail || "Could not open it.");
        return;
      }
      setValue(d.secret);
    } finally {
      setBusy(false);
    }
  }

  if (!cred.has_secret) return <span className="text-ink-3">—</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {value === null ? (
        <>
          <span className="font-mono text-[13px] tracking-widest text-ink-3">••••••••••</span>
          <button onClick={() => void reveal()} disabled={busy}
                  className="rounded px-1.5 py-0.5 text-[11px] font-medium text-brand ring-1 ring-stroke hover:bg-subtle disabled:opacity-50">
            {busy ? "Opening…" : "Reveal"}
          </button>
        </>
      ) : (
        <>
          <CopyText text={value} />
          <button onClick={() => setValue(null)}
                  className="rounded px-1.5 py-0.5 text-[11px] font-medium text-ink-2 ring-1 ring-stroke hover:bg-subtle">
            Hide
          </button>
        </>
      )}
      {problem && <span className="text-xs text-bad">{problem}</span>}
    </span>
  );
}

function CredentialsTab({ name }: { name: string }) {
  const enc = encodeURIComponent(name);
  const [data, setData] = useState<CredentialsPayload | null>(null);
  const [form, setForm] = useState<CredForm | null>(null);
  const [showSecret, setShowSecret] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [removing, setRemoving] = useState<Credential | null>(null);

  const load = useCallback(async () => {
    const r = await fetch(`/api/projects/${enc}/credentials`);
    setData(r.ok ? await r.json() : null);
  }, [enc]);

  useEffect(() => {
    // Fetching on open is the point of this effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  async function save() {
    if (!form) return;
    setBusy(true);
    setError("");
    try {
      const r = await fetch(form.id ? `/api/projects/${enc}/credentials/${form.id}`
                                    : `/api/projects/${enc}/credentials`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(d.detail || "Could not save.");
        return;
      }
      setForm(null);
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function remove(c: Credential) {
    setBusy(true);
    try {
      await fetch(`/api/projects/${enc}/credentials/${c.id}/delete`, { method: "POST" });
      setRemoving(null);
      await load();
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <Section><p className="text-sm text-ink-2">Loading…</p></Section>;
  if (!data.vault_ready) {
    return <EmptyState icon="lock" title="Credentials are not set up"
                       hint="Sentinel needs SENTINEL_VAULT_KEY in its .env to keep passwords encrypted." />;
  }

  const blank: CredForm = { kind: "database", label: "", username: "", secret: "", location: "", notes: "" };
  const add = data.can_manage
    ? <Button variant="primary" icon="plus" onClick={() => { setShowSecret(false); setForm(blank); }}>Add credential</Button>
    : undefined;

  return (
    <div className="space-y-4">
      {data.credentials.length === 0 ? (
        <EmptyState icon="lock" title="No credentials yet"
                    hint="Database passwords, server logins, admin accounts and API keys for this project. Stored encrypted."
                    action={add} />
      ) : (
        <Section title={`Credentials (${data.credentials.length})`} right={add}>
          <ul className="-my-2 divide-y divide-stroke">
            {data.credentials.map((c) => (
              <li key={c.id} className="flex flex-wrap items-start gap-3 py-3">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-subtle">
                  <Icon name={KIND_ICON[c.kind] ?? "lock"} className="h-4 w-4 text-ink-2" />
                </span>
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-sm font-semibold text-ink">
                    {c.label} <span className="ml-1 text-xs font-normal text-ink-3">{c.kind_display}</span>
                  </p>
                  <div className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
                    {c.username && (<><span className="text-ink-3">User</span><CopyText text={c.username} /></>)}
                    <span className="text-ink-3">Secret</span>
                    {data.can_manage ? <SecretValue name={name} cred={c} />
                      : <span className="text-xs text-ink-3">Administrators only</span>}
                    {c.location && (<><span className="text-ink-3">Where</span><CopyText text={c.location} /></>)}
                  </div>
                  {c.notes && <p className="whitespace-pre-wrap text-xs text-ink-2">{c.notes}</p>}
                  <p className="text-[11px] text-ink-3">
                    Updated {relativeTime(c.updated_at)}{c.updated_by && ` by ${c.updated_by}`}
                  </p>
                </div>
                {data.can_manage && (
                  <div className="flex items-center gap-1">
                    <Button variant="ghost" icon="edit"
                            onClick={() => {
                              setShowSecret(false);
                              setForm({ id: c.id, kind: c.kind, label: c.label, username: c.username,
                                        secret: "", location: c.location, notes: c.notes });
                            }}>Edit</Button>
                    <Button variant="ghost" icon="trash" onClick={() => setRemoving(c)}>Remove</Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
      <p className="text-xs text-ink-3">
        Secrets are encrypted and only opened when an administrator reveals one; each reveal is logged in Activity.
      </p>

      {form && (
        <Modal title={form.id ? `Edit ${form.label}` : "Add a credential"} onClose={() => setForm(null)}
               footer={
                 <>
                   <Button onClick={() => setForm(null)}>Cancel</Button>
                   <Button variant="primary" spinning={busy} disabled={busy || !form.label.trim()}
                           onClick={() => void save()}>Save</Button>
                 </>
               }>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <SelectInput label="Type" value={form.kind} options={data.kinds}
                         onChange={(v) => setForm({ ...form, kind: v })} />
            <TextInput label="Name" value={form.label} placeholder="e.g. Production database"
                       onChange={(v) => setForm({ ...form, label: v })} />
            <TextInput label="Username" value={form.username}
                       onChange={(v) => setForm({ ...form, username: v })} />
            <div>
              <TextInput label={form.id ? "Password or key (blank keeps the current one)" : "Password or key"}
                         type={showSecret ? "text" : "password"} value={form.secret}
                         onChange={(v) => setForm({ ...form, secret: v })} />
              <button type="button" onClick={() => setShowSecret((x) => !x)}
                      className="mt-1 text-xs text-brand hover:underline">
                {showSecret ? "Hide" : "Show"}
              </button>
            </div>
            <div className="sm:col-span-2">
              <TextInput label="Where it is used" value={form.location}
                         placeholder="Host, URL or connection string - without the password"
                         onChange={(v) => setForm({ ...form, location: v })} />
            </div>
            <div className="sm:col-span-2">
              <AreaInput label="Notes" rows={3} value={form.notes}
                         onChange={(v) => setForm({ ...form, notes: v })} />
            </div>
          </div>
          {error && <p className="mt-3 text-xs text-bad">{error}</p>}
        </Modal>
      )}

      {removing && (
        <ConfirmDialog title={`Remove ${removing.label}?`}
                       body={<>The stored secret is deleted. This cannot be undone.</>}
                       confirmLabel="Remove" busy={busy}
                       onClose={() => setRemoving(null)}
                       onConfirm={() => void remove(removing)} />
      )}
    </div>
  );
}

/* ── Docs ─────────────────────────────────────────────────────────────────── */

type DocEntry = {
  id: number; sha: string; short_sha: string; url: string; repo: string; repo_id: number;
  committed_at: string | null; author: string; kind: string; kind_label: string;
  title: string; body: string; additions: number; deletions: number; source: string;
  files: { filename: string; status: string; additions: number; deletions: number }[];
};
type DocsPayload = {
  github_configured: boolean; ai: boolean; checking: boolean;
  repos: { id: number; name: string; url: string }[];
  entries: DocEntry[];
};

const KIND_TONE: Record<string, Tone> = {
  feat: "good", fix: "warn", perf: "info", refactor: "info", docs: "accent",
};

function DocCard({ e }: { e: DocEntry }) {
  const [showFiles, setShowFiles] = useState(false);
  return (
    <article className="rounded-xl bg-surface p-4 ring-panel">
      <header className="flex flex-wrap items-center gap-2">
        <Badge tone={KIND_TONE[e.kind] ?? "neutral"}>{e.kind_label}</Badge>
        <h3 className="min-w-0 flex-1 text-sm font-semibold text-ink">{e.title}</h3>
        {e.source === "ai" && <span className="text-[11px] text-ink-3">written by AI</span>}
      </header>
      <p className="mt-1 text-xs text-ink-3">
        {e.author} · {e.committed_at ? new Date(e.committed_at).toLocaleString(undefined,
          { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""} · {e.repo}{" "}
        <a href={e.url} target="_blank" rel="noreferrer" className="font-mono text-brand hover:underline">{e.short_sha}</a>
        {" "}· <span className="text-good">+{e.additions}</span> <span className="text-bad">-{e.deletions}</span>
      </p>
      {e.body && (
        <div className="prose-sm mt-3 max-w-none text-sm text-ink-2">
          <Markdown source={e.body.replace(/\*\*Files changed \(\d+\)\*\*[\s\S]*$/, "").trim()} />
        </div>
      )}
      {e.files.length > 0 && (
        <div className="mt-3">
          <button onClick={() => setShowFiles((v) => !v)}
                  className="text-xs font-medium text-brand hover:underline">
            {showFiles ? "Hide" : "Show"} {e.files.length} changed file{e.files.length === 1 ? "" : "s"}
          </button>
          {showFiles && (
            <ul className="mt-2 space-y-0.5 rounded-lg bg-subtle/60 px-3 py-2 font-mono text-[12px]">
              {e.files.map((f) => (
                <li key={f.filename} className="flex items-center gap-2">
                  <span className="w-16 shrink-0 text-ink-3">{f.status}</span>
                  <span className="min-w-0 flex-1 truncate text-ink-2" title={f.filename}>{f.filename}</span>
                  <span className="text-good">+{f.additions}</span>
                  <span className="text-bad">-{f.deletions}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </article>
  );
}

function DocsTab({ name }: { name: string }) {
  const enc = encodeURIComponent(name);
  const [data, setData] = useState<DocsPayload | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const r = await fetch(`/api/projects/${enc}/docs`);
    setData(r.ok ? await r.json() : null);
  }, [enc]);

  useEffect(() => {
    // Fetching on open is the point of this effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // While a check is running, follow it until the new entries are in.
  useEffect(() => {
    if (!data?.checking) return;
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [data?.checking, load]);

  async function check() {
    setError("");
    const r = await fetch(`/api/projects/${enc}/docs/sync`, { method: "POST" });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      setError(d.detail || "Could not check for new commits.");
      return;
    }
    setData((d) => d && { ...d, checking: true });
  }

  if (!data) return <Section><p className="text-sm text-ink-2">Loading…</p></Section>;
  if (data.repos.length === 0) {
    return <EmptyState icon="docs" title="No repository on this project"
                       hint="Assign one under GitHub, and every commit pushed to it is written up here as documentation." />;
  }

  // Grouped by month, newest first - the order the entries arrive in.
  const months: [string, DocEntry[]][] = [];
  for (const e of data.entries) {
    const key = e.committed_at ? new Date(e.committed_at).toLocaleDateString(undefined,
      { month: "long", year: "numeric" }) : "Undated";
    const last = months[months.length - 1];
    if (last && last[0] === key) last[1].push(e); else months.push([key, [e]]);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-sm text-ink-2">
          Written from the commits on {data.repos.map((r) => r.name).join(", ")}.
          New commits are picked up every 10 minutes{data.ai ? ", and explained by AI" : ""}.
        </p>
        <Button icon="sync" spinning={data.checking} disabled={data.checking || !data.github_configured}
                onClick={() => void check()}>
          {data.checking ? "Checking…" : "Check for new commits"}
        </Button>
      </div>
      {error && <p className="rounded-lg bg-bad-bg px-3 py-2 text-xs text-bad">{error}</p>}

      {data.entries.length === 0 ? (
        <EmptyState icon="docs" title={data.checking ? "Reading the commits…" : "Nothing written yet"}
                    hint="The newest commits are written up first; this takes a moment." />
      ) : months.map(([month, entries]) => (
        <section key={month} className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-3">{month}</h2>
          {entries.map((e) => <DocCard key={e.id} e={e} />)}
        </section>
      ))}
    </div>
  );
}

/* ── Feedback ─────────────────────────────────────────────────────────────── */

type FeedbackItem = {
  id: number; kind: string; kind_display: string; title: string; description: string; area: string;
  submitter_name: string; submitter_email: string; submitter_role: string;
  status: string; status_display: string; manager_note: string; source: string; created_by: string;
  task: { id: number; title: string; status: string } | null;
  created_at: string;
  attachments: { id: number; name: string; width: number; height: number; url: string }[];
};
type FeedbackPayload = {
  feedback: FeedbackItem[]; counts: Record<string, number>;
  kinds: { value: string; label: string }[]; statuses: { value: string; label: string }[];
  link: { url: string; token: string; active: boolean } | null;
  is_admin: boolean; max_files: number;
};

const KIND_FEEDBACK_TONE: Record<string, Tone> = {
  problem: "bad", change: "info", idea: "good", question: "neutral",
};

/* The type picker in "Add feedback": an icon and a one-line hint per kind. */
const FEEDBACK_KIND_META: Record<string, { icon: string; hint: string }> = {
  problem: { icon: "alert", hint: "A bug, error or something broken" },
  change: { icon: "edit", hint: "Make something work differently" },
  idea: { icon: "flag", hint: "An improvement worth making" },
  question: { icon: "inbox", hint: "Something that needs an answer" },
};

function FeedbackCard({ f, name, data, onChange, onView }: {
  f: FeedbackItem; name: string; data: FeedbackPayload; onChange: () => Promise<void>;
  onView: (src: string, label: string) => void;
}) {
  const enc = encodeURIComponent(name);
  const [note, setNote] = useState(f.manager_note);
  const [busy, setBusy] = useState("");

  async function update(body: Record<string, string>, label: string) {
    setBusy(label);
    try {
      await fetch(`/api/projects/${enc}/feedback/${f.id}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      await onChange();
    } finally {
      setBusy("");
    }
  }

  async function post(path: string, label: string) {
    setBusy(label);
    try {
      await fetch(`/api/projects/${enc}/feedback/${f.id}${path}`, { method: "POST" });
      await onChange();
    } finally {
      setBusy("");
    }
  }

  const who = [f.submitter_name || (f.source === "staff" ? f.created_by : "Someone"), f.submitter_role]
    .filter(Boolean).join(", ");
  return (
    <article className="rounded-xl bg-surface p-4 ring-panel">
      <header className="flex flex-wrap items-start gap-2">
        <Badge tone={KIND_FEEDBACK_TONE[f.kind] ?? "neutral"}>{f.kind_display}</Badge>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-ink">
            <span className="mr-1 text-ink-3">#{f.id}</span>{f.title}
          </h3>
          <p className="mt-0.5 text-xs text-ink-3">
            {who} · {new Date(f.created_at).toLocaleString(undefined,
              { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
            {" "}· {f.source === "form" ? "feedback form" : "added by staff"}
            {f.submitter_email && <> · <a href={`mailto:${f.submitter_email}`} className="text-brand hover:underline">{f.submitter_email}</a></>}
          </p>
        </div>
        <select value={f.status} disabled={!!busy} aria-label="Status"
                onChange={(e) => void update({ status: e.target.value }, "status")}
                className="h-8 rounded-lg bg-surface px-2 text-sm text-ink ring-control focus-ring">
          {data.statuses.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </header>

      {f.area && <p className="mt-2 text-xs text-ink-2"><span className="text-ink-3">Where: </span>{f.area}</p>}
      {f.description && <p className="mt-2 whitespace-pre-wrap text-sm text-ink-2">{f.description}</p>}

      {f.attachments.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {f.attachments.map((a) => (
            <li key={a.id}>
              <button onClick={() => onView(a.url, a.name)} title={`${a.name} - click to enlarge`}
                      className="block overflow-hidden rounded-md ring-1 ring-stroke transition hover:ring-brand">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={a.url} alt={a.name} className="h-24 w-36 object-cover" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 rounded-lg bg-subtle/50 p-3">
        <label className="block text-xs font-medium text-ink-2">
          Manager&apos;s note
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
                    placeholder="What is being done about it, or why not"
                    className="mt-1 w-full rounded-md bg-surface px-2.5 py-1.5 text-sm text-ink ring-control focus-ring" />
        </label>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {note !== f.manager_note && (
            <Button variant="primary" spinning={busy === "note"} disabled={!!busy}
                    onClick={() => void update({ manager_note: note }, "note")}>Save note</Button>
          )}
          {f.task ? (
            <Link href={`${projectHref(name, "tasks")}&view=board&task=${f.task.id}`}
                  className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium text-brand hover:bg-surface">
              <Icon name="tasks" className="h-4 w-4" /> Task: {f.task.title}
            </Link>
          ) : (
            <Button icon="plus" spinning={busy === "task"} disabled={!!busy}
                    onClick={() => void post("/task", "task")}>Create task</Button>
          )}
          {data.is_admin && (
            <Button variant="ghost" icon="trash" className="ml-auto" disabled={!!busy}
                    onClick={() => { if (window.confirm(`Delete feedback #${f.id}? Its screenshots go too.`)) void post("/delete", "delete"); }}>
              Delete
            </Button>
          )}
        </div>
      </div>
    </article>
  );
}

const EMAIL_RE = /^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/;

/* Email addresses as chips: type or paste them, separated by commas, spaces
   or new lines. Anything that isn't an address stays as a red chip so it can
   be fixed rather than silently dropped. */
function EmailChips({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const commit = (text: string) => {
    const parts = text.split(/[\s,;]+/).map((s) => s.trim().replace(/^<|>$/g, "")).filter(Boolean);
    setDraft("");
    if (!parts.length) return;
    const next = [...value];
    for (const p of parts) if (!next.some((x) => x.toLowerCase() === p.toLowerCase())) next.push(p);
    onChange(next);
  };
  return (
    <div onClick={() => input.current?.focus()}
         className="flex min-h-[40px] cursor-text flex-wrap items-center gap-1.5 rounded-lg bg-surface px-2 py-1.5 ring-control focus-within:ring-2 focus-within:ring-brand/40">
      {value.map((a) => {
        const ok = EMAIL_RE.test(a);
        return (
          <span key={a} title={ok ? a : "Not an email address"}
                className={`inline-flex max-w-full items-center gap-1 rounded-md py-0.5 pl-2 pr-1 text-[13px] ${
                  ok ? "bg-subtle text-ink" : "bg-bad-bg text-bad"}`}>
            <span className="truncate">{a}</span>
            <button type="button" aria-label={`Remove ${a}`}
                    onClick={(e) => { e.stopPropagation(); onChange(value.filter((x) => x !== a)); }}
                    className="rounded px-1 text-ink-3 hover:bg-surface hover:text-ink">×</button>
          </span>
        );
      })}
      <input
        ref={input}
        value={draft}
        inputMode="email"
        autoComplete="email"
        aria-label="Email addresses"
        placeholder={value.length ? "" : "name@company.com, another@company.com"}
        onChange={(e) => {
          const v = e.target.value;
          if (/[,;\s]$/.test(v)) commit(v); else setDraft(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); commit(draft); }
          else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
        }}
        onPaste={(e) => { e.preventDefault(); commit(`${draft} ${e.clipboardData.getData("text")}`); }}
        onBlur={() => commit(draft)}
        className="min-w-[12rem] flex-1 bg-transparent px-1 py-0.5 text-sm text-ink outline-none placeholder:text-ink-3"
      />
    </div>
  );
}

/* Email the form to anyone. Sentinel sends it from the company mailbox with
   one button that opens the form; no account is needed to fill it in. */
function SendFeedbackModal({ name, publicUrl, onClose, onSent }: {
  name: string; publicUrl: string; onClose: () => void; onSent: () => void;
}) {
  const [to, setTo] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<null | { sent: string[]; failed: string[] }>(null);
  const valid = to.filter((a) => EMAIL_RE.test(a));
  const invalid = to.length - valid.length;

  async function send() {
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(name)}/feedback/send`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipients: valid, message }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok && !d.sent?.length) { setError(d.detail || "Could not send it."); return; }
      setResult({ sent: d.sent ?? [], failed: d.failed ?? [] });
      onSent();
    } catch {
      setError("Could not reach Sentinel's server.");
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <Modal title="Feedback form sent" onClose={onClose} compact
             footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
        <p className="text-sm text-ink">
          Sent to {result.sent.length} {result.sent.length === 1 ? "person" : "people"}. They can fill in the
          form straight from the email.
        </p>
        {result.failed.length > 0 && (
          <p className="mt-2 text-sm text-bad">Couldn&apos;t send to {result.failed.join(", ")}. Try those again.</p>
        )}
      </Modal>
    );
  }

  return (
    <Modal title="Send the feedback form" onClose={onClose}
           footer={
             <>
               <Button onClick={onClose}>Cancel</Button>
               <Button variant="primary" icon="mail" spinning={busy} disabled={busy || valid.length === 0 || invalid > 0}
                       onClick={() => void send()}>
                 {valid.length > 1 ? `Send to ${valid.length} people` : "Send"}
               </Button>
             </>
           }>
      <div className="space-y-4">
        <div>
          <div className="mb-1 text-[13px] font-medium text-ink">To</div>
          <EmailChips value={to} onChange={setTo} />
          <p className={`mt-1 text-[12px] ${invalid ? "text-bad" : "text-ink-3"}`}>
            {invalid
              ? `${invalid} of these ${invalid === 1 ? "isn't an email address" : "aren't email addresses"} - remove or fix ${invalid === 1 ? "it" : "them"}.`
              : "Anyone - they don't need a Sentinel login. Separate addresses with commas or press Enter."}
          </p>
        </div>
        <AreaInput label="Message (optional)" value={message} onChange={setMessage} rows={3}
                   hint="Shown above the button in the email." />
        <p className="rounded-lg bg-subtle px-3 py-2 text-[12px] text-ink-2">
          They&apos;ll get an email titled <b className="text-ink">&quot;Your feedback on {name}&quot;</b> with a button
          that opens {publicUrl ? <span className="break-all font-mono">{publicUrl}</span> : "the form (a link is made when you send)"}.
        </p>
        {error && <p className="text-sm text-bad">{error}</p>}
      </div>
    </Modal>
  );
}

function FeedbackTab({ name }: { name: string }) {
  const enc = encodeURIComponent(name);
  const [data, setData] = useState<FeedbackPayload | null>(null);
  const [status, setStatus] = useState("all");
  const [kind, setKind] = useState("all");
  const [viewing, setViewing] = useState<{ src: string; label: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ kind: "problem", title: "", description: "", area: "", name: "", role: "" });
  const [shots, setShots] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [sending, setSending] = useState(false);
  const [dragging, setDragging] = useState(false);
  const shotPicker = useRef<HTMLInputElement>(null);
  const maxShots = data?.max_files ?? 6;
  const addShots = useCallback((files: File[]) => {
    const images = files.filter((f) => f.type.startsWith("image/"));
    if (images.length) setShots((cur) => [...cur, ...images].slice(0, maxShots));
  }, [maxShots]);
  // Previews for the thumbnails, released when the list changes.
  const shotUrls = useMemo(() => shots.map((f) => URL.createObjectURL(f)), [shots]);
  useEffect(() => () => shotUrls.forEach((u) => URL.revokeObjectURL(u)), [shotUrls]);
  // While the form is open, a pasted screenshot (Print Screen, then Ctrl+V)
  // lands in the list without saving it to a file first.
  useEffect(() => {
    if (!adding) return;
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []);
      if (files.some((f) => f.type.startsWith("image/"))) { e.preventDefault(); addShots(files); }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [adding, addShots]);

  const load = useCallback(async () => {
    const r = await fetch(`/api/projects/${enc}/feedback`);
    setData(r.ok ? await r.json() : null);
  }, [enc]);

  useEffect(() => {
    // Fetching on open is the point of this effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  async function linkAction(action: string) {
    if (action === "regenerate" && !window.confirm("Make a new link? The current one stops working."))
      return;
    await fetch(`/api/projects/${enc}/feedback/link`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }),
    });
    await load();
  }

  async function addFeedback() {
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      Object.entries(form).forEach(([k, v]) => body.append(k, v));
      shots.forEach((f) => body.append("screenshots", f));
      const r = await fetch(`/api/projects/${enc}/feedback`, { method: "POST", body });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(d.detail || "Could not add it.");
        return;
      }
      setAdding(false);
      setForm({ kind: "problem", title: "", description: "", area: "", name: "", role: "" });
      setShots([]);
      await load();
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <Section><p className="text-sm text-ink-2">Loading…</p></Section>;

  /* The link people are sent is the public one, so it works for anyone who
     gets it. "Open form" previews it from wherever Sentinel is running, which
     is what you want while testing locally. */
  const publicUrl = data.link?.url ?? "";
  const previewUrl = data.link && typeof window !== "undefined"
    ? `${window.location.origin}/feedback/${data.link.token}` : publicUrl;
  const shareText = `Please share your feedback on ${name} - report a problem, ask for a change or suggest an improvement: ${publicUrl}`;
  const shown = data.feedback.filter((f) =>
    (status === "all" || f.status === status) && (kind === "all" || f.kind === kind));

  return (
    <div className="space-y-4">
      <Section title="Feedback form">
        {!data.link ? (
          <div className="flex flex-wrap items-center gap-3">
            <p className="flex-1 text-sm text-ink-2">
              A form anyone can fill in - clients, inspectors, suppliers - with no login. They can report a
              problem, ask for a change, suggest something or ask a question, with screenshots.
            </p>
            <Button icon="link" onClick={() => void linkAction("create")}>Make a link</Button>
            <Button variant="primary" icon="mail" onClick={() => setSending(true)}>Send by email</Button>
          </div>
        ) : (
          <div className="space-y-2.5">
            <p className="text-sm text-ink-2">
              Anyone with this link can fill in the form - no login needed. Send it by email, share it, or copy it
              into a message.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`min-w-0 flex-1 basis-64 truncate rounded-md bg-canvas px-3 py-1.5 font-mono text-xs ring-control ${
                data.link.active ? "text-ink" : "text-ink-3 line-through"}`}>{publicUrl}</span>
              <Button variant="primary" icon="mail" disabled={!data.link.active} onClick={() => setSending(true)}>
                Send
              </Button>
              <Button icon="link" disabled={!data.link.active}
                      onClick={() => { void navigator.clipboard?.writeText(publicUrl); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
                {copied ? "Copied" : "Copy"}
              </Button>
              {data.link.active && (
                <a href={`https://wa.me/?text=${encodeURIComponent(shareText)}`} target="_blank" rel="noreferrer"
                   className="inline-flex items-center gap-1.5 rounded-md bg-surface px-2.5 py-1.5 text-sm font-medium text-ink ring-control hover:bg-subtle">
                  <Icon name="phone" className="h-4 w-4" /> WhatsApp
                </a>
              )}
              <a href={previewUrl} target="_blank" rel="noreferrer"
                 className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium text-ink-2 ring-control hover:bg-subtle">
                Open form
              </a>
              <Button onClick={() => void linkAction(data.link!.active ? "disable" : "enable")}>
                {data.link.active ? "Turn off" : "Turn on"}
              </Button>
              <Button variant="ghost" onClick={() => void linkAction("regenerate")}>New link</Button>
            </div>
          </div>
        )}
      </Section>

      {sending && (
        <SendFeedbackModal name={name} publicUrl={publicUrl}
                           onClose={() => setSending(false)} onSent={() => void load()} />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Pill active={status === "all"} onClick={() => setStatus("all")}>All {data.feedback.length}</Pill>
        {data.statuses.map((s) => (
          <Pill key={s.value} active={status === s.value} onClick={() => setStatus(s.value)}>
            {s.label} {data.counts[s.value] ?? 0}
          </Pill>
        ))}
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Type"
                className="h-9 rounded-lg bg-surface px-2 text-sm text-ink ring-control focus-ring">
          <option value="all">All types</option>
          {data.kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
        <Button variant="primary" icon="plus" className="ml-auto" onClick={() => { setError(""); setAdding(true); }}>
          Add feedback
        </Button>
      </div>

      {shown.length === 0 ? (
        <EmptyState icon="inbox" title={data.feedback.length ? "Nothing matches" : "No feedback yet"}
                    hint={data.feedback.length ? "Try another filter."
                      : "Share the feedback link with the people using the system, or add some yourself."} />
      ) : shown.map((f) => (
        <FeedbackCard key={f.id} f={f} name={name} data={data} onChange={load}
                      onView={(src, label) => setViewing({ src, label })} />
      ))}

      {viewing && (
        <Modal title={viewing.label} xl onClose={() => setViewing(null)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={viewing.src} alt={viewing.label} className="mx-auto mb-4 max-h-[70vh] w-auto rounded-md" />
        </Modal>
      )}

      {adding && (
        <Modal title="Add feedback" onClose={() => setAdding(false)}
               footer={
                 <>
                   <Button onClick={() => setAdding(false)}>Cancel</Button>
                   <Button variant="primary" spinning={busy} disabled={busy || !form.title.trim()}
                           onClick={() => void addFeedback()}>Add feedback</Button>
                 </>
               }>
          <div className="space-y-4">
            <fieldset>
              <legend className="mb-1.5 text-sm font-medium text-ink">What kind of feedback?</legend>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {data.kinds.map((k) => {
                  const meta = FEEDBACK_KIND_META[k.value];
                  const on = form.kind === k.value;
                  return (
                    <button key={k.value} type="button" aria-pressed={on}
                            onClick={() => setForm({ ...form, kind: k.value })}
                            className={`rounded-lg px-3 py-2.5 text-left transition ${on
                              ? "bg-brand/5 ring-2 ring-brand"
                              : "bg-surface ring-1 ring-stroke hover:bg-subtle"}`}>
                      <Icon name={meta?.icon ?? "inbox"} className={`h-4 w-4 ${on ? "text-brand" : "text-ink-3"}`} />
                      <span className={`mt-1.5 block text-[13px] font-medium ${on ? "text-ink" : "text-ink-2"}`}>{k.label}</span>
                      {meta && <span className="block text-[11px] leading-snug text-ink-3">{meta.hint}</span>}
                    </button>
                  );
                })}
              </div>
            </fieldset>

            <TextInput label="Title" value={form.title} onChange={(v) => setForm({ ...form, title: v })}
                       placeholder="A short summary, e.g. Save button hidden on tablets" />
            <AreaInput label="Details" rows={4} value={form.description}
                       onChange={(v) => setForm({ ...form, description: v })}
                       placeholder="What happened, what you expected, and the steps to see it again" />

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <TextInput label="Where in the system" value={form.area} placeholder="The screen, page or step"
                         onChange={(v) => setForm({ ...form, area: v })} />
              <TextInput label="Raised by" value={form.name} placeholder="Leave blank if it's you"
                         hint="e.g. who called it in" onChange={(v) => setForm({ ...form, name: v })} />
            </div>

            <div>
              <div className="mb-1.5 flex items-baseline justify-between">
                <span className="text-sm font-medium text-ink">Screenshots</span>
                <span className="text-[12px] text-ink-3">{shots.length} of {data.max_files}</span>
              </div>
              {shots.length < data.max_files && (
                <div role="button" tabIndex={0}
                     onClick={() => shotPicker.current?.click()}
                     onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); shotPicker.current?.click(); } }}
                     onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                     onDragLeave={() => setDragging(false)}
                     onDrop={(e) => { e.preventDefault(); setDragging(false); addShots(Array.from(e.dataTransfer.files)); }}
                     className={`flex cursor-pointer flex-col items-center rounded-lg border-2 border-dashed px-4 py-5 text-center transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 ${
                       dragging ? "border-brand bg-brand/5" : "border-stroke hover:bg-subtle/60"}`}>
                  <Icon name="upload" className="h-5 w-5 text-ink-3" />
                  <span className="mt-1.5 text-sm text-ink">
                    <span className="font-medium text-brand">Choose images</span>, drop them here, or paste a screenshot
                  </span>
                  <span className="mt-0.5 text-[12px] text-ink-3">PNG or JPG · up to {data.max_files}</span>
                  <input ref={shotPicker} type="file" accept="image/*" multiple className="hidden"
                         onChange={(e) => { addShots(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
                </div>
              )}
              {shots.length > 0 && (
                <ul className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-6">
                  {shots.map((f, i) => (
                    <li key={`${f.name}-${i}`} className="group relative">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={shotUrls[i]} alt={f.name} title={f.name}
                           className="aspect-square w-full rounded-md object-cover ring-1 ring-stroke" />
                      <button type="button" aria-label={`Remove ${f.name}`}
                              onClick={() => setShots((cur) => cur.filter((_, j) => j !== i))}
                              className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-black/60 text-white hover:bg-black/80">
                        <Icon name="x" className="h-3 w-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          {error && <p className="mt-3 text-sm text-bad">{error}</p>}
        </Modal>
      )}
    </div>
  );
}

/* ── Activity ─────────────────────────────────────────────────────────────── */

function ActivityTab({ activity }: { activity: Activity[] | null }) {
  const days = useMemo(() => {
    const by = new Map<string, Activity[]>();
    for (const a of activity ?? []) {
      const key = new Date(a.when).toLocaleDateString(undefined,
        { weekday: "long", day: "numeric", month: "long", year: "numeric" });
      by.set(key, [...(by.get(key) ?? []), a]);
    }
    return [...by.entries()];
  }, [activity]);

  if (!activity) return <Section><p className="text-sm text-ink-2">Loading…</p></Section>;
  if (activity.length === 0) {
    return <EmptyState icon="clock" title="Nothing recorded yet"
                       hint="Changes to this project and its tasks will show here." />;
  }
  return (
    <div className="space-y-4">
      {days.map(([day, rows]) => (
        <Section key={day} title={day}>
          <ul className="space-y-2">
            {rows.map((a) => (
              <li key={a.id} className="flex gap-3 text-sm">
                <span className="w-16 shrink-0 whitespace-nowrap tabular-nums text-ink-3">
                  {new Date(a.when).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                </span>
                <span className="text-ink-2">
                  {a.summary}{a.task && <span className="text-ink-3"> · {a.task}</span>}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      ))}
    </div>
  );
}
