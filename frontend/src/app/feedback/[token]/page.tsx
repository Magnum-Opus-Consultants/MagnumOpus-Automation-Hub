"use client";

/**
 * The public feedback form for one project.
 *
 * For anybody who uses the system a project delivers - an inspector, a
 * supervisor, a clerk - to report a problem, ask for a change, suggest
 * something or ask a question, with screenshots. Reached by a link with no
 * login, so like the client request sheets it shows nothing of the Sentinel
 * shell: just who is asking and the form.
 */
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";

type Info = {
  project: string; client: string;
  kinds: { value: string; label: string }[];
  max_files: number; max_mb: number;
};

function Wordmark() {
  return (
    <span className="inline-flex items-center gap-2.5 text-white">
      <svg viewBox="0 0 32 32" className="h-7 w-7 shrink-0" aria-hidden>
        <path d="M16 2.6 27 6.4v9.1c0 6.9-4.5 11.6-11 13.9-6.5-2.3-11-7-11-13.9V6.4L16 2.6Z"
              fill="currentColor" opacity="0.95" />
        <path d="M10.2 17.6l3.3-3.6 2.7 2.6 4.4-5.2" fill="none" stroke="#0b1220"
              strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="leading-tight">
        <span className="block text-sm font-semibold tracking-tight">Magnum Opus Consultants</span>
        <span className="block text-[11px] opacity-75">Software · Systems · Reporting</span>
      </span>
    </span>
  );
}

const field = "mt-1.5 w-full rounded-lg bg-surface px-3 py-2 text-sm text-ink ring-control placeholder:text-ink-3 focus:outline-none focus:ring-2 focus:ring-brand";

export default function FeedbackFormPage() {
  const params = useParams<{ token: string }>();
  const token = Array.isArray(params?.token) ? params.token[0] : params?.token ?? "";
  const [info, setInfo] = useState<Info | null>(null);
  const [invalid, setInvalid] = useState(false);
  const [kind, setKind] = useState("problem");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [area, setArea] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState<{ reference: number; warning: string } | null>(null);
  const trap = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`/api/public/feedback/${encodeURIComponent(token)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d: Info) => setInfo(d))
      .catch(() => setInvalid(true));
  }, [token]);

  // Screenshots can be pasted straight in - the quickest way to send one.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const pasted = Array.from(e.clipboardData?.files ?? []).filter((f) => f.type.startsWith("image/"));
      if (pasted.length) addFiles(pasted.map((f, i) =>
        new File([f], f.name && f.name !== "image.png" ? f.name : `pasted-${Date.now()}-${i}.png`, { type: f.type })));
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  });

  function addFiles(list: File[]) {
    if (!info) return;
    setError("");
    const images = list.filter((f) => f.type.startsWith("image/"));
    const tooBig = images.find((f) => f.size > info.max_mb * 1024 * 1024);
    if (tooBig) setError(`"${tooBig.name}" is over ${info.max_mb} MB.`);
    setFiles((cur) => [...cur, ...images.filter((f) => f.size <= info.max_mb * 1024 * 1024)]
      .slice(0, info.max_files));
  }

  async function submit() {
    if (!title.trim()) {
      setError("Give it a short title.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      Object.entries({ kind, title, description, area, name, email, role,
                       website: trap.current?.value ?? "" })
        .forEach(([k, v]) => body.append(k, v));
      files.forEach((f) => body.append("screenshots", f));
      const r = await fetch(`/api/public/feedback/${encodeURIComponent(token)}`, { method: "POST", body });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(d.detail || "That did not send. Please try again.");
        return;
      }
      setSent({ reference: d.reference, warning: d.warning || "" });
    } finally {
      setBusy(false);
    }
  }

  function another() {
    setSent(null);
    setTitle("");
    setDescription("");
    setArea("");
    setFiles([]);
  }

  return (
    <main className="min-h-screen bg-canvas pb-16">
      <header className="relative isolate overflow-hidden bg-[#0b1220]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/moc-banner.jpg" alt="" className="absolute inset-0 h-full w-full object-cover opacity-75"
             style={{ objectPosition: "62% 38%" }} />
        <div aria-hidden className="absolute inset-0 bg-gradient-to-t from-[#0b1220] via-[#0b1220]/60 to-[#0b1220]/10" />
        <div className="relative mx-auto w-full max-w-2xl px-5 pb-8 pt-6 text-white">
          <Wordmark />
          {info && (
            <>
              <p className="mt-7 text-[11px] font-semibold uppercase tracking-[0.14em] text-white/70">Feedback</p>
              <h1 className="mt-1.5 text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">{info.project}</h1>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-white/75">
                Tell us what is not working, what you would like changed, or ask a question.
                Screenshots help a lot - you can paste them straight in.
              </p>
            </>
          )}
        </div>
      </header>

      <div className="mx-auto w-full max-w-2xl px-5">
        {invalid ? (
          <div className="mt-8 rounded-xl bg-surface p-6 text-center ring-panel">
            <p className="font-semibold text-ink">This feedback link is not valid any more.</p>
            <p className="mt-1 text-sm text-ink-2">Ask the person who sent it to you for a new one.</p>
          </div>
        ) : !info ? (
          <p className="mt-8 text-sm text-ink-2">Loading…</p>
        ) : sent ? (
          <div className="mt-8 rounded-xl bg-surface p-6 text-center ring-panel">
            <p className="text-lg font-semibold text-ink">Thank you - it has been sent.</p>
            <p className="mt-1 text-sm text-ink-2">
              Your reference is <span className="font-semibold text-ink">#{sent.reference}</span>.
              {email.trim() ? " We will reply to the address you gave if we need more." : ""}
            </p>
            {sent.warning && <p className="mt-3 text-xs text-warnx">{sent.warning}</p>}
            <button onClick={another}
                    className="mt-5 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">
              Send something else
            </button>
          </div>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); void submit(); }}
                className="mt-6 space-y-5 rounded-xl bg-surface p-5 ring-panel sm:p-6">
            <fieldset>
              <legend className="text-sm font-medium text-ink">What is it?</legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {info.kinds.map((k) => (
                  <label key={k.value}
                         className={`cursor-pointer rounded-lg px-3 py-1.5 text-sm font-medium ring-1 transition ${
                           kind === k.value ? "bg-brand text-white ring-brand" : "bg-surface text-ink-2 ring-stroke hover:bg-subtle"}`}>
                    <input type="radio" name="kind" value={k.value} checked={kind === k.value}
                           onChange={() => setKind(k.value)} className="sr-only" />
                    {k.label}
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="block text-sm font-medium text-ink">
              Title
              <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required
                     placeholder="In a few words" className={field} />
            </label>
            <label className="block text-sm font-medium text-ink">
              Details
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={5}
                        placeholder="What happened, what you expected, or what you would like instead"
                        className={field} />
            </label>
            <label className="block text-sm font-medium text-ink">
              Where in the system <span className="font-normal text-ink-3">(optional)</span>
              <input value={area} onChange={(e) => setArea(e.target.value)} maxLength={200}
                     placeholder="The screen, page or step" className={field} />
            </label>

            <div>
              <p className="text-sm font-medium text-ink">
                Screenshots <span className="font-normal text-ink-3">(up to {info.max_files}, {info.max_mb} MB each)</span>
              </p>
              <div onDragOver={(e) => e.preventDefault()}
                   onDrop={(e) => { e.preventDefault(); addFiles(Array.from(e.dataTransfer.files)); }}
                   onClick={() => picker.current?.click()}
                   className="mt-1.5 cursor-pointer rounded-lg border-2 border-dashed border-stroke px-4 py-5 text-center text-sm text-ink-2 hover:bg-subtle/60">
                Drop images here, click to choose, or paste a screenshot
                <input ref={picker} type="file" accept="image/*" multiple className="hidden"
                       onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
              </div>
              {files.length > 0 && (
                <ul className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
                  {files.map((f, i) => (
                    <li key={`${f.name}-${i}`} className="relative">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={URL.createObjectURL(f)} alt={f.name}
                           className="aspect-square w-full rounded-md object-cover ring-1 ring-stroke" />
                      <button type="button" aria-label={`Remove ${f.name}`}
                              onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))}
                              className="absolute right-1 top-1 rounded bg-black/60 px-1.5 text-xs text-white">✕</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <label className="block text-sm font-medium text-ink">
                Your name
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={150} className={field} />
              </label>
              <label className="block text-sm font-medium text-ink">
                Your role <span className="font-normal text-ink-3">(optional)</span>
                <input value={role} onChange={(e) => setRole(e.target.value)} maxLength={100}
                       placeholder="e.g. Supervisor" className={field} />
              </label>
              <label className="block text-sm font-medium text-ink">
                Email <span className="font-normal text-ink-3">(for a reply)</span>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
              </label>
            </div>

            {/* Left empty by people; only bots fill it in. */}
            <input ref={trap} name="website" tabIndex={-1} autoComplete="off" aria-hidden
                   className="absolute left-[-9999px] h-0 w-0 opacity-0" />

            {error && <p className="text-sm text-bad">{error}</p>}
            <button type="submit" disabled={busy}
                    className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-hover disabled:opacity-60 sm:w-auto">
              {busy ? "Sending…" : "Send feedback"}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
