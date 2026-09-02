"use client";

import { useCallback, useEffect, useState } from "react";
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
type ServerOpt = { id: number; name: string };

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

function CommitRow({ c, first }: { c: Commit; first?: boolean }) {
  const tags = (c.refs || "")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s && !s.startsWith("HEAD ->"));
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      {/* timeline rail */}
      <span className="absolute left-[7px] top-4 h-full w-px bg-stroke last:hidden" aria-hidden />
      <span className={`relative z-10 mt-1 h-3.5 w-3.5 shrink-0 rounded-full border-2 ${first ? "border-brand bg-brand-tint" : "border-ink-3 bg-surface"}`} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium leading-snug text-ink">{c.subject}</p>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-3">
          <span className="font-mono text-ink-2">{c.short_sha}</span>
          <span>·</span>
          <span>{c.author}</span>
          <span>·</span>
          <span title={c.date}>{relativeTime(c.date)}</span>
          {tags.map((t) => (
            <span key={t} className="rounded bg-subtle px-1.5 py-0.5 font-mono text-xs text-ink-2">{t}</span>
          ))}
        </div>
      </div>
    </li>
  );
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
  // Derived rather than stored: history is cleared by the handlers that trigger
  // a re-fetch, so "no history yet for the open repo" is exactly the loading state.
  const hLoading = sel !== null && history === null;
  const [editing, setEditing] = useState<Repo | "new" | null>(null);
  const [form, setForm] = useState<Form>(BLANK);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

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
      .then((d) => setServers((d.servers ?? []).map((s: ServerOpt) => ({ id: s.id, name: s.name }))))
      .catch(() => setServers([]));
  }, [load]);

  // Load history whenever a repo is opened or the depth changes. The handlers
  // that change `sel`/`limit` clear `history` first, so there is no setState here
  // before the fetch resolves.
  useEffect(() => {
    if (!sel) return;
    let alive = true;
    fetch(`/api/repos/${sel.id}/history?limit=${limit}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
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

  function startNew() { setForm(BLANK); setError(""); setEditing("new"); }
  function startEdit(r: Repo) { setForm(toForm(r)); setError(""); setEditing(r); }
  const set = <K extends keyof Form>(k: K) => (v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    if (!editing) return;
    setSaving(true);
    setError("");
    const body = { ...form, server: form.server ? Number(form.server) : null };
    const url = editing === "new" ? "/api/repos/create" : `/api/repos/${editing.id}`;
    const res = await fetch(url, {
      method: editing === "new" ? "POST" : "PATCH",
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

  async function remove(r: Repo) {
    if (!confirm(`Remove "${r.name}" from the platform? The repository itself is untouched.`)) return;
    await fetch(`/api/repos/${r.id}/delete`, { method: "DELETE" });
    setSel(null);
    await load();
  }

  return (
    <AppShell
      active="Repositories"
      me={me}
      wide
    >
      <PageHead
        title="Repositories"
        subtitle="Every tracked codebase, its latest commit and recent history — read live from git."
        actions={
          <>
            <Button icon="plus" variant="primary" onClick={startNew}>Add repository</Button>
            <Button icon="sync" spinning={loading} onClick={refresh} disabled={loading}>Refresh</Button>
          </>
        }
      />

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <StatTile label="Repositories" value={data?.total ?? "—"} icon="git" hint="Tracked in total" />
        <StatTile label="Readable" value={data ? `${data.linked}/${data.total}` : "—"} tone={data && data.linked < data.total ? "warn" : "good"} icon="branch" hint="Git history available" />
        <StatTile label="Uncommitted work" value={data?.dirty ?? "—"} tone={(data?.dirty ?? 0) > 0 ? "warn" : "good"} icon="alert" hint="Repos with local changes" />
      </div>

      {data === null ? (
        <p className="py-12 text-center text-sm text-ink-3">Loading repositories…</p>
      ) : data.repos.length === 0 ? (
        <EmptyState
          icon="git"
          title="No repositories tracked yet"
          hint="Add a repository with its local path on this host and Sentinel will read the branch, latest commit and history straight from git — no tokens needed."
          action={<Button icon="plus" variant="primary" onClick={startNew}>Add repository</Button>}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {data.repos.map((r) => (
            <div key={r.id} className="group flex flex-col rounded-lg border border-stroke bg-surface p-4 shadow-sm transition hover:border-brand hover:shadow-md">
              <div className="flex items-start justify-between gap-2">
                <button onClick={() => { setHistory(null); setLimit(30); setSel(r); }} className="min-w-0 text-left">
                  <h3 className="truncate font-semibold leading-tight text-ink group-hover:text-brand-hover">{r.name}</h3>
                  <p className="truncate text-xs text-ink-3">{shortRemote(r.remote_url || r.remote)}</p>
                </button>
                {r.available
                  ? <Badge tone="good"><Icon name="branch" className="h-3 w-3" />{r.branch ?? "?"}</Badge>
                  : <Badge tone="warn">Unreadable</Badge>}
              </div>

              {r.description && <p className="mt-2 line-clamp-2 text-xs text-ink-2">{r.description}</p>}

              <div className="mt-3 flex-1">
                {r.available && r.last_commit ? (
                  <div className="rounded-lg bg-subtle p-2.5">
                    <p className="line-clamp-2 text-xs font-medium text-ink">{r.last_commit.subject}</p>
                    <p className="mt-1 text-xs text-ink-3">
                      <span className="font-mono">{r.last_commit.short_sha}</span> · {r.last_commit.author} · {relativeTime(r.last_commit.date)}
                    </p>
                  </div>
                ) : (
                  <p className="rounded-lg bg-warnx-bg p-2.5 text-xs text-warnx">{r.error ?? "No history available."}</p>
                )}
              </div>

              <div className="mt-3 flex items-center justify-between border-t border-stroke-soft pt-3 text-xs text-ink-3">
                <div className="flex items-center gap-2">
                  {(r.ahead ?? 0) > 0 && <span className="text-brand">↑{r.ahead} unpushed</span>}
                  {(r.behind ?? 0) > 0 && <span className="text-warnx">↓{r.behind} behind</span>}
                  {(r.dirty ?? 0) > 0 && <span className="text-warnx">{r.dirty} changed</span>}
                  {r.available && !r.ahead && !r.behind && !r.dirty && <span className="text-good">Clean</span>}
                </div>
                <div className="flex gap-1 opacity-0 transition group-hover:opacity-100">
                  <Button variant="ghost" icon="edit" onClick={() => startEdit(r)} aria-label={`Edit ${r.name}`} />
                  <Button variant="ghost" icon="trash" onClick={() => remove(r)} aria-label={`Remove ${r.name}`} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* History */}
      {sel && (
        <Modal
          wide
          title={`${sel.name} — history`}
          onClose={() => setSel(null)}
          footer={
            <>
              {history?.available && history.commits.length >= limit && (
                <Button className="mr-auto" onClick={() => { setHistory(null); setLimit((l) => l + 50); }} disabled={hLoading}>
                  {hLoading ? "Loading…" : "Load more"}
                </Button>
              )}
              <Button icon="edit" onClick={() => { const r = sel; setSel(null); startEdit(r); }}>Edit</Button>
              <Button variant="primary" onClick={() => setSel(null)}>Close</Button>
            </>
          }
        >
          <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
            <div>
              <div className="mb-3 flex items-center gap-2 text-xs text-ink-3">
                <Icon name="commit" className="h-3.5 w-3.5" />
                {hLoading ? "Reading git…" : history?.available ? `${history.commits.length} most recent commits` : "No history"}
              </div>
              {!history && hLoading && <p className="py-8 text-center text-sm text-ink-3">Reading git history…</p>}
              {history && !history.available && (
                <div className="rounded-xl bg-warnx-bg ring-1 ring-inset ring-warnx/20 p-5">
                  <p className="text-sm font-semibold text-warnx">Git history unavailable</p>
                  <p className="mt-1 text-sm text-warnx">{history.error}</p>
                  <p className="mt-2 text-xs text-warnx">
                    Set this repository&apos;s <b>local path</b> to a git checkout that exists on the host running Sentinel.
                  </p>
                </div>
              )}
              {history?.available && (
                history.commits.length > 0
                  ? <ul className="relative">{history.commits.map((c, i) => <CommitRow key={c.sha} c={c} first={i === 0} />)}</ul>
                  : <p className="py-8 text-center text-sm text-ink-3">This repository has no commits yet.</p>
              )}
            </div>

            <div className="space-y-3">
              <Section title="Repository">
                <Row k="Branch" v={history?.branch ?? sel.branch} />
                <Row k="Provider" v={sel.provider} />
                <Row k="Company" v={sel.company} />
                <Row k="Server" v={sel.server_name} />
                <Row k="Last activity" v={history?.last_activity ? relativeTime(history.last_activity) : null} />
              </Section>
              <Section title="Working tree">
                <Row k="Uncommitted files" v={history?.dirty ?? sel.dirty ?? 0} />
                <Row k="Unpushed commits" v={history?.ahead ?? sel.ahead} />
                <Row k="Behind remote" v={history?.behind ?? sel.behind} />
                <p className="pt-2 text-xs leading-snug text-ink-3">
                  Ahead/behind compares against the last-fetched remote ref — Sentinel never runs a fetch or any network git command.
                </p>
              </Section>
              <Section title="Location">
                <Row k="Remote" v={shortRemote(history?.remote ?? sel.remote_url)} />
                <Row k="Local path" v={sel.local_path} mono />
              </Section>
              {sel.notes && <Section title="Notes"><p className="whitespace-pre-wrap text-sm text-ink-2">{sel.notes}</p></Section>}
            </div>
          </div>
        </Modal>
      )}

      {/* Create / edit */}
      {editing && (
        <Modal
          wide
          title={editing === "new" ? "Add repository" : `Edit ${editing.name}`}
          onClose={() => setEditing(null)}
          footer={
            <>
              {error && <p className="mr-auto text-sm text-bad">{error}</p>}
              <Button onClick={() => setEditing(null)}>Cancel</Button>
              <Button variant="primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save repository"}</Button>
            </>
          }
        >
          <div className="space-y-4">
            <Section title="Identity">
              <div className="grid gap-3 sm:grid-cols-3">
                <TextInput label="Name" value={form.name} onChange={set("name")} placeholder="MagnumOpus-Automation-Hub" />
                <TextInput label="Company" value={form.company} onChange={set("company")} />
                <SelectInput label="Provider" value={form.provider} onChange={set("provider")} options={PROVIDER_OPTS} />
              </div>
              <div className="mt-3">
                <AreaInput label="Description" rows={2} value={form.description} onChange={set("description")} />
              </div>
            </Section>
            <Section title="Location">
              <div className="grid gap-3 sm:grid-cols-2">
                <TextInput label="Local path" hint="on the Sentinel host" value={form.local_path} onChange={set("local_path")} placeholder="/var/www/app" />
                <TextInput label="Remote URL" value={form.remote_url} onChange={set("remote_url")} placeholder="git@github.com:org/repo.git" />
                <TextInput label="Default branch" value={form.default_branch} onChange={set("default_branch")} placeholder="main" />
                <SelectInput
                  label="Hosted on server"
                  value={form.server}
                  onChange={set("server")}
                  options={[{ value: "", label: "— none —" }, ...servers.map((s) => ({ value: String(s.id), label: s.name }))]}
                />
              </div>
              <p className="mt-2 text-xs text-ink-3">
                The <b>local path</b> is what enables history — it must be a git checkout on the machine running this platform.
              </p>
            </Section>
            <Section title="Notes">
              <AreaInput label="Notes" value={form.notes} onChange={set("notes")} />
            </Section>
          </div>
        </Modal>
      )}
    </AppShell>
  );
}
