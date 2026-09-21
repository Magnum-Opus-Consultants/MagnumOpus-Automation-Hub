"use client";

/**
 * A project's documentation.
 *
 * The documents come first, because that is what documentation is: the prose
 * somebody wrote in the repository (its README and docs/). The first version of
 * this page led with the commit log, and no arrangement of commits ever read
 * like documentation — a changelog answers "what changed", and a reader here is
 * asking "how does this work".
 *
 * The commits stay, as "Recent changes" underneath. They are the answer to a
 * real but different question, and they are honest in a way the documents are
 * not: they show whether anyone is explaining their work.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { canAccess, Icon, type Me } from "@/components/Sidebar";
import {
  AppShell, PageHead, Button, Modal, TextInput, ConfirmDialog, relativeTime,
} from "@/components/ui";
import { Markdown } from "@/components/markdown";

type Page = {
  path: string; title: string; body: string;
  /** "sentinel" — written here and editable; "repo" — read from the repository. */
  source: "sentinel" | "repo";
  id?: number; order?: number; updated_at?: string; updated_by?: string;
};
type Commit = {
  sha: string; short_sha: string; subject: string; body: string;
  author: string; date: string; url: string;
};
type Group = { kind: string; commits: Commit[] };
type Month = { key: string; label: string; groups: Group[]; count: number };
type Docs = {
  pages: Page[];
  repo: { id: number; name: string; full_name: string; url: string;
          description: string; branch: string; company: string };
  project: string;
  months: Month[];
  history_problem: string | null;
  totals: {
    commits: number; described: number; described_pct: number;
    merges_skipped: number; reached_limit: boolean;
    contributors: { name: string; commits: number }[];
  };
};

/**
 * The document without its own title line.
 *
 * The H1 is where the title came from, so rendering it again puts the same
 * words twice at the top of every page.
 */
function bodyOf(body: string) {
  const lines = body.replace(/\r\n/g, "\n").split("\n");
  const first = lines.findIndex((l) => l.trim());
  if (first >= 0 && lines[first].startsWith("# ")) {
    return lines.slice(first + 1).join("\n").replace(/^\n+/, "");
  }
  return body;
}

/** The ## headings inside one document, for the contents list. */
function sections(body: string) {
  return body.split("\n")
    .filter((l) => /^##\s+/.test(l))
    .map((l) => l.replace(/^##\s+/, "").trim());
}

/** One line in the contents, with its own headings when it is the open one. */
function TocEntry({ p, open, onSelect }: { p: Page; open: boolean; onSelect: () => void }) {
  return (
    <li>
      <button type="button" onClick={onSelect}
              className={`w-full rounded-lg px-2 py-1.5 text-left text-sm transition focus-ring ${
                open ? "bg-subtle font-medium text-ink"
                     : "text-ink-2 hover:bg-subtle hover:text-ink"}`}>
        {p.title}
      </button>
      {open && sections(p.body).length > 0 && (
        <ul className="mb-1 ml-2 space-y-0.5 border-l border-stroke pl-2.5 pt-0.5">
          {sections(p.body).map((s) => (
            <li key={s} className="py-0.5 text-xs leading-snug text-ink-3">{s}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

export default function RepoDocsPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [me, setMe] = useState<Me | null>(null);
  const [d, setD] = useState<Docs | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState("");          // current document path
  const [history, setHistory] = useState(false);
  const [editing, setEditing] = useState<Page | "new" | null>(null);
  const [draft, setDraft] = useState({ title: "", path: "", body: "" });
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState<Page | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const r = await fetch(`/api/repos/${id}/documentation`);
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(body.detail || "Could not build the documentation.");
        setD(null);
        return;
      }
      setError("");
      setD(body);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((m: Me) => {
        setMe(m);
        if (!canAccess(m, "repos")) window.location.href = "/data-analysis";
      })
      .catch(() => (window.location.href = "/login"));
    void load();
  }, [load]);

  // Open the front page once the documents arrive, and keep whatever the reader
  // chose after a refresh if that document is still there.
  const pages = useMemo(() => d?.pages ?? [], [d]);
  useEffect(() => {
    if (!pages.length) return;
    setOpen((cur) => (cur && pages.some((p) => p.path === cur) ? cur : pages[0].path));
  }, [pages]);

  const current = pages.find((p) => p.path === open) ?? pages[0];
  const t = d?.totals;

  function beginEdit(p: Page | "new") {
    setPreview(false);
    setEditing(p);
    setDraft(p === "new"
      ? { title: "", path: "", body: "" }
      : { title: p.title, path: p.path, body: p.body });
  }

  async function save() {
    if (!draft.title.trim()) return;
    setSaving(true);
    try {
      const r = await fetch(`/api/repos/${id}/docs/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: draft.title.trim(),
          // An empty path lets the server name the page from its title. A page
          // being edited keeps the path it has, so its identity survives a
          // retitle and any links to it still land.
          path: draft.path.trim(),
          body: draft.body,
          order: editing !== "new" && editing ? editing.order ?? 0 : pages.length,
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(body.detail || "Could not save the page.");
        return;
      }
      setEditing(null);
      setOpen(body.path);
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function removePage(p: Page) {
    if (!p.id) return;
    await fetch(`/api/repos/${id}/docs/${p.id}/delete`, { method: "DELETE" });
    setRemoving(null);
    setOpen("");
    await load();
  }

  async function importFromRepo() {
    setLoading(true);
    try {
      await fetch(`/api/repos/${id}/docs/import`, { method: "POST" });
      await load();
    } finally {
      setLoading(false);
    }
  }

  return (
    <AppShell active="Repositories" me={me} wide>
      <PageHead
        title={d ? d.repo.name : "Documentation"}
        subtitle={d
          ? (d.repo.description
             || `Documentation for ${d.repo.full_name}, read from the repository.`)
          : "Read from the repository."}
        actions={
          <>
            <Link href="/repos"
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-ink-2 ring-control transition hover:bg-subtle hover:text-ink focus-ring">
              <Icon name="back" className="h-3.5 w-3.5" />
              Repositories
            </Link>
            {d && (
              <Link href={`/tasks?project=${encodeURIComponent(d.project)}`}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-ink-2 ring-control transition hover:bg-subtle hover:text-ink focus-ring">
                <Icon name="board" className="h-3.5 w-3.5" />
                Project
              </Link>
            )}
            <Button icon="sync" spinning={loading}
                    onClick={() => { setLoading(true); void load(); }}>
              Refresh
            </Button>
            <Button icon="plus" variant="primary" onClick={() => beginEdit("new")}>
              New page
            </Button>
          </>
        }
      />

      {loading && !d ? (
        <div className="rounded-xl bg-surface p-6 ring-panel">
          <p className="text-sm text-ink-2">Reading the repository…</p>
        </div>
      ) : error ? (
        <div className="rounded-xl bg-surface px-6 py-10 text-center ring-panel">
          <Icon name="alert" className="mx-auto h-5 w-5 text-warnx" />
          <p className="mt-2 text-sm font-semibold text-ink">
            No documentation to show yet
          </p>
          <p className="mx-auto mt-1 max-w-md text-sm text-ink-2">{error}</p>
        </div>
      ) : d && t ? (
        <div className="space-y-4">
          {pages.length === 0 ? (
            <div className="rounded-xl bg-surface px-6 py-10 text-center ring-panel">
              <Icon name="docs" className="mx-auto h-5 w-5 text-ink-3" />
              <p className="mt-2 text-sm font-semibold text-ink">
                This repository has nothing written in it yet
              </p>
              <p className="mx-auto mt-1 max-w-lg text-sm leading-relaxed text-ink-2">
                Write the pages here and they are kept on this platform — no
                commit needed, and nothing is sent anywhere. If the repository
                already has a <code className="rounded bg-subtle px-1 py-0.5 font-mono text-xs">README.md</code>{" "}
                or a <code className="rounded bg-subtle px-1 py-0.5 font-mono text-xs">docs/</code>{" "}
                folder, those are shown too.
              </p>
              <div className="mt-4 flex items-center justify-center gap-2">
                <Button icon="plus" variant="primary" onClick={() => beginEdit("new")}>
                  Write the first page
                </Button>
                {d.repo.url && (
                  <Button icon="download" onClick={() => void importFromRepo()}>
                    Import from the repository
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
              {/* Contents */}
              <nav className="shrink-0 rounded-xl bg-surface p-2 ring-panel lg:sticky lg:top-4 lg:w-60">
                <p className="px-2 pb-1.5 pt-1 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                  Contents
                </p>
                <ul className="space-y-0.5">
                  {pages.filter((p) => p.source === "sentinel").map((p) => (
                    <TocEntry key={p.path} p={p} open={current?.path === p.path}
                              onSelect={() => setOpen(p.path)} />
                  ))}
                </ul>

                {/* Files that live in the repository, kept visibly apart: they
                    are not part of what anyone curated here, and mixing them in
                    lets a stray file pass as documentation. */}
                {pages.some((p) => p.source === "repo") && (
                  <>
                    <p className="mt-2 border-t border-stroke px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                      From the repository
                    </p>
                    <ul className="space-y-0.5">
                      {pages.filter((p) => p.source === "repo").map((p) => (
                        <TocEntry key={p.path} p={p} open={current?.path === p.path}
                                  onSelect={() => setOpen(p.path)} />
                      ))}
                    </ul>
                  </>
                )}
                <div className="mt-1 border-t border-stroke px-2 pb-1 pt-2">
                  <a href={d.repo.url} target="_blank" rel="noreferrer"
                     className="inline-flex items-center gap-1.5 text-xs text-ink-3 transition hover:text-ink">
                    <Icon name="git" className="h-3.5 w-3.5" />
                    View on GitHub
                  </a>
                </div>
              </nav>

              {/* The document */}
              <article className="min-w-0 flex-1 rounded-xl bg-surface px-6 py-5 ring-panel">
                {current && (
                  <>
                    <header className="mb-3 border-b border-stroke pb-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <h1 className="text-lg font-semibold text-ink">{current.title}</h1>
                        <div className="flex shrink-0 items-center gap-1">
                          <button type="button" onClick={() => beginEdit(current)}
                                  className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-ink-3 transition hover:bg-subtle hover:text-ink focus-ring">
                            <Icon name="edit" className="h-3.5 w-3.5" />
                            Edit
                          </button>
                          {current.source === "sentinel" && (
                            <button type="button" onClick={() => setRemoving(current)}
                                    className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-ink-3 transition hover:bg-bad/10 hover:text-bad focus-ring">
                              <Icon name="trash" className="h-3.5 w-3.5" />
                              Delete
                            </button>
                          )}
                        </div>
                      </div>
                      <p className="mt-1 text-xs text-ink-3">
                        {current.source === "sentinel" ? (
                          <>
                            Kept on this platform
                            {current.updated_at && <> · updated {relativeTime(current.updated_at)}</>}
                            {current.updated_by && <> by {current.updated_by}</>}
                          </>
                        ) : (
                          <>
                            Read from the repository ({current.path}) — editing
                            it here keeps your version on this platform
                          </>
                        )}
                      </p>
                    </header>
                    <Markdown source={bodyOf(current.body)} />
                  </>
                )}
              </article>
            </div>
          )}

          {/* Recent changes — supporting, collapsed by default. */}
          <section className="overflow-hidden rounded-xl bg-surface ring-panel">
            <button type="button" onClick={() => setHistory((v) => !v)}
                    className="flex w-full items-center justify-between gap-3 px-5 py-3 text-left transition hover:bg-subtle focus-ring">
              <span className="flex items-baseline gap-2">
                <span className="text-sm font-semibold text-ink">Recent changes</span>
                <span className="text-xs text-ink-3">
                  {t.commits} commit{t.commits === 1 ? "" : "s"}
                  {t.commits > 0 && ` · ${t.described_pct}% explain why`}
                </span>
              </span>
              <Icon name="chevron"
                    className={`h-4 w-4 shrink-0 text-ink-3 transition-transform ${
                      history ? "" : "rotate-180"}`} />
            </button>

            {history && (
              <div className="border-t border-stroke">
                {t.described_pct < 50 && t.commits > 0 && (
                  <p className="border-b border-stroke px-5 py-3 text-xs leading-relaxed text-ink-2">
                    <b className="text-ink">
                      {t.commits - t.described} of {t.commits} commits are a
                      subject line only.
                    </b>{" "}
                    They appear here as one-liners because that is all there is.
                    A commit body explaining the decision — not restating the
                    diff — is what makes history worth reading later.
                  </p>
                )}
                {d.months.length === 0 ? (
                  <p className="px-5 py-6 text-center text-sm text-ink-2">
                    No commits yet.
                  </p>
                ) : (
                  <div className="divide-y divide-stroke">
                    {d.months.map((m) => (
                      <div key={m.key} className="px-5 py-3">
                        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                          {m.label}
                        </h3>
                        <ul className="space-y-2.5">
                          {m.groups.flatMap((g) => g.commits).map((c) => (
                            <li key={c.sha}>
                              <p className="text-sm leading-snug text-ink">{c.subject}</p>
                              {c.body && (
                                <p className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed text-ink-2">
                                  {c.body}
                                </p>
                              )}
                              <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-3">
                                <a href={c.url} target="_blank" rel="noreferrer"
                                   className="font-mono underline-offset-2 transition hover:text-ink hover:underline">
                                  {c.short_sha}
                                </a>
                                <span>·</span>
                                <span>{c.author}</span>
                                <span>·</span>
                                <span>{relativeTime(c.date)}</span>
                              </p>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                )}
                <p className="border-t border-stroke px-5 py-2.5 text-xs text-ink-3">
                  <a href={`${d.repo.url}/commits/${d.repo.branch}`} target="_blank"
                     rel="noreferrer" className="underline-offset-2 hover:text-ink hover:underline">
                    The full history is on GitHub
                  </a>
                </p>
              </div>
            )}
          </section>
        </div>
      ) : null}

      {editing && (
        <Modal
          title={editing === "new" ? "New page" : `Edit — ${editing.title}`}
          onClose={() => setEditing(null)}
          xl
          footer={
            <>
              <span className="mr-auto text-xs text-ink-3">
                Markdown. Saved here, not to the repository.
              </span>
              <Button onClick={() => setPreview((v) => !v)}>
                {preview ? "Write" : "Preview"}
              </Button>
              <Button onClick={() => setEditing(null)}>Cancel</Button>
              <Button variant="primary" spinning={saving}
                      disabled={!draft.title.trim()} onClick={() => void save()}>
                Save
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <TextInput label="Title" value={draft.title}
                       onChange={(v) => setDraft((s) => ({ ...s, title: v }))}
                       placeholder="The life of an inspection" />
            {preview ? (
              <div className="min-h-[24rem] rounded-lg bg-canvas p-4 ring-control">
                {draft.body.trim()
                  ? <Markdown source={bodyOf(draft.body)} />
                  : <p className="text-sm text-ink-3">Nothing written yet.</p>}
              </div>
            ) : (
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-ink-2">Page</span>
                <textarea
                  value={draft.body}
                  onChange={(e) => setDraft((s) => ({ ...s, body: e.target.value }))}
                  rows={20}
                  spellCheck
                  placeholder={"## What this covers\n\nPlain sentences. Use **bold**, `code`, lists and tables."}
                  className="w-full rounded-lg bg-canvas px-3 py-2 font-mono text-xs leading-relaxed text-ink ring-control focus-ring"
                />
              </label>
            )}
          </div>
        </Modal>
      )}

      {removing && (
        <ConfirmDialog
          title="Delete this page?"
          onClose={() => setRemoving(null)}
          onConfirm={() => void removePage(removing)}
          body={<><b className="text-ink">{removing.title}</b> will be deleted
                 from this platform. This cannot be undone.</>}
        />
      )}
    </AppShell>
  );
}
