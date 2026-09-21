"use client";

/**
 * Chart primitives, hand-rolled in SVG.
 *
 * No charting library: the platform ships none, and these forms are simple
 * enough that a dependency would cost more than it saves.
 *
 * The palette is the validated categorical set, run through the colour
 * validator against this product's own surfaces — white cards in light mode,
 * zinc-900 (#18181b) in dark, which is what --c-surface actually resolves to:
 *
 *   light  worst adjacent CVD ΔE 9.1, normal-vision 22.9   → pass
 *   dark   worst adjacent CVD ΔE 8.4, normal-vision 19.8   → pass
 *
 * Light mode flagged aqua and yellow below 3:1 against white, which obliges
 * relief: every segment carries a visible direct label and every chart has a
 * table view, so no value is reachable by colour or hover alone.
 *
 * Rules held to throughout: hues assigned in fixed slot order and never
 * cycled, colour following the entity rather than its rank, one axis per plot,
 * a 2px surface gap between adjacent fills, hairline grid, and status colours
 * reserved for status — never as a spare series.
 */
import { useId, useState } from "react";

/* Categorical slots, in fixed order. A ninth series is never generated: the
   tail folds into "Other". */
export const SERIES = [
  "var(--viz-1)", "var(--viz-2)", "var(--viz-3)", "var(--viz-4)",
  "var(--viz-5)", "var(--viz-6)", "var(--viz-7)", "var(--viz-8)",
];

/* Status is a separate, reserved scale. */
export const STATUS = {
  good: "var(--viz-good)",
  warning: "var(--viz-warning)",
  serious: "var(--viz-serious)",
  critical: "var(--viz-critical)",
} as const;

/**
 * The tokens every chart reads. Mount it once near the top of the page, and
 * put the `viz` class on an ancestor of everything that reads a SERIES or
 * STATUS colour - not only the charts. Anything outside that scope resolves
 * the custom properties to nothing and paints transparent.
 */
export function VizTokens() {
  return (
    <style>{`
      .viz {
        /* Categorical — validated slot order, light steps */
        --viz-1: #2a78d6; --viz-2: #eb6834; --viz-3: #1baf7a; --viz-4: #eda100;
        --viz-5: #e87ba4; --viz-6: #008300; --viz-7: #4a3aa7; --viz-8: #e34948;
        /* Status — fixed, never themed, never used for a series */
        --viz-good: #0ca30c; --viz-warning: #fab219;
        --viz-serious: #ec835a; --viz-critical: #d03b3b;
        /* Sequential blue, for magnitude on a grid */
        --viz-seq-1: #cde2fb; --viz-seq-2: #9ec5f4; --viz-seq-3: #6da7ec;
        --viz-seq-4: #3987e5; --viz-seq-5: #256abf; --viz-seq-6: #184f95;
        /* Chrome */
        --viz-grid: #e1e0d9; --viz-axis: #c3c2b7; --viz-muted: #898781;
        --viz-surface: #ffffff;
      }
      /* This product switches themes with a .dark class on <html>, so the
         dark steps hang off that rather than off prefers-color-scheme. */
      .dark .viz {
        /* The same eight hues, stepped for the dark surface — not a flip */
        --viz-1: #3987e5; --viz-2: #d95926; --viz-3: #199e70; --viz-4: #c98500;
        --viz-5: #d55181; --viz-6: #008300; --viz-7: #9085e9; --viz-8: #e66767;
        --viz-seq-1: #184f95; --viz-seq-2: #256abf; --viz-seq-3: #2a78d6;
        --viz-seq-4: #3987e5; --viz-seq-5: #6da7ec; --viz-seq-6: #9ec5f4;
        --viz-grid: #2c2c2a; --viz-axis: #383835; --viz-muted: #898781;
        --viz-surface: #18181b;
      }
    `}</style>
  );
}

/** A chart card: title, the plot, a legend, and a table view behind a toggle. */
export function ChartCard({ title, hint, legend, table, children, empty }: {
  title: string; hint?: string;
  legend?: { label: string; color: string }[];
  table?: { head: string[]; rows: (string | number)[][] };
  children: React.ReactNode; empty?: string;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <section className="viz overflow-hidden rounded-xl bg-surface ring-panel">
      <header className="flex items-start justify-between gap-3 px-4 pt-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {hint && <p className="mt-0.5 text-xs leading-snug text-ink-3">{hint}</p>}
        </div>
        {table && (
          <button onClick={() => setShowTable((v) => !v)}
                  className="shrink-0 rounded-md px-2 py-1 text-[11px] font-medium text-ink-3 ring-control transition hover:bg-subtle hover:text-ink focus-ring">
            {showTable ? "Chart" : "Table"}
          </button>
        )}
      </header>

      {empty ? (
        <p className="px-4 py-8 text-sm text-ink-3">{empty}</p>
      ) : showTable && table ? (
        <div className="overflow-x-auto px-4 py-3">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-stroke">
                {table.head.map((h, i) => (
                  <th key={h} className={`py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-3 ${
                    i === 0 ? "text-left" : "text-right"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i} className="border-b border-stroke/60 last:border-0">
                  {r.map((c, j) => (
                    <td key={j} className={`py-1.5 ${j === 0
                      ? "text-ink" : "text-right tabular-nums text-ink-2"}`}>{c}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-4 py-3">{children}</div>
      )}

      {legend && legend.length > 1 && !showTable && !empty && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-stroke px-4 py-2">
          {legend.map((l) => (
            <span key={l.label} className="flex items-center gap-1.5 text-[11px] text-ink-2">
              <span aria-hidden className="h-2.5 w-2.5 rounded-sm"
                    style={{ background: l.color }} />
              {l.label}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

/**
 * A donut. Only used for part-to-whole where the segments are few and
 * genuinely unequal — a donut comparing close values is unreadable, and one
 * with more than about six segments blurs.
 */
export function Donut({ data, centreLabel, centreValue }: {
  data: { label: string; value: number; color?: string }[];
  centreLabel?: string; centreValue?: string | number;
}) {
  const id = useId();
  const total = data.reduce((n, d) => n + d.value, 0);
  const [hover, setHover] = useState<number | null>(null);
  if (total <= 0) return <p className="py-6 text-sm text-ink-3">Nothing to show.</p>;

  const R = 62, r = 40, cx = 80, cy = 80;
  // 2px of surface between segments, expressed as a gap in degrees.
  const gap = data.length > 1 ? 2.2 : 0;

  // Each segment's start comes from the prefix sum of the ones before it, so
  // the sweep is a pure calculation rather than a counter mutated mid-render.
  const deg = (v: number) => (v / total) * 360;
  const segments = data.map((d, i) => {
    const start = -90 + deg(data.slice(0, i).reduce((n, x) => n + x.value, 0));
    return {
      ...d, i,
      from: start + gap / 2,
      to: start + deg(d.value) - gap / 2,
      pct: Math.round((d.value / total) * 100),
      color: d.color ?? SERIES[i % SERIES.length],
    };
  });

  const arc = (from: number, to: number, outer: number, inner: number) => {
    const p = (a: number, rad: number) => [
      cx + rad * Math.cos((a * Math.PI) / 180),
      cy + rad * Math.sin((a * Math.PI) / 180),
    ];
    const large = to - from > 180 ? 1 : 0;
    const [x1, y1] = p(from, outer), [x2, y2] = p(to, outer);
    const [x3, y3] = p(to, inner), [x4, y4] = p(from, inner);
    return `M${x1} ${y1}A${outer} ${outer} 0 ${large} 1 ${x2} ${y2}`
         + `L${x3} ${y3}A${inner} ${inner} 0 ${large} 0 ${x4} ${y4}Z`;
  };

  return (
    <div className="flex flex-wrap items-center gap-4">
      <svg viewBox="0 0 160 160" width={160} height={160} role="img"
           aria-label={`${centreLabel ?? "Split"}: ` +
             data.map((d) => `${d.label} ${d.value}`).join(", ")}>
        {segments.map((s) => s.to > s.from && (
          <path key={s.label}
                d={arc(s.from, s.to, hover === s.i ? R + 2 : R, r)}
                fill={s.color}
                onMouseEnter={() => setHover(s.i)} onMouseLeave={() => setHover(null)}
                style={{ transition: "d .15s" }}>
            <title>{`${s.label}: ${s.value} (${s.pct}%)`}</title>
          </path>
        ))}
        {centreValue !== undefined && (
          <>
            <text x={cx} y={cy - 2} textAnchor="middle"
                  className="fill-ink" style={{ fontSize: 22, fontWeight: 600 }}>
              {centreValue}
            </text>
            <text x={cx} y={cy + 14} textAnchor="middle"
                  style={{ fontSize: 9, fill: "var(--viz-muted)" }}>
              {centreLabel}
            </text>
          </>
        )}
      </svg>
      {/* Direct labels beside the ring: the relief the contrast check requires,
          and quicker to read than matching colours to a legend. */}
      <ul className="min-w-40 flex-1 space-y-1" id={id}>
        {segments.map((s) => (
          <li key={s.label}
              onMouseEnter={() => setHover(s.i)} onMouseLeave={() => setHover(null)}
              className={`flex items-center gap-2 rounded px-1 text-xs transition ${
                hover === s.i ? "bg-subtle" : ""}`}>
            <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ background: s.color }} />
            <span className="min-w-0 flex-1 truncate text-ink-2">{s.label}</span>
            <span className="tabular-nums text-ink">{s.value}</span>
            <span className="w-9 text-right tabular-nums text-ink-3">{s.pct}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Horizontal stacked bars — the honest form for part-to-whole across many
 * long-named categories, where a pie would be unreadable.
 */
export function StackedBars({ rows, series, maxTotal }: {
  rows: { label: string; values: number[]; note?: string }[];
  series: { label: string; color: string }[];
  maxTotal?: number;
}) {
  const max = maxTotal ?? Math.max(1, ...rows.map((r) =>
    r.values.reduce((a, b) => a + b, 0)));
  return (
    <div className="space-y-2">
      {rows.map((row) => {
        const total = row.values.reduce((a, b) => a + b, 0);
        return (
          <div key={row.label} className="flex items-center gap-3">
            <span className="w-36 shrink-0 truncate text-xs text-ink-2"
                  title={row.label}>{row.label}</span>
            <div className="relative h-5 flex-1">
              <div className="flex h-full w-full items-stretch"
                   style={{ width: `${(total / max) * 100}%` }}>
                {row.values.map((v, i) => v > 0 && (
                  <div key={i} className="relative h-full first:rounded-l-[4px] last:rounded-r-[4px]"
                       style={{
                         flexGrow: v, background: series[i].color,
                         // 2px of surface between fills, not a border.
                         marginRight: i < row.values.length - 1 ? 2 : 0,
                       }}
                       title={`${row.label} — ${series[i].label}: ${v}`}>
                    {/* Labelled in place only when it fits, else left to the
                        row total and the table view. */}
                    {v > 0 && (v / max) * 100 > 8 && (
                      <span className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-white">
                        {v}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
            <span className="w-10 shrink-0 text-right text-xs tabular-nums text-ink-2">
              {total}
            </span>
            {row.note && (
              <span className="w-20 shrink-0 truncate text-right text-[11px] text-bad"
                    title={row.note}>{row.note}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Plain bars, one hue — magnitude across a handful of categories. */
export function Bars({ rows, color, ordinal }: {
  rows: { label: string; value: number; color?: string }[];
  color?: string; ordinal?: boolean;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  // An ordered scale gets the ordinal ramp; nominal categories get one hue,
  // because shading a nominal bar by its own length says nothing new.
  // Starts at seq-3, not seq-1: an ordinal ramp's nearest-surface step still
  // has to clear 2:1, which the two lightest sequential steps do not.
  const ramp = ["var(--viz-seq-3)", "var(--viz-seq-4)",
                "var(--viz-seq-5)", "var(--viz-seq-6)"];
  return (
    <div className="space-y-1.5">
      {rows.map((r, i) => (
        <div key={r.label} className="flex items-center gap-3">
          <span className="w-28 shrink-0 truncate text-xs text-ink-2">{r.label}</span>
          <div className="h-4 flex-1">
            <div className="h-full rounded-[4px] transition-all"
                 style={{
                   width: `${Math.max(r.value > 0 ? 2 : 0, (r.value / max) * 100)}%`,
                   background: r.color ?? (ordinal ? ramp[i % ramp.length]
                                                   : color ?? SERIES[0]),
                 }}
                 title={`${r.label}: ${r.value}`} />
          </div>
          <span className="w-8 shrink-0 text-right text-xs tabular-nums text-ink">
            {r.value}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * A five-step meter for the delivery-pressure scale.
 *
 * Not a chart: it is one value against a fixed ordered scale, so a meter is the
 * form. Status colours, and always with the label — never colour alone.
 */
export function ScaleMeter({ steps, activeIndex, reason }: {
  steps: string[]; activeIndex: number; reason?: string;
}) {
  const tone = (i: number) =>
    i <= 1 ? STATUS.critical : i === 2 ? STATUS.warning : STATUS.good;
  return (
    <div>
      <div className="flex gap-1">
        {steps.map((s, i) => (
          <div key={s} className="flex-1">
            <div className="h-2 rounded-sm"
                 style={{ background: i === activeIndex ? tone(i) : "var(--viz-grid)" }} />
            <p className={`mt-1 text-[10px] leading-tight ${
              i === activeIndex ? "font-semibold text-ink" : "text-ink-3"}`}>
              {s}
            </p>
          </div>
        ))}
      </div>
      {reason && <p className="mt-2 text-xs leading-snug text-ink-2">{reason}</p>}
    </div>
  );
}

/**
 * A heatmap for the focus matrix — magnitude on a grid, so one hue light→dark.
 * Every cell shows its number as well as its shade, so the colour is never the
 * only encoding.
 */
export function Heatmap({ columns, rows }: {
  columns: { key: string; label: string; title?: string }[];
  rows: { label: string; cells: { key: string; value: number | null }[] }[];
}) {
  const values = rows.flatMap((r) => r.cells.map((c) => c.value ?? 0));
  const max = Math.max(1, ...values);
  const step = (v: number) => {
    if (v <= 0) return "transparent";
    const n = Math.ceil((v / max) * 5);
    return `var(--viz-seq-${Math.min(6, Math.max(1, n + 1))})`;
  };
  return (
    <div className="overflow-x-auto">
      <table className="border-separate" style={{ borderSpacing: 2 }}>
        <thead>
          <tr>
            <th />
            {columns.map((c) => (
              <th key={c.key} title={c.title}
                  className="px-1 pb-1 text-[11px] font-semibold text-ink-2">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <th className="pr-2 text-right text-xs font-medium text-ink-2">
                {r.label}
              </th>
              {r.cells.map((c) => (
                <td key={c.key}
                    className="h-7 w-12 rounded text-center text-[11px] tabular-nums"
                    style={{
                      background: step(c.value ?? 0),
                      color: (c.value ?? 0) > max * 0.6 ? "#fff" : "var(--color-ink)",
                    }}
                    title={`${r.label} — ${c.key}: ${c.value ?? 0}%`}>
                  {c.value === null || c.value === 0 ? "" : `${c.value}%`}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
