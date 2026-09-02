"use client";

import { useEffect, useRef, useState } from "react";
import { Sidebar, Icon, canAccess, type Me } from "@/components/Sidebar";
import { AppShell } from "@/components/ui";

type Server = {
  id: number; name: string; company?: string; ip: string | null; host?: string; port?: number | null;
  group: string; target: string | null; status: "up" | "down" | "unknown"; latency_ms: number | null;
  hostname?: string; os?: string; provider?: string; cpu?: string; ram?: string; disk?: string;
  runtimes?: string[]; services?: string[]; databases?: string[]; domains?: string[];
  access?: string; netbird_ip?: string | null; lan_ip?: string | null; notes?: string[]; netbird_url?: string | null;
  ssh_user?: string; ssh_ip?: string; ssh_key?: string; ssh_command?: string | null;
  password?: string; scanned_at?: string | null;
};
type Metrics = {
  available: boolean; source?: string; detail?: string;
  cpu_percent?: number | null; cores?: number; load?: number;
  mem_used_mb?: number; mem_total_mb?: number; disk_used_gb?: number; disk_total_gb?: number; uptime?: string | null;
};
type Form = Record<string, string>;

const STATUS: Record<string, { label: string; dot: string; text: string; ring: string }> = {
  up: { label: "Online", dot: "bg-good", text: "text-good", ring: "ring-emerald-600/20 bg-good-bg" },
  down: { label: "Unreachable", dot: "bg-bad", text: "text-bad", ring: "ring-red-600/20 bg-bad-bg" },
  unknown: { label: "Unknown", dot: "bg-ink-3", text: "text-ink-2", ring: "ring-stroke bg-subtle" },
};
const COMPANY: Record<string, string> = {
  "Magnum Opus Consultants": "bg-brand-tint text-brand-hover ring-blue-600/20",
  "Food Safety Agency": "bg-good-bg text-good ring-emerald-600/20",
  "E-Click": "bg-violet-50 text-violet-700 ring-violet-600/20",
  Shared: "bg-subtle text-ink-2 ring-stroke",
};
const DTABS = ["Overview", "Live Monitoring", "Domains", "Access"];

function CompanyBadge({ c }: { c?: string }) {
  if (!c) return null;
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${COMPANY[c] ?? COMPANY.Shared}`}>{c}</span>;
}
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="rounded-lg border border-stroke bg-surface p-5 shadow-sm"><h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-ink-3">{title}</h3>{children}</div>;
}
function Row({ k, v, mono }: { k: string; v?: string | null; mono?: boolean }) {
  if (!v) return null;
  return <div className="flex justify-between gap-4 py-1.5 text-sm"><span className="shrink-0 text-ink-3">{k}</span><span className={`text-right font-medium text-ink ${mono ? "break-all font-mono text-xs" : ""}`}>{v}</span></div>;
}
function Bar({ pct, color = "bg-brand-tint0" }: { pct: number; color?: string }) {
  return <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-subtle"><div className={`h-full rounded-full ${color} transition-all duration-500`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} /></div>;
}
function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return <label className="block"><span className="text-xs font-medium text-ink-2">{label}</span><input value={value} onChange={(e) => onChange(e.target.value)} className="mt-1 w-full rounded-lg border border-stroke px-3 py-1.5 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand" /></label>;
}
function AreaInput({ label, value, onChange, hint }: { label: string; value: string; onChange: (v: string) => void; hint?: string }) {
  return <label className="block"><span className="text-xs font-medium text-ink-2">{label}{hint && <span className="text-ink-3"> · {hint}</span>}</span><textarea value={value} onChange={(e) => onChange(e.target.value)} rows={4} className="mt-1 w-full rounded-lg border border-stroke px-3 py-1.5 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand" /></label>;
}

function formFromServer(s: Server): Form {
  return {
    name: s.name || "", company: s.company || "", group: s.group || "", ip: s.ip || "", host: s.host || "", port: s.port ? String(s.port) : "",
    hostname: s.hostname || "", provider: s.provider || "",
    access: s.access || "", netbird_ip: s.netbird_ip || "", lan_ip: s.lan_ip || "", netbird_url: s.netbird_url || "",
    ssh_user: s.ssh_user || "", ssh_ip: s.ssh_ip || "", ssh_key: s.ssh_key || "", password: s.password || "",
    domains: (s.domains || []).join("\n"), notes: (s.notes || []).join("\n"),
  };
}

export default function ServersPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<{ servers: Server[]; up: number; down: number; total: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [sel, setSel] = useState<Server | null>(null);
  const [dtab, setDtab] = useState("Overview");
  const [group, setGroup] = useState("All");
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [mLoading, setMLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Form>({});
  const [saving, setSaving] = useState(false);
  const [scanning, setScanning] = useState(false);
  const restored = useRef(false);

  function load(selectId?: number, edit = false) {
    setLoading(true);
    return fetch("/api/servers").then((r) => (r.ok ? r.json() : Promise.reject())).then((d) => {
      setData(d);
      if (selectId != null) {
        const found = d.servers.find((s: Server) => s.id === selectId);
        if (found) { setSel(found); if (edit) { setForm(formFromServer(found)); setEditing(true); } }
      } else if (!restored.current) {
        restored.current = true;
        const sp = new URLSearchParams(window.location.search);
        const sId = sp.get("server");
        if (sId) { const f = d.servers.find((s: Server) => String(s.id) === sId); if (f) { setSel(f); setDtab(sp.get("tab") || "Overview"); } }
      } else {
        setSel((cur) => (cur ? d.servers.find((s: Server) => s.id === cur.id) ?? cur : null));
      }
    }).catch(() => setData({ servers: [], up: 0, down: 0, total: 0 })).finally(() => setLoading(false));
  }
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    if (sp.get("group")) setGroup(sp.get("group")!);
    fetch("/api/auth/me").then((r) => (r.ok ? r.json() : Promise.reject())).then((m: Me) => { setMe(m); if (!canAccess(m, "servers")) window.location.href = "/data-analysis"; }).catch(() => (window.location.href = "/login"));
    load();
  }, []);
  useEffect(() => {
    const sp = new URLSearchParams();
    if (sel) { sp.set("server", String(sel.id)); sp.set("tab", dtab); }
    else if (group !== "All") sp.set("group", group);
    const qs = sp.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [sel, dtab, group]);
  useEffect(() => {
    if (!sel || dtab !== "Live Monitoring" || editing) return;
    let alive = true;
    const fetchM = () => { setMLoading(true); fetch(`/api/servers/metrics?id=${sel.id}`).then((r) => r.json()).then((m) => alive && setMetrics(m)).catch(() => alive && setMetrics({ available: false, detail: "Unavailable" })).finally(() => alive && setMLoading(false)); };
    setMetrics(null); fetchM();
    const id = setInterval(fetchM, 3500);
    return () => { alive = false; clearInterval(id); };
  }, [sel, dtab, editing]);

  const initials = me?.username?.slice(0, 2).toUpperCase() ?? "··";
  async function signOut() { await fetch("/api/auth/logout", { method: "POST" }); window.location.href = "/login"; }
  const groups = Array.from(new Set((data?.servers ?? []).map((s) => s.group)));

  function open(s: Server) { setSel(s); setDtab("Overview"); setMetrics(null); setEditing(false); }
  function startEdit() { if (sel) { setForm(formFromServer(sel)); setEditing(true); } }
  async function save() {
    if (!sel) return;
    setSaving(true);
    await fetch(`/api/servers/${sel.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
    setSaving(false); setEditing(false);
    await load(sel.id);
  }
  async function addServer() {
    const res = await fetch("/api/servers/create", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "New Server", group: "DigitalOcean Cloud" }) });
    const d = await res.json();
    await load(d.id, true);
  }
  async function removeServer() {
    if (!sel || !confirm(`Delete "${sel.name}"?`)) return;
    await fetch(`/api/servers/${sel.id}/delete`, { method: "DELETE" });
    setSel(null); setEditing(false); load();
  }
  async function scanServer() {
    if (!sel) return;
    setScanning(true);
    const res = await fetch(`/api/servers/${sel.id}/scan`, { method: "POST" });
    const d = await res.json().catch(() => ({}));
    setScanning(false);
    if (!d.ok) alert(d.detail || "Scan failed");
    await load(sel.id);
  }
  const set = (k: string) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <AppShell active="Servers" me={me} wide>
          {!sel ? (
            <>
              <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-5 text-sm">
                  <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-good" /> <b>{data?.up ?? "—"}</b> online</span>
                  <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-bad" /> <b>{data?.down ?? "—"}</b> unreachable</span>
                  <span className="text-ink-3">of {data?.total ?? "—"} servers</span>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={addServer} className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white transition hover:bg-brand-hover"><Icon name="plus" className="h-4 w-4" /> New server</button>
                  <button onClick={() => load()} disabled={loading} className="inline-flex items-center gap-1.5 rounded-lg border border-stroke bg-surface px-3 py-1.5 text-sm font-medium text-ink transition hover:border-brand hover:text-brand disabled:opacity-60"><Icon name="sync" className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh</button>
                </div>
              </div>
              <div className="mb-5 flex flex-wrap items-center gap-6 border-b border-stroke">
                {["All", ...groups].map((g) => {
                  const count = g === "All" ? data?.servers.length ?? 0 : data?.servers.filter((s) => s.group === g).length ?? 0;
                  return <button key={g} onClick={() => setGroup(g)} className={`-mb-px flex items-center gap-2 border-b-2 px-1 pb-3 text-sm font-medium transition ${group === g ? "border-brand text-brand" : "border-transparent text-ink-2 hover:text-ink"}`}>{g}<span className="rounded-full bg-subtle px-1.5 text-xs text-ink-2">{count}</span></button>;
                })}
              </div>
              {data === null && <p className="py-12 text-center text-sm text-ink-3">Checking servers…</p>}
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {data?.servers.filter((s) => group === "All" || s.group === group).map((s) => {
                  const st = STATUS[s.status];
                  return (
                    <button key={s.id} onClick={() => open(s)} className="rounded-lg border border-stroke bg-surface p-4 text-left shadow-sm transition hover:border-brand hover:shadow-md">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2"><span className={`h-2.5 w-2.5 shrink-0 rounded-full ${st.dot} ${s.status === "up" ? "animate-pulse" : ""}`} /><h3 className="truncate font-semibold leading-tight">{s.name}</h3></div>
                        <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${st.ring} ${st.text}`}>{st.label}</span>
                      </div>
                      <div className="mt-1.5"><CompanyBadge c={s.company} /></div>
                      <p className="mt-2 line-clamp-2 text-xs text-ink-2">{s.notes?.[0] ?? s.provider ?? ""}</p>
                      <div className="mt-3 flex items-center justify-between border-t border-stroke-soft pt-3 text-xs text-ink-3">
                        <span className="font-mono">{s.ip ?? "—"}</span>
                        <span>{s.cpu && s.ram ? `${s.cpu} · ${s.ram}` : ""}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </>
          ) : (
            <div>
              <button onClick={() => { setSel(null); setEditing(false); }} className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-ink-2 hover:text-ink"><Icon name="back" className="h-4 w-4" /> All servers</button>
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <span className={`h-3 w-3 rounded-full ${STATUS[sel.status].dot} ${sel.status === "up" ? "animate-pulse" : ""}`} />
                <h1 className="text-2xl font-bold tracking-tight">{sel.name}</h1>
                <CompanyBadge c={sel.company} />
                <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS[sel.status].ring} ${STATUS[sel.status].text}`}>{STATUS[sel.status].label}</span>
                <div className="ml-auto flex items-center gap-2">
                  {sel.netbird_url && !editing && <a href={sel.netbird_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white transition hover:bg-brand-hover"><Icon name="server" className="h-4 w-4" /> Connect via NetBird</a>}
                  {!editing && sel.ssh_command && <button onClick={scanServer} disabled={scanning} className="inline-flex items-center gap-1.5 rounded-lg border border-stroke bg-surface px-3 py-1.5 text-sm font-medium text-ink transition hover:border-brand hover:text-brand disabled:opacity-60"><Icon name="sync" className={`h-4 w-4 ${scanning ? "animate-spin" : ""}`} /> {scanning ? "Scanning…" : "Scan"}</button>}
                  {!editing && <button onClick={startEdit} className="rounded-lg border border-stroke bg-surface px-3 py-1.5 text-sm font-medium text-ink transition hover:border-brand hover:text-brand">Edit</button>}
                  {!editing && <button onClick={removeServer} className="rounded-lg border border-stroke bg-surface px-3 py-1.5 text-sm font-medium text-ink-2 transition hover:border-bad hover:text-bad">Delete</button>}
                </div>
              </div>

              {editing ? (
                /* ── EDIT FORM ── */
                <div className="space-y-4">
                  <Section title="Basics">
                    <div className="grid gap-3 sm:grid-cols-3">
                      <TextInput label="Name" value={form.name} onChange={set("name")} />
                      <TextInput label="Company" value={form.company} onChange={set("company")} />
                      <TextInput label="Group" value={form.group} onChange={set("group")} />
                    </div>
                  </Section>
                  <Section title="Network & hosting">
                    <div className="grid gap-3 sm:grid-cols-3">
                      <TextInput label="Public IP" value={form.ip} onChange={set("ip")} />
                      <TextInput label="Provider" value={form.provider} onChange={set("provider")} />
                      <TextInput label="Hostname" value={form.hostname} onChange={set("hostname")} />
                      <TextInput label="Status-check host" value={form.host} onChange={set("host")} />
                      <TextInput label="Status-check port" value={form.port} onChange={set("port")} />
                      <TextInput label="NetBird IP" value={form.netbird_ip} onChange={set("netbird_ip")} />
                      <TextInput label="LAN IP" value={form.lan_ip} onChange={set("lan_ip")} />
                      <TextInput label="NetBird connect URL" value={form.netbird_url} onChange={set("netbird_url")} />
                    </div>
                  </Section>
                  <Section title="Access & credentials">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <TextInput label="Access notes" value={form.access} onChange={set("access")} />
                      <TextInput label="SSH user" value={form.ssh_user} onChange={set("ssh_user")} />
                      <TextInput label="SSH host / IP" value={form.ssh_ip} onChange={set("ssh_ip")} />
                      <TextInput label="SSH key file (in ~/.ssh)" value={form.ssh_key} onChange={set("ssh_key")} />
                      <TextInput label="Password" value={form.password} onChange={set("password")} />
                    </div>
                    <p className="mt-2 text-xs text-ink-3">SSH user + host + key enable live metrics and scanning for this server.</p>
                  </Section>
                  <Section title="Documentation">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <AreaInput label="Domains" hint="one per line" value={form.domains} onChange={set("domains")} />
                      <AreaInput label="Notes & risks" hint="one per line" value={form.notes} onChange={set("notes")} />
                    </div>
                    <p className="mt-2 text-xs text-ink-3">OS, CPU, RAM, disk, runtimes, services and databases are auto-detected — press Scan to refresh them from the server.</p>
                  </Section>
                  <div className="flex items-center gap-2">
                    <button onClick={save} disabled={saving} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-hover disabled:opacity-60">{saving ? "Saving…" : "Save changes"}</button>
                    <button onClick={() => setEditing(false)} className="rounded-lg border border-stroke bg-surface px-4 py-2 text-sm font-medium text-ink-2 transition hover:bg-subtle">Cancel</button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="mb-5 flex items-center gap-6 border-b border-stroke">
                    {DTABS.map((t) => (
                      <button key={t} onClick={() => setDtab(t)} className={`-mb-px flex items-center gap-1.5 border-b-2 px-1 pb-3 text-sm font-medium transition ${dtab === t ? "border-brand text-brand" : "border-transparent text-ink-2 hover:text-ink"}`}>
                        {t === "Live Monitoring" && <span className="h-1.5 w-1.5 rounded-full bg-good" />}{t}
                        {t === "Domains" && sel.domains && sel.domains.length > 0 && <span className="rounded-full bg-subtle px-1.5 text-xs text-ink-2">{sel.domains.length}</span>}
                      </button>
                    ))}
                  </div>

                  {dtab === "Overview" && (
                    <div className="grid gap-4 lg:grid-cols-2">
                      <Section title="Overview"><Row k="Company" v={sel.company} /><Row k="Hostname" v={sel.hostname} /><Row k="OS" v={sel.os} /><Row k="Provider" v={sel.provider} /><Row k="Group" v={sel.group} /><Row k="Public IP" v={sel.ip} mono /><Row k="Latency" v={sel.status === "up" && sel.latency_ms != null ? `${sel.latency_ms} ms` : undefined} /></Section>
                      <Section title="Hardware"><Row k="CPU" v={sel.cpu} /><Row k="RAM" v={sel.ram} /><Row k="Disk / Storage" v={sel.disk} />{sel.runtimes && sel.runtimes.length > 0 && <div className="mt-3"><p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-3">Runtimes</p><div className="flex flex-wrap gap-1.5">{sel.runtimes.map((r) => <span key={r} className="rounded-lg bg-subtle px-2 py-1 text-xs font-medium text-ink-2">{r}</span>)}</div></div>}<p className="mt-3 border-t border-stroke-soft pt-3 text-xs text-ink-3">{sel.scanned_at ? `Auto-detected · scanned ${sel.scanned_at}` : "Auto-detected — press Scan to detect from the server."}</p></Section>
                      {sel.services && sel.services.length > 0 && <Section title="Services"><ul className="space-y-1.5">{sel.services.map((s) => <li key={s} className="flex items-center gap-2 text-sm text-ink"><span className="h-1.5 w-1.5 rounded-full bg-blue-400" /> {s}</li>)}</ul></Section>}
                      <Section title="Databases">{sel.databases && sel.databases.length > 0 ? <ul className="space-y-1.5">{sel.databases.map((d) => <li key={d} className="flex items-center gap-2 text-sm text-ink"><Icon name="records" className="h-3.5 w-3.5 text-ink-3" /> {d}</li>)}</ul> : <p className="text-sm text-ink-3">No databases recorded.</p>}</Section>
                      {sel.notes && sel.notes.length > 0 && <div className="lg:col-span-2"><Section title="Notes & Risks"><ul className="space-y-2">{sel.notes.map((nn, i) => <li key={i} className={`flex gap-2 text-sm ${nn.includes("⚠️") || nn.toLowerCase().includes("internet-facing") || nn.toLowerCase().includes("unprotected") ? "text-warnx" : "text-ink-2"}`}><span className="text-ink-3">•</span> {nn.replace("⚠️", "").trim()}</li>)}</ul></Section></div>}
                    </div>
                  )}

                  {dtab === "Live Monitoring" && (
                    <div>
                      {metrics === null && <p className="py-10 text-center text-sm text-ink-3">Connecting to {sel.name}…</p>}
                      {metrics && !metrics.available && <div className="rounded-lg border border-stroke bg-surface p-8 text-center shadow-sm"><p className="text-sm font-medium text-ink-2">Live metrics unavailable</p><p className="mt-1 text-sm text-ink-3">{metrics.detail || "No metrics source."}</p></div>}
                      {metrics && metrics.available && (
                        <>
                          <div className="mb-3 flex items-center gap-2 text-xs text-ink-3"><span className="relative flex h-2 w-2"><span className="absolute inline-flex h-2 w-2 animate-ping rounded-full bg-emerald-400 opacity-75" /><span className="inline-flex h-2 w-2 rounded-full bg-good" /></span> Live · SSH · refreshes every 3.5s {mLoading && "· updating…"}</div>
                          <div className="grid gap-4 sm:grid-cols-3">
                            <div className="rounded-lg border border-stroke bg-surface p-5 shadow-sm"><div className="flex items-baseline justify-between"><span className="text-xs font-semibold uppercase tracking-wide text-ink-3">CPU</span><span className="text-2xl font-bold tabular-nums">{metrics.cpu_percent != null ? `${metrics.cpu_percent}%` : "—"}</span></div><Bar pct={metrics.cpu_percent ?? 0} color={(metrics.cpu_percent ?? 0) > 85 ? "bg-bad" : "bg-brand-tint0"} /><p className="mt-2 text-xs text-ink-3">{metrics.cores} cores{metrics.load != null ? ` · load ${metrics.load}` : ""}</p></div>
                            <div className="rounded-lg border border-stroke bg-surface p-5 shadow-sm"><div className="flex items-baseline justify-between"><span className="text-xs font-semibold uppercase tracking-wide text-ink-3">Memory</span><span className="text-2xl font-bold tabular-nums">{metrics.mem_total_mb ? `${Math.round((metrics.mem_used_mb! / metrics.mem_total_mb) * 100)}%` : "—"}</span></div><Bar pct={metrics.mem_total_mb ? (metrics.mem_used_mb! / metrics.mem_total_mb) * 100 : 0} color="bg-violet-500" /><p className="mt-2 text-xs text-ink-3">{metrics.mem_used_mb} / {metrics.mem_total_mb} MB</p></div>
                            <div className="rounded-lg border border-stroke bg-surface p-5 shadow-sm"><div className="flex items-baseline justify-between"><span className="text-xs font-semibold uppercase tracking-wide text-ink-3">Disk</span><span className="text-2xl font-bold tabular-nums">{metrics.disk_total_gb ? `${Math.round((metrics.disk_used_gb! / metrics.disk_total_gb) * 100)}%` : "—"}</span></div><Bar pct={metrics.disk_total_gb ? (metrics.disk_used_gb! / metrics.disk_total_gb) * 100 : 0} color="bg-sky-500" /><p className="mt-2 text-xs text-ink-3">{metrics.disk_used_gb} / {metrics.disk_total_gb} GB</p></div>
                          </div>
                          {metrics.uptime && <p className="mt-4 text-sm text-ink-2">Uptime: {metrics.uptime}</p>}
                        </>
                      )}
                    </div>
                  )}

                  {dtab === "Domains" && (
                    <Section title={`Domains allocated to ${sel.name}`}>
                      {sel.domains && sel.domains.length > 0 ? <ul className="divide-y divide-stroke-soft">{sel.domains.map((d) => <li key={d} className="flex items-center justify-between py-2.5"><span className="flex items-center gap-2 font-mono text-sm text-ink"><Icon name="docs" className="h-4 w-4 text-ink-3" /> {d}</span><a href={`https://${d}`} target="_blank" rel="noreferrer" className="text-xs font-medium text-brand hover:text-brand-hover">Visit →</a></li>)}</ul> : <p className="text-sm text-ink-3">No domains allocated to this server.</p>}
                    </Section>
                  )}

                  {dtab === "Access" && (
                    <div className="grid gap-4 lg:grid-cols-2">
                      <Section title="Connection">
                        <Row k="Access" v={sel.access} />
                        <Row k="SSH command" v={sel.ssh_command} mono />
                        <Row k="SSH user" v={sel.ssh_user} />
                        <Row k="SSH host / IP" v={sel.ssh_ip} mono />
                        <Row k="SSH key" v={sel.ssh_key ? `~/.ssh/${sel.ssh_key}` : undefined} mono />
                        <Row k="Password" v={sel.password} mono />
                      </Section>
                      <Section title="Addresses">
                        <Row k="Public IP" v={sel.ip} mono />
                        <Row k="NetBird IP" v={sel.netbird_ip} mono />
                        <Row k="LAN IP" v={sel.lan_ip} mono />
                        <Row k="Status target" v={sel.target} mono />
                        {sel.netbird_url && <a href={sel.netbird_url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-sm font-semibold text-white transition hover:bg-brand-hover"><Icon name="server" className="h-4 w-4" /> Connect via NetBird</a>}
                      </Section>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
    </AppShell>
  );
}
