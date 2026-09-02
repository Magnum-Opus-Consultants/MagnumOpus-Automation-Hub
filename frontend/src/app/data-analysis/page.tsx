"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Icon, canAccess, type Me } from "@/components/Sidebar";
import { AppShell, PageHead, Badge, Button, Pill, type Tone } from "@/components/ui";

type StationStatus = "healthy" | "stale" | "error" | "unknown";

type Station = {
  key: string;
  code: string;
  name: string;
  description: string;
  records: number | null;
  last_sync: { time: string; date: string } | null;
  time_ago: string | null;
  status: StationStatus;
};

type Log = { t: string; station: string; msg: string; level: "info" | "ok" | "warn" };

const TABS = ["Automated Reports", "Sync Logs"] as const;
type Tab = (typeof TABS)[number];

const STATUS_TONE: Record<StationStatus, Tone> = {
  healthy: "good",
  stale: "warn",
  error: "bad",
  unknown: "neutral",
};
const STATUS_DOT: Record<StationStatus, string> = {
  healthy: "bg-good",
  stale: "bg-warnx",
  error: "bg-bad",
  unknown: "bg-ink-3",
};
const STATUS_LABEL: Record<StationStatus, string> = {
  healthy: "Healthy",
  stale: "Stale",
  error: "Failed",
  unknown: "Never synced",
};

/** Stations the backend has no manual trigger for — they sync on their own. */
const AUTO_ONLY = new Set(["creditor"]);

const FILTERS = ["All", "Failed", "Stale", "Healthy"] as const;
type Filter = (typeof FILTERS)[number];

export default function DataAnalysisPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [stations, setStations] = useState<Station[] | null>(null);
  const [tab, setTab] = useState<Tab>("Automated Reports");
  const [filter, setFilter] = useState<Filter>("All");
  const [syncing, setSyncing] = useState<Set<string>>(new Set());
  const [refreshing, setRefreshing] = useState(false);
  const [logs, setLogs] = useState<Log[]>([]);
  const seeded = useRef(false);

  const loadStations = useCallback(async (seed = false) => {
    try {
      const r = await fetch("/api/data-analysis/stations");
      if (!r.ok) throw new Error(String(r.status));
      const d: { stations: Station[] } = await r.json();
      setStations(d.stations);
      if (seed && !seeded.current) {
        seeded.current = true;
        // Seed the log with the last known sync per station, newest first.
        setLogs(
          d.stations
            .filter((s) => s.last_sync)
            .sort((a, b) =>
              a.last_sync!.date + a.last_sync!.time < b.last_sync!.date + b.last_sync!.time ? 1 : -1,
            )
            .slice(0, 40)
            .map((s) => ({
              t: `${s.last_sync!.date}, ${s.last_sync!.time}`,
              station: s.name,
              msg: s.records != null ? `Synced ${s.records.toLocaleString()} records` : "Synced",
              level: s.status === "healthy" ? ("ok" as const) : ("warn" as const),
            })),
        );
      }
    } catch {
      setStations([]);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        // Data Analysis is the only surfaced module, so a user without it has
        // nowhere else to land — send them back to sign in rather than to a
        // page that is no longer in the navigation.
        if (!canAccess(m, "data")) window.location.href = "/login";
      })
      .catch(() => (window.location.href = "/login"));
    // loadStations only sets state after awaiting, so nothing re-renders
    // synchronously here; the rule cannot see through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadStations(true);
  }, [loadStations]);

  function addLog(station: string, msg: string, level: Log["level"]) {
    const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setLogs((prev) => [{ t, station, msg, level }, ...prev].slice(0, 200));
  }

  async function onSync(s: Station) {
    setSyncing((prev) => new Set(prev).add(s.key));
    addLog(s.name, "Sync requested…", "info");
    try {
      const res = await fetch("/api/data-analysis/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ station: s.key }),
      });
      const d = await res.json().catch(() => ({}));
      const started = d.status === "started";
      addLog(s.name, d.message || d.detail || (started ? "Sync started" : "Done"), started ? "ok" : "warn");
      // Give the background job a moment, then pick up the new row counts.
      if (started) setTimeout(() => void loadStations(), 4000);
    } catch {
      addLog(s.name, "Sync failed — could not reach the backend", "warn");
    } finally {
      setTimeout(
        () => setSyncing((prev) => { const n = new Set(prev); n.delete(s.key); return n; }),
        700,
      );
    }
  }

  function refresh() {
    setRefreshing(true);
    void loadStations();
  }

  const n = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString());

  // Every status is counted, so the parts always add up to the total.
  const counts = {
    healthy: stations?.filter((s) => s.status === "healthy").length ?? 0,
    stale: stations?.filter((s) => s.status === "stale").length ?? 0,
    error: stations?.filter((s) => s.status === "error").length ?? 0,
    unknown: stations?.filter((s) => s.status === "unknown").length ?? 0,
  };
  const shown = (stations ?? []).filter((s) =>
    filter === "All" ? true
      : filter === "Failed" ? s.status === "error"
      : filter === "Stale" ? s.status === "stale" || s.status === "unknown"
      : s.status === "healthy",
  );

  return (
    <AppShell active="Data Analysis" me={me} wide>
      <PageHead
        title="Data Analysis"
        subtitle={
          stations
            ? [
                `${stations.length} sources`,
                `${counts.healthy} healthy`,
                `${counts.error} failed`,
                counts.stale > 0 ? `${counts.stale} stale` : null,
                counts.unknown > 0 ? `${counts.unknown} never synced` : null,
              ].filter(Boolean).join(" · ")
            : undefined
        }
        actions={<Button icon="sync" spinning={refreshing} onClick={refresh} disabled={refreshing}>Refresh</Button>}
      />

      <div className="mb-4 flex items-center gap-6 border-b border-stroke">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px flex items-center gap-2 border-b-2 px-1 pb-2.5 text-sm font-medium transition ${
              tab === t ? "border-brand text-brand" : "border-transparent text-ink-2 hover:text-ink"
            }`}
          >
            {t === "Sync Logs" && <Icon name="sync" className="h-4 w-4" />}
            {t}
            {t === "Sync Logs" && logs.length > 0 && (
              <span className="rounded-full bg-subtle px-1.5 text-xs text-ink-2">{logs.length}</span>
            )}
          </button>
        ))}
      </div>

      {tab === "Automated Reports" ? (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            {FILTERS.map((f) => (
              <Pill key={f} active={filter === f} onClick={() => setFilter(f)}>{f}</Pill>
            ))}
          </div>

          {stations === null ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
              {Array.from({ length: 12 }).map((_, i) => (
                <div key={i} className="rounded-lg bg-surface p-3.5 ring-panel">
                  <div className="h-4 w-3/4 animate-pulse rounded bg-subtle" />
                  <div className="mt-2 h-3 w-full animate-pulse rounded bg-subtle" />
                  <div className="mt-3 h-6 w-1/2 animate-pulse rounded bg-subtle" />
                  <div className="mt-3 h-7 w-full animate-pulse rounded bg-subtle" />
                </div>
              ))}
            </div>
          ) : shown.length === 0 ? (
            <p className="rounded-lg bg-surface px-4 py-12 text-center text-sm text-ink-2 ring-panel">
              No sources match this filter.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
              {shown.map((s) => {
                const isSyncing = syncing.has(s.key);
                const auto = AUTO_ONLY.has(s.key);
                return (
                  <div key={s.key} className="flex flex-col rounded-lg bg-surface p-3.5 ring-panel transition hover:bg-subtle/40">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="truncate text-sm font-semibold leading-tight text-ink" title={s.name}>{s.name}</h3>
                      {/* Reflects the real sync status — a source with rows but a
                          failed run is not "active". */}
                      <span
                        className={`mt-1 h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[s.status]}`}
                        title={STATUS_LABEL[s.status]}
                      />
                    </div>
                    <p className="mt-1 line-clamp-2 h-8 text-xs text-ink-3" title={s.description}>{s.description}</p>

                    <div className="mt-2 text-lg font-bold tracking-tight tabular-nums text-ink">{n(s.records)}</div>
                    <div className="text-xs font-medium uppercase tracking-wide text-ink-3">Records</div>

                    <div className="mt-2">
                      <Badge tone={STATUS_TONE[s.status]}>{STATUS_LABEL[s.status]}</Badge>
                    </div>

                    {auto ? (
                      <p className="mt-3 rounded-md bg-subtle px-2.5 py-1.5 text-center text-xs text-ink-2" title="No manual trigger for this source">
                        Syncs automatically
                      </p>
                    ) : (
                      <button
                        onClick={() => onSync(s)}
                        disabled={isSyncing}
                        className="mt-3 inline-flex items-center justify-center gap-1.5 rounded-md bg-surface px-2.5 py-1.5 text-xs font-medium text-ink ring-control transition hover:bg-subtle disabled:opacity-60 focus-ring"
                      >
                        <Icon name="sync" className={`h-3.5 w-3.5 ${isSyncing ? "animate-spin" : ""}`} />
                        {isSyncing ? "Syncing…" : "Sync"}
                      </button>
                    )}

                    <p className="mt-2 truncate text-xs text-ink-3" title={s.last_sync ? `${s.last_sync.date}, ${s.last_sync.time}` : undefined}>
                      {s.time_ago ? `${s.time_ago}` : s.last_sync ? `${s.last_sync.date}, ${s.last_sync.time}` : "Not yet synced"}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </>
      ) : (
        <div className="overflow-hidden rounded-lg bg-surface ring-panel">
          <div className="flex items-center justify-between border-b border-stroke px-4 py-2.5">
            <h2 className="text-sm font-semibold text-ink">Data sync logs</h2>
            <button
              onClick={refresh}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-brand transition hover:underline focus-ring"
            >
              <Icon name="sync" className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} /> Refresh
            </button>
          </div>
          <div className="max-h-[70vh] divide-y divide-stroke overflow-y-auto font-mono text-xs">
            {logs.length === 0 && <p className="px-4 py-10 text-center text-ink-3">No sync activity yet.</p>}
            {logs.map((l, i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-2">
                <span className="w-24 shrink-0 text-ink-3">{l.t}</span>
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${l.level === "ok" ? "bg-good" : l.level === "warn" ? "bg-warnx" : "bg-infox"}`} />
                <span className="w-40 shrink-0 truncate font-sans font-medium text-ink">{l.station}</span>
                <span className="truncate text-ink-2">{l.msg}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </AppShell>
  );
}
