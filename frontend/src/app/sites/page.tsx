"use client";

/**
 * Client Sites: turn an answered brief into a website, edit its blocks, publish.
 *
 * The editor renders itself from the block library the API sends, so adding a
 * new block type on the server needs no change here.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, StatTile, Badge, Button, EmptyState, Modal,
  TextInput, AreaInput, SelectInput, Pill,
} from "@/components/ui";

type FieldDef = { name: string; type: "text" | "textarea" | "url" | "list" | "items"; label: string };
type BlockDef = { kind: string; label: string; blurb: string; fields: FieldDef[] };
type Item = { title?: string; body?: string };
type BlockContent = Record<string, string | string[] | Item[] | undefined>;
type Block = {
  id: number; kind: string; label: string; order: number;
  is_visible: boolean; content: BlockContent;
};
type TemplateDef = { value: string; label: string; blurb: string };
type Site = {
  id: number; request: number | null;
  client_name: string; site_name: string; slug: string;
  tagline: string; logo_url: string;
  palette: string; font: string;
  template: string; template_label: string; industry: string;
  status: string; status_display: string;
  published_url: string; published_ip: string; published_at: string | null;
  preview_url: string; notes: string;
  block_count: number; blocks: Block[]; updated_at: string | null;
};
type Seedable = {
  id: number; title: string; client_name: string; kind: string; answered_count: number;
};
type Payload = {
  sites: Site[]; total: number; published: number;
  palettes: [string, string][]; fonts: [string, string][];
  templates: TemplateDef[]; stock_categories: string[];
  library: BlockDef[]; seedable: Seedable[];
};

const FILTERS = ["All", "Draft", "Published"] as const;
type Filter = (typeof FILTERS)[number];

// Swatches so a palette can be judged without opening a preview.
const SWATCH: Record<string, string> = {
  slate: "#334155", ocean: "#2563eb", forest: "#15803d",
  sunset: "#ea580c", plum: "#7c3aed", mono: "#111111",
};

export default function SitesPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<Payload | null>(null);
  // Starts true so the first paint shows the loading state without the mount
  // effect having to set it synchronously.
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("All");
  const [q, setQ] = useState("");
  const [openSite, setOpenSite] = useState<number | null>(null);
  const [editingBlock, setEditingBlock] = useState<{ site: Site; block: Block } | null>(null);
  const [draft, setDraft] = useState<BlockContent>({});
  // Empty palette/font/template mean "as the answers suggest" - the server
  // decides. They are only sent when someone has actually overridden them.
  const [creating, setCreating] = useState<
    { request: number | null; site_name: string; client_name: string;
      palette: string; font: string; template: string; error: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/sites");
      if (!r.ok) throw new Error(String(r.status));
      setData(await r.json());
    } catch {
      setData({ sites: [], total: 0, published: 0, palettes: [], fonts: [],
                templates: [], stock_categories: [], library: [], seedable: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "sites")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // load() only updates state after awaiting the fetch, so nothing re-renders
    // synchronously here; the rule cannot see through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const sites = useMemo(() => data?.sites ?? [], [data]);
  const library = useMemo(() => data?.library ?? [], [data]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return sites.filter((s) => {
      if (filter !== "All" && s.status !== filter.toLowerCase()) return false;
      if (needle && !`${s.site_name} ${s.client_name} ${s.slug}`.toLowerCase().includes(needle)) {
        return false;
      }
      return true;
    });
  }, [sites, filter, q]);

  async function post(url: string, body?: unknown) {
    setBusy(true);
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        alert(d.detail || "That did not work.");
        return null;
      }
      await load();
      return d;
    } finally {
      setBusy(false);
    }
  }

  async function createSite() {
    if (!creating) return;
    if (!creating.request && !creating.site_name.trim()) {
      setCreating({ ...creating, error: "Give the site a name, or pick a brief." });
      return;
    }
    const d = await post("/api/sites/create", {
      request: creating.request,
      site_name: creating.site_name.trim(),
      client_name: creating.client_name.trim(),
      // Omitted rather than defaulted: an empty value here would be rejected,
      // and a default would override what the answers imply.
      ...(creating.palette ? { palette: creating.palette } : {}),
      ...(creating.font ? { font: creating.font } : {}),
      ...(creating.template ? { template: creating.template } : {}),
    });
    if (d) {
      setCreating(null);
      setOpenSite(d.id);
      setNote(creating.request
        ? `${d.site_name}: ${d.block_count} sections built from their answers, `
          + `read as ${d.industry || "general business"} on the `
          + `${d.template_label || d.template} layout.`
        : `${d.site_name} created.`);
    }
  }

  async function publish(s: Site) {
    const d = await post(`/api/sites/${s.id}/publish`);
    if (d) setNote(`${s.site_name} is live at ${d.published_url}`);
  }

  async function removeSite(s: Site) {
    if (!confirm(`Delete "${s.site_name}"? The published page comes down too.`)) return;
    setBusy(true);
    try {
      await fetch(`/api/sites/${s.id}/delete`, { method: "DELETE" });
      if (openSite === s.id) setOpenSite(null);
      setNote(`${s.site_name} was deleted.`);
      await load();
    } finally {
      setBusy(false);
    }
  }

  function startEditBlock(site: Site, block: Block) {
    setDraft({ ...block.content });
    setEditingBlock({ site, block });
  }

  async function saveBlock() {
    if (!editingBlock) return;
    const d = await post(`/api/sites/${editingBlock.site.id}/blocks`, {
      block: editingBlock.block.id, content: draft,
    });
    if (d) setEditingBlock(null);
  }

  function defFor(kind: string) {
    return library.find((l) => l.kind === kind);
  }

  /** One field of a block, driven by the library's declared type. */
  function renderField(f: FieldDef) {
    const val = draft[f.name];
    if (f.type === "textarea") {
      return (
        <AreaInput key={f.name} label={f.label} rows={4}
                   value={typeof val === "string" ? val : ""}
                   onChange={(v) => setDraft({ ...draft, [f.name]: v })} />
      );
    }
    if (f.type === "list") {
      const list = Array.isArray(val) ? (val as string[]) : [];
      return (
        <div key={f.name} className="sm:col-span-2">
          <p className="mb-1 text-sm font-medium text-ink">{f.label}</p>
          {list.map((v, i) => (
            <div key={i} className="mb-1.5 flex gap-1.5">
              <input value={v}
                     onChange={(e) => {
                       const next = [...list];
                       next[i] = e.target.value;
                       setDraft({ ...draft, [f.name]: next });
                     }}
                     placeholder="https://…"
                     className="h-9 flex-1 rounded-lg bg-canvas px-2.5 text-sm text-ink ring-control focus-ring" />
              <button onClick={() => setDraft({ ...draft, [f.name]: list.filter((_, j) => j !== i) })}
                      aria-label="Remove"
                      className="h-9 w-9 shrink-0 rounded-lg text-ink-3 transition hover:bg-subtle hover:text-bad focus-ring">
                ✕
              </button>
            </div>
          ))}
          <Button icon="plus" onClick={() => setDraft({ ...draft, [f.name]: [...list, ""] })}>
            Add
          </Button>
        </div>
      );
    }
    if (f.type === "items") {
      const items = Array.isArray(val) ? (val as Item[]) : [];
      return (
        <div key={f.name} className="sm:col-span-2">
          <p className="mb-1.5 text-sm font-medium text-ink">{f.label}</p>
          <div className="space-y-2">
            {items.map((it, i) => (
              <div key={i} className="rounded-lg bg-canvas p-2.5 ring-1 ring-inset ring-stroke">
                <div className="flex gap-1.5">
                  <input value={it.title ?? ""}
                         onChange={(e) => {
                           const next = [...items];
                           next[i] = { ...next[i], title: e.target.value };
                           setDraft({ ...draft, [f.name]: next });
                         }}
                         placeholder="Title"
                         className="h-9 flex-1 rounded-lg bg-surface px-2.5 text-sm font-medium text-ink ring-control focus-ring" />
                  <button onClick={() => setDraft({ ...draft, [f.name]: items.filter((_, j) => j !== i) })}
                          aria-label="Remove"
                          className="h-9 w-9 shrink-0 rounded-lg text-ink-3 transition hover:bg-subtle hover:text-bad focus-ring">
                    ✕
                  </button>
                </div>
                <textarea value={it.body ?? ""} rows={2}
                          onChange={(e) => {
                            const next = [...items];
                            next[i] = { ...next[i], body: e.target.value };
                            setDraft({ ...draft, [f.name]: next });
                          }}
                          placeholder="Description"
                          className="mt-1.5 w-full resize-y rounded-lg bg-surface px-2.5 py-1.5 text-sm text-ink ring-control focus-ring" />
              </div>
            ))}
          </div>
          <div className="mt-2">
            <Button icon="plus"
                    onClick={() => setDraft({ ...draft, [f.name]: [...items, { title: "", body: "" }] })}>
              Add item
            </Button>
          </div>
        </div>
      );
    }
    return (
      <TextInput key={f.name} label={f.label}
                 value={typeof val === "string" ? val : ""}
                 placeholder={f.type === "url" ? "https://…" : undefined}
                 onChange={(v) => setDraft({ ...draft, [f.name]: v })} />
    );
  }

  return (
    <AppShell active="Client Sites" me={me} wide>
      <PageHead
        title="Client Sites"
        subtitle="A client answers their brief and a draft site is built and published here automatically. Review it before you send them the link."
        actions={
          <>
            <Button icon="plus" variant="primary"
                    onClick={() => setCreating({
                      request: data?.seedable?.[0]?.id ?? null,
                      site_name: "", client_name: "",
                      palette: "", font: "", template: "", error: "",
                    })}>
              New site
            </Button>
            <Button icon="sync" spinning={loading}
                    onClick={() => { setLoading(true); void load(); }}>Refresh</Button>
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Sites" value={loading ? "—" : data?.total ?? 0} icon="globe" />
        <StatTile label="Published" value={loading ? "—" : data?.published ?? 0}
                  icon="shield" tone="good" />
        <StatTile label="Drafts"
                  value={loading ? "—" : (data?.total ?? 0) - (data?.published ?? 0)}
                  icon="edit" tone="neutral" />
        <StatTile label="Briefs ready to build"
                  value={loading ? "—" : data?.seedable?.length ?? 0}
                  icon="mail" tone={(data?.seedable?.length ?? 0) ? "info" : "neutral"}
                  hint={(data?.seedable?.length ?? 0) ? "Answered, no site yet" : undefined} />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Search by site, client or slug…"
               className="h-9 min-w-52 flex-1 rounded-lg bg-surface px-3 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring" />
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
        <Section><div className="p-6 text-sm text-ink-2">Loading sites…</div></Section>
      ) : shown.length === 0 ? (
        <Section>
          <EmptyState
            icon="globe"
            title={sites.length ? "Nothing matches" : "No sites yet"}
            hint={sites.length
              ? "Try a different filter."
              : (data?.seedable?.length ?? 0) > 0
                ? "A brief was answered before this was switched on — build its site here."
                : "Send a client a question sheet. When they answer, their site appears here on its own."}
            action={<Button icon="plus" variant="primary"
                            onClick={() => setCreating({
                              request: data?.seedable?.[0]?.id ?? null,
                              site_name: "", client_name: "",
                              palette: "", font: "", template: "", error: "",
                            })}>New site</Button>} />
        </Section>
      ) : (
        <div className="space-y-3">
          {shown.map((s) => {
            const open = openSite === s.id;
            return (
              <Section key={s.id}>
                <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <button onClick={() => setOpenSite(open ? null : s.id)}
                          aria-label={open ? "Collapse" : "Expand"}
                          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-2 transition hover:bg-subtle hover:text-ink focus-ring">
                    <Icon name="chevron" className={`h-4 w-4 transition-transform ${open ? "" : "rotate-180"}`} />
                  </button>

                  <span aria-hidden className="h-8 w-8 shrink-0 rounded-lg"
                        style={{ background: SWATCH[s.palette] ?? "#334155" }} />

                  <button onClick={() => setOpenSite(open ? null : s.id)}
                          className="min-w-0 flex-1 text-left focus-ring">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-ink">{s.site_name}</span>
                      <Badge tone={s.status === "published" ? "good" : "neutral"}>
                        {s.status_display}
                      </Badge>
                    </span>
                    <span className="block truncate text-xs text-ink-3">
                      {s.client_name} · /{s.slug} · {s.block_count} sections
                      {s.template && ` · ${s.template} layout`}
                      {s.industry && ` · read as ${s.industry}`}
                      {s.published_ip && ` · ${s.published_ip}`}
                    </span>
                  </button>

                  {s.status === "published" && s.published_url && (
                    <a href={s.published_url} target="_blank" rel="noreferrer"
                       className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold text-brand ring-control transition hover:bg-brand-tint focus-ring">
                      <Icon name="globe" className="h-3.5 w-3.5" />
                      Live site
                    </a>
                  )}
                  <a href={s.preview_url} target="_blank" rel="noreferrer"
                     className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-ink-2 ring-control transition hover:bg-subtle focus-ring">
                    Preview
                  </a>
                  <Button icon="upload" variant="primary" spinning={busy}
                          onClick={() => void publish(s)}>
                    {s.status === "published" ? "Republish" : "Publish"}
                  </Button>
                  <button onClick={() => void removeSite(s)} aria-label="Delete site"
                          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-3 transition hover:bg-subtle hover:text-bad focus-ring">
                    <Icon name="trash" className="h-4 w-4" />
                  </button>
                </div>

                {open && (
                  <div className="border-t border-stroke">
                    {/* Look and feel */}
                    <div className="grid grid-cols-1 gap-4 border-b border-stroke bg-subtle/30 p-4 sm:grid-cols-3">
                      <SelectInput
                        label="Layout" value={s.template}
                        hint="Changes the shape of the page, not its content."
                        onChange={(v) => void post(`/api/sites/${s.id}`, { template: v })}
                        options={(data?.templates ?? []).map((t) => ({
                          value: t.value, label: t.label }))} />
                      <SelectInput label="Palette" value={s.palette}
                                   onChange={(v) => void post(`/api/sites/${s.id}`, { palette: v })}
                                   options={(data?.palettes ?? []).map(([value, label]) => ({ value, label }))} />
                      <SelectInput label="Font pairing" value={s.font}
                                   onChange={(v) => void post(`/api/sites/${s.id}`, { font: v })}
                                   options={(data?.fonts ?? []).map(([value, label]) => ({ value, label }))} />
                    </div>

                    {s.notes && (
                      <p className="border-b border-stroke bg-warnx-bg px-4 py-2 text-xs text-warnx">
                        <strong>From the brief, not published:</strong> {s.notes}
                      </p>
                    )}

                    {/* Sections */}
                    <ul className="divide-y divide-stroke">
                      {s.blocks.map((b, i) => {
                        const def = defFor(b.kind);
                        const summary = Object.entries(b.content)
                          .filter(([, v]) => typeof v === "string" && v)
                          .map(([, v]) => v as string)[0] ?? "";
                        return (
                          <li key={b.id} className="flex items-center gap-3 px-4 py-2">
                            <span className="w-6 shrink-0 text-right text-[11px] text-ink-3">{i + 1}</span>
                            <button onClick={() => startEditBlock(s, b)}
                                    className="min-w-0 flex-1 text-left focus-ring">
                              <span className="flex items-center gap-2">
                                <span className={`text-sm font-medium ${b.is_visible ? "text-ink" : "text-ink-3 line-through"}`}>
                                  {b.label}
                                </span>
                                {!b.is_visible && <Badge tone="neutral">Hidden</Badge>}
                              </span>
                              <span className="block truncate text-xs text-ink-3">
                                {summary || def?.blurb}
                              </span>
                            </button>

                            <button onClick={() => void post(`/api/sites/${s.id}/blocks`,
                                                             { block: b.id, order: b.order - 15 })}
                                    disabled={i === 0} aria-label="Move up"
                                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-ink disabled:opacity-25 focus-ring">
                              <Icon name="chevron" className="h-3.5 w-3.5" />
                            </button>
                            <button onClick={() => void post(`/api/sites/${s.id}/blocks`,
                                                             { block: b.id, order: b.order + 15 })}
                                    disabled={i === s.blocks.length - 1} aria-label="Move down"
                                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-ink disabled:opacity-25 focus-ring">
                              <Icon name="chevron" className="h-3.5 w-3.5 rotate-180" />
                            </button>
                            <button onClick={() => void post(`/api/sites/${s.id}/blocks`,
                                                             { block: b.id, is_visible: !b.is_visible })}
                                    aria-label={b.is_visible ? "Hide" : "Show"}
                                    title={b.is_visible ? "Hide from the site" : "Show on the site"}
                                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring">
                              <Icon name={b.is_visible ? "shield" : "lock"} className="h-3.5 w-3.5" />
                            </button>
                            <button onClick={() => void fetch(`/api/sites/${s.id}/blocks/${b.id}/delete`,
                                                              { method: "DELETE" }).then(load)}
                                    aria-label="Remove section"
                                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-bad focus-ring">
                              <Icon name="trash" className="h-3.5 w-3.5" />
                            </button>
                          </li>
                        );
                      })}
                    </ul>

                    {/* The block library, as an add row */}
                    <div className="flex flex-wrap items-center gap-1.5 border-t border-stroke p-3">
                      <span className="mr-1 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                        Add a section
                      </span>
                      {library.map((l) => (
                        <button key={l.kind} title={l.blurb}
                                onClick={() => void post(`/api/sites/${s.id}/blocks`, { kind: l.kind })}
                                className="rounded-md bg-subtle px-2 py-1 text-[11px] font-medium text-ink-2 transition hover:bg-brand-tint hover:text-brand-pressed focus-ring">
                          + {l.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </Section>
            );
          })}
        </div>
      )}

      {/* ── New site ── */}
      {creating && (
        <Modal
          title="New client site"
          onClose={() => setCreating(null)}
          footer={
            <>
              {creating.error && <span className="mr-auto text-sm text-bad">{creating.error}</span>}
              <Button onClick={() => setCreating(null)}>Cancel</Button>
              <Button variant="primary" spinning={busy} onClick={createSite} disabled={busy}>
                {creating.request ? "Build from the brief" : "Create blank"}
              </Button>
            </>
          }
        >
          <div className="space-y-4">
            <SelectInput
              label="Build from a client's brief"
              value={creating.request ? String(creating.request) : ""}
              onChange={(v) => setCreating({ ...creating, request: v ? Number(v) : null })}
              hint={creating.request
                ? "Their answers choose the layout, the palette and the copy."
                : "A blank site starts on the layout you pick below."}
              options={[
                { value: "", label: "Start from a blank layout" },
                ...(data?.seedable ?? []).map((x) => ({
                  value: String(x.id),
                  label: `${x.client_name} — ${x.title} (${x.answered_count} answered)`,
                })),
              ]}
            />
            <SelectInput
              label="Layout"
              value={creating.template}
              onChange={(v) => setCreating({ ...creating, template: v })}
              hint={(data?.templates ?? []).find((t) => t.value === creating.template)?.blurb
                    ?? "Chosen from what the client said they do."}
              options={[
                { value: "", label: creating.request
                    ? "Automatic — from their answers" : "Automatic" },
                ...(data?.templates ?? []).map((t) => ({
                  value: t.value, label: t.label })),
              ]}
            />
            {!creating.request && (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <TextInput label="Site name" value={creating.site_name}
                           onChange={(v) => setCreating({ ...creating, site_name: v, error: "" })} />
                <TextInput label="Client" value={creating.client_name}
                           onChange={(v) => setCreating({ ...creating, client_name: v })} />
              </div>
            )}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <p className="mb-1.5 text-sm font-medium text-ink">Palette</p>
                <div className="flex flex-wrap items-center gap-1.5">
                  <button onClick={() => setCreating({ ...creating, palette: "" })}
                          className={`h-8 rounded-lg px-2.5 text-[11px] font-semibold ring-2 transition ${
                            creating.palette === ""
                              ? "bg-brand-tint text-brand-pressed ring-brand"
                              : "bg-subtle text-ink-2 ring-transparent hover:bg-canvas"
                          }`}>
                    Auto
                  </button>
                  {(data?.palettes ?? []).map(([value, label]) => (
                    <button key={value} title={label}
                            onClick={() => setCreating({ ...creating, palette: value })}
                            aria-label={label}
                            className={`h-8 w-8 rounded-lg ring-2 transition ${
                              creating.palette === value ? "ring-ink" : "ring-transparent"
                            }`}
                            style={{ background: SWATCH[value] ?? "#334155" }} />
                  ))}
                </div>
              </div>
              <SelectInput label="Font pairing" value={creating.font}
                           onChange={(v) => setCreating({ ...creating, font: v })}
                           options={[{ value: "", label: "Automatic" },
                                     ...(data?.fonts ?? []).map(([value, label]) => ({ value, label }))]} />
            </div>
          </div>
        </Modal>
      )}

      {/* ── Edit a section ── */}
      {editingBlock && (
        <Modal
          title={`Edit: ${editingBlock.block.label}`}
          wide
          onClose={() => setEditingBlock(null)}
          footer={
            <>
              <span className="mr-auto text-xs text-ink-3">
                {defFor(editingBlock.block.kind)?.blurb}
              </span>
              <Button onClick={() => setEditingBlock(null)}>Cancel</Button>
              <Button variant="primary" spinning={busy} onClick={saveBlock} disabled={busy}>
                Save section
              </Button>
            </>
          }
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {(defFor(editingBlock.block.kind)?.fields ?? []).map(renderField)}
          </div>
        </Modal>
      )}
    </AppShell>
  );
}
