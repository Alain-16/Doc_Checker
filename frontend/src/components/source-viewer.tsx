"use client";

import { useMemo, useState } from "react";
import { usePages } from "@/lib/api/hooks";
import type { Schemas } from "@/lib/api/client";

type PageOut = Schemas["PageOut"];

/** Splits text around the first occurrence of `snippet` (whitespace-insensitive). */
function splitOnSnippet(text: string, snippet: string | null | undefined): [string, string, string] | null {
  if (!snippet) return null;
  const words = snippet.trim().split(/\s+/).filter(Boolean).slice(0, 25);
  if (!words.length) return null;
  const pattern = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
  const match = new RegExp(pattern, "i").exec(text);
  if (!match) return null;
  return [text.slice(0, match.index), match[0], text.slice(match.index + match[0].length)];
}

const SIZES = {
  lg: { head: "text-[9px]", text: "text-[12.5px]", pad: "px-[7%] py-[6%]" },
  md: { head: "text-[8px]", text: "text-[11px]", pad: "px-[6%] py-[5%]" },
  sm: { head: "text-[7.5px]", text: "text-[9.5px]", pad: "px-[5%] py-[4%]" },
};

/** One page as the pipeline read it, with the evidence snippet highlighted. */
export function TextPage({
  page,
  heading,
  highlight,
  size = "lg",
  filename,
}: {
  page: PageOut;
  heading?: string | null;
  highlight?: string | null;
  size?: keyof typeof SIZES;
  filename?: string;
}) {
  const s = SIZES[size];
  const parts = splitOnSnippet(page.text, highlight);
  const scanned = page.source_type !== "digital";
  return (
    <div
      className={`flex aspect-[8.5/11] flex-col gap-2 overflow-hidden border border-viewer-line text-[#26302A] shadow-[0_1px_3px_rgba(30,59,47,.18)] ${s.pad} ${scanned ? "bg-[#EFECE4]" : "bg-white"}`}
    >
      <div className={`flex shrink-0 justify-between gap-2 border-b border-[#D9D3C6] pb-1.5 tracking-[.08em] text-[#6B746D] uppercase ${s.head}`}>
        <span className="truncate">{heading ?? ""}</span>
        <span className="whitespace-nowrap">
          Page {page.page_number}
          {scanned && ` · OCR ${Math.round(page.confidence * 100)}%`}
        </span>
      </div>
      <div className={`min-h-0 flex-1 overflow-auto leading-normal whitespace-pre-wrap ${s.text} ${scanned ? "font-mono" : "font-sans"}`}>
        {page.text.trim() === "" ? (
          <span className="text-muted-3 italic">No text was read on this page (image or blank).</span>
        ) : parts ? (
          <>
            {parts[0]}
            <mark className="rounded-sm bg-[#F3DE9E] px-0.5 text-inherit outline outline-[1.5px] outline-[#B8923A]">{parts[1]}</mark>
            {parts[2]}
          </>
        ) : (
          page.text
        )}
      </div>
      {filename && size !== "sm" && <div className="shrink-0 text-[9px] text-[#8A918A]">{filename} · page {page.page_number}</div>}
    </div>
  );
}

/** Loads one page of a vendor file and shows it. */
export function SinglePage({
  fileId,
  page,
  highlight,
  heading,
  size = "md",
}: {
  fileId: string;
  page: number;
  highlight?: string | null;
  heading?: string | null;
  size?: keyof typeof SIZES;
}) {
  const pages = usePages(fileId, page, page);
  if (pages.isPending) return <div className="flex aspect-[8.5/11] animate-pulse-soft items-center justify-center bg-white text-xs text-muted">Loading page…</div>;
  if (pages.isError || !pages.data[0]) return <div className="p-4 text-xs text-muted">Page {page} could not be loaded.</div>;
  return <TextPage page={pages.data[0]} highlight={highlight} heading={heading} size={size} />;
}

/**
 * The side-by-side source viewer: page thumbnails, prev/next, zoom, and the
 * page text with the selected evidence highlighted.
 */
export function SourceViewer({
  fileId,
  filename,
  from,
  to,
  page,
  onPage,
  highlight,
  highlightLabel,
  onClearHighlight,
  heading,
}: {
  fileId: string;
  filename: string;
  from: number;
  to: number;
  page: number;
  onPage: (n: number) => void;
  highlight?: string | null;
  highlightLabel?: string | null;
  onClearHighlight?: () => void;
  heading?: string | null;
}) {
  const [zoom, setZoom] = useState(100);
  const pages = usePages(fileId, from, to);
  const current = useMemo(() => pages.data?.find((p) => p.page_number === page), [pages.data, page]);
  const numbers = Array.from({ length: to - from + 1 }, (_, i) => from + i);

  return (
    <section aria-label="Source document viewer" className="flex min-w-0 flex-col overflow-hidden rounded-lg border border-viewer-line bg-viewer">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-paper px-2.5 py-2">
        <span className="text-[14px] font-semibold">Source</span>
        <span className="min-w-[120px] flex-1 truncate font-mono text-[12.5px] text-muted">{filename}</span>
        <div className="flex items-center gap-1">
          <ViewerButton label="Previous page" onClick={() => onPage(Math.max(from, page - 1))}>
            ‹
          </ViewerButton>
          <span className="min-w-[104px] text-center font-mono text-xs">
            Page {page} · {from}–{to}
          </span>
          <ViewerButton label="Next page" onClick={() => onPage(Math.min(to, page + 1))}>
            ›
          </ViewerButton>
        </div>
        <div className="flex items-center gap-1">
          <ViewerButton label="Zoom out" onClick={() => setZoom((z) => Math.max(75, z - 25))}>
            −
          </ViewerButton>
          <span className="w-10 text-center font-mono text-xs">{zoom}%</span>
          <ViewerButton label="Zoom in" onClick={() => setZoom((z) => Math.min(175, z + 25))}>
            +
          </ViewerButton>
        </div>
        <a href={`/api/vendor-files/${fileId}/original`} className="text-xs whitespace-nowrap text-forest underline">
          Original PDF
        </a>
      </div>
      {highlightLabel && (
        <div className="flex items-center gap-2 border-b border-[#E3CC8A] bg-[#F6EBCB] px-3 py-[7px] text-xs text-[#5A4500]">
          <span aria-hidden="true">⌖</span>
          <span className="flex-1">{highlightLabel}</span>
          {onClearHighlight && (
            <button onClick={onClearHighlight} className="cursor-pointer border-none bg-transparent text-xs text-[#5A4500] underline">
              Clear
            </button>
          )}
        </div>
      )}
      <div className="flex min-h-0">
        <div className="flex max-h-[760px] w-14 shrink-0 flex-col gap-1.5 overflow-auto border-r border-viewer-line px-2 py-2.5">
          {numbers.map((n) => (
            <button
              key={n}
              onClick={() => onPage(n)}
              aria-label={`Page ${n}`}
              className="flex aspect-[8.5/11] shrink-0 cursor-pointer items-end justify-center rounded-sm pb-0.5 font-mono text-[11px] text-forest"
              style={{ border: `1.5px solid ${n === page ? "#1E3B2F" : "#D8D0BE"}`, background: n === page ? "#FFFFFF" : "#FBF8F1", fontWeight: n === page ? 600 : 400 }}
            >
              {n}
            </button>
          ))}
        </div>
        <div className="flex max-h-[760px] flex-1 justify-center overflow-auto p-[18px]">
          <div className="w-full shrink-0" style={{ maxWidth: Math.round((560 * zoom) / 100) }}>
            {pages.isPending && <div className="flex aspect-[8.5/11] animate-pulse-soft items-center justify-center bg-white text-muted">Loading pages…</div>}
            {pages.isError && <div className="p-4 text-muted">The pages could not be loaded.</div>}
            {current && <TextPage page={current} highlight={highlight} heading={heading} filename={filename} />}
            {pages.isSuccess && !current && <div className="p-4 text-muted">Page {page} has no text on file.</div>}
          </div>
        </div>
      </div>
    </section>
  );
}

function ViewerButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} aria-label={label} className="h-[26px] w-7 cursor-pointer rounded border border-line-strong bg-paper text-forest">
      {children}
    </button>
  );
}
