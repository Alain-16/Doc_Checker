"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { docStatus, pagesText } from "@/components/doc-table";
import { findingPage, findingSnippet } from "@/components/findings";
import { useCrumbs } from "@/components/shell/crumbs";
import { SourceViewer } from "@/components/source-viewer";
import { Badge, EmptyState, ErrorNote } from "@/components/ui/badge";
import { Page } from "@/components/ui/page";
import { ApiError } from "@/lib/api/client";
import { useDocument } from "@/lib/api/hooks";
import { fmtDate, fmtDateTime, humanize } from "@/lib/format";

type Selected = { page: number; snippet: string | null; label: string } | null;

function valueText(value: unknown): string {
  if (value === null || value === undefined) return "Not stated";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((v) => (typeof v === "object" ? Object.values(v as object).join(" · ") : String(v))).join("; ");
  return JSON.stringify(value);
}

export default function DocumentDetailPage() {
  const { docId } = useParams<{ docId: string }>();
  const params = useSearchParams();
  const doc = useDocument(docId);
  const d = doc.data;
  const [page, setPage] = useState<number | null>(params.get("page") ? Number(params.get("page")) : null);
  const [selected, setSelected] = useState<Selected>(null);
  useCrumbs([{ label: "Documents", href: "/documents" }, { label: d?.vendor_name ?? "…" }, { label: d?.label ?? "…" }]);

  if (doc.isError) {
    return (
      <Page>
        {doc.error instanceof ApiError && doc.error.status === 404 ? (
          <EmptyState title="Document not found.">
            <Link href="/documents" className="btn-secondary no-underline">
              Back to documents
            </Link>
          </EmptyState>
        ) : (
          <ErrorNote error={doc.error} />
        )}
      </Page>
    );
  }
  if (!d) return <Page><div className="animate-pulse-soft text-muted">Loading document…</div></Page>;

  const governing = d.dates.find((x) => x.is_document_date && d.governing_date && x.date_value === d.governing_date);
  const shownPage = page ?? governing?.page_number ?? d.start_page;
  const select = (p: number | null | undefined, snippet: string | null | undefined, label: string) => {
    if (!p) return;
    setPage(p);
    setSelected({ page: p, snippet: snippet ?? null, label });
  };
  const status = docStatus(d);
  const openFindings = d.findings.filter((f) => !f.resolved);
  const pastFindings = d.findings.filter((f) => f.resolved);
  const confidences: [string, number | null | undefined][] = [
    ["Classification", d.classification_confidence],
    ["Segmentation", d.segmentation_confidence],
    ["Lowest date", d.dates.length ? Math.min(...d.dates.map((x) => x.confidence)) : null],
    ["Lowest attribute", d.attributes.length ? Math.min(...d.attributes.map((x) => x.confidence)) : null],
  ];
  const anyLow = confidences.some(([, v]) => v != null && v < 0.8);

  const control: { label: string; value: string; warn?: boolean }[] = [
    { label: "Vendor", value: d.vendor_name ?? "Not identified", warn: !d.vendor_name },
    { label: "Component / Item", value: d.component_name ?? "—" },
    { label: "Document type", value: d.document_type_label ?? "Unclassified — review pending", warn: !d.document_type_label },
    { label: "Document number", value: d.document_number ?? "—" },
    { label: "Revision", value: d.revision ?? "—" },
    { label: "Governing date", value: d.governing_date ? fmtDate(d.governing_date) : "Not determined", warn: !d.governing_date },
    { label: "Page range", value: `${pagesText(d)} of ${d.filename}` },
  ];

  return (
    <Page max={1600} tight>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-[1_1_520px] flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="eyebrow">{d.document_type_label ?? "Unclassified"}</span>
            <Badge status={status} />
          </div>
          <h1 className="m-0 text-[22px] leading-[1.3] font-semibold text-pretty">{d.title || d.label}</h1>
          <div className="flex flex-wrap gap-x-[18px] gap-y-1 text-[14px] text-muted-2">
            <span>
              Vendor:{" "}
              {d.vendor_id ? (
                <Link href={`/vendors/${d.vendor_id}`} className="font-medium">
                  {d.vendor_name}
                </Link>
              ) : (
                <strong className="font-medium text-review">Not identified</strong>
              )}
            </span>
            <span>
              Component: <strong className="font-medium text-ink">{d.component_name ?? "—"}</strong>
            </span>
            <span>
              No.: <strong className="font-mono font-medium text-ink">{d.document_number || "—"}</strong>
            </span>
            <span>
              Rev: <strong className="font-mono font-medium text-ink">{d.revision || "—"}</strong>
            </span>
            <span>
              Pages: <strong className="font-mono font-medium text-ink">{pagesText(d)}</strong>
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href={`/vendor-files/${d.vendor_file_id}?page=${shownPage}`} className="btn-secondary no-underline">
            Open original vendor file
          </Link>
          <Link
            href={`/copilot?vendor=${encodeURIComponent(d.vendor_id ?? "")}&q=${encodeURIComponent(`What does the ${d.label} say, and why is its status ${status === "open" ? "pending" : status}?`)}`}
            className="btn-primary no-underline hover:text-page"
          >
            Ask Copilot about this document
          </Link>
        </div>
      </div>

      {d.superseded_by && (
        <div role="note" className="flex flex-wrap items-center gap-2.5 rounded-md border border-[#D2CEC2] bg-[#ECEAE3] px-3.5 py-2.5 text-[#3E4C43]">
          <span aria-hidden="true">↺</span>Historical record. Superseded by
          <Link href={`/documents/${d.superseded_by.id}`}>{d.superseded_by.label}</Link>
          {d.superseded_by.governing_date && `(${fmtDate(d.superseded_by.governing_date)})`}. Not used for current compliance status.
        </div>
      )}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,440px),1fr))] items-start gap-4">
        <div className="flex min-w-0 flex-col gap-3.5">
          <section className="card">
            <div className="card-head items-baseline">
              <h2 className="card-title">Compliance status</h2>
              <Badge status={status} />
            </div>
            <div className="flex flex-col gap-3 px-4 py-3.5">
              <p className="m-0 text-[14.5px] leading-normal">{d.status_reason ?? "Not evaluated yet."}</p>
              <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[13.5px]">
                <dt className="text-muted">Governing date</dt>
                <dd className="m-0 font-mono">
                  {d.governing_date ? `${fmtDate(d.governing_date)}${governing ? ` (${governing.date_type} date)` : ""}` : "Not determined"}
                </dd>
                <dt className="text-muted">Open findings</dt>
                <dd className="m-0 font-mono">{openFindings.length}</dd>
                <dt className="text-muted">Evaluation date</dt>
                <dd className="m-0 font-mono">{fmtDateTime(d.status_evaluated_at)}</dd>
              </dl>
              {d.reviews.length > 0 && (
                <Link href={`/review?document=${d.id}`} className="btn-secondary btn-sm self-start no-underline">
                  {d.reviews.length} item{d.reviews.length > 1 ? "s" : ""} in the Review Queue
                </Link>
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-head items-baseline">
              <h2 className="card-title">Document control</h2>
              <span className="text-xs text-muted">Select a value to see its source</span>
            </div>
            <div className="flex flex-col px-2 py-1.5">
              {control.map((f) => (
                <div key={f.label} className="grid grid-cols-[170px_minmax(0,1fr)_auto] items-center gap-3 p-2 text-[14px]">
                  <span className="text-muted">{f.label}</span>
                  <span className="font-medium" style={{ color: f.warn ? "#8A4B12" : "#1B2A22" }}>
                    {f.value}
                  </span>
                  <span />
                </div>
              ))}
              {d.dates.length > 0 && <div className="section-label px-2 pt-3 pb-1">Dates found</div>}
              {d.dates.map((x) => (
                <EvidenceRow
                  key={x.id}
                  label={`${humanize(x.date_type)} date${x.is_document_date ? "" : " (mentioned)"}`}
                  value={`${fmtDate(x.date_value)}${x.precision !== "day" ? ` (${x.precision})` : ""}`}
                  sub={`“${x.original_text}”${x.is_ambiguous ? " · ambiguous" : ""} · ${Math.round(x.confidence * 100)}%${x.extraction_method === "human" ? " · confirmed by a reviewer" : ""}`}
                  page={x.page_number}
                  warn={x.is_ambiguous || x.confidence < 0.8}
                  on={selected?.label === `date-${x.id}`}
                  onClick={() => select(x.page_number, x.evidence_snippet, `date-${x.id}`)}
                />
              ))}
              {d.attributes.length > 0 && <div className="section-label px-2 pt-3 pb-1">Key attributes</div>}
              {d.attributes.map((a) => (
                <EvidenceRow
                  key={a.id}
                  label={a.display_name}
                  value={valueText(a.value)}
                  sub={`${Math.round(a.confidence * 100)}%${a.extraction_method === "human" ? " · confirmed by a reviewer" : ""}`}
                  page={a.page_number}
                  warn={a.value === null || a.confidence < 0.8}
                  on={selected?.label === `attr-${a.id}`}
                  onClick={() => select(a.page_number, a.evidence_snippet, `attr-${a.id}`)}
                />
              ))}
            </div>
          </section>

          <section className="card">
            <div className="border-b border-line px-4 py-3">
              <h2 className="card-title">Findings</h2>
            </div>
            {[...openFindings, ...pastFindings].map((f) => {
              const p = findingPage(f.evidence);
              return (
                <div key={f.id} className="flex flex-col gap-2 border-b border-line-soft px-4 py-3 last:border-b-0" style={{ opacity: f.resolved ? 0.7 : 1 }}>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge status={f.severity} />
                    <Badge status={f.resolved ? "resolved" : "open"} />
                    <span className="text-xs text-muted">
                      Created {fmtDate(f.created_at)}
                      {f.resolved_at && ` · resolved ${fmtDate(f.resolved_at)}`}
                    </span>
                  </div>
                  <span className="font-medium">{f.rule_name}</span>
                  <span className="text-[13.5px] leading-normal text-muted-2">{f.message}</span>
                  <div className="flex gap-2">
                    {p && (
                      <button className="btn-primary btn-sm" onClick={() => select(p, findingSnippet(f.evidence), `finding-${f.id}`)}>
                        View evidence · p. {p}
                      </button>
                    )}
                    <Link href={`/findings?open=${f.id}`} className="btn-secondary btn-sm no-underline">
                      Finding details
                    </Link>
                  </div>
                </div>
              );
            })}
            {!d.findings.length && <div className="p-4 text-muted">No compliance findings for this document.</div>}
          </section>

          <section className="card flex flex-col gap-2.5 px-4 py-3">
            <div className="flex items-baseline justify-between">
              <h2 className="m-0 text-[14px] font-semibold">Extraction confidence</h2>
              {anyLow ? (
                <span className="text-xs font-medium text-review">◔ Below 80% — human review required</span>
              ) : (
                <span className="text-xs text-muted">All above review threshold</span>
              )}
            </div>
            {confidences
              .filter(([, v]) => v != null)
              .map(([label, v]) => {
                const pct = Math.round((v as number) * 100);
                return (
                  <div key={label} className="grid grid-cols-[120px_minmax(0,1fr)_44px] items-center gap-2.5 text-xs">
                    <span className="text-muted">{label}</span>
                    <div className="h-1 overflow-hidden rounded-sm bg-line-soft">
                      <div className="h-full" style={{ width: `${pct}%`, background: pct < 80 ? "#CDA54F" : "#7F8C6A" }} />
                    </div>
                    <span className="text-right font-mono" style={{ color: pct < 80 ? "#8A4B12" : "#4A554D" }}>
                      {pct}%
                    </span>
                  </div>
                );
              })}
          </section>

          {d.supersedes.length > 0 && (
            <section className="card">
              <div className="border-b border-line px-4 py-3">
                <h2 className="card-title">Earlier versions on file</h2>
              </div>
              {d.supersedes.map((o) => (
                <Link
                  key={o.id}
                  href={`/documents/${o.id}`}
                  className="flex justify-between gap-3 border-b border-line-soft px-4 py-2.5 text-ink no-underline last:border-b-0 hover:bg-hover-row hover:text-ink"
                >
                  <span>{o.label}</span>
                  <span className="font-mono text-xs text-muted">{o.governing_date ? fmtDate(o.governing_date) : "—"}</span>
                </Link>
              ))}
            </section>
          )}
        </div>

        <div className="sticky top-3">
          <SourceViewer
            fileId={d.vendor_file_id}
            filename={d.filename}
            from={d.start_page}
            to={d.end_page}
            page={shownPage}
            onPage={(n) => {
              setPage(n);
              if (selected && selected.page !== n) setSelected(null);
            }}
            highlight={selected?.page === shownPage ? selected.snippet : null}
            highlightLabel={selected?.page === shownPage && selected.snippet ? "Showing the evidence for the selected value" : null}
            onClearHighlight={() => setSelected(null)}
            heading={d.vendor_name}
          />
        </div>
      </div>
    </Page>
  );
}

function EvidenceRow({
  label,
  value,
  sub,
  page,
  warn,
  on,
  onClick,
}: {
  label: string;
  value: string;
  sub: string;
  page: number | null | undefined;
  warn?: boolean;
  on: boolean;
  onClick: () => void;
}) {
  const inner = (
    <>
      <span className="text-muted">{label}</span>
      <span className="flex min-w-0 flex-col">
        <span className="font-medium break-words" style={{ color: warn ? "#8A4B12" : "#1B2A22" }}>
          {value}
        </span>
        <span className="text-[12.5px] text-muted">{sub}</span>
      </span>
      {page ? <span className="rounded border border-line-chip px-1.5 py-px font-mono text-[12px] whitespace-nowrap text-forest">⌖ p. {page}</span> : <span />}
    </>
  );
  return page ? (
    <button
      onClick={onClick}
      className="grid cursor-pointer grid-cols-[170px_minmax(0,1fr)_auto] items-center gap-3 rounded-md border p-2 text-left text-[14px] text-ink hover:bg-sand-2"
      style={{ background: on ? "#F6EBCB" : "transparent", borderColor: on ? "#D9BC72" : "transparent" }}
    >
      {inner}
    </button>
  ) : (
    <div className="grid grid-cols-[170px_minmax(0,1fr)_auto] items-center gap-3 p-2 text-[14px]">{inner}</div>
  );
}
