"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";

/* The reviewer's view of one project.
 *
 * Reached by a share link, with no account and no session. It deliberately has
 * no sidebar, no project switcher, no import and no way to create anything: the
 * only things a reviewer can change are the three columns that are theirs to
 * fill in. That is enforced on the server too - this page simply does not offer
 * anything else. */

const NAVY = "#1F2A44";
const NAVY_DEEP = "#16213A";
const SLATE = "#3D5A80";
const GREEN = "#1E7B34";
const AMBER = "#9C6500";
const RED = "#C00000";

type Choice = { key: string; label: string };
type LegendEntry = { label: string; definition: string; fill: string; ink: string };
type LegendBlock = { heading: string; entries: LegendEntry[] };
type Rollup = {
  total: number; pass: number; requires_action: number; outstanding: number;
  pending_retest: number; tested: number; not_tested: number;
  readiness_pct: number; carried_over: number;
};
type Row = {
  iteration_id: number; issue: string; description: string;
  bucket_display: string; dev_status_display: string;
  pass_number: number; carried_over: boolean;
  tested: string; tested_display: string;
  readiness: string; readiness_display: string;
  client_feedback: string;
};
type Sheet = { version_id: number; label: string; rollup: Rollup; items: Row[] };
type Area = {
  id: number; name: string; current_version: string;
  current_version_id: number | null; rollup: Rollup; sheets: Sheet[];
};
type Payload = {
  project: {
    name: string; client: string; summary: string; testing_window: string;
    version_label: string; rollup: Rollup;
  };
  areas: Area[];
  vocabularies: { tested: Choice[]; readiness: Choice[]; legend: LegendBlock[] };
  from_company: string;
};

const TILES: { key: keyof Rollup; label: string; colour: string }[] = [
  { key: "total", label: "Total Items", colour: NAVY },
  { key: "pass", label: "PASS", colour: GREEN },
  { key: "requires_action", label: "Requires Action", colour: AMBER },
  { key: "outstanding", label: "Outstanding", colour: RED },
  { key: "pending_retest", label: "Pending Retest", colour: SLATE },
  { key: "readiness_pct", label: "Readiness %", colour: NAVY_DEEP },
];

function swatch(legend: LegendBlock[], label: string): LegendEntry | null {
  for (const block of legend) {
    const hit = block.entries.find((e) => e.label === label);
    if (hit) return hit;
  }
  return null;
}

/** A status shown but not editable here - coloured exactly as it is on the
    platform, so a reviewer and the team are reading the same sheet. The
    definition is on hover, because these are the terms being judged against. */
function StatusChip({ legend, label }: { legend: LegendBlock[]; label: string }) {
  const s = swatch(legend, label);
  if (!s) return <span className="text-[12px] text-slate-600">{label}</span>;
  return (
    <span className="inline-block rounded px-2 py-0.5 text-[11px] font-semibold"
          title={s.definition ? `${label} — ${s.definition}` : label}
          style={{ backgroundColor: s.fill, color: s.ink }}>
      {label}
    </span>
  );
}

function Strip({ label, rollup }: { label: string; rollup: Rollup }) {
  return (
    <div className="mb-5">
      <h3 className="mb-2 text-sm font-semibold text-slate-800">{label}</h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {TILES.map((t) => (
          <div key={t.key} className="overflow-hidden rounded-lg ring-1 ring-slate-200">
            <div className="px-2 py-1.5 text-center text-[10px] font-semibold leading-tight text-white"
                 style={{ backgroundColor: t.colour }}>
              {t.label}
            </div>
            <div className="bg-white py-2 text-center text-2xl font-bold"
                 style={{ color: t.colour }}>
              {t.key === "readiness_pct" ? `${rollup.readiness_pct}%` : rollup[t.key]}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Grows to fit its content, so a long review note is never behind a scrollbar. */
function AutoTextarea({ value, onChange, placeholder }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const fit = (el: HTMLTextAreaElement | null) => {
    if (!el) return;
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
      className="w-full resize-none overflow-hidden rounded bg-slate-50 px-2 py-1.5
                 text-[12px] leading-relaxed text-slate-900 ring-1 ring-transparent
                 placeholder:text-slate-400 hover:ring-slate-300 focus:outline-none
                 focus:ring-2 focus:ring-sky-500/40"
    />
  );
}

/** Keeps the horizontal scrollbar on screen, however tall the sheet gets. */
function StickyScroller({ children }: { children: React.ReactNode }) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const spacerRef = useRef<HTMLDivElement>(null);
  const [overflowing, setOverflowing] = useState(false);
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
    requestAnimationFrame(() => { syncing.current = false; });
  };

  return (
    <>
      <div ref={bodyRef} className="overflow-x-auto"
           onScroll={() => mirror(bodyRef.current, barRef.current)}>
        {children}
      </div>
      {overflowing && (
        <div ref={barRef}
             onScroll={() => mirror(barRef.current, bodyRef.current)}
             className="sticky bottom-0 z-20 overflow-x-auto border-t border-slate-200
                        bg-white/95 backdrop-blur"
             aria-hidden>
          <div ref={spacerRef} className="h-3" />
        </div>
      )}
    </>
  );
}

function ReviewRow({ row, vocab, onSave, saving }: {
  row: Row;
  vocab: Payload["vocabularies"];
  onSave: (patch: Partial<Row>) => void;
  saving: boolean;
}) {
  const fields = ["tested", "readiness", "client_feedback"] as const;
  const serverValues = () => ({
    tested: row.tested, readiness: row.readiness,
    client_feedback: row.client_feedback,
  });

  const [draft, setDraft] = useState(serverValues);
  const [seen, setSeen] = useState(serverValues);

  /* The team edits these same rows from the platform. Adopt what they change,
     field by field, but never over something this reviewer has typed and not
     yet saved - and without remounting the row, which would make the page
     flicker and drop the cursor. */
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

  const select = (value: string, options: Choice[], onChange: (v: string) => void) => {
    const label = options.find((o) => o.key === value)?.label ?? "";
    const s = swatch(vocab.legend, label);
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)}
              title={s?.definition ? `${label} — ${s.definition}` : label}
              className="w-full cursor-pointer rounded px-2 py-1 text-[11px] font-semibold
                         ring-1 ring-transparent hover:ring-slate-300 focus:outline-none
                         focus:ring-2 focus:ring-sky-500/40"
              style={s ? { backgroundColor: s.fill, color: s.ink } : undefined}>
        {options.map((o) => {
          const def = swatch(vocab.legend, o.label)?.definition;
          return (
            <option key={o.key} value={o.key}
                    title={def ? `${o.label} — ${def}` : o.label}>
              {o.label}
            </option>
          );
        })}
      </select>
    );
  };

  return (
    <tr className="border-b border-slate-200 align-top last:border-0">
      <td className="px-2 py-2">
        <div className="font-medium break-words whitespace-pre-wrap text-slate-900">
          {row.issue}
        </div>
        {row.carried_over && (
          <div className="mt-1 text-[11px] text-amber-700">
            carried over from an earlier build
          </div>
        )}
      </td>
      <td className="px-2 py-2 text-[12px] leading-relaxed text-slate-600">
        <div className="break-words whitespace-pre-wrap">{row.description}</div>
      </td>
      <td className="px-2 py-2">
        <StatusChip legend={vocab.legend} label={row.bucket_display} />
      </td>
      <td className="px-2 py-2">
        <StatusChip legend={vocab.legend} label={row.dev_status_display} />
      </td>
      <td className="px-2 py-2">
        {select(draft.tested, vocab.tested, (v) => setDraft({ ...draft, tested: v }))}
      </td>
      <td className="px-2 py-2">
        {select(draft.readiness, vocab.readiness,
                (v) => setDraft({ ...draft, readiness: v }))}
      </td>
      <td className="px-2 py-2">
        <AutoTextarea value={draft.client_feedback}
                      onChange={(v) => setDraft({ ...draft, client_feedback: v })}
                      placeholder="What you found…" />
      </td>
      <td className="px-2 py-2 text-right">
        {dirty && (
          <button onClick={() => onSave(draft)} disabled={saving}
                  className="rounded-md bg-sky-600 px-2.5 py-1 text-[11px] font-semibold
                             text-white hover:bg-sky-700 disabled:opacity-50">
            Save
          </button>
        )}
      </td>
    </tr>
  );
}

export default function SharedReadinessPage(
  { params }: { params: Promise<{ token: string }> },
) {
  const { token } = use(params);
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [areaId, setAreaId] = useState<number | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);

  const load = useCallback(async () => {
    const res = await fetch(`/api/public/readiness/${token}`);
    if (!res.ok) {
      let detail = "This link is not valid.";
      try { detail = (await res.json()).detail ?? detail; } catch {}
      setError(detail);
      return;
    }
    setData(await res.json());
  }, [token]);

  useEffect(() => {
    // load() only sets state after awaiting its fetch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  /* Live sync with the team working the same sheet in the platform: ask only
     for what changed and patch those rows in, so nothing else re-renders. */
  const syncedAt = useRef<string | null>(null);

  useEffect(() => {
    let stopped = false;

    async function tick() {
      if (stopped || document.hidden) return;
      const since = syncedAt.current;
      const res = await fetch(
        `/api/public/readiness/${token}/changes`
        + (since ? `?since=${encodeURIComponent(since)}` : ""));
      if (!res.ok || stopped) return;
      const delta = await res.json();
      const first = syncedAt.current === null;
      syncedAt.current = delta.server_time;
      if (first) return;

      let mustReload = false;
      setData((cur) => {
        if (!cur) return cur;
        const counts = new Map<number, number>();
        for (const a of delta.areas) {
          for (const sh of a.sheets) counts.set(sh.version_id, sh.count);
        }
        const patches = new Map<number, Row>();
        for (const c of delta.changed) patches.set(c.item.iteration_id, c.item);

        return {
          ...cur,
          areas: cur.areas.map((area) => {
            const server = delta.areas.find(
              (a: { id: number }) => a.id === area.id);
            const sheets = area.sheets.map((sh) => {
              if (counts.get(sh.version_id) !== sh.items.length) mustReload = true;
              const serverSheet = server?.sheets.find(
                (x: { version_id: number }) => x.version_id === sh.version_id);
              const items = sh.items.map(
                (r) => patches.get(r.iteration_id) ?? r);
              if (items.every((r, i) => r === sh.items[i])
                  && serverSheet?.rollup === sh.rollup) return sh;
              return { ...sh, items, rollup: serverSheet?.rollup ?? sh.rollup };
            });
            return { ...area, sheets, rollup: server?.rollup ?? area.rollup };
          }),
        };
      });

      if (mustReload) await load();
    }

    const id = window.setInterval(() => { void tick(); }, 5000);
    void tick();
    return () => { stopped = true; window.clearInterval(id); };
  }, [token, load]);

  async function save(row: Row, patch: Partial<Row>) {
    setSaving(true);
    try {
      const res = await fetch(`/api/public/readiness/${token}/rows/${row.iteration_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!res.ok) {
        let detail = "Could not save that row.";
        try { detail = (await res.json()).detail ?? detail; } catch {}
        setError(detail);
        return;
      }
      const out = await res.json();
      // Patch just this row, rather than reloading the project and re-rendering
      // every other row that did not change.
      setData((cur) => cur && {
        ...cur,
        areas: cur.areas.map((a) => ({
          ...a,
          sheets: a.sheets.map((sh) => {
            const idx = sh.items.findIndex(
              (r) => r.iteration_id === out.item.iteration_id);
            if (idx < 0) return sh;
            const items = [...sh.items];
            items[idx] = out.item;
            return { ...sh, items, rollup: out.rollup };
          }),
        })),
      });
    } finally {
      setSaving(false);
    }
  }

  if (error && !data) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
        <div className="max-w-md rounded-xl bg-white p-8 text-center ring-1 ring-slate-200">
          <h1 className="text-lg font-semibold text-slate-900">Link unavailable</h1>
          <p className="mt-2 text-sm text-slate-600">{error}</p>
        </div>
      </main>
    );
  }
  if (!data) return null;

  const area = data.areas.find((a) => a.id === areaId) ?? data.areas[0] ?? null;
  const sheet = area
    ? (area.sheets.find((sh) => sh.version_id === versionId)
       ?? area.sheets[area.sheets.length - 1] ?? null)
    : null;

  return (
    <main className="min-h-screen bg-slate-100 pb-10">
      <header style={{ backgroundColor: NAVY }} className="px-6 py-5 text-white">
        <h1 className="text-xl font-bold">{data.project.name}</h1>
        <p className="mt-1 text-[13px] text-slate-300">
          {[data.project.client, data.project.testing_window, data.project.version_label]
            .filter(Boolean).join("   ·   ")}
        </p>
      </header>

      <div className="mx-auto max-w-[1800px] px-4 pt-5 sm:px-6">
        {data.project.summary && (
          <p className="mb-4 text-sm text-slate-600">{data.project.summary}</p>
        )}

        <div className="mb-5 rounded-lg bg-sky-50 px-4 py-3 text-[13px] text-sky-900
                        ring-1 ring-sky-200">
          You can set the <strong>Client Test / Review Status</strong>,{" "}
          <strong>Readiness Status</strong> and{" "}
          <strong>Client Feedback / Comments</strong> on any row. Changes save when
          you press Save on that row.
        </div>

        {error && (
          <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700
                          ring-1 ring-red-200">
            {error}
          </div>
        )}

        <div className="rounded-xl bg-white p-4 ring-1 ring-slate-200">
          {/* Apps */}
          <div className="mb-4 flex flex-wrap gap-1 border-b border-slate-200 pb-2">
            {data.areas.map((a) => (
              <button key={a.id}
                      onClick={() => { setAreaId(a.id); setVersionId(null); }}
                      className={`rounded-md px-3 py-1.5 text-[13px] font-medium ${
                        area?.id === a.id
                          ? "bg-sky-50 text-sky-700"
                          : "text-slate-600 hover:bg-slate-100"}`}>
                {a.name}
                <span className="ml-1.5 text-[11px] opacity-60">{a.rollup.total}</span>
              </button>
            ))}
          </div>

          {area && (
            <>
              {/* Builds, as a dropdown - a chain of buttons runs off the row
                  once an app has more than a few. */}
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <label htmlFor="build" className="text-[12px] text-slate-500">
                  Build Version:
                </label>
                <select id="build"
                        value={sheet?.version_id ?? ""}
                        onChange={(e) => setVersionId(Number(e.target.value))}
                        className="rounded-lg bg-slate-50 px-3 py-1.5 text-sm font-medium
                                   text-slate-900 ring-1 ring-slate-300 focus:outline-none
                                   focus:ring-2 focus:ring-sky-500/40">
                  {area.sheets.map((sh, i) => (
                    <option key={sh.version_id} value={sh.version_id}>
                      {sh.label}
                      {`  (${sh.rollup.total} item${sh.rollup.total === 1 ? "" : "s"}`}
                      {`, ${sh.rollup.readiness_pct}%)`}
                      {i === area.sheets.length - 1 ? "  — current" : ""}
                    </option>
                  ))}
                </select>
              </div>

              <Strip label={`${area.name} ${sheet?.label ?? ""}`}
                     rollup={sheet?.rollup ?? area.rollup} />

              {!sheet || sheet.items.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  Nothing outstanding on this build.
                </p>
              ) : (
                <StickyScroller>
                  <table className="w-full min-w-[1800px] table-fixed text-sm">
                    <thead>
                      <tr style={{ backgroundColor: NAVY }} className="text-left text-white">
                        {[["Issue", "w-80"],
                          ["Description", "w-[28rem]"], ["Feedback Bucket", "w-44"],
                          ["Development Feedback", "w-52"],
                          ["Client Test / Review Status", "w-44"],
                          ["Readiness Status", "w-44"],
                          ["Client Feedback / Comments", "w-[26rem]"],
                          ["", "w-20"]].map(([h, w], i) => (
                          <th key={i}
                              className={`${w} px-3 py-2 text-[11px] font-semibold uppercase tracking-wide`}>
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sheet.items.map((row) => (
                        <ReviewRow
                          key={row.iteration_id}
                          row={row}
                          vocab={data.vocabularies}
                          saving={saving}
                          onSave={(patch) => save(row, patch)}
                        />
                      ))}
                    </tbody>
                  </table>
                </StickyScroller>
              )}
            </>
          )}
        </div>

        {/* The criteria they are judging against. */}
        <div className="mt-5 rounded-xl bg-white p-4 ring-1 ring-slate-200">
          <h2 className="mb-3 text-sm font-semibold text-slate-900">
            What the statuses mean
          </h2>
          {data.vocabularies.legend.map((block) => (
            <div key={block.heading} className="mb-5 last:mb-0">
              <div className="mb-2 rounded px-3 py-1.5 text-sm font-semibold text-white"
                   style={{ backgroundColor: SLATE }}>
                {block.heading}
              </div>
              <table className="w-full text-sm">
                <tbody>
                  {block.entries.map((e) => (
                    <tr key={e.label} className="border-b border-slate-200 align-top last:border-0">
                      <td className="w-56 py-2 pr-4">
                        <span className="inline-block rounded px-2 py-1 text-[12px] font-semibold"
                              style={{ backgroundColor: e.fill, color: e.ink }}>
                          {e.label}
                        </span>
                      </td>
                      <td className="py-2 text-[13px] leading-relaxed text-slate-600">
                        {e.definition}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>

        <p className="mt-6 text-center text-[12px] text-slate-400">
          {data.from_company}
        </p>
      </div>
    </main>
  );
}
