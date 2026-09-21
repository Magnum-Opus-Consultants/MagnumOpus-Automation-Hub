"use client";

/**
 * The weekly management report.
 *
 * Built to a brief that asked for a holistic weekly view of client delivery
 * and departmental capacity, in eight named sections, and was explicit that it
 * must "drive execution — not merely record activity".
 *
 * So the page is not a document. Escalations come first because that is what a
 * manager is reading for; actions can be raised, acknowledged and closed from
 * here; priorities can be ticked off; and "Notify owners" tells the responsible
 * people what is theirs and asks them to confirm the date.
 */
import { useCallback, useEffect, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, StatTile, Badge, Button, EmptyState, Modal,
  TextInput, AreaInput, SelectInput, Pill,
} from "@/components/ui";

type Choice = { value: string; label: string };
type Person = { id: number; name: string };
type Action = {
  id: number; title: string; detail: string; project: string; client: string;
  owner: string; raised_by: string; due: string | null;
  status: string; status_display: string; is_overdue: boolean;
  needs_decision: boolean; decision: string;
  notified: boolean; acknowledged: boolean; awaiting_acknowledgement: boolean;
  times_reported: number; devops_url: string;
};
/* What the editor holds. The report returns an owner's *name* and a `due`
   string; the API accepts an owner *id* and a `due_date`. Rather than bend
   either side, the draft carries both and only the write fields are sent. */
type ActionDraft = Partial<Action> & {
  owner_id?: number | null;
  due_date?: string | null;
  project_name?: string;
};

type Report = {
  week_start: string; week_end: string; is_live: boolean;
  headline: Record<string, number>;
  clients_and_projects: {
    client: string; tasks: number; done: number; overdue: number; blocked: number;
    agreement: { tier: string; response_hours: number | null;
                 resolution_hours: number | null; support_window: string;
                 hosting_provider: string; renewal_date: string | null;
                 renews_in_days: number | null } | null;
    projects: { name: string; status_display: string; is_active: boolean;
                start_date: string | null; end_date: string | null;
                tasks: number; done: number; overdue: number; blocked: number;
                progress: number; team: string[];
                quoted_hours: number | null; actual_hours: number | null }[];
  }[];
  deadlines: {
    overdue_count: number; no_due_date: number;
    due_this_week: DeadlineRow[]; due_next_week: DeadlineRow[];
    overdue: DeadlineRow[];
  };
  work: {
    completed_this_week: { project: string; title: string; owners: string[]; when: string }[];
    completed_total: number; accepted_total: number; outstanding: number;
    blocked: { project: string; title: string; status_display: string; owners: string[] }[];
    awaiting_client_sign_off: { project: string; title: string; status_display: string }[];
  };
  people_and_actions: {
    people: { person: string; open_tasks: number; overdue: number;
              hours: number; projects: string[] }[];
    unassigned_open_tasks: number;
    actions: Action[]; actions_closed_this_week: Action[];
  };
  tickets_risks_debt: {
    tickets: { open: number; opened_this_week: number; resolved_this_week: number;
               response_breaches: TicketRow[]; resolution_breaches: TicketRow[];
               oldest: TicketRow[] };
    risks: RiskRow[]; technical_debt_count: number; reviews_overdue: number;
  };
  service_requirements: {
    client: string; project: string; tier: string;
    response_hours: number | null; resolution_hours: number | null;
    support_window: string; hosting_provider: string; environment_url: string;
    backup_schedule: string; renewal_date: string | null;
    renews_in_days: number | null; monthly_fee: number | null;
    owner: string; notes: string;
  }[];
  capacity_and_priorities: {
    people_with_work: number; hours_per_person: number; available_hours: number;
    committed_hours: number; utilisation_pct: number; over_committed: string[];
    priorities: { id: number; title: string; project: string; client: string;
                  owner: string; is_done: boolean; carried_over: boolean;
                  note: string }[];
    last_week_carried: { title: string; owner: string }[];
  };
  escalations: { kind: string; title: string; owner: string; why: string;
                 reference: string }[];
  stored: { status: string; summary: string; recipients: string;
            sent_at: string | null; prepared_by: string } | null;
  weeks_available: string[];
  people: Person[];
  choices: Record<string, Choice[]>;
};
type DeadlineRow = {
  project: string; title: string; status_display: string; priority: string;
  development: string; due: string | null; owners: string[];
  estimated_hours: number | null; days_late: number;
};
type TicketRow = {
  reference: string; client: string; subject: string; priority?: string;
  status_display?: string; owner: string; age_days: number; devops_url?: string;
};
type RiskRow = {
  id: number; kind: string; kind_display: string; title: string;
  project: string; client: string; severity: string; severity_display: string;
  likelihood_display: string; score: number; status_display: string;
  owner: string; mitigation: string; review_date: string | null;
  review_overdue: boolean; devops_url: string;
};

const SECTIONS = [
  "Escalations", "Clients & projects", "Deadlines", "Work state",
  "People & actions", "Tickets, risks & debt", "Service & SLA",
  "Capacity & priorities",
] as const;
type SectionName = (typeof SECTIONS)[number];

export default function ManagementPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [week, setWeek] = useState("");
  const [tab, setTab] = useState<SectionName>("Escalations");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [editAction, setEditAction] = useState<ActionDraft | null>(null);
  const [newFocus, setNewFocus] = useState("");

  const load = useCallback(async (w: string) => {
    try {
      const q = w ? `?week=${encodeURIComponent(w)}` : "";
      const r = await fetch(`/api/management/report${q}`);
      setData(r.ok ? await r.json() : null);
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
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load("");
  }, [load]);

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
        setNote(d.detail || "That did not work.");
        return null;
      }
      await load(week);
      return d;
    } finally {
      setBusy(false);
    }
  }

  const h = data?.headline ?? {};

  return (
    <AppShell active="Management" me={me} wide>
      <PageHead
        title="Weekly management report"
        subtitle={data
          ? `Week of ${data.week_start} to ${data.week_end}${data.is_live ? " — live figures" : " — as published"}`
          : "Client delivery, capacity, accountability and what needs a decision."}
        actions={
          <>
            {(data?.weeks_available?.length ?? 0) > 0 && (
              <select value={week} onChange={(e) => { setWeek(e.target.value); setLoading(true); void load(e.target.value); }}
                      className="h-8 rounded-lg bg-surface px-2 text-xs text-ink ring-control focus-ring">
                <option value="">This week</option>
                {data!.weeks_available.map((w) => <option key={w} value={w}>Week of {w}</option>)}
              </select>
            )}
            <Button icon="mail" spinning={busy}
                    onClick={() => void post("/api/management/chase", { notify: true })
                      .then((d) => d && setNote(
                        `${d.notified.length} owner(s) notified, ${d.reported} action(s) counted, `
                        + `${d.carried_over} priority(ies) carried over.`))}>
              Notify owners
            </Button>
            <Button icon="upload" variant="primary" spinning={busy}
                    onClick={() => void post("/api/management/save", { publish: true })
                      .then((d) => d && setNote(`Published the week of ${d.week_start}.`))}>
              Publish
            </Button>
            <Button icon="sync" spinning={loading}
                    onClick={() => { setLoading(true); void load(week); }}>Refresh</Button>
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <StatTile label="Active projects" value={loading ? "—" : h.active_projects ?? 0} icon="board" />
        <StatTile label="Open tasks" value={loading ? "—" : h.open_tasks ?? 0} icon="analysis" />
        <StatTile label="Done this week" value={loading ? "—" : h.completed_this_week ?? 0}
                  icon="shield" tone="good" />
        <StatTile label="Overdue" value={loading ? "—" : h.overdue ?? 0}
                  icon="alert" tone={(h.overdue ?? 0) > 0 ? "bad" : "good"} />
        <StatTile label="Open tickets" value={loading ? "—" : h.open_tickets ?? 0}
                  icon="mail" tone={(h.open_tickets ?? 0) > 0 ? "warn" : "good"} />
        <StatTile label="Needs a decision" value={loading ? "—" : h.escalations ?? 0}
                  icon="alert" tone={(h.escalations ?? 0) > 0 ? "bad" : "good"}
                  hint="Escalations" />
      </div>

      {note && (
        <p className="mb-3 flex items-start gap-2 rounded-lg bg-infox-bg px-3 py-2 text-xs text-infox">
          <Icon name="shield" className="mt-px h-4 w-4 shrink-0" />
          <span className="flex-1">{note}</span>
          <button onClick={() => setNote("")} aria-label="Dismiss"
                  className="shrink-0 opacity-60 hover:opacity-100">✕</button>
        </p>
      )}

      <div className="mb-3 flex flex-wrap gap-1.5">
        {SECTIONS.map((s, i) => (
          <Pill key={s} active={tab === s} onClick={() => setTab(s)}>
            {i + 1}. {s}
          </Pill>
        ))}
      </div>

      {loading ? (
        <Section><div className="p-6 text-sm text-ink-2">Building the report…</div></Section>
      ) : !data ? (
        <Section>
          <EmptyState icon="alert" title="Could not build the report"
                      hint="Check that you have Project Tracker access." />
        </Section>
      ) : (
        <>
          {tab === "Escalations" && (
            <Section>
              <Head title="Matters requiring escalation or a management decision"
                    hint="Assembled from the other sections, so nothing can be a breach in one place and absent here." />
              {data.escalations.length === 0 ? (
                <p className="px-4 py-6 text-sm text-ink-2">Nothing to escalate this week.</p>
              ) : (
                <ul className="divide-y divide-stroke border-t border-stroke">
                  {data.escalations.map((e, i) => (
                    <li key={i} className="flex items-start gap-3 px-4 py-2.5">
                      <Badge tone={e.kind === "sla" || e.kind === "action" ? "bad"
                        : e.kind === "decision" ? "info" : "warn"}>{e.kind}</Badge>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-ink">{e.title}</p>
                        <p className="text-xs text-ink-3">
                          {e.why}{e.owner && ` · ${e.owner}`} · {e.reference}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          )}

          {tab === "Clients & projects" && (
            <Section>
              <Head title="Each client and active project" />
              <div className="divide-y divide-stroke border-t border-stroke">
                {data.clients_and_projects.map((c) => (
                  <div key={c.client} className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-ink">{c.client}</span>
                      {c.agreement && (
                        <Badge tone="info">{c.agreement.tier}</Badge>
                      )}
                      <span className="text-xs text-ink-3">
                        {c.done}/{c.tasks} done
                        {c.overdue > 0 && <span className="text-bad"> · {c.overdue} overdue</span>}
                        {c.blocked > 0 && <span className="text-warn"> · {c.blocked} blocked</span>}
                      </span>
                    </div>
                    <ul className="mt-2 space-y-1.5">
                      {c.projects.map((p) => (
                        <li key={p.name} className="flex flex-wrap items-center gap-2 text-xs">
                          <span className="w-44 shrink-0 truncate font-medium text-ink-2">{p.name}</span>
                          <Badge tone={p.is_active ? "neutral" : "good"}>{p.status_display}</Badge>
                          <span className="text-ink-3">
                            {p.start_date ?? "no start"} → {p.end_date ?? "open"}
                          </span>
                          <span className="tabular-nums text-ink-3">{p.done}/{p.tasks} ({p.progress}%)</span>
                          {p.quoted_hours !== null && (
                            <span className="text-ink-3">
                              {p.actual_hours ?? 0}/{p.quoted_hours}h
                            </span>
                          )}
                          {p.team.length > 0 && <span className="text-ink-3">· {p.team.join(", ")}</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {tab === "Deadlines" && (
            <Section>
              <Head title="Current tasks, deliverables and deadlines"
                    hint={`${data.deadlines.no_due_date} open task(s) have no due date at all.`} />
              <div className="border-t border-stroke">
                <DeadlineTable label="Due this week" rows={data.deadlines.due_this_week} />
                <DeadlineTable label="Due next week" rows={data.deadlines.due_next_week} />
                <DeadlineTable label={`Overdue (${data.deadlines.overdue_count})`}
                               rows={data.deadlines.overdue} late />
              </div>
            </Section>
          )}

          {tab === "Work state" && (
            <Section>
              <Head title="Completed, outstanding and blocked work" />
              <div className="grid gap-4 border-t border-stroke p-4 md:grid-cols-2">
                <List title={`Completed this week (${data.work.completed_this_week.length})`}
                      empty="Nothing was closed out this week."
                      items={data.work.completed_this_week.map(
                        (w) => `${w.project}: ${w.title}${w.owners.length ? ` — ${w.owners.join(", ")}` : ""}`)} />
                <List title={`Blocked (${data.work.blocked.length})`}
                      empty="Nothing is blocked."
                      items={data.work.blocked.map(
                        (b) => `${b.project}: ${b.title} — ${b.status_display}`)} />
                <List title={`Awaiting client sign-off (${data.work.awaiting_client_sign_off.length})`}
                      empty="Nothing is waiting on a client."
                      items={data.work.awaiting_client_sign_off.map(
                        (b) => `${b.project}: ${b.title} — ${b.status_display}`)} />
                <div>
                  <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">Totals</h3>
                  <dl className="space-y-1 text-sm">
                    <Row k="Outstanding" v={data.work.outstanding} />
                    <Row k="Completed (all time)" v={data.work.completed_total} />
                    <Row k="Accepted by the client" v={data.work.accepted_total} />
                  </dl>
                </div>
              </div>
            </Section>
          )}

          {tab === "People & actions" && (
            <>
              <Section>
                <Head title="Responsible persons"
                      hint={data.people_and_actions.unassigned_open_tasks > 0
                        ? `${data.people_and_actions.unassigned_open_tasks} open task(s) have nobody assigned.`
                        : undefined} />
                {data.people_and_actions.people.length === 0 ? (
                  <p className="px-4 py-6 text-sm text-ink-2">
                    No task has an assignee yet, so there is nobody to hold to anything.
                  </p>
                ) : (
                  <ul className="divide-y divide-stroke border-t border-stroke">
                    {data.people_and_actions.people.map((p) => (
                      <li key={p.person} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                        <span className="w-44 shrink-0 truncate font-medium text-ink">{p.person}</span>
                        <span className="tabular-nums text-ink-2">{p.open_tasks} open</span>
                        {p.overdue > 0 && <span className="tabular-nums text-bad">{p.overdue} overdue</span>}
                        <span className="tabular-nums text-ink-3">{p.hours}h estimated</span>
                        <span className="min-w-0 flex-1 truncate text-xs text-ink-3">
                          {p.projects.join(", ")}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section className="mt-4">
                <div className="flex items-center justify-between px-4 py-2.5">
                  <div>
                    <h2 className="text-sm font-semibold text-ink">Agreed actions</h2>
                    <p className="text-xs text-ink-3">
                      An action has an owner, a date, a confirmation and a close-out.
                    </p>
                  </div>
                  <Button icon="plus" variant="primary"
                          onClick={() => setEditAction({ status: "open" })}>
                    Raise an action
                  </Button>
                </div>
                {data.people_and_actions.actions.length === 0 ? (
                  <p className="border-t border-stroke px-4 py-6 text-sm text-ink-2">
                    No open actions. Raise one during the review and the owner is emailed.
                  </p>
                ) : (
                  <ul className="divide-y divide-stroke border-t border-stroke">
                    {data.people_and_actions.actions.map((a) => (
                      <li key={a.id} className="flex items-start gap-3 px-4 py-2.5">
                        <div className="min-w-0 flex-1">
                          <button onClick={() => setEditAction(a)}
                                  className="text-left text-sm font-medium text-ink hover:underline focus-ring">
                            {a.title}
                          </button>
                          <p className="text-xs text-ink-3">
                            {a.owner || "unassigned"}
                            {a.due && ` · due ${a.due}`}
                            {a.project && ` · ${a.project}`}
                            {a.times_reported > 1 && ` · reported ${a.times_reported} weeks`}
                          </p>
                        </div>
                        {a.needs_decision && !a.decision && <Badge tone="info">decision</Badge>}
                        {a.awaiting_acknowledgement && <Badge tone="warn">not confirmed</Badge>}
                        {a.is_overdue && <Badge tone="bad">overdue</Badge>}
                        <Badge tone={a.status === "done" ? "good" : "neutral"}>
                          {a.status_display}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                )}
                {data.people_and_actions.actions_closed_this_week.length > 0 && (
                  <p className="border-t border-stroke px-4 py-2 text-xs text-good">
                    Closed out this week: {data.people_and_actions.actions_closed_this_week
                      .map((a) => a.title).join("; ")}
                  </p>
                )}
              </Section>
            </>
          )}

          {tab === "Tickets, risks & debt" && (
            <>
              <Section>
                <Head title="Support tickets"
                      hint={`${data.tickets_risks_debt.tickets.opened_this_week} opened and `
                        + `${data.tickets_risks_debt.tickets.resolved_this_week} resolved this week.`} />
                <div className="grid gap-4 border-t border-stroke p-4 md:grid-cols-2">
                  <List title={`SLA resolution breaches (${data.tickets_risks_debt.tickets.resolution_breaches.length})`}
                        empty="No resolution SLA is breached."
                        items={data.tickets_risks_debt.tickets.resolution_breaches.map(
                          (t) => `${t.client}: ${t.subject} — ${t.age_days}d${t.owner ? `, ${t.owner}` : ""}`)} />
                  <List title={`Oldest open (${data.tickets_risks_debt.tickets.oldest.length})`}
                        empty="No open tickets."
                        items={data.tickets_risks_debt.tickets.oldest.map(
                          (t) => `${t.reference} ${t.client}: ${t.subject} — ${t.age_days}d`)} />
                </div>
              </Section>
              <Section className="mt-4">
                <Head title="Risks and technical debt"
                      hint={`${data.tickets_risks_debt.technical_debt_count} technical debt item(s); `
                        + `${data.tickets_risks_debt.reviews_overdue} review(s) overdue.`} />
                {data.tickets_risks_debt.risks.length === 0 ? (
                  <p className="border-t border-stroke px-4 py-6 text-sm text-ink-2">
                    Nothing on the register. An empty risk register usually means
                    nobody has written the risks down, not that there are none.
                  </p>
                ) : (
                  <ul className="divide-y divide-stroke border-t border-stroke">
                    {data.tickets_risks_debt.risks.map((r) => (
                      <li key={r.id} className="flex items-start gap-3 px-4 py-2.5">
                        <Badge tone={r.severity === "critical" || r.severity === "high"
                          ? "bad" : "neutral"}>{r.severity_display}</Badge>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-ink">{r.title}</p>
                          <p className="text-xs text-ink-3">
                            {r.kind_display} · {r.likelihood_display} · score {r.score}
                            {r.owner && ` · ${r.owner}`}
                            {r.project && ` · ${r.project}`}
                            {!r.mitigation && <span className="text-bad"> · no mitigation recorded</span>}
                          </p>
                        </div>
                        {r.review_overdue && <Badge tone="warn">review overdue</Badge>}
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </>
          )}

          {tab === "Service & SLA" && (
            <Section>
              <Head title="SLA, hosting and service requirements" />
              {data.service_requirements.length === 0 ? (
                <p className="border-t border-stroke px-4 py-6 text-sm text-ink-2">
                  No service agreements recorded. Without a response time written
                  against a client, no SLA figure on this report means anything.
                </p>
              ) : (
                <div className="overflow-x-auto border-t border-stroke">
                  <table className="w-full min-w-[820px] text-sm">
                    <thead>
                      <tr className="border-b border-stroke text-left">
                        {["Client", "Tier", "Response", "Resolution", "Window",
                          "Hosting", "Renewal", "Owner"].map((x) => (
                          <th key={x} className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">{x}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.service_requirements.map((s, i) => (
                        <tr key={i} className="border-b border-stroke last:border-0">
                          <td className="px-3 py-2 font-medium text-ink">{s.client}</td>
                          <td className="px-3 py-2 text-ink-2">{s.tier}</td>
                          <td className="px-3 py-2 tabular-nums text-ink-2">{s.response_hours ?? "—"}h</td>
                          <td className="px-3 py-2 tabular-nums text-ink-2">{s.resolution_hours ?? "—"}h</td>
                          <td className="px-3 py-2 text-xs text-ink-3">{s.support_window || "—"}</td>
                          <td className="px-3 py-2 text-xs text-ink-3">{s.hosting_provider || "—"}</td>
                          <td className="px-3 py-2 text-xs text-ink-3">
                            {s.renewal_date ?? "—"}
                            {s.renews_in_days !== null && s.renews_in_days <= 60 && (
                              <span className="text-warn"> ({s.renews_in_days}d)</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-xs text-ink-3">{s.owner || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
          )}

          {tab === "Capacity & priorities" && (
            <>
              <Section>
                <Head title="Team capacity"
                      hint={`${data.capacity_and_priorities.hours_per_person}h per person per week assumed.`} />
                <div className="grid gap-3 border-t border-stroke p-4 sm:grid-cols-3">
                  <Row k="People with work" v={data.capacity_and_priorities.people_with_work} />
                  <Row k="Available hours" v={data.capacity_and_priorities.available_hours} />
                  <Row k="Committed this week" v={`${data.capacity_and_priorities.committed_hours}h`} />
                </div>
                <div className="px-4 pb-4">
                  <div className="h-2 overflow-hidden rounded-full bg-subtle">
                    <div className={`h-full rounded-full ${
                      data.capacity_and_priorities.utilisation_pct > 100 ? "bg-bad" : "bg-brand"}`}
                         style={{ width: `${Math.min(100, data.capacity_and_priorities.utilisation_pct)}%` }} />
                  </div>
                  <p className="mt-1 text-xs text-ink-3">
                    {data.capacity_and_priorities.utilisation_pct}% committed
                    {data.capacity_and_priorities.over_committed.length > 0
                      && ` · over capacity: ${data.capacity_and_priorities.over_committed.join(", ")}`}
                  </p>
                </div>
              </Section>

              <Section className="mt-4">
                <Head title="Priorities this week"
                      hint="What did not get done is carried into next week automatically." />
                <div className="flex gap-2 border-t border-stroke px-4 py-2.5">
                  <input value={newFocus} onChange={(e) => setNewFocus(e.target.value)}
                         onKeyDown={(e) => {
                           if (e.key === "Enter" && newFocus.trim()) {
                             void post("/api/management/focus", { title: newFocus.trim() })
                               .then(() => setNewFocus(""));
                           }
                         }}
                         placeholder="Add a priority for this week…"
                         className="h-9 flex-1 rounded-lg bg-canvas px-3 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring" />
                  <Button icon="plus" disabled={!newFocus.trim()} spinning={busy}
                          onClick={() => void post("/api/management/focus", { title: newFocus.trim() })
                            .then(() => setNewFocus(""))}>
                    Add
                  </Button>
                </div>
                {data.capacity_and_priorities.priorities.length === 0 ? (
                  <p className="border-t border-stroke px-4 py-6 text-sm text-ink-2">
                    No priorities set for this week.
                  </p>
                ) : (
                  <ul className="divide-y divide-stroke border-t border-stroke">
                    {data.capacity_and_priorities.priorities.map((p) => (
                      <li key={p.id} className="flex items-center gap-3 px-4 py-2">
                        <input type="checkbox" checked={p.is_done}
                               onChange={() => void post("/api/management/focus",
                                 { id: p.id, is_done: !p.is_done })}
                               className="h-4 w-4 rounded border-stroke focus-ring" />
                        <span className={`min-w-0 flex-1 text-sm ${
                          p.is_done ? "text-ink-3 line-through" : "text-ink"}`}>
                          {p.title}
                          {p.owner && <span className="text-ink-3"> — {p.owner}</span>}
                        </span>
                        {p.carried_over && <Badge tone="warn">carried over</Badge>}
                        <button onClick={() => void fetch(`/api/management/focus/${p.id}/delete`,
                                                          { method: "DELETE" }).then(() => load(week))}
                                aria-label="Remove"
                                className="text-ink-3 transition hover:text-bad focus-ring">
                          <Icon name="trash" className="h-3.5 w-3.5" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </>
          )}
        </>
      )}

      {editAction && (
        <Modal title={editAction.id ? "Action" : "Raise an action"} wide
               onClose={() => setEditAction(null)}
               footer={
                 <>
                   {editAction.id && (
                     <Button onClick={() => void fetch(`/api/management/actions/${editAction.id}/delete`,
                                                       { method: "DELETE" })
                       .then(() => { setEditAction(null); void load(week); })}>
                       Delete
                     </Button>
                   )}
                   <Button onClick={() => setEditAction(null)}>Cancel</Button>
                   <Button variant="primary" spinning={busy}
                           onClick={() => void post("/api/management/actions", {
                             id: editAction.id,
                             title: editAction.title,
                             detail: editAction.detail,
                             owner: editAction.owner_id ?? null,
                             due_date: editAction.due_date ?? editAction.due ?? null,
                             status: editAction.status,
                             project_name: editAction.project_name ?? editAction.project ?? "",
                             needs_decision: editAction.needs_decision,
                             decision: editAction.decision,
                           }).then((d) => d && setEditAction(null))}>
                     Save
                   </Button>
                 </>
               }>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <TextInput label="What has been agreed" value={editAction.title ?? ""}
                         onChange={(v) => setEditAction({ ...editAction, title: v })} />
            </div>
            <SelectInput label="Owner"
                         value={editAction.owner_id ? String(editAction.owner_id) : ""}
                         hint="They are emailed and asked to confirm the date."
                         onChange={(v) => setEditAction({ ...editAction, owner_id: v ? Number(v) : null, owner: undefined })}
                         options={[{ value: "", label: "Unassigned" },
                                   ...(data?.people ?? []).map((p) => ({ value: String(p.id), label: p.name }))]} />
            <div>
              <span className="block h-6 text-sm font-medium leading-6 text-ink">Due date</span>
              <input type="date" value={editAction.due ?? ""}
                     onChange={(e) => setEditAction({ ...editAction, due_date: e.target.value, due: e.target.value })}
                     className="h-9 w-full rounded-lg bg-canvas px-2.5 text-sm text-ink ring-control focus-ring" />
            </div>
            <SelectInput label="Status" value={editAction.status ?? "open"}
                         onChange={(v) => setEditAction({ ...editAction, status: v })}
                         options={(data?.choices?.action_status ?? []).map((c) => ({ value: c.value, label: c.label }))} />
            <TextInput label="Project" value={editAction.project ?? ""}
                       onChange={(v) => setEditAction({ ...editAction, project_name: v, project: v })} />
            <div className="sm:col-span-2">
              <AreaInput label="Detail" rows={3} value={editAction.detail ?? ""}
                         onChange={(v) => setEditAction({ ...editAction, detail: v })} />
            </div>
            <label className="flex items-center gap-2 text-sm text-ink sm:col-span-2">
              <input type="checkbox" checked={!!editAction.needs_decision}
                     onChange={(e) => setEditAction({ ...editAction, needs_decision: e.target.checked })}
                     className="h-4 w-4 rounded border-stroke focus-ring" />
              This needs a management decision, not just doing
            </label>
            {editAction.needs_decision && (
              <div className="sm:col-span-2">
                <AreaInput label="Decision" rows={2} value={editAction.decision ?? ""}
                           hint="Recording it here takes it off the escalation list."
                           onChange={(v) => setEditAction({ ...editAction, decision: v })} />
              </div>
            )}
            {editAction.id && (
              <p className="text-xs text-ink-3 sm:col-span-2">
                Reported on {editAction.times_reported ?? 0} week(s).
                {editAction.notified ? " Owner notified." : " Owner not yet notified."}
                {editAction.acknowledged && " Confirmed by the owner."}
              </p>
            )}
          </div>
        </Modal>
      )}
    </AppShell>
  );
}

function Head({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-4 py-2.5">
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
      {hint && <p className="text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string | number }) {
  return (
    <div className="flex justify-between gap-2 text-sm">
      <span className="text-ink-3">{k}</span>
      <span className="font-medium tabular-nums text-ink">{v}</span>
    </div>
  );
}

function List({ title, items, empty }:
              { title: string; items: string[]; empty: string }) {
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">{title}</h3>
      {items.length === 0 ? (
        <p className="text-sm text-ink-3">{empty}</p>
      ) : (
        <ul className="space-y-1">
          {items.slice(0, 12).map((t, i) => (
            <li key={i} className="text-sm leading-snug text-ink-2">{t}</li>
          ))}
          {items.length > 12 && (
            <li className="text-xs text-ink-3">…and {items.length - 12} more</li>
          )}
        </ul>
      )}
    </div>
  );
}

function DeadlineTable({ label, rows, late }:
                       { label: string; rows: DeadlineRow[]; late?: boolean }) {
  if (rows.length === 0) {
    return (
      <div className="border-b border-stroke px-4 py-3 last:border-0">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-3">{label}</h3>
        <p className="mt-1 text-sm text-ink-3">Nothing.</p>
      </div>
    );
  }
  return (
    <div className="border-b border-stroke last:border-0">
      <h3 className="px-4 pt-3 text-xs font-semibold uppercase tracking-wide text-ink-3">{label}</h3>
      <ul className="divide-y divide-stroke/60 px-4 py-1.5">
        {rows.slice(0, 15).map((r, i) => (
          <li key={i} className="flex flex-wrap items-center gap-2 py-1.5 text-sm">
            <span className="w-36 shrink-0 truncate text-xs text-ink-3">{r.project}</span>
            <span className="min-w-0 flex-1 truncate text-ink">{r.title}</span>
            {r.development && <span className="text-[11px] text-ink-3">{r.development}</span>}
            <span className="text-xs text-ink-3">{r.owners.join(", ") || "unassigned"}</span>
            <span className={`w-24 shrink-0 text-right text-xs tabular-nums ${
              late ? "text-bad" : "text-ink-3"}`}>
              {late ? `${r.days_late}d late` : r.due}
            </span>
          </li>
        ))}
      </ul>
      {rows.length > 15 && (
        <p className="px-4 pb-2 text-xs text-ink-3">…and {rows.length - 15} more</p>
      )}
    </div>
  );
}
