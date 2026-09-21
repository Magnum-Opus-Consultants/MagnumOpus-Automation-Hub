"use client";

/**
 * A small Markdown renderer for documentation pages.
 *
 * Hand-written rather than a library, for one reason that matters: it builds
 * React elements, never an HTML string. There is no `dangerouslySetInnerHTML`
 * anywhere, so a repository's README cannot inject script into this app — and
 * these documents come from whoever can push to the repo, which is not
 * necessarily whoever is reading the page.
 *
 * It covers what documentation actually uses: headings, paragraphs, lists,
 * fenced and inline code, blockquotes, rules, tables, links, bold and italic.
 * Anything it does not recognise renders as its own literal text rather than
 * disappearing — losing a line silently would be worse than showing it plain.
 */
import { useId } from "react";

/** Inline: `code`, **bold**, *italic*, [text](url). */
function inline(text: string, keyBase: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  // One pass, longest-token-first so ** is not eaten by *.
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;

  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${i++}`;

    if (tok.startsWith("`")) {
      out.push(
        <code key={key} className="rounded bg-subtle px-1 py-0.5 font-mono text-[0.9em] text-ink">
          {tok.slice(1, -1)}
        </code>);
    } else if (tok.startsWith("**") || tok.startsWith("__")) {
      out.push(<strong key={key} className="font-semibold text-ink">{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("*")) {
      out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    } else {
      const close = tok.indexOf("](");
      const label = tok.slice(1, close);
      const href = tok.slice(close + 2, -1);
      // Only http(s) and in-app paths; a javascript: URL in a README is not
      // something this page should make clickable.
      const safe = /^(https?:\/\/|\/|#)/i.test(href);
      out.push(safe
        ? <a key={key} href={href} target={href.startsWith("http") ? "_blank" : undefined}
             rel="noreferrer"
             className="text-brand underline underline-offset-2 hover:text-brand-hover">{label}</a>
        : <span key={key}>{label}</span>);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ source }: { source: string }) {
  const uid = useId();
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  const k = () => `${uid}-${key++}`;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code
    if (line.startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={k()} className="my-3 overflow-x-auto rounded-lg bg-subtle p-3 text-xs leading-relaxed">
          <code className="font-mono text-ink-2">{body.join("\n")}</code>
        </pre>);
      continue;
    }

    // Headings
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const text = h[2];
      const cls = level === 1 ? "mt-6 mb-2 text-xl font-semibold text-ink first:mt-0"
                : level === 2 ? "mt-6 mb-2 text-base font-semibold text-ink first:mt-0"
                : "mt-4 mb-1.5 text-sm font-semibold text-ink";
      const Tag = (`h${Math.min(level + 1, 6)}`) as "h2";
      blocks.push(<Tag key={k()} className={cls}>{inline(text, k())}</Tag>);
      i++;
      continue;
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push(<hr key={k()} className="my-5 border-stroke" />);
      i++;
      continue;
    }

    // Blockquote
    if (line.startsWith("> ")) {
      const body: string[] = [];
      while (i < lines.length && lines[i].startsWith("> ")) body.push(lines[i++].slice(2));
      blocks.push(
        <blockquote key={k()} className="my-3 border-l-2 border-stroke pl-3 text-sm italic text-ink-2">
          {inline(body.join(" "), k())}
        </blockquote>);
      continue;
    }

    // Lists
    const bullet = /^\s*[-*+]\s+(.*)$/;
    const numbered = /^\s*\d+[.)]\s+(.*)$/;
    if (bullet.test(line) || numbered.test(line)) {
      const ordered = numbered.test(line);
      const items: string[] = [];
      while (i < lines.length) {
        const m = ordered ? numbered.exec(lines[i]) : bullet.exec(lines[i]);
        if (!m) break;
        items.push(m[1]);
        i++;
      }
      const Tag = ordered ? "ol" : "ul";
      blocks.push(
        <Tag key={k()} className={`my-2 space-y-1 pl-5 text-sm leading-relaxed text-ink-2 ${
          ordered ? "list-decimal" : "list-disc"}`}>
          {items.map((it) => <li key={k()}>{inline(it, k())}</li>)}
        </Tag>);
      continue;
    }

    // Table
    if (line.includes("|") && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1] ?? "")) {
      const cells = (row: string) =>
        row.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|")) rows.push(cells(lines[i++]));
      blocks.push(
        <div key={k()} className="my-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-stroke">
                {head.map((c) => (
                  <th key={k()} className="px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-3">
                    {inline(c, k())}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={k()} className="border-b border-stroke/60 last:border-0">
                  {r.map((c) => (
                    <td key={k()} className="px-2 py-1.5 align-top text-ink-2">{inline(c, k())}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>);
      continue;
    }

    // Blank
    if (!line.trim()) { i++; continue; }

    // Paragraph: consecutive non-blank lines that start no other block.
    const para: string[] = [];
    while (i < lines.length && lines[i].trim()
           && !lines[i].startsWith("#") && !lines[i].startsWith("```")
           && !lines[i].startsWith("> ")
           && !bullet.test(lines[i]) && !numbered.test(lines[i])) {
      para.push(lines[i++]);
    }
    blocks.push(
      <p key={k()} className="my-2.5 text-sm leading-relaxed text-ink-2">
        {inline(para.join(" "), k())}
      </p>);
  }

  return <div className="max-w-3xl">{blocks}</div>;
}
