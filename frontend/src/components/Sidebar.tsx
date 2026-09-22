"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import { useTheme } from "@/components/ThemeToggle";
import { Collapse, Pop } from "@/components/motion";

/**
 * The Sentinel mark: a shield for "watched", with a rising sweep and a tick
 * inside it. Drawn as a filled path so it stays legible at 20px in the rail
 * and scales up cleanly for the sign-in page.
 */
/**
 * The Sentinel mark.
 *
 * The artwork is a raster supplied by the brand, keyed to a transparent ground
 * in `public/sentinel-mark.png` so it sits on the light rail and the dark one
 * without a box around it. `next/image` is skipped deliberately: this renders
 * at 28px in a fixed slot, where the optimiser's work is all cost and no
 * benefit, and it must be ready on first paint rather than lazily.
 */
export function Logo({ className = "h-8 w-8" }: { className?: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src="/sentinel-mark.png" alt="Sentinel" className={`${className} object-contain`} />
  );
}

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
    case "link": return <svg {...p}><path d="M10 13a5 5 0 0 0 7.07 0l2-2A5 5 0 0 0 12 4l-1 1" /><path d="M14 11a5 5 0 0 0-7.07 0l-2 2A5 5 0 0 0 12 20l1-1" /></svg>;
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
    case "check": return <svg {...p}><path d="M20 6 9 17l-5-5" /></svg>;
    case "pause": return <svg {...p}><path d="M10 5v14M14 5v14" /></svg>;
    case "inbox": return <svg {...p}><path d="M4 13h4l2 3h4l2-3h4" /><path d="M4 13 6.5 5h11L20 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" /></svg>;
    case "sun": return <svg {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" /></svg>;
    case "moon": return <svg {...p}><path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.5 6.5 0 0 0 9.8 9.8z" /></svg>;
    default: return null;
  }
}

// Each item is gated by a module key (null = always visible). `admin` items show
// only to superusers. `section` groups items under a collapsible heading.
// Each item is gated by a module key (null = always visible). `admin` items show
// only to superusers. `section` groups items under a collapsible heading.
//
// The other pages (servers, domains, repos, documentation, users, dashboard)
// still exist and their routes work directly — they are simply not surfaced in
// the navigation yet.
const NAV: { label: string; href: string; module: string | null; admin?: boolean; section: string; icon: string; soon?: boolean; projects?: boolean }[] = [
  { label: "Data Analysis", href: "/data-analysis", module: "data", section: "Operations", icon: "analysis" },
  { label: "Reporting", href: "/reporting", module: "data", section: "Operations", icon: "clock" },
  { label: "Project Tracker", href: "/tasks", module: "tasks", section: "Delivery", icon: "board", projects: true },
  { label: "Client Requests", href: "/client-requests", module: "client_requests", section: "Delivery", icon: "mail" },
  { label: "Repositories", href: "/repos", module: "repos", section: "Delivery", icon: "git" },
  { label: "Readiness Testing", href: "/readiness-testing", module: "system_testing", section: "Delivery", icon: "check" },
  { label: "Activity", href: "/activity", module: null, section: "Reference", icon: "clock" },
  { label: "Handbook", href: "/handbook", module: "handbook", section: "Reference", icon: "docs" },
  { label: "Users & Access", href: "/access", module: null, admin: true, section: "Administration", icon: "users" },
];

const SECTION_ORDER = ["Overview", "Operations", "Infrastructure", "Delivery",
                       "Reference", "Administration"];

/* Reference and Administration hold one row each. Four headings above seven
   rows is more structure than the structure is worth, so these two run
   together at the foot of the rail under a hairline instead of a caption. */
const TAIL_SECTIONS = ["Reference", "Administration"];

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

type ProjectLink = { name: string; open: number; total: number; lists: string[];
  color: string; icon: string; logo_url: string; workspace: string };
type MemberRow = { id: number; user_id: number; username: string; full_name: string;
  email: string; role: string; role_display: string; notified: boolean; added_by: string };
type UserRow = { id: number; username: string; full_name: string; email: string;
  is_superuser: boolean };

type WorkspaceLink = { name: string; color: string; icon: string; logo_url: string;
  is_default: boolean; projects: string[]; lists: string[] };

// Tailwind cannot see a colour built at runtime, so the classes are spelled out.
const PROJECT_DOT: Record<string, string> = {
  "": "text-ink-3",
  blue: "text-infox", green: "text-good", amber: "text-warnx", red: "text-bad",
  purple: "text-brand", teal: "text-good", pink: "text-bad", slate: "text-ink-2",
};
/**
 * The mark for a workspace or project: an uploaded logo wins, then an emoji
 * icon, then the built-in glyph. A logo that fails to load falls back rather
 * than leaving a broken-image box in the rail.
 */
function Badge({ logo, icon, fallback, color, className = "h-3.5 w-3.5" }: {
  logo?: string; icon?: string; fallback: string; color?: string; className?: string;
}) {
  const [broken, setBroken] = useState(false);
  if (logo && !broken) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={logo}
        alt=""
        onError={() => setBroken(true)}
        className={`${className} shrink-0 rounded-sm object-contain`}
      />
    );
  }
  if (icon) {
    return <span className={`${className} shrink-0 text-center leading-none`}>{icon}</span>;
  }
  return <Icon name={fallback} className={`${className} shrink-0 ${PROJECT_DOT[color ?? ""] ?? "text-ink-3"}`} />;
}

const COLOR_CHOICES = ["", "blue", "green", "amber", "red", "purple", "teal", "pink", "slate"];

export function Sidebar({ active, me, onCollapse }: { active: string; me: Me | null; onCollapse?: () => void }) {
  const isAdmin = !!(me?.is_admin || me?.is_superuser);
  const initials = me?.username?.slice(0, 2).toUpperCase() ?? "··";
  const [projects, setProjects] = useState<ProjectLink[] | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceLink[] | null>(null);
  // Workspaces are expanded by default, so this holds the collapsed ones.
  // The rail remounts on every navigation, so this is persisted - otherwise a
  // workspace you collapsed springs open again on the next click.
  const [collapsedWs, setCollapsedWs] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem("sentinel-collapsed-workspaces");
      // Read after mount, not in a lazy initialiser: this page is prerendered,
      // so touching localStorage during the first render would make the server
      // and client markup disagree.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (raw) setCollapsedWs(new Set(JSON.parse(raw) as string[]));
    } catch {
      // A blocked or corrupt store just means everything starts expanded.
    }
  }, []);
  const [wsMenu, setWsMenu] = useState<{ w: WorkspaceLink; x: number; y: number } | null>(null);
  const [renamingWs, setRenamingWs] = useState<{ name: string; value: string } | null>(null);
  const [newWs, setNewWs] = useState<{ name: string; color: string; error: string } | null>(null);
  const [newWsList, setNewWsList] = useState<{ workspace: string; name: string; error: string } | null>(null);
  const [newProject, setNewProject] = useState<{ workspace: string; name: string; error: string } | null>(null);
  const [members, setMembers] = useState<
    { workspace: string; rows: MemberRow[]; users: UserRow[]; roles: [string, string][];
      pick: string; role: string; error: string; note: string } | null>(null);
  const [branding, setBranding] = useState<
    { kind: "workspace" | "project"; name: string; icon: string; logo: string; error: string } | null>(null);
  // Right-click menu anchored at the pointer, ClickUp-style.
  const [menu, setMenu] = useState<{ p: ProjectLink; x: number; y: number } | null>(null);
  const [renaming, setRenaming] = useState<{ p: ProjectLink; value: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeWorkspace, setActiveWorkspace] = useState<string | null>(null);
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const [activeList, setActiveList] = useState<string | null>(null);

  // The rail sits outside the routed page, so it reads the selection from the
  // URL. `popstate` alone misses client-side pushes, so the pathname+search is
  // polled cheaply - without this the highlight sticks on the previous item.
  const search = typeof window === "undefined" ? "" : window.location.search;
  useEffect(() => {
    let last = "";
    const read = () => {
      const cur = window.location.search;
      if (cur === last) return;
      last = cur;
      const p = new URLSearchParams(cur);
      setActiveWorkspace(p.get("workspace"));
      setActiveProject(p.get("project"));
      setActiveList(p.get("list"));
    };
    read();
    const id = window.setInterval(read, 250);
    window.addEventListener("popstate", read);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("popstate", read);
    };
  }, [search]);

  const canTasks = canAccess(me, "tasks");

  const loadProjects = useCallback(() => {
    if (!canTasks) return;
    fetch("/api/tasks/projects")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => {
        setProjects(d.projects ?? []);
        setWorkspaces(d.workspaces ?? []);
      })
      .catch(() => {
        setProjects([]);
        setWorkspaces([]);
      });
  }, [canTasks]);

  // A click anywhere else closes the menu, as a context menu should.
  function toggleCollapsed(name: string) {
    setCollapsedWs((cur) => {
      const next = new Set(cur);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      try {
        window.localStorage.setItem(
          "sentinel-collapsed-workspaces", JSON.stringify([...next]));
      } catch {
        // Not worth failing the click over.
      }
      return next;
    });
  }

  async function saveWorkspace(body: Record<string, unknown>) {
    setBusy(true);
    try {
      const r = await fetch("/api/tasks/workspaces/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        alert(d.detail || "Could not save the workspace.");
        return false;
      }
      loadProjects();
      return true;
    } finally {
      setBusy(false);
    }
  }

  async function commitWsRename() {
    if (!renamingWs) return;
    const next = renamingWs.value.trim();
    if (!next || next === renamingWs.name) {
      setRenamingWs(null);
      return;
    }
    if (await saveWorkspace({ name: renamingWs.name, new_name: next })) {
      setRenamingWs(null);
    }
  }

  async function openMembers(wsName: string) {
    setWsMenu(null);
    setBusy(true);
    try {
      const r = await fetch(
        `/api/tasks/workspaces/members?workspace=${encodeURIComponent(wsName)}`);
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        alert(d.detail || "Could not load members.");
        return;
      }
      setMembers({
        workspace: wsName,
        rows: d.members?.[wsName] ?? [],
        users: d.users ?? [],
        roles: d.roles ?? [],
        pick: "",
        role: "member",
        error: "",
        note: "",
      });
    } finally {
      setBusy(false);
    }
  }

  async function reloadMembers(wsName: string, note = "") {
    const r = await fetch(
      `/api/tasks/workspaces/members?workspace=${encodeURIComponent(wsName)}`);
    const d = await r.json().catch(() => ({}));
    setMembers((cur) => cur && {
      ...cur,
      rows: d.members?.[wsName] ?? [],
      users: d.users ?? cur.users,
      pick: "",
      error: "",
      note,
    });
  }

  async function addMember() {
    if (!members) return;
    if (!members.pick) {
      setMembers({ ...members, error: "Pick someone to add." });
      return;
    }
    setBusy(true);
    try {
      const r = await fetch("/api/tasks/workspaces/members/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: members.workspace, user: members.pick, role: members.role,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setMembers({ ...members, error: d.detail || "Could not add that user." });
        return;
      }
      // Say plainly whether the person was actually emailed - a silent grant
      // looks identical to a delivered notification otherwise.
      const note = d.no_email_on_file
        ? `${d.username} was added, but has no email address on file so no notification was sent.`
        : d.notified
          ? `${d.username} was added and notified by email.`
          : `${d.username} was added, but the notification email failed to send.`;
      await reloadMembers(members.workspace, note);
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(row: MemberRow, role: string) {
    if (!members) return;
    setBusy(true);
    try {
      await fetch("/api/tasks/workspaces/members/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: members.workspace, user: row.username, role }),
      });
      await reloadMembers(members.workspace, `${row.username} is now a ${role}.`);
    } finally {
      setBusy(false);
    }
  }

  async function removeMember(row: MemberRow) {
    if (!members) return;
    if (!confirm(`Remove ${row.username} from ${members.workspace}?`)) return;
    setBusy(true);
    try {
      await fetch("/api/tasks/workspaces/members/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: members.workspace, user: row.username }),
      });
      await reloadMembers(members.workspace, `${row.username} was removed.`);
    } finally {
      setBusy(false);
    }
  }

  async function resendInvite(row: MemberRow) {
    if (!members) return;
    setBusy(true);
    try {
      const r = await fetch("/api/tasks/workspaces/members/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: members.workspace, user: row.username, role: row.role, notify: true,
        }),
      });
      const d = await r.json().catch(() => ({}));
      await reloadMembers(members.workspace,
        d.notified ? `Notification resent to ${row.username}.`
                   : `Could not email ${row.username}.`);
    } finally {
      setBusy(false);
    }
  }

  async function saveBranding() {
    if (!branding) return;
    setBusy(true);
    try {
      const url = branding.kind === "workspace"
        ? "/api/tasks/workspaces/save"
        : "/api/tasks/projects/update";
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: branding.name,
          icon: branding.icon,
          logo_url: branding.logo,
        }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setBranding({ ...branding, error: d.detail || "Could not save." });
        return;
      }
      setBranding(null);
      loadProjects();
    } finally {
      setBusy(false);
    }
  }

  async function createProject() {
    if (!newProject) return;
    const name = newProject.name.trim();
    if (!name) {
      setNewProject({ ...newProject, error: "Give the project a name." });
      return;
    }
    setBusy(true);
    try {
      const r = await fetch("/api/tasks/projects/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: newProject.workspace, name }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setNewProject({ ...newProject, error: d.detail || "Could not create the project." });
        return;
      }
      setNewProject(null);
      loadProjects();
    } finally {
      setBusy(false);
    }
  }

  async function createWorkspaceList() {
    if (!newWsList) return;
    const name = newWsList.name.trim();
    if (!name) {
      setNewWsList({ ...newWsList, error: "Give the list a name." });
      return;
    }
    setBusy(true);
    try {
      const r = await fetch("/api/tasks/lists/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: newWsList.workspace, name }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setNewWsList({ ...newWsList, error: d.detail || "Could not create the list." });
        return;
      }
      setNewWsList(null);
      loadProjects();
    } finally {
      setBusy(false);
    }
  }

  async function createWorkspace() {
    if (!newWs) return;
    const name = newWs.name.trim();
    if (!name) {
      setNewWs({ ...newWs, error: "Give the workspace a name." });
      return;
    }
    if ((workspaces ?? []).some((w) => w.name.toLowerCase() === name.toLowerCase())) {
      setNewWs({ ...newWs, error: "A workspace with that name already exists." });
      return;
    }
    if (await saveWorkspace({ name, color: newWs.color })) {
      setNewWs(null);
    }
  }

  async function deleteWorkspace(w: WorkspaceLink) {
    if (w.is_default) return;
    const n = w.projects.length;
    const msg = n
      ? `Delete workspace "${w.name}"?\n\nIts ${n} project(s) will move to the default workspace - no tasks are deleted.`
      : `Delete workspace "${w.name}"?`;
    if (!confirm(msg)) return;
    setBusy(true);
    try {
      const r = await fetch("/api/tasks/workspaces/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: w.name }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        alert(d.detail || "Could not delete the workspace.");
        return;
      }
      setWsMenu(null);
      loadProjects();
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!menu && !wsMenu) return;
    const close = () => {
      setMenu(null);
      setWsMenu(null);
    };
    window.addEventListener("click", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("keydown", close);
    };
  }, [menu, wsMenu]);

  async function setColor(p: ProjectLink, color: string) {
    setBusy(true);
    try {
      await fetch("/api/tasks/projects/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: p.name, color }),
      });
      setMenu(null);
      loadProjects();
    } finally {
      setBusy(false);
    }
  }

  async function commitRename() {
    if (!renaming) return;
    const next = renaming.value.trim();
    if (!next || next === renaming.p.name) {
      setRenaming(null);
      return;
    }
    setBusy(true);
    try {
      const r = await fetch("/api/tasks/projects/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: renaming.p.name, new_name: next }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        alert(d.detail || "Could not rename the project.");
        return;
      }
      setRenaming(null);
      loadProjects();
    } finally {
      setBusy(false);
    }
  }

  async function deleteProject(p: ProjectLink) {
    if (!confirm(`Delete "${p.name || "No project"}" and all ${p.total} of its tasks?

This cannot be undone.`)) return;
    setBusy(true);
    try {
      const r = await fetch("/api/tasks/projects/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: p.name, expected_tasks: p.total }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        alert(d.detail || "Could not delete the project.");
        return;
      }
      setMenu(null);
      loadProjects();
      // The page is showing that project, so send the user somewhere valid.
      if (window.location.search.includes(encodeURIComponent(p.name))) {
        window.location.href = "/tasks";
      }
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!canTasks) return;
    // Deliberately the light endpoint - the full task list would be thousands
    // of rows just to render a few links.
    fetch("/api/tasks/projects")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => {
        setProjects(d.projects ?? []);
        setWorkspaces(d.workspaces ?? []);
      })
      .catch(() => {
        setProjects([]);
        setWorkspaces([]);
      });
  }, [canTasks]);

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  }

  const name = me?.full_name || (me ? me.username.charAt(0).toUpperCase() + me.username.slice(1) : "");
  const items = NAV.filter((item) => (item.admin ? isAdmin : canAccess(me, item.module)));
  const sections = SECTION_ORDER
    .map((s) => ({ name: s, items: items.filter((i) => i.section === s) }))
    .filter((s) => s.items.length > 0);

  return (
    // Pinned to the viewport, not the page: without h-screen + sticky the rail
    // stretches to the full content height and its footer (identity, theme,
    // sign out) ends up below the fold on any long page.
    <aside
      // Fluent/Microsoft 365 rail: flat neutral surface, hairline divider,
      // 32px rows, small radii, and a 3px left accent on the active item.
      style={{ fontFamily: '"Segoe UI Variable", "Segoe UI", Inter, system-ui, sans-serif' }}
      // Width and the divider now belong to the animated wrapper in AppShell;
      // keeping them here too would fight it mid-transition.
      className="hidden h-full w-60 shrink-0 flex-col bg-nav lg:flex"
    >
      {/* Brand row doubles as the collapse control's home, so the rail has a
          proper header instead of a floating button. */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-stroke-soft px-3">
        <Logo className="h-7 w-7 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold leading-tight text-ink">Sentinel</p>
          <p className="truncate text-[11px] leading-tight text-ink-3">Magnum Opus</p>
        </div>
        {onCollapse && (
          <button
            onClick={onCollapse}
            title="Collapse sidebar"
            aria-label="Collapse sidebar"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring"
          >
            <Icon name="collapse" className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto px-1.5 py-2">
        {sections.map((sec, i) => {
          const tail = TAIL_SECTIONS.includes(sec.name);
          // Only the first of the tail pair draws the divider, or the two
          // single rows end up fenced off from each other as well.
          const firstTail = tail && !TAIL_SECTIONS.includes(sections[i - 1]?.name);
          return (
          <div key={sec.name}
               className={tail
                 ? (firstTail ? "mt-3 border-t border-stroke-soft pt-3" : "")
                 : "mb-4"}>
            {!tail && (
              <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
                {sec.name}
              </p>
            )}
            <ul className="space-y-0.5">
              {sec.items.map((item) => (
                <li key={item.label}>
                  {/* The tasks entry is not one link but one row per workspace:
                      a workspace is the level above projects, so it is what the
                      rail should list. */}
                  {item.projects ? (
                    <>
                    {/* The entry itself is always rendered. Previously this
                        branch emitted only the per-workspace rows, so when the
                        workspace list was empty - no workspaces yet, or the
                        projects fetch failed and was caught - Project Tracker
                        disappeared from the rail entirely with no way in. */}
                    <NavLink item={item} active={active} />
                    {(workspaces ?? []).map((w) => {
                      const wsProjects = (projects ?? []).filter((p) => p.workspace === w.name);
                      const wsOpen = !collapsedWs.has(w.name);
                      const isActive = activeWorkspace === w.name
                        && activeProject == null && activeList == null;
                      return (
                        <div key={w.name}>
                          {renamingWs?.name === w.name ? (
                            <input
                              autoFocus
                              value={renamingWs.value}
                              disabled={busy}
                              onChange={(e) => setRenamingWs({ ...renamingWs, value: e.target.value })}
                              onBlur={commitWsRename}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") void commitWsRename();
                                if (e.key === "Escape") setRenamingWs(null);
                              }}
                              className="mx-2 h-7 w-[calc(100%-1rem)] rounded bg-surface px-1.5 text-[13px] text-ink ring-control focus-ring"
                            />
                          ) : (
                            <div className="relative flex items-center">
                              <button
                                onClick={() => toggleCollapsed(w.name)}
                                aria-label={wsOpen ? "Collapse workspace" : "Expand workspace"}
                                className="absolute left-1 z-10 flex h-5 w-5 items-center justify-center rounded text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring"
                              >
                                <Icon name="chevron"
                                      className={`h-3 w-3 transition-transform ${wsOpen ? "" : "rotate-180"}`} />
                              </button>
                              <Link
                                href={`/tasks?workspace=${encodeURIComponent(w.name)}`}
                                title={`${w.name} - ${wsProjects.length} projects. Right-click for options.`}
                                onContextMenu={(e) => {
                                  e.preventDefault();
                                  setWsMenu({ w, x: e.clientX, y: e.clientY });
                                }}
                                className={`relative flex h-8 flex-1 items-center gap-2.5 rounded pl-7 pr-2 text-[13px] transition ${
                                  isActive
                                    ? "bg-brand-tint font-semibold text-ink"
                                    : "text-ink-2 hover:bg-subtle hover:text-ink"
                                }`}
                              >
                                <span aria-hidden
                                      className={`absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-sm ${
                                        isActive ? "bg-brand" : "bg-transparent"
                                      }`} />
                                <Badge logo={w.logo_url} icon={w.icon} fallback={item.icon}
                                       color={w.color} className="h-4 w-4" />
                                <span className="truncate">{w.name}</span>
                                <span className="ml-auto shrink-0 text-[11px] text-ink-3">
                                  {wsProjects.length}
                                </span>
                              </Link>
                            </div>
                          )}

                          <Collapse open={wsOpen && (w.lists ?? []).length > 0}>
                            <ul className="space-y-px">
                              {(w.lists ?? []).map((l) => (
                                <li key={`wsl-${l}`}>
                                  <Link
                                    href={`/tasks?workspace=${encodeURIComponent(w.name)}&list=${encodeURIComponent(l)}`}
                                    title={`List "${l}" in ${w.name}`}
                                    aria-current={activeList === l ? "page" : undefined}
                                    className={`flex h-7 items-center gap-1.5 rounded pl-8 pr-2 text-[13px] transition ${
                                      activeList === l
                                        ? "bg-brand-tint font-semibold text-ink"
                                        : "text-ink-2 hover:bg-subtle hover:text-ink"
                                    }`}
                                  >
                                    <Icon name="tasks" className="h-3.5 w-3.5 shrink-0 text-ink-3" />
                                    <span className="truncate">{l}</span>
                                  </Link>
                                </li>
                              ))}
                            </ul>
                          </Collapse>

                          <Collapse open={wsOpen && wsProjects.length > 0}>
                            <ul className="mb-1 space-y-px">
                              {wsProjects.map((p) => (
                                <li key={p.name || "__none__"}>
                                  {renaming?.p.name === p.name ? (
                                    <input
                                      autoFocus
                                      value={renaming.value}
                                      disabled={busy}
                                      onChange={(e) => setRenaming({ ...renaming, value: e.target.value })}
                                      onBlur={commitRename}
                                      onKeyDown={(e) => {
                                        if (e.key === "Enter") void commitRename();
                                        if (e.key === "Escape") setRenaming(null);
                                      }}
                                      className="ml-8 mr-2 h-6 w-[calc(100%-2.5rem)] rounded bg-surface px-1.5 text-xs text-ink ring-control focus-ring"
                                    />
                                  ) : (
                                    <Link
                                      href={`/tasks?project=${encodeURIComponent(p.name)}`}
                                      title={`${p.open} open of ${p.total} - right-click for options`}
                                      aria-current={activeProject === p.name ? "page" : undefined}
                                      onContextMenu={(e) => {
                                        e.preventDefault();
                                        setMenu({ p, x: e.clientX, y: e.clientY });
                                      }}
                                      className={`relative flex h-7 items-center gap-1.5 rounded pl-8 pr-2 text-[13px] transition ${
                                        activeProject === p.name
                                          ? "bg-brand-tint font-semibold text-ink"
                                          : "text-ink-2 hover:bg-subtle hover:text-ink"
                                      }`}
                                    >
                                      <span aria-hidden
                                            className={`absolute left-4 top-1/2 h-3.5 w-[3px] -translate-y-1/2 rounded-r-sm ${
                                              activeProject === p.name ? "bg-brand" : "bg-transparent"
                                            }`} />
                                      <Badge logo={p.logo_url} icon={p.icon} fallback="folder"
                                             color={p.color} />
                                      <span className="truncate">{p.name || "No project"}</span>
                                      {p.open > 0 && (
                                        <span className="ml-auto shrink-0 text-[11px] text-ink-3">{p.open}</span>
                                      )}
                                    </Link>
                                  )}
                                </li>
                              ))}
                            </ul>
                          </Collapse>
                        </div>
                      );
                    })}
                    </>
                  ) : (
                    <NavLink item={item} active={active} />
                  )}
                </li>
              ))}
            </ul>
          </div>
          );
        })}

      </nav>

      {members && (
        <>
          <button aria-label="Close" onClick={() => setMembers(null)}
                  className="fixed inset-0 z-[70] bg-black/40" />
          <div className="pointer-events-none fixed inset-0 z-[71] flex items-center justify-center p-4">
            <div
              role="dialog"
              aria-modal="true"
              aria-label="Members and access"
              className="pointer-events-auto flex max-h-[85vh] w-full max-w-lg flex-col rounded-lg bg-surface shadow-2xl ring-1 ring-stroke"
            >
              <header className="border-b border-stroke px-4 py-3">
                <h2 className="text-[15px] font-semibold text-ink">Members &amp; access</h2>
                <p className="mt-0.5 text-xs text-ink-3">
                  Who can reach <span className="font-medium text-ink-2">{members.workspace}</span>.
                  Access covers every project and list inside it.
                </p>
              </header>

              <div className="flex-1 overflow-y-auto px-4 py-3">
                {members.rows.length === 0 ? (
                  <p className="rounded bg-subtle/60 px-3 py-4 text-center text-xs text-ink-3">
                    Nobody has been added yet. Administrators can always see every workspace.
                  </p>
                ) : (
                  <ul className="divide-y divide-stroke rounded ring-panel">
                    {members.rows.map((row) => (
                      <li key={row.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand text-[10px] font-semibold text-white">
                          {row.username.slice(0, 2).toUpperCase()}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[13px] font-medium text-ink">
                            {row.full_name || row.username}
                          </p>
                          <p className="truncate text-[11px] text-ink-3">
                            {row.email || "no email on file"}
                            {row.email && (row.notified ? " · notified" : " · not notified")}
                          </p>
                        </div>
                        <select
                          value={row.role}
                          disabled={busy}
                          onChange={(e) => void changeRole(row, e.target.value)}
                          aria-label={`Role for ${row.username}`}
                          className="h-7 shrink-0 rounded bg-surface px-1.5 text-xs text-ink-2 ring-control focus-ring"
                        >
                          {members.roles.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                        {row.email && !row.notified && (
                          <button
                            onClick={() => void resendInvite(row)}
                            disabled={busy}
                            title="Send the notification again"
                            className="flex h-7 w-7 items-center justify-center rounded text-ink-3 transition hover:bg-subtle hover:text-brand focus-ring"
                          >
                            <Icon name="mail" className="h-3.5 w-3.5" />
                          </button>
                        )}
                        <button
                          onClick={() => void removeMember(row)}
                          disabled={busy}
                          title="Remove from this workspace"
                          className="flex h-7 w-7 items-center justify-center rounded text-ink-3 transition hover:bg-subtle hover:text-bad focus-ring"
                        >
                          <Icon name="trash" className="h-3.5 w-3.5" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}

                <div className="mt-4 rounded bg-subtle/50 p-3">
                  <p className="mb-2 text-xs font-semibold text-ink-2">Add someone</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={members.pick}
                      onChange={(e) => setMembers({ ...members, pick: e.target.value, error: "" })}
                      className="h-8 min-w-40 flex-1 rounded bg-surface px-2 text-xs text-ink ring-control focus-ring"
                    >
                      <option value="">Choose a user…</option>
                      {members.users
                        .filter((u) => !members.rows.some((r) => r.user_id === u.id))
                        .map((u) => (
                          <option key={u.id} value={u.username}>
                            {u.full_name || u.username}{u.email ? ` — ${u.email}` : " — no email"}
                          </option>
                        ))}
                    </select>
                    <select
                      value={members.role}
                      onChange={(e) => setMembers({ ...members, role: e.target.value })}
                      className="h-8 rounded bg-surface px-2 text-xs text-ink ring-control focus-ring"
                    >
                      {members.roles.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                    <button
                      onClick={() => void addMember()}
                      disabled={busy}
                      className="h-8 rounded bg-brand px-3 text-xs font-semibold text-white transition hover:bg-brand-hover disabled:opacity-60 focus-ring"
                    >
                      {busy ? "Adding…" : "Add & notify"}
                    </button>
                  </div>
                  <p className="mt-2 text-[11px] text-ink-3">
                    Viewer reads only · Member creates and edits tasks · Manager also manages
                    projects, lists and members. They are emailed when added.
                  </p>
                </div>

                {members.error && <p className="mt-3 text-xs text-bad">{members.error}</p>}
                {members.note && <p className="mt-3 text-xs text-good">{members.note}</p>}
              </div>

              <footer className="flex justify-end border-t border-stroke px-4 py-3">
                <button
                  onClick={() => setMembers(null)}
                  className="h-8 rounded px-3 text-[13px] font-medium text-ink-2 ring-control transition hover:bg-subtle focus-ring"
                >
                  Done
                </button>
              </footer>
            </div>
          </div>
        </>
      )}

      {branding && (
        <>
          <button aria-label="Close" onClick={() => setBranding(null)}
                  className="fixed inset-0 z-[70] bg-black/40" />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Icon and logo"
            className="fixed left-1/2 top-28 z-[71] w-full max-w-sm -translate-x-1/2 rounded-lg bg-surface p-4 shadow-2xl ring-1 ring-stroke"
          >
            <h2 className="text-[15px] font-semibold text-ink">Icon &amp; logo</h2>
            <p className="mb-4 mt-0.5 text-xs text-ink-3">
              For <span className="font-medium text-ink-2">{branding.name}</span>. A logo is used
              when set, otherwise the icon.
            </p>

            <label className="mb-1 block text-xs font-medium text-ink-2" htmlFor="br-icon">
              Icon
            </label>
            <div className="mb-1.5 flex flex-wrap gap-1.5">
              {["", "\u{1F6E1}", "\u{1F4CA}", "\u{1F5C2}", "\u{1F310}", "\u2699", "\u{1F680}",
                "\u{1F4E6}", "\u{1F4B8}", "\u{1F4C5}", "\u{1F527}", "\u2705"].map((e) => (
                <button
                  key={e || "none"}
                  onClick={() => setBranding({ ...branding, icon: e, error: "" })}
                  title={e || "None"}
                  className={`flex h-8 w-8 items-center justify-center rounded text-base ring-1 ring-inset transition hover:bg-subtle ${
                    branding.icon === e ? "bg-brand-tint ring-brand" : "ring-stroke"
                  }`}
                >
                  {e || <span className="text-[10px] text-ink-3">none</span>}
                </button>
              ))}
            </div>
            <input
              id="br-icon"
              value={branding.icon}
              maxLength={8}
              disabled={busy}
              onChange={(e) => setBranding({ ...branding, icon: e.target.value, error: "" })}
              placeholder="Or paste any emoji"
              className="h-9 w-full rounded bg-canvas px-2.5 text-[13px] text-ink ring-control placeholder:text-ink-3 focus-ring"
            />

            <label className="mb-1 mt-4 block text-xs font-medium text-ink-2" htmlFor="br-logo">
              Company logo URL
            </label>
            <input
              id="br-logo"
              value={branding.logo}
              disabled={busy}
              onChange={(e) => setBranding({ ...branding, logo: e.target.value, error: "" })}
              onKeyDown={(e) => {
                if (e.key === "Enter") void saveBranding();
                if (e.key === "Escape") setBranding(null);
              }}
              placeholder="https://example.com/logo.png"
              className="h-9 w-full rounded bg-canvas px-2.5 text-[13px] text-ink ring-control placeholder:text-ink-3 focus-ring"
            />
            {branding.logo && (
              <div className="mt-2 flex items-center gap-2 rounded bg-subtle/60 p-2">
                <Badge logo={branding.logo} icon={branding.icon} fallback="folder" className="h-6 w-6" />
                <span className="text-[11px] text-ink-3">Preview</span>
              </div>
            )}

            {branding.error && <p className="mt-3 text-xs text-bad">{branding.error}</p>}

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                onClick={() => setBranding(null)}
                className="h-8 rounded px-3 text-[13px] font-medium text-ink-2 ring-control transition hover:bg-subtle focus-ring"
              >
                Cancel
              </button>
              <button
                onClick={() => void saveBranding()}
                disabled={busy}
                className="h-8 rounded bg-brand px-3 text-[13px] font-semibold text-white transition hover:bg-brand-hover disabled:opacity-60 focus-ring"
              >
                {busy ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </>
      )}

      {newProject && (
        <>
          <button aria-label="Close" onClick={() => setNewProject(null)}
                  className="fixed inset-0 z-[70] bg-black/40" />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="New project"
            className="fixed left-1/2 top-28 z-[71] w-full max-w-sm -translate-x-1/2 rounded-lg bg-surface p-4 shadow-2xl ring-1 ring-stroke"
          >
            <h2 className="text-[15px] font-semibold text-ink">New project</h2>
            <p className="mb-4 mt-0.5 text-xs text-ink-3">
              A folder inside <span className="font-medium text-ink-2">{newProject.workspace}</span>.
              It can sit empty until there is something to put in it.
            </p>
            <label className="mb-1 block text-xs font-medium text-ink-2" htmlFor="proj-name">
              Project name
            </label>
            <input
              id="proj-name"
              autoFocus
              value={newProject.name}
              disabled={busy}
              onChange={(e) => setNewProject({ ...newProject, name: e.target.value, error: "" })}
              onKeyDown={(e) => {
                if (e.key === "Enter") void createProject();
                if (e.key === "Escape") setNewProject(null);
              }}
              placeholder="e.g. Documentation"
              className="h-9 w-full rounded bg-canvas px-2.5 text-[13px] text-ink ring-control placeholder:text-ink-3 focus-ring"
            />
            {newProject.error && <p className="mt-3 text-xs text-bad">{newProject.error}</p>}
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                onClick={() => setNewProject(null)}
                className="h-8 rounded px-3 text-[13px] font-medium text-ink-2 ring-control transition hover:bg-subtle focus-ring"
              >
                Cancel
              </button>
              <button
                onClick={() => void createProject()}
                disabled={busy}
                className="h-8 rounded bg-brand px-3 text-[13px] font-semibold text-white transition hover:bg-brand-hover disabled:opacity-60 focus-ring"
              >
                Create project
              </button>
            </div>
          </div>
        </>
      )}

      {newWsList && (
        <>
          <button aria-label="Close" onClick={() => setNewWsList(null)}
                  className="fixed inset-0 z-[70] bg-black/40" />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="New list"
            className="fixed left-1/2 top-28 z-[71] w-full max-w-sm -translate-x-1/2 rounded-lg bg-surface p-4 shadow-2xl ring-1 ring-stroke"
          >
            <h2 className="text-[15px] font-semibold text-ink">New list</h2>
            <p className="mb-4 mt-0.5 text-xs text-ink-3">
              Directly inside <span className="font-medium text-ink-2">{newWsList.workspace}</span> —
              it does not need to belong to a project.
            </p>
            <label className="mb-1 block text-xs font-medium text-ink-2" htmlFor="wsl-name">
              List name
            </label>
            <input
              id="wsl-name"
              autoFocus
              value={newWsList.name}
              disabled={busy}
              onChange={(e) => setNewWsList({ ...newWsList, name: e.target.value, error: "" })}
              onKeyDown={(e) => {
                if (e.key === "Enter") void createWorkspaceList();
                if (e.key === "Escape") setNewWsList(null);
              }}
              placeholder="e.g. This week"
              className="h-9 w-full rounded bg-canvas px-2.5 text-[13px] text-ink ring-control placeholder:text-ink-3 focus-ring"
            />
            {newWsList.error && <p className="mt-3 text-xs text-bad">{newWsList.error}</p>}
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                onClick={() => setNewWsList(null)}
                className="h-8 rounded px-3 text-[13px] font-medium text-ink-2 ring-control transition hover:bg-subtle focus-ring"
              >
                Cancel
              </button>
              <button
                onClick={() => void createWorkspaceList()}
                disabled={busy}
                className="h-8 rounded bg-brand px-3 text-[13px] font-semibold text-white transition hover:bg-brand-hover disabled:opacity-60 focus-ring"
              >
                {busy ? "Creating…" : "Create list"}
              </button>
            </div>
          </div>
        </>
      )}

      {newWs && (
        <>
          <button aria-label="Close" onClick={() => setNewWs(null)}
                  className="fixed inset-0 z-[70] bg-black/40" />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="New workspace"
            className="fixed left-1/2 top-28 z-[71] w-full max-w-sm -translate-x-1/2 rounded-lg bg-surface p-4 shadow-2xl ring-1 ring-stroke"
          >
            <h2 className="text-[15px] font-semibold text-ink">New workspace</h2>
            <p className="mb-4 mt-0.5 text-xs text-ink-3">
              A workspace holds projects. Projects hold lists, lists hold tasks.
            </p>

            <label className="mb-1 block text-xs font-medium text-ink-2" htmlFor="ws-name">
              Workspace name
            </label>
            <input
              id="ws-name"
              autoFocus
              value={newWs.name}
              disabled={busy}
              onChange={(e) => setNewWs({ ...newWs, name: e.target.value, error: "" })}
              onKeyDown={(e) => {
                if (e.key === "Enter") void createWorkspace();
                if (e.key === "Escape") setNewWs(null);
              }}
              placeholder="e.g. Client delivery"
              className="h-9 w-full rounded bg-canvas px-2.5 text-[13px] text-ink ring-control placeholder:text-ink-3 focus-ring"
            />

            <p className="mb-1.5 mt-4 text-xs font-medium text-ink-2">Colour</p>
            <div className="flex flex-wrap gap-2">
              {COLOR_CHOICES.map((c) => (
                <button
                  key={c || "none"}
                  onClick={() => setNewWs({ ...newWs, color: c })}
                  title={c || "None"}
                  aria-label={`Colour ${c || "none"}`}
                  className={`flex h-7 w-7 items-center justify-center rounded ring-1 ring-inset transition hover:bg-subtle ${
                    newWs.color === c ? "ring-brand bg-brand-tint" : "ring-stroke"
                  }`}
                >
                  <Icon name="board" className={`h-4 w-4 ${PROJECT_DOT[c] ?? "text-ink-3"}`} />
                </button>
              ))}
            </div>

            {newWs.error && <p className="mt-3 text-xs text-bad">{newWs.error}</p>}

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                onClick={() => setNewWs(null)}
                className="h-8 rounded px-3 text-[13px] font-medium text-ink-2 ring-control transition hover:bg-subtle focus-ring"
              >
                Cancel
              </button>
              <button
                onClick={() => void createWorkspace()}
                disabled={busy}
                className="h-8 rounded bg-brand px-3 text-[13px] font-semibold text-white transition hover:bg-brand-hover disabled:opacity-60 focus-ring"
              >
                {busy ? "Creating…" : "Create workspace"}
              </button>
            </div>
          </div>
        </>
      )}

      {wsMenu && (
        <div
          role="menu"
          onClick={(e) => e.stopPropagation()}
          style={{ left: Math.min(wsMenu.x, 240), top: wsMenu.y }}
          className="fixed z-[60] w-56 overflow-hidden rounded bg-surface py-1 shadow-xl ring-1 ring-stroke"
        >
          <p className="truncate px-3 py-1.5 text-[11px] font-semibold text-ink-3">
            {wsMenu.w.name}{wsMenu.w.is_default && " · default"}
          </p>
          <button
            onClick={() => { setRenamingWs({ name: wsMenu.w.name, value: wsMenu.w.name }); setWsMenu(null); }}
            className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-ink-2 transition hover:bg-subtle hover:text-ink"
          >
            <Icon name="edit" className="h-3.5 w-3.5" />
            Rename workspace
          </button>
          <button
            onClick={() => void openMembers(wsMenu.w.name)}
            className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-ink-2 transition hover:bg-subtle hover:text-ink"
          >
            <Icon name="users" className="h-3.5 w-3.5" />
            Members &amp; access
          </button>
          <button
            onClick={() => {
              setBranding({ kind: "workspace", name: wsMenu.w.name,
                            icon: wsMenu.w.icon || "", logo: wsMenu.w.logo_url || "", error: "" });
              setWsMenu(null);
            }}
            className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-ink-2 transition hover:bg-subtle hover:text-ink"
          >
            <Icon name="upload" className="h-3.5 w-3.5" />
            Icon &amp; logo
          </button>
          <button
            onClick={() => {
              setNewProject({ workspace: wsMenu.w.name, name: "", error: "" });
              setWsMenu(null);
            }}
            className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-ink-2 transition hover:bg-subtle hover:text-ink"
          >
            <Icon name="folder" className="h-3.5 w-3.5" />
            New project in this workspace
          </button>
          <button
            onClick={() => {
              setNewWsList({ workspace: wsMenu.w.name, name: "", error: "" });
              setWsMenu(null);
            }}
            className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-ink-2 transition hover:bg-subtle hover:text-ink"
          >
            <Icon name="tasks" className="h-3.5 w-3.5" />
            New list in this workspace
          </button>
          <button
            onClick={() => { setNewWs({ name: "", color: "", error: "" }); setWsMenu(null); }}
            className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-ink-2 transition hover:bg-subtle hover:text-ink"
          >
            <Icon name="plus" className="h-3.5 w-3.5" />
            New workspace
          </button>

          <div className="mt-1 border-t border-stroke px-3 py-2">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-ink-3">Colour</p>
            <div className="flex flex-wrap gap-1.5">
              {COLOR_CHOICES.map((c) => (
                <button
                  key={c || "none"}
                  onClick={() => void saveWorkspace({ name: wsMenu.w.name, color: c })}
                  disabled={busy}
                  title={c || "None"}
                  aria-label={`Colour ${c || "none"}`}
                  className={`flex h-5 w-5 items-center justify-center rounded-full ring-1 ring-inset transition hover:scale-110 disabled:opacity-40 ${
                    wsMenu.w.color === c ? "ring-ink" : "ring-stroke"
                  }`}
                >
                  <Icon name="board" className={`h-3 w-3 ${PROJECT_DOT[c] ?? "text-ink-3"}`} />
                </button>
              ))}
            </div>
          </div>

          <div className="mt-1 border-t border-stroke pt-1">
            <button
              onClick={() => void deleteWorkspace(wsMenu.w)}
              disabled={busy || wsMenu.w.is_default}
              title={wsMenu.w.is_default ? "The default workspace cannot be deleted" : undefined}
              className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-bad transition hover:bg-bad-bg disabled:opacity-40"
            >
              <Icon name="trash" className="h-3.5 w-3.5" />
              Delete workspace
            </button>
          </div>
        </div>
      )}

      {menu && (
        <div
          role="menu"
          onClick={(e) => e.stopPropagation()}
          style={{ left: Math.min(menu.x, 240), top: menu.y }}
          className="fixed z-[60] w-52 overflow-hidden rounded bg-surface py-1 shadow-xl ring-1 ring-stroke"
        >
          <p className="truncate px-3 py-1.5 text-[11px] font-semibold text-ink-3">
            {menu.p.name || "No project"}
          </p>
          <button
            onClick={() => { setRenaming({ p: menu.p, value: menu.p.name }); setMenu(null); }}
            disabled={!menu.p.name}
            className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-ink-2 transition hover:bg-subtle hover:text-ink disabled:opacity-40"
          >
            <Icon name="edit" className="h-3.5 w-3.5" />
            Rename
          </button>
          <button
            onClick={() => {
              setBranding({ kind: "project", name: menu.p.name,
                            icon: menu.p.icon || "", logo: menu.p.logo_url || "", error: "" });
              setMenu(null);
            }}
            disabled={!menu.p.name}
            className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-ink-2 transition hover:bg-subtle hover:text-ink disabled:opacity-40"
          >
            <Icon name="upload" className="h-3.5 w-3.5" />
            Icon &amp; logo
          </button>
          <Link
            href={`/tasks?project=${encodeURIComponent(menu.p.name)}&addlist=1`}
            onClick={() => setMenu(null)}
            className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-ink-2 transition hover:bg-subtle hover:text-ink"
          >
            <Icon name="plus" className="h-3.5 w-3.5" />
            Add list
          </Link>

          <div className="mt-1 border-t border-stroke px-3 py-2">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-ink-3">Colour</p>
            <div className="flex flex-wrap gap-1.5">
              {COLOR_CHOICES.map((c) => (
                <button
                  key={c || "none"}
                  onClick={() => void setColor(menu.p, c)}
                  disabled={busy || !menu.p.name}
                  title={c || "None"}
                  aria-label={`Colour ${c || "none"}`}
                  className={`flex h-5 w-5 items-center justify-center rounded-full ring-1 ring-inset transition hover:scale-110 disabled:opacity-40 ${
                    menu.p.color === c ? "ring-ink" : "ring-stroke"
                  }`}
                >
                  <Icon name="folder" className={`h-3 w-3 ${PROJECT_DOT[c] ?? "text-ink-3"}`} />
                </button>
              ))}
            </div>
          </div>

          <div className="mt-1 border-t border-stroke pt-1">
            <button
              onClick={() => void deleteProject(menu.p)}
              disabled={busy || !menu.p.name}
              className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-[13px] text-bad transition hover:bg-bad-bg disabled:opacity-40"
            >
              <Icon name="trash" className="h-3.5 w-3.5" />
              Delete project
            </button>
          </div>
        </div>
      )}

      <AccountMenu name={name} initials={initials} isAdmin={isAdmin}
                   onSignOut={signOut} />
    </aside>
  );
}

/** Text-only nav row — no icons; active state is a brand label on a subtle fill. */
function NavLink({ item, active }: { item: { label: string; href: string; icon?: string; soon?: boolean }; active: string }) {
  const isActive = item.label === active;
  return (
    <Link
      href={item.href}
      aria-current={isActive ? "page" : undefined}
      title={item.soon ? "Still under development" : undefined}
      // The active row was carrying four signals at once - an accent bar, a
      // tinted fill, bold text and a blue icon - which is what made it shout.
      // Two carry it: the bar says which row, a neutral fill says it is
      // selected, and the brand colour appears exactly once in the rail.
      className={`group relative flex h-8 items-center gap-2.5 rounded-md pl-3 pr-2 text-[13px] transition-colors ${
        isActive
          ? "bg-subtle font-medium text-ink"
          : "text-ink-2 hover:bg-subtle/60 hover:text-ink"
      }`}
    >
      <span
        aria-hidden
        className={`absolute left-0 top-1/2 w-[3px] -translate-y-1/2 rounded-r-full bg-brand transition-all ${
          isActive ? "h-4 opacity-100" : "h-0 opacity-0"
        }`}
      />
      {item.icon && (
        <Icon
          name={item.icon}
          className={`h-4 w-4 shrink-0 transition-colors ${
            isActive ? "text-ink" : "text-ink-3 group-hover:text-ink-2"}`}
        />
      )}
      <span className="truncate">{item.label}</span>
      {item.soon && (
        <span className="ml-auto shrink-0 rounded bg-warnx-bg px-1 py-0.5 text-[10px] font-medium uppercase tracking-wide text-warnx">
          Soon
        </span>
      )}
    </Link>
  );
}


/**
 * The account block at the foot of the rail.
 *
 * The previous version squeezed an avatar, a name, a role, a theme button and
 * a sign-out button onto one 32px row: five things competing for the width the
 * rail has least of, with two icon-only controls nobody could name. This is
 * the pattern the rest of the app's tooling uses - the row is one button, and
 * the actions live in a menu above it where they have room to be labelled.
 */
function AccountMenu({ name, initials, isAdmin, onSignOut }: {
  name: string; initials: string; isAdmin: boolean; onSignOut: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useTheme();
  const box = useRef<HTMLDivElement>(null);

  // Close on an outside click or Escape, the two ways people expect to dismiss
  // a menu they opened by accident.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const isDark = theme === "dark";

  return (
    <div ref={box} className="relative shrink-0 border-t border-stroke p-2">
      <Pop open={open}
           className="absolute bottom-full left-2 right-2 mb-1 origin-bottom">
        <div role="menu"
             className="overflow-hidden rounded-lg bg-surface py-1 shadow-lg ring-1 ring-stroke">
          <button role="menuitem"
                  onClick={() => setTheme(isDark ? "light" : "dark")}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] text-ink transition hover:bg-subtle focus-ring">
            <Icon name={isDark ? "sun" : "moon"} className="h-4 w-4 text-ink-3" />
            <span className="flex-1">{isDark ? "Light mode" : "Dark mode"}</span>
          </button>
          <div className="my-1 border-t border-stroke" />
          <button role="menuitem" onClick={onSignOut}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] text-ink transition hover:bg-bad-bg hover:text-bad focus-ring">
            <Icon name="signout" className="h-4 w-4" />
            <span className="flex-1">Sign out</span>
          </button>
        </div>
      </Pop>

      <button onClick={() => setOpen((v) => !v)}
              aria-haspopup="menu" aria-expanded={open}
              className={`flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition focus-ring ${
                open ? "bg-subtle" : "hover:bg-subtle"}`}>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-semibold text-white">
          {initials}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-semibold leading-tight text-ink">
            {name || "…"}
          </span>
          <span className="block truncate text-[11px] leading-tight text-ink-3">
            {isAdmin ? "Administrator" : "Member"}
          </span>
        </span>
        <Icon name="chevron"
              className={`h-4 w-4 shrink-0 text-ink-3 transition-transform ${
                open ? "rotate-180" : ""}`} />
      </button>
    </div>
  );
}
