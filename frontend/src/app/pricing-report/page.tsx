"use client";

/**
 * The Pricing Report.
 *
 * The report is two things stacked, exactly as the workbook has always had it:
 *
 *   TOP     the pricing export — every quote, whether it converted into a
 *           booking, how long that took, and who quoted it.
 *   BOTTOM  the turnover analysis rows appended underneath — income and
 *           branch, with no quote behind them.
 *
 * The page keeps that separation visible rather than blending the two into
 * one set of averages, because a figure that mixes a quote count with an
 * income line is nearly always a mistake. Each card says which half it reads.
 *
 * One filter row scopes everything. Change the year and both halves move
 * together, so the conversion rate and the income are always describing the
 * same period.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import { AppShell, PageHead, Button } from "@/components/ui";
import {
  VizTokens, ChartCard, Donut, StackedBars, Bars, SERIES,
} from "@/components/charts";

type Month = {
  month: string; label: string; quotes: number; converted: number;
  conversion_pct: number | null; income: number;
};
type Report = {
  loaded: boolean;
  source: { filename: string; loaded_at: string; quote_rows: number;
            turnover_rows: number; size_mb: number } | null;
  filters?: {
    applied: Record<string, string>;
    years: number[]; branches: string[]; modes: string[]; directions: string[];
  };
  totals?: {
    quotes: number; converted: number; conversion_pct: number; missed: number;
    duplicates: number; income: number; clients: number;
    avg_conversion_days: number;
  };
  months?: Month[];
  branches?: { branch: string; income: number; quotes: number }[];
  top_clients?: { client: string; name: string; income: number }[];
  by_person?: { person: string; quotes: number; converted: number;
                conversion_pct: number; avg_days: number | null }[];
  transport_modes?: { key: string; value: number }[];
  directions?: { key: string; value: number }[];
  au_nz?: { key: string; value: number }[];
  lanes?: { key: string; value: number }[];
  imports?: { id: number; filename: string; loaded_at: string; rows: number;
              is_active: boolean }[];
};

const money = (n: number) =>
  n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M`
  : n >= 1_000 ? `$${(n / 1_000).toFixed(0)}k`
  : `$${n.toFixed(0)}`;

const full = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD",
                              maximumFractionDigits: 0 });

export default function PricingReportPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [d, setD] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [f, setF] = useState({ year: "", branch: "", mode: "", direction: "" });
  const [uniqueOnly, setUniqueOnly] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async (next: typeof f, unique: boolean) => {
    try {
      const q = new URLSearchParams();
      Object.entries(next).forEach(([k, v]) => v && q.set(k, v));
      if (unique) q.set("unique_only", "1");
      const r = await fetch(`/api/pricing/report?${q}`);
      setD(r.ok ? await r.json() : null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "data")) window.location.href = "/";
      })
      .catch(() => (window.location.href = "/login"));
    void load({ year: "", branch: "", mode: "", direction: "" }, false);
  }, [load]);

  const set = (k: keyof typeof f, v: string) => {
    const next = { ...f, [k]: v };
    setF(next);
    setLoading(true);
    void load(next, uniqueOnly);
  };

  const upload = async (file: File) => {
    setBusy(`Reading ${file.name} — a full workbook takes about a minute.`);
    const body = new FormData();
    body.append("file", file);
    try {
      const r = await fetch("/api/pricing/upload", { method: "POST", body });
      const j = await r.json();
      if (!r.ok) {
        setBusy(j.detail || "The workbook could not be read.");
        return;
      }
      setBusy(`Loaded ${j.quote_rows.toLocaleString()} quote rows and `
              + `${j.turnover_rows.toLocaleString()} turnover rows.`);
      setLoading(true);
      await load(f, uniqueOnly);
    } catch {
      setBusy("The upload did not finish.");
    }
  };

  const t = d?.totals;
  const months = d?.months ?? [];
  const maxMonthQuotes = Math.max(1, ...months.map((m) => m.quotes));

  return (
    <AppShell active="Pricing Report" me={me} wide>
      <VizTokens />
      <PageHead
        title="Pricing Report"
        subtitle={d?.source
          ? `${d.source.quote_rows.toLocaleString()} quotes and ${d.source.turnover_rows.toLocaleString()} turnover rows from ${d.source.filename}`
          : "Quotes from the CargoWise pricing export, with the turnover analysis appended."}
        actions={
          <>
            <input ref={fileInput} type="file" accept=".xlsx,.xlsm" hidden
                   onChange={(e) => {
                     const file = e.target.files?.[0];
                     if (file) void upload(file);
                     e.target.value = "";
                   }} />
            <Button icon="upload" onClick={() => fileInput.current?.click()}>
              Load workbook
            </Button>
            <Button icon="sync" spinning={loading}
                    onClick={() => { setLoading(true); void load(f, uniqueOnly); }}>
              Refresh
            </Button>
          </>
        }
      />

      {busy && (
        <div className="mb-3 flex items-start gap-2 rounded-xl bg-infox-bg px-4 py-3 text-sm text-infox ring-1 ring-inset ring-infox/20">
          <Icon name="upload" className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="flex-1">{busy}</span>
          <button onClick={() => setBusy("")}
                  className="text-xs font-medium underline focus-ring">
            dismiss
          </button>
        </div>
      )}

      {loading && !d ? (
        <div className="rounded-xl bg-surface p-6 ring-panel">
          <p className="text-sm text-ink-2">Reading the report…</p>
        </div>
      ) : !d?.loaded ? (
        <div className="rounded-xl bg-surface px-6 py-10 text-center ring-panel">
          <Icon name="monitoring" className="mx-auto h-5 w-5 text-ink-3" />
          <p className="mt-2 text-sm font-semibold text-ink">
            No pricing workbook has been loaded yet
          </p>
          <p className="mx-auto mt-1 max-w-md text-sm text-ink-2">
            Load the CargoWise pricing export — the one with the turnover
            analysis rows appended underneath — and the report builds itself
            from it.
          </p>
          <div className="mt-4 flex justify-center">
            <Button icon="upload" variant="primary"
                    onClick={() => fileInput.current?.click()}>
              Load workbook
            </Button>
          </div>
        </div>
      ) : (
        <div className={`viz space-y-4 transition-opacity ${loading ? "opacity-60" : ""}`}>

          {/* ── One filter row, scoping both halves ───────────────────── */}
          <section className="flex flex-wrap items-center gap-2 rounded-xl bg-surface px-4 py-3 ring-panel">
            <span className="text-xs font-semibold uppercase tracking-wide text-ink-3">
              Showing
            </span>
            <Pick label="All years" value={f.year}
                  options={(d.filters?.years ?? []).map(String)}
                  onChange={(v) => set("year", v)} />
            <Pick label="All branches" value={f.branch}
                  options={d.filters?.branches ?? []}
                  onChange={(v) => set("branch", v)} />
            <Pick label="All modes" value={f.mode}
                  options={d.filters?.modes ?? []}
                  onChange={(v) => set("mode", v)} />
            <Pick label="Import and export" value={f.direction}
                  options={d.filters?.directions ?? []}
                  onChange={(v) => set("direction", v)} />
            <label className="ml-auto flex items-center gap-2 text-xs text-ink-2">
              <input type="checkbox" checked={uniqueOnly}
                     onChange={(e) => {
                       setUniqueOnly(e.target.checked);
                       setLoading(true);
                       void load(f, e.target.checked);
                     }}
                     className="h-3.5 w-3.5 accent-[var(--color-brand)]" />
              Drop the {t?.duplicates.toLocaleString()} rows flagged duplicate
            </label>
          </section>

          {/* ── The top half: quotes ─────────────────────────────────── */}
          <Split n={1} title="Pricing — the quotes"
                 hint="From the CargoWise pricing export. Every quote raised, and whether it turned into a booking." />

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Big label="Quotes raised" value={t!.quotes.toLocaleString()} />
            <Big label="Converted" value={t!.converted.toLocaleString()}
                 sub={`${t!.conversion_pct}% of everything quoted`}
                 tone={t!.conversion_pct < 20 ? "bad" : undefined} />
            <Big label="Average time to convert"
                 value={`${t!.avg_conversion_days}`}
                 sub="days from quote to booking" />
            <Big label="Clients quoted" value={t!.clients.toLocaleString()} />
          </section>

          <ChartCard
            title="Quotes and conversions by month"
            hint="Blue converted into a booking; orange did not."
            legend={[{ label: "Converted", color: SERIES[0] },
                     { label: "Not converted", color: SERIES[1] }]}
            empty={months.length === 0 ? "Nothing in this slice." : undefined}
            table={{
              head: ["Month", "Quotes", "Converted", "Rate"],
              rows: months.map((m) => [m.label, m.quotes, m.converted,
                                       m.conversion_pct === null ? "—" : `${m.conversion_pct}%`]),
            }}>
            <StackedBars
              maxTotal={maxMonthQuotes}
              series={[{ label: "Converted", color: SERIES[0] },
                       { label: "Not converted", color: SERIES[1] }]}
              rows={months.map((m) => ({
                label: m.label,
                values: [m.converted, m.quotes - m.converted],
                note: m.conversion_pct === null ? undefined : `${m.conversion_pct}%`,
              }))} />
          </ChartCard>

          <section className="grid gap-4 xl:grid-cols-3">
            <ChartCard title="Air, sea and the rest"
                       hint="How the quotes split by transport mode."
                       table={{ head: ["Mode", "Quotes"],
                                rows: (d.transport_modes ?? []).map((m) => [m.key, m.value]) }}>
              <Donut centreLabel="quotes" centreValue={t!.quotes.toLocaleString()}
                     data={(d.transport_modes ?? []).map((m) => ({
                       label: m.key, value: m.value }))} />
            </ChartCard>

            <ChartCard title="Import, export or domestic"
                       table={{ head: ["Direction", "Quotes"],
                                rows: (d.directions ?? []).map((m) => [m.key, m.value]) }}>
              <Donut data={(d.directions ?? []).map((m) => ({
                       label: m.key, value: m.value }))} />
            </ChartCard>

            <ChartCard title="Where the freight is going"
                       hint="Destination country, busiest first."
                       table={{ head: ["Country", "Quotes"],
                                rows: (d.lanes ?? []).map((m) => [m.key, m.value]) }}>
              <Bars rows={(d.lanes ?? []).slice(0, 8).map((m) => ({
                label: m.key, value: m.value }))} />
            </ChartCard>
          </section>

          <Card title="Conversion by the person who quoted"
                hint="The question the report exists to answer. Busiest quoters first.">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead>
                  <tr className="border-b border-stroke text-left">
                    {["Person", "Quotes", "Converted", "Rate", "Avg days"].map((h, i) => (
                      <th key={h} className={`px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3 ${
                        i === 0 ? "" : "text-right"}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(d.by_person ?? []).map((p) => (
                    <tr key={p.person} className="border-b border-stroke/60 last:border-0">
                      <td className="px-4 py-2 text-ink">{p.person}</td>
                      <td className="px-4 py-2 text-right tabular-nums text-ink-2">
                        {p.quotes.toLocaleString()}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-ink-2">
                        {p.converted.toLocaleString()}
                      </td>
                      <td className="px-4 py-2 text-right">
                        {/* The bar is the comparison; the number is the value. */}
                        <span className="inline-flex items-center justify-end gap-2">
                          <span className="h-1.5 w-16 overflow-hidden rounded-full bg-subtle">
                            <span className="block h-full rounded-full"
                                  style={{ width: `${Math.min(100, p.conversion_pct * 2)}%`,
                                           background: SERIES[0] }} />
                          </span>
                          <b className="w-12 tabular-nums text-ink">{p.conversion_pct}%</b>
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-ink-2">
                        {p.avg_days ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* ── The bottom half: turnover ────────────────────────────── */}
          <Split n={2} title="Turnover — the income"
                 hint="The turnover analysis rows appended under the pricing data. Income and branch only; there is no quote behind these." />

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Big label="Total income" value={money(t!.income)}
                 sub={full(t!.income)} />
            <Big label="Branches earning"
                 value={String((d.branches ?? []).length)} />
            <Big label="Best month"
                 value={months.length
                   ? money(Math.max(...months.map((m) => m.income))) : "—"}
                 sub={months.length
                   ? months.reduce((a, b) => (b.income > a.income ? b : a)).label
                   : undefined} />
            <Big label="Top client"
                 value={d.top_clients?.[0] ? money(d.top_clients[0].income) : "—"}
                 sub={d.top_clients?.[0]?.name} />
          </section>

          <ChartCard
            title="Income by month"
            hint="One hue: this is a single measure over time, not competing series."
            empty={months.every((m) => m.income === 0)
              ? "No turnover rows in this slice." : undefined}
            table={{
              head: ["Month", "Income"],
              rows: months.map((m) => [m.label, full(m.income)]),
            }}>
            <Bars rows={months.filter((m) => m.income > 0).map((m) => ({
              label: m.label, value: Math.round(m.income),
            }))} />
          </ChartCard>

          <section className="grid gap-4 xl:grid-cols-2">
            <ChartCard
              title="Income by branch"
              hint="Quote counts sit beside it for context — they are counted from the pricing half, not the income half."
              empty={(d.branches ?? []).length === 0
                ? "No turnover rows in this slice." : undefined}
              table={{
                head: ["Branch", "Income", "Quotes"],
                rows: (d.branches ?? []).map((b) => [b.branch, full(b.income),
                                                     b.quotes]),
              }}>
              <Bars rows={(d.branches ?? []).slice(0, 10).map((b) => ({
                label: b.branch, value: Math.round(b.income),
              }))} />
            </ChartCard>

            <Card title="Top clients by income"
                  hint="From the turnover rows.">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-stroke text-left">
                      <th className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                        Client
                      </th>
                      <th className="px-4 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                        Income
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(d.top_clients ?? []).map((c) => (
                      <tr key={c.client} className="border-b border-stroke/60 last:border-0">
                        <td className="px-4 py-2">
                          <span className="text-ink">{c.name || c.client}</span>
                          <span className="ml-2 text-xs text-ink-3">{c.client}</span>
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums text-ink-2">
                          {full(c.income)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </section>

          {/* ── Where it came from ───────────────────────────────────── */}
          <div className="rounded-xl bg-surface px-4 py-3 text-xs text-ink-3 ring-panel">
            <p>
              Read from <b className="text-ink-2">{d.source!.filename}</b>{" "}
              ({d.source!.size_mb} MB), loaded{" "}
              {new Date(d.source!.loaded_at).toLocaleString()}.{" "}
              {d.source!.quote_rows.toLocaleString()} quote rows and{" "}
              {d.source!.turnover_rows.toLocaleString()} turnover rows are in
              the database — the report is a query over them, not over the file,
              so it can be sliced without opening Excel.
            </p>
            {(d.imports ?? []).length > 1 && (
              <p className="mt-1.5">
                Earlier loads:{" "}
                {(d.imports ?? []).filter((i) => !i.is_active).map((i) => (
                  <button key={i.id}
                          onClick={async () => {
                            await fetch(`/api/pricing/imports/${i.id}/activate`,
                                        { method: "POST" });
                            setLoading(true);
                            void load(f, uniqueOnly);
                          }}
                          className="mr-2 underline hover:text-ink focus-ring">
                    {i.filename} ({new Date(i.loaded_at).toLocaleDateString()})
                  </button>
                ))}
              </p>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}

/** A divider that names which half of the report follows. */
function Split({ n, title, hint }: { n: number; title: string; hint: string }) {
  return (
    <div className="flex items-start gap-3 pt-2">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-bold text-white">
        {n}
      </span>
      <div>
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        <p className="text-xs leading-snug text-ink-3">{hint}</p>
      </div>
    </div>
  );
}

function Pick({ label, value, options, onChange }: {
  label: string; value: string; options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
            className="h-8 rounded-lg bg-surface px-2 text-xs text-ink ring-control focus-ring">
      <option value="">{label}</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

/** One number, said big, with a plain line underneath. */
function Big({ label, value, sub, tone }:
             { label: string; value: string; sub?: string; tone?: "bad" }) {
  return (
    <div className="rounded-xl bg-surface px-5 py-4 ring-panel">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-3">
        {label}
      </p>
      {/* Proportional figures: tabular digits look loose at this size. */}
      <p className="mt-1 text-3xl font-semibold leading-none text-ink">{value}</p>
      {sub && (
        <p className={`mt-1.5 truncate text-xs ${tone === "bad" ? "text-bad" : "text-ink-3"}`}
           title={sub}>{sub}</p>
      )}
    </div>
  );
}

function Card({ title, hint, children }:
              { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl bg-surface ring-panel">
      <header className="border-b border-stroke px-5 py-3">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {hint && <p className="mt-0.5 text-xs leading-snug text-ink-3">{hint}</p>}
      </header>
      {children}
    </section>
  );
}
