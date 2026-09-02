"use client";

import { useEffect, useRef, useState } from "react";
import { Sidebar, Icon, canAccess, type Me } from "@/components/Sidebar";
import { AppShell } from "@/components/ui";

type Company = {
  id: number; name: string; systems: number; documents: number;
  logo?: string; brand_color?: string; industry?: string; website?: string;
  contact_name?: string; contact_email?: string; contact_phone?: string; description?: string;
};
type System = { id: number; name: string; description: string; documents: number };
type Folder = { id: number; name: string; folders: number; files: number };
type Doc = { id: number; name: string; size: number; uploaded_by: string; uploaded_at: string };
type Contents = { path: { id: number; name: string }[]; folders: Folder[]; documents: Doc[] };

type CForm = {
  name: string; logo: string; brand_color: string; industry: string; website: string;
  contact_name: string; contact_email: string; contact_phone: string; description: string;
};

const DEFAULT_BRAND = "#2563EB";
const PRESETS = ["#2563EB", "#0EA5E9", "#16A34A", "#0D9488", "#EA580C", "#DC2626", "#9333EA", "#DB2777", "#475569", "#0F172A"];

const emptyForm = (): CForm => ({ name: "", logo: "", brand_color: DEFAULT_BRAND, industry: "", website: "", contact_name: "", contact_email: "", contact_phone: "", description: "" });

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result as string);
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}

// Turn "Magnum Opus Consultants" into "MO"
function monogram(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

export default function DocumentationPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [view, setView] = useState<"companies" | "systems" | "files">("companies");
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [company, setCompany] = useState<Company | null>(null);
  const [systems, setSystems] = useState<System[] | null>(null);
  const [system, setSystem] = useState<{ id: number; name: string } | null>(null);
  const [folderId, setFolderId] = useState<number | null>(null);
  const [contents, setContents] = useState<Contents | null>(null);
  const [adding, setAdding] = useState(false);
  const [addVal, setAddVal] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const logoInput = useRef<HTMLInputElement>(null);

  // company branding modal
  const [editId, setEditId] = useState<number | null>(null); // 0 = new, >0 = edit, null = closed
  const [cForm, setCForm] = useState<CForm>(emptyForm());
  const [savingC, setSavingC] = useState(false);
  const [cErr, setCErr] = useState("");

  useEffect(() => {
    fetch("/api/auth/me").then((r) => (r.ok ? r.json() : Promise.reject())).then((m: Me) => { setMe(m); if (!canAccess(m, "documentation")) window.location.href = "/data-analysis"; }).catch(() => (window.location.href = "/login"));
    loadCompanies();
  }, []);

  const j = (r: Response) => (r.ok ? r.json() : Promise.reject());
  function loadCompanies() { fetch("/api/docs/companies").then(j).then((d) => setCompanies(d.companies)).catch(() => setCompanies([])); }
  function loadSystems(cid: number) { setSystems(null); fetch(`/api/docs/systems?company=${cid}`).then(j).then((d) => setSystems(d.systems)).catch(() => setSystems([])); }
  function loadContents(sid: number, fid: number | null) { setContents(null); fetch(`/api/docs/contents?system=${sid}${fid ? `&folder=${fid}` : ""}`).then(j).then(setContents).catch(() => setContents({ path: [], folders: [], documents: [] })); }

  function openCompany(c: Company) { setCompany(c); setView("systems"); loadSystems(c.id); }
  function openSystem(s: System) { setSystem(s); setFolderId(null); setView("files"); loadContents(s.id, null); }
  function openFolder(fid: number | null) { setFolderId(fid); if (system) loadContents(system.id, fid); }

  function openNewCompany() { setCErr(""); setCForm(emptyForm()); setEditId(0); }
  function openEditCompany(c: Company) {
    setCErr("");
    setCForm({
      name: c.name, logo: c.logo || "", brand_color: c.brand_color || DEFAULT_BRAND,
      industry: c.industry || "", website: c.website || "",
      contact_name: c.contact_name || "", contact_email: c.contact_email || "", contact_phone: c.contact_phone || "",
      description: c.description || "",
    });
    setEditId(c.id);
  }

  async function pickLogo(files: FileList | null) {
    const f = files?.[0];
    if (!f) return;
    if (!f.type.startsWith("image/")) { setCErr("Logo must be an image file."); return; }
    if (f.size > 1_500_000) { setCErr("Logo is too large — please use an image under 1.5 MB."); return; }
    setCErr("");
    setCForm((cf) => ({ ...cf, logo: "" }));
    const dataUrl = await fileToDataUrl(f);
    setCForm((cf) => ({ ...cf, logo: dataUrl }));
  }

  async function saveCompany() {
    if (!cForm.name.trim()) { setCErr("Company name is required."); return; }
    setSavingC(true); setCErr("");
    let id = editId || 0;
    try {
      if (!id) {
        const r = await fetch("/api/docs/companies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: cForm.name.trim() }) });
        const d = await r.json();
        if (!r.ok) { setCErr(d.detail || "Could not create company."); setSavingC(false); return; }
        id = d.id;
      }
      const r2 = await fetch(`/api/docs/companies/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cForm) });
      const d2 = await r2.json();
      if (!r2.ok) { setCErr(d2.detail || "Could not save."); setSavingC(false); return; }
      setSavingC(false);
      setEditId(null);
      loadCompanies();
      if (company && company.id === id && d2.company) setCompany(d2.company);
    } catch {
      setSavingC(false); setCErr("Network error.");
    }
  }

  async function create() {
    const name = addVal.trim();
    if (!name) return;
    if (view === "systems" && company) {
      await fetch("/api/docs/systems", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ company: company.id, name }) });
      loadSystems(company.id);
    } else if (view === "files" && system) {
      await fetch("/api/docs/folders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ system: system.id, parent: folderId, name }) });
      loadContents(system.id, folderId);
    }
    setAddVal(""); setAdding(false);
  }

  async function upload(files: FileList | null) {
    if (!files || !system) return;
    setUploading(true);
    for (const f of Array.from(files)) {
      const fd = new FormData();
      fd.append("system", String(system.id));
      if (folderId) fd.append("folder", String(folderId));
      fd.append("file", f);
      await fetch("/api/docs/documents", { method: "POST", body: fd });
    }
    setUploading(false);
    loadContents(system.id, folderId);
  }

  async function del(url: string, after: () => void) {
    await fetch(url, { method: "DELETE" });
    after();
  }

  const initials = me?.username?.slice(0, 2).toUpperCase() ?? "··";
  async function signOut() { await fetch("/api/auth/logout", { method: "POST" }); window.location.href = "/login"; }
  const size = (b: number) => (b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`);
  const addLabel = view === "systems" ? "New System" : "New Folder";
  const brand = company?.brand_color || DEFAULT_BRAND;

  return (
    <AppShell active="Documentation" me={me}>
          {/* breadcrumb */}
          <div className="mb-5 flex flex-wrap items-center gap-1.5 text-sm">
            <button onClick={() => { setView("companies"); setCompany(null); setSystem(null); loadCompanies(); }} className={`font-medium ${view === "companies" ? "text-ink" : "text-ink-3 hover:text-ink"}`}>Companies</button>
            {company && (<><span className="text-ink-3">/</span>
              <button onClick={() => { setView("systems"); setSystem(null); loadSystems(company.id); }} className={`font-medium ${view === "systems" ? "text-ink" : "text-ink-3 hover:text-ink"}`}>{company.name}</button></>)}
            {system && (<><span className="text-ink-3">/</span>
              <button onClick={() => openFolder(null)} className={`font-medium ${view === "files" && !folderId ? "text-ink" : "text-ink-3 hover:text-ink"}`}>{system.name}</button></>)}
            {view === "files" && contents?.path.map((p) => (
              <span key={p.id} className="flex items-center gap-1.5">
                <span className="text-ink-3">/</span>
                <button onClick={() => openFolder(p.id)} className={`font-medium ${folderId === p.id ? "text-ink" : "text-ink-3 hover:text-ink"}`}>{p.name}</button>
              </span>
            ))}
          </div>

          {/* COMPANIES */}
          {view === "companies" && (
            <>
              <div className="mb-4 flex items-center justify-between">
                <h1 className="text-lg font-semibold">Companies</h1>
                <button onClick={openNewCompany} className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white shadow-sm transition hover:bg-brand-hover">
                  <Icon name="plus" className="h-4 w-4" /> New Company
                </button>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {companies === null && <p className="col-span-full py-12 text-center text-sm text-ink-3">Loading…</p>}
                {companies?.length === 0 && <p className="col-span-full py-12 text-center text-sm text-ink-3">No companies yet. Add one to get started.</p>}
                {companies?.map((c) => {
                  const col = c.brand_color || DEFAULT_BRAND;
                  return (
                    <div key={c.id} className="group relative overflow-hidden rounded-lg border border-stroke bg-surface shadow-sm transition hover:shadow-md">
                      <div className="h-1.5 w-full" style={{ backgroundColor: col }} />
                      <div className="p-4">
                        <button onClick={() => openCompany(c)} className="flex w-full items-center gap-3 text-left">
                          {c.logo ? (
                            <img src={c.logo} alt="" className="h-11 w-11 shrink-0 rounded-lg object-contain ring-1 ring-stroke" />
                          ) : (
                            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-sm font-bold" style={{ backgroundColor: `${col}1A`, color: col }}>{monogram(c.name)}</span>
                          )}
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-semibold" title={c.name}>{c.name}</p>
                            <p className="truncate text-xs text-ink-3">{c.industry ? c.industry : `${c.systems} systems · ${c.documents} docs`}</p>
                          </div>
                        </button>
                        {c.industry && <p className="mt-2 text-xs text-ink-3">{c.systems} systems · {c.documents} docs</p>}
                      </div>
                      <div className="absolute right-2 top-3 flex gap-1 opacity-0 transition group-hover:opacity-100">
                        <button onClick={() => openEditCompany(c)} title="Edit company" className="rounded-lg bg-white/90 p-1 text-ink-3 shadow-sm hover:text-brand"><Icon name="edit" className="h-4 w-4" /></button>
                        <button onClick={() => del(`/api/docs/companies/${c.id}`, loadCompanies)} title="Delete" className="rounded-lg bg-white/90 p-1 text-ink-3 shadow-sm hover:text-red-500"><Icon name="trash" className="h-4 w-4" /></button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {/* SYSTEMS — with company profile banner */}
          {view === "systems" && company && (
            <>
              {/* profile banner */}
              <div className="mb-5 overflow-hidden rounded-2xl border border-stroke bg-surface shadow-sm">
                <div className="h-2 w-full" style={{ backgroundColor: brand }} />
                <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-start">
                  {company.logo ? (
                    <img src={company.logo} alt="" className="h-16 w-16 shrink-0 rounded-lg object-contain ring-1 ring-stroke" />
                  ) : (
                    <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg text-xl font-bold" style={{ backgroundColor: `${brand}1A`, color: brand }}>{monogram(company.name)}</span>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h1 className="text-xl font-semibold">{company.name}</h1>
                      {company.industry && <span className="rounded-full px-2 py-0.5 text-xs font-medium" style={{ backgroundColor: `${brand}1A`, color: brand }}>{company.industry}</span>}
                    </div>
                    {company.description && <p className="mt-1.5 max-w-2xl text-sm text-ink-2">{company.description}</p>}
                    <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
                      {company.website && <a href={company.website.startsWith("http") ? company.website : `https://${company.website}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-brand"><Icon name="globe" className="h-3.5 w-3.5" />{company.website}</a>}
                      {company.contact_name && <span className="inline-flex items-center gap-1"><Icon name="users" className="h-3.5 w-3.5" />{company.contact_name}</span>}
                      {company.contact_email && <a href={`mailto:${company.contact_email}`} className="inline-flex items-center gap-1 hover:text-brand"><Icon name="mail" className="h-3.5 w-3.5" />{company.contact_email}</a>}
                      {company.contact_phone && <span className="inline-flex items-center gap-1"><Icon name="phone" className="h-3.5 w-3.5" />{company.contact_phone}</span>}
                    </div>
                  </div>
                  <button onClick={() => openEditCompany(company)} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-stroke bg-surface px-3 py-1.5 text-sm font-medium text-ink transition hover:border-brand hover:text-brand">
                    <Icon name="edit" className="h-4 w-4" /> Edit
                  </button>
                </div>
              </div>

              {/* systems add bar */}
              <div className="mb-4 flex items-center gap-2">
                {adding ? (
                  <form onSubmit={(e) => { e.preventDefault(); create(); }} className="flex items-center gap-2">
                    <input autoFocus value={addVal} onChange={(e) => setAddVal(e.target.value)} placeholder={`${addLabel} name`} className="rounded-lg border border-stroke px-3 py-1.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand" />
                    <button type="submit" className="rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-hover">Add</button>
                    <button type="button" onClick={() => { setAdding(false); setAddVal(""); }} className="text-sm text-ink-3 hover:text-ink">Cancel</button>
                  </form>
                ) : (
                  <button onClick={() => setAdding(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-stroke bg-surface px-3 py-1.5 text-sm font-medium text-ink transition hover:border-brand hover:text-brand">
                    <Icon name="plus" className="h-4 w-4" /> {addLabel}
                  </button>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
                {systems === null && <p className="col-span-full py-12 text-center text-sm text-ink-3">Loading…</p>}
                {systems?.length === 0 && <p className="col-span-full py-12 text-center text-sm text-ink-3">No systems/projects yet.</p>}
                {systems?.map((s) => (
                  <div key={s.id} className="group relative rounded-lg border border-stroke bg-surface p-3.5 shadow-sm transition hover:shadow-md">
                    <button onClick={() => openSystem(s)} className="block w-full text-left">
                      <span className="flex h-9 w-9 items-center justify-center rounded-lg" style={{ backgroundColor: `${brand}1A`, color: brand }}><Icon name="server" /></span>
                      <p className="mt-2 truncate text-sm font-semibold" title={s.name}>{s.name}</p>
                      <p className="text-xs text-ink-3">{s.documents} documents</p>
                    </button>
                    <button onClick={() => del(`/api/docs/systems/${s.id}`, () => company && loadSystems(company.id))} className="absolute right-2 top-2 opacity-0 transition group-hover:opacity-100"><Icon name="trash" className="h-4 w-4 text-ink-3 hover:text-red-500" /></button>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* FILES (folder tree) */}
          {view === "files" && (
            <>
              <div className="mb-4 flex items-center gap-2">
                {adding ? (
                  <form onSubmit={(e) => { e.preventDefault(); create(); }} className="flex items-center gap-2">
                    <input autoFocus value={addVal} onChange={(e) => setAddVal(e.target.value)} placeholder={`${addLabel} name`} className="rounded-lg border border-stroke px-3 py-1.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand" />
                    <button type="submit" className="rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-hover">Add</button>
                    <button type="button" onClick={() => { setAdding(false); setAddVal(""); }} className="text-sm text-ink-3 hover:text-ink">Cancel</button>
                  </form>
                ) : (
                  <button onClick={() => setAdding(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-stroke bg-surface px-3 py-1.5 text-sm font-medium text-ink transition hover:border-brand hover:text-brand">
                    <Icon name="plus" className="h-4 w-4" /> {addLabel}
                  </button>
                )}
                <button onClick={() => fileInput.current?.click()} disabled={uploading} className="inline-flex items-center gap-1.5 rounded-lg border border-stroke bg-surface px-3 py-1.5 text-sm font-medium text-ink transition hover:border-brand hover:text-brand disabled:opacity-60">
                  <Icon name="upload" className={`h-4 w-4 ${uploading ? "animate-pulse" : ""}`} /> {uploading ? "Uploading…" : "Upload"}
                </button>
                <input ref={fileInput} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
              </div>

              <div className="overflow-hidden rounded-lg border border-stroke bg-surface shadow-sm">
                {contents === null && <p className="py-12 text-center text-sm text-ink-3">Loading…</p>}
                {contents && contents.folders.length === 0 && contents.documents.length === 0 && (
                  <p className="py-12 text-center text-sm text-ink-3">Empty folder. Add a folder or upload a document.</p>
                )}
                <ul className="divide-y divide-stroke-soft">
                  {contents?.folders.map((f) => (
                    <li key={`f${f.id}`} className="group flex items-center gap-3 px-4 py-3 hover:bg-subtle">
                      <button onClick={() => openFolder(f.id)} className="flex flex-1 items-center gap-3 text-left">
                        <Icon name="folder" className="h-5 w-5 text-blue-400" />
                        <span className="font-medium">{f.name}</span>
                        <span className="text-xs text-ink-3">{f.folders} folders · {f.files} files</span>
                      </button>
                      <button onClick={() => del(`/api/docs/folders/${f.id}`, () => system && loadContents(system.id, folderId))} className="opacity-0 transition group-hover:opacity-100"><Icon name="trash" className="h-4 w-4 text-ink-3 hover:text-red-500" /></button>
                    </li>
                  ))}
                  {contents?.documents.map((d) => (
                    <li key={`d${d.id}`} className="group flex items-center gap-3 px-4 py-3 hover:bg-subtle">
                      <Icon name="file" className="h-5 w-5 text-ink-3" />
                      <span className="flex-1 truncate">
                        <span className="font-medium">{d.name}</span>
                        <span className="ml-2 text-xs text-ink-3">{size(d.size)} · {d.uploaded_at}{d.uploaded_by ? ` · ${d.uploaded_by}` : ""}</span>
                      </span>
                      <a href={`/api/docs/documents/${d.id}/download`} className="text-ink-3 hover:text-brand" title="Download"><Icon name="download" className="h-4 w-4" /></a>
                      <button onClick={() => del(`/api/docs/documents/${d.id}`, () => system && loadContents(system.id, folderId))} className="opacity-0 transition group-hover:opacity-100"><Icon name="trash" className="h-4 w-4 text-ink-3 hover:text-red-500" /></button>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}

      {/* company branding / profile modal */}
      {editId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand/40 p-4" onClick={() => !savingC && setEditId(null)}>
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-surface p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{editId ? "Edit company" : "New company"}</h2>
              <button onClick={() => setEditId(null)} className="text-ink-3 transition hover:text-ink">✕</button>
            </div>

            {cErr && <p className="mt-4 rounded-lg bg-bad-bg px-3 py-2 text-sm text-red-600">{cErr}</p>}

            {/* logo + brand */}
            <div className="mt-5 flex items-center gap-4">
              {cForm.logo ? (
                <img src={cForm.logo} alt="" className="h-16 w-16 shrink-0 rounded-lg object-contain ring-1 ring-stroke" />
              ) : (
                <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg text-xl font-bold" style={{ backgroundColor: `${cForm.brand_color}1A`, color: cForm.brand_color }}>{monogram(cForm.name || "Co")}</span>
              )}
              <div className="flex flex-col gap-1.5">
                <div className="flex gap-2">
                  <button onClick={() => logoInput.current?.click()} className="rounded-lg border border-stroke px-3 py-1.5 text-sm font-medium text-ink transition hover:border-brand hover:text-brand">Upload logo</button>
                  {cForm.logo && <button onClick={() => setCForm({ ...cForm, logo: "" })} className="rounded-lg px-2 py-1.5 text-sm text-ink-3 hover:text-red-500">Remove</button>}
                </div>
                <p className="text-xs text-ink-3">PNG or SVG, under 1.5 MB. Falls back to a colored monogram.</p>
                <input ref={logoInput} type="file" accept="image/*" hidden onChange={(e) => pickLogo(e.target.files)} />
              </div>
            </div>

            {/* brand color */}
            <div className="mt-5">
              <label className="text-xs font-medium text-ink-2">Brand color</label>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {PRESETS.map((p) => (
                  <button key={p} onClick={() => setCForm({ ...cForm, brand_color: p })} className={`h-7 w-7 rounded-full ring-2 ring-offset-2 transition ${cForm.brand_color.toLowerCase() === p.toLowerCase() ? "ring-brand" : "ring-transparent"}`} style={{ backgroundColor: p }} aria-label={p} />
                ))}
                <label className="ml-1 inline-flex items-center gap-1.5 text-xs text-ink-2">
                  <input type="color" value={cForm.brand_color || DEFAULT_BRAND} onChange={(e) => setCForm({ ...cForm, brand_color: e.target.value })} className="h-7 w-9 cursor-pointer rounded border border-stroke bg-surface" />
                  custom
                </label>
              </div>
            </div>

            {/* fields */}
            <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="text-xs font-medium text-ink-2">Company name</label>
                <input value={cForm.name} onChange={(e) => setCForm({ ...cForm, name: e.target.value })} placeholder="Magnum Opus Consultants" className="mt-1 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand" />
              </div>
              <div>
                <label className="text-xs font-medium text-ink-2">Industry</label>
                <input value={cForm.industry} onChange={(e) => setCForm({ ...cForm, industry: e.target.value })} placeholder="Consulting" className="mt-1 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand" />
              </div>
              <div>
                <label className="text-xs font-medium text-ink-2">Website</label>
                <input value={cForm.website} onChange={(e) => setCForm({ ...cForm, website: e.target.value })} placeholder="company.com" className="mt-1 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand" />
              </div>
              <div>
                <label className="text-xs font-medium text-ink-2">Contact name</label>
                <input value={cForm.contact_name} onChange={(e) => setCForm({ ...cForm, contact_name: e.target.value })} placeholder="Jane Doe" className="mt-1 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand" />
              </div>
              <div>
                <label className="text-xs font-medium text-ink-2">Contact phone</label>
                <input value={cForm.contact_phone} onChange={(e) => setCForm({ ...cForm, contact_phone: e.target.value })} placeholder="+27 ..." className="mt-1 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand" />
              </div>
              <div className="sm:col-span-2">
                <label className="text-xs font-medium text-ink-2">Contact email</label>
                <input value={cForm.contact_email} onChange={(e) => setCForm({ ...cForm, contact_email: e.target.value })} placeholder="jane@company.com" className="mt-1 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand" />
              </div>
              <div className="sm:col-span-2">
                <label className="text-xs font-medium text-ink-2">Profile <span className="text-ink-3">(short description)</span></label>
                <textarea value={cForm.description} onChange={(e) => setCForm({ ...cForm, description: e.target.value })} rows={3} placeholder="What this company does, key notes…" className="mt-1 w-full rounded-lg border border-stroke px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand" />
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-2">
              <button onClick={() => setEditId(null)} disabled={savingC} className="rounded-lg border border-stroke px-4 py-2 text-sm font-medium text-ink-2 transition hover:border-brand hover:text-ink">Cancel</button>
              <button onClick={saveCompany} disabled={savingC || !cForm.name.trim()} className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-hover disabled:opacity-40">
                {savingC ? "Saving…" : editId ? "Save changes" : "Create company"}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
