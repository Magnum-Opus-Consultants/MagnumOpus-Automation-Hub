"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, Row, StatTile, Badge, Button, EmptyState, Modal,
  TextInput, AreaInput, SelectInput, CheckboxInput,
  Pill, expiryTone, expiryLabel, type Tone,
} from "@/components/ui";

type Domain = {
  id: number; name: string; company: string; environment: string; status: string;
  registrar: string; dns_provider: string; nameservers: string; primary_url: string;
  server: number | null; server_name: string;
  registered_on: string | null; expires_on: string | null; ssl_expires_on: string | null;
  days_to_expiry: number | null; days_to_ssl_expiry: number | null;
  auto_renew: boolean; notes: string; order: number;
};
type Payload = { domains: Domain[]; total: number; expiring_soon: number; expired: number; ssl_expiring_soon: number };
type ServerOpt = { id: number; name: string };

const STATUS_TONE: Record<string, Tone> = {
  active: "good", parked: "neutral", redirect: "info", transferring: "warn", expired: "bad",
};
const STATUS_OPTS = [
  { value: "active", label: "Active" }, { value: "parked", label: "Parked" },
  { value: "redirect", label: "Redirect" }, { value: "transferring", label: "Transferring" },
  { value: "expired", label: "Expired" },
];
const ENV_OPTS = [
  { value: "production", label: "Production" }, { value: "staging", label: "Staging" },
  { value: "internal", label: "Internal" }, { value: "other", label: "Other" },
];

const BLANK = {
  name: "", company: "", environment: "production", status: "active",
  registrar: "", dns_provider: "", nameservers: "", primary_url: "",
  server: "", registered_on: "", expires_on: "", ssl_expires_on: "",
  auto_renew: true, notes: "",
};
type Form = typeof BLANK;

function toForm(d: Domain): Form {
  return {
    name: d.name, company: d.company, environment: d.environment, status: d.status,
    registrar: d.registrar, dns_provider: d.dns_provider, nameservers: d.nameservers,
    primary_url: d.primary_url, server: d.server ? String(d.server) : "",
    registered_on: d.registered_on ?? "", expires_on: d.expires_on ?? "",
    ssl_expires_on: d.ssl_expires_on ?? "", auto_renew: d.auto_renew, notes: d.notes,
  };
}

export default function DomainsPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<Payload | null>(null);
  const [servers, setServers] = useState<ServerOpt[]>([]);
  // Starts true so the first paint shows the loading state without the mount
  // effect having to set it synchronously.
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [env, setEnv] = useState("All");
  const [sel, setSel] = useState<Domain | null>(null);
  const [editing, setEditing] = useState<Domain | "new" | null>(null);
  const [form, setForm] = useState<Form>(BLANK);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Every state update happens after an await, so nothing re-renders
  // synchronously while the mount effect is still running.
  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/domains");
      if (!r.ok) throw new Error(String(r.status));
      const d: Payload = await r.json();
      setData(d);
      setSel((cur) => (cur ? d.domains.find((x) => x.id === cur.id) ?? null : null));
    } catch {
      setData({ domains: [], total: 0, expiring_soon: 0, expired: 0, ssl_expiring_soon: 0 });
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
        if (!canAccess(m, "domains")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // load() only updates state after awaiting the fetch, so nothing re-renders
    // synchronously here; the rule cannot see through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    // Server list powers the "points at" dropdown; failure just leaves it empty.
    fetch("/api/servers")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setServers((d.servers ?? []).map((s: ServerOpt) => ({ id: s.id, name: s.name }))))
      .catch(() => setServers([]));
  }, [load]);

  const rows = useMemo(() => {
    const term = q.trim().toLowerCase();
    return (data?.domains ?? []).filter((d) => {
      if (env !== "All" && d.environment !== env) return false;
      if (!term) return true;
      return [d.name, d.company, d.registrar, d.dns_provider, d.server_name]
        .some((f) => (f ?? "").toLowerCase().includes(term));
    });
  }, [data, q, env]);

  // Soonest expiry first, undated last — the renewal queue reading of the list.
  const sorted = useMemo(
    () => [...rows].sort((a, b) => {
      const av = a.days_to_expiry, bv = b.days_to_expiry;
      if (av === null && bv === null) return a.name.localeCompare(b.name);
      if (av === null) return 1;
      if (bv === null) return -1;
      return av - bv;
    }),
    [rows],
  );

  function startNew() { setForm(BLANK); setError(""); setEditing("new"); }
  function startEdit(d: Domain) { setForm(toForm(d)); setError(""); setEditing(d); }
  const set = <K extends keyof Form>(k: K) => (v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    if (!editing) return;
    setSaving(true);
    setError("");
    const body = { ...form, server: form.server ? Number(form.server) : null };
    const url = editing === "new" ? "/api/domains/create" : `/api/domains/${editing.id}`;
    const res = await fetch(url, {
      method: editing === "new" ? "POST" : "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setSaving(false);
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      setError(d.detail || "Could not save this domain.");
      return;
    }
    setEditing(null);
    await load();
  }

  async function remove(d: Domain) {
    if (!confirm(`Delete ${d.name}? This cannot be undone.`)) return;
    await fetch(`/api/domains/${d.id}/delete`, { method: "DELETE" });
    setSel(null);
    await load();
  }

  return (
    <AppShell
      active="Domains"
      me={me}
      wide
    >
      <PageHead
        title="Domains"
        subtitle="Registrations, DNS, SSL and renewal dates for every domain the group owns."
        actions={
          <>
            <Button icon="plus" variant="primary" onClick={startNew}>New domain</Button>
            <Button icon="sync" spinning={loading} onClick={refresh} disabled={loading}>Refresh</Button>
          </>
        }
      />

      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Domains" value={data?.total ?? "—"} icon="globe" hint="Tracked in total" />
        <StatTile label="Expiring ≤30d" value={data?.expiring_soon ?? "—"} tone={(data?.expiring_soon ?? 0) > 0 ? "warn" : "good"} icon="clock" hint="Registration renewal" />
        <StatTile label="Expired" value={data?.expired ?? "—"} tone={(data?.expired ?? 0) > 0 ? "bad" : "good"} icon="alert" hint="Past renewal date" />
        <StatTile label="SSL ≤30d" value={data?.ssl_expiring_soon ?? "—"} tone={(data?.ssl_expiring_soon ?? 0) > 0 ? "warn" : "good"} icon="lock" hint="Certificate renewal" />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 sm:max-w-xs">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search domain, registrar, server…"
            className="w-full rounded-lg border border-stroke bg-surface py-1.5 pl-9 pr-3 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand"
          />
          <svg viewBox="0 0 24 24" className="pointer-events-none absolute left-2.5 top-1.5 h-4 w-4 text-ink-3" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        </div>
        {["All", ...ENV_OPTS.map((e) => e.value)].map((e) => (
          <Pill key={e} active={env === e} onClick={() => setEnv(e)}>{e}</Pill>
        ))}
      </div>

      {data === null ? (
        <p className="py-12 text-center text-sm text-ink-3">Loading domains…</p>
      ) : sorted.length === 0 ? (
        <EmptyState
          icon="globe"
          title={data.total === 0 ? "No domains recorded yet" : "No domains match this filter"}
          hint={data.total === 0 ? "Add your first domain to start tracking registrar, DNS and renewal dates." : "Try a different search or environment."}
          action={data.total === 0 ? <Button icon="plus" variant="primary" onClick={startNew}>New domain</Button> : undefined}
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-stroke bg-surface shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead className="border-b border-stroke bg-subtle/60 text-left text-xs font-medium uppercase tracking-wider text-ink-3">
                <tr>
                  <th className="px-4 py-2.5">Domain</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Registrar</th>
                  <th className="px-4 py-2.5">Points at</th>
                  <th className="px-4 py-2.5">Registration</th>
                  <th className="px-4 py-2.5">SSL</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-stroke-soft">
                {sorted.map((d) => (
                  <tr key={d.id} className="group transition hover:bg-brand-tint/50">
                    <td className="px-4 py-2.5">
                      <button onClick={() => setSel(d)} className="text-left">
                        <span className="font-semibold text-ink group-hover:text-brand-hover">{d.name}</span>
                        <span className="block text-xs text-ink-3">{d.company || d.environment}</span>
                      </button>
                    </td>
                    <td className="px-4 py-2.5"><Badge tone={STATUS_TONE[d.status] ?? "neutral"}>{d.status}</Badge></td>
                    <td className="px-4 py-2.5 text-ink-2">{d.registrar || "—"}</td>
                    <td className="px-4 py-2.5 text-ink-2">
                      {d.server_name
                        ? <a href={`/servers?server=${d.server}`} className="text-brand hover:text-brand-hover">{d.server_name}</a>
                        : <span className="text-ink-3">—</span>}
                    </td>
                    <td className="px-4 py-2.5"><Badge tone={expiryTone(d.days_to_expiry)}>{expiryLabel(d.days_to_expiry)}</Badge></td>
                    <td className="px-4 py-2.5"><Badge tone={expiryTone(d.days_to_ssl_expiry)}>{expiryLabel(d.days_to_ssl_expiry)}</Badge></td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="flex justify-end gap-1 opacity-0 transition group-hover:opacity-100">
                        <Button variant="ghost" icon="edit" onClick={() => startEdit(d)} aria-label={`Edit ${d.name}`} />
                        <Button variant="ghost" icon="trash" onClick={() => remove(d)} aria-label={`Delete ${d.name}`} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Detail drawer */}
      {sel && (
        <Modal
          title={sel.name}
          onClose={() => setSel(null)}
          footer={
            <>
              <Button icon="edit" onClick={() => { const d = sel; setSel(null); startEdit(d); }}>Edit</Button>
              <Button variant="danger" icon="trash" onClick={() => remove(sel)}>Delete</Button>
            </>
          }
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Section title="Registration">
              <Row k="Status" v={sel.status} />
              <Row k="Environment" v={sel.environment} />
              <Row k="Company" v={sel.company} />
              <Row k="Registrar" v={sel.registrar} />
              <Row k="Auto-renew" v={sel.auto_renew ? "Yes" : "No"} />
              <Row k="Registered" v={sel.registered_on} />
              <Row k="Expires" v={sel.expires_on ? `${sel.expires_on} (${expiryLabel(sel.days_to_expiry)})` : null} />
            </Section>
            <Section title="DNS & hosting">
              <Row k="DNS provider" v={sel.dns_provider} />
              <Row k="Points at" v={sel.server_name} />
              <Row k="Primary URL" v={sel.primary_url} mono />
              <Row k="SSL expires" v={sel.ssl_expires_on ? `${sel.ssl_expires_on} (${expiryLabel(sel.days_to_ssl_expiry)})` : null} />
              {sel.nameservers && (
                <div className="pt-2">
                  <p className="mb-1 text-xs text-ink-3">Nameservers</p>
                  <ul className="space-y-0.5">
                    {sel.nameservers.split("\n").filter(Boolean).map((ns) => (
                      <li key={ns} className="font-mono text-xs text-ink">{ns}</li>
                    ))}
                  </ul>
                </div>
              )}
            </Section>
            {sel.notes && (
              <div className="sm:col-span-2">
                <Section title="Notes"><p className="whitespace-pre-wrap text-sm text-ink-2">{sel.notes}</p></Section>
              </div>
            )}
            {sel.primary_url && (
              <div className="sm:col-span-2">
                <a href={sel.primary_url.startsWith("http") ? sel.primary_url : `https://${sel.name}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand hover:text-brand-hover">
                  <Icon name="globe" className="h-4 w-4" /> Open site
                </a>
              </div>
            )}
          </div>
        </Modal>
      )}

      {/* Create / edit */}
      {editing && (
        <Modal
          wide
          title={editing === "new" ? "New domain" : `Edit ${editing.name}`}
          onClose={() => setEditing(null)}
          footer={
            <>
              {error && <p className="mr-auto text-sm text-bad">{error}</p>}
              <Button onClick={() => setEditing(null)}>Cancel</Button>
              <Button variant="primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save domain"}</Button>
            </>
          }
        >
          <div className="space-y-4">
            <Section title="Identity">
              <div className="grid gap-3 sm:grid-cols-3">
                <TextInput label="Domain name" value={form.name} onChange={set("name")} placeholder="example.com" />
                <TextInput label="Company" value={form.company} onChange={set("company")} />
                <SelectInput label="Environment" value={form.environment} onChange={set("environment")} options={ENV_OPTS} />
                <SelectInput label="Status" value={form.status} onChange={set("status")} options={STATUS_OPTS} />
                <TextInput label="Primary URL" value={form.primary_url} onChange={set("primary_url")} hint="optional" />
                <SelectInput
                  label="Points at server"
                  value={form.server}
                  onChange={set("server")}
                  options={[{ value: "", label: "— none —" }, ...servers.map((s) => ({ value: String(s.id), label: s.name }))]}
                />
              </div>
            </Section>
            <Section title="Registrar & DNS">
              <div className="grid gap-3 sm:grid-cols-2">
                <TextInput label="Registrar" value={form.registrar} onChange={set("registrar")} />
                <TextInput label="DNS provider" value={form.dns_provider} onChange={set("dns_provider")} />
              </div>
              <div className="mt-3">
                <AreaInput label="Nameservers" hint="one per line" rows={3} value={form.nameservers} onChange={set("nameservers")} />
              </div>
            </Section>
            <Section title="Renewal dates">
              <div className="grid gap-3 sm:grid-cols-4">
                <TextInput label="Registered on" type="date" value={form.registered_on} onChange={set("registered_on")} />
                <TextInput label="Expires on" type="date" value={form.expires_on} onChange={set("expires_on")} />
                <TextInput label="SSL expires on" type="date" value={form.ssl_expires_on} onChange={set("ssl_expires_on")} />
                <CheckboxInput label="Auto-renew" hint="Registrar renews automatically" checked={form.auto_renew} onChange={set("auto_renew")} />
              </div>
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
