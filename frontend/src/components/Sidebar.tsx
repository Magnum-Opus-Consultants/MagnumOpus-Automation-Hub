"use client";

import { ThemeToggle } from "@/components/ThemeToggle";

export function Icon({ name, className = "h-5 w-5" }: { name: string; className?: string }) {
  const p = { className, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (name) {
    case "home": return <svg {...p}><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /></svg>;
    case "analysis": return <svg {...p}><path d="M3 3v18h18" /><path d="M7 14l3-3 3 3 4-5" /></svg>;
    case "server": return <svg {...p}><rect x="3" y="4" width="18" height="7" rx="1.5" /><rect x="3" y="13" width="18" height="7" rx="1.5" /><path d="M7 7.5h.01M7 16.5h.01" /></svg>;
    case "monitoring": return <svg {...p}><path d="M3 12h4l2 6 4-14 2 8h6" /></svg>;
    case "docs": return <svg {...p}><path d="M6 2h9l5 5v15H6z" /><path d="M15 2v5h5M9 13h6M9 17h6" /></svg>;
    case "records": return <svg {...p}><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" /><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></svg>;
    case "stations": return <svg {...p}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></svg>;
    case "tasks": return <svg {...p}><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>;
    case "sync": return <svg {...p}><path d="M21 2v6h-6M3 22v-6h6" /><path d="M21 8a9 9 0 0 0-15-3L3 8M3 16a9 9 0 0 0 15 3l3-3" /></svg>;
    case "gantt": return <svg {...p}><path d="M8 6h10M6 12h12M10 18h8M4 4v16" /></svg>;
    case "building": return <svg {...p}><rect x="4" y="3" width="16" height="18" rx="1.5" /><path d="M9 7h.01M15 7h.01M9 11h.01M15 11h.01M9 15h.01M15 15h.01M10 21v-3h4v3" /></svg>;
    case "folder": return <svg {...p}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></svg>;
    case "file": return <svg {...p}><path d="M7 3h8l4 4v14H5V5a2 2 0 0 1 2-2z" /><path d="M15 3v4h4" /></svg>;
    case "upload": return <svg {...p}><path d="M12 15V4M8 8l4-4 4 4" /><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" /></svg>;
    case "download": return <svg {...p}><path d="M12 4v11M8 11l4 4 4-4" /><path d="M4 19h16" /></svg>;
    case "trash": return <svg {...p}><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13h10l1-13" /></svg>;
    case "plus": return <svg {...p}><path d="M12 5v14M5 12h14" /></svg>;
    case "back": return <svg {...p}><path d="M15 18l-6-6 6-6" /></svg>;
    case "users": return <svg {...p}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></svg>;
    case "shield": return <svg {...p}><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z" /><path d="M9 12l2 2 4-4" /></svg>;
    case "edit": return <svg {...p}><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>;
    case "globe": return <svg {...p}><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18" /></svg>;
    case "mail": return <svg {...p}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></svg>;
    case "phone": return <svg {...p}><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2 4.2 2 2 0 0 1 4 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 10a16 16 0 0 0 6 6l1.3-1.4a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7A2 2 0 0 1 22 16.9z" /></svg>;
    case "git": return <svg {...p}><circle cx="6" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="9" r="2.5" /><path d="M6 8.5v7M8.5 6.8A6 6 0 0 0 15.6 9M18 11.5c0 4-3.6 4.6-9.6 5.9" /></svg>;
    case "commit": return <svg {...p}><circle cx="12" cy="12" r="3.5" /><path d="M2 12h6.5M15.5 12H22" /></svg>;
    case "branch": return <svg {...p}><circle cx="7" cy="5" r="2.2" /><circle cx="7" cy="19" r="2.2" /><circle cx="17" cy="9" r="2.2" /><path d="M7 7.2v9.6M9.2 5h3.3a2.5 2.5 0 0 1 2.5 2.5v0" /></svg>;
    case "board": return <svg {...p}><rect x="3" y="4" width="5.5" height="16" rx="1.4" /><rect x="9.75" y="4" width="5.5" height="11" rx="1.4" /><rect x="16.5" y="4" width="4.5" height="7" rx="1.4" /></svg>;
    case "calendar": return <svg {...p}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></svg>;
    case "clock": return <svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7.5V12l3 2" /></svg>;
    case "lock": return <svg {...p}><rect x="4" y="10.5" width="16" height="10.5" rx="2" /><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5" /></svg>;
    case "alert": return <svg {...p}><path d="M12 3.5 2.5 20h19z" /><path d="M12 9.5v5M12 17.5h.01" /></svg>;
    case "chevron": return <svg {...p}><path d="m6 15 6-6 6 6" /></svg>;
    case "collapse": return <svg {...p}><path d="M15 6l-6 6 6 6" /><path d="M4 4v16" /></svg>;
    case "expand": return <svg {...p}><path d="M9 6l6 6-6 6" /><path d="M20 4v16" /></svg>;
    case "signout": return <svg {...p}><path d="M15 17l5-5-5-5" /><path d="M20 12H9" /><path d="M12 19H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6" /></svg>;
    default: return null;
  }
}

// Each item is gated by a module key (null = always visible). `admin` items show
// only to superusers. `section` groups items under a collapsible heading.
// Each item is gated by a module key (null = always visible). `admin` items show
// only to superusers. `section` groups items under a collapsible heading.
//
// Scoped to Data Analysis for now. The other pages (servers, domains, repos,
// documentation, users, reporting, dashboard) still exist and their routes work
// directly — they are simply not surfaced in the navigation.
const NAV: { label: string; href: string; module: string | null; admin?: boolean; section: string; soon?: boolean }[] = [
  { label: "Data Analysis", href: "/data-analysis", module: "data", section: "Delivery" },
];

const SECTION_ORDER = ["Overview", "Infrastructure", "Delivery", "Administration"];

export type Me = {
  id?: number;
  username: string;
  full_name?: string;
  is_superuser: boolean;
  is_admin?: boolean;
  modules?: string[];
};

export function canAccess(me: Me | null, module: string | null): boolean {
  if (!me) return false;
  if (me.is_admin || me.is_superuser) return true;
  if (module === null) return true;
  return (me.modules ?? []).includes(module);
}

export function Sidebar({ active, me, onCollapse }: { active: string; me: Me | null; onCollapse?: () => void }) {
  const isAdmin = !!(me?.is_admin || me?.is_superuser);
  const initials = me?.username?.slice(0, 2).toUpperCase() ?? "··";

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  }

  const name = me?.full_name || (me ? me.username.charAt(0).toUpperCase() + me.username.slice(1) : "");
  const items = NAV.filter((item) => (item.admin ? isAdmin : canAccess(me, item.module)));
  const sections = SECTION_ORDER
    .map((s) => ({ name: s, items: items.filter((i) => i.section === s) }))
    .filter((s) => s.items.length > 0);

  // Flat list of links — no group headings, no per-group collapse.
  const links = sections.flatMap((sec) => sec.items);

  return (
    // Pinned to the viewport, not the page: without h-screen + sticky the rail
    // stretches to the full content height and its footer (identity, theme,
    // sign out) ends up below the fold on any long page.
    <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col self-start border-r border-stroke bg-nav lg:flex">
      {onCollapse && (
        <div className="flex h-10 shrink-0 items-center justify-end px-2">
          <button
            onClick={onCollapse}
            title="Collapse sidebar"
            aria-label="Collapse sidebar"
            className="flex h-7 w-7 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring"
          >
            <Icon name="collapse" className="h-4 w-4" />
          </button>
        </div>
      )}

      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        <ul className="space-y-px">
          {links.map((item) => (
            <li key={item.label}>
              <NavLink item={item} active={active} />
            </li>
          ))}
        </ul>
      </nav>

      <div className="shrink-0 border-t border-stroke p-2">
        <div className="flex items-center gap-2 px-1.5 py-1">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand text-[11px] font-semibold text-white">
            {initials}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-ink">{name || "…"}</p>
            <p className="truncate text-xs text-ink-3">{isAdmin ? "Administrator" : "Member"}</p>
          </div>
          <ThemeToggle />
          <button
            onClick={signOut}
            title="Sign out"
            aria-label="Sign out"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring"
          >
            <Icon name="signout" className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

/** Text-only nav row — no icons; active state is a brand label on a subtle fill. */
function NavLink({ item, active }: { item: { label: string; href: string; soon?: boolean }; active: string }) {
  const isActive = item.label === active;
  return (
    <a
      href={item.href}
      aria-current={isActive ? "page" : undefined}
      title={item.soon ? "Still under development" : undefined}
      className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition ${
        isActive
          ? "bg-subtle font-medium text-brand"
          : "text-ink-2 hover:bg-subtle/60 hover:text-ink"
      }`}
    >
      <span className="truncate">{item.label}</span>
      {item.soon && (
        <span className="ml-auto shrink-0 rounded bg-warnx-bg px-1 py-0.5 text-[10px] font-medium uppercase tracking-wide text-warnx">
          Soon
        </span>
      )}
    </a>
  );
}
