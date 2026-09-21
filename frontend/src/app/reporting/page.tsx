"use client";

/**
 * The CargoWise reports, which used to be a separate concern entirely: their
 * own repository, their own systemd timer, a status JSON on disk and an email
 * that was the only way to know a report had failed.
 *
 * This page is the reason to consolidate them. Fifteen reports, when each last
 * pulled successfully, how many rows it moved, and — when one fails — a
 * sentence saying what to do about it, with a button to try again.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, StatTile, Badge, Button, EmptyState, Pill, Modal,
} from "@/components/ui";

type Report = {
  script: string; name: string; enabled: boolean;
  run_days: number[]; runs_today: boolean;
  last_outcome: string; last_run_at: string | null;
  last_success_at: string | null; last_rows: number | null;
  last_error: string; consecutive_failures: number;
  hours_since_success: number | null;
};
type Run = {
  id: number; script: string; name: string;
  outcome: string; outcome_label: string;
  rows: number | null; error: string;
  duration_seconds: number | null; started_at: string | null;
  batch: string; triggered_by: string;
};
type Payload = {
  reports: Report[]; total: number; failing: number; stale: number;
  rows_last_pull: number; last_batch: Run[];
  running: { batch: string; started: string | null; scripts: string[] };
  schedule: string; source: { root: string; env_file: string };
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const FILTERS = ["All", "Failing", "Stale", "Today"] as const;
type Filter = (typeof FILTERS)[number];

/** A daily report that has not pulled in this long has missed a run. */
const STALE_HOURS = 36;

function when(iso: string | null) {
  if (!iso) return "never";
  const d = new Date(iso);
  const hours = (Date.now() - d.getTime()) / 36e5;
  if (hours < 1) return "just now";
  if (hours < 24) return `${Math.round(hours)}h ago`;
  if (hours < 48) return "yesterday";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function outcomeTone(r: Report): "good" | "bad" | "warn" | "neutral" {
  if (r.last_outcome === "failed") return "bad";
  if (r.hours_since_success === null) return "neutral";
  if (r.hours_since_success > STALE_HOURS) return "warn";
  if (r.last_outcome === "ok") return "good";
  return "neutral";
}

export default function ReportingPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("All");
  const [busy, setBusy] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [history, setHistory] = useState<{ report: Report; runs: Run[] } | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/awa/reports");
      if (!r.ok) throw new Error(String(r.status));
      setData(await r.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "data")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // While a batch is running, each report lands one at a time — so the page
  // follows along rather than making someone reload to see progress.
  const running = !!data?.running?.batch;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => void load(), 6000);
    return () => clearInterval(t);
  }, [running, load]);

  const reports = useMemo(() => data?.reports ?? [], [data]);
  const shown = useMemo(() => {
    if (filter === "Failing") return reports.filter((r) => r.last_outcome === "failed");
    if (filter === "Stale") {
      return reports.filter(
        (r) => r.hours_since_success === null || r.hours_since_success > STALE_HOURS);
    }
    if (filter === "Today") return reports.filter((r) => r.runs_today);
    return reports;
  }, [reports, filter]);

  async function run(scripts?: string[]) {
    setBusy(scripts ?? reports.map((r) => r.script));
    try {
      const res = await fetch("/api/awa/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // force: pressing "Run now" on a Monday-only report on a Wednesday
        // means run it, not skip it.
        body: JSON.stringify({ scripts, force: !!scripts }),
      });
      const d = await res.json().catch(() => ({}));
      if (res.status === 409) {
        setNote("A run is already in progress — this page will follow it.");
      } else if (!res.ok) {
        setNote(d.detail || "Could not start the run.");
      } else {
        setNote(scripts
          ? `Running ${scripts.length === 1 ? "that report" : `${scripts.length} reports`} now.`
          : "Running every scheduled report now. This takes a few minutes.");
      }
      await load();
    } finally {
      setBusy([]);
    }
  }

  async function openHistory(report: Report) {
    setHistory({ report, runs: [] });
    const r = await fetch(`/api/awa/runs?script=${encodeURIComponent(report.script)}&limit=40`);
    if (r.ok) {
      const d = await r.json();
      setHistory({ report, runs: d.runs ?? [] });
    }
  }

  return (
    <AppShell active="Reporting" me={me} wide>
      <PageHead
        title="Reporting"
        subtitle="CargoWise pulls that build the Excel reports on SharePoint. Run daily by this platform."
        actions={
          <>
            {/* The weekly management report is reporting too - it just builds
                from the tracker rather than from CargoWise, so it lives here
                rather than as its own rail entry. */}
            <Link href="/up-report"
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-ink-2 ring-control transition hover:bg-subtle hover:text-ink focus-ring">
              <Icon name="docs" className="h-3.5 w-3.5" />
              Up Management Report
            </Link>
            <Button icon="sync" variant="primary" spinning={running || busy.length > 0}
                    disabled={running} onClick={() => void run()}>
              {running ? "Running…" : "Run all now"}
            </Button>
            <Button icon="sync" spinning={loading}
                    onClick={() => { setLoading(true); void load(); }}>Refresh</Button>
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Reports" value={loading ? "—" : data?.total ?? 0} icon="analysis" />
        <StatTile label="Failing" value={loading ? "—" : data?.failing ?? 0}
                  icon="alert" tone={(data?.failing ?? 0) > 0 ? "bad" : "good"}
                  hint={(data?.failing ?? 0) > 0 ? "Last run did not finish" : "All clear"} />
        <StatTile label="Stale" value={loading ? "—" : data?.stale ?? 0}
                  icon="clock" tone={(data?.stale ?? 0) > 0 ? "warn" : "good"}
                  hint={`No successful pull in ${STALE_HOURS}h`} />
        <StatTile label="Rows last pull"
                  value={loading ? "—" : (data?.rows_last_pull ?? 0).toLocaleString()}
                  icon="board" tone="info" />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <Pill key={f} active={filter === f} onClick={() => setFilter(f)}>{f}</Pill>
        ))}
        {data?.schedule && (
          <span className="ml-auto flex items-center gap-1.5 text-xs text-ink-3">
            <Icon name="clock" className="h-3.5 w-3.5" />
            {data.schedule}
          </span>
        )}
      </div>

      {note && (
        <p className="mb-3 flex items-start gap-2 rounded-lg bg-infox-bg px-3 py-2 text-xs text-infox">
          <Icon name="sync" className="mt-px h-4 w-4 shrink-0" />
          <span className="flex-1">{note}</span>
          <button onClick={() => setNote("")} aria-label="Dismiss"
                  className="shrink-0 opacity-60 hover:opacity-100">✕</button>
        </p>
      )}

      {loading ? (
        <Section><div className="p-6 text-sm text-ink-2">Loading reports…</div></Section>
      ) : !data ? (
        <Section>
          <EmptyState icon="alert" title="Could not reach the reports"
                      hint="The platform could not read the report state. Check that you have Data Analysis access." />
        </Section>
      ) : shown.length === 0 ? (
        <Section>
          <EmptyState icon="shield" title="Nothing matches"
                      hint={filter === "Failing" ? "No report is currently failing."
                            : filter === "Stale" ? "Every report has pulled recently."
                            : "No report is scheduled for today."} />
        </Section>
      ) : (
        <Section>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-stroke text-left">
                  {["Report", "Status", "Rows", "Last successful pull", "Runs on", ""]
                    .map((h, i) => (
                    <th key={h + i}
                        className={`whitespace-nowrap px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3 ${
                          h === "Rows" ? "text-right" : ""}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const tone = outcomeTone(r);
                  const isBusy = busy.includes(r.script)
                    || (running && (data.running.scripts ?? []).includes(r.script));
                  return (
                    <tr key={r.script}
                        className="border-b border-stroke last:border-0 hover:bg-subtle/50">
                      <td className="px-4 py-3">
                        <button onClick={() => void openHistory(r)}
                                className="text-left focus-ring">
                          <span className="font-medium text-ink">{r.name}</span>
                          {r.last_error && (
                            <span className="mt-0.5 block max-w-lg text-xs leading-snug text-bad">
                              {r.last_error}
                            </span>
                          )}
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {isBusy ? (
                          <Badge tone="info">Running…</Badge>
                        ) : (
                          <Badge tone={tone}>
                            {r.last_outcome === "failed" ? "Failed"
                              : tone === "warn" ? "Stale"
                              : r.last_outcome === "ok" ? "Updated"
                              : r.last_outcome === "skipped" ? "Not today"
                              : "No runs"}
                          </Badge>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-ink-2">
                        {r.last_rows === null ? "—" : r.last_rows.toLocaleString()}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink-2">
                        {when(r.last_success_at)}
                        {r.consecutive_failures > 1 && (
                          <span className="ml-2 text-xs text-bad">
                            {r.consecutive_failures} failures in a row
                          </span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-ink-3">
                        {r.run_days.length === 0
                          ? "Every day"
                          : r.run_days.map((d) => DAYS[d]).join(", ")}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        <Button icon="sync" spinning={isBusy} disabled={running}
                                onClick={() => void run([r.script])}>
                          Run now
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="border-t border-stroke px-4 py-2.5 text-xs text-ink-3">
            Scripts run from <code className="text-ink-2">{data.source.root}</code> on
            this server. A failed report keeps its last good workbook on SharePoint.
          </p>
        </Section>
      )}

      {history && (
        <Modal title={history.report.name} wide
               onClose={() => setHistory(null)}
               footer={
                 <>
                   <span className="mr-auto text-xs text-ink-3">
                     {history.report.script}
                   </span>
                   <Button onClick={() => setHistory(null)}>Close</Button>
                   <Button variant="primary" icon="sync" disabled={running}
                           onClick={() => { void run([history.report.script]); setHistory(null); }}>
                     Run now
                   </Button>
                 </>
               }>
          {history.runs.length === 0 ? (
            <p className="text-sm text-ink-2">Loading the run history…</p>
          ) : (
            <ul className="divide-y divide-stroke">
              {history.runs.map((run_) => (
                <li key={run_.id} className="flex items-start gap-3 py-2.5">
                  <Badge tone={run_.outcome === "ok" ? "good"
                    : run_.outcome === "failed" ? "bad" : "neutral"}>
                    {run_.outcome_label}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ink">
                      {run_.started_at
                        ? new Date(run_.started_at).toLocaleString(undefined, {
                            day: "numeric", month: "short", hour: "2-digit",
                            minute: "2-digit" })
                        : "—"}
                      {run_.rows !== null && (
                        <span className="ml-2 tabular-nums text-ink-3">
                          {run_.rows.toLocaleString()} rows
                        </span>
                      )}
                      {run_.duration_seconds !== null && (
                        <span className="ml-2 text-xs text-ink-3">
                          {run_.duration_seconds < 60
                            ? `${Math.round(run_.duration_seconds)}s`
                            : `${Math.round(run_.duration_seconds / 60)}m`}
                        </span>
                      )}
                    </p>
                    {run_.error && (
                      <p className="mt-0.5 text-xs leading-snug text-bad">{run_.error}</p>
                    )}
                    {run_.triggered_by && (
                      <p className="mt-0.5 text-xs text-ink-3">
                        Started by {run_.triggered_by}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Modal>
      )}
    </AppShell>
  );
}
