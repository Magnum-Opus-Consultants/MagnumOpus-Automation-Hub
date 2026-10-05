"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { Icon, canAccess, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, StatTile, Badge, Button, EmptyState, relativeTime, type Tone,
} from "@/components/ui";

/* Backups, as the servers that run them report it.
 *
 * Every server backs itself up with a nightly systemd job - database dumps and
 * media archives uploaded to Nextcloud. Sentinel reads those jobs over the
 * same SSH access the Servers page uses: when each last ran, whether it
 * worked, and which databases and files it uploaded. That answers the morning
 * question - did last night's backups land? - for every server at once. */

// ── backup jobs (over SSH) ───────────────────────────────────────────────────

type JobRun = {
  started: string; ended: string | null; ok: boolean | null; seconds: number | null;
  items: { name: string; dest: string; size: string; link: string | null }[];
  problems: string[]; warnings: string[]; summary: string; lines: string[];
};
type Job = {
  timer: string; service: string; description: string; schedule: string;
  repeat: "hourly" | "daily" | "weekly" | "monthly" | null; day: number | string | null;
  next_at: string | null; last_start: string | null; last_exit: string | null;
  result: string; active: string;
  status: "ok" | "warn" | "late" | "failed" | "running" | "never";
  runs: JobRun[];
  store: NextcloudSite | null;
};
type JobServer = {
  id: number | null; name: string; company: string; address: string;
  reachable: boolean; detail: string; jobs: Job[];
};
/* Where a company's backups land. `netbird` sites only open with NetBird on. */
type NextcloudSite = { name: string; url: string; folder: string; netbird: boolean };
type JobsData = { checked_at?: string; servers?: JobServer[]; nextcloud?: NextcloudSite[]; error?: string };

function NextcloudLink({ site, compact = false }: { site: NextcloudSite; compact?: boolean }) {
  const title = site.netbird ? `${site.name} - open with NetBird connected` : site.name;
  if (compact) {
    return (
      <a href={site.folder} target="_blank" rel="noreferrer" title={title} onClick={(e) => e.stopPropagation()}
         className="mt-0.5 inline-flex items-center gap-1 text-[12px] font-medium text-brand hover:underline">
        Open in {site.name} ↗
      </a>
    );
  }
  return (
    <a href={site.folder} target="_blank" rel="noreferrer" title={title}
       className="inline-flex items-center gap-1.5 rounded-lg bg-surface px-3 py-1.5 text-sm font-medium text-ink ring-control hover:bg-subtle">
      <Icon name="folder" className="h-4 w-4" /> {site.name}
      {site.netbird && <span className="text-[11px] font-normal text-ink-3">NetBird</span>}
    </a>
  );
}

const JOB_STATUS: Record<Job["status"], { label: string; tone: Tone }> = {
  ok: { label: "Succeeded", tone: "good" },
  warn: { label: "Finished with errors", tone: "warn" },
  late: { label: "Late", tone: "warn" },
  failed: { label: "Failed", tone: "bad" },
  running: { label: "Running now", tone: "info" },
  never: { label: "Never run", tone: "neutral" },
};

// ── formatting ───────────────────────────────────────────────────────────────

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-ZA", {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function fmtDuration(s: number | null): string {
  if (s == null) return "";
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

/* "in 21 h" / "3 h ago" - relativeTime only looks backwards. */
function fromNow(iso: string | null): string {
  if (!iso) return "";
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return relativeTime(iso);
  const h = diff / 3_600_000;
  return h < 1 ? `in ${Math.max(1, Math.round(h * 60))} min` : h < 48 ? `in ${Math.round(h)} h` : `in ${Math.round(h / 24)} days`;
}

function ordinal(n: number): string {
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${s}`;
}

/* The servers keep their own time zones, but every other time on the page is
   local, so the schedule reads in local time too - taken from the next run
   ("Daily 04:00", not "Daily 02:00 UTC"). */
function localSchedule(j: Job): string {
  if (!j.schedule) return "—";
  if (!j.next_at || !j.repeat) return j.schedule;
  const t = new Date(j.next_at).toLocaleTimeString("en-ZA", { hour: "2-digit", minute: "2-digit" });
  if (j.repeat === "daily") return `Daily ${t}`;
  if (j.repeat === "monthly" && typeof j.day === "number") return `Monthly, ${ordinal(j.day)} at ${t}`;
  if (j.repeat === "weekly" && j.day) return `Weekly, ${j.day} at ${t}`;
  if (j.repeat === "hourly") return "Hourly";
  return j.schedule;
}

/* What a run uploaded, in a few words. */
function uploaded(run: JobRun | undefined): string {
  if (!run) return "—";
  if (run.items.length === 0) {
    if (run.ok === false) return "Nothing uploaded";
    return run.summary || (run.lines.length ? `${run.lines.length} log lines` : "Ran - nothing logged");
  }
  const names = run.items.map((i) => i.name);
  const what = names.length <= 2 ? names.join(", ") : `${names.slice(0, 2).join(", ")} +${names.length - 2} more`;
  return `${run.items.length} uploaded · ${what}`;
}

function runTone(r: JobRun): string {
  if (r.ok === false) return "bg-bad";
  if (r.problems.length) return "bg-warnx";
  if (r.ok) return "bg-good";
  return "bg-ink-3";
}

// ── page ─────────────────────────────────────────────────────────────────────

export default function BackupsPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [jobs, setJobs] = useState<JobsData | null>(null);
  const [loading, setLoading] = useState(false);
  // Who is being checked, known at once - shown while the SSH checks run.
  const [waitingOn, setWaitingOn] = useState<{ name: string; company: string; address: string }[] | null>(null);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    const q = refresh ? "?refresh=1" : "";
    if (!refresh) {
      fetch("/api/backups/jobs?list=1")
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => d?.servers && setWaitingOn(d.servers))
        .catch(() => {});
    }
    const jobsReq = fetch(`/api/backups/jobs${q}`)
      .then(async (r) => (r.status === 401 ? null : setJobs(await r.json())))
      .catch(() => setJobs({ error: "Could not reach Sentinel's server." }));
    await jobsReq;
    setLoading(false);
  }, []);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "servers")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // load() only sets state after awaiting its fetches; the rule cannot see
    // through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const servers = jobs?.servers ?? [];
  const withJobs = servers.filter((s) => s.reachable && s.jobs.length > 0);
  const noJobs = servers.filter((s) => s.reachable && s.jobs.length === 0);
  const unreachable = servers.filter((s) => !s.reachable);
  const allJobs = withJobs.flatMap((s) => s.jobs);
  const healthy = allJobs.filter((j) => j.status === "ok" || j.status === "running").length;
  const attention = allJobs.length - healthy;

  return (
    <AppShell active="Backups" me={me} wide>
      <PageHead
        title="Backups"
        subtitle="The backup jobs on each server: when they last ran, whether they worked and what they uploaded."
        actions={
          <>
            {(jobs?.nextcloud ?? []).map((site) => <NextcloudLink key={site.url} site={site} />)}
            <Button icon="sync" spinning={loading} disabled={loading} onClick={() => load(true)}>Refresh</Button>
          </>
        }
      />

      {jobs === null && <LoadingJobs servers={waitingOn} />}
      {jobs?.error && (
        <EmptyState icon="alert" title="Couldn't check the backup jobs" hint={jobs.error}
                    action={<Button icon="sync" spinning={loading} onClick={() => load(true)}>Try again</Button>} />
      )}

      {jobs && !jobs.error && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Backup jobs" value={allJobs.length} icon="shield"
                      hint={`on ${withJobs.length} server${withJobs.length === 1 ? "" : "s"}`} />
            <StatTile label="Last run worked" value={healthy} tone="good" hint="most recent run succeeded" />
            <StatTile label="Need attention" value={attention} tone={attention ? "bad" : "neutral"}
                      hint={attention ? "failed, late or with errors" : "none"} />
            <StatTile label="Not checked" value={unreachable.length} tone={unreachable.length ? "warn" : "neutral"}
                      hint={unreachable.length ? "no SSH access from here" : "every server answered"} />
          </div>

          <div className="space-y-4">
            {withJobs.map((s) => <ServerJobs key={s.address} server={s} />)}

            {noJobs.length > 0 && (
              <Section title="No backup jobs found">
                <div className="px-4 py-3">
                  <p className="mb-2 text-[13px] text-warnx">
                    These servers answered, but have no backup timer - nothing on them is being backed up.
                  </p>
                  <ul className="space-y-1 text-sm">
                    {noJobs.map((s) => (
                      <li key={s.address} className="flex flex-wrap items-baseline gap-x-2">
                        <span className="font-medium text-ink">{s.name}</span>
                        <span className="text-[12px] text-ink-3">{s.company} · {s.address}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </Section>
            )}

            {unreachable.length > 0 && (
              <Section title="Couldn't check">
                <ul className="divide-y divide-stroke">
                  {unreachable.map((s) => (
                    <li key={s.address} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-4 py-2.5">
                      <span>
                        <span className="text-sm font-medium text-ink">{s.name}</span>
                        <span className="ml-2 text-[12px] text-ink-3">{s.company} · {s.address}</span>
                      </span>
                      <span className="text-[12px] text-ink-3">{s.detail}</span>
                    </li>
                  ))}
                </ul>
              </Section>
            )}
          </div>

          {jobs.checked_at && (
            <p className="mt-3 text-[12px] text-ink-3">
              Checked {relativeTime(jobs.checked_at)} over SSH · read-only (systemd status and job logs).
            </p>
          )}
        </>
      )}

    </AppShell>
  );
}

/* While the servers are being checked: one card per company with its servers
   named and placeholder rows pulsing, so it is clear what the page is waiting
   for. Before the list arrives (a moment), the cards are unnamed. */
function LoadingJobs({ servers }: { servers: { name: string; company: string; address: string }[] | null }) {
  const groups = new Map<string, { name: string; address: string }[]>();
  for (const s of servers ?? []) {
    const key = s.company || "Other servers";
    groups.set(key, [...(groups.get(key) ?? []), s]);
  }
  const cards: [string | null, { name: string; address: string }[]][] =
    groups.size ? [...groups.entries()] : [[null, []], [null, []]];
  const bar = "animate-pulse rounded bg-stroke";
  return (
    <div aria-busy="true" aria-live="polite">
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="rounded-lg bg-surface px-4 py-3.5 ring-panel">
            <div className={`h-3 w-24 ${bar}`} />
            <div className={`mt-3 h-6 w-10 ${bar}`} />
          </div>
        ))}
      </div>
      <div className="space-y-4">
        {cards.map(([company, list], i) => (
          <Section key={company ?? i}
                   title={company ?? undefined}
                   right={
                     <span className="flex items-center gap-1.5 text-xs text-ink-3">
                       <Icon name="sync" className="h-3.5 w-3.5 animate-spin" />
                       {list.length
                         ? `Checking ${list.length} server${list.length === 1 ? "" : "s"}…`
                         : "Checking…"}
                     </span>
                   }>
            <ul className="divide-y divide-stroke">
              {(list.length ? list : [null, null]).map((s, j) => (
                <li key={s?.address ?? j} className="flex items-center gap-4 px-4 py-3">
                  <div className="min-w-0 shrink sm:w-80 sm:shrink-0">
                    {s ? (
                      <>
                        <div className="truncate text-sm font-medium text-ink">{s.name}</div>
                        <div className="text-[12px] text-ink-3">{s.address}</div>
                      </>
                    ) : (
                      <>
                        <div className={`h-3.5 w-44 ${bar}`} />
                        <div className={`mt-2 h-3 w-24 ${bar}`} />
                      </>
                    )}
                  </div>
                  <div className={`hidden h-3 w-24 sm:block ${bar}`} />
                  <div className={`hidden h-3 flex-1 md:block ${bar}`} />
                  <div className={`ml-auto h-5 w-20 rounded-md ${bar}`} />
                </li>
              ))}
            </ul>
          </Section>
        ))}
      </div>
    </div>
  );
}

/* One server's backup jobs, one row each; a row opens to its recent runs. */
function ServerJobs({ server }: { server: JobServer }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Section title={server.name}
             right={<span className="text-xs text-ink-3">{server.company} · {server.address}</span>}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="border-b border-stroke text-left text-[11px] font-medium uppercase tracking-wide text-ink-3">
              <th className="px-4 py-2 font-medium">Job</th>
              <th className="px-3 py-2 font-medium">Schedule</th>
              <th className="px-3 py-2 font-medium">Last run</th>
              <th className="px-3 py-2 font-medium">Uploaded</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="w-10 px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {server.jobs.map((j) => {
              const st = JOB_STATUS[j.status];
              const last = j.runs[0];
              const isOpen = open === j.timer;
              return (
                <Fragment key={j.timer}>
                  <tr onClick={() => setOpen(isOpen ? null : j.timer)}
                      className={`cursor-pointer border-b border-stroke align-top hover:bg-subtle/50 ${isOpen ? "bg-subtle/50" : ""}`}>
                    <td className="px-4 py-2.5">
                      <div className="font-medium text-ink">{j.description}</div>
                      <div className="font-mono text-[11px] text-ink-3">{j.service}</div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="text-ink" title={j.schedule ? `Server time: ${j.schedule}` : undefined}>
                        {localSchedule(j)}
                      </div>
                      {j.next_at && <div className="text-[12px] text-ink-3">next {fromNow(j.next_at)}</div>}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="text-ink">{relativeTime(last?.started ?? j.last_start)}</div>
                      <div className="text-[12px] text-ink-3">
                        {fmtWhen(last?.started ?? j.last_start)}
                        {last?.seconds != null && ` · took ${fmtDuration(last.seconds)}`}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-[13px] text-ink-2">
                      <div>
                        {uploaded(last)}
                        {last && last.warnings.length > 0 && (
                          <span className="text-warnx"> · {last.warnings.length} warning{last.warnings.length === 1 ? "" : "s"}</span>
                        )}
                      </div>
                      {j.store && <NextcloudLink site={j.store} compact />}
                    </td>
                    <td className="px-3 py-2.5"><Badge tone={st.tone}>{st.label}</Badge></td>
                    <td className="px-3 py-2.5 text-ink-3">
                      <Icon name="chevron" className={`h-4 w-4 transition-transform ${isOpen ? "" : "-rotate-90"}`} />
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-stroke bg-subtle/30">
                      <td colSpan={6} className="px-4 py-3"><JobRuns job={j} /></td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

/* A strip of the last runs - green worked, red failed, amber finished with
   errors - and the detail of whichever run is picked (the latest first). */
function JobRuns({ job }: { job: Job }) {
  const [pick, setPick] = useState(0);
  const [showLog, setShowLog] = useState(false);
  if (job.runs.length === 0) {
    return <p className="text-[13px] text-ink-3">No runs in the server&apos;s log for the last 15 days.</p>;
  }
  const run = job.runs[Math.min(pick, job.runs.length - 1)];
  const outcome = run.ok === false ? "Failed" : run.problems.length ? "Finished with errors" : run.ok ? "Succeeded" : "Unknown";
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-3">
          Last {job.runs.length} run{job.runs.length === 1 ? "" : "s"}
        </span>
        {/* Oldest on the left, like a timeline. */}
        <div className="flex items-center gap-1">
          {[...job.runs].reverse().map((r) => {
            const i = job.runs.indexOf(r);
            return (
              <button key={r.started} onClick={(e) => { e.stopPropagation(); setPick(i); setShowLog(false); }}
                      title={`${fmtWhen(r.started)} - ${r.ok === false ? "failed" : r.problems.length ? "finished with errors" : r.ok ? "succeeded" : "unknown"}`}
                      aria-label={`Run ${fmtWhen(r.started)}`}
                      className={`h-5 w-3.5 rounded-sm ${runTone(r)} ${i === pick ? "ring-2 ring-brand ring-offset-1 ring-offset-surface" : "opacity-80 hover:opacity-100"}`} />
            );
          })}
        </div>
      </div>

      <div className="rounded-lg bg-surface p-3 ring-1 ring-stroke">
        <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-sm font-semibold text-ink">{fmtWhen(run.started)}</span>
          <span className={`text-[13px] font-medium ${run.ok === false ? "text-bad" : run.problems.length ? "text-warnx" : "text-good"}`}>
            {outcome}
          </span>
          {run.seconds != null && <span className="text-[12px] text-ink-3">took {fmtDuration(run.seconds)}</span>}
        </div>

        {run.summary && <p className="mb-2 text-[13px] text-ink-2">{run.summary}</p>}

        {run.problems.length > 0 && (
          <ul className="mb-2 space-y-0.5">
            {run.problems.map((p, i) => <li key={i} className="font-mono text-[12px] text-bad">{p}</li>)}
          </ul>
        )}

        {run.warnings.length > 0 && (
          <ul className="mb-2 space-y-0.5">
            {run.warnings.map((w, i) => <li key={i} className="font-mono text-[12px] text-warnx">{w}</li>)}
          </ul>
        )}

        {run.items.length > 0 && (
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-ink-3">
                <th className="py-1 pr-3 font-medium">Database / files</th>
                <th className="py-1 pr-3 font-medium">Uploaded to</th>
                <th className="py-1 text-right font-medium">Size</th>
              </tr>
            </thead>
            <tbody>
              {run.items.map((it) => (
                <tr key={it.name + it.dest} className="border-t border-stroke align-top">
                  <td className="py-1.5 pr-3 font-medium text-ink">{it.name}</td>
                  <td className="break-all py-1.5 pr-3 text-ink-2">
                    {it.link ? (
                      <a href={it.link} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                         title={`Open this backup's folder in ${job.store?.name ?? "Nextcloud"}`}
                         className="text-brand hover:underline">{it.dest}</a>
                    ) : it.dest}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-ink-2">{it.size}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {run.lines.length > 0 && (
          <div className="mt-2">
            <button onClick={(e) => { e.stopPropagation(); setShowLog(!showLog); }}
                    className="text-[12px] font-medium text-brand hover:underline">
              {showLog ? "Hide the log" : `Show the log (${run.lines.length} line${run.lines.length === 1 ? "" : "s"})`}
            </button>
            {showLog && (
              <pre className="mt-1.5 max-h-72 overflow-auto rounded-md bg-subtle px-3 py-2 text-[11.5px] leading-relaxed text-ink-2">
                {run.lines.join("\n")}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
