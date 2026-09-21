"use client";

/**
 * The Up Management Report — as a dashboard.
 *
 * Written to be understood on the first pass by somebody who has never seen
 * the report before. That ruled a lot out:
 *
 *   - **It opens with a verdict, not a metric.** One sentence saying what is
 *     going on ("All 4 open jobs are late — the oldest by 141 days"), then the
 *     two or three things to do about it. Both come from the backend, so the
 *     words are part of the report rather than a front-end flourish.
 *   - **Plain words.** "Still to do", not "Outstanding". "Late work", not
 *     "Delivery risk". "Problems to fix", not "Risk register". The report's
 *     own vocabulary — delivery pressure, sprints, the five-step scale — is
 *     real and stays in the PDF, but it lives at the bottom of this page
 *     under "How this is worked out" where it explains itself.
 *   - **Nothing is shown twice, and nothing empty is shown at all.** A card
 *     with no data is not a card: its one useful sentence becomes an action in
 *     the banner. The stream donut and the focus heatmap appear the moment
 *     there is something to draw.
 *   - **Three numbers, not seven tiles.** Done, still to do, finished this
 *     week. Counts of zero (blocked, tickets) say nothing worth a tile.
 *
 * Nothing here is typed in: every figure comes from projects, tasks, activity,
 * tickets, risks and service agreements, so if a number looks wrong the fix is
 * in the tracker. The PDF button gives the V3 Word document, rendered to the
 * millimetre, for sending upstairs — one computation behind both, so they can
 * never disagree.
 */
import { useCallback, useEffect, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import { AppShell, PageHead, Button } from "@/components/ui";
import {
  VizTokens, ChartCard, Donut, StackedBars, Bars, ScaleMeter, Heatmap,
  SERIES, STATUS,
} from "@/components/charts";

type Risk = {
  id: number | null; source: string; description: string; kind: string;
  owner: string; severity: string; severity_display: string;
  mitigation: string; status_display: string; client: string; project: string;
  review_overdue: boolean; score: number; days_late: number;
};
type Dash = {
  header: {
    title: string; week_start: string; week_ending: string;
    issue_number: string; report_version: string; generated_at: string;
  };
  verdict: {
    tone: "good" | "warn" | "bad"; headline: string; actions: string[];
    scale_label: string; scale_reason: string;
  };
  pressure: {
    value: string; label: string; score: number; reason: string;
    signals: { open: number; overdue: number; blocked: number;
               committed_hours: number; capacity_hours: number };
  };
  totals: {
    clients: number; completed: number; outstanding: number;
    closed_this_week: number; blocked: number; risks: number;
    severe_risks: number;
  };
  tickets: { open: number; closed: number; raised_this_week: number };
  streams: { key: string; label: string; total: number;
             completed: number; outstanding: number }[];
  clients: { client: string; completed: number; outstanding: number;
             overdue: number; blocked: number; total: number }[];
  severity: { severity: string; count: number }[];
  risks: Risk[];
  ageing: { band: string; count: number }[];
  oldest_overdue_days: number;
  focus: {
    people: { person_id: number; person: string; initials: string;
              items: number; hours: number; over_capacity: boolean }[];
    staff_rows: { bucket: string; items: number;
                  cells: { person_id: number; share_pct: number | null;
                           items: number | null; hours: number | null }[] }[];
    unassigned_items: number;
  };
  financial: {
    bucket: string; next_invoice_date: string | null; sla_active: boolean;
    sla_summary: string; monthly_fee: number | null;
    renewal_date: string | null; has_agreement: boolean;
  }[];
  next_week: {
    rows: { bucket: string; responsibility: string;
            items: { title: string; due: string | null; owner: string;
                     stream: string; is_overdue: boolean }[] }[];
  };
  notes: {
    unclassified_tasks: number; automated_projects_excluded: number;
    projects_without_client: number; projects_without_dates: number;
  };
  how_it_is_derived: string[];
  weeks_available: string[];
  is_current_week: boolean;
};

const PRESSURE = ["Depleted", "Inefficient", "Cruising",
                  "Maintaining Momentum", "Pro-Active & Visionary Mindset"];

/* Severity is state, so it wears the reserved status scale — and always with
   its name beside it. */
const SEVERITY_TONE: Record<string, string> = {
  critical: STATUS.critical, high: STATUS.serious,
  medium: STATUS.warning, low: STATUS.good,
};

/* Plain words for the severities, so a reader does not have to rank them. */
const SEVERITY_WORD: Record<string, string> = {
  critical: "Urgent", high: "Serious", medium: "Worth a look", low: "Minor",
};

export default function UpReportPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [d, setD] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [showHow, setShowHow] = useState(false);
  const [week, setWeek] = useState("");

  const load = useCallback(async (w: string) => {
    try {
      const q = w ? `?week=${encodeURIComponent(w)}` : "";
      const r = await fetch(`/api/management/up-dashboard${q}`);
      setD(r.ok ? await r.json() : null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "tasks")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    void load("");
  }, [load]);

  const pdfHref = `/api/management/up-report.pdf${
    week ? `?week=${encodeURIComponent(week)}` : ""}`;

  const total = d ? d.totals.completed + d.totals.outstanding : 0;
  const donePct = total ? Math.round((d!.totals.completed / total) * 100) : 0;

  // Cards that would have nothing to draw are not drawn — the banner's action
  // list already says what to do to fill them in.
  const bandsUsed = d ? d.ageing.filter((a) => a.count > 0).length : 0;
  const scheduled = d ? d.next_week.rows.filter((r) => r.items.length > 0) : [];
  const idle = d ? d.next_week.rows.filter((r) => r.items.length === 0) : [];
  const agreements = d ? d.financial.filter((f) => f.has_agreement) : [];
  const hasStreams = (d?.streams.length ?? 0) >= 2;
  const hasFocus = (d?.focus.people.length ?? 0) > 0;

  // Highlights Reporting in the rail: this report is reached from there,
  // and a page that lights up nothing in the sidebar reads as lost.
  return (
    <AppShell active="Reporting" me={me} wide>
      <VizTokens />
      <PageHead
        title="Up Management Report"
        subtitle={d
          ? `Week ending ${d.header.week_ending} · worked out from the tracker, nothing typed in`
          : "Worked out from the tracker every week. Nothing on it is filled in by hand."}
        actions={
          <>
            {/* One filter for the whole page — everything below redraws
                against the same week. */}
            {(d?.weeks_available?.length ?? 0) > 0 && (
              <select value={week}
                      onChange={(e) => { setWeek(e.target.value); setLoading(true); void load(e.target.value); }}
                      className="h-8 rounded-lg bg-surface px-2 text-xs text-ink ring-control focus-ring">
                <option value="">This week</option>
                {d!.weeks_available.map((w) => <option key={w} value={w}>Week of {w}</option>)}
              </select>
            )}
            <a href={pdfHref} target="_blank" rel="noreferrer"
               className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-ink-2 ring-control transition hover:bg-subtle focus-ring">
              <Icon name="docs" className="h-3.5 w-3.5" />
              View document
            </a>
            <a href={`${pdfHref}${pdfHref.includes("?") ? "&" : "?"}download=1`}
               className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-brand px-2.5 text-xs font-semibold text-white transition hover:bg-brand-hover focus-ring">
              <Icon name="upload" className="h-3.5 w-3.5" />
              Download PDF
            </a>
            <Button icon="sync" spinning={loading}
                    onClick={() => { setLoading(true); void load(week); }}>Refresh</Button>
          </>
        }
      />

      {loading && !d ? (
        <div className="rounded-xl bg-surface p-6 ring-panel">
          <p className="text-sm text-ink-2">Working out this week&rsquo;s report…</p>
        </div>
      ) : !d ? (
        <div className="rounded-xl bg-surface p-6 ring-panel">
          <p className="text-sm text-ink-2">Could not build the report.</p>
        </div>
      ) : (
        // Held at reduced opacity while refetching rather than flashing a
        // skeleton, so nothing on the page jumps.
        <div className={`viz space-y-4 transition-opacity ${loading ? "opacity-60" : ""}`}>

          {/* ── 1. What is going on, in one sentence ──────────────────── */}
          <Verdict v={d.verdict} />

          {/* ── 2. The three numbers that matter ──────────────────────── */}
          <section className="grid gap-3 sm:grid-cols-3">
            <Big label="Done" value={d.totals.completed}
                 sub={`${donePct}% of all ${total} jobs`} />
            <Big label="Still to do" value={d.totals.outstanding}
                 tone={d.pressure.signals.overdue > 0 ? "bad" : undefined}
                 sub={d.pressure.signals.overdue === 0
                   ? "none of them late"
                   : d.pressure.signals.overdue === d.totals.outstanding
                     ? `every one is late, worst by ${d.oldest_overdue_days} days`
                     : `${d.pressure.signals.overdue} of them late, worst by ${d.oldest_overdue_days} days`} />
            <Big label="Finished this week" value={d.totals.closed_this_week}
                 sub={`across ${d.totals.clients} clients`} />
          </section>

          {/* ── 3. Who the work belongs to ────────────────────────────── */}
          <section className={`grid gap-4 ${hasStreams || hasFocus
            ? "xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]" : ""}`}>
            <ChartCard
              title="Jobs per client"
              hint="Blue is finished, orange is still open."
              legend={[{ label: "Finished", color: SERIES[0] },
                       { label: "Still open", color: SERIES[1] }]}
              empty={d.clients.length === 0 ? "No client work this week." : undefined}
              table={{
                head: ["Client", "Finished", "Still open", "Late", "Total"],
                rows: d.clients.map((c) => [c.client, c.completed, c.outstanding,
                                            c.overdue, c.total]),
              }}>
              <StackedBars
                series={[{ label: "Finished", color: SERIES[0] },
                         { label: "Still open", color: SERIES[1] }]}
                rows={d.clients.map((c) => ({
                  label: c.client,
                  values: [c.completed, c.outstanding],
                  note: c.overdue > 0 ? `${c.overdue} late` : undefined,
                }))} />
            </ChartCard>

            {(hasStreams || hasFocus) && (
              <div className="grid gap-4">
                {hasStreams && (
                  <ChartCard
                    title="What kind of work it is"
                    hint="Website, app, API, support and internal work as a share of the total."
                    table={{
                      head: ["Kind", "Finished", "Still open", "Total"],
                      rows: d.streams.map((s) => [s.label, s.completed,
                                                  s.outstanding, s.total]),
                    }}>
                    <Donut centreLabel="jobs" centreValue={total}
                           data={d.streams.map((s) => ({ label: s.label, value: s.total }))} />
                  </ChartCard>
                )}
                {hasFocus && (
                  <ChartCard
                    title="Who worked on what"
                    hint="Each person's week across clients — darker where more of their time went."
                    table={{
                      head: ["Client", ...d.focus.people.map((p) => p.person)],
                      rows: d.focus.staff_rows.map((r) => [
                        r.bucket,
                        ...r.cells.map((c) => c.share_pct === null ? "—" : `${c.share_pct}%`),
                      ]),
                    }}>
                    <Heatmap
                      columns={d.focus.people.map((p) => ({
                        key: String(p.person_id), label: p.initials,
                        title: `${p.person} — ${p.items} jobs, ${p.hours}h`,
                      }))}
                      rows={d.focus.staff_rows.map((r) => ({
                        label: r.bucket,
                        cells: r.cells.map((c) => ({
                          key: String(c.person_id), value: c.share_pct,
                        })),
                      }))} />
                  </ChartCard>
                )}
              </div>
            )}
          </section>

          {/* Only when the lateness actually spreads across bands — one band
              is one bar, which the "Still to do" number already said. */}
          {bandsUsed > 1 && (
            <ChartCard
              title="How late the late work is"
              table={{
                head: ["Days late", "Jobs"],
                rows: d.ageing.map((a) => [a.band, a.count]),
              }}>
              <Bars ordinal rows={d.ageing.map((a) => ({ label: a.band, value: a.count }))} />
            </ChartCard>
          )}

          {/* ── 4. Problems, worst first ──────────────────────────────── */}
          {d.risks.length > 0 && (
            <section className="overflow-hidden rounded-xl bg-surface ring-panel">
              <header className="flex flex-wrap items-end justify-between gap-4 border-b border-stroke px-5 py-3">
                <div>
                  <h3 className="text-sm font-semibold text-ink">
                    Problems to fix ({d.risks.length})
                  </h3>
                  <p className="mt-0.5 text-xs text-ink-3">
                    Worst first. Anything somebody logged, plus what the
                    platform spotted in the tracker by itself.
                  </p>
                </div>
                <SeverityStrip rows={d.severity} total={d.totals.risks} />
              </header>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] text-sm">
                  <thead>
                    <tr className="border-b border-stroke text-left">
                      {["How bad", "What is wrong", "Type", "Who is on it"].map((h) => (
                        <th key={h} className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {d.risks.map((r, i) => (
                      <tr key={r.id ?? `o${i}`} className="border-b border-stroke/60 last:border-0">
                        <td className="px-4 py-2">
                          <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-ink">
                            <span aria-hidden className="h-2.5 w-2.5 rounded-full"
                                  style={{ background: SEVERITY_TONE[r.severity] }} />
                            {SEVERITY_WORD[r.severity] ?? r.severity_display}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-ink">{r.description}</td>
                        <td className="px-4 py-2 text-xs text-ink-2">{r.kind}</td>
                        <td className={`px-4 py-2 text-xs ${r.owner ? "text-ink-2" : "text-bad"}`}>
                          {r.owner || "Nobody"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* ── 5. What is coming, and the money ──────────────────────── */}
          <section className="grid gap-4 xl:grid-cols-2">
            <Card title="Due next week"
                  hint="Read off the due dates in the tracker.">
              {scheduled.length === 0 ? (
                <p className="px-5 py-6 text-sm text-ink-2">
                  Nothing is dated for next week.
                </p>
              ) : (
                <ul className="divide-y divide-stroke">
                  {scheduled.map((r) => (
                    <li key={r.bucket} className="px-5 py-2.5">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="text-sm font-medium text-ink">{r.bucket}</span>
                        {r.responsibility !== "unassigned" && (
                          <span className="text-xs text-ink-3">{r.responsibility}</span>
                        )}
                      </div>
                      <ul className="mt-1 space-y-0.5">
                        {r.items.map((it, i) => (
                          <li key={i} className="flex flex-wrap items-baseline gap-2 text-xs">
                            <span className={it.is_overdue ? "text-bad" : "text-ink-2"}>
                              {it.title}
                            </span>
                            {it.due && (
                              <span className="text-ink-3">
                                due {it.due}{it.is_overdue && " · already late"}
                              </span>
                            )}
                            {it.owner && <span className="text-ink-3">· {it.owner}</span>}
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              )}
              {idle.length > 0 && (
                <p className="border-t border-stroke px-5 py-2.5 text-xs text-ink-3">
                  Nothing dated for {idle.map((r) => r.bucket).join(", ")}.
                </p>
              )}
            </Card>

            <Card title="Fees and renewals"
                  hint="Read off the service agreements on file.">
              {agreements.length === 0 ? (
                <p className="px-5 py-6 text-sm leading-relaxed text-ink-2">
                  No client has a service agreement on file, so there is no fee,
                  invoice date or renewal to report. Add one against a client
                  and it appears here.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[520px] text-sm">
                    <thead>
                      <tr className="border-b border-stroke text-left">
                        {["Client", "Monthly fee", "Next invoice", "SLA", "Renewal"].map((h) => (
                          <th key={h} className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {agreements.map((f) => (
                        <tr key={f.bucket} className="border-b border-stroke/60 last:border-0">
                          <td className="px-4 py-2 text-ink">{f.bucket}</td>
                          <td className="px-4 py-2 text-xs tabular-nums text-ink-2">
                            R {f.monthly_fee ?? 0}
                          </td>
                          <td className="px-4 py-2 text-xs tabular-nums text-ink-2">
                            {f.next_invoice_date || "Not scheduled"}
                          </td>
                          <td className="px-4 py-2 text-xs text-ink-2">
                            {f.sla_active ? f.sla_summary || "Active" : "Inactive"}
                          </td>
                          <td className="px-4 py-2 text-xs tabular-nums text-ink-2">
                            {f.renewal_date || "Not scheduled"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </section>

          {/* ── 6. The report's own vocabulary, explained, out of the way ─ */}
          <div className="rounded-xl bg-surface px-4 py-3 ring-panel">
            <button onClick={() => setShowHow((v) => !v)}
                    className="flex w-full items-center gap-2 text-left text-xs font-semibold text-ink-2 focus-ring">
              <Icon name="chevron"
                    className={`h-3.5 w-3.5 transition-transform ${showHow ? "rotate-180" : "rotate-90"}`} />
              How this is worked out, and what the report calls things
            </button>
            {showHow && (
              <div className="mt-3 space-y-4">
                <div className="rounded-lg bg-subtle/50 px-4 py-3">
                  <p className="text-xs font-semibold text-ink">
                    Delivery pressure &mdash; the report&rsquo;s five-step scale
                  </p>
                  <p className="mb-3 mt-0.5 text-xs text-ink-3">
                    Section 3 of the V3 document. It is on the PDF, so it is
                    explained here rather than dropped.
                  </p>
                  <ScaleMeter steps={PRESSURE} activeIndex={d.pressure.score}
                              reason={d.pressure.reason} />
                  <p className="mt-2 text-xs text-ink-2">
                    {d.pressure.signals.committed_hours} of{" "}
                    {d.pressure.signals.capacity_hours} hours are committed this
                    week
                    {d.pressure.signals.committed_hours === 0
                      && " — no open job carries an estimate yet, so this is what the tracker knows rather than what the team is doing"}.
                  </p>
                </div>
                <ul className="space-y-1 pl-1 text-xs leading-relaxed text-ink-3">
                  {d.how_it_is_derived.map((line, i) => <li key={i}>· {line}</li>)}
                  <li>· {d.notes.automated_projects_excluded} automated project(s) are
                    left out of every figure — those are report syncs, not real jobs.</li>
                  <li>· Support tickets: {d.tickets.open} open,{" "}
                    {d.tickets.closed} closed, {d.tickets.raised_this_week} raised
                    this week. {d.totals.blocked} job(s) blocked.</li>
                  <li>· The PDF and this page come from one calculation, so they
                    can never disagree about a number.</li>
                  <li>· Nothing here is entered by hand. Change the tracker and
                    the report follows.</li>
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}

/**
 * The banner: what is going on, then what to do about it.
 *
 * Both the sentence and the actions are computed in the backend, so this
 * component only decides how loud to be about them.
 */
function Verdict({ v }: { v: Dash["verdict"] }) {
  // A backend that predates the verdict simply has no banner, rather than
  // taking the whole page down with it.
  if (!v?.tone) return null;
  const tone = {
    good: { ring: "ring-good/25", bg: "bg-good-bg", icon: "check",
            text: "text-good" },
    warn: { ring: "ring-warnx/25", bg: "bg-warnx-bg", icon: "alert",
            text: "text-warnx" },
    bad:  { ring: "ring-bad/25", bg: "bg-bad-bg", icon: "alert",
            text: "text-bad" },
  }[v.tone];
  return (
    <section className={`rounded-xl px-5 py-4 ring-1 ring-inset ${tone.bg} ${tone.ring}`}>
      <div className="flex items-start gap-3">
        <Icon name={tone.icon} className={`mt-0.5 h-5 w-5 shrink-0 ${tone.text}`} />
        <div className="min-w-0">
          <p className="text-lg font-semibold leading-snug text-ink">
            {v.headline}
          </p>
          {v.actions.length > 0 && (
            <>
              <p className="mt-2.5 text-xs font-semibold uppercase tracking-wide text-ink-3">
                What to do about it
              </p>
              <ol className="mt-1 space-y-1">
                {v.actions.map((a, i) => (
                  <li key={i} className="flex gap-2 text-sm leading-snug text-ink-2">
                    <span className="tabular-nums text-ink-3">{i + 1}.</span>
                    <span>{a}</span>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

/** One number, said big, with a plain line underneath. */
function Big({ label, value, sub, tone }:
             { label: string; value: number; sub?: string; tone?: "bad" }) {
  return (
    <div className="rounded-xl bg-surface px-5 py-4 ring-panel">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-3">
        {label}
      </p>
      {/* Proportional figures on a large standalone number — tabular digits
          make it look loose at this size. */}
      <p className="mt-1 text-4xl font-semibold leading-none text-ink">{value}</p>
      {sub && (
        <p className={`mt-1.5 text-xs ${tone === "bad" ? "text-bad" : "text-ink-3"}`}>
          {sub}
        </p>
      )}
    </div>
  );
}

/**
 * The severity mix as one strip, sat in the problem card's header.
 *
 * Six rows do not need a chart beside them, but the mix is worth seeing at a
 * glance — so it rides along with the table it describes instead of taking a
 * card of its own. Every segment is labelled, so the status colour never
 * carries the meaning alone.
 */
function SeverityStrip({ rows, total }:
                       { rows: { severity: string; count: number }[];
                         total: number }) {
  const shown = rows.filter((r) => r.count > 0);
  if (shown.length < 2) return null;
  return (
    <div className="min-w-56 flex-1 sm:max-w-xs">
      <div className="flex h-2 items-stretch overflow-hidden rounded-sm">
        {shown.map((r, i) => (
          <div key={r.severity}
               style={{
                 flexGrow: r.count, background: SEVERITY_TONE[r.severity],
                 // 2px of surface between fills, not a border.
                 marginRight: i < shown.length - 1 ? 2 : 0,
               }}
               title={`${SEVERITY_WORD[r.severity] ?? r.severity}: ${r.count} of ${total}`} />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap justify-end gap-x-3 gap-y-0.5">
        {shown.map((r) => (
          <span key={r.severity} className="flex items-center gap-1 text-[11px] text-ink-2">
            <span aria-hidden className="h-2 w-2 rounded-full"
                  style={{ background: SEVERITY_TONE[r.severity] }} />
            {r.count} {(SEVERITY_WORD[r.severity] ?? r.severity).toLowerCase()}
          </span>
        ))}
      </div>
    </div>
  );
}

function Card({ title, hint, children }:
              { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl bg-surface ring-panel">
      <header className="border-b border-stroke px-5 py-3">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {hint && <p className="mt-0.5 text-xs leading-snug text-ink-3">{hint}</p>}
      </header>
      {children}
    </section>
  );
}
