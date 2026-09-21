"use client";

/**
 * Projects: the Gantt, and the project record behind each bar.
 *
 * Separate from /tasks on purpose. That page is for working a board; this one
 * is for seeing where projects sit against time and editing the things that
 * make a project reportable — its client, its status, its dates.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import { Gantt, type GanttData } from "@/components/gantt";
import {
  AppShell, PageHead, Section, StatTile, Badge, Button, EmptyState, Modal,
  TextInput, AreaInput, SelectInput,
} from "@/components/ui";

type ProjectRecord = {
  name: string; client: string; client_email: string; client_contact: string;
  status: string; status_display: string;
  priority: string; priority_display: string;
  description: string; start_date: string | null; end_date: string | null;
  quoted_hours: number | null; color: string; icon: string;
  workspace: string; assigned: { id: number; name: string }[];
};
type ProjectsPayload = {
  projects: ProjectRecord[];
  statuses: { value: string; label: string }[];
  priorities: { value: string; label: string }[];
};
type Activity = { id: number; kind: string; summary: string; task: string; when: string };

export default function ProjectsPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [gantt, setGantt] = useState<GanttData | null>(null);
  const [records, setRecords] = useState<ProjectsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [workspace, setWorkspace] = useState("");
  const [editing, setEditing] = useState<ProjectRecord | null>(null);
  const [activity, setActivity] = useState<Activity[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(async (ws: string) => {
    try {
      const q = ws ? `?workspace=${encodeURIComponent(ws)}` : "";
      const [g, r] = await Promise.all([
        fetch(`/api/projects/gantt${q}`).then((x) => (x.ok ? x.json() : null)),
        fetch("/api/projects").then((x) => (x.ok ? x.json() : null)),
      ]);
      setGantt(g);
      setRecords(r);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "tasks")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load("");
  }, [load]);

  const totals = useMemo(() => {
    const ps = gantt?.projects ?? [];
    return {
      projects: ps.filter((p) => p.name).length,
      tasks: ps.reduce((n, p) => n + p.total_tasks, 0),
      done: ps.reduce((n, p) => n + p.completed_tasks, 0),
      overdue: ps.reduce((n, p) => n + p.overdue_tasks, 0),
    };
  }, [gantt]);

  async function openProject(name: string) {
    const rec = records?.projects.find((p) => p.name === name);
    if (!rec) return;
    setEditing(rec);
    setActivity(null);
    const r = await fetch(`/api/projects/${encodeURIComponent(name)}/activity?limit=40`);
    if (r.ok) setActivity((await r.json()).activity ?? []);
  }

  async function save() {
    if (!editing) return;
    setSaving(true);
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(editing.name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client: editing.client, client_email: editing.client_email,
          client_contact: editing.client_contact, description: editing.description,
          status: editing.status, priority: editing.priority,
          start_date: editing.start_date, end_date: editing.end_date,
          quoted_hours: editing.quoted_hours,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setNote(d.detail || "Could not save.");
        return;
      }
      setNote(d.changed?.length
        ? `Saved ${d.changed.length} change${d.changed.length === 1 ? "" : "s"} to ${editing.name}.`
        : `Nothing changed on ${editing.name}.`);
      setEditing(null);
      await load(workspace);
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell active="Projects" me={me} wide>
      <PageHead
        title="Projects"
        subtitle="Every project against the calendar. Expand one to see the work week by week."
        actions={
          <>
            {(gantt?.workspaces?.length ?? 0) > 0 && (
              <select value={workspace}
                      onChange={(e) => { setWorkspace(e.target.value); setLoading(true); void load(e.target.value); }}
                      className="h-8 rounded-lg bg-surface px-2 text-xs text-ink ring-control focus-ring">
                <option value="">All workspaces</option>
                {gantt!.workspaces.map((w) => <option key={w} value={w}>{w}</option>)}
              </select>
            )}
            <Button icon="sync" spinning={loading}
                    onClick={() => { setLoading(true); void load(workspace); }}>
              Refresh
            </Button>
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Projects" value={loading ? "—" : totals.projects} icon="board" />
        <StatTile label="Tasks on the chart" value={loading ? "—" : totals.tasks} icon="analysis" />
        <StatTile label="Done" value={loading ? "—" : totals.done} icon="shield" tone="good" />
        <StatTile label="Overdue" value={loading ? "—" : totals.overdue}
                  icon="alert" tone={totals.overdue ? "bad" : "good"} />
      </div>

      {note && (
        <p className="mb-3 flex items-start gap-2 rounded-lg bg-good-bg px-3 py-2 text-xs text-good">
          <Icon name="shield" className="mt-px h-4 w-4 shrink-0" />
          <span className="flex-1">{note}</span>
          <button onClick={() => setNote("")} aria-label="Dismiss"
                  className="shrink-0 opacity-60 hover:opacity-100">✕</button>
        </p>
      )}

      {loading ? (
        <Section><div className="p-6 text-sm text-ink-2">Building the chart…</div></Section>
      ) : !gantt || gantt.projects.length === 0 ? (
        <Section>
          <EmptyState icon="board" title="Nothing to chart yet"
                      hint="Create a project in the tracker and give it dates, and it will appear here." />
        </Section>
      ) : (
        <>
          <Gantt data={gantt} />

          {/* The records behind the bars. */}
          <Section className="mt-4">
            <div className="flex items-center justify-between px-4 py-2.5">
              <h2 className="text-sm font-semibold text-ink">Project details</h2>
              <span className="text-xs text-ink-3">
                Click a project to set its client, status and dates
              </span>
            </div>
            <ul className="divide-y divide-stroke border-t border-stroke">
              {(records?.projects ?? []).map((p) => (
                <li key={p.name}>
                  <button onClick={() => void openProject(p.name)}
                          className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition hover:bg-subtle/50 focus-ring">
                    {p.icon && <span aria-hidden className="text-base">{p.icon}</span>}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink">{p.name}</span>
                      <span className="block truncate text-xs text-ink-3">
                        {p.client || "no client set"}
                        {p.start_date && ` · ${p.start_date} → ${p.end_date ?? "open"}`}
                        {p.workspace && ` · ${p.workspace}`}
                      </span>
                    </span>
                    <Badge tone={p.status === "completed" ? "good"
                      : p.status === "cancelled" ? "bad"
                      : p.status.startsWith("completed") ? "info"
                      : p.status === "on_hold" || p.status === "in_progress_guidance" ? "warn"
                      : "neutral"}>
                      {p.status_display}
                    </Badge>
                    <Icon name="chevron" className="h-4 w-4 shrink-0 -rotate-90 text-ink-3" />
                  </button>
                </li>
              ))}
            </ul>
          </Section>
        </>
      )}

      {editing && (
        <Modal title={editing.name} wide onClose={() => setEditing(null)}
               footer={
                 <>
                   <Button onClick={() => setEditing(null)}>Cancel</Button>
                   <Button variant="primary" spinning={saving} onClick={save} disabled={saving}>
                     Save project
                   </Button>
                 </>
               }>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <SelectInput label="Status" value={editing.status}
                         onChange={(v) => setEditing({ ...editing, status: v })}
                         options={(records?.statuses ?? []).map((s) => ({ value: s.value, label: s.label }))} />
            <SelectInput label="Priority" value={editing.priority}
                         onChange={(v) => setEditing({ ...editing, priority: v })}
                         options={(records?.priorities ?? []).map((s) => ({ value: s.value, label: s.label }))} />
            <TextInput label="Client" value={editing.client}
                       onChange={(v) => setEditing({ ...editing, client: v })} />
            <TextInput label="Client email" value={editing.client_email}
                       hint="Where a client report would be sent."
                       onChange={(v) => setEditing({ ...editing, client_email: v })} />
            <div>
              <span className="block h-6 truncate text-sm font-medium leading-6 text-ink">Start date</span>
              <input type="date" value={editing.start_date ?? ""}
                     onChange={(e) => setEditing({ ...editing, start_date: e.target.value || null })}
                     className="h-9 w-full rounded-lg bg-canvas px-2.5 text-sm text-ink ring-control focus-ring" />
            </div>
            <div>
              <span className="block h-6 truncate text-sm font-medium leading-6 text-ink">End date</span>
              <input type="date" value={editing.end_date ?? ""}
                     onChange={(e) => setEditing({ ...editing, end_date: e.target.value || null })}
                     className="h-9 w-full rounded-lg bg-canvas px-2.5 text-sm text-ink ring-control focus-ring" />
            </div>
            <TextInput label="Quoted hours"
                       value={editing.quoted_hours === null ? "" : String(editing.quoted_hours)}
                       hint="What was sold, to measure actuals against."
                       onChange={(v) => setEditing({
                         ...editing,
                         quoted_hours: v.trim() === "" ? null : Number(v) })} />
            <TextInput label="Client contact" value={editing.client_contact}
                       onChange={(v) => setEditing({ ...editing, client_contact: v })} />
            <div className="sm:col-span-2">
              <AreaInput label="Description" rows={3} value={editing.description}
                         onChange={(v) => setEditing({ ...editing, description: v })} />
            </div>
          </div>

          <div className="mt-5 border-t border-stroke pt-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">
              History
            </h3>
            {activity === null ? (
              <p className="text-sm text-ink-3">Loading…</p>
            ) : activity.length === 0 ? (
              <p className="text-sm text-ink-3">
                Nothing recorded yet. Changes made from here are logged.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {activity.map((a) => (
                  <li key={a.id} className="flex gap-2 text-xs">
                    <span className="w-28 shrink-0 tabular-nums text-ink-3">
                      {new Date(a.when).toLocaleDateString(undefined,
                        { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                    </span>
                    <span className="text-ink-2">
                      {a.summary}{a.task && <span className="text-ink-3"> — {a.task}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Modal>
      )}
    </AppShell>
  );
}
