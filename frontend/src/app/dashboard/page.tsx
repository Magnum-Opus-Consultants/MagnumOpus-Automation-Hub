"use client";

import { useEffect, useState } from "react";
import { Icon, canAccess, type Me } from "@/components/Sidebar";
import { AppShell, relativeTime } from "@/components/ui";

type Commit = { short_sha: string; author: string; date: string; subject: string };
type Repo = { id: number; name: string; available: boolean; last_commit: Commit | null };

type Server = { id: number; name: string; status: "up" | "down" | "unknown" };
type Metrics = {
  available: boolean;
  cpu_percent?: number | null;
  mem_used_mb?: number; mem_total_mb?: number;
  disk_used_gb?: number; disk_total_gb?: number;
};

type Station = {
  key: string; name: string; records: number;
  time_ago: string | null;
  status: "healthy" | "stale" | "error" | "unknown";
};

/** At or above this, a resource reading is worth flagging. */
const BUSY = 85;

const pct = (used?: number, total?: number) =>
  used != null && total ? Math.round((used / total) * 100) : null;

const avg = (xs: number[]) => (xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : null);

/** One big number with its label. */
function Figure({ label, value, tone = "ink" }: { label: string; value: React.ReactNode; tone?: "ink" | "good" | "bad" | "muted" }) {
  const color = { ink: "text-ink", good: "text-good", bad: "text-bad", muted: "text-ink-3" }[tone];
  return (
    <div className="flex-1 px-5 py-6">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</p>
      <p className={`mt-1 truncate text-5xl font-semibold leading-none tracking-tight tabular-nums ${color}`}>{value}</p>
    </div>
  );
}

/** Compact resource readout: label, wide bar, percentage. */
function Meter({ label, value }: { label: string; value: number | null | undefined }) {
  const loading = value === undefined;
  const tone = value == null ? "bg-subtle" : value >= BUSY ? "bg-bad" : value >= 70 ? "bg-warnx" : "bg-good";
  return (
    <div className="flex-1">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</span>
        <span className="text-sm font-semibold tabular-nums text-ink">
          {loading ? "…" : value == null ? "n/a" : `${value}%`}
        </span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-subtle">
        <div
          className={`h-full rounded-full transition-all duration-500 ${tone} ${loading ? "animate-pulse" : ""}`}
          style={{ width: loading ? "100%" : `${Math.min(100, value ?? 0)}%` }}
        />
      </div>
    </div>
  );
}

/** Plain-language line saying whether this area is fine. */
function Verdict({ ok, text }: { ok: boolean; text: string }) {
  return (
    <div className={`mt-auto flex items-center gap-2 border-t border-stroke px-5 py-3 text-sm font-medium ${ok ? "text-good" : "text-bad"}`}>
      <span className={`h-2 w-2 shrink-0 rounded-full ${ok ? "bg-good" : "bg-bad"}`} />
      {text}
    </div>
  );
}

function Panel({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="flex flex-col overflow-hidden rounded-lg bg-surface ring-panel">
      <div className="flex items-center gap-2 border-b border-stroke px-5 py-2.5">
        <h2 className="text-xs font-medium uppercase tracking-wide text-ink-3">{title}</h2>
        {right && <div className="ml-auto">{right}</div>}
      </div>
      <div className="flex flex-1 flex-col">{children}</div>
    </section>
  );
}

/** Placeholder with the same shape as a loaded panel, so nothing shifts when
 *  the data lands and a slow fetch never reads as an empty/broken panel. */
function SkeletonPanel({ title, figures, meters }: { title: string; figures: number; meters?: boolean }) {
  return (
    <Panel title={title} right={<span className="text-xs text-ink-3">Loading…</span>}>
      <div className="flex items-stretch divide-x divide-stroke">
        {Array.from({ length: figures }).map((_, i) => (
          <div key={i} className="flex-1 px-5 py-6">
            <div className="h-3 w-14 animate-pulse rounded bg-subtle" />
            <div className="mt-2.5 h-9 w-16 animate-pulse rounded bg-subtle" />
          </div>
        ))}
      </div>
      <div className="border-t border-stroke px-5 py-4">
        <div className="h-3 w-24 animate-pulse rounded bg-subtle" />
        {meters ? (
          <div className="mt-3 flex gap-6">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex-1">
                <div className="h-3 w-10 animate-pulse rounded bg-subtle" />
                <div className="mt-1.5 h-2 animate-pulse rounded-full bg-subtle" />
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-2 h-7 w-28 animate-pulse rounded bg-subtle" />
        )}
      </div>
      <div className="mt-auto flex items-center gap-2 border-t border-stroke px-5 py-3">
        <div className="h-2 w-2 animate-pulse rounded-full bg-subtle" />
        <div className="h-3 w-40 animate-pulse rounded bg-subtle" />
      </div>
    </Panel>
  );
}

export default function DashboardPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [servers, setServers] = useState<{ up: number; down: number; total: number; servers: Server[] } | null>(null);
  const [metrics, setMetrics] = useState<Record<number, Metrics>>({});
  const [stations, setStations] = useState<{ healthy: number; stale: number; error: number; total: number; stations: Station[] } | null>(null);
  const [repos, setRepos] = useState<{ repos: Repo[] } | null>(null);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);

        function get<T>(url: string, set: (d: T) => void) {
          fetch(url)
            .then((r) => (r.ok ? (r.json() as Promise<T>) : Promise.reject(new Error(String(r.status)))))
            .then(set)
            .catch(() => {});
        }

        if (canAccess(m, "data")) get("/api/data-analysis/stations", setStations);
        if (canAccess(m, "repos")) get("/api/repos", setRepos);
        if (canAccess(m, "servers")) {
          get<{ up: number; down: number; total: number; servers: Server[] }>("/api/servers", (d) => {
            setServers(d);
            // Resources come from a per-server SSH call — only ask the reachable ones.
            d.servers
              .filter((s) => s.status === "up")
              .forEach((s) =>
                get<Metrics>(`/api/servers/metrics?id=${s.id}`, (mm) =>
                  setMetrics((cur) => ({ ...cur, [s.id]: mm })),
                ),
              );
          });
        }
      })
      .catch(() => (window.location.href = "/login"));
  }, []);

  // ── Reports ──
  const all = stations?.stations ?? [];
  const passed = stations?.healthy ?? 0;
  const failed = all.length - passed;
  const reportsOk = stations != null && failed === 0;
  const lastSync = all.map((s) => s.time_ago).find((t) => t && t !== "never") ?? null;

  // ── Servers: fleet-wide averages, not a per-box table. Detail lives on /servers. ──
  const upServers = (servers?.servers ?? []).filter((s) => s.status === "up");
  const live = upServers.map((s) => metrics[s.id]).filter((m): m is Metrics => !!m?.available);
  const checking = upServers.filter((s) => metrics[s.id] === undefined).length;
  // Stay in the loading state until every online server has answered, so the
  // averages appear once instead of jumping as each SSH call lands.
  const pending = checking > 0;

  const cpuAvg = pending ? undefined : avg(live.map((m) => m.cpu_percent ?? 0));
  const memAvg = pending ? undefined : avg(live.map((m) => pct(m.mem_used_mb, m.mem_total_mb) ?? 0));
  const diskAvg = pending ? undefined : avg(live.map((m) => pct(m.disk_used_gb, m.disk_total_gb) ?? 0));

  const hot = [cpuAvg, memAvg, diskAvg].some((v) => v != null && v >= BUSY);
  const serversOk = servers != null && servers.down === 0 && !hot;

  const activity = (repos?.repos ?? [])
    .filter((r) => r.available && r.last_commit)
    .map((r) => ({ repo: r.name, c: r.last_commit! }))
    .sort((a, b) => b.c.date.localeCompare(a.c.date))
    .slice(0, 4);

  // What this user should see at all — drives skeleton vs. real vs. nothing.
  const wantsData = !!me && canAccess(me, "data");
  const wantsServers = !!me && canAccess(me, "servers");
  const wantsRepos = !!me && canAccess(me, "repos");
  const nothing = !!me && !wantsData && !wantsServers && !wantsRepos;

  return (
    <AppShell active="Dashboard" me={me} wide>
      <div className="grid gap-4 xl:grid-cols-2">
        {/* Before `me` resolves we do not yet know which panels apply, so show
            both placeholders — that is the common case on a cold load. */}
        {!me && (
          <>
            <SkeletonPanel title="Reports" figures={2} />
            <SkeletonPanel title="Servers" figures={3} meters />
          </>
        )}

        {wantsData && !stations && <SkeletonPanel title="Reports" figures={2} />}
        {wantsServers && !servers && <SkeletonPanel title="Servers" figures={3} meters />}

        {stations && (
          <Panel
            title="Reports"
            right={<a href="/data-analysis" className="text-xs font-medium text-brand hover:underline">View all</a>}
          >
            <div className="flex items-stretch divide-x divide-stroke">
              <Figure label="Passed" value={passed} tone={passed > 0 ? "good" : "muted"} />
              <Figure label="Failed" value={failed} tone={failed > 0 ? "bad" : "muted"} />
            </div>
            <div className="border-t border-stroke px-5 py-4">
              <p className="text-xs font-medium uppercase tracking-wide text-ink-3">Last sync</p>
              <p className="mt-0.5 text-2xl font-semibold text-ink">{lastSync ?? "never"}</p>
            </div>
            <Verdict
              ok={reportsOk}
              text={reportsOk
                ? `All ${stations.total} reports up to date`
                : `${failed} of ${stations.total} reports need attention`}
            />
          </Panel>
        )}

        {servers && (
          <Panel
            title="Servers"
            right={
              <div className="flex items-center gap-3">
                {checking > 0 && (
                  <span className="flex items-center gap-1.5 text-xs text-ink-3">
                    <Icon name="sync" className="h-3 w-3 animate-spin" />
                    Checking {checking}…
                  </span>
                )}
                <a href="/servers" className="text-xs font-medium text-brand hover:underline">View all</a>
              </div>
            }
          >
            <div className="flex items-stretch divide-x divide-stroke">
              <Figure label="Online" value={servers.up} tone={servers.up > 0 ? "good" : "muted"} />
              <Figure label="Offline" value={servers.down} tone={servers.down > 0 ? "bad" : "muted"} />
              <Figure label="Total" value={servers.total} />
            </div>
            <div className="border-t border-stroke px-5 py-4">
              <p className="mb-2.5 text-xs font-medium uppercase tracking-wide text-ink-3">
                Average load · {live.length || upServers.length} online
              </p>
              <div className="flex gap-6">
                <Meter label="CPU" value={cpuAvg} />
                <Meter label="Memory" value={memAvg} />
                <Meter label="Disk" value={diskAvg} />
              </div>
            </div>
            <Verdict
              ok={serversOk}
              text={serversOk
                ? `All ${servers.total} reachable, resources healthy`
                : [
                    servers.down > 0 ? `${servers.down} of ${servers.total} unreachable` : null,
                    hot ? "resources running hot" : null,
                  ].filter(Boolean).join(" · ")}
            />
          </Panel>
        )}

        {activity.length > 0 && (
          <div className="xl:col-span-2">
            <Panel title="Recent activity">
              <ul className="divide-y divide-stroke">
                {activity.map(({ repo, c }) => (
                  <li key={`${repo}-${c.short_sha}`} className="flex items-start gap-3 px-5 py-3">
                    <Icon name="commit" className="mt-0.5 h-4 w-4 shrink-0 text-ink-3" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink">{c.subject}</p>
                      <p className="truncate text-xs text-ink-3">{repo} · {c.author} · {relativeTime(c.date)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>
          </div>
        )}

        {nothing && (
          <Panel title="Overview">
            <p className="px-5 py-4 text-sm text-ink-2">Nothing to show yet.</p>
          </Panel>
        )}
      </div>
    </AppShell>
  );
}
