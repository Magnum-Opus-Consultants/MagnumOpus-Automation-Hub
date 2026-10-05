/* What this tab has already loaded, kept between page visits.
 *
 * Every page renders its own AppShell, so moving from one project to the next
 * mounts a fresh sidebar and a fresh page - and both used to start empty and
 * fetch everything again, which looked like a full reload each time. Pages
 * now start from the last copy they saw here and refresh it quietly, and the
 * sidebar loads a project's data on hover so it is usually there before the
 * click lands.
 *
 * Module memory only: it lasts until the tab reloads and is never written to
 * storage, so nothing outlives the session. Signing out reloads the page,
 * which empties it before anyone else signs in. */

const store = new Map<string, { value: unknown; at: number }>();
const inflight = new Map<string, Promise<unknown>>();

export function peek<T>(key: string): T | undefined {
  return store.get(key)?.value as T | undefined;
}

export function put<T>(key: string, value: T): void {
  store.set(key, { value, at: Date.now() });
}

/* ── one project's page data ──────────────────────────────────────────────── */

export type ProjectBundle = {
  detail: unknown;        // the project, or "missing" when there is none
  tasks: unknown;
  metrics: unknown;
  activity: unknown[];
};

const projectKey = (name: string) => `project:${name}`;

export function peekProject(name: string): ProjectBundle | undefined {
  return peek<ProjectBundle>(projectKey(name));
}

/** Fetch a project's page data (and remember it). Callers asking at the same
    time share one set of requests. */
export function loadProject(name: string): Promise<ProjectBundle> {
  const key = projectKey(name);
  const running = inflight.get(key) as Promise<ProjectBundle> | undefined;
  if (running) return running;
  const enc = encodeURIComponent(name);
  const json = (r: Response) => (r.ok ? r.json() : null);
  const p = Promise.all([
    fetch(`/api/projects/${enc}`).then((r) => (r.status === 404 ? "missing" : json(r))),
    fetch(`/api/tasks?project=${enc}`).then(json),
    fetch(`/api/projects/metrics?project=${enc}`).then(json),
    fetch(`/api/projects/${enc}/activity?limit=150`).then(json),
  ]).then(([detail, tasks, metrics, activity]) => {
    const bundle: ProjectBundle = { detail, tasks, metrics, activity: activity?.activity ?? [] };
    put(key, bundle);
    return bundle;
  }).finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

/** Warm a project before it is opened - from a hover or focus in the sidebar.
    Skipped when a recent copy is already here. */
export function prefetchProject(name: string): void {
  if (!name) return;
  const hit = store.get(projectKey(name));
  if (hit && Date.now() - hit.at < 30_000) return;
  void loadProject(name).catch(() => {
    // A failed warm-up costs nothing; the page fetches again when opened.
  });
}
