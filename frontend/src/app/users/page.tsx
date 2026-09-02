"use client";

import { useEffect, useState } from "react";
import { Sidebar, Icon, type Me } from "@/components/Sidebar";
import { AppShell } from "@/components/ui";

type Module = { key: string; label: string; desc?: string };
type User = {
  id: number;
  username: string;
  full_name: string;
  email: string;
  is_admin: boolean;
  is_active: boolean;
  modules: string[];
  last_login: string | null;
  date_joined: string | null;
};

type Form = {
  id?: number;
  full_name: string;
  username: string;
  email: string;
  password: string;
  is_admin: boolean;
  is_active: boolean;
  modules: string[];
};

const EMPTY: Form = { full_name: "", username: "", email: "", password: "", is_admin: false, is_active: true, modules: [] };

function initialsOf(s: string) {
  const parts = s.trim().split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return s.slice(0, 2).toUpperCase();
}

function fmtDate(iso: string | null) {
  if (!iso) return "Never";
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return "—";
  }
}

export default function UsersPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [modules, setModules] = useState<Module[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Form | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<User | null>(null);

  async function load() {
    const r = await fetch("/api/users");
    if (r.status === 401) { window.location.href = "/login"; return; }
    if (r.status === 403) { window.location.href = "/data-analysis"; return; }
    const d = await r.json();
    setUsers(d.users ?? []);
    setModules(d.modules ?? []);
    setLoading(false);
  }

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!(m.is_admin || m.is_superuser)) { window.location.href = "/data-analysis"; return; }
        load();
      })
      .catch(() => (window.location.href = "/login"));
  }, []);

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  }

  function openNew() {
    setError("");
    setIsNew(true);
    setEditing({ ...EMPTY, modules: [] });
  }

  function openEdit(u: User) {
    setError("");
    setIsNew(false);
    setEditing({
      id: u.id,
      full_name: u.full_name === u.username ? "" : u.full_name,
      username: u.username,
      email: u.email,
      password: "",
      is_admin: u.is_admin,
      is_active: u.is_active,
      modules: [...u.modules],
    });
  }

  function toggleModule(key: string) {
    setEditing((f) => (f ? { ...f, modules: f.modules.includes(key) ? f.modules.filter((k) => k !== key) : [...f.modules, key] } : f));
  }

  async function save() {
    if (!editing) return;
    setSaving(true);
    setError("");
    const body: Record<string, unknown> = {
      full_name: editing.full_name,
      email: editing.email,
      is_admin: editing.is_admin,
      is_active: editing.is_active,
      modules: editing.modules,
    };
    body.username = editing.username;
    if (isNew || editing.password) {
      body.password = editing.password;
    }
    const url = isNew ? "/api/users/create" : `/api/users/${editing.id}`;
    const r = await fetch(url, {
      method: isNew ? "POST" : "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json().catch(() => ({}));
    setSaving(false);
    if (!r.ok) { setError(d.detail || "Something went wrong."); return; }
    setEditing(null);
    load();
  }

  async function remove(u: User) {
    const r = await fetch(`/api/users/${u.id}/delete`, { method: "DELETE" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { setError(d.detail || "Could not delete user."); setConfirmDelete(null); return; }
    setConfirmDelete(null);
    load();
  }

  const initials = me?.username?.slice(0, 2).toUpperCase() ?? "··";
  const adminCount = users.filter((u) => u.is_admin && u.is_active).length;

  return (
    <AppShell active="Users" me={me}>
          <div className="flex items-end justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">Users &amp; Access</h1>
              <p className="mt-1 text-sm text-ink-2">Create users and allocate the modules they can access.</p>
            </div>
            <button
              onClick={openNew}
              className="inline-flex items-center gap-2 rounded-lg bg-brand px-3.5 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-brand-hover"
            >
              <Icon name="plus" className="h-4 w-4" /> New user
            </button>
          </div>

          {/* stat strip */}
          <div className="mt-8 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-stroke bg-stroke sm:grid-cols-4">
            {[
              { label: "Total users", value: users.length },
              { label: "Administrators", value: adminCount },
              { label: "Active", value: users.filter((u) => u.is_active).length },
              { label: "Modules", value: modules.length },
            ].map((s) => (
              <div key={s.label} className="bg-surface p-5">
                <div className="text-xs font-medium uppercase tracking-wide text-ink-3">{s.label}</div>
                <div className="mt-2 text-2xl font-semibold tabular-nums">{s.value}</div>
              </div>
            ))}
          </div>

          {/* user list */}
          <div className="mt-8 overflow-hidden rounded-lg border border-stroke">
            <div className="hidden grid-cols-[1.6fr_1.4fr_auto] items-center gap-4 border-b border-stroke bg-subtle px-5 py-3 text-xs font-semibold uppercase tracking-wide text-ink-3 sm:grid">
              <span>User</span>
              <span>Module access</span>
              <span className="text-right">Actions</span>
            </div>
            {loading && <p className="px-5 py-10 text-center text-sm text-ink-3">Loading…</p>}
            {!loading && users.length === 0 && <p className="px-5 py-10 text-center text-sm text-ink-3">No users yet.</p>}
            {users.map((u) => (
              <div key={u.id} className="grid grid-cols-1 items-center gap-4 border-b border-stroke-soft px-5 py-4 last:border-0 sm:grid-cols-[1.6fr_1.4fr_auto]">
                {/* identity */}
                <div className="flex items-center gap-3">
                  <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white ${u.is_admin ? "bg-gradient-to-br from-blue-500 to-blue-600" : "bg-brand"}`}>
                    {initialsOf(u.full_name || u.username)}
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-semibold">{u.full_name || u.username}</p>
                      {u.is_admin && <span className="inline-flex items-center gap-1 rounded-full bg-brand-tint px-1.5 py-0.5 text-xs font-semibold text-brand"><Icon name="shield" className="h-3 w-3" />Admin</span>}
                      {!u.is_active && <span className="rounded-full bg-subtle px-1.5 py-0.5 text-xs font-semibold text-ink-2">Disabled</span>}
                    </div>
                    <p className="truncate text-xs text-ink-3">@{u.username}{u.email ? ` · ${u.email}` : ""}</p>
                  </div>
                </div>
                {/* modules */}
                <div className="flex flex-wrap gap-1.5">
                  {u.is_admin ? (
                    <span className="rounded-lg bg-brand-tint px-2 py-1 text-xs font-medium text-brand">All modules</span>
                  ) : u.modules.length === 0 ? (
                    <span className="text-xs text-ink-3">No modules assigned</span>
                  ) : (
                    modules.filter((m) => u.modules.includes(m.key)).map((m) => (
                      <span key={m.key} className="rounded-lg bg-subtle px-2 py-1 text-xs font-medium text-ink-2">{m.label}</span>
                    ))
                  )}
                </div>
                {/* actions */}
                <div className="flex items-center gap-2 sm:justify-end">
                  <button onClick={() => openEdit(u)} className="rounded-lg border border-stroke px-3 py-1.5 text-xs font-medium text-ink-2 transition hover:border-brand hover:text-ink">Edit</button>
                  <button
                    onClick={() => setConfirmDelete(u)}
                    disabled={u.id === me?.id}
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-stroke text-ink-3 transition hover:border-bad hover:text-bad disabled:cursor-not-allowed disabled:opacity-30"
                    title={u.id === me?.id ? "You cannot delete your own account" : "Delete user"}
                  >
                    <Icon name="trash" className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>

      {/* create / edit modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand/40 p-4" onClick={() => !saving && setEditing(null)}>
          <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-surface p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{isNew ? "New user" : `Edit ${editing.username}`}</h2>
              <button onClick={() => setEditing(null)} className="text-ink-3 transition hover:text-ink">✕</button>
            </div>

            {error && <p className="mt-4 rounded-lg bg-bad-bg px-3 py-2 text-sm text-red-600">{error}</p>}

            <div className="mt-5 space-y-5">
              {/* identity */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <label className="text-xs font-medium text-ink-2">Full name</label>
                  <input
                    value={editing.full_name}
                    onChange={(e) => setEditing({ ...editing, full_name: e.target.value })}
                    placeholder="Jane Doe"
                    className="mt-1 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-ink-2">Username</label>
                  <input
                    value={editing.username}
                    onChange={(e) => setEditing({ ...editing, username: e.target.value })}
                    placeholder="jdoe"
                    className="mt-1 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand"
                  />
                  {!isNew && <p className="mt-1 text-xs text-ink-3">This is the name they sign in with.</p>}
                </div>
                <div>
                  <label className="text-xs font-medium text-ink-2">Email <span className="text-ink-3">(optional)</span></label>
                  <input
                    value={editing.email}
                    onChange={(e) => setEditing({ ...editing, email: e.target.value })}
                    placeholder="jane@company.com"
                    className="mt-1 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand"
                  />
                </div>
              </div>

              {/* two columns: security | role & access */}
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {/* security column */}
                <div className="space-y-4">
                  <div className="rounded-lg border border-stroke p-4">
                    <p className="text-sm font-medium">{isNew ? "Set password" : "Reset password"}</p>
                    <p className="mt-0.5 text-xs text-ink-3">{isNew ? "The user signs in with this password." : "Type a new password to reset it. Leave blank to keep the current one."}</p>
                    <input
                      type="text"
                      value={editing.password}
                      onChange={(e) => setEditing({ ...editing, password: e.target.value })}
                      placeholder={isNew ? "Set a password" : "New password"}
                      className="mt-2 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand"
                    />
                  </div>

                  {!isNew && (
                    <div className={`rounded-lg border p-4 ${editing.is_active ? "border-stroke" : "border-red-200 bg-bad-bg/40"}`}>
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium">Account status</p>
                          <p className="mt-0.5 text-xs text-ink-3">{editing.is_active ? "Active — the user can sign in." : "Deactivated — sign-in is blocked."}</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setEditing({ ...editing, is_active: !editing.is_active })}
                          className={`relative h-6 w-11 shrink-0 rounded-full transition ${editing.is_active ? "bg-brand-tint0" : "bg-ink-3"}`}
                          aria-label="Toggle account active"
                        >
                          <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-surface shadow transition-all ${editing.is_active ? "left-[22px]" : "left-0.5"}`} />
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* role & access column */}
                <div className="space-y-4">
                  <div className="rounded-lg border border-stroke p-4">
                    <label className="flex cursor-pointer items-start gap-3">
                      <input type="checkbox" checked={editing.is_admin} onChange={(e) => setEditing({ ...editing, is_admin: e.target.checked })} className="mt-0.5 h-4 w-4 accent-blue-500" />
                      <span>
                        <span className="block text-sm font-medium">Administrator</span>
                        <span className="block text-xs text-ink-3">Full access to every module plus user management.</span>
                      </span>
                    </label>
                  </div>

                  <div className={editing.is_admin ? "pointer-events-none opacity-40" : ""}>
                    <p className="mb-2 text-xs font-medium text-ink-2">Module access</p>
                    <div className="space-y-2">
                      {modules.map((m) => {
                        const on = editing.is_admin || editing.modules.includes(m.key);
                        return (
                          <label key={m.key} className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition ${on ? "border-blue-300 bg-brand-tint/50" : "border-stroke hover:border-stroke"}`}>
                            <input type="checkbox" checked={on} onChange={() => toggleModule(m.key)} className="mt-0.5 h-4 w-4 accent-blue-500" />
                            <span>
                              <span className="block text-sm font-medium">{m.label}</span>
                              {m.desc && <span className="block text-xs text-ink-3">{m.desc}</span>}
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-2">
              <button onClick={() => setEditing(null)} disabled={saving} className="rounded-lg border border-stroke px-4 py-2 text-sm font-medium text-ink-2 transition hover:border-brand hover:text-ink">Cancel</button>
              <button onClick={save} disabled={saving || (isNew && (!editing.username || !editing.password))} className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-hover disabled:opacity-40">
                {saving ? "Saving…" : isNew ? "Create user" : "Save changes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* delete confirm */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand/40 p-4" onClick={() => setConfirmDelete(null)}>
          <div className="w-full max-w-sm rounded-2xl bg-surface p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold">Delete user?</h2>
            <p className="mt-2 text-sm text-ink-2">
              This permanently removes <span className="font-medium text-ink">{confirmDelete.full_name || confirmDelete.username}</span> and their access. This cannot be undone.
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button onClick={() => setConfirmDelete(null)} className="rounded-lg border border-stroke px-4 py-2 text-sm font-medium text-ink-2 transition hover:border-brand hover:text-ink">Cancel</button>
              <button onClick={() => remove(confirmDelete)} className="rounded-lg bg-bad px-4 py-2 text-sm font-medium text-white transition hover:bg-bad">Delete</button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
