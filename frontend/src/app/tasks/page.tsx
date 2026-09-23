"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Button, EmptyState, Pill,
  TextInput, AreaInput, SelectInput, ContextMenu, ConfirmDialog, Modal,
  type MenuItem,
} from "@/components/ui";
import {
  BUCKETS, statusesIn, STATE_DOT, statusTone, PRIORITY_STRIP, PRIORITY_TEXT, PRIORITY_ORDER,
  NO_PROJECT, NO_LIST, MONTHS, DOW,
  parseISO, toISO, addDays, startOfDay, dayDiff, monthMatrix, periodLabel,
  labelOf, fmtHours, rollUp, sumTotals,
  DueChip, TimeChip, ProgressBar,
  type Task, type Choice, type Payload, type Totals,
} from "@/components/tracker";
import { Workload } from "@/components/workload";
import { AssigneePicker } from "@/components/assignee";

const VIEWS = ["Board", "Calendar", "Gantt", "Workload"] as const;
type View = (typeof VIEWS)[number];
const VIEW_ICON: Record<View, string> = {
  Board: "board", Calendar: "calendar", Gantt: "gantt", Workload: "users",
};
const GROUPINGS = ["Bucket", "Priority", "Project"] as const;
type Grouping = (typeof GROUPINGS)[number];
const PRIORITY_FILTERS = ["All", "Critical", "High", "Medium", "Low"] as const;

/* Ten flat statuses are hard to scan, so the dropdown groups them by what the
   work is actually doing. The values are unchanged - this is presentation. */
const BUCKET_GROUP: Record<string, string> = {
  backlog: "Not started", todo: "Not started",
  in_progress: "Working", in_progress_guidance: "Working", review: "Working",
  on_hold: "Waiting", review_pending: "Waiting", discrepancy: "Waiting",
  done: "Closed", cancelled: "Closed",
};

/* The two "Completed (…)" labels are long enough to stretch the control; the
   group heading already says they are waiting on somebody. */
const BUCKET_LABEL: Record<string, string> = {
  in_progress_guidance: "In Progress — needs guidance",
  review_pending: "Completed — review pending",
  discrepancy: "Completed — data discrepancy",
};
type PriorityFilter = (typeof PRIORITY_FILTERS)[number];

/* A status select that carries its colour, grouped by what the work is doing.

   Each <option> is given its own fill: left alone they inherit the select's
   background, which paints the whole open list in the current choice's colour
   and makes ten statuses look like one. Safari and macOS Chrome ignore option
   colours, so the chosen status also shows as a dot on the control itself -
   the colour is a second signal, never the only one. */
function StatusSelect({ id, value, statuses, onChange, className = "" }: {
  id?: string;
  value: string;
  statuses: Choice[];
  onChange: (v: string) => void;
  className?: string;
}) {
  const tone = statusTone(value);
  const groups = useMemo(() => {
    const order: string[] = [];
    const byGroup = new Map<string, Choice[]>();
    for (const c of statuses) {
      const g = BUCKET_GROUP[c[0]] ?? "Other";
      if (!byGroup.has(g)) { byGroup.set(g, []); order.push(g); }
      byGroup.get(g)!.push(c);
    }
    return order.map((g) => [g, byGroup.get(g)!] as const);
  }, [statuses]);

  return (
    <div className="relative">
      <span className={`pointer-events-none absolute left-2.5 top-1/2 h-2 w-2 -translate-y-1/2
                        rounded-full ${STATE_DOT[value] ?? "bg-ink-3"}`} />
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ backgroundColor: tone.bg, color: tone.fg }}
        className={`h-9 w-full cursor-pointer rounded-md pl-6 pr-2 text-sm font-medium
                    ring-control focus-ring ${className}`}
      >
        {groups.map(([group, items]) => (
          <optgroup key={group} label={group}>
            {items.map(([v, l]) => {
              const t = statusTone(v);
              return (
                <option key={v} value={v} style={{ backgroundColor: t.bg, color: t.fg }}>
                  {BUCKET_LABEL[v] ?? l}
                </option>
              );
            })}
          </optgroup>
        ))}
      </select>
    </div>
  );
}

type Form = {
  title: string; description: string; status: string; priority: string;
  project_name: string; list_name: string; company: string;
  start_date: string; end_date: string;
  start_time: string; end_time: string;
  estimated_hours: string; actual_hours: string;
  assignees: number[];
};

function TasksInner() {
  // Sidebar project links arrive as ?project=<name>, so the page opens filtered
  // to that project with it already expanded.
  const params = useSearchParams();
  const initialProject = params?.get("project");

  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<Payload | null>(null);
  // Starts true so the first paint shows the loading state without the mount
  // effect having to set it synchronously.
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<View>("Board");
  const [grouping, setGrouping] = useState<Grouping>("Bucket");
  const [q, setQ] = useState("");
  const [priority, setPriority] = useState<PriorityFilter>("All");
  const [project, setProject] = useState(
    initialProject ? (initialProject || NO_PROJECT) : "All");
  const [hideDone, setHideDone] = useState(false);

  // Which projects belong to the workspace being viewed. Empty array means
  // "not scoped to a workspace"; null means "not loaded yet".
  const [wsProjects, setWsProjects] = useState<string[] | null>(null);
  const [workspace, setWorkspace] = useState<string | null>(null);

  const [selected, setSelected] = useState<number | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [creating, setCreating] = useState<
    { parent: Task | null; status: string; project: string; list: string } | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [newList, setNewList] = useState<{ project: string; name: string } | null>(null);
  // Inline list creation from inside the task dialog: a project with no
  // lists otherwise leaves a select whose only option is a dash.
  const [inlineList, setInlineList] = useState("");
  const [addingList, setAddingList] = useState(false);
  const [dayTask, setDayTask] = useState<
    { start: string; end: string; title: string; project: string; list: string;
      priority: string; assignees: number[]; error: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [dragId, setDragId] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; task: Task } | null>(null);
  const [confirming, setConfirming] = useState<Task | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [month, setMonth] = useState(() => {
    const n = new Date();
    return { y: n.getFullYear(), m: n.getMonth() };
  });
  const newRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/tasks");
      if (!r.ok) throw new Error(String(r.status));
      setData(await r.json());
    } catch {
      setData({
        tasks: [], counts: {}, projects: [], lists: {}, statuses: [], priorities: [],
        companies: [], total: 0,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  async function refresh() {
    setLoading(true);
    await load();
  }

  // Client-side navigation from the sidebar changes ?project= without
  // remounting the page, so the filter is synced here rather than only seeded
  // from the initial render.
  useEffect(() => {
    const p = params?.get("project");
    // Syncing state from the URL is the point of this effect: the sidebar
    // navigates client-side, so the param changes without a remount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProject(p == null ? "All" : (p || NO_PROJECT));
    // Opening a project should land on its calendar - that is the view that
    // answers "what is happening when".
    if (p != null) setView("Calendar");
    // The sidebar's "Add list" arrives as ?addlist=1 alongside the project.
    if (p && params?.get("addlist")) {
       
      setNewList({ project: p, name: "" });
    }

    // A workspace link shows everything inside it at once, so the project
    // filter stays on "All" and the workspace does the narrowing instead.
    const w = params?.get("workspace");
     
    setWorkspace(w);
    if (!w) {
       
      setWsProjects(null);
      return;
    }
    fetch("/api/tasks/projects")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => {
        const found = (d.workspaces ?? []).find((x: { name: string }) => x.name === w);
        setWsProjects(found ? found.projects : []);
      })
      .catch(() => setWsProjects([]));
  }, [params]);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "tasks")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // load() only updates state after awaiting the fetch, so nothing re-renders
    // synchronously here; the rule cannot see through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // `data?.x ?? []` would be a fresh array every render, defeating the memos.
  const all = useMemo(() => data?.tasks ?? [], [data]);
  const statuses = useMemo<Choice[]>(() => data?.statuses ?? [], [data]);
  const priorities = useMemo<Choice[]>(() => data?.priorities ?? [], [data]);
  const byId = useMemo(() => new Map(all.map((t) => [t.id, t])), [all]);
  const sel = selected != null ? byId.get(selected) ?? null : null;

  const childrenOf = useMemo(() => {
    const m = new Map<number, Task[]>();
    for (const t of all) {
      if (t.parent == null) continue;
      const list = m.get(t.parent) ?? [];
      list.push(t);
      m.set(t.parent, list);
    }
    for (const list of m.values()) {
      list.sort((a, b) =>
        (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9) || a.id - b.id);
    }
    return m;
  }, [all]);

  const kidsOf = useCallback((id: number) => childrenOf.get(id) ?? [], [childrenOf]);

  const matches = useCallback((t: Task) => {
    const needle = q.trim().toLowerCase();
    if (needle && !`${t.title} ${t.description} ${t.project_name}`.toLowerCase().includes(needle)) return false;
    if (priority !== "All" && t.priority !== priority.toLowerCase()) return false;
    if (project !== "All" && (t.project_name || NO_PROJECT) !== project) return false;
    // Scoped to a workspace: only its projects. wsProjects === null means the
    // page is not workspace-scoped at all.
    if (wsProjects !== null && !wsProjects.includes(t.project_name || "")) return false;
    if (hideDone && t.status === "done") return false;
    return true;
  }, [q, priority, project, hideDone, wsProjects]);

  const visible = useMemo(() => all.filter(matches), [all, matches]);

  /** Board columns show top-level tasks only - a bucket of flattened subtasks
   *  was unreadable at this volume. Subtask state lives on the card. */
  const columns = useMemo(() => {
    const cards = visible.filter((t) => t.parent == null);
    const sort = (a: Task, b: Task) =>
      (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9) ||
      (parseISO(a.end_date)?.getTime() ?? Infinity) - (parseISO(b.end_date)?.getTime() ?? Infinity) ||
      a.title.localeCompare(b.title);

    if (grouping === "Bucket") {
      return BUCKETS
        .map((key) => {
          // A column holds its own status plus the ones that qualify it, so a
          // task can never fall between the columns and disappear.
          const held = statusesIn(key);
          return {
            key, label: labelOf(statuses, key), dot: STATE_DOT[key],
            droppable: key as string | null,
            items: cards.filter((t) => held.includes(t.status)).sort(sort),
          };
        })
        // Backlog and On Hold are states a board need not always show; empty,
        // they are noise. The rest anchor the workflow and always stand.
        .filter((c) => !["backlog", "on_hold"].includes(c.key) || c.items.length > 0);
    }
    if (grouping === "Priority") {
      return ["critical", "high", "medium", "low"].map((key) => ({
        key, label: labelOf(priorities, key), dot: PRIORITY_STRIP[key],
        droppable: null as string | null,
        items: cards.filter((t) => t.priority === key).sort(sort),
      }));
    }
    const names = Array.from(new Set(cards.map((t) => t.project_name || NO_PROJECT))).sort();
    return names.map((key) => ({
      key, label: key, dot: "bg-brand", droppable: null as string | null,
      items: cards.filter((t) => (t.project_name || NO_PROJECT) === key).sort(sort),
    }));
  }, [visible, grouping, statuses, priorities]);

  const stats = useMemo(() => {
    const open = all.filter((t) => t.status !== "done");
    const today = startOfDay(new Date()).getTime();
    const totals = sumTotals(all.filter((t) => t.parent == null).map((t) => rollUp(t, kidsOf(t.id))));
    return {
      total: all.length,
      open: open.length,
      critical: open.filter((t) => t.priority === "critical").length,
      overdue: open.filter((t) => {
        const d = parseISO(t.end_date);
        return d && d.getTime() < today;
      }).length,
      done: all.filter((t) => t.status === "done").length,
      totals,
    };
  }, [all, kidsOf]);

  const weeks = useMemo(() => monthMatrix(month.y, month.m), [month]);

  /**
   * Lay scheduled tasks out as bars across each week row.
   *
   * A task spanning several weeks is cut into one segment per row, so the bar
   * reads as continuous down the grid. Segments are packed into lanes with a
   * first-fit sweep, which is what stops two overlapping tasks drawing on top
   * of each other.
   */
  const weekBars = useMemo(() => {
    const scheduled = visible
      .filter((t) => t.start_date || t.end_date)
      .map((t) => {
        const a = parseISO(t.start_date) ?? parseISO(t.end_date)!;
        const b = parseISO(t.end_date) ?? parseISO(t.start_date)!;
        return { t, s: a <= b ? a : b, e: b >= a ? b : a };
      })
      // Longest first: long bars claim the top lanes, which reads better than
      // a single-day task pushing a three-week span down the stack.
      .sort((x, y) => (dayDiff(y.s, y.e) - dayDiff(x.s, x.e))
        || x.s.getTime() - y.s.getTime());

    return weeks.map((week) => {
      const weekStart = week[0];
      const weekEnd = week[6];
      const lanes: { end: number }[] = [];
      const bars: {
        task: Task; startCol: number; span: number; lane: number;
        continuesLeft: boolean; continuesRight: boolean;
      }[] = [];

      for (const { t, s: start, e: end } of scheduled) {
        if (end < weekStart || start > weekEnd) continue;
        const from = start < weekStart ? weekStart : start;
        const to = end > weekEnd ? weekEnd : end;
        const startCol = dayDiff(weekStart, from);
        const span = dayDiff(from, to) + 1;

        // First lane whose last occupied column is before this bar starts.
        let lane = lanes.findIndex((l) => l.end < startCol);
        if (lane === -1) {
          lane = lanes.length;
          lanes.push({ end: startCol + span - 1 });
        } else {
          lanes[lane].end = startCol + span - 1;
        }

        bars.push({
          task: t, startCol, span, lane,
          continuesLeft: start < weekStart,
          continuesRight: end > weekEnd,
        });
      }
      return bars;
    });
  }, [visible, weeks]);

  /** Declare a list from inside the task dialog and select it straight away. */
  async function createInlineList() {
    if (!dayTask) return;
    const name = inlineList.trim();
    if (!name) return;
    setSaving(true);
    try {
      const r = await fetch("/api/tasks/lists/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project: dayTask.project === NO_PROJECT ? "" : dayTask.project,
          workspace: dayTask.project ? "" : (workspace ?? ""),
          name,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setDayTask({ ...dayTask, error: d.detail || "Could not create that list." });
        return;
      }
      await load();
      setDayTask({ ...dayTask, list: name, error: "" });
      setInlineList("");
      setAddingList(false);
    } finally {
      setSaving(false);
    }
  }

  async function createDayTask() {
    if (!dayTask) return;
    const title = dayTask.title.trim();
    if (!title) {
      setDayTask({ ...dayTask, error: "Give the task a title." });
      return;
    }
    if (dayTask.end && dayTask.end < dayTask.start) {
      setDayTask({ ...dayTask, error: "The due date cannot be before the start date." });
      return;
    }
    setSaving(true);
    try {
      const r = await fetch("/api/tasks/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          project_name: dayTask.project === NO_PROJECT ? "" : dayTask.project,
          list_name: dayTask.list,
          priority: dayTask.priority,
          status: "todo",
          start_date: dayTask.start,
          end_date: dayTask.end || dayTask.start,
          assignees: dayTask.assignees,
        }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setDayTask({ ...dayTask, error: d.detail || "Could not create the task." });
        return;
      }
      setDayTask(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  const gantt = useMemo(() => {
    const scheduled = visible
      .filter((t) => t.start_date || t.end_date)
      .map((t) => {
        const s = parseISO(t.start_date) ?? parseISO(t.end_date)!;
        const e = parseISO(t.end_date) ?? parseISO(t.start_date)!;
        return { t, s: s <= e ? s : e, e: e >= s ? e : s };
      })
      .sort((a, b) => a.s.getTime() - b.s.getTime() || a.t.title.localeCompare(b.t.title));

    const unscheduled = visible.filter((t) => !t.start_date && !t.end_date);
    if (scheduled.length === 0) return { rows: [], unscheduled, start: new Date(), days: 0 };

    let min = scheduled[0].s;
    let max = scheduled[0].e;
    for (const r of scheduled) {
      if (r.s < min) min = r.s;
      if (r.e > max) max = r.e;
    }
    const start = addDays(min, -2);
    // Cap the window: one far-future due date would otherwise stretch the grid
    // to thousands of columns.
    const days = Math.min(dayDiff(start, max) + 3, 180);
    return { rows: scheduled, unscheduled, start, days };
  }, [visible]);

  /** Optimistic single-field patch: the row moves immediately, then reconciles. */
  async function patch(t: Task, changes: Partial<Task>) {
    setData((cur) => cur && {
      ...cur,
      tasks: cur.tasks.map((x) => (x.id === t.id ? { ...x, ...changes } : x)),
    });
    try {
      const r = await fetch(`/api/tasks/${t.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(changes),
      });
      if (!r.ok) throw new Error(String(r.status));
    } finally {
      // Reconcile either way, so a rejected change does not stay on screen as
      // though it had been saved.
      await load();
    }
  }

  async function quickCreate(status: string, parent: Task | null, title: string,
                             projectName: string, listName = "") {
    const clean = title.trim();
    if (!clean) return;
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        title: clean, status, priority: "medium",
        project_name: parent?.project_name ?? (projectName === NO_PROJECT ? "" : projectName),
        list_name: parent?.list_name ?? (listName === NO_LIST ? "" : listName),
      };
      if (parent) body.parent = parent.id;
      await fetch("/api/tasks/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setNewTitle("");
      setCreating(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  /** Declared lists exist without tasks, so only the name is needed. */
  async function createList() {
    if (!newList) return;
    const name = newList.name.trim();
    if (!name) return setError("Give the list a name.");
    setSaving(true);
    setError("");
    try {
      // A list has to live somewhere. With a real project that is the project;
      // under "No project" it belongs to the workspace being viewed, and
      // sending neither is what made this fail with a 400.
      const project = newList.project === NO_PROJECT ? "" : newList.project;
      if (!project && !workspace) {
        throw new Error("Open a workspace or a project first — a list has to "
                      + "live inside one of them.");
      }
      const r = await fetch("/api/tasks/lists/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          project ? { project, name } : { workspace, name }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || "Could not create the list.");
      }
      setNewList(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the list.");
    } finally {
      setSaving(false);
    }
  }

  function beginCreate(status: string, parent: Task | null = null, projectName = "", listName = "") {
    /* Inside a workspace the board only lists that workspace's projects, so a
       task created against "" saves and then cannot be seen from the board it
       was created on. Fall back to the workspace's first project rather than
       to nothing; if it has none, the dialog explains why and blocks. */
    const fallback = workspace ? (wsProjects?.[0] ?? "") : "";
    const chosen = projectName || fallback;
    setCreating({ parent, status, project: chosen, list: listName });
    setNewTitle("");
    setTimeout(() => newRef.current?.focus(), 0);
  }

  function openEditor(t: Task) {
    setSelected(t.id);
    setError("");
    setForm({
      title: t.title, description: t.description, status: t.status, priority: t.priority,
      project_name: t.project_name, list_name: t.list_name, company: t.company,
      start_date: t.start_date ?? "", end_date: t.end_date ?? "",
      start_time: t.start_time ?? "", end_time: t.end_time ?? "",
      assignees: (t.assignees ?? []).map((a) => a.id),
      estimated_hours: t.estimated_hours != null ? String(t.estimated_hours) : "",
      actual_hours: t.actual_hours != null ? String(t.actual_hours) : "",
    });
  }

  async function saveEditor() {
    if (!sel || !form) return;
    if (!form.title.trim()) {
      setError("Title is required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const r = await fetch(`/api/tasks/${sel.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          start_date: form.start_date || null,
          end_date: form.end_date || null,
          start_time: form.start_time || null,
          end_time: form.end_time || null,
          assignees: form.assignees,
          estimated_hours: form.estimated_hours === "" ? null : form.estimated_hours,
          actual_hours: form.actual_hours === "" ? null : form.actual_hours,
        }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || d.errors?.join(" ") || `Save failed (${r.status})`);
      }
      await load();
      setForm(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  /** Ask first. The dialog does the deleting, in `reallyRemove`. */
  function remove(t: Task) {
    setConfirming(t);
  }

  async function reallyRemove(t: Task) {
    setDeleting(true);
    try {
      await fetch(`/api/tasks/${t.id}/delete`, { method: "DELETE" });
      if (selected === t.id) {
        setSelected(null);
        setForm(null);
      }
      await load();
    } finally {
      setDeleting(false);
      setConfirming(null);
    }
  }

  /** Duplicate a card, so a repeating job is not retyped from scratch. */
  async function duplicate(t: Task) {
    await fetch("/api/tasks/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: `${t.title} (copy)`,
        status: t.status,
        priority: t.priority,
        project_name: t.project_name || "",
        list_name: t.list_name || "",
        start_date: t.start_date || null,
        end_date: t.end_date || null,
        estimated_hours: t.estimated_hours ?? null,
        description: t.description || "",
        parent: t.parent ?? null,
      }),
    });
    await load();
  }

  /** What right-clicking a card offers. */
  function menuFor(t: Task): MenuItem[] {
    const items: MenuItem[] = [
      { label: "Edit", icon: "edit", onSelect: () => openEditor(t) },
      { label: "Duplicate", icon: "file", onSelect: () => void duplicate(t) },
    ];
    // The two moves people actually want from the board. Anything else is a
    // drag, or the editor.
    if (t.status !== "done") {
      items.push({ label: "Mark done", icon: "check", separated: true,
                   onSelect: () => void patch(t, { status: "done" }) });
    } else {
      items.push({ label: "Reopen", icon: "sync", separated: true,
                   onSelect: () => void patch(t, { status: "todo" }) });
    }
    items.push({ label: "Delete", icon: "trash", danger: true, separated: true,
                 onSelect: () => remove(t) });
    return items;
  }

  function onDrop(kind: "status" | "date", value: string) {
    const t = dragId != null ? byId.get(dragId) : null;
    setDragId(null);
    setDragOver(null);
    if (!t) return;
    if (kind === "status" && t.status !== value) void patch(t, { status: value });
    if (kind === "date" && t.end_date !== value) void patch(t, { end_date: value });
  }

  const projectOpts = ["All", ...(data?.projects ?? []), NO_PROJECT];

  /* The projects a new task may be filed under. Scoped to a workspace, only
     that workspace's own projects qualify - anything else is invisible from
     here the moment it is saved. */
  const createProjectOpts = workspace ? (wsProjects ?? []) : (data?.projects ?? []);
  /* Nothing to file it under and no "No project" escape hatch: saving would
     produce a task this board can never show. */
  const createBlocked = !!workspace && createProjectOpts.length === 0;
  const todayISO = toISO(new Date());

  /** Planner-style card, shared by the board and calendar. */
  /* `column` is the board column this card is sitting in, so the card can tell
     when its own status is not the column's plain case. Undefined elsewhere
     (the calendar, the tree), where there is no column to differ from. */
  function Card({ t, compact = false, column }: {
    t: Task; compact?: boolean; column?: string;
  }) {
    const kids = kidsOf(t.id);
    const doneKids = kids.filter((k) => k.status === "done").length;
    const totals = rollUp(t, kids);
    return (
      <article
        draggable
        onDragStart={() => setDragId(t.id)}
        onDragEnd={() => { setDragId(null); setDragOver(null); }}
        onClick={() => openEditor(t)}
        onContextMenu={(e) => {
          e.preventDefault();
          setMenu({ x: e.clientX, y: e.clientY, task: t });
        }}
        className={`cursor-grab overflow-hidden rounded-lg bg-surface ring-panel transition hover:ring-brand/40 active:cursor-grabbing ${
          dragId === t.id ? "opacity-40" : ""
        }`}
      >
        <div className={`h-1 w-full ${PRIORITY_STRIP[t.priority] ?? "bg-ink-3"}`} />
        <div className={compact ? "p-1.5" : "p-2.5"}>
          <p className={`leading-snug ${compact ? "truncate text-xs" : "text-sm"} font-medium ${
            t.status === "done" ? "text-ink-3 line-through" : "text-ink"
          }`}>
            {t.title}
          </p>
          {!compact && (
            <>
              {periodLabel(t) && (
                <p className="mt-1 text-[11px] text-ink-3">{periodLabel(t)}</p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span className={`text-[11px] font-semibold ${PRIORITY_TEXT[t.priority]}`}>
                  {labelOf(priorities, t.priority)}
                </span>
                {/* A column holds more than one status, so a card that is not
                    the column's plain case states which it is - otherwise
                    "needs guidance" or "cancelled" would read as ordinary. */}
                {t.status !== column && (
                  <span className="rounded px-1.5 py-0.5 text-[11px] font-semibold"
                        style={{ backgroundColor: statusTone(t.status).bg,
                                 color: statusTone(t.status).fg }}>
                    {BUCKET_LABEL[t.status] ?? labelOf(statuses, t.status)}
                  </span>
                )}
                <DueChip date={t.end_date} done={t.status === "done"} />
                <TimeChip totals={totals} compact />
                {t.project_name && (
                  <span className="truncate rounded bg-subtle px-1.5 py-0.5 text-[11px] text-ink-2">
                    {t.project_name}
                  </span>
                )}
              </div>
              {kids.length > 0 && (
                <div className="mt-2">
                  <ProgressBar done={doneKids} total={kids.length} />
                </div>
              )}
            </>
          )}
        </div>
      </article>
    );
  }

  /** One task row inside the Projects tree, with its subtasks beneath. */

  return (
    <AppShell active="Project Tracker" me={me} wide>
      <PageHead
        title={workspace ?? "Project Tracker"}
        subtitle={loading ? "Loading work items…"
          : `${stats.open} open · ${stats.critical} critical · ${stats.overdue} overdue · ${stats.done} done · `
            + `${fmtHours(stats.totals.hasAct ? stats.totals.act : null)} logged of `
            + `${fmtHours(stats.totals.hasEst ? stats.totals.est : null)} estimated`}
        actions={
          <>
            <Button icon="plus" onClick={() => beginCreate("todo", null, project === "All" ? "" : project)}>
              New task
            </Button>
            <Button icon="sync" spinning={loading} onClick={refresh} disabled={loading}>Refresh</Button>
          </>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg bg-subtle p-0.5">
          {VIEWS.map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-semibold transition focus-ring ${
                view === v ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"
              }`}
            >
              <Icon name={VIEW_ICON[v]} className="h-4 w-4" />
              {v}
            </button>
          ))}
        </div>

        {view === "Board" && (
          <label className="flex items-center gap-1.5 text-sm text-ink-2">
            Group by
            <select value={grouping} onChange={(e) => setGrouping(e.target.value as Grouping)}
                    className="h-9 rounded-lg bg-surface px-2 text-sm text-ink ring-control focus-ring">
              {GROUPINGS.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </label>
        )}

        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter tasks…"
          className="h-9 min-w-44 flex-1 rounded-lg bg-surface px-3 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring"
        />
        {PRIORITY_FILTERS.map((p) => (
          <Pill key={p} active={priority === p} onClick={() => setPriority(p)}>{p}</Pill>
        ))}
        {projectOpts.length > 2 && (
          <select value={project} onChange={(e) => setProject(e.target.value)}
                  className="h-9 max-w-40 rounded-lg bg-surface px-2 text-sm text-ink ring-control focus-ring">
            {projectOpts.map((p) => <option key={p} value={p}>{p === "All" ? "All projects" : p}</option>)}
          </select>
        )}
        <label className="flex cursor-pointer select-none items-center gap-1.5 text-sm text-ink-2">
          <input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)}
                 className="h-4 w-4 rounded border-stroke accent-[var(--color-brand)]" />
          Hide done
        </label>
      </div>

      {/* Top-level creator. A dialog rather than a strip in the toolbar: the
          project is the field that decides whether the task is ever seen again,
          and inline it was a 9rem select most people never looked at. */}
      {creating && !creating.parent && (
        <Modal
          title="New task"
          compact
          onClose={() => { setCreating(null); setNewTitle(""); }}
          footer={
            <>
              <Button variant="ghost"
                      onClick={() => { setCreating(null); setNewTitle(""); }}>Cancel</Button>
              <Button variant="primary" spinning={saving}
                      disabled={!newTitle.trim() || createBlocked}
                      onClick={() => void quickCreate(
                        creating.status, null, newTitle, creating.project)}>
                Add task
              </Button>
            </>
          }
        >
          <div className="space-y-4 pb-2">
            <div>
              <label htmlFor="new-task-title"
                     className="mb-1 block text-xs font-medium text-ink-2">Title</label>
              <input
                id="new-task-title"
                ref={newRef}
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newTitle.trim() && !createBlocked) {
                    void quickCreate(creating.status, null, newTitle, creating.project);
                  }
                }}
                placeholder="What needs doing?"
                className="h-9 w-full rounded-md bg-surface px-2.5 text-sm text-ink
                           ring-control placeholder:text-ink-3 focus-ring"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="new-task-project"
                       className="mb-1 block text-xs font-medium text-ink-2">Project</label>
                <select id="new-task-project" value={creating.project}
                        onChange={(e) => setCreating({ ...creating, project: e.target.value })}
                        className="h-9 w-full rounded-md bg-surface px-2 text-sm text-ink
                                   ring-control focus-ring">
                  {/* Inside a workspace, "No project" is a task nobody will see
                      again, so it is not offered there. */}
                  {!workspace && <option value="">No project</option>}
                  {createProjectOpts.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="new-task-status"
                       className="mb-1 block text-xs font-medium text-ink-2">Status</label>
                <StatusSelect id="new-task-status" value={creating.status} statuses={statuses}
                              onChange={(v) => setCreating({ ...creating, status: v })} />
              </div>
            </div>

            {/* A workspace with nothing in it cannot hold a task: the board
                lists a workspace's projects, so a task with no project would
                save and then vanish. Say so here rather than let that happen. */}
            {createBlocked && (
              <p className="rounded-md bg-warnx-bg px-3 py-2 text-xs leading-relaxed text-warnx">
                <strong>{workspace}</strong> has no projects yet. A task has to belong
                to one to show on this board — add a project to {workspace} first,
                otherwise the task saves but never appears.
              </p>
            )}
          </div>
        </Modal>
      )}

      {loading ? (
        <div className="rounded-xl bg-surface p-6 text-sm text-ink-2 ring-panel">Loading work items…</div>
            ) : view === "Board" ? (
        /* ─────────── Board ─────────── */
        <div className="flex gap-3 overflow-x-auto pb-2">
          {columns.length === 0 && (
            <div className="w-full">
              <EmptyState icon="board" title="Nothing to show" hint="Adjust the filters, or add a task."
                          action={<Button icon="plus" variant="primary" onClick={() => beginCreate("todo")}>New task</Button>} />
            </div>
          )}
          {columns.map((col) => {
            const isOver = dragOver === col.key && col.droppable !== null;
            return (
              <section
                key={col.key}
                onDragOver={col.droppable ? (e) => { e.preventDefault(); setDragOver(col.key); } : undefined}
                onDragLeave={() => setDragOver((c) => (c === col.key ? null : c))}
                onDrop={col.droppable ? () => onDrop("status", col.droppable!) : undefined}
                className={`flex w-72 shrink-0 flex-col rounded-xl bg-subtle/50 ring-1 ring-inset transition ${
                  isOver ? "ring-2 ring-brand" : "ring-stroke/60"
                }`}
              >
                <header className="flex items-center gap-2 px-3 py-2.5">
                  <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${col.dot}`} />
                  <h3 className="truncate text-sm font-semibold text-ink">{col.label}</h3>
                  <span className="ml-auto rounded-md bg-surface px-1.5 py-0.5 text-xs font-semibold text-ink-2">
                    {col.items.length}
                  </span>
                </header>
                {col.droppable && (
                  <button
                    onClick={() => beginCreate(col.droppable!, null, project === "All" ? "" : project)}
                    className="mx-2 mb-2 flex items-center gap-1.5 rounded-lg border border-dashed border-stroke px-2 py-1.5 text-xs font-medium text-ink-3 transition hover:border-brand hover:text-brand focus-ring"
                  >
                    <Icon name="plus" className="h-3.5 w-3.5" />
                    Add task
                  </button>
                )}
                <div className="flex min-h-16 flex-col gap-2 px-2 pb-2">
                  {col.items.length === 0 && (
                    <p className="px-1 py-2 text-center text-xs text-ink-3">{isOver ? "Drop here" : "Empty"}</p>
                  )}
                  {col.items.map((t) => <Card key={t.id} t={t} column={col.key} />)}
                </div>
              </section>
            );
          })}
        </div>
      ) : view === "Workload" ? (
        /* ─────────── Workload ─────────── */
        /* Reads `visible`, so the project filter and search narrow the chart
           the same way they narrow every other view. */
        <Workload tasks={visible} />
      ) : view === "Calendar" ? (
        /* ─────────── Calendar ─────────── */
        <div className="overflow-hidden rounded-xl bg-surface ring-panel">
          <header className="flex flex-wrap items-center gap-2 border-b border-stroke px-3 py-2.5">
            <h3 className="text-sm font-semibold text-ink">{MONTHS[month.m]} {month.y}</h3>
            <div className="ml-auto flex items-center gap-1">
              <Button onClick={() => setMonth(({ y, m }) => (m === 0 ? { y: y - 1, m: 11 } : { y, m: m - 1 }))}>Prev</Button>
              <Button onClick={() => { const n = new Date(); setMonth({ y: n.getFullYear(), m: n.getMonth() }); }}>Today</Button>
              <Button onClick={() => setMonth(({ y, m }) => (m === 11 ? { y: y + 1, m: 0 } : { y, m: m + 1 }))}>Next</Button>
            </div>
          </header>

          <div className="grid grid-cols-7 border-b border-stroke bg-subtle/50">
            {DOW.map((d) => (
              <div key={d} className="px-2 py-1.5 text-center text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                {d}
              </div>
            ))}
          </div>

          {weeks.map((week, wi) => {
            const bars = weekBars[wi] ?? [];
            const lanes = bars.length ? Math.max(...bars.map((b) => b.lane)) + 1 : 0;
            return (
              <div key={toISO(week[0])} className="relative">
                <div className="grid grid-cols-7">
                  {week.map((d) => {
                    const iso = toISO(d);
                    const inMonth = d.getMonth() === month.m;
                    const isToday = iso === todayISO;
                    const isOver = dragOver === `d:${iso}`;
                    return (
                      <button
                        key={iso}
                        type="button"
                        onDragOver={(e) => { e.preventDefault(); setDragOver(`d:${iso}`); }}
                        onDragLeave={() => setDragOver((c) => (c === `d:${iso}` ? null : c))}
                        onDrop={() => onDrop("date", iso)}
                        onClick={() => setDayTask({
                          start: iso, end: iso, title: "",
                          project: project === "All" ? "" : (project === NO_PROJECT ? "" : project),
                          list: "", priority: "medium", assignees: [], error: "",
                        })}
                        title={`Add a task on ${iso}`}
                        // The lane count sets the height so bars never overflow
                        // into the row below.
                        style={{ minHeight: 30 + lanes * 22 + 34, paddingTop: 4 }}
                        // A <button> centres its content, which dropped the date
                        // number into the middle of the cell - straight into the
                        // bars. Flex-start pins it to the top of the band.
                        className={`group relative flex flex-col items-start justify-start border-b border-r border-stroke p-1.5 text-left transition ${
                          inMonth ? "hover:bg-brand-tint/30" : "bg-subtle/30 hover:bg-subtle/50"
                        } ${isOver ? "ring-2 ring-inset ring-brand" : ""}`}
                      >
                        <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold ${
                          isToday ? "bg-brand text-white" : inMonth ? "text-ink-2" : "text-ink-3/60"
                        }`}>
                          {d.getDate()}
                        </span>
                        <span className="pointer-events-none absolute right-1.5 top-1.5 text-ink-3 opacity-0 transition group-hover:opacity-100">
                          <Icon name="plus" className="h-3.5 w-3.5" />
                        </span>
                      </button>
                    );
                  })}
                </div>

                {/* Bars sit above the cells, so a span reads as one continuous
                    line across the week rather than a chip per day. */}
                <div className="pointer-events-none absolute inset-x-0" style={{ top: 30 }}>
                  {bars.map((b) => {
                    const done = b.task.status === "done";
                    const overdue = !done && (parseISO(b.task.end_date) ?? new Date()) < startOfDay(new Date());
                    return (
                      <button
                        key={`${b.task.id}-${b.startCol}`}
                        type="button"
                        onClick={(e) => { e.stopPropagation(); openEditor(b.task); }}
                        title={`${b.task.title} · ${periodLabel(b.task)}`}
                        style={{
                          left: `calc(${(b.startCol / 7) * 100}% + 3px)`,
                          width: `calc(${(b.span / 7) * 100}% - 6px)`,
                          top: b.lane * 22,
                        }}
                        className={`pointer-events-auto absolute flex h-[18px] items-center gap-1 overflow-hidden px-1.5 text-[11px] font-medium text-white transition hover:brightness-110 focus-ring ${
                          done ? "bg-good" : overdue ? "bg-bad" : PRIORITY_STRIP[b.task.priority] ?? "bg-brand"
                        } ${b.continuesLeft ? "rounded-l-none" : "rounded-l"} ${
                          b.continuesRight ? "rounded-r-none" : "rounded-r"
                        }`}
                      >
                        {/* A square edge is the "continues" cue - the arrow
                            glyphs rendered as emoji on Windows. */}
                        <span className={`truncate ${done ? "line-through opacity-80" : ""}`}>
                          {b.task.title}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}

          <p className="px-3 py-2 text-xs text-ink-3">
            Bars run from a task&apos;s start date to its due date. Click any day to add a task,
            or drop a card on a day to move its due date.
          </p>
        </div>
      ) : (
        /* ─────────── Gantt ─────────── */
        <div className="overflow-hidden rounded-xl bg-surface ring-panel">
          {gantt.rows.length === 0 ? (
            <EmptyState icon="gantt" title="Nothing scheduled"
                        hint="Give tasks a start and due date to see them on a timeline." />
          ) : (
            <div className="overflow-x-auto">
              <div className="min-w-max">
                <div className="flex border-b border-stroke bg-subtle/50">
                  <div className="sticky left-0 z-10 w-64 shrink-0 border-r border-stroke bg-subtle/50 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                    Task · period · hours
                  </div>
                  {Array.from({ length: gantt.days }, (_, i) => {
                    const d = addDays(gantt.start, i);
                    const iso = toISO(d);
                    const weekend = d.getDay() === 0 || d.getDay() === 6;
                    return (
                      <div key={iso}
                           className={`w-7 shrink-0 border-r border-stroke/60 py-1 text-center text-[10px] ${
                             weekend ? "bg-subtle" : ""
                           } ${iso === todayISO ? "bg-brand-tint font-bold text-brand-pressed" : "text-ink-3"}`}>
                        <div>{d.getDate() === 1 ? MONTHS[d.getMonth()].slice(0, 3) : ""}</div>
                        <div>{d.getDate()}</div>
                      </div>
                    );
                  })}
                </div>

                {gantt.rows.map(({ t, s, e }) => {
                  const offset = Math.max(dayDiff(gantt.start, s), 0);
                  const span = Math.max(dayDiff(s, e) + 1, 1);
                  const overdue = t.status !== "done" && e < startOfDay(new Date());
                  const totals = rollUp(t, kidsOf(t.id));
                  return (
                    <div key={t.id} className="flex border-b border-stroke last:border-b-0 hover:bg-subtle/30">
                      <button onClick={() => openEditor(t)}
                              className="sticky left-0 z-10 w-64 shrink-0 border-r border-stroke bg-surface px-3 py-2 text-left focus-ring">
                        <span className={`block truncate text-xs font-medium ${
                          t.status === "done" ? "text-ink-3 line-through" : "text-ink"
                        }`}>
                          {t.title}
                        </span>
                        <span className="flex items-center gap-1.5 text-[10px] text-ink-3">
                          {span} day{span === 1 ? "" : "s"}
                          {(totals.hasEst || totals.hasAct) && (
                            <>· {fmtHours(totals.hasAct ? totals.act : null)} / {fmtHours(totals.hasEst ? totals.est : null)}</>
                          )}
                        </span>
                      </button>
                      <div className="relative flex-1 py-2" style={{ width: gantt.days * 28 }}>
                        <button
                          onClick={() => openEditor(t)}
                          title={`${t.title} · ${periodLabel(t)}`}
                          className={`absolute top-2 flex h-5 items-center overflow-hidden rounded px-1.5 text-[10px] font-semibold text-white transition hover:brightness-110 focus-ring ${
                            t.status === "done" ? "bg-good" : overdue ? "bg-bad" : PRIORITY_STRIP[t.priority] ?? "bg-brand"
                          }`}
                          style={{ left: offset * 28 + 2, width: Math.max(span * 28 - 4, 18) }}
                        >
                          <span className="truncate">{span > 1 ? t.title : ""}</span>
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {gantt.unscheduled.length > 0 && (
            <div className="border-t border-stroke px-3 py-2">
              <p className="mb-1.5 text-xs font-semibold text-ink-2">
                Unscheduled ({gantt.unscheduled.length}) — no start or due date
              </p>
              <div className="flex flex-wrap gap-1.5">
                {gantt.unscheduled.slice(0, 24).map((t) => (
                  <button key={t.id} onClick={() => openEditor(t)}
                          className="flex items-center gap-1.5 rounded-md bg-subtle px-2 py-1 text-xs text-ink-2 transition hover:text-brand focus-ring">
                    <span className={`h-1.5 w-1.5 rounded-full ${PRIORITY_STRIP[t.priority]}`} />
                    <span className="max-w-48 truncate">{t.title}</span>
                  </button>
                ))}
                {gantt.unscheduled.length > 24 && (
                  <span className="px-2 py-1 text-xs text-ink-3">+{gantt.unscheduled.length - 24} more</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {view === "Board" && !loading && grouping === "Bucket" && (
        <p className="mt-3 text-xs text-ink-3">
          Drag a card between buckets to change its state. Cards are top-level tasks; open one to see its subtasks.
        </p>
      )}

      {/* ── New list ── */}
      {newList && (
        <>
          <button aria-label="Close" onClick={() => setNewList(null)}
                  className="fixed inset-0 z-40 bg-black/30" />
          <div className="fixed left-1/2 top-24 z-50 w-full max-w-md -translate-x-1/2 rounded-xl bg-surface p-4 shadow-2xl ring-1 ring-stroke">
            <h2 className="mb-1 text-base font-semibold text-ink">New list</h2>
            <p className="mb-4 text-xs text-ink-3">
              In <span className="font-medium text-ink-2">
                {newList.project === NO_PROJECT ? (workspace ?? "no workspace")
                                                : newList.project}
              </span>. A list groups related tasks inside it.
            </p>
            <div className="space-y-4">
              <TextInput label="List name" value={newList.name}
                         placeholder="e.g. Phase 2 — migration"
                         hint="You can add tasks to it afterwards."
                         onChange={(v) => setNewList({ ...newList, name: v })} />
            </div>
            <div className="mt-5 flex items-center gap-2">
              {error && <span className="mr-auto text-sm text-bad">{error}</span>}
              <span className="ml-auto" />
              <Button onClick={() => setNewList(null)}>Cancel</Button>
              <Button variant="primary" spinning={saving} onClick={createList} disabled={saving}>
                Create list
              </Button>
            </div>
          </div>
        </>
      )}

      {/* ── Add a task on a clicked day ── */}
      {dayTask && (
        <>
          <button aria-label="Close" onClick={() => setDayTask(null)}
                  className="fixed inset-0 z-40 bg-black/40" />
          {/* Centred in the viewport with a flex wrapper: the old fixed top
              offset put it up in the corner on a tall window. */}
          <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-label="New task"
            className="pointer-events-auto max-h-[90vh] w-full max-w-md overflow-y-auto rounded-xl bg-surface p-5 shadow-2xl ring-1 ring-stroke"
          >
            <h2 className="text-base font-semibold text-ink">New task</h2>
            <p className="mb-4 mt-0.5 text-xs text-ink-3">
              It will show on the calendar as a bar from the start date to the due date.
            </p>

            <div className="space-y-4">
              <TextInput label="Title" value={dayTask.title}
                         placeholder="e.g. Draft the migration plan"
                         onChange={(v) => setDayTask({ ...dayTask, title: v, error: "" })} />
              <div className="grid grid-cols-2 gap-4">
                <TextInput label="Start date" type="date" value={dayTask.start}
                           onChange={(v) => setDayTask({ ...dayTask, start: v, error: "" })} />
                <TextInput label="Due date" type="date" value={dayTask.end}
                           hint="Same day for a one-day task."
                           onChange={(v) => setDayTask({ ...dayTask, end: v, error: "" })} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <SelectInput
                  label="Project" value={dayTask.project}
                  onChange={(v) => setDayTask({ ...dayTask, project: v, list: "" })}
                  options={[{ value: "", label: "No project" },
                            ...(data?.projects ?? []).map((p) => ({ value: p, label: p }))]}
                />
                <div>
                  <div className="mb-1 flex h-6 items-center justify-between">
                    <span className="text-sm font-medium leading-6 text-ink">List</span>
                    {!addingList && (
                      <button type="button"
                              onClick={() => { setAddingList(true); setInlineList(""); }}
                              className="rounded px-1.5 text-[11px] font-semibold text-brand transition hover:bg-brand-tint focus-ring">
                        + New list
                      </button>
                    )}
                  </div>
                  {addingList ? (
                    <div className="flex gap-1.5">
                      <input
                        autoFocus
                        value={inlineList}
                        onChange={(e) => setInlineList(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") { e.preventDefault(); void createInlineList(); }
                          if (e.key === "Escape") { setAddingList(false); setInlineList(""); }
                        }}
                        placeholder="e.g. Phase 1"
                        className="h-9 min-w-0 flex-1 rounded-lg bg-canvas px-2.5 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring"
                      />
                      <button type="button" onClick={() => void createInlineList()}
                              disabled={saving || !inlineList.trim()}
                              className="h-9 shrink-0 rounded-lg bg-brand px-2.5 text-xs font-semibold text-white transition hover:bg-brand-hover disabled:opacity-50 focus-ring">
                        Add
                      </button>
                      <button type="button"
                              onClick={() => { setAddingList(false); setInlineList(""); }}
                              className="h-9 shrink-0 rounded-lg px-2 text-xs font-medium text-ink-2 ring-control transition hover:bg-subtle focus-ring">
                        ✕
                      </button>
                    </div>
                  ) : (
                    <>
                      <select
                        value={dayTask.list}
                        onChange={(e) => setDayTask({ ...dayTask, list: e.target.value })}
                        className="h-9 w-full rounded-lg bg-canvas px-2.5 text-sm text-ink ring-control focus-ring"
                      >
                        <option value="">No list</option>
                        {(data?.lists?.[dayTask.project] ?? []).map((l) => (
                          <option key={l} value={l}>{l}</option>
                        ))}
                      </select>
                      <span className="mt-1 block text-xs leading-snug text-ink-3">
                        {(data?.lists?.[dayTask.project] ?? []).length
                          ? "Optional."
                          : dayTask.project
                            ? "This project has no lists yet."
                            : "Pick a project first, or leave it without a list."}
                      </span>
                    </>
                  )}
                </div>
              </div>
              {/* A native select cannot colour its options, and the level is
                  the thing you scan for - so each one carries its colour. */}
              <div>
                <p className="mb-1.5 text-xs font-medium text-ink-2">Priority</p>
                <div className="flex flex-wrap gap-1.5">
                  {priorities.map(([value, l]) => {
                    const on = dayTask.priority === value;
                    return (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setDayTask({ ...dayTask, priority: value })}
                        aria-pressed={on}
                        className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold ring-1 ring-inset transition ${
                          on
                            ? "bg-brand-tint text-ink ring-brand"
                            : "bg-surface text-ink-2 ring-stroke hover:bg-subtle"
                        }`}
                      >
                        <span className={`h-2.5 w-2.5 rounded-full ${PRIORITY_STRIP[value] ?? "bg-ink-3"}`} />
                        {l}
                      </button>
                    );
                  })}
                </div>
              </div>
              <AssigneePicker people={data?.people ?? []}
                              value={dayTask.assignees}
                              onChange={(ids) => setDayTask({ ...dayTask, assignees: ids })} />
            </div>

            {dayTask.error && <p className="mt-3 text-sm text-bad">{dayTask.error}</p>}

            <div className="mt-5 flex items-center justify-end gap-2">
              <Button onClick={() => setDayTask(null)}>Cancel</Button>
              <Button variant="primary" spinning={saving} onClick={createDayTask} disabled={saving}>
                Add task
              </Button>
            </div>
          </div>
          </div>
        </>
      )}

      {/* ── Detail panel ── */}
      {sel && form && (
        <>
          <button aria-label="Close task" onClick={() => { setForm(null); setSelected(null); }}
                  className="fixed inset-0 z-40 bg-black/30" />
          {/* max-w-lg (32rem) was tight for a two-column form plus subtasks;
                  3xl gives the fields room without swallowing the board
                  behind it on a laptop screen. */}
          <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-3xl flex-col bg-surface shadow-2xl ring-1 ring-stroke">
            <header className="flex items-start gap-3 border-b border-stroke px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="mb-0.5 flex items-center gap-2 text-xs text-ink-3">
                  <span>#{sel.id}</span>
                  {sel.parent != null && <span className="truncate">· subtask of {byId.get(sel.parent)?.title}</span>}
                  {sel.project_name && <span className="truncate">· {sel.project_name}</span>}
                </p>
                <h2 className="truncate text-base font-semibold text-ink">{sel.title}</h2>
              </div>
              <button onClick={() => { setForm(null); setSelected(null); }} aria-label="Close"
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-2 transition hover:bg-subtle hover:text-ink focus-ring">
                <Icon name="expand" className="h-4 w-4" />
              </button>
            </header>

            <div className="flex-1 overflow-y-auto px-4 py-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <TextInput label="Title" value={form.title} onChange={(v) => setForm({ ...form, title: v })} />
                </div>
                {/* Same control as the create dialog, so a status is the same
                    colour wherever it is set. */}
                <div>
                  <label htmlFor="edit-task-status"
                         className="mb-1 block text-xs font-medium text-ink-2">Bucket</label>
                  <StatusSelect id="edit-task-status" value={form.status} statuses={statuses}
                                onChange={(v) => setForm({ ...form, status: v })} />
                </div>
                <SelectInput label="Priority" value={form.priority}
                             onChange={(v) => setForm({ ...form, priority: v })}
                             options={priorities.map(([value, l]) => ({ value, label: l }))} />
                <TextInput label="Project" value={form.project_name} placeholder="Optional"
                           onChange={(v) => setForm({ ...form, project_name: v })} />
                <TextInput label="List" value={form.list_name} placeholder={NO_LIST}
                           onChange={(v) => setForm({ ...form, list_name: v })} />
                <SelectInput label="Company" value={form.company}
                             onChange={(v) => setForm({ ...form, company: v })}
                             options={[{ value: "", label: "—" },
                                       ...(data?.companies ?? []).map(([value, l]) => ({ value, label: l }))]} />
                <TextInput label="Start date" type="date" value={form.start_date}
                           onChange={(v) => setForm({ ...form, start_date: v })} />
                <TextInput label="Due date" type="date" value={form.end_date}
                           onChange={(v) => setForm({ ...form, end_date: v })} />
                {/* Times are optional: most tasks are booked to a day, and a
                    blank here means "no particular time", not midnight. */}
                <TextInput label="Start time" type="time" value={form.start_time}
                           onChange={(v) => setForm({ ...form, start_time: v })} />
                <TextInput label="End time" type="time" value={form.end_time}
                           onChange={(v) => setForm({ ...form, end_time: v })} />
                <TextInput label="Estimated hours" type="number" value={form.estimated_hours}
                           placeholder="e.g. 8"
                           onChange={(v) => setForm({ ...form, estimated_hours: v })} />
                <TextInput label="Actual hours" type="number" value={form.actual_hours}
                           placeholder="Log as you go"
                           onChange={(v) => setForm({ ...form, actual_hours: v })} />
                <div className="sm:col-span-2">
                  <AssigneePicker people={data?.people ?? []}
                                  value={form.assignees}
                                  onChange={(ids) => setForm({ ...form, assignees: ids })} />
                </div>
                <div className="sm:col-span-2">
                  <AreaInput label="Notes" rows={4} value={form.description}
                             onChange={(v) => setForm({ ...form, description: v })} />
                </div>
              </div>

              {/* Time summary — the point of tracking both numbers. */}
              {(() => {
                const totals: Totals = rollUp(sel, kidsOf(sel.id));
                const variance = totals.est > 0 ? totals.act - totals.est : null;
                return (
                  <section className="mt-5 rounded-lg bg-subtle/50 p-3">
                    <h3 className="mb-2 text-sm font-semibold text-ink">Time</h3>
                    <dl className="grid grid-cols-3 gap-2 text-center">
                      <div>
                        <dt className="text-[11px] uppercase tracking-wide text-ink-3">Estimated</dt>
                        <dd className="text-sm font-semibold text-ink">{fmtHours(totals.hasEst ? totals.est : null)}</dd>
                      </div>
                      <div>
                        <dt className="text-[11px] uppercase tracking-wide text-ink-3">Actual</dt>
                        <dd className="text-sm font-semibold text-ink">{fmtHours(totals.hasAct ? totals.act : null)}</dd>
                      </div>
                      <div>
                        <dt className="text-[11px] uppercase tracking-wide text-ink-3">Variance</dt>
                        <dd className={`text-sm font-semibold ${
                          variance == null ? "text-ink-3" : variance > 0 ? "text-bad" : "text-good"
                        }`}>
                          {variance == null ? "—" : `${variance > 0 ? "+" : ""}${fmtHours(Math.round(variance * 10) / 10)}`}
                        </dd>
                      </div>
                    </dl>
                    {periodLabel(sel) && (
                      <p className="mt-2 text-center text-[11px] text-ink-3">{periodLabel(sel)}</p>
                    )}
                    <div className="mt-3 border-t border-stroke pt-3">
                      <TaskTimer task={sel} onChange={refresh} />
                    </div>
                    {kidsOf(sel.id).length > 0 && sel.estimated_hours == null && (
                      <p className="mt-2 text-[11px] text-ink-3">
                        Totals are rolled up from subtasks. Set an estimate here to quote the whole task instead.
                      </p>
                    )}
                  </section>
                );
              })()}

              {sel.parent == null && (
                <section className="mt-5">
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-ink">
                      Subtasks
                      <span className="ml-2 font-normal text-ink-3">
                        {kidsOf(sel.id).filter((k) => k.status === "done").length}/{kidsOf(sel.id).length}
                      </span>
                    </h3>
                    {/* Stay on the task being edited. The previous version
                        closed the panel and set up a create row that only
                        rendered for top-level tasks, so the button did
                        nothing at all. */}
                    <Button icon="plus"
                            onClick={() => beginCreate("todo", sel)}>Add</Button>
                  </div>
                  <ul className="divide-y divide-stroke rounded-lg ring-panel">
                    {creating?.parent?.id === sel.id && (
                      <li className="flex items-center gap-2 px-3 py-2">
                        <span className="h-2 w-2 shrink-0 rounded-full bg-ink-3" />
                        <input ref={newRef} value={newTitle} autoFocus
                               placeholder="Subtask title, then Enter"
                               onChange={(e) => setNewTitle(e.target.value)}
                               onKeyDown={(e) => {
                                 if (e.key === "Enter") {
                                   void quickCreate("todo", sel, newTitle, "");
                                 }
                                 if (e.key === "Escape") setCreating(null);
                               }}
                               className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3" />
                        <Button icon="plus" disabled={saving || !newTitle.trim()}
                                onClick={() => void quickCreate("todo", sel, newTitle, "")}>
                          Add
                        </Button>
                        <Button variant="ghost" onClick={() => setCreating(null)}>
                          Cancel
                        </Button>
                      </li>
                    )}
                    {kidsOf(sel.id).length === 0 && creating?.parent?.id !== sel.id && (
                      <li className="px-3 py-3 text-xs text-ink-3">No subtasks yet.</li>
                    )}
                    {kidsOf(sel.id).map((k) => (
                      <li key={k.id} className="flex items-center gap-2 px-3 py-2">
                        <button onClick={() => void patch(k, { status: k.status === "done" ? "todo" : "done" })}
                                aria-label={k.status === "done" ? "Reopen subtask" : "Complete subtask"}
                                className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition focus-ring ${
                                  k.status === "done" ? "border-good bg-good text-white" : "border-ink-3/50 text-transparent hover:border-brand"
                                }`}>
                          <Icon name="tasks" className="h-2.5 w-2.5" />
                        </button>
                        <button onClick={() => openEditor(k)}
                                className={`min-w-0 flex-1 truncate text-left text-sm focus-ring ${
                                  k.status === "done" ? "text-ink-3 line-through" : "text-ink-2"
                                }`}>
                          {k.title}
                        </button>
                        <TimeChip totals={rollUp(k, [])} compact />
                        <span className={`shrink-0 text-[11px] font-semibold ${PRIORITY_TEXT[k.priority]}`}>
                          {labelOf(priorities, k.priority)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <p className="mt-6 text-xs text-ink-3">
                Created {sel.created_at?.slice(0, 10) ?? "—"} · updated {sel.updated_at?.slice(0, 10) ?? "—"}
              </p>
            </div>

            <footer className="flex items-center gap-2 border-t border-stroke px-4 py-3">
              {error && <span className="mr-auto text-sm text-bad">{error}</span>}
              {!error && <Button icon="trash" variant="danger" onClick={() => remove(sel)}>Delete</Button>}
              <span className="ml-auto" />
              <Button onClick={() => { setForm(null); setSelected(null); }}>Cancel</Button>
              <Button variant="primary" spinning={saving} onClick={saveEditor} disabled={saving}>Save</Button>
            </footer>
          </aside>
        </>
      )}

      {menu && (
        <ContextMenu x={menu.x} y={menu.y} items={menuFor(menu.task)}
                     onClose={() => setMenu(null)} />
      )}

      {confirming && (
        <ConfirmDialog
          title="Delete this task?"
          busy={deleting}
          onClose={() => setConfirming(null)}
          onConfirm={() => void reallyRemove(confirming)}
          body={
            <>
              <b className="text-ink">{confirming.title}</b> will be deleted.
              {kidsOf(confirming.id).length > 0 && (
                <> Its {kidsOf(confirming.id).length} subtask
                  {kidsOf(confirming.id).length === 1 ? "" : "s"} will be
                  detached, not deleted.</>
              )}{" "}
              This cannot be undone.
            </>
          }
        />
      )}
    </AppShell>
  );
}


/**
 * `useSearchParams` opts a route out of static prerendering unless it sits
 * inside a Suspense boundary - `next build` fails on it even though `next dev`
 * does not. The boundary keeps /tasks prerenderable and shows the same loading
 * state the page uses for its own data.
 */
export default function TasksPage() {
  return (
    <Suspense
      fallback={
        <div className="p-6 text-sm text-ink-2">Loading work items…</div>
      }
    >
      <TasksInner />
    </Suspense>
  );
}

/**
 * The running clock, ClickUp-style: press start, do the work, press stop and
 * the elapsed time lands in Actual hours.
 *
 * The server owns the arithmetic - it holds the instant the timer began and
 * works out the elapsed time on stop. This component only renders the count
 * upward, so a reload, a different browser or a closed laptop cannot lose or
 * inflate the figure.
 */
function TaskTimer({ task, onChange }: { task: Task; onChange: () => void }) {
  const startedAt = task.timer_started_at ?? null;
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!startedAt) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  async function toggle() {
    setBusy(true);
    try {
      await fetch(`/api/tasks/${task.id}/timer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: startedAt ? "stop" : "start" }),
      });
      await onChange();
    } finally {
      setBusy(false);
    }
  }

  const elapsed = startedAt
    ? Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000))
    : 0;
  const clock = [Math.floor(elapsed / 3600), Math.floor(elapsed / 60) % 60,
                 elapsed % 60]
    .map((n) => String(n).padStart(2, "0")).join(":");

  return (
    <div className="flex items-center gap-2">
      {startedAt && (
        <span className="flex flex-1 items-center gap-2 text-lg font-semibold tabular-nums text-ink">
          <span aria-hidden className="h-2.5 w-2.5 animate-pulse rounded-full bg-bad" />
          {clock}
        </span>
      )}
      <button onClick={toggle} disabled={busy}
              className={`inline-flex h-9 items-center justify-center gap-2 rounded-lg text-sm font-semibold transition focus-ring disabled:opacity-50 ${
                startedAt ? "bg-bad px-4 text-white hover:opacity-90"
                          : "w-full bg-surface text-ink ring-control hover:bg-subtle"}`}>
        <Icon name={startedAt ? "pause" : "clock"} className="h-4 w-4" />
        {startedAt ? "Stop" : "Start timer"}
      </button>
    </div>
  );
}
