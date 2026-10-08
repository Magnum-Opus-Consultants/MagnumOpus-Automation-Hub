"use client";

import { useCallback, useEffect, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, StatTile, Button, EmptyState, Badge, Modal,
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
type Member = { id: string; email: string; name: string };
type Person = {
  id: number; username: string; full_name: string; email: string;
  clickup_id: string; clickup_name: string; matched_by: string;
};

export default function ClickUpPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [workspace, setWorkspace] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState("");
  // Which project is being linked, and what has been typed to narrow the list.
  const [picking, setPicking] = useState<null | { project: string; filter: string }>(null);

  const load = useCallback(async (pull = false) => {
    const [s, p, ppl] = await Promise.all([
      fetch(`/api/clickup/status${pull ? "?pull=1" : ""}`),
      fetch("/api/tasks/projects"),
      fetch("/api/clickup/people"),
    ]);
    if (s.status === 401) return;
    if (s.ok) setStatus(await s.json());
    if (p.ok) {
      const data = await p.json();
      setProjects((data.projects ?? []).filter((x: Project) => x.name));
    }
    if (ppl.ok) {
      const data = await ppl.json();
      setPeople(data.people ?? []);
      setMembers(data.members ?? []);
      setWorkspace(data.workspace ?? "");
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
    void load(true);   // first load also asks ClickUp for anything new
  }, [load]);

  /* The sync runs itself - on save, and on a sweep for anything that failed.
     This page only reports on it, so it refreshes its own figures rather than
     offering a button to press. Watching "waiting" fall to zero is the point. */
  useEffect(() => {
    const id = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 10000);
    return () => window.clearInterval(id);
  }, [load]);

  /* The workspace tree is several ClickUp calls, so it is fetched the first
     time somebody opens the picker and kept for the rest of the visit - not as
     a button they have to press before the page becomes useful. */
  async function openPicker(project: string) {
    setPicking({ project, filter: "" });
    setError("");
    if (!workspaces) await loadLists();
  }

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
      setPicking(null);
      setResult(listId
        ? `${project} now pushes to ${listName}. ${out.queued} task(s) queued.`
        : `${project} is no longer linked.`);
      await load();
    } finally {
      setBusy("");
    }
  }

  /* Not a way to sync - the sync runs itself. This only exists for the case
     the automatic path cannot fix on its own: something that failed and is
     waiting on the five-minute sweep, where somebody who has just corrected
     the cause would rather not wait. It is shown only when there is actually
     something failing. */
  async function retryFailing() {
    setBusy("retry"); setError(""); setResult("");
    try {
      const res = await fetch("/api/clickup/sync", { method: "POST" });
      const out = await res.json();
      if (!res.ok) { setError(out.detail ?? "Retry failed."); return; }
      setResult(out.failed
        ? `${out.pushed} pushed, ${out.failed} still failing.`
          + (out.last_error ? ` ${out.last_error}` : "")
        : `${out.pushed} pushed. Nothing failing now.`);
      await load();
    } finally {
      setBusy("");
    }
  }

  async function linkPerson(userId: number, clickupId: string) {
    setBusy(`person-${userId}`);
    try {
      await fetch("/api/clickup/people/link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user: userId, clickup_id: clickupId }),
      });
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
                      hint={status.waiting ? "pushing now" : "up to date"} />
            <div>
              <StatTile label="Failing" icon="alert" value={status.failing}
                        tone={status.failing ? "bad" : "neutral"}
                        hint={status.failing ? "retried every 5 minutes" : undefined} />
              {status.failing > 0 && (
                <Button icon="sync" variant="danger" spinning={busy === "retry"}
                        onClick={retryFailing}
                        className="mt-2 w-full">
                  Retry now
                </Button>
              )}
            </div>
          </div>
        </Section>
      )}

      <Section title="Projects">
        <p className="mb-4 text-sm text-ink-3">
          Link a project to a list and it keeps itself in step from then on:
          creating a task, renaming one or moving it to In Progress or Review
          updates ClickUp within seconds, with no button to press. Anything
          unlinked is left alone. Pushing is one way — a change made in ClickUp
          is overwritten the next time its task changes here.
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
                        {current ? (
                          <Badge tone="good">
                            {current.list_name || current.list_id}
                          </Badge>
                        ) : (
                          <span className="text-[12px] text-ink-3">Not linked</span>
                        )}
                      </td>
                      <td className="py-3 pr-3 text-right whitespace-nowrap">
                        <Button icon="link" spinning={busy === p.name}
                                onClick={() => openPicker(p.name)}>
                          {current ? "Change" : "Link"}
                        </Button>
                        {current && (
                          <button
                            onClick={() => link(p.name, "", "")}
                            className="ml-1 rounded p-1.5 text-ink-3 hover:bg-subtle hover:text-bad"
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

      <Section
        title="People — one mapping, used by every project"
        className="mt-4"
        right={workspace && (
          <span className="text-[12px] text-ink-3">
            ClickUp workspace: <strong className="text-ink-2">{workspace}</strong>
          </span>
        )}
      >
        <p className="mb-4 text-sm text-ink-3">
          Set once here and it applies wherever that person is assigned — this is
          not per project. ClickUp issues a member id per workspace rather than
          per list, so the same person is the same member in every list in{" "}
          {workspace || "your workspace"}.
        </p>
        <p className="mb-4 text-sm text-ink-3">
          The two systems share no accounts: here a person is a username, in
          ClickUp an email address. Assignment is matched on the email where both
          sides have the same one, and set by hand where they do not. Somebody
          with no counterpart leaves the ClickUp task unassigned — better an
          obviously incomplete task than one assigned to the wrong person.
        </p>

        {people.length === 0 ? (
          <EmptyState icon="users" title="No users yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-stroke text-left text-[11px] uppercase tracking-wide text-ink-3">
                  <th className="py-2 pr-3 font-medium">Tracker user</th>
                  <th className="py-2 pr-3 font-medium">Email</th>
                  <th className="py-2 pr-3 font-medium">ClickUp member</th>
                </tr>
              </thead>
              <tbody>
                {people.map((pr) => (
                  <tr key={pr.id} className="border-b border-stroke last:border-0">
                    <td className="py-3 pr-3">
                      <span className="font-medium text-ink">{pr.username}</span>
                      {pr.full_name && (
                        <span className="ml-2 text-[12px] text-ink-3">{pr.full_name}</span>
                      )}
                    </td>
                    <td className="py-3 pr-3 text-ink-2">
                      {pr.email || <span className="text-ink-3">none set</span>}
                    </td>
                    <td className="py-3 pr-3">
                      <div className="flex items-center gap-2">
                        <select
                          value={pr.clickup_id}
                          disabled={busy === `person-${pr.id}`}
                          onChange={(e) => linkPerson(pr.id, e.target.value)}
                          className="w-full max-w-xs rounded-lg bg-subtle px-3 py-1.5 text-sm
                                     text-ink ring-1 ring-stroke focus:outline-none
                                     focus:ring-brand/40"
                        >
                          <option value="">— nobody —</option>
                          {members.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name}{m.email && m.name !== m.email ? ` (${m.email})` : ""}
                            </option>
                          ))}
                        </select>
                        {pr.matched_by === "email" && (
                          <Badge tone="good">by email</Badge>
                        )}
                        {pr.matched_by === "manual" && (
                          <Badge tone="info">set by hand</Badge>
                        )}
                        {!pr.matched_by && (
                          <Badge tone="warn">unassigned</Badge>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {picking && (
        <Modal
          title={`Link ${picking.project} to a ClickUp list`}
          onClose={() => setPicking(null)}
          wide
          footer={<Button onClick={() => setPicking(null)}>Cancel</Button>}
        >
          <div className="space-y-3">
            <p className="text-sm text-ink-2">
              Pick the list its tasks should appear in. From then on, creating a
              task, renaming one or moving it to In Progress or Review here
              updates the matching ClickUp task within seconds.
            </p>

            <input
              autoFocus
              value={picking.filter}
              onChange={(e) => setPicking({ ...picking, filter: e.target.value })}
              placeholder="Search lists"
              className="w-full rounded-lg bg-subtle px-3 py-2 text-sm text-ink
                         ring-1 ring-stroke placeholder:text-ink-3
                         focus:outline-none focus:ring-brand/40"
            />

            {!workspaces ? (
              <p className="py-6 text-center text-sm text-ink-3">
                Reading your ClickUp lists…
              </p>
            ) : (
              <div className="max-h-[22rem] overflow-y-auto">
                {workspaces.map((w) =>
                  w.spaces.map((sp) => {
                    const q = picking.filter.trim().toLowerCase();
                    const lists = sp.lists.filter(
                      (l) => !q || l.name.toLowerCase().includes(q)
                             || sp.name.toLowerCase().includes(q));
                    if (lists.length === 0) return null;
                    return (
                      <div key={sp.id} className="mb-3 last:mb-0">
                        <div className="mb-1 text-[11px] font-semibold uppercase
                                        tracking-wide text-ink-3">
                          {w.name} · {sp.name}
                        </div>
                        <div className="space-y-1">
                          {lists.map((l) => (
                            <button
                              key={l.id}
                              onClick={() => link(picking.project, l.id, l.name)}
                              className="flex w-full items-center justify-between
                                         rounded-lg px-3 py-2 text-left text-sm
                                         text-ink ring-1 ring-stroke transition
                                         hover:bg-brand/5 hover:ring-brand/40"
                            >
                              <span>{l.name}</span>
                              <Icon name="link" className="h-4 w-4 text-ink-3" />
                            </button>
                          ))}
                        </div>
                      </div>
                    );
                  }),
                )}
              </div>
            )}
          </div>
        </Modal>
      )}
    </AppShell>
  );
}
