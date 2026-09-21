"use client";

/**
 * Users & Access: every account, what it can open, and which workspaces it can
 * reach - in one place.
 *
 * Module access and workspace allocation used to live in two different corners
 * of the app (a page nobody linked, and a right-click menu). Answering "what
 * can this person actually see?" meant checking both.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, StatTile, Badge, Button, EmptyState, Modal,
  TextInput, SelectInput, CheckboxInput, Pill,
} from "@/components/ui";

type Grant = { workspace: string; role: string; role_display: string; notified: boolean };
type UserRow = {
  id: number; username: string; full_name: string; email: string;
  is_admin: boolean; is_active: boolean; modules: string[];
  last_login: string | null; date_joined: string | null;
  workspaces: Grant[]; sees_all_workspaces: boolean;
};
type ModuleDef = { key: string; label: string; desc: string };
type Payload = {
  users: UserRow[]; modules: ModuleDef[];
  workspaces: { name: string; is_default: boolean }[];
  roles: [string, string][];
};

const FILTERS = ["All", "Administrators", "Members", "Inactive"] as const;
type Filter = (typeof FILTERS)[number];

type Form = {
  username: string; full_name: string; email: string; password: string;
  is_admin: boolean; is_active: boolean; modules: string[];
};
const BLANK: Form = {
  username: "", full_name: "", email: "", password: "",
  is_admin: false, is_active: true, modules: [],
};

export default function AccessPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<Payload | null>(null);
  // Starts true so the first paint shows the loading state without the mount
  // effect having to set it synchronously.
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("All");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<UserRow | "new" | null>(null);
  const [form, setForm] = useState<Form>(BLANK);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  // Which user's workspace panel is open, plus the pending add.
  const [expanded, setExpanded] = useState<number | null>(null);
  const [allocating, setAllocating] = useState<
    { user: UserRow; workspace: string; role: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/users");
      if (!r.ok) throw new Error(String(r.status));
      setData(await r.json());
    } catch {
      setData({ users: [], modules: [], workspaces: [], roles: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!(m.is_admin || m.is_superuser)) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // load() only updates state after awaiting the fetch, so nothing re-renders
    // synchronously here; the rule cannot see through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const users = useMemo(() => data?.users ?? [], [data]);
  const modules = useMemo(() => data?.modules ?? [], [data]);
  const workspaces = useMemo(() => data?.workspaces ?? [], [data]);
  const roles = useMemo(() => data?.roles ?? [], [data]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return users.filter((u) => {
      if (filter === "Administrators" && !u.is_admin) return false;
      if (filter === "Members" && (u.is_admin || !u.is_active)) return false;
      if (filter === "Inactive" && u.is_active) return false;
      if (needle && !`${u.username} ${u.full_name} ${u.email}`.toLowerCase().includes(needle)) {
        return false;
      }
      return true;
    });
  }, [users, filter, q]);

  const stats = useMemo(() => ({
    total: users.length,
    admins: users.filter((u) => u.is_admin).length,
    inactive: users.filter((u) => !u.is_active).length,
    noEmail: users.filter((u) => !u.email).length,
  }), [users]);

  function startNew() {
    setForm({ ...BLANK, modules: modules.map((m) => m.key) });
    setError("");
    setEditing("new");
  }

  function startEdit(u: UserRow) {
    setForm({
      username: u.username, full_name: u.full_name === u.username ? "" : u.full_name,
      email: u.email, password: "",
      is_admin: u.is_admin, is_active: u.is_active, modules: [...u.modules],
    });
    setError("");
    setEditing(u);
  }

  async function save() {
    if (!form.username.trim()) {
      setError("A username is required.");
      return;
    }
    if (editing === "new" && !form.password) {
      setError("Set a password for the new account.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const url = editing === "new" ? "/api/users/create" : `/api/users/${(editing as UserRow).id}`;
      const body: Record<string, unknown> = { ...form };
      // An empty password on an edit means "leave it alone", not "blank it".
      if (editing !== "new" && !form.password) delete body.password;
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || d.error || `Save failed (${r.status})`);
      }
      setEditing(null);
      setNote(editing === "new"
        ? `${form.username} was created.`
        : `${form.username} was updated.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function remove(u: UserRow) {
    if (u.id === me?.id) {
      alert("You cannot delete the account you are signed in with.");
      return;
    }
    if (!confirm(`Delete ${u.username}? This cannot be undone.`)) return;
    const r = await fetch(`/api/users/${u.id}/delete`, { method: "DELETE" });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      alert(d.detail || "Could not delete that user.");
      return;
    }
    setNote(`${u.username} was deleted.`);
    await load();
  }

  async function addGrant() {
    if (!allocating) return;
    if (!allocating.workspace) return;
    setSaving(true);
    try {
      const r = await fetch("/api/tasks/workspaces/members/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: allocating.workspace,
          user: allocating.user.username,
          role: allocating.role,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        alert(d.detail || "Could not grant access.");
        return;
      }
      setNote(d.no_email_on_file
        ? `${allocating.user.username} was added to ${allocating.workspace}, but has no email address so no notification was sent.`
        : d.notified
          ? `${allocating.user.username} was added to ${allocating.workspace} and notified by email.`
          : `${allocating.user.username} was added to ${allocating.workspace}, but the email failed to send.`);
      setAllocating(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function changeRole(u: UserRow, workspace: string, role: string) {
    await fetch("/api/tasks/workspaces/members/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace, user: u.username, role }),
    });
    setNote(`${u.username} is now a ${role} in ${workspace}.`);
    await load();
  }

  async function revoke(u: UserRow, workspace: string) {
    if (!confirm(`Remove ${u.username} from ${workspace}?`)) return;
    await fetch("/api/tasks/workspaces/members/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace, user: u.username }),
    });
    setNote(`${u.username} was removed from ${workspace}.`);
    await load();
  }

  function toggleModule(key: string) {
    setForm((f) => ({
      ...f,
      modules: f.modules.includes(key)
        ? f.modules.filter((k) => k !== key)
        : [...f.modules, key],
    }));
  }

  return (
    <AppShell active="Users & Access" me={me} wide>
      <PageHead
        title="Users & Access"
        subtitle="Every account, what it can open, and which workspaces it can reach."
        actions={
          <>
            <Button icon="plus" variant="primary" onClick={startNew}>New user</Button>
            <Button icon="sync" spinning={loading}
                    onClick={() => { setLoading(true); void load(); }}>Refresh</Button>
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Users" value={loading ? "—" : stats.total} icon="users" />
        <StatTile label="Administrators" value={loading ? "—" : stats.admins}
                  icon="shield" tone="accent" />
        <StatTile label="Inactive" value={loading ? "—" : stats.inactive}
                  icon="lock" tone={stats.inactive ? "warn" : "neutral"} />
        <StatTile label="No email on file" value={loading ? "—" : stats.noEmail}
                  icon="mail" tone={stats.noEmail ? "warn" : "neutral"}
                  hint={stats.noEmail ? "Cannot be notified" : undefined} />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search by name, username or email…"
          className="h-9 min-w-52 flex-1 rounded-lg bg-surface px-3 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring"
        />
        {FILTERS.map((f) => (
          <Pill key={f} active={filter === f} onClick={() => setFilter(f)}>{f}</Pill>
        ))}
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
        <Section><div className="p-6 text-sm text-ink-2">Loading users…</div></Section>
      ) : shown.length === 0 ? (
        <Section>
          <EmptyState icon="users"
                      title={users.length ? "No users match" : "No users yet"}
                      hint={users.length ? "Try a different filter." : "Create the first account."}
                      action={<Button icon="plus" variant="primary" onClick={startNew}>New user</Button>} />
        </Section>
      ) : (
        <Section>
          <div className="hidden items-center gap-3 border-b border-stroke bg-subtle/60 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3 lg:flex">
            <span className="w-6" />
            <span className="flex-1">User</span>
            <span className="w-24">Role</span>
            <span className="w-28">Can open</span>
            <span className="w-32">Workspaces</span>
            <span className="w-24">Last seen</span>
            <span className="w-20 text-right">Actions</span>
          </div>

          <ul className="divide-y divide-stroke">
            {shown.map((u) => {
              const open = expanded === u.id;
              const pageCount = u.is_admin ? modules.length : u.modules.length;
              const wsCount = u.sees_all_workspaces ? -1 : u.workspaces.length;
              return (
                <li key={u.id}>
                  <div className={`flex items-center gap-3 px-3 py-2.5 transition hover:bg-subtle/40 ${
                    open ? "bg-subtle/50" : ""
                  }`}>
                    <button onClick={() => setExpanded(open ? null : u.id)}
                            aria-label={open ? "Collapse" : "Expand"}
                            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-2 transition hover:bg-subtle hover:text-ink focus-ring">
                      <Icon name="chevron"
                            className={`h-4 w-4 transition-transform ${open ? "" : "rotate-180"}`} />
                    </button>

                    <button onClick={() => setExpanded(open ? null : u.id)}
                            className="flex min-w-0 flex-1 items-center gap-2.5 text-left focus-ring">
                      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold text-white ${
                        u.is_active ? "bg-brand" : "bg-ink-3"
                      }`}>
                        {u.username.slice(0, 2).toUpperCase()}
                      </span>
                      <span className="min-w-0">
                        <span className="flex items-center gap-1.5">
                          <span className="truncate text-sm font-medium text-ink">
                            {u.full_name || u.username}
                          </span>
                          {u.id === me?.id && <Badge tone="info">You</Badge>}
                          {!u.is_active && <Badge tone="bad">Inactive</Badge>}
                        </span>
                        <span className="block truncate text-xs text-ink-3">
                          {u.username}
                          {u.email
                            ? ` · ${u.email}`
                            : " · no email"}
                        </span>
                      </span>
                    </button>

                    <span className="hidden w-24 shrink-0 lg:block">
                      {u.is_admin
                        ? <Badge tone="accent">Admin</Badge>
                        : <span className="text-xs text-ink-3">Member</span>}
                    </span>

                    {/* Counts, with a warning tint when the answer is "nothing" */}
                    <span className={`hidden w-28 shrink-0 text-xs lg:block ${
                      !u.is_admin && pageCount === 0 ? "font-medium text-warnx" : "text-ink-2"
                    }`}>
                      {u.is_admin ? "Everything"
                        : pageCount === 0 ? "No pages"
                        : `${pageCount} of ${modules.length} pages`}
                    </span>

                    <span className={`hidden w-32 shrink-0 truncate text-xs lg:block ${
                      wsCount === 0 ? "font-medium text-warnx" : "text-ink-2"
                    }`}>
                      {wsCount === -1 ? "All workspaces"
                        : wsCount === 0 ? "None"
                        : u.workspaces.map((g) => g.workspace).join(", ")}
                    </span>

                    <span className="hidden w-24 shrink-0 text-xs text-ink-3 lg:block">
                      {u.last_login ? u.last_login.slice(0, 10) : "never"}
                    </span>

                    <span className="flex w-20 shrink-0 justify-end gap-0.5">
                      <button onClick={() => startEdit(u)} aria-label={`Edit ${u.username}`}
                              title="Edit"
                              className="flex h-7 w-7 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring">
                        <Icon name="edit" className="h-4 w-4" />
                      </button>
                      <button onClick={() => remove(u)} aria-label={`Delete ${u.username}`}
                              title="Delete"
                              className="flex h-7 w-7 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-bad focus-ring">
                        <Icon name="trash" className="h-4 w-4" />
                      </button>
                    </span>
                  </div>

                  {open && (
                    <div className="grid grid-cols-1 gap-5 border-t border-stroke bg-canvas px-3 py-4 pl-12 lg:grid-cols-2">
                      <div>
                        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                          Pages
                        </p>
                        {u.is_admin ? (
                          <p className="text-xs text-ink-2">
                            Administrators bypass module access entirely.
                          </p>
                        ) : (
                          <div className="flex flex-wrap gap-1.5">
                            {modules.map((m) => (
                              <span key={m.key}
                                    className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                                      u.modules.includes(m.key)
                                        ? "bg-brand-tint text-brand-pressed"
                                        : "bg-subtle text-ink-3 line-through opacity-60"
                                    }`}>
                                {m.label}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>

                      <div>
                        <div className="mb-2 flex items-center justify-between">
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                            Workspace access
                          </p>
                          {!u.is_admin && (
                            <button
                              onClick={() => setAllocating({
                                user: u,
                                workspace: workspaces.find(
                                  (w) => !u.workspaces.some((g) => g.workspace === w.name))?.name ?? "",
                                role: "member",
                              })}
                              className="rounded px-1.5 py-0.5 text-[11px] font-medium text-brand transition hover:bg-brand-tint focus-ring"
                            >
                              + Grant access
                            </button>
                          )}
                        </div>

                        {u.sees_all_workspaces ? (
                          <p className="text-xs text-ink-2">
                            Not restricted — administrators reach every workspace.
                          </p>
                        ) : u.workspaces.length === 0 ? (
                          <p className="text-xs italic text-ink-3">
                            No workspaces, so no project work is visible to them.
                          </p>
                        ) : (
                          <ul className="space-y-1">
                            {u.workspaces.map((g) => (
                              <li key={g.workspace} className="flex items-center gap-2">
                                <Icon name="board" className="h-3.5 w-3.5 shrink-0 text-ink-3" />
                                <span className="min-w-0 flex-1 truncate text-xs text-ink">
                                  {g.workspace}
                                </span>
                                {!g.notified && (
                                  <span title="Not notified by email"
                                        className="shrink-0 text-[10px] text-warnx">
                                    not notified
                                  </span>
                                )}
                                <select
                                  value={g.role}
                                  onChange={(e) => void changeRole(u, g.workspace, e.target.value)}
                                  aria-label={`Role for ${u.username} in ${g.workspace}`}
                                  className="h-6 shrink-0 rounded bg-transparent px-1 text-[11px] text-ink-2 ring-control focus-ring"
                                >
                                  {roles.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                                </select>
                                <button onClick={() => void revoke(u, g.workspace)}
                                        aria-label={`Remove ${u.username} from ${g.workspace}`}
                                        className="shrink-0 text-ink-3 transition hover:text-bad focus-ring">
                                  <Icon name="trash" className="h-3.5 w-3.5" />
                                </button>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {/* ── Grant access ── */}
      {allocating && (
        <Modal
          title="Grant workspace access"
          onClose={() => setAllocating(null)}
          footer={
            <>
              <Button onClick={() => setAllocating(null)}>Cancel</Button>
              <Button variant="primary" spinning={saving} onClick={addGrant}
                      disabled={saving || !allocating.workspace}>
                {allocating.user.email ? "Grant & notify" : "Grant access"}
              </Button>
            </>
          }
        >
          {/* Who this is for, so the dialog is unambiguous when several are open
              in quick succession. */}
          <div className="mb-5 flex items-center gap-3 rounded-lg bg-subtle/60 p-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-semibold text-white">
              {allocating.user.username.slice(0, 2).toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-ink">
                {allocating.user.full_name || allocating.user.username}
              </p>
              <p className="truncate text-xs text-ink-3">
                {allocating.user.email || "no email address on file"}
              </p>
            </div>
          </div>

          {workspaces.every((w) => allocating.user.workspaces.some((g) => g.workspace === w.name)) ? (
            <p className="text-sm text-ink-2">
              {allocating.user.username} already has access to every workspace.
            </p>
          ) : (
            <>
              <p className="mb-1.5 text-sm font-medium text-ink">Workspace</p>
              <select
                value={allocating.workspace}
                onChange={(e) => setAllocating({ ...allocating, workspace: e.target.value })}
                className="mb-5 h-10 w-full rounded-lg bg-canvas px-3 text-sm text-ink ring-control focus-ring"
              >
                {workspaces
                  .filter((w) => !allocating.user.workspaces.some((g) => g.workspace === w.name))
                  .map((w) => <option key={w.name} value={w.name}>{w.name}</option>)}
              </select>

              {/* Roles as cards: a select hides what each one actually permits,
                  which is the only thing being decided here. */}
              <p className="mb-1.5 text-sm font-medium text-ink">Role</p>
              <div className="space-y-2">
                {roles.map(([value, label]) => {
                  const on = allocating.role === value;
                  const blurb = value === "viewer"
                    ? "Can read the work. Cannot change anything."
                    : value === "member"
                      ? "Can create and edit tasks in the workspace."
                      : "Can also manage its projects, lists and members.";
                  return (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setAllocating({ ...allocating, role: value })}
                      aria-pressed={on}
                      className={`flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left ring-1 ring-inset transition ${
                        on ? "bg-brand-tint ring-brand" : "bg-surface ring-stroke hover:bg-subtle"
                      }`}
                    >
                      <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 transition ${
                        on ? "border-brand" : "border-ink-3/40"
                      }`}>
                        {on && <span className="h-2 w-2 rounded-full bg-brand" />}
                      </span>
                      <span className="min-w-0">
                        <span className="block text-sm font-medium text-ink">{label}</span>
                        <span className="block text-xs leading-snug text-ink-3">{blurb}</span>
                      </span>
                    </button>
                  );
                })}
              </div>

              <p className={`mt-4 flex items-start gap-2 rounded-lg px-3 py-2 text-xs ${
                allocating.user.email ? "bg-infox-bg text-infox" : "bg-warnx-bg text-warnx"
              }`}>
                <Icon name={allocating.user.email ? "mail" : "alert"}
                      className="mt-px h-3.5 w-3.5 shrink-0" />
                <span>
                  {allocating.user.email
                    ? `They will be emailed at ${allocating.user.email} with what they can now reach.`
                    : `${allocating.user.username} has no email address, so no notification can be sent. Add one first if they should be told.`}
                </span>
              </p>
            </>
          )}
        </Modal>
      )}

      {/* ── Create / edit user ── */}
      {editing && (
        <Modal
          title={editing === "new" ? "New user" : `Edit ${(editing as UserRow).username}`}
          wide
          onClose={() => setEditing(null)}
          footer={
            <>
              {error && <span className="mr-auto text-sm text-bad">{error}</span>}
              <Button onClick={() => setEditing(null)}>Cancel</Button>
              <Button variant="primary" spinning={saving} onClick={save} disabled={saving}>
                {editing === "new" ? "Create user" : "Save"}
              </Button>
            </>
          }
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <TextInput label="Username" value={form.username}
                       onChange={(v) => setForm({ ...form, username: v })} />
            <TextInput label="Full name" value={form.full_name} placeholder="Optional"
                       onChange={(v) => setForm({ ...form, full_name: v })} />
            <TextInput label="Email" type="email" value={form.email}
                       hint="Needed for workspace notifications."
                       onChange={(v) => setForm({ ...form, email: v })} />
            <TextInput label="Password" type="password" value={form.password}
                       placeholder={editing === "new" ? "" : "Leave blank to keep the current one"}
                       onChange={(v) => setForm({ ...form, password: v })} />
            <CheckboxInput label="Administrator" checked={form.is_admin}
                           hint="Bypasses module and workspace restrictions."
                           onChange={(v) => setForm({ ...form, is_admin: v })} />
            <CheckboxInput label="Active" checked={form.is_active}
                           hint="Inactive accounts cannot sign in."
                           onChange={(v) => setForm({ ...form, is_active: v })} />
          </div>

          <div className="mt-5">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-ink">Pages they can open</p>
              <div className="flex gap-1.5">
                <button onClick={() => setForm({ ...form, modules: modules.map((m) => m.key) })}
                        className="rounded px-1.5 py-0.5 text-[11px] font-medium text-brand transition hover:bg-brand-tint focus-ring">
                  All
                </button>
                <button onClick={() => setForm({ ...form, modules: [] })}
                        className="rounded px-1.5 py-0.5 text-[11px] font-medium text-ink-3 transition hover:bg-subtle focus-ring">
                  None
                </button>
              </div>
            </div>
            {form.is_admin ? (
              <p className="rounded-lg bg-subtle/60 px-3 py-2 text-xs text-ink-2">
                Administrators can open everything, so these have no effect.
              </p>
            ) : (
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {modules.map((m) => {
                  const on = form.modules.includes(m.key);
                  return (
                    <button key={m.key} onClick={() => toggleModule(m.key)}
                            className={`flex items-start gap-2 rounded-lg px-2.5 py-2 text-left ring-1 ring-inset transition ${
                              on ? "bg-brand-tint ring-brand/40" : "bg-surface ring-stroke hover:bg-subtle"
                            }`}>
                      <span className={`mt-px flex h-4 w-4 shrink-0 items-center justify-center rounded border transition ${
                        on ? "border-brand bg-brand text-white" : "border-ink-3/50 text-transparent"
                      }`}>
                        <Icon name="tasks" className="h-2.5 w-2.5" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-xs font-medium text-ink">{m.label}</span>
                        <span className="block text-[11px] leading-snug text-ink-3">{m.desc}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </Modal>
      )}
    </AppShell>
  );
}
