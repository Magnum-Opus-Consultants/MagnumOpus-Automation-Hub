"use client";

import { useCallback, useEffect, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, StatTile, Button, EmptyState, Badge,
} from "@/components/ui";

/* Where a Project Tracker project is pointed at a ClickUp list.
 *
 * On its own page rather than buried in the tracker: linking is a setup job
 * done once per project, and it needs somewhere to show how the sync is
 * actually doing - what is waiting, what failed and why. Pushing is one way,
 * tracker to ClickUp, so there is never a question of which side won.
 */

type ListOption = { id: string; name: string };
type Space = { id: string; name: string; lists: ListOption[] };
type Workspace = { id: string; name: string; spaces: Space[] };
type Linked = { name: string; list_id: string; list_name: string };
type Status = {
  configured: boolean;
  linked_projects: Linked[];
  waiting: number;
  failing: number;
  synced: number;
};
type Project = { name: string; open: number; total: number };

export default function ClickUpPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState("");

  const load = useCallback(async () => {
    const [s, p] = await Promise.all([
      fetch("/api/clickup/status"),
      fetch("/api/tasks/projects"),
    ]);
    if (s.status === 401) return;
    if (s.ok) setStatus(await s.json());
    if (p.ok) {
      const data = await p.json();
      setProjects((data.projects ?? []).filter((x: Project) => x.name));
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
    // load() only sets state after awaiting its fetches.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  /* The workspace tree is several ClickUp calls, so it is fetched once when
     somebody actually goes to link something rather than on page load. */
  async function loadLists() {
    if (workspaces) return;
    setBusy("lists"); setError("");
    try {
      const res = await fetch("/api/clickup/lists");
      if (!res.ok) {
        setError((await res.json()).detail ?? "Could not read your ClickUp lists.");
        return;
      }
      setWorkspaces((await res.json()).workspaces);
    } finally {
      setBusy("");
    }
  }

  async function link(project: string, listId: string, listName: string) {
    setBusy(project); setError(""); setResult("");
    try {
      const res = await fetch("/api/clickup/link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project, list_id: listId, list_name: listName }),
      });
      if (!res.ok) {
        setError((await res.json()).detail ?? "Could not save that link.");
        return;
      }
      const out = await res.json();
      setResult(listId
        ? `${project} now pushes to ${listName}. ${out.queued} task(s) queued.`
        : `${project} is no longer linked.`);
      await load();
    } finally {
      setBusy("");
    }
  }

  async function syncNow() {
    setBusy("sync"); setError(""); setResult("");
    try {
      const res = await fetch("/api/clickup/sync", { method: "POST" });
      const out = await res.json();
      if (!res.ok) { setError(out.detail ?? "Sync failed."); return; }
      setResult(
        `${out.pushed} pushed, ${out.failed} failed, ${out.waiting} still waiting.`
        + (out.last_error ? ` Last error: ${out.last_error}` : ""));
      await load();
    } finally {
      setBusy("");
    }
  }

  const linkFor = (name: string) =>
    status?.linked_projects.find((l) => l.name === name);

  if (!me) return null;

  return (
    <AppShell active="ClickUp" me={me}>
      <PageHead
        title="ClickUp"
        subtitle="Mirror Project Tracker tasks into ClickUp."
        actions={
          <Button icon="sync" spinning={busy === "sync"} onClick={syncNow}
                  variant="primary">
            Sync now
          </Button>
        }
      />

      {status && !status.configured && (
        <div className="mb-4 rounded-lg bg-warnx-bg px-4 py-3 text-sm text-warnx
                        ring-1 ring-warnx/20">
          No ClickUp token is configured. Add{" "}
          <code className="font-mono">CLICKUP_API_TOKEN</code> to{" "}
          <code className="font-mono">automations/.env</code> and restart the
          server. Nothing syncs until then.
        </div>
      )}
      {error && (
        <div className="mb-4 rounded-lg bg-bad/10 px-4 py-3 text-sm text-bad ring-1 ring-bad/20">
          {error}
        </div>
      )}
      {result && (
        <div className="mb-4 rounded-lg bg-good-bg px-4 py-3 text-sm text-good ring-1 ring-good/20">
          {result}
        </div>
      )}

      {status && (
        <Section title="Sync" className="mb-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Linked projects" icon="link"
                      value={status.linked_projects.length} />
            <StatTile label="Tasks mirrored" icon="check" value={status.synced}
                      tone={status.synced ? "good" : "neutral"} />
            <StatTile label="Waiting to push" icon="clock" value={status.waiting}
                      tone={status.waiting ? "info" : "neutral"}
                      hint={status.waiting ? "retried every 5 minutes" : undefined} />
            <StatTile label="Failing" icon="alert" value={status.failing}
                      tone={status.failing ? "bad" : "neutral"} />
          </div>
        </Section>
      )}

      <Section
        title="Projects"
        right={
          !workspaces && (
            <Button icon="download" spinning={busy === "lists"} onClick={loadLists}>
              Load ClickUp lists
            </Button>
          )
        }
      >
        <p className="mb-4 text-sm text-ink-3">
          A project pushes to ClickUp only once you point it at a list. Anything
          unlinked is left alone, so turning this on cannot fill a board with
          tasks nobody expected. Pushing is one way — a change made in ClickUp is
          overwritten the next time its task changes here.
        </p>

        {projects.length === 0 ? (
          <EmptyState icon="folder" title="No projects yet"
                      hint="Projects appear here once the tracker has tasks filed under one." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-stroke text-left text-[11px] uppercase tracking-wide text-ink-3">
                  <th className="py-2 pr-3 font-medium">Project</th>
                  <th className="py-2 pr-3 font-medium">Tasks</th>
                  <th className="py-2 pr-3 font-medium">ClickUp list</th>
                  <th className="py-2 pr-3 font-medium" />
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => {
                  const current = linkFor(p.name);
                  return (
                    <tr key={p.name} className="border-b border-stroke last:border-0">
                      <td className="py-3 pr-3 font-medium text-ink">{p.name}</td>
                      <td className="py-3 pr-3 text-ink-2">
                        {p.open} open / {p.total}
                      </td>
                      <td className="py-3 pr-3">
                        {workspaces ? (
                          <select
                            value={current?.list_id ?? ""}
                            disabled={busy === p.name}
                            onChange={(e) => {
                              const id = e.target.value;
                              const name = e.target.selectedOptions[0]?.dataset.name ?? "";
                              link(p.name, id, name);
                            }}
                            className="w-full max-w-sm rounded-lg bg-subtle px-3 py-1.5 text-sm
                                       text-ink ring-1 ring-stroke focus:outline-none
                                       focus:ring-brand/40"
                          >
                            <option value="">— not linked —</option>
                            {workspaces.map((w) =>
                              w.spaces.map((sp) => (
                                <optgroup key={sp.id} label={`${w.name} · ${sp.name}`}>
                                  {sp.lists.map((l) => (
                                    <option key={l.id} value={l.id} data-name={l.name}>
                                      {l.name}
                                    </option>
                                  ))}
                                </optgroup>
                              )),
                            )}
                          </select>
                        ) : current ? (
                          <Badge tone="good">{current.list_name || current.list_id}</Badge>
                        ) : (
                          <span className="text-[12px] text-ink-3">Not linked</span>
                        )}
                      </td>
                      <td className="py-3 pr-3 text-right">
                        {current && (
                          <button
                            onClick={() => link(p.name, "", "")}
                            className="rounded p-1.5 text-ink-3 hover:bg-subtle hover:text-bad"
                            aria-label={`Unlink ${p.name}`}
                            title="Stop pushing this project"
                          >
                            <Icon name="trash" className="h-4 w-4" />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </AppShell>
  );
}
