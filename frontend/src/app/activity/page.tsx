"use client";

/**
 * What everyone has been doing.
 *
 * The page leads with one line per person — "Ethan created 3 tasks, completed
 * 1" — because that is the question people actually ask. The individual events
 * are underneath for when the summary is not enough.
 *
 * The same data is served to agents at /api/v1/activity, deliberately: a person
 * and an agent asking "what did Ethan do today" must not get different answers.
 */
import { useCallback, useEffect, useState } from "react";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import { AppShell, PageHead, Button, Pill, relativeTime } from "@/components/ui";

type Entry = {
  id: number; sentence: string; actor: string; username: string;
  verb: string; object_type: string; object_id: number | null;
  object_label: string; detail: string; project: string;
  source: "web" | "api" | "system"; via: string; at: string;
};
type Person = { actor: string; count: number; sentence: string; items: string[] };
type Feed = { entries: Entry[]; summary: Person[]; people: string[]; types: string[] };

const RANGES = [
  { label: "Today", days: 1 },
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "All", days: 0 },
];

/** Colour by what happened, not by who did it — deletions must stand out. */
const VERB_TONE: Record<string, string> = {
  created: "text-good",
  completed: "text-good",
  deleted: "text-bad",
  reopened: "text-warnx",
};

const TYPE_ICON: Record<string, string> = {
  task: "board", repository: "git", document: "docs", list: "folder",
};

export default function ActivityPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [d, setD] = useState<Feed | null>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);
  const [actor, setActor] = useState("");
  const [q, setQ] = useState("");

  const load = useCallback(async () => {
    const p = new URLSearchParams({ limit: "200" });
    if (days) p.set("days", String(days));
    if (actor) p.set("actor", actor);
    if (q.trim()) p.set("q", q.trim());
    try {
      const r = await fetch(`/api/activity?${p}`);
      setD(r.ok ? await r.json() : null);
    } finally {
      setLoading(false);
    }
  }, [days, actor, q]);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setMe)
      .catch(() => (window.location.href = "/login"));
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Entries grouped under the day they happened, which is how people scan a log.
  const byDay = new Map<string, Entry[]>();
  for (const e of d?.entries ?? []) {
    const key = new Date(e.at).toDateString();
    (byDay.get(key) ?? byDay.set(key, []).get(key)!).push(e);
  }

  return (
    <AppShell active="Activity" me={me} wide>
      <PageHead
        title="Activity"
        subtitle={d
          ? `${d.entries.length} thing${d.entries.length === 1 ? "" : "s"} happened${
              days ? ` in the last ${days} day${days === 1 ? "" : "s"}` : ""}`
          : "Who did what, across the platform."}
        actions={
          <Button icon="sync" spinning={loading}
                  onClick={() => { setLoading(true); void load(); }}>
            Refresh
          </Button>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {RANGES.map((r) => (
          <Pill key={r.label} active={days === r.days} onClick={() => setDays(r.days)}>
            {r.label}
          </Pill>
        ))}
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter…"
          className="h-9 w-56 rounded-lg bg-surface px-3 text-sm text-ink ring-control focus-ring"
        />
        {actor && (
          <button onClick={() => setActor("")}
                  className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand-tint px-3 text-sm font-medium text-brand transition hover:bg-brand-tint-2 focus-ring">
            {actor}
            <Icon name="chevron" className="h-3 w-3 rotate-90" />
          </button>
        )}
      </div>

      {loading && !d ? (
        <div className="rounded-xl bg-surface p-6 ring-panel">
          <p className="text-sm text-ink-2">Reading the log…</p>
        </div>
      ) : !d || d.entries.length === 0 ? (
        <div className="rounded-xl bg-surface px-6 py-10 text-center ring-panel">
          <Icon name="clock" className="mx-auto h-5 w-5 text-ink-3" />
          <p className="mt-2 text-sm font-semibold text-ink">Nothing recorded yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm leading-relaxed text-ink-2">
            Activity is written as people work — creating tasks, moving them,
            writing documentation. It starts filling from now, not
            retrospectively.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* One line per person. */}
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {d.summary.map((p) => (
              <button key={p.actor} onClick={() => setActor(p.actor)}
                      className="rounded-xl bg-surface p-4 text-left ring-panel transition hover:ring-brand/40 focus-ring">
                <p className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand text-[10px] font-bold text-white">
                    {p.actor.split(" ").map((w) => w[0]).slice(0, 2).join("")}
                  </span>
                  {p.actor}
                </p>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-2">
                  {p.sentence.replace(`${p.actor} `, "")}
                </p>
                {p.items.length > 0 && (
                  <p className="mt-1.5 truncate text-xs text-ink-3">
                    {p.items.join(" · ")}
                  </p>
                )}
              </button>
            ))}
          </section>

          {/* The events themselves. */}
          {[...byDay.entries()].map(([day, entries]) => (
            <section key={day} className="overflow-hidden rounded-xl bg-surface ring-panel">
              <header className="border-b border-stroke px-5 py-2.5">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-3">
                  {day}
                </h2>
              </header>
              <ul className="divide-y divide-stroke">
                {entries.map((e) => (
                  <li key={e.id} className="flex items-start gap-3 px-5 py-2.5">
                    <Icon name={TYPE_ICON[e.object_type] ?? "file"}
                          className="mt-0.5 h-4 w-4 shrink-0 text-ink-3" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm leading-snug text-ink-2">
                        <button onClick={() => setActor(e.actor)}
                                className="font-medium text-ink hover:underline">
                          {e.actor || "Someone"}
                        </button>{" "}
                        <span className={VERB_TONE[e.verb] ?? "text-ink-2"}>{e.verb}</span>{" "}
                        {e.object_type}
                        {e.object_label && <> <span className="text-ink">{e.object_label}</span></>}
                        {e.detail && <span className="text-ink-3"> — {e.detail}</span>}
                      </p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-3">
                        <span>{relativeTime(e.at)}</span>
                        {e.project && <><span>·</span><span>{e.project}</span></>}
                        {e.source === "api" && (
                          <>
                            <span>·</span>
                            <span className="rounded bg-subtle px-1.5 py-0.5">
                              via API{e.via ? ` (${e.via})` : ""}
                            </span>
                          </>
                        )}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </AppShell>
  );
}
