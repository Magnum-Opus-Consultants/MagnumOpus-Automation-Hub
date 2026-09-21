"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, StatTile, Badge, Button, EmptyState, Modal,
  TextInput, AreaInput, SelectInput, Pill, type Tone,
} from "@/components/ui";

type Attachment = {
  id: number; kind: "file" | "link"; question: string; label: string;
  url?: string; original_name?: string; size?: number; download?: string;
  uploaded_at: string | null;
};
type Req = {
  id: number; title: string; kind: string; kind_display: string; kind_other: string;
  client_name: string; client_email: string; intro: string;
  questions: string[]; answers: Record<string, string>;
  status: string; notify_email: string; cc_emails: string[]; recipients: string[];
  attachments: Attachment[];
  question_count: number; answered_count: number;
  link: string;
  created_at: string | null; sent_at: string | null; answered_at: string | null;
};
type Payload = {
  requests: Req[]; total: number; sent: number; answered: number; draft: number;
  kinds: [string, string][];
};

const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral", sent: "info", answered: "good",
};
const FILTERS = ["All", "Draft", "Sent", "Answered"] as const;
type Filter = (typeof FILTERS)[number];

// Question library. Each group can be pulled into a request wholesale, or
// individual questions picked from the "Add from library" dropdown.
const LIBRARY: { group: string; questions: string[] }[] = [
  {
    group: "Project scope",
    questions: [
      "What is the scope of the work as you see it?",
      "What is explicitly out of scope?",
      "What does a successful outcome look like?",
      "Who is the decision-maker and who signs off?",
      "What is driving the deadline?",
      "What has already been tried or built?",
      "What are the biggest risks from your side?",
    ],
  },
  {
    group: "Website",
    questions: [
      "What is the main goal of the website?",
      "Who is the primary audience?",
      "Do you have existing branding (logo, colours, fonts) we should follow?",
      "Which pages or sections do you need?",
      "Are there any websites you like that we should look at?",
      "Who will maintain the content after launch?",
      "What is your target launch date?",
    ],
  },
  {
    group: "Software",
    questions: [
      "What problem should the software solve?",
      "Who will use it, and roughly how many people?",
      "Which systems must it connect to or replace?",
      "What data needs to move in and out?",
      "Are there any compliance or data-residency requirements?",
      "How will we know it is working once it is live?",
    ],
  },
  {
    group: "Reports",
    questions: [
      "Which report or dashboard is this about?",
      "Who reads it, and how often do they need it?",
      "Which figures must it show?",
      "Where does the underlying data come from today?",
      "What is wrong or missing in the current version?",
      "What period should it cover?",
    ],
  },
  {
    group: "Budget & timeline",
    questions: [
      "What is your budget range for this?",
      "When do you need it delivered?",
      "Are there fixed dates we must work around?",
      "Who handles invoicing on your side?",
    ],
  },
  {
    group: "Access & logistics",
    questions: [
      "Who is our day-to-day contact?",
      "What access or credentials will we need, and who grants them?",
      "Are there internal approvals we should plan around?",
    ],
  },
];

// Which library group seeds a request when the "About" is switched.
const KIND_SEED: Record<string, string> = {
  website: "Website",
  software: "Software",
  reports: "Reports",
  project: "Project scope",
  other: "Project scope",
};

const INTRO_TEMPLATES: { name: string; text: string }[] = [
  {
    name: "Discovery — new work",
    text: "Thanks for getting in touch. Before we quote, a few questions so we scope this accurately and don't guess at anything important.",
  },
  {
    name: "Detail needed — in progress",
    text: "We've started looking at this and need a bit more detail from your side before we can move forward.",
  },
  {
    name: "Report or dashboard change",
    text: "So we change the right numbers and don't break anything you rely on, could you confirm the following.",
  },
  {
    name: "Support — troubleshooting",
    text: "Sorry you're having trouble. The answers below will let us reproduce the issue rather than guess at it.",
  },
  {
    name: "Handover / access",
    text: "To get everything moving on our side, we need a few practical details confirmed.",
  },
];

type Form = {
  title: string; kind: string; kind_other: string;
  client_name: string; client_email: string;
  intro: string; notify_email: string; cc: string; questions: string[];
};
const BLANK: Form = {
  title: "", kind: "project", kind_other: "", client_name: "", client_email: "",
  intro: "", notify_email: "", cc: "", questions: [""],
};

function libraryFor(group: string) {
  return LIBRARY.find((g) => g.group === group)?.questions ?? [];
}

/** What a client sent alongside their answers: files to download, links to open. */
function AttachmentList({ items }: { items: Attachment[] }) {
  if (items.length === 0) return null;
  const size = (b?: number) => {
    if (!b) return "";
    const mb = b / (1024 * 1024);
    return mb >= 0.1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
  };
  return (
    <ul className="mt-1.5 space-y-1">
      {items.map((a) => (
        <li key={a.id} className="flex items-center gap-2">
          <Icon name={a.kind === "link" ? "link" : "file"}
                className="h-3.5 w-3.5 shrink-0 text-ink-3" />
          {a.kind === "link" ? (
            <a href={a.url} target="_blank" rel="noreferrer"
               className="min-w-0 flex-1 truncate text-xs text-brand hover:underline">
              {a.label}
            </a>
          ) : (
            <>
              <span className="min-w-0 flex-1 truncate text-xs text-ink-2">
                {a.label}
                {a.size ? <span className="text-ink-3"> · {size(a.size)}</span> : null}
              </span>
              {/* A normal link, not fetch(): the response is a file download and
                  the session cookie authorises it. */}
              <a href={a.download} download
                 className="inline-flex h-6 shrink-0 items-center rounded px-2 text-[11px] font-semibold text-brand transition hover:bg-brand-tint focus-ring">
                Download
              </a>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function ClientRequestsPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<Payload | null>(null);
  // Starts true so the first paint shows the loading state without the mount
  // effect having to set it synchronously.
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("All");
  const [q, setQ] = useState("");
  const [composing, setComposing] = useState(false);
  const [form, setForm] = useState<Form>(BLANK);
  const [viewing, setViewing] = useState<Req | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<number | null>(null);
  const [addCc, setAddCc] = useState("");
  const [libOpen, setLibOpen] = useState(false);
  const [libSearch, setLibSearch] = useState("");

  // Every state update happens after an await, so nothing re-renders
  // synchronously while the mount effect is still running.
  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/client-requests");
      if (!r.ok) throw new Error(String(r.status));
      setData(await r.json());
    } catch {
      setData({ requests: [], total: 0, sent: 0, answered: 0, draft: 0, kinds: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  async function refresh() {
    setLoading(true);
    await load();
  }

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "client_requests")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // load() only updates state after awaiting the fetch, so nothing re-renders
    // synchronously here; the rule cannot see through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const all = useMemo(() => data?.requests ?? [], [data]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return all.filter((r) => {
      if (filter !== "All" && r.status !== filter.toLowerCase()) return false;
      if (needle && !`${r.title} ${r.client_name} ${r.client_email}`.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [all, filter, q]);

  function startNew() {
    setForm({ ...BLANK, questions: libraryFor("Project scope") });
    setError("");
    setComposing(true);
  }

  /** Switching "About" reloads that kind's starter questions - but never over
   *  questions that have been edited by hand. */
  function changeKind(kind: string) {
    setForm((f) => {
      const currentSeed = libraryFor(KIND_SEED[f.kind] ?? "");
      const untouched = JSON.stringify(f.questions) === JSON.stringify(currentSeed)
        || f.questions.every((x) => !x.trim());
      return {
        ...f,
        kind,
        questions: untouched ? (libraryFor(KIND_SEED[kind] ?? "") || [""]) : f.questions,
      };
    });
  }

  /** Append library questions, skipping any already on the request. */
  function addFromLibrary(questions: string[]) {
    setForm((f) => {
      const have = new Set(f.questions.map((x) => x.trim().toLowerCase()).filter(Boolean));
      const additions = questions.filter((x) => !have.has(x.trim().toLowerCase()));
      const kept = f.questions.filter((x) => x.trim());
      return { ...f, questions: [...kept, ...additions] };
    });
  }

  function setQuestion(i: number, v: string) {
    setForm((f) => ({ ...f, questions: f.questions.map((x, j) => (j === i ? v : x)) }));
  }
  function addQuestion() {
    setForm((f) => ({ ...f, questions: [...f.questions, ""] }));
  }
  function removeQuestion(i: number) {
    setForm((f) => ({
      ...f,
      questions: f.questions.length > 1 ? f.questions.filter((_, j) => j !== i) : f.questions,
    }));
  }

  async function submit(send: boolean) {
    const questions = form.questions.map((x) => x.trim()).filter(Boolean);
    if (!form.title.trim()) return setError("Give the request a title.");
    if (!form.client_name.trim()) return setError("Enter the client's name.");
    if (!form.client_email.includes("@")) return setError("Enter a valid client email.");
    if (questions.length === 0) return setError("Add at least one question.");

    setSaving(true);
    setError("");
    try {
      const r = await fetch("/api/client-requests/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          questions,
          send,
          cc_emails: form.cc,
          kind_other: form.kind_other,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Failed (${r.status})`);
      setComposing(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  async function sendNow(r: Req) {
    setSaving(true);
    try {
      const res = await fetch(`/api/client-requests/${r.id}/send`, { method: "POST" });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        alert(d.detail || "Could not send the email.");
      }
      await load();
    } finally {
      setSaving(false);
    }
  }

  /** Add recipients to an existing request — they get every reply from now on. */
  async function addRecipients(r: Req) {
    const raw = addCc.trim();
    if (!raw) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/client-requests/${r.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ add_cc: raw }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) {
        alert(d.detail || "Could not add those addresses.");
        return;
      }
      setAddCc("");
      setViewing(d);
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function remove(r: Req) {
    if (!confirm(`Delete "${r.title}"? The client's link will stop working.`)) return;
    await fetch(`/api/client-requests/${r.id}/delete`, { method: "DELETE" });
    if (viewing?.id === r.id) setViewing(null);
    await load();
  }

  async function copyLink(r: Req) {
    try {
      await navigator.clipboard.writeText(r.link);
      setCopied(r.id);
      setTimeout(() => setCopied((c) => (c === r.id ? null : c)), 1800);
    } catch {
      // Clipboard is blocked in some browsers/contexts; show the link instead
      // of failing silently.
      prompt("Copy this link:", r.link);
    }
  }

  const kindOpts = (data?.kinds ?? []).map(([value, label]) => ({ value, label }));

  return (
    <AppShell active="Client Requests" me={me} wide>
      <PageHead
        title="Client Requests"
        subtitle="Send a client a set of questions; their answers come back to your inbox."
        actions={
          <>
            <Button icon="plus" variant="primary" onClick={startNew}>New request</Button>
            <Button icon="sync" spinning={loading} onClick={refresh} disabled={loading}>Refresh</Button>
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Total" value={loading ? "—" : data?.total ?? 0} icon="mail" tone="neutral" />
        <StatTile label="Draft" value={loading ? "—" : data?.draft ?? 0} icon="edit" tone="neutral" />
        <StatTile label="Awaiting reply" value={loading ? "—" : data?.sent ?? 0} icon="clock"
                  tone={(data?.sent ?? 0) ? "warn" : "neutral"} />
        <StatTile label="Answered" value={loading ? "—" : data?.answered ?? 0} icon="shield" tone="good" />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search by title, client or email…"
          className="h-9 min-w-52 flex-1 rounded-lg bg-surface px-3 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring"
        />
        {FILTERS.map((f) => (
          <Pill key={f} active={filter === f} onClick={() => setFilter(f)}>{f}</Pill>
        ))}
      </div>

      <Section>
        {loading ? (
          <div className="p-6 text-sm text-ink-2">Loading requests…</div>
        ) : shown.length === 0 ? (
          <EmptyState
            icon="mail"
            title={all.length ? "Nothing matches these filters" : "No client requests yet"}
            hint={all.length
              ? "Try a different filter."
              : "Create one to send a client a short set of questions about their software, website or project."}
            action={<Button icon="plus" variant="primary" onClick={startNew}>New request</Button>}
          />
        ) : (
          <>
          <div className="hidden items-center gap-3 border-b border-stroke bg-subtle/60 px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3 md:flex">
            <span className="w-1" />
            <span className="flex-1">Request</span>
            <span className="w-28">Answered</span>
            <span className="w-28">Status</span>
            <span className="w-[124px]" />
            <span className="w-8" />
          </div>
          <ul className="divide-y divide-stroke">
            {shown.map((r) => (
              <li key={r.id} className="flex items-center gap-3 px-4 py-3 transition hover:bg-subtle/40">
                {/* Status as a coloured rail rather than a badge in the title
                    line: it scans down the list without crowding the name. */}
                <span className={`h-9 w-1 shrink-0 rounded-full ${
                  r.status === "answered" ? "bg-good"
                    : r.status === "sent" ? "bg-infox" : "bg-ink-3/40"
                }`} />

                <button onClick={() => setViewing(r)}
                        className="min-w-0 flex-1 text-left focus-ring">
                  <span className="block truncate text-sm font-medium text-ink">
                    {r.title}
                  </span>
                  <span className="block truncate text-xs text-ink-3">
                    {r.client_name} · {r.client_email} · {r.kind_display}
                  </span>
                </button>

                {/* Answered progress, so the list shows how much came back. */}
                <span className="hidden w-28 shrink-0 items-center gap-1.5 sm:flex">
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-subtle">
                    <span className={`block h-full rounded-full ${
                      r.answered_count === r.question_count && r.question_count > 0
                        ? "bg-good" : "bg-brand"
                    }`} style={{
                      width: `${r.question_count
                        ? Math.round((r.answered_count / r.question_count) * 100) : 0}%`,
                    }} />
                  </span>
                  <span className="shrink-0 text-[11px] text-ink-3">
                    {r.answered_count}/{r.question_count}
                  </span>
                </span>

                {(r.attachments?.length ?? 0) > 0 && (
                  <span title={`${r.attachments.length} attachment(s)`}
                        className="hidden shrink-0 items-center gap-1 text-[11px] text-ink-2 sm:flex">
                    <Icon name="file" className="h-3.5 w-3.5" />
                    {r.attachments.length}
                  </span>
                )}
                <span className="hidden w-28 shrink-0 md:block">
                  <Badge tone={STATUS_TONE[r.status] ?? "neutral"}>
                    {r.status === "sent" ? "Awaiting reply"
                      : r.status === "answered" ? "Answered" : "Draft"}
                  </Badge>
                </span>

                <Button icon="file" onClick={() => setViewing(r)}>View</Button>
                {r.status !== "answered" && (
                  <Button icon="mail" variant="primary" spinning={saving}
                          onClick={() => sendNow(r)}>
                    {r.status === "sent" ? "Resend" : "Send"}
                  </Button>
                )}
                <button onClick={() => remove(r)} aria-label="Delete request"
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-3 transition hover:bg-subtle hover:text-bad focus-ring">
                  <Icon name="trash" className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
          </>
        )}
      </Section>

      {/* ── Compose ── */}
      {composing && (
        <Modal
          title="New client request"
          wide
          onClose={() => setComposing(false)}
          footer={
            <>
              {error && <span className="mr-auto text-sm text-bad">{error}</span>}
              <Button onClick={() => setComposing(false)}>Cancel</Button>
              <Button spinning={saving} onClick={() => submit(false)} disabled={saving}>
                Save as draft
              </Button>
              <Button variant="primary" icon="mail" spinning={saving}
                      onClick={() => submit(true)} disabled={saving}>
                Save &amp; send
              </Button>
            </>
          }
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <TextInput label="Title" value={form.title}
                         placeholder="e.g. Website redesign — discovery questions"
                         onChange={(v) => setForm({ ...form, title: v })} />
            </div>
            <SelectInput label="About" value={form.kind} onChange={changeKind}
                         options={kindOpts.length ? kindOpts : [{ value: "project", label: "Project" }]}
                         hint="Switching this loads a starter question set." />
            {form.kind === "other" ? (
              <TextInput label="What is it about?" value={form.kind_other}
                         placeholder="e.g. Hosting migration"
                         hint="The client sees this wording."
                         onChange={(v) => setForm({ ...form, kind_other: v })} />
            ) : <div className="hidden sm:block" />}
            <TextInput label="Send answers to" value={form.notify_email}
                       placeholder="Defaults to your account email"
                       onChange={(v) => setForm({ ...form, notify_email: v })} />
            <TextInput label="Also send to" value={form.cc}
                       placeholder="colleague@moc-pty.com, another@moc-pty.com"
                       hint="Comma-separated. They receive every reply too."
                       onChange={(v) => setForm({ ...form, cc: v })} />
            <TextInput label="Client name" value={form.client_name}
                       onChange={(v) => setForm({ ...form, client_name: v })} />
            <TextInput label="Client email" type="email" value={form.client_email}
                       onChange={(v) => setForm({ ...form, client_email: v })} />
            <div className="sm:col-span-2">
              <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                <span className="text-xs font-medium text-ink-2">Intro template</span>
                {INTRO_TEMPLATES.map((t) => (
                  <button key={t.name} type="button"
                          onClick={() => setForm((f) => ({ ...f, intro: t.text }))}
                          className={`rounded-md px-2 py-1 text-[11px] font-medium transition focus-ring ${
                            form.intro === t.text
                              ? "bg-brand-tint text-brand-pressed"
                              : "bg-subtle text-ink-2 hover:text-ink"
                          }`}>
                    {t.name}
                  </button>
                ))}
                {form.intro && (
                  <button type="button" onClick={() => setForm((f) => ({ ...f, intro: "" }))}
                          className="rounded-md px-2 py-1 text-[11px] text-ink-3 transition hover:text-bad focus-ring">
                    Clear
                  </button>
                )}
              </div>
              <AreaInput label="Intro message" rows={2} value={form.intro}
                         hint="Shown above the questions in the email and on the form."
                         onChange={(v) => setForm({ ...form, intro: v })} />
            </div>
          </div>

          <div className="mt-5">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-ink">
                Questions <span className="font-normal text-ink-3">({form.questions.filter((x) => x.trim()).length})</span>
              </h3>
              <span className="ml-auto" />
              {/* A native <select> cannot show which questions are already on
                  the request, and truncates long option text. This is a real
                  popover with tick state and a search. */}
              <div className="relative">
                <Button icon="plus" onClick={() => setLibOpen((v) => !v)}>
                  Add from library
                </Button>
                {libOpen && (
                  <>
                    <button aria-label="Close library" onClick={() => setLibOpen(false)}
                            className="fixed inset-0 z-40 cursor-default" />
                    <div className="absolute right-0 z-50 mt-1 max-h-80 w-[26rem] overflow-y-auto rounded-lg bg-surface p-2 shadow-2xl ring-1 ring-stroke">
                      <input
                        autoFocus
                        value={libSearch}
                        onChange={(e) => setLibSearch(e.target.value)}
                        placeholder="Search questions…"
                        className="mb-2 h-8 w-full rounded bg-canvas px-2 text-xs text-ink ring-control placeholder:text-ink-3 focus-ring"
                      />
                      {LIBRARY.map((g) => {
                        const needle = libSearch.trim().toLowerCase();
                        const qs = g.questions.filter((x) => x.toLowerCase().includes(needle));
                        if (qs.length === 0) return null;
                        return (
                          <div key={g.group} className="mb-2">
                            <div className="flex items-center gap-2 px-1 pb-1">
                              <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                                {g.group}
                              </span>
                              <button
                                onClick={() => addFromLibrary(qs)}
                                className="ml-auto rounded px-1.5 py-0.5 text-[11px] font-medium text-brand transition hover:bg-brand-tint focus-ring"
                              >
                                Add all {qs.length}
                              </button>
                            </div>
                            <ul>
                              {qs.map((qq) => {
                                const on = form.questions.some(
                                  (x) => x.trim().toLowerCase() === qq.toLowerCase());
                                return (
                                  <li key={qq}>
                                    <button
                                      onClick={() => {
                                        if (on) {
                                          setForm((f) => ({
                                            ...f,
                                            questions: f.questions.filter(
                                              (x) => x.trim().toLowerCase() !== qq.toLowerCase()),
                                          }));
                                        } else {
                                          addFromLibrary([qq]);
                                        }
                                      }}
                                      className={`flex w-full items-start gap-2 rounded px-1.5 py-1 text-left text-xs transition hover:bg-subtle ${
                                        on ? "text-ink" : "text-ink-2"
                                      }`}
                                    >
                                      <span className={`mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border transition ${
                                        on ? "border-brand bg-brand text-white" : "border-ink-3/50 text-transparent"
                                      }`}>
                                        <Icon name="tasks" className="h-2 w-2" />
                                      </span>
                                      <span>{qq}</span>
                                    </button>
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        );
                      })}
                      {LIBRARY.every((g) => g.questions.every(
                        (x) => !x.toLowerCase().includes(libSearch.trim().toLowerCase()))) && (
                        <p className="px-1 py-3 text-center text-xs text-ink-3">No questions match.</p>
                      )}
                    </div>
                  </>
                )}
              </div>
              <Button icon="plus" onClick={addQuestion}>Blank</Button>
            </div>
            <ul className="space-y-2">
              {form.questions.map((qq, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span className="w-5 shrink-0 text-right text-xs text-ink-3">{i + 1}.</span>
                  <input
                    value={qq}
                    onChange={(e) => setQuestion(i, e.target.value)}
                    placeholder="Type a question for the client"
                    className="h-9 flex-1 rounded-lg bg-surface px-3 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring"
                  />
                  <button onClick={() => removeQuestion(i)} aria-label={`Remove question ${i + 1}`}
                          disabled={form.questions.length === 1}
                          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-3 transition hover:bg-subtle hover:text-bad disabled:opacity-30 focus-ring">
                    <Icon name="trash" className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </Modal>
      )}

      {/* ── View / answers ── */}
      {viewing && (
        <Modal
          title={viewing.title}
          wide
          onClose={() => setViewing(null)}
          footer={
            <>
              <span className="mr-auto text-xs text-ink-3">
                {viewing.client_name} · {viewing.client_email}
                {viewing.answered_at && ` · answered ${viewing.answered_at.slice(0, 16).replace("T", " ")}`}
              </span>
              <Button icon="link" onClick={() => copyLink(viewing)}>
                {copied === viewing.id ? "Copied" : "Copy link"}
              </Button>
              {viewing.status !== "answered" && (
                <Button variant="primary" icon="mail" spinning={saving}
                        onClick={() => sendNow(viewing)}>
                  {viewing.status === "sent" ? "Resend" : "Send"}
                </Button>
              )}
            </>
          }
        >
          {/* A summary strip first: how much came back, and from whom. */}
          <div className="mb-4 flex flex-wrap items-center gap-4 rounded-lg bg-subtle/60 p-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-3">Client</p>
              <p className="text-sm font-medium text-ink">{viewing.client_name}</p>
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-3">About</p>
              <p className="text-sm font-medium text-ink">{viewing.kind_display}</p>
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-3">Status</p>
              <p className="text-sm font-medium text-ink">
                {viewing.status === "answered" ? "Answered"
                  : viewing.status === "sent" ? "Awaiting reply" : "Draft"}
              </p>
            </div>
            <div className="ml-auto min-w-32">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-3">
                Answered
              </p>
              <div className="mt-1 flex items-center gap-2">
                <span className="h-1.5 w-20 overflow-hidden rounded-full bg-surface">
                  <span className={`block h-full rounded-full ${
                    viewing.answered_count === viewing.question_count && viewing.question_count > 0
                      ? "bg-good" : "bg-brand"
                  }`} style={{
                    width: `${viewing.question_count
                      ? Math.round((viewing.answered_count / viewing.question_count) * 100) : 0}%`,
                  }} />
                </span>
                <span className="text-xs font-medium text-ink-2">
                  {viewing.answered_count} of {viewing.question_count}
                </span>
              </div>
            </div>
          </div>

          {viewing.intro && <p className="mb-4 text-sm text-ink-2">{viewing.intro}</p>}

          <section className="mb-4 rounded-lg bg-subtle/50 p-3">
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">
              Replies go to
            </h3>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {(viewing.recipients ?? []).map((addr, i) => (
                <span key={addr}
                      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs ${
                        i === 0 ? "bg-brand-tint text-brand-pressed font-medium" : "bg-surface text-ink-2 ring-panel"
                      }`}>
                  <Icon name="mail" className="h-3 w-3" />
                  {addr}
                </span>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={addCc}
                onChange={(e) => setAddCc(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void addRecipients(viewing); }}
                placeholder="add another@moc-pty.com"
                className="h-8 min-w-48 flex-1 rounded-lg bg-surface px-2 text-xs text-ink ring-control placeholder:text-ink-3 focus-ring"
              />
              <Button spinning={saving} onClick={() => void addRecipients(viewing)}>Add recipient</Button>
            </div>
          </section>
          <ol className="space-y-2">
            {viewing.questions.map((qq, i) => {
              const a = ((viewing.answers ?? {})[qq] ?? "").trim();
              return (
                <li key={i}
                    className={`overflow-hidden rounded-lg ring-1 ring-inset ${
                      a ? "bg-surface ring-good/25" : "bg-subtle/40 ring-stroke"
                    }`}>
                  <div className="flex items-start gap-2.5 px-3 pt-2.5">
                    <span className={`mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                      a ? "bg-good text-white" : "bg-subtle text-ink-3"
                    }`}>
                      {a ? "\u2713" : i + 1}
                    </span>
                    <p className="text-sm font-medium text-ink">{qq}</p>
                  </div>
                  <p className={`whitespace-pre-wrap px-3 pb-1 pl-[42px] pt-1 text-sm ${
                    a ? "text-ink-2" : "italic text-ink-3"
                  }`}>
                    {a || (viewing.status === "answered" ? "Not answered" : "Awaiting reply")}
                  </p>
                  <div className="px-3 pb-3 pl-[42px]">
                    <AttachmentList
                      items={(viewing.attachments ?? []).filter((x) => x.question === qq)} />
                  </div>
                </li>
              );
            })}
          </ol>
          {(viewing.attachments ?? []).some((x) => !x.question) && (
            <section className="mt-4">
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">
                Other attachments
              </h3>
              <AttachmentList items={(viewing.attachments ?? []).filter((x) => !x.question)} />
            </section>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg bg-subtle/40 p-3">
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-3">
                The client&apos;s link
              </p>
              <p className="truncate text-xs text-ink-2">{viewing.link}</p>
            </div>
            <Button icon="link" onClick={() => copyLink(viewing)}>
              {copied === viewing.id ? "Copied" : "Copy"}
            </Button>
            <a href={viewing.link} target="_blank" rel="noreferrer"
               className="inline-flex h-8 items-center rounded-lg px-3 text-xs font-semibold text-ink-2 ring-control transition hover:bg-subtle focus-ring">
              Open as the client
            </a>
          </div>
        </Modal>
      )}
    </AppShell>
  );
}
