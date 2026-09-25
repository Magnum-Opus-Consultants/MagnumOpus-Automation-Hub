"use client";

import {
  useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore,
} from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Section, Button, EmptyState, Modal,
  ConfirmDialog, TextInput, AreaInput, SelectInput, Pill,
} from "@/components/ui";

/* The live testing sheet, as a page.
 *
 * Every sheet the workbook carried has a view here - the dashboard, one per app
 * under test, the criteria legend and the parked enhancements - so the whole
 * pack can be read and edited before anyone exports it. The dashboard is built
 * from however many apps the project has, not the two the template happened to
 * ship with.
 *
 * Totals are never stored. The server derives them from the items on each
 * request, which is what stops the summary drifting from the rows the way the
 * hand-maintained spreadsheets did. The swatch colours below are the workbook's
 * own, so the screen and the exported pack read identically. */

const NAVY = "#1F2A44";
const NAVY_DEEP = "#16213A";
const SLATE = "#3D5A80";
const GREEN = "#1E7B34";
const AMBER = "#9C6500";
const RED = "#C00000";

type Choice = { key: string; label: string };
type LegendEntry = { label: string; definition: string; fill: string; ink: string };
type LegendBlock = { heading: string; entries: LegendEntry[] };
type Vocab = {
  legend: LegendBlock[];
  buckets: Choice[]; dev_statuses: Choice[]; tested: Choice[]; readiness: Choice[];
};
type Rollup = {
  total: number; pass: number; requires_action: number; outstanding: number;
  pending_retest: number; tested: number; not_tested: number; readiness_pct: number;
  carried_over: number;
};
type Item = {
  id: number; issue: string; description: string;
  bucket: string; bucket_display: string;
  dev_status: string; dev_status_display: string;
  tested: string; tested_display: string;
  readiness: string; readiness_display: string;
  client_feedback: string; order: number; updated_at: string | null;
  iteration_id: number; pass_number: number; carried_over: boolean;
  history: History[];
};
type History = {
  version: string; number: number; readiness_display: string;
  dev_status_display: string; tested_display: string; client_feedback: string;
};
type Version = {
  id: number; label: string; note: string; released_on: string | null; order: number;
};
type AreaSummary = {
  id: number; name: string; order: number; rollup: Rollup;
  // A build chain, not a single label: fixes land mid-round, so an app is
  // tested against several versions before the round closes.
  versions: Version[]; current_version: string;
};
type Sheet = {
  version_id: number; label: string; note: string; released_on: string | null;
  rollup: Rollup; items: Item[];
};
type Area = AreaSummary & { sheets: Sheet[]; current_version_id: number | null };
type Project = {
  id: number; name: string; client: string; summary: string;
  testing_window: string; window_start: string; window_end: string;
  window_label: string; version_label: string; is_archived: boolean;
  created_at: string | null; updated_at: string | null;
  areas: AreaSummary[]; rollup: Rollup;
};
type Note = { id: number; text: string; is_done: boolean; order: number };
type ShareLink = {
  id: number; token: string; label: string; is_active: boolean;
  url: string; path: string; created_at: string | null; created_by: string;
  last_opened_at: string | null;
};

/* The six dashboard tiles, in the workbook's order and colours. */
const TILES: { key: keyof Rollup; label: string; colour: string }[] = [
  { key: "total", label: "Total Items", colour: NAVY },
  { key: "pass", label: "PASS", colour: GREEN },
  { key: "requires_action", label: "Requires Action", colour: AMBER },
  { key: "outstanding", label: "Outstanding", colour: RED },
  { key: "pending_retest", label: "Pending Retest", colour: SLATE },
  { key: "readiness_pct", label: "Readiness %", colour: NAVY_DEEP },
];

const EMPTY_ROLLUP: Rollup = {
  total: 0, pass: 0, requires_action: 0, outstanding: 0,
  pending_retest: 0, tested: 0, not_tested: 0, readiness_pct: 0, carried_over: 0,
};

const blankDraft = () => ({
  id: 0, issue: "", description: "",
  bucket: "in_scope_change", dev_status: "in_progress",
  tested: "not_tested", readiness: "requires_action", client_feedback: "",
});
type Draft = ReturnType<typeof blankDraft>;

async function readError(res: Response, fallback: string) {
  try {
    const body = await res.json();
    return (body && body.detail) || fallback;
  } catch {
    return fallback;
  }
}

/** "2.1.5 -> 2.1.6 -> 2.1.8": every build this app was tested against. */
function chainOf(area: AreaSummary): string {
  return area.versions.map((v) => v.label).join(" → ");
}

/** Look up a status swatch from the legend the server sent. */
/* Row density, kept in localStorage so it survives a reload, and served through
   a store so the value can be read during render instead of written in after
   mount. getServer answers false so the markup React hydrates against is
   stable; the real preference lands on the first client snapshot. Storage can
   throw (private mode, blocked cookies), so every access is guarded. */
const COMPACT_KEY = "rt.compact";
const compactPref = {
  listeners: new Set<() => void>(),
  subscribe(cb: () => void) {
    compactPref.listeners.add(cb);
    return () => { compactPref.listeners.delete(cb); };
  },
  get() {
    try { return localStorage.getItem(COMPACT_KEY) === "1"; } catch { return false; }
  },
  getServer() { return false; },
  set(next: boolean) {
    try { localStorage.setItem(COMPACT_KEY, next ? "1" : "0"); } catch {}
    compactPref.listeners.forEach((l) => l());
  },
};

function swatch(vocab: Vocab | null, label: string): LegendEntry | null {
  if (!vocab) return null;
  for (const block of vocab.legend) {
    const hit = block.entries.find((e) => e.label === label);
    if (hit) return hit;
  }
  return null;
}

function StatusCell({ vocab, label }: { vocab: Vocab | null; label: string }) {
  const s = swatch(vocab, label);
  if (!s) return <span className="text-[12px] text-ink-2">{label}</span>;
  return (
    <span className="inline-block rounded px-2 py-0.5 text-[11px] font-semibold"
          title={s.definition ? `${label} — ${s.definition}` : label}
          style={{ backgroundColor: s.fill, color: s.ink }}>
      {label}
    </span>
  );
}

/** One area's metric strip - the block the workbook repeated per app. */
function MetricStrip({ label, version, rollup }:
  { label: string; version?: string; rollup: Rollup }) {
  return (
    <div className="mb-5">
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-semibold text-ink">{label}</h3>
        {version && <span className="text-[12px] text-ink-3">{version}</span>}
      </div>
      <div className="grid gap-2 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        {TILES.map((t) => (
          <div key={t.key} className="overflow-hidden rounded-lg ring-1 ring-stroke">
            <div className="px-2 py-1.5 text-center text-[10px] font-semibold leading-tight text-white"
                 style={{ backgroundColor: t.colour }}>
              {t.label}
            </div>
            <div className="bg-surface py-2 text-center text-2xl font-bold"
                 style={{ color: t.colour }}>
              {t.key === "readiness_pct" ? `${rollup.readiness_pct}%` : rollup[t.key]}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** The readiness breakdown table the workbook carried under each strip. */
function ReadinessTable({ vocab, rollup }: { vocab: Vocab | null; rollup: Rollup }) {
  const rows: [string, number][] = [
    ["PASS", rollup.pass],
    ["REQUIRES ACTION", rollup.requires_action],
    ["OUTSTANDING", rollup.outstanding],
    ["Rectified & Requires Testing", rollup.pending_retest],
  ];
  return (
    <table className="w-full max-w-md text-sm">
      <tbody>
        {rows.map(([label, count]) => (
          <tr key={label} className="border-b border-stroke last:border-0">
            <td className="py-1.5 pr-3">
              <StatusCell vocab={vocab} label={label} />
            </td>
            <td className="py-1.5 text-right font-medium text-ink">{count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** A horizontally scrolling area whose scrollbar stays in view.

   The sheet is far wider than any screen, and a scrollbar sitting at the bottom
   of a tall table is off-screen exactly when someone needs to discover it. So a
   second, empty scroller is pinned to the bottom of the viewport and mirrors the
   real one in both directions: the bar is always visible, wherever you are in
   the rows. It is hidden once the table happens to fit. */
function StickyScroller({ children }: { children: React.ReactNode }) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const spacerRef = useRef<HTMLDivElement>(null);
  const [overflowing, setOverflowing] = useState(false);
  // Guard against the two scrollers echoing each other's scroll events.
  const syncing = useRef(false);

  const measure = useCallback(() => {
    const body = bodyRef.current;
    const spacer = spacerRef.current;
    if (!body || !spacer) return;
    spacer.style.width = `${body.scrollWidth}px`;
    setOverflowing(body.scrollWidth > body.clientWidth + 1);
  }, []);

  useEffect(() => {
    measure();
    const body = bodyRef.current;
    if (!body || typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(body);
    if (body.firstElementChild) ro.observe(body.firstElementChild);
    return () => ro.disconnect();
  }, [measure, children]);

  const mirror = (from: HTMLDivElement | null, to: HTMLDivElement | null) => {
    if (!from || !to || syncing.current) return;
    syncing.current = true;
    to.scrollLeft = from.scrollLeft;
    // Released on the next frame, after the echoed scroll event has fired.
    requestAnimationFrame(() => { syncing.current = false; });
  };

  return (
    <>
      <div ref={bodyRef} className="overflow-x-auto"
           onScroll={() => mirror(bodyRef.current, barRef.current)}>
        {children}
      </div>
      {overflowing && (
        <div
          ref={barRef}
          onScroll={() => mirror(barRef.current, bodyRef.current)}
          className="sticky bottom-0 z-20 overflow-x-auto border-t border-stroke
                     bg-surface/95 backdrop-blur"
          aria-hidden
        >
          <div ref={spacerRef} className="h-3" />
        </div>
      )}
    </>
  );
}

/** A textarea with no scrollbar of its own: it grows to fit what is in it.

   The feedback column carries several lines of review notes per item, and a
   fixed-height box hides most of them behind an inner scrollbar - which is the
   one place on this sheet where the text is the point. Height is measured from
   the content after every change, and once on mount for what was loaded. */
function AutoTextarea({ value, onChange, placeholder, plain = false, className = "" }: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  plain?: boolean;
  className?: string;
}) {
  const fit = (el: HTMLTextAreaElement | null) => {
    if (!el) return;
    // Collapse first, or the height only ever ratchets upwards.
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };

  return (
    <textarea
      ref={fit}
      value={value}
      rows={1}
      placeholder={placeholder}
      onChange={(e) => { fit(e.currentTarget); onChange(e.target.value); }}
      /* `plain` is for the columns that are the sheet's own content rather than
         a box to fill in: it reads as text and only shows it is a field on
         hover or focus. Set as one class per variant, not layered over the
         other, because two background utilities in one string resolve by
         stylesheet order rather than by which was written last. */
      className={`w-full resize-none overflow-hidden rounded px-2 py-1.5
                  text-[12px] leading-relaxed text-ink ring-1 ring-transparent
                  placeholder:text-ink-3 hover:ring-stroke focus:outline-none
                  focus:ring-brand/40
                  ${plain ? "bg-transparent hover:bg-subtle focus:bg-subtle" : "bg-subtle"}
                  ${className}`}
    />
  );
}

/* A row that edits in place.
 *
 * The verdict columns are the ones that actually change during a round, so they
 * are dropdowns in the table rather than behind a dialog - opening a modal to
 * change one select, for every item, every day of testing, is most of the work
 * of running the sheet. Save only lights up once something has changed, so the
 * row still reads as data until you touch it. */
function ItemRow({ item, vocab, compact, busy, onSave, onRetest, onDelete, onDirty }: {
  item: Item;
  vocab: Vocab | null;
  compact: boolean;
  busy: boolean;
  onSave: (patch: Partial<Item>) => Promise<void>;
  onRetest: () => void;
  onDelete: () => void;
  onDirty: (id: number, dirty: boolean) => void;
}) {
  /* issue and description ride the same machinery as the selects: listing them
     here is what gives them dirty-tracking, the Save button, and the field-by-
     field merge when someone else edits the row while you are typing in it. */
  const fields = ["issue", "description", "bucket", "dev_status", "tested",
                  "readiness", "client_feedback"] as const;
  const serverValues = () => ({
    issue: item.issue, description: item.description,
    bucket: item.bucket, dev_status: item.dev_status,
    tested: item.tested, readiness: item.readiness,
    client_feedback: item.client_feedback,
  });

  const [draft, setDraft] = useState(serverValues);
  // The server values this row last reconciled against, so a remote change can
  // be told apart from a local one.
  const [seen, setSeen] = useState(serverValues);
  const [open, setOpen] = useState(false);
  /* Compact clamps the description; this opens the one row you are reading
     without leaving compact. Kept separate from `open` (the build history) so
     expanding the text does not drag the earlier builds along with it. */
  const [expanded, setExpanded] = useState(false);
  const clamped = compact && !expanded;

  /* Someone else - the team here, or a client through a share link - may edit
     this same row while it is on screen. Rather than remounting the row (which
     would throw away a half-typed comment and make the table flicker), adopt
     the incoming value field by field, and only where this user has not touched
     that field themselves. Their edits always win until they save or discard.
     Adjusting state during render is React's documented way to react to changed
     props without an effect. */
  const incoming = serverValues();
  if (fields.some((f) => incoming[f] !== seen[f])) {
    setSeen(incoming);
    setDraft((cur) => {
      const next = { ...cur };
      for (const f of fields) {
        if (incoming[f] !== seen[f] && cur[f] === seen[f]) next[f] = incoming[f];
      }
      return next;
    });
  }

  const dirty = fields.some((f) => draft[f] !== incoming[f]);

  /* Reviewers edit the same rows through a share link, so the page refreshes
     itself - but a refresh mid-edit would throw away what is being typed. The
     row tells the page when it is holding unsaved changes, and the poll waits.
     Reported through a ref on the parent, so this never triggers a render. */
  useEffect(() => {
    onDirty(item.iteration_id, dirty);
    return () => onDirty(item.iteration_id, false);
  }, [dirty, item.iteration_id, onDirty]);

  const swatchFor = (label: string) => swatch(vocab, label);
  /* Each status carries a definition from the Legend, and the whole point of
     the vocabulary is that people pick the right one. So the definition is on
     the control as a tooltip, and on every option inside the open list too -
     you should not have to leave the row to remember what OUTSTANDING means. */
  const cell = (value: string, options: Choice[] | undefined,
                onChange: (v: string) => void) => {
    const label = options?.find((o) => o.key === value)?.label ?? "";
    const s = swatchFor(label);
    return (
      <select
        value={value}
        title={s?.definition ? `${label} — ${s.definition}` : label}
        onChange={(e) => onChange(e.target.value)}
        className="w-full cursor-pointer rounded px-2 py-1 text-[11px] font-semibold
                   ring-1 ring-transparent hover:ring-stroke focus:outline-none focus:ring-brand/40"
        style={s ? { backgroundColor: s.fill, color: s.ink }
                 : { backgroundColor: "transparent" }}
      >
        {options?.map((o) => {
          /* An option with no colour of its own must say so explicitly: left
             unset it inherits the select's fill, which paints the whole open
             list in the current choice's colour. Each option carries its own
             swatch, so the list reads as the legend rather than one block. */
          const os = swatchFor(o.label);
          return (
            <option key={o.key} value={o.key}
                    title={os?.definition ? `${o.label} — ${os.definition}` : o.label}
                    style={os ? { backgroundColor: os.fill, color: os.ink }
                              : { backgroundColor: "var(--c-surface)", color: "var(--c-ink)" }}>
              {o.label}
            </option>
          );
        })}
      </select>
    );
  };

  return (
    <>
      <tr className="border-b border-stroke align-top last:border-0">
        <td className={`px-2 align-top ${compact ? "py-1.5" : "py-2"}`}>
          {/* The title is typed into, so in compact the chevron beside it - not
              the text - is what expands the row. Clicking into the words has to
              put a caret there, or you could never edit a title in compact. */}
          <div className="flex items-start gap-1">
            {compact && (
              <button
                onClick={() => setExpanded(!expanded)}
                aria-expanded={expanded}
                title={expanded ? "Collapse this row" : "Show the full description"}
                className="mt-1.5 shrink-0 rounded px-0.5 text-[9px] text-ink-3
                           hover:bg-subtle hover:text-brand"
              >
                {expanded ? "▼" : "▶"}
              </button>
            )}
            <AutoTextarea
              value={draft.issue}
              onChange={(v) => setDraft({ ...draft, issue: v })}
              placeholder="Issue title…"
              plain
              className="font-medium"
            />
          </div>
          {item.history.length > 0 && (
            <button onClick={() => setOpen(!open)}
                    className="mt-1 text-[11px] text-brand hover:underline">
              {item.carried_over ? "carried over" : "also on"} ·{" "}
              {item.history.length} earlier build
              {item.history.length === 1 ? "" : "s"} {open ? "▲" : "▼"}
            </button>
          )}
        </td>
        <td className={`px-2 align-top text-[12px] leading-relaxed text-ink-2 ${
          compact ? "py-1.5" : "py-2"}`}>
          {/* Clamped, the description is a preview you tap to open - a textarea
              cannot be line-clamped and still be typed into. Once open, and in
              full view, it is the editable field itself. */}
          {clamped ? (
            <button
              onClick={() => setExpanded(true)}
              title={`${item.description}\n\nClick to edit`}
              className="w-full text-left hover:text-ink"
            >
              <span className="line-clamp-2 break-words whitespace-pre-wrap">
                {item.description || <span className="text-ink-3">No description…</span>}
              </span>
            </button>
          ) : (
            <AutoTextarea
              value={draft.description}
              onChange={(v) => setDraft({ ...draft, description: v })}
              placeholder="What was found…"
              plain
              className="text-ink-2"
            />
          )}
        </td>
        <td className={`px-2 align-top w-40 ${compact ? "py-1.5" : "py-2"}`}>
          {cell(draft.bucket, vocab?.buckets,
                (v) => setDraft({ ...draft, bucket: v }))}
        </td>
        <td className={`px-2 align-top w-48 ${compact ? "py-1.5" : "py-2"}`}>
          {cell(draft.dev_status, vocab?.dev_statuses,
                (v) => setDraft({ ...draft, dev_status: v }))}
        </td>
        <td className={`px-2 align-top w-28 ${compact ? "py-1.5" : "py-2"}`}>
          {cell(draft.tested, vocab?.tested,
                (v) => setDraft({ ...draft, tested: v }))}
        </td>
        <td className={`px-2 align-top w-40 ${compact ? "py-1.5" : "py-2"}`}>
          {cell(draft.readiness, vocab?.readiness,
                (v) => setDraft({ ...draft, readiness: v }))}
        </td>
        {/* Free text, not a vocabulary: this is where the reviewer writes what
            they actually found, so it stays a box you type into. */}
        <td className={`px-2 align-top w-64 ${compact ? "py-1.5" : "py-2"}`}>
          <AutoTextarea
            value={draft.client_feedback}
            onChange={(v) => setDraft({ ...draft, client_feedback: v })}
            placeholder="What the reviewer found…"
          />
        </td>
        <td className="px-2 py-2 text-right whitespace-nowrap">
          {dirty && (
            <button
              onClick={() => onSave(draft)}
              /* The server rejects a blank title with a 400. Catching it here
                 means an emptied title reads as "finish this", not as a failed
                 save after the fact. */
              disabled={busy || !draft.issue.trim()}
              title={!draft.issue.trim() ? "An issue needs a title before it can be saved" : undefined}
              className="rounded-md bg-brand px-2.5 py-1 text-[11px] font-semibold
                         text-white hover:opacity-90 disabled:opacity-50"
            >
              Save
            </button>
          )}
          {!dirty && item.readiness !== "pass" && (
            <button
              onClick={onRetest}
              title="Record another test pass after this has been actioned"
              className="rounded-md px-2 py-1 text-[11px] font-medium text-brand hover:bg-brand/10"
            >
              Retest
            </button>
          )}
          <button
            onClick={onDelete}
            className="ml-1 rounded p-1.5 text-ink-3 hover:bg-subtle hover:text-bad"
            aria-label="Delete item"
          >
            <Icon name="trash" className="h-4 w-4" />
          </button>
        </td>
      </tr>

      {/* Where this issue stood on the builds before this one. */}
      {open && item.history.map((r, i) => (
        <tr key={i} className="border-b border-stroke bg-subtle/40 text-[12px]">
          <td className="px-2 py-1.5 text-ink-3" colSpan={2}>
            #{r.number} · Build {r.version}
          </td>
          <td className="px-2 py-1.5" />
          <td className="px-2 py-1.5">
            <StatusCell vocab={vocab} label={r.dev_status_display} />
          </td>
          <td className="px-2 py-1.5">
            <StatusCell vocab={vocab} label={r.tested_display} />
          </td>
          <td className="px-2 py-1.5">
            <StatusCell vocab={vocab} label={r.readiness_display} />
          </td>
          <td className="px-2 py-1.5 whitespace-pre-line text-ink-3" colSpan={2}>
            {r.client_feedback}
          </td>
        </tr>
      ))}
    </>
  );
}

export default function SystemTestingPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [vocab, setVocab] = useState<Vocab | null>(null);

  // null = the index. Readiness Testing opens on the list of systems that have
  // been tested, because a project is one round against one system and there
  // are many of them - E-Crop retested against a new build is its own entry.
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [areas, setAreas] = useState<Area[] | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  // "dashboard" | "legend" | "notes" | an area id as a number
  const [view, setView] = useState<string | number>("dashboard");
  const [filter, setFilter] = useState<string>("All");
  const [sheetVersion, setSheetVersion] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  /* Compact trades the full description for a two-line preview, so a sheet of
     thirty items is scannable in one screen instead of one row per screen.
     The full text is a click on the issue away. Read through the store rather
     than an effect so the server render has a defined answer. */
  const compact = useSyncExternalStore(
    compactPref.subscribe, compactPref.get, compactPref.getServer);
  const toggleCompact = (next: boolean) => compactPref.set(next);

  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [projectModal, setProjectModal] = useState<null | "new" | "edit">(null);
  const [projectForm, setProjectForm] = useState({
    name: "", client: "", window_start: "", window_end: "",
    version_label: "", summary: "",
    apps: [{ name: "", version: "" }] as { name: string; version: string }[],
  });
  const [itemModal, setItemModal] = useState<null | Draft>(null);
  const [areaModal, setAreaModal] = useState<null | { id: number; name: string; version_label: string }>(null);
  const [versionModal, setVersionModal] = useState<null | {
    area: Area; label: string; note: string;
  }>(null);
  const [shareModal, setShareModal] = useState<null | {
    project: Project; links: ShareLink[]; label: string; copied: string;
  }>(null);
  const [retestItem, setRetestItem] = useState<null | {
    item: Item; dev_status: string; tested: string; readiness: string;
    client_feedback: string;
  }>(null);
  const [noteModal, setNoteModal] = useState<null | { id: number; text: string }>(null);
  const [retestModal, setRetestModal] = useState<null | {
    from: Project; name: string; window_start: string; window_end: string;
    include_items: boolean;
  }>(null);
  const [confirm, setConfirm] = useState<null | { title: string; body: string; run: () => void }>(null);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const selected = useMemo(
    () => projects?.find((p) => p.id === selectedId) ?? null,
    [projects, selectedId]);

  /* ── loading ─────────────────────────────────────────────────────────── */

  const loadProjects = useCallback(async (keep?: number) => {
    const res = await fetch("/api/system-testing/projects");
    // A 401 means the session check is already redirecting to /login; a
    // "could not load" on the way out would only be noise.
    if (res.status === 401) return;
    if (!res.ok) { setError(await readError(res, "Could not load projects.")); return; }
    const data = await res.json();
    setProjects(data.projects);
    setVocab(data.vocabularies);
    // Only ever move the selection when a caller names a project to land on.
    // Defaulting to the first one would make the index unreachable.
    if (keep !== undefined) setSelectedId(keep);
  }, []);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "system_testing")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    // loadProjects() only updates state after awaiting its fetch, so nothing
    // re-renders synchronously here; the rule cannot see through the function
    // boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadProjects();
  }, [loadProjects]);

  const loadDetail = useCallback(async (id: number, blank = true) => {
    // Only clear when moving to a different project. Clearing on a background
    // reload is what made the table blink.
    if (blank) { setAreas(null); setNotes([]); }
    const res = await fetch(`/api/system-testing/projects/${id}`);
    if (res.status === 401) return;
    if (!res.ok) { setError(await readError(res, "Could not load that project.")); return; }
    const data = await res.json();
    setAreas(data.areas);
    setNotes(data.notes);
  }, []);

  /* Opening a project always lands on its dashboard. Done here rather than in
     an effect so the tab and the selection change in the same render. */
  const openProject = useCallback((id: number | null) => {
    setSelectedId(id);
    setView("dashboard");
    setFilter("All");
    setSearch("");
    setSheetVersion(null);
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    // loadDetail only sets state inside its own function body, after awaiting
    // its fetch; the rule cannot see through the function boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  /* Rows with unsaved edits, by iteration id. A ref, not state: it changes on
     every keystroke and nothing renders from it. */
  const dirtyRows = useRef<Set<number>>(new Set());
  const markDirty = useCallback((id: number, dirty: boolean) => {
    if (dirty) dirtyRows.current.add(id);
    else dirtyRows.current.delete(id);
  }, []);

  const refresh = useCallback(async () => {
    if (selectedId) await loadDetail(selectedId, false);
    await loadProjects(selectedId ?? undefined);
  }, [selectedId, loadDetail, loadProjects]);

  /* Live sync with whoever else is on the sheet.
   *
   * Asks only for what changed since the last check and patches those rows into
   * place, so an unchanged row is the same object as before and React leaves it
   * alone - no flicker, no lost focus, and a row being edited keeps its own
   * values (see ItemRow). A row added or deleted elsewhere cannot be seen from
   * timestamps, so the row counts are compared and a full reload is done only
   * then. It runs while rows are being edited, because the merge is safe. */
  const syncedAt = useRef<string | null>(null);

  useEffect(() => {
    if (!selectedId) return;
    // Captured so the closures below have a plain number, not number | null.
    const projectId = selectedId;
    syncedAt.current = null;
    let stopped = false;

    async function tick() {
      if (stopped || document.hidden) return;
      const since = syncedAt.current;
      const res = await fetch(
        `/api/system-testing/projects/${projectId}/changes`
        + (since ? `?since=${encodeURIComponent(since)}` : ""));
      if (!res.ok || stopped) return;
      const data = await res.json();
      const first = syncedAt.current === null;
      syncedAt.current = data.server_time;
      // The first tick establishes the baseline; everything is "changed"
      // relative to no timestamp, and it is already on screen.
      if (first) return;

      let mustReload = false;
      setAreas((cur) => {
        if (!cur) return cur;
        const counts = new Map<number, number>();
        for (const a of data.areas) {
          for (const sh of a.sheets) counts.set(sh.version_id, sh.count);
        }
        const patches = new Map<number, Item>();
        for (const c of data.changed) patches.set(c.item.iteration_id, c.item);

        const next = cur.map((area) => {
          const server = data.areas.find((a: { id: number }) => a.id === area.id);
          const sheets = area.sheets.map((sh) => {
            if (counts.get(sh.version_id) !== sh.items.length) mustReload = true;
            const serverSheet = server?.sheets.find(
              (x: { version_id: number }) => x.version_id === sh.version_id);
            /* A row holding unsaved edits keeps the object it already has.
               Replacing it with the server's copy mid-edit is what threw away
               a dropdown someone had just changed: the row is rebuilt from the
               incoming item, and the change goes with it. dirtyRows is written
               by every row as it gains and loses unsaved changes - it was being
               kept and never consulted, so the guard this comment describes did
               not actually exist. */
            const items = sh.items.map((it) =>
              dirtyRows.current.has(it.iteration_id)
                ? it
                : patches.get(it.iteration_id) ?? it);
            const touched = items.some((it, i) => it !== sh.items[i]);
            if (!touched && serverSheet?.rollup === sh.rollup) return sh;
            return { ...sh, items, rollup: serverSheet?.rollup ?? sh.rollup };
          });
          return { ...area, sheets, rollup: server?.rollup ?? area.rollup };
        });
        return next;
      });

      /* A full reload rebuilds every row from the server, so it takes unsaved
         edits with it. Rows only stay dirty until they are saved or discarded,
         and the reload is triggered by a count change that will still be true
         next tick - so waiting costs five seconds and saves someone's typing. */
      if (mustReload && dirtyRows.current.size === 0) {
        await loadDetail(projectId, false);
        await loadProjects(projectId);
      }
    }

    const id = window.setInterval(() => { void tick(); }, 5000);
    void tick();
    return () => { stopped = true; window.clearInterval(id); };
  }, [selectedId, loadDetail, loadProjects]);

  /* ── mutations ───────────────────────────────────────────────────────── */

  const send = useCallback(async (url: string, init: RequestInit, fallback: string) => {
    setBusy(true); setError("");
    try {
      const res = await fetch(url, init);
      if (!res.ok) { setError(await readError(res, fallback)); return null; }
      return await res.json();
    } catch {
      setError(fallback);
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const jsonPost = (body: unknown): RequestInit => ({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  async function saveProject() {
    const editing = projectModal === "edit" && selected;
    const url = editing
      ? `/api/system-testing/projects/${selected!.id}/save`
      : "/api/system-testing/projects/create";
    const payload = editing
      ? projectForm
      : {
          ...projectForm,
          // Each app is created on the build it starts on, so the first sheet
          // says which version it was run against.
          areas: projectForm.apps
            .map((a) => ({ name: a.name.trim(), version: a.version.trim() }))
            .filter((a) => a.name),
        };
    const out = await send(url, jsonPost(payload), "Could not save the project.");
    if (!out) return;
    setProjectModal(null);
    await loadProjects(out.project.id);
    openProject(out.project.id);
  }

  async function saveItem() {
    if (!itemModal || typeof view !== "number") return;
    const editing = itemModal.id > 0;
    const url = editing
      ? `/api/system-testing/items/${itemModal.id}`
      : "/api/system-testing/items/create";
    const payload = editing ? itemModal : { ...itemModal, area: view };
    const out = await send(url, jsonPost(payload), "Could not save the item.");
    if (!out) return;
    setItemModal(null);
    await refresh();
  }

  async function saveArea() {
    if (!areaModal || !selectedId) return;
    const creating = areaModal.id === 0;
    const url = creating
      ? "/api/system-testing/areas/create"
      : `/api/system-testing/areas/${areaModal.id}`;
    const payload = creating
      ? { project: selectedId, name: areaModal.name, version_label: areaModal.version_label }
      : { name: areaModal.name, version_label: areaModal.version_label };
    const out = await send(url, jsonPost(payload), "Could not save the app.");
    if (!out) return;
    setAreaModal(null);
    await refresh();
    if (creating) setView(out.area.id);
  }

  async function startRetest() {
    if (!retestModal) return;
    const out = await send(
      `/api/system-testing/projects/${retestModal.from.id}/duplicate`,
      jsonPost({
        name: retestModal.name,
        window_start: retestModal.window_start,
        window_end: retestModal.window_end,
        include_items: retestModal.include_items,
      }),
      "Could not start the retest.");
    if (!out) return;
    setRetestModal(null);
    await loadProjects(out.project.id);
  }

  /** Inline row save: writes the verdict onto the item's current pass. */
  async function saveRow(item: Item, patch: Partial<Item>) {
    // Named explicitly so editing a row on an older build corrects that build's
    // pass rather than the current one.
    const out = await send(`/api/system-testing/items/${item.id}`,
      jsonPost({ ...patch, iteration: item.iteration_id }),
      "Could not save that row.");
    if (!out) return;
    await refresh();
  }

  /** Record another pass once an item has been actioned. */
  async function addIteration() {
    if (!retestItem) return;
    const out = await send(
      `/api/system-testing/items/${retestItem.item.id}/iterations`,
      jsonPost({
        dev_status: retestItem.dev_status,
        tested: retestItem.tested,
        readiness: retestItem.readiness,
        client_feedback: retestItem.client_feedback,
      }),
      "Could not record the retest.");
    if (!out) return;
    setRetestItem(null);
    await refresh();
  }

  async function openShare(project: Project) {
    setError("");
    const res = await fetch(`/api/system-testing/projects/${project.id}/share-links`);
    const links = res.ok ? (await res.json()).links : [];
    setShareModal({ project, links, label: "", copied: "" });
  }

  async function createShare() {
    if (!shareModal) return;
    const out = await send(
      `/api/system-testing/projects/${shareModal.project.id}/share-links/create`,
      jsonPost({ label: shareModal.label }), "Could not create the link.");
    if (!out) return;
    setShareModal({
      ...shareModal, label: "",
      links: [out.link, ...shareModal.links],
    });
  }

  async function revokeShare(link: ShareLink) {
    if (!shareModal) return;
    const out = await send(`/api/system-testing/share-links/${link.id}/revoke`,
      { method: "POST" }, "Could not revoke the link.");
    if (!out) return;
    setShareModal({
      ...shareModal,
      links: shareModal.links.map((l) => (l.id === link.id ? out.link : l)),
    });
  }

  async function copyShare(link: ShareLink) {
    if (!shareModal) return;
    // The stored URL points at the deployed host; from a dev browser the same
    // path on this origin is the one that actually opens.
    const url = `${window.location.origin}${link.path}`;
    try {
      await navigator.clipboard.writeText(url);
      setShareModal({ ...shareModal, copied: link.token });
    } catch {
      setError(`Copy failed. The link is ${url}`);
    }
  }

  async function releaseVersion() {
    if (!versionModal) return;
    const out = await send(
      `/api/system-testing/areas/${versionModal.area.id}/versions`,
      jsonPost({ label: versionModal.label, note: versionModal.note }),
      "Could not record the version.");
    if (!out) return;
    setVersionModal(null);
    // Land on the build just released - it is the one being tested now.
    setSheetVersion(out.version?.id ?? null);
    await refresh();
  }

  async function saveNote() {
    if (!noteModal || !selectedId) return;
    const creating = noteModal.id === 0;
    const url = creating
      ? "/api/system-testing/notes/create"
      : `/api/system-testing/notes/${noteModal.id}`;
    const payload = creating
      ? { project: selectedId, text: noteModal.text }
      : { text: noteModal.text };
    const out = await send(url, jsonPost(payload), "Could not save the note.");
    if (!out) return;
    setNoteModal(null);
    await refresh();
  }

  async function toggleNote(n: Note) {
    await send(`/api/system-testing/notes/${n.id}`, jsonPost({ is_done: !n.is_done }),
      "Could not update the note.");
    await refresh();
  }

  function removeItem(item: Item) {
    setConfirm({
      title: "Delete this item?",
      body: `"${item.issue}" will be removed from the sheet. This cannot be undone.`,
      run: async () => {
        setConfirm(null);
        await send(`/api/system-testing/items/${item.id}/delete`, { method: "DELETE" },
          "Could not delete the item.");
        await refresh();
      },
    });
  }

  function removeArea(a: Area) {
    setConfirm({
      title: `Delete "${a.name}"?`,
      body: `All ${a.rollup.total} item(s) for this app will be deleted too. This cannot be undone.`,
      run: async () => {
        setConfirm(null);
        await send(`/api/system-testing/areas/${a.id}/delete`, { method: "DELETE" },
          "Could not delete the app.");
        setView("dashboard");
        await refresh();
      },
    });
  }

  function removeNote(n: Note) {
    setConfirm({
      title: "Delete this note?",
      body: "It will be removed from the enhancements list.",
      run: async () => {
        setConfirm(null);
        await send(`/api/system-testing/notes/${n.id}/delete`, { method: "DELETE" },
          "Could not delete the note.");
        await refresh();
      },
    });
  }

  function removeProject(p: Project) {
    setConfirm({
      title: `Delete "${p.name}"?`,
      body: "Every app, item and note in this project will be deleted. This cannot be undone.",
      run: async () => {
        setConfirm(null);
        await send(`/api/system-testing/projects/${p.id}/delete`, { method: "DELETE" },
          "Could not delete the project.");
        openProject(null);
        await loadProjects();
      },
    });
  }

  /* Download without leaving the page: a plain location assignment counts as a
     navigation, a synthetic anchor lets the attachment land in place. */
  function download(kind: "xlsx" | "pdf") {
    if (!selected) return;
    const a = document.createElement("a");
    a.href = `/api/system-testing/projects/${selected.id}/export`
      + (kind === "pdf" ? ".pdf" : "");
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function onImport(file: File) {
    setImporting(true); setError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/system-testing/import", { method: "POST", body: fd });
      if (!res.ok) { setError(await readError(res, "Could not import that workbook.")); return; }
      const out = await res.json();
      await loadProjects(out.project.id);
      openProject(out.project.id);
    } catch {
      setError("Could not import that workbook.");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  /* ── derived view state ──────────────────────────────────────────────── */

  const area = typeof view === "number"
    ? areas?.find((a) => a.id === view) ?? null
    : null;
  /* Which release's sheet is on screen. Null means the latest, which is what
     opening an app should show - the build being tested now. */
  const sheet = area
    ? (area.sheets.find((sh) => sh.version_id === sheetVersion)
       ?? area.sheets[area.sheets.length - 1] ?? null)
    : null;
  const rollup = selected?.rollup ?? EMPTY_ROLLUP;

  const visibleItems = useMemo(() => {
    if (!sheet) return [];
    const q = search.trim().toLowerCase();
    return sheet.items.filter((it) => {
      if (filter !== "All" && it.readiness !== filter) return false;
      if (!q) return true;
      return `${it.issue} ${it.description} ${it.client_feedback}`
        .toLowerCase().includes(q);
    });
  }, [sheet, filter, search]);

  if (!me) return null;

  return (
    <AppShell active="Readiness Testing" me={me} wide>
      <PageHead
        title="Readiness Testing"
        subtitle="Live testing sheets, readiness rollups and client packs."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileRef} type="file" accept=".xlsx,.xlsm" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onImport(f); }}
            />
            <Button icon="upload" spinning={importing}
                    onClick={() => fileRef.current?.click()}>
              Import workbook
            </Button>
            {selected && (
              <>
                <Button icon="download" onClick={() => download("xlsx")}>
                  Export Excel
                </Button>
                <Button icon="file" onClick={() => download("pdf")}>
                  Export PDF
                </Button>
              </>
            )}
            <Button variant="primary" icon="plus"
                    onClick={() => {
                      setProjectForm({ name: "", client: "", window_start: "",
                                       window_end: "", version_label: "",
                                       summary: "",
                                       apps: [{ name: "", version: "" }] });
                      setProjectModal("new");
                    }}>
              New project
            </Button>
          </div>
        }
      />

      {error && (
        <div className="mb-4 rounded-lg bg-bad/10 px-4 py-3 text-sm text-bad ring-1 ring-bad/20">
          {error}
        </div>
      )}

      {projects === null ? null : projects.length === 0 ? (
        <EmptyState
          icon="analysis"
          title="No testing projects yet"
          hint="Start one from scratch, or import a Management Live Sheet workbook to bring its sheets across. The workbook is a template - each project keeps its own apps, versions and items."
          action={
            <Button variant="primary" icon="upload" spinning={importing}
                    onClick={() => fileRef.current?.click()}>
              Import a workbook
            </Button>
          }
        />
      ) : (
        <>
          {/* ── The index: every system that has been tested ─────────── */}
          {!selected && (
            <Section title={`Tested systems (${projects.length})`}>
              <p className="mb-4 text-sm text-ink-3">
                One entry per round of testing. A system that is tested again
                against a new build gets its own entry, so each round keeps its
                own readiness figure.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[820px] text-sm">
                  <thead>
                    {/* Widths are set here rather than left to the content:
                        the project cell runs to three lines and would otherwise
                        take whatever it liked, leaving the narrow columns to
                        drift. Each header sits over its own column and is
                        aligned the way that column's values are. */}
                    <tr className="border-b border-stroke text-left text-[11px] uppercase tracking-wide text-ink-3">
                      <th className="w-[30%] py-2 pr-3 font-medium">Project</th>
                      <th className="w-[15%] py-2 pr-3 font-medium">Client</th>
                      <th className="w-[13%] py-2 pr-3 font-medium">Testing window</th>
                      <th className="w-[18%] py-2 pr-3 font-medium">Apps</th>
                      <th className="w-16 py-2 pr-3 text-right font-medium">Items</th>
                      <th className="w-36 py-2 pr-3 font-medium">Readiness</th>
                      <th className="py-2 font-medium" />
                    </tr>
                  </thead>
                  <tbody>
                    {projects.map((p) => (
                      <tr key={p.id}
                          className="border-b border-stroke last:border-0 hover:bg-subtle/50">
                        <td className="py-3 pr-3 align-top">
                          <button onClick={() => openProject(p.id)}
                                  className="text-left font-medium text-ink hover:text-brand">
                            {p.name}
                          </button>
                          {p.version_label && (
                            <div className="text-[12px] text-ink-3">{p.version_label}</div>
                          )}
                          {p.areas.some((a) => a.current_version) && (
                            <div className="text-[12px] text-ink-3">
                              {p.areas.filter((a) => a.current_version)
                                .map((a) => `${a.name} ${a.current_version}`)
                                .join("  ·  ")}
                            </div>
                          )}
                        </td>
                        <td className="py-3 pr-3 align-top text-ink-2">{p.client || "—"}</td>
                        <td className="py-3 pr-3 align-top text-ink-2">{p.window_label || "—"}</td>
                        <td className="py-3 pr-3 align-top text-ink-2">
                          {p.areas.length === 0 ? "—" : (
                            <span className="flex flex-wrap gap-1">
                              {p.areas.map((a) => (
                                <span key={a.id}
                                      className="rounded bg-subtle px-1.5 py-0.5 text-[11px] text-ink-2">
                                  {a.name}
                                </span>
                              ))}
                            </span>
                          )}
                        </td>
                        <td className="py-3 pr-3 align-top text-right tabular-nums text-ink-2">{p.rollup.total}</td>
                        <td className="py-3 pr-3 align-top">
                          {/* The figure is given a fixed width and tabular
                              figures so the bars all end on the same line and
                              the percentages read as a column rather than
                              shifting with the width of each number. */}
                          <span className="flex items-center gap-2">
                            <span className="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-subtle">
                              <span className="block h-full rounded-full"
                                    style={{
                                      width: `${p.rollup.readiness_pct}%`,
                                      backgroundColor:
                                        p.rollup.readiness_pct === 100 ? GREEN
                                        : p.rollup.outstanding > 0 ? RED : AMBER,
                                    }} />
                            </span>
                            <span className="w-10 text-right text-[12px] font-medium tabular-nums text-ink">
                              {p.rollup.readiness_pct}%
                            </span>
                          </span>
                        </td>
                        <td className="py-3 align-top text-right whitespace-nowrap">
                          <Button icon="link" onClick={() => openShare(p)}>
                            Share
                          </Button>
                          <span className="ml-2 inline-block align-middle">
                            <Button icon="sync"
                                    onClick={() => setRetestModal({
                                      from: p,
                                      name: `${p.name} - Retest`,
                                      window_start: "", window_end: "",
                                      include_items: true,
                                    })}>
                              Retest
                            </Button>
                          </span>
                          <span className="ml-2 inline-block align-middle">
                            <Button onClick={() => openProject(p.id)}>Open</Button>
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          {selected && (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <button onClick={() => openProject(null)}
                        className="flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink">
                  <Icon name="back" className="h-4 w-4" />
                  All tested systems
                </button>
                <span className="text-ink-3">/</span>
                <span className="text-[13px] font-medium text-ink">{selected.name}</span>
                <Button icon="link" onClick={() => openShare(selected)}>
                  Share with reviewer
                </Button>
                <Button icon="sync"
                        onClick={() => setRetestModal({
                          from: selected,
                          name: `${selected.name} - Retest`,
                          window_start: "", window_end: "",
                          include_items: true,
                        })}>
                  Retest this system
                </Button>
              </div>

              {/* Sheet tabs - one per sheet the workbook carried, however many
                  apps this project has. */}
              <div className="mb-5 flex flex-wrap items-center gap-1 border-b border-stroke pb-2">
                <TabButton active={view === "dashboard"}
                           onClick={() => setView("dashboard")}>
                  Dashboard
                </TabButton>
                {(areas ?? []).map((a) => (
                  <TabButton key={a.id} active={view === a.id}
                             onClick={() => {
                               setView(a.id); setFilter("All"); setSheetVersion(null);
                             }}>
                    {a.name}
                    <span className="ml-1.5 text-[11px] opacity-60">
                      {a.rollup.total}
                    </span>
                  </TabButton>
                ))}
                <TabButton active={view === "legend"} onClick={() => setView("legend")}>
                  Legend &amp; Criteria
                </TabButton>
                <TabButton active={view === "notes"} onClick={() => setView("notes")}>
                  Notes
                  {notes.length > 0 && (
                    <span className="ml-1.5 text-[11px] opacity-60">{notes.length}</span>
                  )}
                </TabButton>
                <button
                  onClick={() => setAreaModal({ id: 0, name: "", version_label: "" })}
                  className="ml-1 rounded-md px-2 py-1.5 text-[13px] text-ink-3 hover:bg-subtle hover:text-ink"
                >
                  + Add app
                </button>
              </div>

              {/* ── Dashboard ──────────────────────────────────────────── */}
              {view === "dashboard" && (
                <>
                  <Section
                    title={selected.name}
                    right={
                      <div className="flex items-center gap-2">
                        <Button icon="edit"
                                onClick={() => {
                                  setProjectForm({
                                    name: selected.name, client: selected.client,
                                    window_start: selected.window_start,
                                    window_end: selected.window_end,
                                    version_label: selected.version_label,
                                    summary: selected.summary, apps: [],
                                  });
                                  setProjectModal("edit");
                                }}>
                          Edit
                        </Button>
                        <Button variant="danger" icon="trash"
                                onClick={() => removeProject(selected)}>
                          Delete
                        </Button>
                      </div>
                    }
                  >
                    {(selected.client || selected.window_label || selected.version_label) && (
                      <p className="mb-1 text-sm text-ink-2">
                        {[selected.client, selected.window_label, selected.version_label]
                          .filter(Boolean).join("   ·   ")}
                      </p>
                    )}
                    {selected.summary && (
                      <p className="mb-4 text-sm text-ink-3">{selected.summary}</p>
                    )}

                    {/* One strip per app. Six apps get six strips. */}
                    {(areas ?? []).map((a) => (
                      <MetricStrip key={a.id} label={a.name}
                                   version={chainOf(a)} rollup={a.rollup} />
                    ))}

                    {(areas ?? []).length > 1 && (
                      <MetricStrip label="All apps" rollup={rollup} />
                    )}
                  </Section>

                  {(areas ?? []).length > 0 && (
                    <Section title="Readiness status">
                      <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-3">
                        {(areas ?? []).map((a) => (
                          <div key={a.id}>
                            <h4 className="mb-2 text-sm font-semibold text-ink">
                              {a.name}
                            </h4>
                            <ReadinessTable vocab={vocab} rollup={a.rollup} />
                          </div>
                        ))}
                      </div>
                    </Section>
                  )}
                </>
              )}

              {/* ── One app's sheet ────────────────────────────────────── */}
              {area && (
                <Section
                  title={area.name}
                  right={
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        value={search} onChange={(e) => setSearch(e.target.value)}
                        placeholder="Search items"
                        className="w-44 rounded-lg bg-subtle px-3 py-1.5 text-sm text-ink
                                   ring-1 ring-stroke placeholder:text-ink-3
                                   focus:outline-none focus:ring-brand/40"
                      />
                      <Button icon="edit"
                              onClick={() => setAreaModal({
                                id: area.id, name: area.name,
                                version_label: "",
                              })}>
                        Edit app name
                      </Button>
                      <Button variant="danger" icon="trash"
                              onClick={() => removeArea(area)}>
                        Delete
                      </Button>
                      <Button variant="primary" icon="plus"
                              onClick={() => setItemModal(blankDraft())}>
                        Add item
                      </Button>
                    </div>
                  }
                >
                  {/* Each build has its own sheet. A chain of buttons ran off
                      the row once an app had more than a few builds, so the
                      builds are a dropdown; the newest is selected on open,
                      because that is the one being tested. */}
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <label htmlFor="build-select" className="text-[12px] text-ink-3">
                      Build Version:
                    </label>
                    <select
                      id="build-select"
                      value={sheet?.version_id ?? ""}
                      onChange={(e) => setSheetVersion(Number(e.target.value))}
                      className="rounded-lg bg-subtle px-3 py-1.5 text-sm font-medium text-ink
                                 ring-1 ring-stroke focus:outline-none focus:ring-brand/40"
                    >
                      {area.sheets.map((sh, i) => (
                        <option key={sh.version_id} value={sh.version_id}>
                          {sh.label}
                          {`  (${sh.rollup.total} item${sh.rollup.total === 1 ? "" : "s"}`}
                          {`, ${sh.rollup.readiness_pct}%)`}
                          {i === area.sheets.length - 1 ? "  — current" : ""}
                        </option>
                      ))}
                    </select>
                    <span className="text-[12px] text-ink-3">
                      {area.sheets.length} build{area.sheets.length === 1 ? "" : "s"}
                    </span>
                    <Button icon="upload"
                            onClick={() => setVersionModal({ area, label: "", note: "" })}>
                      Release new version
                    </Button>
                  </div>

                  {sheet && sheet.version_id !== area.current_version_id && (
                    <div className="mb-3 rounded-lg bg-subtle px-3 py-2 text-[12px] text-ink-2">
                      Viewing build <strong>{sheet.label}</strong>, an earlier
                      release. The app&apos;s readiness comes from{" "}
                      <button onClick={() => setSheetVersion(area.current_version_id)}
                              className="font-medium text-brand hover:underline">
                        {area.current_version || "the current build"}
                      </button>.
                    </div>
                  )}

                  <div className="mb-4">
                    <MetricStrip label={`${area.name} ${sheet?.label ?? ""}`}
                                 rollup={sheet?.rollup ?? EMPTY_ROLLUP} />
                  </div>

                  <div className="mb-3 flex flex-wrap gap-2">
                    <Pill active={filter === "All"} onClick={() => setFilter("All")}>
                      All ({sheet?.rollup.total ?? 0})
                    </Pill>
                    {vocab?.readiness.map((r) => (
                      <Pill key={r.key} active={filter === r.key}
                            onClick={() => setFilter(r.key)}>
                        {r.label}
                      </Pill>
                    ))}
                    {(sheet?.rollup.carried_over ?? 0) > 0 && (
                      <span className="self-center text-[12px] text-ink-3">
                        {sheet!.rollup.carried_over} carried over from an earlier build
                      </span>
                    )}

                    {/* Density sits with the filters because it does the same
                        job: deciding how much of the sheet you see at once. */}
                    <div className="ml-auto flex items-center gap-1 rounded-lg border border-stroke p-0.5">
                      {([["Full", false], ["Compact", true]] as const).map(([label, val]) => (
                        <button
                          key={label}
                          onClick={() => toggleCompact(val)}
                          aria-pressed={compact === val}
                          title={val ? "Two-line previews — click an issue for the rest"
                                     : "Show every description in full"}
                          className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                            compact === val
                              ? "bg-brand text-white"
                              : "text-ink-2 hover:bg-subtle"}`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {visibleItems.length === 0 ? (
                    <EmptyState
                      icon="board" title="Nothing here"
                      hint={(sheet?.rollup.total ?? 0) === 0
                        ? "Nothing outstanding on this build."
                        : "No items match this filter."}
                    />
                  ) : (
                    // Wide columns with a sideways scroll: the text all wraps
                    // and stays visible, so width is what keeps each row
                    // shallow. StickyScroller keeps the bar on screen.
                    <StickyScroller>
                      {/* Compact pulls ~560px out of the table, which is what
                          stops the sideways scroll on a normal screen. */}
                      <table className={`w-full table-fixed text-sm ${
                        compact ? "min-w-[1400px]" : "min-w-[1960px]"}`}>
                        <thead>
                          <tr style={{ backgroundColor: NAVY }} className="text-left text-white">
                            {[["Issue", "w-80"],
                              ["Description", compact ? "w-64" : "w-[28rem]"],
                              ["Feedback Bucket", "w-44"],
                              ["Development Feedback", "w-52"],
                              ["Client Test / Review Status", "w-40"],
                              ["Readiness Status", "w-44"],
                              ["Client Feedback / Comments", compact ? "w-56" : "w-[26rem]"],
                              ["", "w-28"]].map(([h, w], i) => (
                              <th key={i}
                                  className={`${w} px-3 py-2 text-[11px] font-semibold uppercase tracking-wide`}>
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {visibleItems.map((it) => (
                            <ItemRow
                              key={it.iteration_id}
                              item={it}
                              vocab={vocab}
                              compact={compact}
                              busy={busy}
                              onSave={(patch) => saveRow(it, patch)}
                              onRetest={() => setRetestItem({
                                item: it,
                                dev_status: "done_internally_tested",
                                tested: "tested",
                                readiness: "pass",
                                client_feedback: "",
                              })}
                              onDelete={() => removeItem(it)}
                              onDirty={markDirty}
                            />
                          ))}
                        </tbody>
                      </table>
                    </StickyScroller>
                  )}
                </Section>
              )}

              {/* ── Legend & Criteria ──────────────────────────────────── */}
              {view === "legend" && vocab && (
                <Section title="Testing criteria & status definitions">
                  <p className="mb-4 text-sm text-ink-3">
                    These definitions are shared by every project and are written into
                    each exported pack, so the criteria cannot drift between clients.
                  </p>
                  {vocab.legend.map((block) => (
                    <div key={block.heading} className="mb-6 last:mb-0">
                      <div className="mb-2 rounded px-3 py-1.5 text-sm font-semibold text-white"
                           style={{ backgroundColor: SLATE }}>
                        {block.heading}
                      </div>
                      <table className="w-full text-sm">
                        <tbody>
                          {block.entries.map((e) => (
                            <tr key={e.label} className="border-b border-stroke last:border-0 align-top">
                              <td className="w-56 py-2 pr-4">
                                <span className="inline-block rounded px-2 py-1 text-[12px] font-semibold"
                                      style={{ backgroundColor: e.fill, color: e.ink }}>
                                  {e.label}
                                </span>
                              </td>
                              <td className="py-2 text-[13px] leading-relaxed text-ink-2">
                                {e.definition}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
                </Section>
              )}

              {/* ── Notes ──────────────────────────────────────────────── */}
              {view === "notes" && (
                <Section
                  title="Enhancements parked for later"
                  right={
                    <Button variant="primary" icon="plus"
                            onClick={() => setNoteModal({ id: 0, text: "" })}>
                      Add note
                    </Button>
                  }
                >
                  {notes.length === 0 ? (
                    <EmptyState icon="file" title="No notes yet"
                                hint="Enhancements raised during testing but not in scope for this round." />
                  ) : (
                    <table className="w-full text-sm">
                      <tbody>
                        {notes.map((n, i) => (
                          <tr key={n.id} className="border-b border-stroke last:border-0">
                            <td className="w-10 py-2 text-ink-3">{i + 1}</td>
                            <td className="py-2">
                              <button onClick={() => toggleNote(n)}
                                      className={`text-left ${n.is_done
                                        ? "text-ink-3 line-through" : "text-ink-2"}`}>
                                {n.text}
                              </button>
                            </td>
                            <td className="w-24 py-2 text-right whitespace-nowrap">
                              <button onClick={() => setNoteModal({ id: n.id, text: n.text })}
                                      className="rounded p-1.5 text-ink-3 hover:bg-subtle hover:text-ink"
                                      aria-label="Edit note">
                                <Icon name="edit" />
                              </button>
                              <button onClick={() => removeNote(n)}
                                      className="rounded p-1.5 text-ink-3 hover:bg-subtle hover:text-bad"
                                      aria-label="Delete note">
                                <Icon name="trash" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </Section>
              )}
            </>
          )}
        </>
      )}

      {/* ── modals ─────────────────────────────────────────────────────── */}

      {projectModal && (
        <Modal
          title={projectModal === "edit" ? "Edit project" : "New testing project"}
          onClose={() => setProjectModal(null)}
          footer={
            <>
              <Button onClick={() => setProjectModal(null)}>Cancel</Button>
              <Button variant="primary" spinning={busy} onClick={saveProject}>Save</Button>
            </>
          }
        >
          <div className="space-y-3">
            <TextInput label="Project name" value={projectForm.name}
                       onChange={(v) => setProjectForm({ ...projectForm, name: v })}
                       placeholder="E-Crop Stress Testing" />
            <TextInput label="Client" value={projectForm.client}
                       onChange={(v) => setProjectForm({ ...projectForm, client: v })} />
            <div className="grid gap-3 sm:grid-cols-2">
              <TextInput label="Testing window starts" type="date"
                         value={projectForm.window_start}
                         onChange={(v) => setProjectForm({ ...projectForm, window_start: v })} />
              <TextInput label="Testing window ends" type="date"
                         value={projectForm.window_end}
                         onChange={(v) => setProjectForm({ ...projectForm, window_end: v })} />
            </div>
            <TextInput label="Release / round" value={projectForm.version_label}
                       onChange={(v) => setProjectForm({ ...projectForm, version_label: v })}
                       hint="Each app carries its own version - set those on the app itself." />
            <AreaInput label="Summary" value={projectForm.summary} rows={3}
                       onChange={(v) => setProjectForm({ ...projectForm, summary: v })}
                       hint="The blurb at the top of the client pack." />
            {projectModal === "new" && (
              <div>
                <div className="mb-1 text-[13px] font-medium text-ink">
                  Apps under test, and the build each starts on
                </div>
                <p className="mb-2 text-[12px] text-ink-3">
                  Named for this system rather than the last one. Each app keeps
                  its own sheet, readiness figure and build history.
                </p>
                <div className="space-y-2">
                  {projectForm.apps.map((app, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <input
                        value={app.name}
                        onChange={(e) => {
                          const apps = [...projectForm.apps];
                          apps[i] = { ...apps[i], name: e.target.value };
                          setProjectForm({ ...projectForm, apps });
                        }}
                        placeholder="Inspector App"
                        className="flex-1 rounded-lg bg-subtle px-3 py-2 text-sm text-ink
                                   ring-1 ring-stroke placeholder:text-ink-3
                                   focus:outline-none focus:ring-brand/40"
                      />
                      <input
                        value={app.version}
                        onChange={(e) => {
                          const apps = [...projectForm.apps];
                          apps[i] = { ...apps[i], version: e.target.value };
                          setProjectForm({ ...projectForm, apps });
                        }}
                        placeholder="Starting build, e.g. 1.1.2"
                        className="w-52 rounded-lg bg-subtle px-3 py-2 text-sm text-ink
                                   ring-1 ring-stroke placeholder:text-ink-3
                                   focus:outline-none focus:ring-brand/40"
                      />
                      {projectForm.apps.length > 1 && (
                        <button
                          onClick={() => setProjectForm({
                            ...projectForm,
                            apps: projectForm.apps.filter((_, j) => j !== i),
                          })}
                          className="rounded p-1.5 text-ink-3 hover:bg-subtle hover:text-bad"
                          aria-label="Remove app"
                        >
                          <Icon name="trash" className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                <button
                  onClick={() => setProjectForm({
                    ...projectForm,
                    apps: [...projectForm.apps, { name: "", version: "" }],
                  })}
                  className="mt-2 text-[12px] font-medium text-brand hover:underline"
                >
                  + Add another app
                </button>
              </div>
            )}
          </div>
        </Modal>
      )}

      {areaModal && (
        <Modal
          title={areaModal.id === 0 ? "Add app" : "Edit app name"}
          onClose={() => setAreaModal(null)}
          footer={
            <>
              <Button onClick={() => setAreaModal(null)}>Cancel</Button>
              <Button variant="primary" spinning={busy} onClick={saveArea}>Save</Button>
            </>
          }
        >
          <div className="space-y-3">
            <TextInput label="App name" value={areaModal.name}
                       onChange={(v) => setAreaModal({ ...areaModal, name: v })}
                       placeholder="Inspector App"
                       hint="One app per surface under test. Each gets its own sheet, dashboard strip and readiness figure." />
            {areaModal.id === 0 && (
              <TextInput label="Starting version" value={areaModal.version_label}
                         onChange={(v) => setAreaModal({ ...areaModal, version_label: v })}
                         placeholder="2.1.5"
                         hint="The build this app starts on. Record later builds with Release new version as they ship." />
            )}
          </div>
        </Modal>
      )}

      {itemModal && vocab && (
        <Modal
          title={itemModal.id > 0 ? "Edit item" : "Add item"}
          onClose={() => setItemModal(null)}
          wide
          footer={
            <>
              <Button onClick={() => setItemModal(null)}>Cancel</Button>
              <Button variant="primary" spinning={busy} onClick={saveItem}>Save</Button>
            </>
          }
        >
          <div className="space-y-3">
            <TextInput label="Issue" value={itemModal.issue}
                       onChange={(v) => setItemModal({ ...itemModal, issue: v })} />
            <AreaInput label="Description" value={itemModal.description} rows={3}
                       onChange={(v) => setItemModal({ ...itemModal, description: v })} />
            <div className="grid gap-3 sm:grid-cols-2">
              <SelectInput label="Feedback bucket" value={itemModal.bucket}
                           onChange={(v) => setItemModal({ ...itemModal, bucket: v })}
                           options={vocab.buckets.map((c) => ({ value: c.key, label: c.label }))} />
              <SelectInput label="Development Feedback" value={itemModal.dev_status}
                           onChange={(v) => setItemModal({ ...itemModal, dev_status: v })}
                           options={vocab.dev_statuses.map((c) => ({ value: c.key, label: c.label }))} />
              <SelectInput label="Client Test / Review Status" value={itemModal.tested}
                           onChange={(v) => setItemModal({ ...itemModal, tested: v })}
                           options={vocab.tested.map((c) => ({ value: c.key, label: c.label }))} />
              <SelectInput label="Readiness Status" value={itemModal.readiness}
                           onChange={(v) => setItemModal({ ...itemModal, readiness: v })}
                           options={vocab.readiness.map((c) => ({ value: c.key, label: c.label }))}
                           hint="Only PASS counts towards readiness." />
            </div>
            <AreaInput label="Client Feedback / Comments" rows={3}
                       value={itemModal.client_feedback}
                       onChange={(v) => setItemModal({ ...itemModal, client_feedback: v })} />
          </div>
        </Modal>
      )}

      {noteModal && (
        <Modal
          title={noteModal.id === 0 ? "Add note" : "Edit note"}
          onClose={() => setNoteModal(null)}
          footer={
            <>
              <Button onClick={() => setNoteModal(null)}>Cancel</Button>
              <Button variant="primary" spinning={busy} onClick={saveNote}>Save</Button>
            </>
          }
        >
          <AreaInput label="Enhancement" value={noteModal.text} rows={3}
                     onChange={(v) => setNoteModal({ ...noteModal, text: v })} />
        </Modal>
      )}

      {shareModal && (
        <Modal
          title={`Share ${shareModal.project.name}`}
          onClose={() => setShareModal(null)}
          wide
          footer={<Button onClick={() => setShareModal(null)}>Done</Button>}
        >
          <div className="space-y-4">
            <p className="text-sm text-ink-2">
              A share link opens this project — and only this project — for a
              reviewer with no account. They can set the{" "}
              <strong>Client Test / Review Status</strong>,{" "}
              <strong>Readiness Status</strong> and{" "}
              <strong>Client Feedback / Comments</strong> on any row. They cannot
              see other projects, import a workbook, create a project, or change
              the issues themselves.
            </p>

            <div className="flex items-end gap-2">
              <div className="flex-1">
                <TextInput label="Who is this link for?" value={shareModal.label}
                           onChange={(v) => setShareModal({ ...shareModal, label: v })}
                           placeholder="NAB review team"
                           hint="Recorded so you can revoke the right link later." />
              </div>
              <Button variant="primary" icon="plus" spinning={busy}
                      onClick={createShare}>
                Create link
              </Button>
            </div>

            {shareModal.links.length === 0 ? (
              <p className="text-[12px] text-ink-3">No links yet.</p>
            ) : (
              <table className="w-full text-sm">
                <tbody>
                  {shareModal.links.map((l) => (
                    <tr key={l.id} className="border-b border-stroke last:border-0">
                      <td className="py-2 pr-3">
                        <div className="font-medium text-ink">
                          {l.label || "Shared link"}
                        </div>
                        <div className="font-mono text-[11px] break-all text-ink-3">
                          {l.path}
                        </div>
                        {!l.is_active && (
                          <span className="text-[11px] font-medium text-bad">Revoked</span>
                        )}
                        {l.last_opened_at && (
                          <span className="ml-2 text-[11px] text-ink-3">
                            last opened {new Date(l.last_opened_at).toLocaleString()}
                          </span>
                        )}
                      </td>
                      <td className="py-2 text-right whitespace-nowrap">
                        {l.is_active && (
                          <>
                            <Button icon="link" onClick={() => copyShare(l)}>
                              {shareModal.copied === l.token ? "Copied" : "Copy"}
                            </Button>
                            <span className="ml-2 inline-block align-middle">
                              <Button variant="danger" onClick={() => revokeShare(l)}>
                                Revoke
                              </Button>
                            </span>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Modal>
      )}

      {retestItem && vocab && (
        <Modal
          title={`Retest: ${retestItem.item.issue}`}
          onClose={() => setRetestItem(null)}
          wide
          footer={
            <>
              <Button onClick={() => setRetestItem(null)}>Cancel</Button>
              <Button variant="primary" spinning={busy} onClick={addIteration}>
                Record pass {retestItem.item.pass_number + 1}
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-sm text-ink-2">
              This adds pass {retestItem.item.pass_number + 1} rather than
              overwriting the last one, so the sheet shows the issue was raised,
              actioned and re-verified.
            </p>
            <div className="rounded-lg bg-subtle px-3 py-2 text-[12px] text-ink-2">
              <span className="font-medium">Previously: </span>
              <StatusCell vocab={vocab} label={retestItem.item.readiness_display} />
              {retestItem.item.client_feedback && (
                <div className="mt-1 whitespace-pre-line text-ink-3">
                  {retestItem.item.client_feedback}
                </div>
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <SelectInput label="Development Feedback" value={retestItem.dev_status}
                           onChange={(v) => setRetestItem({ ...retestItem, dev_status: v })}
                           options={vocab.dev_statuses.map((c) => ({ value: c.key, label: c.label }))} />
              <SelectInput label="Client Test / Review Status" value={retestItem.tested}
                           onChange={(v) => setRetestItem({ ...retestItem, tested: v })}
                           options={vocab.tested.map((c) => ({ value: c.key, label: c.label }))} />
              <SelectInput label="Readiness Status" value={retestItem.readiness}
                           onChange={(v) => setRetestItem({ ...retestItem, readiness: v })}
                           options={vocab.readiness.map((c) => ({ value: c.key, label: c.label }))} />
            </div>
            <AreaInput label="Client Feedback / Comments for this pass" rows={3}
                       value={retestItem.client_feedback}
                       onChange={(v) => setRetestItem({ ...retestItem, client_feedback: v })}
                       hint="Appended under the earlier pass in the exported pack, not replacing it." />
          </div>
        </Modal>
      )}

      {versionModal && (
        <Modal
          title={`Release a new version of ${versionModal.area.name}`}
          onClose={() => setVersionModal(null)}
          footer={
            <>
              <Button onClick={() => setVersionModal(null)}>Cancel</Button>
              <Button variant="primary" spinning={busy} onClick={releaseVersion}>
                Record build
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-sm text-ink-2">
              A build gets its own sheet. Everything that has not reached PASS on{" "}
              <strong>{versionModal.area.current_version || "the current build"}</strong>{" "}
              is still outstanding, so it opens on the new sheet automatically —
              you do not retype the backlog. Issues that passed stay behind on the
              sheet that signed them off.
            </p>
            {versionModal.area.versions.length > 0 && (
              <p className="text-[12px] text-ink-3">
                Currently on {versionModal.area.current_version}.
              </p>
            )}
            <TextInput label="Version" value={versionModal.label}
                       onChange={(v) => setVersionModal({ ...versionModal, label: v })}
                       placeholder="2.1.6" />
            <TextInput label="What changed (optional)" value={versionModal.note}
                       onChange={(v) => setVersionModal({ ...versionModal, note: v })}
                       placeholder="Block number fix, cultivar list" />
          </div>
        </Modal>
      )}

      {retestModal && (
        <Modal
          title="Start a retest"
          onClose={() => setRetestModal(null)}
          footer={
            <>
              <Button onClick={() => setRetestModal(null)}>Cancel</Button>
              <Button variant="primary" spinning={busy} onClick={startRetest}>
                Create round
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-sm text-ink-2">
              This creates a new entry from <strong>{retestModal.from.name}</strong>,
              carrying its apps across. Verdicts do not carry over — nothing in a
              new round has been tested yet — so it starts at 0% readiness.
            </p>
            <TextInput label="New project name" value={retestModal.name}
                       onChange={(v) => setRetestModal({ ...retestModal, name: v })}
                       hint="Each round is its own entry, so give it a name that says which round it is." />
            <div className="grid gap-3 sm:grid-cols-2">
              <TextInput label="Testing window starts" type="date"
                         value={retestModal.window_start}
                         onChange={(v) => setRetestModal({ ...retestModal, window_start: v })} />
              <TextInput label="Testing window ends" type="date"
                         value={retestModal.window_end}
                         onChange={(v) => setRetestModal({ ...retestModal, window_end: v })} />
            </div>
            <label className="flex items-start gap-2 text-sm text-ink-2">
              <input type="checkbox" checked={retestModal.include_items}
                     onChange={(e) => setRetestModal({
                       ...retestModal, include_items: e.target.checked })}
                     className="mt-0.5" />
              <span>
                Carry the items across to re-check
                <span className="block text-[12px] text-ink-3">
                  Untick to start with the apps only and an empty sheet.
                </span>
              </span>
            </label>
          </div>
        </Modal>
      )}

      {confirm && (
        <ConfirmDialog
          title={confirm.title}
          body={confirm.body}
          confirmLabel="Delete"
          onConfirm={confirm.run}
          onClose={() => setConfirm(null)}
        />
      )}
    </AppShell>
  );
}

function TabButton({ active, onClick, children }:
  { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition ${
        active ? "bg-brand/10 text-brand" : "text-ink-2 hover:bg-subtle hover:text-ink"}`}
    >
      {children}
    </button>
  );
}
