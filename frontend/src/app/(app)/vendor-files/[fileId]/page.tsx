"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { docStatus, pagesText } from "@/components/doc-table";
import { ProcessingSteps } from "@/components/processing-steps";
import { useCrumbs } from "@/components/shell/crumbs";
import { SourceViewer } from "@/components/source-viewer";
import { Badge, ErrorNote } from "@/components/ui/badge";
import { Page, PageHeader } from "@/components/ui/page";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api/client";
import { useComponents, useDocuments, useFileStatus, useResumeFile, useReviewItems, useVendors } from "@/lib/api/hooks";

const TINTS = ["#E2E8DA", "#F1E8D3"];

/** One uploaded vendor file: processing status, then how it was split into logical documents. */
export default function VendorFilePage() {
  const { fileId } = useParams<{ fileId: string }>();
  const params = useSearchParams();
  const status = useFileStatus(fileId, true);
  const s = status.data;
  const done = s?.status === "completed";
  const documents = useDocuments({ vendor_file_id: fileId }, !!s);
  const reviews = useReviewItems({ status: "open", vendor_file_id: fileId });
  const resume = useResumeFile();
  const components = useComponents();
  const vendors = useVendors();
  const toast = useToast();
  const [page, setPage] = useState(Number(params.get("page")) || 1);
  useCrumbs([{ label: "Documents", href: "/documents" }, { label: s?.filename ?? "Vendor file" }]);

  if (status.isError) return <Page><ErrorNote error={status.error} /></Page>;
  if (!s) return <Page><div className="animate-pulse-soft text-muted">Loading file…</div></Page>;

  const docs = [...(documents.data ?? [])].sort((a, b) => a.start_page - b.start_page);
  const segIndex = (n: number) => docs.findIndex((d) => n >= d.start_page && n <= d.end_page);
  const current = docs[segIndex(page)];
  const scannedReviews = (reviews.data ?? []).filter((r) => r.item_kind === "page_text").length;
  const boundaryReviews = (reviews.data ?? []).filter((r) => r.item_kind === "segment_boundary").length;
  const found = (components.data ?? []).filter((c) => s.component_ids.includes(c.id));
  const statusKey = s.status === "completed" ? "complete" : s.status;

  return (
    <Page max={1600} tight>
      <PageHeader
        eyebrow="Original vendor file"
        title={<span className="font-mono text-[20px] break-all">{s.filename}</span>}
        sub={
          <span className="flex flex-wrap items-center gap-2">
            {s.page_count} pages <Badge status={statusKey} size="sm" />
            {found.map((c) => (
              <Link key={c.id} href={`/vendors/${c.vendor_id}?tab=components`} className="text-xs">
                {vendors.data?.find((v) => v.id === c.vendor_id)?.name} · {c.name}
              </Link>
            ))}
          </span>
        }
        actions={
          <>
            <a href={`/api/vendor-files/${fileId}/original`} className="btn-secondary no-underline">
              Download original
            </a>
            {s.status === "failed" && (
              <button
                className="btn-primary"
                disabled={resume.isPending}
                onClick={() =>
                  resume.mutate(fileId, {
                    onSuccess: () => toast("Processing queued again. Completed stages are skipped."),
                    onError: (e) => toast(errorMessage(e), "error"),
                  })
                }
              >
                Resume processing
              </button>
            )}
          </>
        }
      />

      {!done && (
        <section className="card grid grid-cols-[repeat(auto-fit,minmax(min(100%,320px),1fr))] gap-6 p-5">
          <div className="flex flex-col">
            <h2 className="mt-0 mb-3.5 text-[16px] font-semibold">Processing</h2>
            <ProcessingSteps stages={s.stages} status={s.status} pageCount={s.page_count} />
          </div>
          <div className="flex flex-col gap-3">
            {s.error && (
              <div role="alert" className="rounded-lg border border-[#E2B2A8] bg-[#FBF1EE] p-3.5 text-[13.5px] text-bad">
                <strong className="mb-1 block font-semibold">Processing stopped</strong>
                {s.error}
              </div>
            )}
            {(s.status === "queued" || s.status === "running") && (
              <div className="rounded-lg border border-dashed border-line-strong p-6 leading-normal text-muted">
                You can leave this page. Processing continues in the background; this page refreshes every 2 seconds.
              </div>
            )}
          </div>
        </section>
      )}

      {docs.length > 0 && (
        <>
          <div className="flex flex-wrap gap-4 text-xs text-muted-2">
            <span>
              <strong className="font-mono text-[16px] text-ink">{docs.length}</strong> logical documents
            </span>
            <span>
              <strong className="font-mono text-[16px] text-review">{boundaryReviews}</strong> boundary to review
            </span>
            <span>
              <strong className="font-mono text-[16px] text-ink">{scannedReviews}</strong> low-confidence pages
            </span>
          </div>
          <div className="card flex flex-col gap-2 px-3.5 py-3">
            <span className="text-xs text-muted">Page map — each band is one logical document</span>
            <div className="grid gap-0.5" style={{ gridTemplateColumns: `repeat(${Math.min(s.page_count, 60)}, minmax(0, 1fr))` }}>
              {Array.from({ length: s.page_count }, (_, i) => i + 1).map((n) => {
                const idx = segIndex(n);
                const inSel = idx >= 0 && docs[idx]?.id === current?.id;
                return (
                  <button
                    key={n}
                    onClick={() => setPage(n)}
                    aria-label={`Page ${n}`}
                    title={`Page ${n}${idx >= 0 ? ` · ${docs[idx]!.label}` : " · not in any document"}`}
                    className="flex h-[34px] cursor-pointer items-end justify-center border-none p-0 font-mono text-[9px] text-forest"
                    style={{
                      background: idx >= 0 ? TINTS[idx % 2] : "#ECE5D7",
                      outline: `2px solid ${n === page ? "#1E3B2F" : inSel ? "#7F8C6A" : "transparent"}`,
                      outlineOffset: -2,
                      opacity: inSel || !current ? 1 : 0.62,
                    }}
                  >
                    {n}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="grid grid-cols-[minmax(260px,340px)_minmax(0,1fr)] items-start gap-4">
            <nav aria-label="Document outline" className="card overflow-hidden">
              <div className="border-b border-line px-3.5 py-2.5 text-[14px] font-semibold">Document outline</div>
              <div className="flex max-h-[760px] flex-col overflow-auto p-1.5">
                {docs.map((d, i) => {
                  const on = d.id === current?.id;
                  return (
                    <button
                      key={d.id}
                      onClick={() => setPage(d.start_page)}
                      className="grid cursor-pointer grid-cols-[6px_minmax(0,1fr)] gap-2.5 rounded-md border px-2.5 py-[9px] text-left text-ink hover:bg-sand-2"
                      style={{ borderColor: on ? "#1E3B2F" : "transparent", background: on ? "#FFFDF9" : "transparent" }}
                    >
                      <span className="rounded-sm border border-[#CFC7B4]" style={{ background: TINTS[i % 2] }} />
                      <span className="flex min-w-0 flex-col gap-[3px]">
                        <span className="flex justify-between gap-2">
                          <span className="font-mono text-xs font-medium">Pages {pagesText(d)}</span>
                          <span className="text-[12px] text-muted">{d.end_page - d.start_page + 1} pp</span>
                        </span>
                        <span className="text-[14px] font-medium">{d.document_type_label ?? "Unclassified"}</span>
                        <span className="truncate text-xs text-muted">{d.title ?? d.label}</span>
                        <Badge status={docStatus(d)} size="sm" />
                      </span>
                    </button>
                  );
                })}
              </div>
            </nav>
            <div className="flex min-w-0 flex-col gap-2">
              {current && (
                <div className="card flex flex-wrap items-center gap-2.5 px-3 py-2.5">
                  <div className="flex min-w-[200px] flex-1 flex-col gap-0.5">
                    <span className="font-semibold">{current.title ?? current.label}</span>
                    <span className="text-xs text-muted">
                      Pages {pagesText(current)} · {current.document_type_label ?? "Unclassified"}
                    </span>
                  </div>
                  <Link href={`/documents/${current.id}?page=${page}`} className="btn-primary btn-sm no-underline hover:text-page">
                    Open document
                  </Link>
                </div>
              )}
              <SourceViewer fileId={fileId} filename={s.filename} from={1} to={s.page_count} page={page} onPage={setPage} heading={current?.vendor_name} />
            </div>
          </div>
        </>
      )}
      {done && documents.isSuccess && !docs.length && <div className="card p-4 text-muted">No logical documents were found in this file.</div>}
    </Page>
  );
}
