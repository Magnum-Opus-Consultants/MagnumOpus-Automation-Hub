"use client";

/**
 * Shared UI primitives for Sentinel, matched to the Helix admin panel
 * (Filament 5.6, amber primary): zinc-50 canvas, white panels edged with a
 * 5% ring instead of borders, rounded-xl cards, rounded-lg controls, Inter.
 * Tokens live in globals.css.
 */
import { useEffect, useState } from "react";
import { Sidebar, Icon, type Me } from "@/components/Sidebar";

/* ── Tone system ─────────────────────────────────────────────────────────── */
export type Tone = "neutral" | "info" | "good" | "warn" | "bad" | "accent";

export const TONE: Record<Tone, { badge: string; dot: string; text: string; bar: string; iconBg: string }> = {
  neutral: { badge: "bg-subtle text-ink-2 ring-ink/10", dot: "bg-ink-3", text: "text-ink-2", bar: "bg-ink-3", iconBg: "bg-subtle text-ink-2" },
  info:    { badge: "bg-infox-bg text-infox ring-infox/20", dot: "bg-infox", text: "text-infox", bar: "bg-infox", iconBg: "bg-infox-bg text-infox" },
  good:    { badge: "bg-good-bg text-good ring-good/20", dot: "bg-good", text: "text-good", bar: "bg-good", iconBg: "bg-good-bg text-good" },
  warn:    { badge: "bg-warnx-bg text-warnx ring-warnx/20", dot: "bg-warnx", text: "text-warnx", bar: "bg-warnx", iconBg: "bg-warnx-bg text-warnx" },
  bad:     { badge: "bg-bad-bg text-bad ring-bad/20", dot: "bg-bad", text: "text-bad", bar: "bg-bad", iconBg: "bg-bad-bg text-bad" },
  accent:  { badge: "bg-brand-tint text-brand-pressed ring-brand/20", dot: "bg-brand", text: "text-brand-pressed", bar: "bg-brand", iconBg: "bg-brand-tint text-brand-pressed" },
};

/* ── Shell ───────────────────────────────────────────────────────────────── */

const RAIL_KEY = "sentinel-sidebar-collapsed";

export function AppShell({
  active, me, children, wide,
}: {
  active: string;
  me: Me | null;
  children: React.ReactNode;
  wide?: boolean;
}) {
  // No topbar: the sidebar already shows which page is active, and page-level
  // actions belong to PageHead inside the content area.
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      // The stored preference is only readable on the client, so it cannot seed
      // useState without risking an SSR/client mismatch.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (localStorage.getItem(RAIL_KEY) === "1") setCollapsed(true);
    } catch {
      // No storage (private window, blocked site data) — stay expanded.
    }
  }, []);

  function setRail(next: boolean) {
    setCollapsed(next);
    try {
      localStorage.setItem(RAIL_KEY, next ? "1" : "0");
    } catch {
      // Preference just won't persist.
    }
  }

  return (
    <div className="flex min-h-screen bg-canvas text-ink">
      {collapsed ? (
        // Collapsed to a slim rail rather than removed entirely: the way back is
        // always visible and in the same place, so it reads as closed, not broken.
        <aside className="sticky top-0 hidden h-screen w-12 shrink-0 flex-col items-center self-start border-r border-stroke bg-nav py-2 lg:flex">
          <button
            onClick={() => setRail(false)}
            title="Expand sidebar"
            aria-label="Show sidebar"
            className="flex h-8 w-8 items-center justify-center rounded-md text-ink-2 transition hover:bg-subtle hover:text-ink focus-ring"
          >
            <Icon name="expand" className="h-4 w-4" />
          </button>
        </aside>
      ) : (
        <Sidebar active={active} me={me} onCollapse={() => setRail(true)} />
      )}
      <main className={`mx-auto w-full min-w-0 flex-1 px-5 py-4 ${wide ? "max-w-[1600px]" : "max-w-7xl"}`}>
        {children}
      </main>
    </div>
  );
}

export function PageHead({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0">
        <h1 className="text-lg font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="text-sm text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-1.5">{actions}</div>}
    </div>
  );
}

/* ── Surfaces ────────────────────────────────────────────────────────────── */

export function Section({ title, right, children, className = "" }: { title?: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl bg-surface ring-panel ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between gap-3 border-b border-stroke px-4 py-2.5">
          {title && <h3 className="text-sm font-semibold text-ink">{title}</h3>}
          {right}
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
}

export function Row({ k, v, mono }: { k: string; v?: string | number | null; mono?: boolean }) {
  if (v === null || v === undefined || v === "") return null;
  return (
    <div className="flex justify-between gap-4 border-b border-stroke py-2 text-sm last:border-0">
      <span className="shrink-0 text-ink-2">{k}</span>
      <span className={`text-right font-medium text-ink ${mono ? "break-all font-mono text-xs font-normal" : ""}`}>{v}</span>
    </div>
  );
}

export function StatTile({ label, value, hint, tone = "neutral", icon }: { label: string; value: React.ReactNode; hint?: string; tone?: Tone; icon?: string }) {
  const t = TONE[tone];
  return (
    <div className="rounded-lg bg-surface px-4 py-3.5 ring-panel">
      <div className="flex items-center gap-2">
        <span className="truncate text-xs font-medium uppercase tracking-wide text-ink-3">{label}</span>
        {icon && <Icon name={icon} className="ml-auto h-4 w-4 shrink-0 text-ink-3" />}
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums text-ink">{value}</span>
        {hint && (
          <span className={`truncate text-xs ${tone === "neutral" ? "text-ink-3" : t.text}`}>{hint}</span>
        )}
      </div>
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: React.ReactNode }) {
  return <span className={`inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset ${TONE[tone].badge}`}>{children}</span>;
}

export function EmptyState({ icon = "folder", title, hint, action }: { icon?: string; title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-surface px-6 py-10 text-center ring-panel">
      <Icon name={icon} className="mx-auto h-5 w-5 text-ink-3" />
      <p className="mt-2 text-sm font-semibold text-ink">{title}</p>
      {hint && <p className="mx-auto mt-0.5 max-w-md text-sm text-ink-2">{hint}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

/* ── Controls ────────────────────────────────────────────────────────────── */

const BTN_BASE = "inline-flex items-center justify-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition disabled:opacity-70 disabled:cursor-not-allowed focus-ring";

export function Button({
  variant = "secondary", icon, spinning, children, ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost"; icon?: string; spinning?: boolean }) {
  const styles = {
    primary: "bg-brand text-white shadow-sm hover:bg-brand-hover",
    secondary: "bg-surface text-ink ring-control hover:bg-subtle",
    danger: "bg-surface text-bad ring-control hover:bg-bad-bg",
    // Icon-only / inline action: no chrome until hover
    ghost: "text-ink-2 hover:bg-subtle hover:text-ink",
  }[variant];
  return (
    <button {...rest} className={`${BTN_BASE} ${styles} ${rest.className ?? ""}`}>
      {icon && <Icon name={icon} className={`h-4 w-4 ${spinning ? "animate-spin" : ""}`} />}
      {children}
    </button>
  );
}

/** Command-bar button: flat, icon + label, for the strip under the app bar. */
export function Command({ icon, spinning, children, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { icon?: string; spinning?: boolean }) {
  return (
    <button
      {...rest}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold text-ink transition hover:bg-subtle disabled:opacity-70 focus-ring ${rest.className ?? ""}`}
    >
      {icon && <Icon name={icon} className={`h-4 w-4 text-brand ${spinning ? "animate-spin" : ""}`} />}
      {children}
    </button>
  );
}

/* Fluent inputs: 1px stroke that darkens at the bottom, brand underline on focus. */
const FIELD =
  "mt-1.5 w-full rounded-lg border-0 bg-surface px-3 py-1.5 text-sm text-ink outline-none ring-control transition " +
  "placeholder:text-ink-3 focus:ring-2 focus:ring-brand";

function Label({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium leading-6 text-ink">
        {label}
        {hint && <span className="font-normal text-ink-3"> · {hint}</span>}
      </span>
      {children}
    </label>
  );
}

export function TextInput({ label, value, onChange, hint, type = "text", placeholder }: { label: string; value: string; onChange: (v: string) => void; hint?: string; type?: string; placeholder?: string }) {
  return (
    <Label label={label} hint={hint}>
      <input type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={FIELD} />
    </Label>
  );
}

export function AreaInput({ label, value, onChange, hint, rows = 4 }: { label: string; value: string; onChange: (v: string) => void; hint?: string; rows?: number }) {
  return (
    <Label label={label} hint={hint}>
      <textarea value={value} rows={rows} onChange={(e) => onChange(e.target.value)} className={FIELD} />
    </Label>
  );
}

export function SelectInput({ label, value, onChange, options, hint }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; hint?: string }) {
  return (
    <Label label={label} hint={hint}>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={FIELD}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Label>
  );
}

export function CheckboxInput({ label, checked, onChange, hint }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 pt-7">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-0 text-brand ring-control focus:ring-2 focus:ring-brand" />
      <span className="text-sm text-ink">
        {label}
        {hint && <span className="block text-xs text-ink-3">{hint}</span>}
      </span>
    </label>
  );
}

/** Fluent pill filter, as used in Office list views. */
export function Pill({ active, children, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button
      {...rest}
      className={`shrink-0 rounded-lg px-3 py-1.5 text-sm font-semibold capitalize transition focus-ring ${
        active ? "bg-brand text-white shadow-sm" : "bg-surface text-ink-2 ring-control hover:bg-subtle hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

/* ── Dialog ──────────────────────────────────────────────────────────────── */

export function Modal({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 sm:p-10">
      <div className={`w-full rounded-xl bg-surface shadow-2xl ring-panel ${wide ? "max-w-4xl" : "max-w-2xl"}`}>
        <div className="flex items-start justify-between gap-4 px-6 pt-6 pb-4">
          <h2 className="text-base font-semibold leading-6 text-ink">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="-mr-2 -mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-2 transition hover:bg-subtle hover:text-ink focus-ring">
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round"><path d="M4 4l12 12M16 4L4 16" /></svg>
          </button>
        </div>
        <div className="max-h-[68vh] overflow-y-auto px-6 pb-2">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */

/** "3 days ago" / "in 12 days" from an ISO string. */
export function relativeTime(iso?: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const secs = Math.round((Date.now() - then) / 1000);
  const future = secs < 0;
  const a = Math.abs(secs);
  const units: [number, string][] = [[60, "second"], [60, "minute"], [24, "hour"], [7, "day"], [4.35, "week"], [12, "month"]];
  let v = a;
  let unit = "second";
  for (const [step, name] of units) {
    if (v < step) { unit = name; break; }
    v = v / step;
    unit = name;
  }
  if (a < 45) return future ? "in a moment" : "just now";
  const n = Math.round(v);
  const label = `${n} ${unit}${n === 1 ? "" : "s"}`;
  return future ? `in ${label}` : `${label} ago`;
}

/** Tone for a countdown in days: past = bad, <30 = warn, else good. */
export function expiryTone(days: number | null | undefined): Tone {
  if (days === null || days === undefined) return "neutral";
  if (days < 0) return "bad";
  if (days <= 30) return "warn";
  if (days <= 90) return "info";
  return "good";
}

export function expiryLabel(days: number | null | undefined): string {
  if (days === null || days === undefined) return "Not set";
  if (days < 0) return `Expired ${Math.abs(days)}d ago`;
  if (days === 0) return "Expires today";
  return `${days}d left`;
}
