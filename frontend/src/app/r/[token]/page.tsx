"use client";

/**
 * The client's view of a question sheet. Reached from an emailed link with no
 * login, so it deliberately renders none of the Sentinel shell - no sidebar, no
 * nav, nothing about the platform beyond who is asking.
 *
 * Styled as a Magnum Opus page rather than an internal tool: the client is the
 * audience here, and this may be the first thing they see of us.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";

type Attachment = {
  id: number; kind: "file" | "link"; question: string; label: string;
  url?: string; original_name?: string; size?: number; content_type?: string;
  uploaded_at: string | null;
};
type Sheet = {
  title: string;
  kind_display: string;
  client_name: string;
  intro: string;
  questions: string[];
  answers: Record<string, string>;
  attachments: Attachment[];
  max_upload_mb: number;
  max_attachments: number;
  allowed_extensions: string[];
  already_answered: boolean;
  answered_at: string | null;
  from_company: string;
};

/** The MOC mark, inline so it needs no extra request and inverts on the banner. */
function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <svg viewBox="0 0 32 32" className="h-7 w-7 shrink-0" aria-hidden>
        <path
          d="M16 2.6 27 6.4v9.1c0 6.9-4.5 11.6-11 13.9-6.5-2.3-11-7-11-13.9V6.4L16 2.6Z"
          fill="currentColor"
          opacity="0.95"
        />
        <path
          d="M10.2 17.6l3.3-3.6 2.7 2.6 4.4-5.2"
          fill="none"
          stroke="#0b1220"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="leading-tight">
        <span className="block text-sm font-semibold tracking-tight">
          Magnum Opus Consultants
        </span>
        <span className="block text-[11px] opacity-75">Software · Systems · Reporting</span>
      </span>
    </span>
  );
}

function fmtSize(bytes?: number) {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 0.1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** What has been attached, with a remove control unless read-only. */
function AttachList({ items, readOnly = false, onRemove }: {
  items: Attachment[]; readOnly?: boolean; onRemove?: (a: Attachment) => void;
}) {
  if (items.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1.5">
      {items.map((a) => (
        <li key={a.id} className="flex items-center gap-2 rounded-lg bg-subtle/60 px-2.5 py-1.5">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
               strokeLinecap="round" strokeLinejoin="round"
               className="h-3.5 w-3.5 shrink-0 text-ink-3">
            {a.kind === "link"
              ? <><path d="M10 13a5 5 0 0 0 7.07 0l2-2A5 5 0 0 0 12 4l-1 1" /><path d="M14 11a5 5 0 0 0-7.07 0l-2 2A5 5 0 0 0 12 20l1-1" /></>
              : <><path d="M7 3h8l4 4v14H5V5a2 2 0 0 1 2-2z" /><path d="M15 3v4h4" /></>}
          </svg>
          {a.kind === "link" ? (
            <a href={a.url} target="_blank" rel="noreferrer"
               className="min-w-0 flex-1 truncate text-xs text-brand hover:underline">
              {a.label}
            </a>
          ) : (
            <span className="min-w-0 flex-1 truncate text-xs text-ink-2">
              {a.label}
              {a.size ? <span className="text-ink-3"> · {fmtSize(a.size)}</span> : null}
            </span>
          )}
          {!readOnly && onRemove && (
            <button onClick={() => onRemove(a)}
                    aria-label={`Remove ${a.label}`}
                    className="shrink-0 text-ink-3 transition hover:text-bad focus-ring">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
                   strokeLinecap="round" className="h-3.5 w-3.5">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

type PanelProps = {
  maxMb: number;
  maxItems: number;
  atLimit: boolean;
  busy: boolean;
  error: string;
  linkUrl: string;
  linkLabel: string;
  fileRef: React.RefObject<HTMLInputElement | null>;
  onFile: (f: File) => void;
  onLinkUrl: (v: string) => void;
  onLinkLabel: (v: string) => void;
  onAddLink: () => void;
  onClose: () => void;
};

/** Upload a file or paste a link. Hoisted out of the page component so React
 *  keeps the same instance between keystrokes and the inputs hold focus. */
function AttachPanel({
  maxMb, maxItems, atLimit, busy, error, linkUrl, linkLabel, fileRef,
  onFile, onLinkUrl, onLinkLabel, onAddLink, onClose,
}: PanelProps) {
  return (
    <div className="mt-2 rounded-lg bg-canvas p-3 ring-1 ring-inset ring-stroke">
      <p className="mb-2 text-xs font-medium text-ink-2">
        Upload a file, or paste a link to something already online.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={fileRef}
          type="file"
          disabled={busy || atLimit}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
          }}
          className="max-w-full text-xs text-ink-2 file:mr-2 file:rounded-md file:border-0 file:bg-brand file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-white hover:file:bg-brand-hover"
        />
        <span className="text-[11px] text-ink-3">up to {maxMb} MB each</span>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="min-w-48 flex-1">
          <span className="mb-1 block text-[11px] font-medium text-ink-2">Or paste a link</span>
          <input
            value={linkUrl}
            onChange={(e) => onLinkUrl(e.target.value)}
            placeholder="https://…"
            className="h-9 w-full rounded-lg bg-surface px-2.5 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring"
          />
        </label>
        <label className="min-w-36 flex-1">
          <span className="mb-1 block text-[11px] font-medium text-ink-2">
            What is it? <span className="font-normal text-ink-3">optional</span>
          </span>
          <input
            value={linkLabel}
            onChange={(e) => onLinkLabel(e.target.value)}
            placeholder="e.g. Our brand folder"
            className="h-9 w-full rounded-lg bg-surface px-2.5 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring"
          />
        </label>
        <button
          onClick={onAddLink}
          disabled={busy}
          className="h-9 shrink-0 rounded-lg bg-brand px-4 text-xs font-semibold text-white transition hover:bg-brand-hover disabled:opacity-60 focus-ring"
        >
          {busy ? "Adding…" : "Add link"}
        </button>
        <button
          onClick={onClose}
          className="h-9 shrink-0 rounded-lg px-3 text-xs font-medium text-ink-2 ring-control transition hover:bg-subtle focus-ring"
        >
          Close
        </button>
      </div>

      {error && <p className="mt-2 text-xs text-bad">{error}</p>}
      {atLimit && (
        <p className="mt-2 text-xs text-warnx">
          That is the limit of {maxItems} attachments. Remove one to add another.
        </p>
      )}
    </div>
  );
}

export default function ClientRequestPage() {
  const params = useParams<{ token: string }>();
  const token = params?.token;

  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  // Starts true so the first paint shows the loading state without the mount
  // effect having to set it synchronously.
  const [loading, setLoading] = useState(true);
  const [invalid, setInvalid] = useState(false);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  // Which question's attach panel is open; "" is the general one, null closed.
  const [attachFor, setAttachFor] = useState<string | null>(null);
  const [linkUrl, setLinkUrl] = useState("");
  const [linkLabel, setLinkLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachError, setAttachError] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const r = await fetch(`/api/public/client-request/${token}`);
      if (r.status === 404) {
        setInvalid(true);
        return;
      }
      if (!r.ok) throw new Error(String(r.status));
      const d: Sheet = await r.json();
      setSheet(d);
      setAnswers(d.answers ?? {});
      if (d.already_answered) setDone(true);
    } catch {
      setInvalid(true);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    // load() only updates state after awaiting the fetch, so nothing re-renders
    // synchronously here; the rule cannot see through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const total = sheet?.questions.length ?? 0;
  const answered = sheet
    ? sheet.questions.filter((q) => (answers[q] ?? "").trim()).length
    : 0;
  const pct = total ? Math.round((answered / total) * 100) : 0;
  const attachments = sheet?.attachments ?? [];
  const atLimit = sheet ? attachments.length >= sheet.max_attachments : false;

  const forQuestion = (q: string) => attachments.filter((a) => a.question === q);
  const general = attachments.filter((a) => !a.question);

  async function refreshSheet() {
    const r = await fetch(`/api/public/client-request/${token}`);
    if (r.ok) setSheet(await r.json());
  }

  async function attachFile(file: File, question: string) {
    setBusy(true);
    setAttachError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (question) fd.append("question", question);
      const r = await fetch(`/api/public/client-request/${token}/attach`, {
        method: "POST", body: fd,
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setAttachError(d.detail || "That file could not be uploaded.");
        return;
      }
      await refreshSheet();
      setAttachFor(null);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function attachLink(question: string) {
    const url = linkUrl.trim();
    if (!url) {
      setAttachError("Paste a link first.");
      return;
    }
    setBusy(true);
    setAttachError("");
    try {
      const fd = new FormData();
      fd.append("url", url);
      if (linkLabel.trim()) fd.append("label", linkLabel.trim());
      if (question) fd.append("question", question);
      const r = await fetch(`/api/public/client-request/${token}/attach`, {
        method: "POST", body: fd,
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setAttachError(d.detail || "That link could not be saved.");
        return;
      }
      setLinkUrl("");
      setLinkLabel("");
      await refreshSheet();
      setAttachFor(null);
    } finally {
      setBusy(false);
    }
  }

  async function removeAttachment(a: Attachment) {
    if (!confirm(`Remove "${a.label}"?`)) return;
    await fetch(`/api/public/client-request/${token}/attach/${a.id}/delete`, {
      method: "DELETE",
    });
    await refreshSheet();
  }

  async function submit() {
    if (!sheet) return;
    if (answered === 0 && attachments.length === 0) {
      setError("Please answer at least one question, or attach something, before sending.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const r = await fetch(`/api/public/client-request/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "Your answers could not be sent.");
      setDone(true);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Your answers could not be sent.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="min-h-screen bg-canvas pb-16">
      {/* ── Branded hero ── */}
      <header className="relative isolate overflow-hidden bg-[#0b1220]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/moc-banner.jpg"
          alt=""
          className="absolute inset-0 h-full w-full object-cover opacity-75"
          style={{ objectPosition: "62% 38%" }}
        />
        <div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-t from-[#0b1220] via-[#0b1220]/60 to-[#0b1220]/10"
        />
        <div className="relative mx-auto w-full max-w-3xl px-5 pb-8 pt-6 text-white">
          <Wordmark className="text-white" />

          {!loading && !invalid && sheet && (
            <>
              <p className="mt-7 text-[11px] font-semibold uppercase tracking-[0.14em] text-white/70">
                {sheet.kind_display} brief
              </p>
              <h1 className="mt-1.5 text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">
                {sheet.title}
              </h1>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-white/75">
                {sheet.client_name}
                {sheet.intro
                  ? ` — ${sheet.intro}`
                  : " — please answer the questions below so we can scope this accurately."}
              </p>
            </>
          )}
        </div>
      </header>

      <div className="mx-auto w-full max-w-3xl px-5">
        {loading ? (
          <div className="mt-6 rounded-xl bg-surface p-8 text-center text-sm text-ink-2 ring-panel">
            Loading your questions…
          </div>
        ) : invalid ? (
          <div className="mt-6 rounded-xl bg-surface p-8 text-center ring-panel">
            <h2 className="mb-2 text-lg font-semibold text-ink">This link is no longer valid</h2>
            <p className="text-sm text-ink-2">
              It may have been withdrawn or replaced. Reply to the email you received and
              we will send you a new one.
            </p>
          </div>
        ) : done ? (
          <div className="mt-6 overflow-hidden rounded-xl bg-surface ring-panel">
            <div className="border-b border-stroke p-8 text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-good-bg">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4}
                     strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6 text-good">
                  <path d="M20 6 9 17l-5-5" />
                </svg>
              </div>
              <h2 className="mb-1.5 text-lg font-semibold text-ink">
                Thank you — we have your answers
              </h2>
              <p className="text-sm text-ink-2">
                {sheet?.from_company} has been notified and will be in touch shortly.
                A copy of what you sent is below.
              </p>
            </div>
            {sheet && (
              <div className="divide-y divide-stroke">
                {sheet.questions.map((q, i) => (
                  <div key={i} className="p-4">
                    <p className="text-sm font-medium text-ink">{q}</p>
                    <p className={`mt-1 whitespace-pre-wrap text-sm ${
                      (answers[q] ?? "").trim() ? "text-ink-2" : "italic text-ink-3"
                    }`}>
                      {(answers[q] ?? "").trim() || "Not answered"}
                    </p>
                    <AttachList items={forQuestion(q)} readOnly />
                  </div>
                ))}
                {general.length > 0 && (
                  <div className="p-4">
                    <p className="text-sm font-medium text-ink">Other attachments</p>
                    <AttachList items={general} readOnly />
                  </div>
                )}
              </div>
            )}
          </div>
        ) : sheet ? (
          <>
            {/* Progress, sticky so it stays visible down a long sheet. */}
            <div className="sticky top-0 z-10 -mx-5 mb-1 border-b border-stroke bg-canvas/95 px-5 py-3 backdrop-blur">
              <div className="flex items-center gap-3">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-subtle">
                  <div
                    className="h-full rounded-full bg-brand transition-all duration-300"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="shrink-0 text-xs font-medium text-ink-2">
                  {answered} of {total} answered
                </span>
              </div>
            </div>

            <div className="mt-4 space-y-3">
              {sheet.questions.map((q, i) => {
                const filled = (answers[q] ?? "").trim().length > 0;
                const mine = forQuestion(q);
                const complete = filled || mine.length > 0;
                return (
                  <div
                    key={i}
                    className={`rounded-xl bg-surface p-4 ring-panel transition ${
                      complete ? "ring-good/30" : ""
                    }`}
                  >
                    <label className="mb-2 flex items-start gap-2.5 text-sm font-medium text-ink"
                           htmlFor={`q${i}`}>
                      <span className={`mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold transition ${
                        complete ? "bg-good text-white" : "bg-subtle text-ink-3"
                      }`}>
                        {complete ? "✓" : i + 1}
                      </span>
                      <span>{q}</span>
                    </label>
                    <textarea
                      id={`q${i}`}
                      rows={3}
                      value={answers[q] ?? ""}
                      onChange={(e) => setAnswers((cur) => ({ ...cur, [q]: e.target.value }))}
                      placeholder="Type your answer here…"
                      className="w-full resize-y rounded-lg bg-canvas px-3 py-2 text-sm text-ink ring-control placeholder:text-ink-3 focus-ring"
                    />

                    <AttachList items={mine} onRemove={(a) => void removeAttachment(a)} />

                    {attachFor !== q && (
                      <button
                        onClick={() => { setAttachFor(q); setAttachError(""); }}
                        className="mt-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-brand transition hover:bg-brand-tint focus-ring"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
                             strokeLinecap="round" className="h-3.5 w-3.5">
                          <path d="M12 5v14M5 12h14" />
                        </svg>
                        Attach a file or link
                      </button>
                    )}
                    {attachFor === q && (
                      <AttachPanel
                        maxMb={sheet.max_upload_mb}
                        maxItems={sheet.max_attachments}
                        atLimit={atLimit}
                        busy={busy}
                        error={attachError}
                        linkUrl={linkUrl}
                        linkLabel={linkLabel}
                        fileRef={fileRef}
                        onFile={(f) => void attachFile(f, q)}
                        onLinkUrl={setLinkUrl}
                        onLinkLabel={setLinkLabel}
                        onAddLink={() => void attachLink(q)}
                        onClose={() => { setAttachFor(null); setAttachError(""); }}
                      />
                    )}
                  </div>
                );
              })}
            </div>

            {/* Anything that does not belong to a single question. */}
            <div className="mt-3 rounded-xl bg-surface p-4 ring-panel">
              <p className="text-sm font-medium text-ink">Anything else that would help</p>
              <p className="mt-0.5 text-xs text-ink-3">
                Brand files, screenshots, documents, or a link to a folder — whatever gives
                us the fuller picture.
              </p>
              <AttachList items={general} onRemove={(a) => void removeAttachment(a)} />
              {attachFor !== "" && (
                <button
                  onClick={() => { setAttachFor(""); setAttachError(""); }}
                  className="mt-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-brand transition hover:bg-brand-tint focus-ring"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
                       strokeLinecap="round" className="h-3.5 w-3.5">
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                  Attach a file or link
                </button>
              )}
              {attachFor === "" && (
                <AttachPanel
                  maxMb={sheet.max_upload_mb}
                  maxItems={sheet.max_attachments}
                  atLimit={atLimit}
                  busy={busy}
                  error={attachError}
                  linkUrl={linkUrl}
                  linkLabel={linkLabel}
                  fileRef={fileRef}
                  onFile={(f) => void attachFile(f, "")}
                  onLinkUrl={setLinkUrl}
                  onLinkLabel={setLinkLabel}
                  onAddLink={() => void attachLink("")}
                  onClose={() => { setAttachFor(null); setAttachError(""); }}
                />
              )}
            </div>

            {error && (
              <p className="mt-4 rounded-lg bg-bad-bg px-3 py-2 text-sm text-bad">{error}</p>
            )}

            <div className="mt-5 flex flex-wrap items-center gap-3 rounded-xl bg-surface p-4 ring-panel">
              <button
                onClick={submit}
                disabled={saving}
                className="inline-flex h-11 items-center gap-2 rounded-lg bg-brand px-6 text-sm font-semibold text-white transition hover:bg-brand-hover disabled:opacity-60 focus-ring"
              >
                {saving ? "Sending…" : "Send my answers"}
              </button>
              <span className="text-sm text-ink-3">
                {answered === total
                  ? "All questions answered — thank you."
                  : `${total - answered} left unanswered. You can still send it.`}
              </span>
            </div>

            <p className="mt-5 text-center text-xs leading-relaxed text-ink-3">
              Answer what you can — we will follow up on anything you leave out.
              <br />
              This link is unique to you, so please do not forward it.
            </p>
          </>
        ) : null}

        <footer className="mt-10 border-t border-stroke pt-5 text-center">
          <p className="text-xs text-ink-3">
            {sheet?.from_company ?? "Magnum Opus Consultants"} · Everything you send here is
            treated as confidential.
          </p>
        </footer>
      </div>
    </main>
  );
}
