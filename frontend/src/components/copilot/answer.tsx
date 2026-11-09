import { Badge } from "@/components/ui/badge";
import { badge, complianceKey } from "@/lib/status";

/** One citation as the backend stores it on the answer (copilot/source.py Source.as_json). */
export type Source = {
  number: number;
  kind: "passage" | "record" | "finding" | "summary";
  document_id: string | null;
  document: string | null;
  pages: [number, number] | null;
  section: string | null;
  compliance_status: string | null;
  status_reason: string | null;
  superseded: boolean;
  excerpt: string;
};

export function asSources(raw: Record<string, unknown>[]): Source[] {
  return raw as unknown as Source[];
}

export function pagesText(s: Source): string {
  if (!s.pages) return "";
  const [a, b] = s.pages;
  return a === b || !b ? `p. ${a}` : `pp. ${a}–${b}`;
}

export function citeLabel(s: Source): string {
  if (s.kind === "summary") return "Database";
  const p = pagesText(s);
  return [s.document ?? "Finding", p].filter(Boolean).join(" · ");
}

export function statusOf(s: Source) {
  return s.document ? complianceKey(s.compliance_status, s.superseded) : null;
}

/**
 * The answer text is "sentence [1, 2] sentence [3]" followed by a plain "Sources:" block
 * (copilot/answers.py compose). The block is dropped — the sources render as cards —
 * and each [n] marker becomes a clickable chip.
 */
export function AnswerBody({ content, sources, onCite }: { content: string; sources: Source[]; onCite: (s: Source) => void }) {
  const cut = content.lastIndexOf("\nSources:");
  const body = (cut >= 0 ? content.slice(0, cut) : content).trim();
  const byNumber = new Map(sources.map((s) => [s.number, s]));
  const paragraphs = body.split(/\n+/).filter((p) => p.trim());

  return (
    <>
      {paragraphs.map((p, i) => (
        <p key={i} className="m-0">
          {p.split(/(\[\d+(?:,\s*\d+)*\])/g).map((part, j) => {
            const m = part.match(/^\[(\d+(?:,\s*\d+)*)\]$/);
            if (!m) return <span key={j}>{part}</span>;
            return m[1]!.split(/,\s*/).map((n) => {
              const s = byNumber.get(Number(n));
              if (!s) return <span key={`${j}-${n}`}>[{n}]</span>;
              const key = statusOf(s);
              return (
                <button
                  key={`${j}-${n}`}
                  onClick={() => onCite(s)}
                  className="mx-0.5 inline-flex cursor-pointer items-center gap-1 rounded border border-line-chip bg-sand px-1.5 align-[1px] font-mono text-[12px] text-forest hover:bg-[#E8E1D1]"
                >
                  <span aria-hidden="true" style={{ color: key ? badge(key).fg : "#5C665E" }}>
                    ●
                  </span>
                  {citeLabel(s)}
                </button>
              );
            });
          })}
        </p>
      ))}
    </>
  );
}

/** "Source document is currently marked Stale …" — one note per stale / approaching / superseded document cited. */
export function StatusWarnings({ sources }: { sources: Source[] }) {
  const seen = new Set<string>();
  const notes = sources.filter((s) => {
    const k = statusOf(s);
    if (!s.document || !k || !["stale", "approaching", "superseded"].includes(k) || seen.has(s.document)) return false;
    seen.add(s.document);
    return true;
  });
  return (
    <>
      {notes.map((s) => {
        const k = statusOf(s)!;
        const b = badge(k);
        const text =
          k === "stale"
            ? `${s.document} is currently marked Stale — confirm against current vendor documentation before relying on it.`
            : k === "approaching"
              ? `${s.document} is approaching its review threshold.`
              : `${s.document} is superseded by a newer revision and kept as a historical record.`;
        return (
          <div
            key={s.document}
            role="note"
            className="flex items-start gap-2 rounded-md border px-3 py-[9px] text-[13.5px]"
            style={{ color: b.fg, background: b.bg, borderColor: b.bd }}
          >
            <span aria-hidden="true" className="font-bold">
              {b.icon}
            </span>
            <span>
              {text}
              {s.status_reason ? ` ${s.status_reason}` : ""}
            </span>
          </div>
        );
      })}
    </>
  );
}

export function SourceCards({ sources, onCite }: { sources: Source[]; onCite: (s: Source) => void }) {
  const docs = new Map<string, Source>();
  for (const s of sources) if (s.document && !docs.has(s.document)) docs.set(s.document, s);
  if (!docs.size) return null;
  return (
    <div className="flex flex-col gap-1.5 border-t border-line-soft pt-2.5">
      <span className="text-[12px] font-semibold tracking-[.05em] text-muted uppercase">Sources</span>
      <div className="flex flex-wrap gap-2">
        {[...docs.values()].map((s) => {
          const pages = sources.filter((x) => x.document === s.document).map(pagesText).filter(Boolean);
          return (
            <button
              key={s.document}
              onClick={() => onCite(s)}
              className="flex max-w-[320px] cursor-pointer flex-col gap-1 rounded-md border border-line bg-subtle px-2.5 py-2 text-left text-ink hover:border-sage"
            >
              <span className="text-[13.5px] leading-[1.35] font-medium">{s.document}</span>
              <span className="flex flex-wrap items-center gap-2">
                {pages.length > 0 && <span className="font-mono text-[12px] text-muted">{[...new Set(pages)].join(", ")}</span>}
                {statusOf(s) && <Badge status={statusOf(s)} size="xs" />}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
