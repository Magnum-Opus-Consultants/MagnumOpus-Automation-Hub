"use client";

/**
 * The handbook: written rules and how-tos, plus how to reach the servers.
 *
 * Access details sit behind an explicit reveal, one server at a time, because
 * a page that renders every password at once is one screen-share away from an
 * incident.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, StatTile, Badge, Button, EmptyState, Modal,
  TextInput, AreaInput, SelectInput, CheckboxInput, Pill,
} from "@/components/ui";

type Article = {
  id: number; title: string; category: string; category_display: string;
  summary: string; body: string; is_pinned: boolean; for_new_starters: boolean;
  order: number; updated_at: string | null; updated_by: string; length: number;
};
type Payload = {
  articles: Article[]; total: number;
  categories: [string, string][]; new_starter_count: number;
};
type ServerRow = {
  id: number; name: string; company: string; group: string; ip: string;
  hostname: string; os: string; provider: string;
  ssh_user: string; ssh_ip: string; ssh_key: string;
  netbird_ip: string; lan_ip: string; access: string; notes: string;
  has_password: boolean;
};

const TABS = ["Handbook", "New starters", "Server access"] as const;
type Tab = (typeof TABS)[number];

type Form = {
  title: string; category: string; summary: string; body: string;
  is_pinned: boolean; for_new_starters: boolean;
};
const BLANK: Form = {
  title: "", category: "getting_started", summary: "", body: "",
  is_pinned: false, for_new_starters: false,
};

/** Render the plain-text body: blank lines split paragraphs, "- " makes bullets. */
function Body({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/).filter((b) => b.trim());
  if (blocks.length === 0) {
    return <p className="text-sm italic text-ink-3">Nothing written yet.</p>;
  }
  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        const bullets = lines.filter((l) => l.trim().startsWith("- "));
        if (bullets.length === lines.length) {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {lines.map((l, j) => (
                <li key={j} className="text-sm leading-relaxed text-ink-2">
                  {l.trim().slice(2)}
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i} className="whitespace-pre-wrap text-sm leading-relaxed text-ink-2">
            {block}
          </p>
        );
      })}
    </div>
  );
}

export default function HandbookPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<Payload | null>(null);
  const [servers, setServers] = useState<ServerRow[] | null>(null);
  const [serverError, setServerError] = useState("");
  // Starts true so the first paint shows the loading state without the mount
  // effect having to set it synchronously.
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("Handbook");
  const [category, setCategory] = useState("All");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [editing, setEditing] = useState<Article | "new" | null>(null);
  const [form, setForm] = useState<Form>(BLANK);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // Revealed passwords, keyed by server id. Never held for the whole list.
  const [secrets, setSecrets] = useState<Record<number, string>>({});

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/handbook");
      if (!r.ok) throw new Error(String(r.status));
      setData(await r.json());
    } catch {
      setData({ articles: [], total: 0, categories: [], new_starter_count: 0 });
    } finally {
      setLoading(false);
    }
  }, []);

  const loadServers = useCallback(async () => {
    try {
      const r = await fetch("/api/handbook/server-access");
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setServerError(d.detail || "Could not load server access.");
        setServers([]);
        return;
      }
      setServers(d.servers ?? []);
      setServerError("");
    } catch {
      setServers([]);
      setServerError("Could not load server access.");
    }
  }, []);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "handbook")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // load() only updates state after awaiting the fetch, so nothing re-renders
    // synchronously here; the rule cannot see through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const articles = useMemo(() => data?.articles ?? [], [data]);
  const categories = useMemo(() => data?.categories ?? [], [data]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return articles.filter((a) => {
      if (tab === "New starters" && !a.for_new_starters) return false;
      if (tab === "Handbook" && category !== "All" && a.category !== category) return false;
      if (needle && !`${a.title} ${a.summary} ${a.body}`.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [articles, tab, category, q]);

  // Grouped by category so the list reads as a table of contents.
  const grouped = useMemo(() => {
    const m = new Map<string, Article[]>();
    for (const a of shown) {
      const list = m.get(a.category) ?? [];
      list.push(a);
      m.set(a.category, list);
    }
    return [...m.entries()].sort((a, b) => {
      const order = categories.map(([k]) => k);
      return order.indexOf(a[0]) - order.indexOf(b[0]);
    });
  }, [shown, categories]);

  function startNew() {
    setForm({ ...BLANK, category: category === "All" ? "getting_started" : category });
    setError("");
    setEditing("new");
  }

  function startEdit(a: Article) {
    setForm({
      title: a.title, category: a.category, summary: a.summary, body: a.body,
      is_pinned: a.is_pinned, for_new_starters: a.for_new_starters,
    });
    setError("");
    setEditing(a);
  }

  async function save() {
    if (!form.title.trim()) {
      setError("Give the page a title.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const url = editing === "new"
        ? "/api/handbook/create"
        : `/api/handbook/${(editing as Article).id}`;
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `Save failed (${r.status})`);
      }
      setEditing(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function remove(a: Article) {
    if (!confirm(`Delete "${a.title}"?`)) return;
    await fetch(`/api/handbook/${a.id}/delete`, { method: "DELETE" });
    if (open === a.id) setOpen(null);
    await load();
  }

  async function reveal(srv: ServerRow) {
    if (secrets[srv.id]) {
      setSecrets((cur) => {
        const next = { ...cur };
        delete next[srv.id];
        return next;
      });
      return;
    }
    const r = await fetch(`/api/handbook/server-access/${srv.id}/reveal`, { method: "POST" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      alert(d.detail || "Could not reveal that password.");
      return;
    }
    setSecrets((cur) => ({ ...cur, [srv.id]: d.password }));
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      prompt("Copy:", text);
    }
  }

  const isAdmin = !!(me?.is_admin || me?.is_superuser);

  return (
    <AppShell active="Handbook" me={me} wide>
      <PageHead
        title="Handbook"
        subtitle="How we work, and how to get access to what we run."
        actions={
          <>
            <Button icon="plus" variant="primary" onClick={startNew}>New page</Button>
            <Button icon="sync" spinning={loading} onClick={() => { setLoading(true); void load(); }}>
              Refresh
            </Button>
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Pages" value={loading ? "—" : data?.total ?? 0} icon="docs" />
        <StatTile label="For new starters" value={loading ? "—" : data?.new_starter_count ?? 0}
                  icon="users" tone="info" />
        <StatTile label="Pinned" value={loading ? "—" : articles.filter((a) => a.is_pinned).length}
                  icon="shield" tone="accent" />
        <StatTile label="Servers documented"
                  value={servers === null ? (isAdmin ? "—" : "n/a") : servers.length}
                  icon="server" tone="neutral" />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg bg-subtle p-0.5">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => {
                setTab(t);
                if (t === "Server access" && servers === null) void loadServers();
              }}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-semibold transition focus-ring ${
                tab === t ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"
              }`}
            >
              <Icon name={t === "Server access" ? "lock" : t === "New starters" ? "users" : "docs"}
                    className="h-4 w-4" />
              {t}
            </button>
          ))}
        </div>

        {tab !== "Server access" && (
          <>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search the handbook…"
              className="h-9 min-w-48 flex-1 rounded-lg bg-surface px-3 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring"
            />
            {tab === "Handbook" && (
              <>
                <Pill active={category === "All"} onClick={() => setCategory("All")}>All</Pill>
                {categories.map(([k, label]) => (
                  <Pill key={k} active={category === k} onClick={() => setCategory(k)}>
                    {label}
                  </Pill>
                ))}
              </>
            )}
          </>
        )}
      </div>

      {tab === "Server access" ? (
        /* ─────────── Server access ─────────── */
        !isAdmin ? (
          <Section>
            <EmptyState icon="lock" title="Administrators only"
                        hint="Server access details and passwords are restricted." />
          </Section>
        ) : serverError ? (
          <Section><div className="p-6 text-sm text-bad">{serverError}</div></Section>
        ) : servers === null ? (
          <Section><div className="p-6 text-sm text-ink-2">Loading server access…</div></Section>
        ) : servers.length === 0 ? (
          <Section>
            <EmptyState icon="server" title="No servers recorded"
                        hint="Add servers on the Servers page and their access details appear here." />
          </Section>
        ) : (
          <>
            <p className="mb-3 flex items-start gap-2 rounded-lg bg-warnx-bg px-3 py-2 text-xs text-warnx">
              <Icon name="alert" className="mt-px h-4 w-4 shrink-0" />
              <span>
                Passwords are fetched one at a time and every reveal is logged. Don&apos;t leave
                one on screen while sharing.
              </span>
            </p>
            <div className="space-y-3">
              {servers.map((srv) => (
                <Section key={srv.id} title={srv.name}
                         right={<span className="text-xs text-ink-3">
                           {[srv.company, srv.group].filter(Boolean).join(" · ")}
                         </span>}>
                  <div className="grid grid-cols-1 gap-x-6 gap-y-2 p-4 sm:grid-cols-2">
                    {[
                      ["IP", srv.ip],
                      ["Hostname", srv.hostname],
                      ["OS", srv.os],
                      ["Provider", srv.provider],
                      ["SSH user", srv.ssh_user],
                      ["SSH host", srv.ssh_ip],
                      ["SSH key", srv.ssh_key],
                      ["NetBird IP", srv.netbird_ip],
                      ["LAN IP", srv.lan_ip],
                    ].filter(([, v]) => v).map(([label, value]) => (
                      <div key={label} className="flex items-baseline gap-2">
                        <span className="w-24 shrink-0 text-[11px] uppercase tracking-wide text-ink-3">
                          {label}
                        </span>
                        <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink">
                          {value}
                        </span>
                        <button onClick={() => copy(String(value))}
                                title={`Copy ${label}`}
                                className="shrink-0 text-ink-3 transition hover:text-brand focus-ring">
                          <Icon name="link" className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}

                    <div className="flex items-baseline gap-2 sm:col-span-2">
                      <span className="w-24 shrink-0 text-[11px] uppercase tracking-wide text-ink-3">
                        Password
                      </span>
                      {srv.has_password ? (
                        <>
                          <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink">
                            {secrets[srv.id] ?? "••••••••••••"}
                          </span>
                          {secrets[srv.id] && (
                            <button onClick={() => copy(secrets[srv.id])}
                                    className="shrink-0 text-ink-3 transition hover:text-brand focus-ring">
                              <Icon name="link" className="h-3.5 w-3.5" />
                            </button>
                          )}
                          <Button onClick={() => void reveal(srv)}>
                            {secrets[srv.id] ? "Hide" : "Reveal"}
                          </Button>
                        </>
                      ) : (
                        <span className="text-xs italic text-ink-3">none stored</span>
                      )}
                    </div>
                  </div>

                  {(srv.access || srv.notes) && (
                    <div className="border-t border-stroke px-4 py-3">
                      {srv.access && (
                        <p className="text-xs text-ink-2"><strong>Access:</strong> {srv.access}</p>
                      )}
                      {srv.notes && (
                        <p className="mt-1 whitespace-pre-wrap text-xs text-ink-3">{srv.notes}</p>
                      )}
                    </div>
                  )}
                </Section>
              ))}
            </div>
          </>
        )
      ) : loading ? (
        <Section><div className="p-6 text-sm text-ink-2">Loading the handbook…</div></Section>
      ) : shown.length === 0 ? (
        <Section>
          <EmptyState
            icon="docs"
            title={articles.length
              ? "Nothing matches"
              : tab === "New starters" ? "No new-starter pages yet" : "The handbook is empty"}
            hint={articles.length
              ? "Try a different category or search."
              : "Write the first page — the rules a new joiner needs on day one."}
            action={<Button icon="plus" variant="primary" onClick={startNew}>New page</Button>}
          />
        </Section>
      ) : (
        <div className="space-y-4">
          {tab === "New starters" && (
            <p className="rounded-lg bg-infox-bg px-3 py-2 text-xs text-infox">
              This is the reading list a new joiner is handed. Tick a page as
              &ldquo;for new starters&rdquo; to include it.
            </p>
          )}
          {grouped.map(([cat, list]) => (
            <Section key={cat}
                     title={categories.find(([k]) => k === cat)?.[1] ?? cat}
                     right={<span className="text-xs text-ink-3">{list.length}</span>}>
              <ul className="divide-y divide-stroke">
                {list.map((a) => (
                  <li key={a.id}>
                    <div className="flex items-center gap-3 px-4 py-2.5">
                      <button onClick={() => setOpen(open === a.id ? null : a.id)}
                              aria-label={open === a.id ? "Collapse" : "Expand"}
                              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-2 transition hover:bg-subtle hover:text-ink focus-ring">
                        <Icon name="chevron"
                              className={`h-4 w-4 transition-transform ${open === a.id ? "" : "rotate-180"}`} />
                      </button>
                      <button onClick={() => setOpen(open === a.id ? null : a.id)}
                              className="min-w-0 flex-1 text-left focus-ring">
                        <span className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-ink">{a.title}</span>
                          {a.is_pinned && <Badge tone="accent">Pinned</Badge>}
                          {a.for_new_starters && <Badge tone="info">New starters</Badge>}
                        </span>
                        {a.summary && (
                          <span className="block truncate text-xs text-ink-3">{a.summary}</span>
                        )}
                      </button>
                      <span className="hidden shrink-0 text-[11px] text-ink-3 sm:block">
                        {a.updated_at?.slice(0, 10)}
                        {a.updated_by && ` · ${a.updated_by}`}
                      </span>
                      <button onClick={() => startEdit(a)} aria-label="Edit"
                              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring">
                        <Icon name="edit" className="h-4 w-4" />
                      </button>
                      <button onClick={() => remove(a)} aria-label="Delete"
                              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-bad focus-ring">
                        <Icon name="trash" className="h-4 w-4" />
                      </button>
                    </div>
                    {open === a.id && (
                      <div className="border-t border-stroke bg-subtle/30 px-4 py-4 pl-13">
                        <Body text={a.body} />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </Section>
          ))}
        </div>
      )}

      {editing && (
        <Modal
          title={editing === "new" ? "New handbook page" : "Edit page"}
          wide
          onClose={() => setEditing(null)}
          footer={
            <>
              {error && <span className="mr-auto text-sm text-bad">{error}</span>}
              <Button onClick={() => setEditing(null)}>Cancel</Button>
              <Button variant="primary" spinning={saving} onClick={save} disabled={saving}>
                {editing === "new" ? "Create" : "Save"}
              </Button>
            </>
          }
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <TextInput label="Title" value={form.title}
                         placeholder="e.g. Getting access on your first day"
                         onChange={(v) => setForm({ ...form, title: v })} />
            </div>
            <SelectInput label="Category" value={form.category}
                         onChange={(v) => setForm({ ...form, category: v })}
                         options={categories.map(([value, label]) => ({ value, label }))} />
            <TextInput label="One-line summary" value={form.summary}
                       placeholder="Shown in the list"
                       onChange={(v) => setForm({ ...form, summary: v })} />
            <div className="sm:col-span-2">
              <AreaInput label="Page" rows={12} value={form.body}
                         hint='Blank lines separate paragraphs. Start a line with "- " for a bullet.'
                         onChange={(v) => setForm({ ...form, body: v })} />
            </div>
            <CheckboxInput label="Pin to the top" checked={form.is_pinned}
                           onChange={(v) => setForm({ ...form, is_pinned: v })} />
            <CheckboxInput label="Include in the new-starter reading list"
                           checked={form.for_new_starters}
                           onChange={(v) => setForm({ ...form, for_new_starters: v })} />
          </div>
        </Modal>
      )}
    </AppShell>
  );
}
