"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, Row, StatTile, Badge, Button, EmptyState, Modal,
  TextInput, AreaInput, SelectInput, relativeTime,
} from "@/components/ui";

type Commit = {
  sha: string; short_sha: string; author: string; email: string;
  date: string; subject: string; refs: string;
};
type Repo = {
  id: number; name: string; company: string; description: string;
  local_path: string; remote_url: string; provider: string; default_branch: string;
  server: number | null; server_name: string; notes: string;
  available: boolean; error: string | null; branch: string | null;
  dirty: number | null; ahead: number | null; behind: number | null;
  remote: string | null; last_commit: Commit | null;
};
type Payload = { repos: Repo[]; total: number; linked: number; dirty: number };
type History = {
  repo: { id: number; name: string };
  available: boolean; error: string | null; branch: string | null;
  commits: Commit[]; ahead: number | null; behind: number | null;
  dirty: number | null; remote: string | null; last_activity: string | null;
};
type ServerOpt = { id: number; name: string; company?: string; ip?: string;
                   provider?: string };

/**
 * Which hosting a server belongs to, from its own provider field.
 *
 * The two groups are the distinction that matters when deciding where code
 * runs: a DigitalOcean droplet is reachable from anywhere, the Proxmox and
 * office machines are not.
 */
function hosting(s: ServerOpt) {
  const p = (s.provider ?? "").toLowerCase();
  if (p.includes("digitalocean")) return "DigitalOcean";
  if (p) return "Local & demo";
  // No provider and no address is a half-created row, not a server.
  return s.ip ? "Local & demo" : "";
}

const PROVIDER_OPTS = [
  { value: "github", label: "GitHub" }, { value: "gitlab", label: "GitLab" },
  { value: "bitbucket", label: "Bitbucket" }, { value: "azure", label: "Azure DevOps" },
  { value: "other", label: "Other" },
];

const BLANK = {
  name: "", company: "", description: "", local_path: "", remote_url: "",
  provider: "github", default_branch: "", server: "", notes: "",
};
type Form = typeof BLANK;

function toForm(r: Repo): Form {
  return {
    name: r.name, company: r.company, description: r.description,
    local_path: r.local_path, remote_url: r.remote_url, provider: r.provider,
    default_branch: r.default_branch, server: r.server ? String(r.server) : "", notes: r.notes,
  };
}

/** Strip a git remote down to owner/repo for display. */
function shortRemote(url?: string | null): string {
  if (!url) return "—";
  return url
    .replace(/^git@([^:]+):/, "")
    .replace(/^https?:\/\/[^/]+\//, "")
    .replace(/\.git$/, "");
}

export default function ReposPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<Payload | null>(null);
  const [servers, setServers] = useState<ServerOpt[]>([]);
  // Starts true so the first paint shows the loading state without the mount
  // effect having to set it synchronously.
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState<Repo | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [limit, setLimit] = useState(30);
  const [editing, setEditing] = useState<Repo | "new" | null>(null);
  const [form, setForm] = useState<Form>(BLANK);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [ghPrivate, setGhPrivate] = useState("private");
  // The repository awaiting a delete confirmation, and any error from it.
  const [confirming, setConfirming] = useState<Repo | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  // Every state update happens after an await, so nothing re-renders
  // synchronously while the mount effect is still running.
  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/repos");
      if (!r.ok) throw new Error(String(r.status));
      const d: Payload = await r.json();
      setData(d);
      setSel((cur) => (cur ? d.repos.find((x) => x.id === cur.id) ?? null : null));
    } catch {
      setData({ repos: [], total: 0, linked: 0, dirty: 0 });
    } finally {
      setLoading(false);
    }
  }, []);

  /** Refresh from a user action — shows the spinner, then reloads. */
  const refresh = useCallback(() => { setLoading(true); void load(); }, [load]);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "repos")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // load() only updates state after awaiting the fetch, so nothing re-renders
    // synchronously here; the rule cannot see through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    fetch("/api/servers")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setServers((d.servers ?? []).map((s: ServerOpt) => ({
        id: s.id, name: s.name, company: s.company, ip: s.ip,
        provider: s.provider }))))
      .catch(() => setServers([]));
  }, [load]);

  // Load history whenever a repo is opened or the depth changes. The handlers
  // that change `sel`/`limit` clear `history` first, so there is no setState here
  // before the fetch resolves.
  useEffect(() => {
    if (!sel) return;
    let alive = true;
    // A GitHub repository's history comes from the API; only a repo with a
    // local checkout and no remote falls back to git. The old code asked git
    // first and reported "history unavailable" for repositories it could read
    // perfectly well.
    const onGitHub = (sel.remote_url || "").includes("github.com/");
    const request = onGitHub
      ? fetch(`/api/repos/${sel.id}/commits`)
          .then((r) => (r.ok ? r.json() : Promise.reject()))
          .then((d): History => ({
            repo: { id: sel.id, name: sel.name },
            available: true, error: null,
            branch: sel.default_branch || "main",
            commits: d.commits ?? [],
            ahead: null, behind: null, dirty: null,
            remote: sel.remote_url,
            last_activity: d.commits?.[0]?.date ?? null,
          }))
      : fetch(`/api/repos/${sel.id}/history?limit=${limit}`)
          .then((r) => (r.ok ? r.json() : Promise.reject()));
    request
      .then((h: History) => { if (alive) setHistory(h); })
      .catch(() => {
        // Render an in-panel error rather than an endless spinner.
        if (alive) setHistory({
          repo: { id: sel.id, name: sel.name }, available: false,
          error: "Could not reach the server to read this repository's history.",
          branch: null, commits: [], ahead: null, behind: null, dirty: null,
          remote: null, last_activity: null,
        });
      });
    return () => { alive = false; };
  }, [sel, limit]);

  // Whether GitHub is wired up decides if the "New on GitHub" button is worth
  // showing at all - a button that always answers "no token" is noise.
  function startNew() {
    setForm(BLANK); setError(""); setGhPrivate("private");
    setEditing("new");
  }
  function startEdit(r: Repo) { setForm(toForm(r)); setError(""); setEditing(r); }
  const set = <K extends keyof Form>(k: K) => (v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    if (!editing) return;
    // Creating on GitHub is a different endpoint, and the only one that makes
    // something outside this platform.
    if (editing === "new") {
      const name = form.name.trim();
      if (!name) { setError("Give the repository a name."); return; }
      setSaving(true);
      setError("");
      try {
        const r = await fetch("/api/github/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, description: form.description,
                                 private: ghPrivate === "private",
                                 company: form.company,
                                 server: form.server ? Number(form.server) : null }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { setError(d.detail || "Could not create the repository."); return; }
        setEditing(null);
        await load();
      } finally {
        setSaving(false);
      }
      return;
    }
    setSaving(true);
    setError("");
    // A new repository always goes through GitHub above, so anything reaching
    // here is an edit of one already tracked.
    const body = { ...form, server: form.server ? Number(form.server) : null };
    const res = await fetch(`/api/repos/${editing.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setSaving(false);
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      setError(d.detail || "Could not save this repository.");
      return;
    }
    setEditing(null);
    await load();
  }

  /**
   * Deleting is two steps: the card asks, this does it.
   *
   * The browser's own confirm() and prompt() were doing this before - grey
   * system dialogs that look nothing like the app, and one of them made you
   * type the repository name. The typing was guarding the wrong thing: the
   * risk here is not mistyping, it is not realising the repo leaves GitHub,
   * and a dialog that says so plainly covers that.
   */
  async function confirmDelete() {
    const r = confirming;
    if (!r) return;
    const onGitHub = (r.remote_url || "").includes("github.com/");
    setDeleting(true);
    setDeleteError("");
    try {
      const res = onGitHub
        ? await fetch(`/api/repos/${r.id}/github-delete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirm: true }),
          })
        : await fetch(`/api/repos/${r.id}/delete`, { method: "DELETE" });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setDeleteError(d.detail || "Could not delete the repository.");
        return;
      }
      setConfirming(null);
      setSel(null);
      await load();
    } finally {
      setDeleting(false);
    }
  }

  return (
    <AppShell
      active="Repositories"
      me={me}
      wide
    >
      <PageHead
        title="Repositories"
        subtitle="Every codebase the team works on, with its latest commit. Read from GitHub, or from a local clone when there is one."
        actions={
          <>
            <Button icon="plus" variant="primary" onClick={startNew}>
              Add repository
            </Button>
            <Button icon="sync" spinning={loading} onClick={refresh} disabled={loading}>Refresh</Button>
          </>
        }
      />

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <StatTile label="Repositories" value={data?.total ?? "—"} icon="git" hint="Tracked in total" />
        <StatTile label="Showing history" value={data ? `${data.linked} of ${data.total}` : "—"} tone={data && data.linked < data.total ? "warn" : "good"} icon="branch" hint={data && data.linked < data.total ? "The rest need a GitHub remote or a local clone" : "Every repository is reporting"} />
        <StatTile label="Unsaved changes" value={data?.dirty ?? "—"} tone={(data?.dirty ?? 0) > 0 ? "warn" : "good"} icon="alert" hint="Only counted for repositories cloned onto this server" />
      </div>

      {data === null ? (
        <p className="py-12 text-center text-sm text-ink-3">Loading repositories…</p>
      ) : data.repos.length === 0 ? (
        <EmptyState
          icon="git"
          title="No repositories tracked yet"
          hint="Create one on GitHub and it is tracked here from the moment it exists — its branch, its latest commit, and a link straight to it."
          action={<Button icon="plus" variant="primary" onClick={startNew}>Add repository</Button>}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {data.repos.map((r) => (
            /* The card is the button. Clicking a small line of text inside a
               large tile is a target nobody aims for. The name and the row
               actions still do their own thing and stop the click. */
            <div key={r.id} role="button" tabIndex={0}
                 onClick={() => { setHistory(null); setLimit(30); setSel(r); }}
                 onKeyDown={(e) => {
                   if (e.key === "Enter" || e.key === " ") {
                     e.preventDefault();
                     setHistory(null); setLimit(30); setSel(r);
                   }
                 }}
                 className="group flex cursor-pointer flex-col rounded-lg border border-stroke bg-surface p-4 shadow-sm transition hover:border-brand hover:shadow-md focus-ring">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  {/* The name opens the repository itself — that is what
                      somebody is reaching for when they click it. History
                      stays available on the line below. */}
                  {r.remote_url ? (
                    <a href={r.remote_url} target="_blank" rel="noreferrer"
                       onClick={(e) => e.stopPropagation()}
                       className="block truncate font-semibold leading-tight text-ink transition hover:text-brand-hover hover:underline">
                      {r.name}
                    </a>
                  ) : (
                    <h3 className="truncate font-semibold leading-tight text-ink">{r.name}</h3>
                  )}
                  <p className="truncate text-xs text-ink-3">{shortRemote(r.remote_url || r.remote)}</p>
                </div>
                {r.available
                  ? <Badge tone="good"><Icon name="branch" className="h-3 w-3" />{r.branch ?? "?"}</Badge>
                  : <Badge tone="warn">No history</Badge>}
              </div>

              {r.description && <p className="mt-2 line-clamp-2 text-xs text-ink-2">{r.description}</p>}

              <div className="mt-3 flex-1">
                {/* When it last changed, not what changed - the message is a
                    line of somebody else's shorthand, and the card is for
                    scanning a list of repositories. The full history is a
                    click away. */}
                {r.available && r.last_commit ? (
                  <p className="text-xs text-ink-2">
                    Last commit {relativeTime(r.last_commit.date)}
                  </p>
                ) : (
                  <p className="text-xs text-warnx">{r.error ?? "No history available."}</p>
                )}
              </div>

              <div className="mt-3 flex items-center justify-between border-t border-stroke-soft pt-3 text-xs text-ink-3">
                <div className="flex items-center gap-2">
                  {(r.ahead ?? 0) > 0 && <span className="text-brand">↑{r.ahead} unpushed</span>}
                  {(r.behind ?? 0) > 0 && <span className="text-warnx">↓{r.behind} behind</span>}
                  {(r.dirty ?? 0) > 0 && <span className="text-warnx">{r.dirty} changed</span>}
                  {r.available && !r.ahead && !r.behind && !r.dirty && <span className="text-good">Clean</span>}
                </div>
                <div onClick={(e) => e.stopPropagation()}
                     className="flex gap-1 opacity-0 transition group-hover:opacity-100">
                  <Button variant="ghost" icon="edit" onClick={() => startEdit(r)} aria-label={`Edit ${r.name}`} />
                  <Button variant="ghost" icon="trash" onClick={() => { setDeleteError(""); setConfirming(r); }} aria-label={`Remove ${r.name}`} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Details */}
      {sel && (
        <Modal
          wide
          title={sel.name}
          onClose={() => setSel(null)}
          footer={
            <>
              {/* Every repository gets a project of the same name when it is
                  created, so these always have somewhere to land. */}
              <Link href={`/repos/${sel.id}/docs`}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium text-ink-2 ring-control transition hover:bg-subtle hover:text-ink focus-ring">
                <Icon name="docs" className="h-4 w-4" />
                Documentation
              </Link>
              <Link href={`/tasks?project=${encodeURIComponent(sel.name)}`}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium text-ink-2 ring-control transition hover:bg-subtle hover:text-ink focus-ring">
                <Icon name="board" className="h-4 w-4" />
                Project
              </Link>
              <Button icon="edit" onClick={() => { const r = sel; setSel(null); startEdit(r); }}>Edit</Button>
              <Button variant="primary" onClick={() => setSel(null)}>Close</Button>
            </>
          }
        >
          {sel.description && (
            <p className="mb-4 text-sm text-ink-2">{sel.description}</p>
          )}

          <div className="grid gap-x-8 gap-y-1 sm:grid-cols-2">
            <Row k="Branch" v={history?.branch ?? sel.branch ?? sel.default_branch} />
            <Row k="Company" v={sel.company} />
            <Row k="Provider" v={sel.provider} />
            <Row k="Deployed on" v={sel.server_name} />
            <Row k="Last commit"
                 v={history?.last_activity ? relativeTime(history.last_activity)
                                           : sel.last_commit ? relativeTime(sel.last_commit.date)
                                           : null} />
            <Row k="Remote" v={shortRemote(history?.remote ?? sel.remote_url)} />
            {sel.local_path && <Row k="Local path" v={sel.local_path} mono />}
            {/* Only meaningful for a checkout on this host; a repository read
                through the API has no working tree to be dirty. */}
            {sel.local_path && (
              <Row k="Uncommitted files" v={history?.dirty ?? sel.dirty ?? 0} />
            )}
          </div>

          {sel.notes && (
            <div className="mt-4 border-t border-stroke pt-3">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-3">Notes</p>
              <p className="whitespace-pre-wrap text-sm text-ink-2">{sel.notes}</p>
            </div>
          )}

          {/* The commit list lived here and duplicated, worse, what GitHub
              already shows. One link is more use than a truncated copy. */}
          {sel.remote_url && (
            <a href={sel.remote_url} target="_blank" rel="noreferrer"
               className="mt-4 flex items-center gap-2.5 rounded-lg bg-subtle px-3 py-2.5 text-sm text-ink transition hover:bg-brand-tint focus-ring">
              <Icon name="git" className="h-4 w-4 shrink-0 text-ink-3" />
              <span className="flex-1">
                View the full history on GitHub
                {history?.commits?.length
                  ? ` · latest ${history.commits[0].short_sha}` : ""}
              </span>
              <Icon name="link" className="h-3.5 w-3.5 shrink-0 text-ink-3" />
            </a>
          )}
        </Modal>
      )}

      {/* Create / edit */}
      {confirming && (
        <Modal
          compact
          title={`Delete ${confirming.name}?`}
          onClose={() => setConfirming(null)}
          footer={
            <>
              {deleteError && (
                <p className="mr-auto text-sm text-bad">{deleteError}</p>
              )}
              <Button onClick={() => setConfirming(null)}>Cancel</Button>
              <Button variant="danger" onClick={confirmDelete} disabled={deleting}>
                {deleting ? "Deleting…" : "Delete repository"}
              </Button>
            </>
          }
        >
          {(confirming.remote_url || "").includes("github.com/") ? (
            <>
              <p className="text-sm text-ink">
                This deletes{" "}
                <span className="font-semibold">
                  {shortRemote(confirming.remote_url)}
                </span>{" "}
                from GitHub — the code, the history and any issues go with it.
              </p>
              <p className="mt-2 text-sm text-bad">This cannot be undone.</p>
            </>
          ) : (
            <p className="text-sm text-ink">
              This stops tracking{" "}
              <span className="font-semibold">{confirming.name}</span> here.
              Nothing outside the platform is touched.
            </p>
          )}
        </Modal>
      )}

      {editing && (
        <Modal
          wide
          title={editing === "new" ? "New repository on GitHub"
                                   : `Edit ${editing.name}`}
          onClose={() => setEditing(null)}
          footer={
            <>
              {error && <p className="mr-auto text-sm text-bad">{error}</p>}
              <Button onClick={() => setEditing(null)}>Cancel</Button>
              <Button variant="primary" onClick={save} disabled={saving}>
                {saving ? "Creating…"
                        : editing === "new" ? "Create repository" : "Save"}
              </Button>
            </>
          }
        >
          <div className="space-y-4">
            {/* One short form, not two boxed panels: five fields do not need
                sections drawn around them, and the borders were carrying more
                weight than the fields. */}
            <div className="grid gap-4 sm:grid-cols-2">
              <TextInput label="Repository name" value={form.name}
                         onChange={set("name")} placeholder="client-portal"
                         hint="Letters, numbers, hyphens." />
              <SelectInput label="Visibility" value={ghPrivate}
                           onChange={setGhPrivate}
                           hint={ghPrivate === "public"
                             ? "Anyone can read it."
                             : "Only your account can see it."}
                           options={[{ value: "private", label: "Private" },
                                     { value: "public", label: "Public" }]} />
              <div className="sm:col-span-2">
                <AreaInput label="Description" rows={2} value={form.description}
                           onChange={set("description")} />
              </div>
              <SelectInput label="Company" value={form.company}
                           onChange={set("company")}
                           options={[{ value: "", label: "— not set —" },
                                     { value: "MOC", label: "MOC" },
                                     { value: "FSA", label: "FSA" }]} />
              <SelectInput
                label="Deployed on"
                value={form.server}
                onChange={set("server")}
                hint="Optional."
                options={[{ value: "", label: "— none —" },
                          ...servers
                            .filter((sv) => hosting(sv))
                            .map((sv) => ({
                              value: String(sv.id),
                              label: sv.ip ? `${sv.name} · ${sv.ip}` : sv.name,
                              group: hosting(sv),
                            }))]}
              />
            </div>
            <p className="mt-4 rounded-lg bg-subtle px-3 py-2.5 text-xs text-ink-2">
              A project of the same name is created alongside it, with a
              <b> Documentation</b> list — so the work has somewhere to live
              from the start.
            </p>
          </div>
        </Modal>
      )}
    </AppShell>
  );
}
