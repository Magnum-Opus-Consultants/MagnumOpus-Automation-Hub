"use client";

import { useState } from "react";

import { Logo } from "@/components/Sidebar";

const STATS = [
  { value: "24/7", label: "Monitoring" },
  { value: "1hr", label: "Sync cycle" },
  { value: "99.9%", label: "Uptime" },
];

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Invalid username or password.");
        setLoading(false);
        return;
      }
      // Play the success animation, then redirect.
      setSuccess(true);
      setTimeout(() => { window.location.href = "/data-analysis"; }, 1600);
    } catch {
      setError("Could not reach the server. Is the backend running?");
      setLoading(false);
    }
  }

  const displayName = username ? username.charAt(0).toUpperCase() + username.slice(1) : "";

  return (
    <main className="grid min-h-screen lg:grid-cols-2">
      {success && (
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-surface" style={{ animation: "sentinel-overlay .3s ease" }}>
          <div className="relative" style={{ animation: "sentinel-pop .55s cubic-bezier(.2,.8,.2,1)" }}>
            <span className="absolute inset-0 rounded-full bg-blue-400" style={{ animation: "sentinel-ring 1s ease-out .25s" }} />
            <div className="relative flex h-20 w-20 items-center justify-center rounded-full bg-brand-tint0 shadow-lg shadow-blue-500/40">
              <svg viewBox="0 0 52 52" className="h-10 w-10">
                <path d="M14 27l8 8 16-16" fill="none" stroke="white" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round"
                  style={{ strokeDasharray: 48, strokeDashoffset: 48, animation: "sentinel-check .45s ease-out .4s forwards" }} />
              </svg>
            </div>
          </div>
          <p className="mt-6 text-xl font-semibold tracking-tight text-ink" style={{ opacity: 0, animation: "sentinel-fade-up .5s ease-out .6s forwards" }}>
            Welcome back{displayName ? `, ${displayName}` : ""}
          </p>
          <p className="mt-1 text-sm text-ink-3" style={{ opacity: 0, animation: "sentinel-fade-up .5s ease-out .78s forwards" }}>
            Signing you in…
          </p>
        </div>
      )}
      {/* ── Left: brand hero ── */}
      {/* Themed gradient: brand tint -> surface -> canvas, so it works in both schemes. */}
      <section className="relative hidden overflow-hidden border-r border-stroke bg-gradient-to-br from-brand-tint via-surface to-canvas lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          aria-hidden
          className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 rounded-full bg-brand-tint0/20 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute bottom-0 right-0 h-80 w-80 rounded-full bg-brand/10 blur-3xl"
        />

        <div aria-hidden />

        <div className="relative">
          <h1 className="text-5xl font-bold leading-[1.05] tracking-tight text-ink">
            Every server.
            <br />
            <span className="text-brand">Always watched.</span>
          </h1>
          <p className="mt-6 max-w-md text-lg leading-relaxed text-ink-2">
            Management, monitoring, and documentation for every server you run —
            one platform, full visibility.
          </p>

          <div className="mt-12 flex gap-10">
            {STATS.map((s) => (
              <div key={s.label}>
                <div className="text-3xl font-bold text-ink">{s.value}</div>
                <div className="mt-1 text-sm text-ink-2">{s.label}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="relative flex items-center gap-2 text-sm text-ink-3">
          <Logo className="h-5 w-5" />
          Sentinel — Magnum Opus Consultants
        </div>
      </section>

      {/* ── Right: sign-in form ── */}
      <section className="flex flex-col items-center justify-center bg-subtle px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-10 flex items-center gap-2 lg:hidden">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-tint0 text-sm font-bold text-white">
              S
            </span>
            <span className="text-lg font-semibold tracking-tight text-ink">
              Sentinel
            </span>
          </div>

          <h2 className="text-2xl font-semibold tracking-tight text-ink">
            Welcome back
          </h2>
          <p className="mt-1 text-sm text-ink-2">Sign in to continue</p>

          <form onSubmit={onSubmit} className="mt-8 space-y-5">
            <div>
              <label
                htmlFor="username"
                className="block text-sm font-medium text-ink"
              >
                Username
              </label>
              <input
                id="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter your username"
                className="mt-1.5 block w-full rounded-lg border border-stroke bg-surface px-3.5 py-2.5 text-sm text-ink shadow-sm outline-none transition placeholder:text-ink-3 focus:border-brand focus:ring-2 focus:ring-brand"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-ink"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                className="mt-1.5 block w-full rounded-lg border border-stroke bg-surface px-3.5 py-2.5 text-sm text-ink shadow-sm outline-none transition placeholder:text-ink-3 focus:border-brand focus:ring-2 focus:ring-brand"
              />
            </div>

            {error && (
              <p className="text-sm text-red-600" role="alert">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-hover focus:outline-none focus:ring-2 focus:ring-blue-500/40 disabled:opacity-60"
            >
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="mt-10 text-center text-xs text-ink-3 lg:hidden">
            Sentinel — Magnum Opus Consultants
          </p>
        </div>
      </section>
    </main>
  );
}
