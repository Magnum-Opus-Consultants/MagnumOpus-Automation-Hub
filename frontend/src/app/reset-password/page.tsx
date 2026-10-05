"use client";

/* Choose a new password, from the link in a reset email.
 *
 * Public - the person isn't signed in, which is the point. The link carries a
 * user id and a one-time token; the page checks it first so an expired link
 * says so before anyone types a password, then sets the new one. */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Logo } from "@/components/Sidebar";

type Check = { valid: boolean; username?: string; min_length?: number; detail?: string };

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<Shell><p className="text-sm text-ink-3">Checking your link…</p></Shell>}>
      <ResetPassword />
    </Suspense>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <Logo className="h-7 w-7" />
          <span className="text-lg font-semibold tracking-tight text-ink">Sentinel</span>
        </div>
        <div className="rounded-xl bg-surface p-6 ring-panel">{children}</div>
      </div>
    </main>
  );
}

function ResetPassword() {
  const params = useSearchParams();
  const uid = params.get("uid") ?? "";
  const token = params.get("token") ?? "";
  const [check, setCheck] = useState<Check | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!uid || !token) return;
    fetch(`/api/auth/password-reset/check?uid=${encodeURIComponent(uid)}&token=${encodeURIComponent(token)}`)
      .then((r) => r.json())
      .then((d: Check) => setCheck(d))
      .catch(() => setCheck({ valid: false, detail: "Could not reach Sentinel. Try again in a minute." }));
  }, [uid, token]);

  const min = check?.min_length ?? 8;
  const rules = [
    { ok: password.length >= min, text: `At least ${min} characters` },
    { ok: password.length > 0 && !/^\d+$/.test(password), text: "Letters as well as numbers" },
    { ok: confirm.length > 0 && confirm === password, text: "Both boxes match" },
  ];
  const ready = rules.every((r) => r.ok);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError("");
    try {
      const r = await fetch("/api/auth/password-reset/confirm", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uid, token, password }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { setError(d.detail || "That didn't work. Try again."); return; }
      setDone(true);
    } catch {
      setError("Could not reach Sentinel. Try again in a minute.");
    } finally {
      setBusy(false);
    }
  }

  if (!uid || !token || (check && !check.valid)) {
    return (
      <Shell>
        <h1 className="text-base font-semibold text-ink">This link doesn&apos;t work any more</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          {check?.detail || "Reset links work once and expire after a few days. Ask an administrator to send you a new one."}
        </p>
        <a href="/login" className="mt-5 inline-block text-sm font-medium text-brand hover:underline">Go to sign in</a>
      </Shell>
    );
  }

  if (!check) {
    return <Shell><p className="text-sm text-ink-3">Checking your link…</p></Shell>;
  }

  if (done) {
    return (
      <Shell>
        <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-full bg-good-bg text-good">✓</div>
        <h1 className="text-base font-semibold text-ink">Password changed</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          You can now sign in as <b className="font-medium text-ink">{check.username}</b> with your new password.
        </p>
        <a href="/login"
           className="mt-5 inline-flex w-full justify-center rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">
          Sign in
        </a>
      </Shell>
    );
  }

  const field = "mt-1.5 w-full rounded-lg border-0 bg-surface px-3 py-2 text-sm text-ink outline-none ring-control transition placeholder:text-ink-3 focus:ring-2 focus:ring-brand";
  return (
    <Shell>
      <h1 className="text-base font-semibold text-ink">Choose a new password</h1>
      <p className="mt-1 text-sm text-ink-2">
        For <b className="font-medium text-ink">{check.username}</b>
      </p>
      <form onSubmit={submit} className="mt-5 space-y-4">
        {/* Lets password managers save the new password against the right login. */}
        <input type="text" name="username" autoComplete="username" value={check.username} readOnly hidden />
        <label className="block text-sm font-medium text-ink">
          New password
          <input type={show ? "text" : "password"} value={password} autoComplete="new-password" autoFocus
                 onChange={(e) => setPassword(e.target.value)} className={field} />
        </label>
        <label className="block text-sm font-medium text-ink">
          Type it again
          <input type={show ? "text" : "password"} value={confirm} autoComplete="new-password"
                 onChange={(e) => setConfirm(e.target.value)} className={field} />
        </label>
        <label className="flex items-center gap-2 text-xs text-ink-2">
          <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
          Show passwords
        </label>
        <ul className="space-y-1">
          {rules.map((r) => (
            <li key={r.text} className={`flex items-center gap-2 text-xs ${r.ok ? "text-good" : "text-ink-3"}`}>
              <span aria-hidden className={`flex h-3.5 w-3.5 items-center justify-center rounded-full text-[9px] ${
                r.ok ? "bg-good text-white" : "ring-1 ring-stroke"}`}>{r.ok ? "✓" : ""}</span>
              {r.text}
            </li>
          ))}
        </ul>
        {error && <p className="text-sm text-bad">{error}</p>}
        <button type="submit" disabled={!ready || busy}
                className="w-full rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-hover disabled:opacity-50">
          {busy ? "Saving…" : "Set new password"}
        </button>
      </form>
    </Shell>
  );
}
