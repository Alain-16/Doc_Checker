"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { SinglePage } from "@/components/source-viewer";
import { Badge, EmptyState, ErrorNote } from "@/components/ui/badge";
import { ReasonDialog } from "@/components/ui/dialog";
import { FilterBar, Page } from "@/components/ui/page";
import { Segmented } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import type { Schemas } from "@/lib/api/client";
import { useComponents, useDocumentTypes, usePages, useResolveReview, useReviewItem, useReviewItems, useVendors } from "@/lib/api/hooks";
import { fmtDateTime, humanize } from "@/lib/format";

type Item = Schemas["ReviewItemOut"];
type Resolution = Schemas["ReviewResolution"];

const RESOLUTION_STATUS: Record<string, string> = { confirmed: "confirmed", corrected: "corrected", not_applicable: "na" };
const KIND_TITLE: Record<string, string> = {
  page_text: "Page text uncertain",
  segment_boundary: "Segment boundary uncertain",
  document_type: "Document type uncertain",
  date: "Date extraction uncertain",
  attribute_value: "Key attribute uncertain",
  vendor_identification: "Vendor or component uncertain",
  compliance_status: "Compliance status uncertain",
};

export default function ReviewQueuePage() {
  const router = useRouter();
  const params = useSearchParams();
  const state = (params.get("status") ?? "open") as "open" | "resolved";
  const documentId = params.get("document") ?? undefined;
  const vendorId = params.get("vendor") ?? undefined;
  const items = useReviewItems({ status: state, document_id: documentId, vendor_id: vendorId });
  const list = items.data ?? [];
  // The unfiltered list (same status) feeds the filter options, with counts.
  const everything = useReviewItems({ status: state });
  const vendorOptions = countBy(everything.data ?? [], (i) => i.document?.vendor_id ?? "none", (i) => i.document?.vendor_name ?? "Vendor not identified");
  const documentOptions = countBy(
    (everything.data ?? []).filter((i) => !vendorId || (i.document?.vendor_id ?? "none") === vendorId),
    (i) => i.document?.id ?? "none",
    (i) => (i.document ? `${i.document.label} · p. ${i.document.start_page}–${i.document.end_page}` : "No document"),
  );
  const groups = groupByDocument(list);
  const ordered = groups.flatMap((g) => g.items); // the order shown on screen
  const selectedId = params.get("item");
  // A linked item (e.g. from Activity) may not be in this list: fetch it on its own.
  const inList = list.find((i) => i.id === selectedId);
  const single = useReviewItem(selectedId && items.isSuccess && !inList ? selectedId : null);
  const item = inList ?? single.data ?? ordered[0];
  const [deciding, setDeciding] = useState<Resolution | null>(null);

  const setParam = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    router.replace(`/review${next.size ? `?${next}` : ""}`, { scroll: false });
  };

  return (
    <Page max={1680} tight>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="m-0 text-[24px] font-semibold">Review queue</h1>
          <p className="m-0 text-muted">Uncertain results held for a human decision. Every decision is electronically signed; affected documents are re-evaluated at once.</p>
        </div>
        <div className="flex items-center gap-2">
          <Segmented label="Show" options={["open", "resolved"]} value={state} onChange={(s) => setParam({ status: s === "open" ? null : s, item: null })} />
          {state === "open" && items.data && (
            <span className="rounded border border-[#DDBF9C] bg-[#F4E6D6] px-2.5 py-1 font-mono text-xs text-review">{list.length} pending</span>
          )}
        </div>
      </div>
      <FilterBar>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Vendor
          <select
            className="select max-w-[260px]"
            value={vendorId ?? ""}
            onChange={(e) => setParam({ vendor: e.target.value || null, document: null, item: null })}
          >
            <option value="">All vendors ({everything.data?.length ?? "…"})</option>
            {vendorOptions.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label} ({o.count})
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Document
          <select className="select max-w-[360px]" value={documentId ?? ""} onChange={(e) => setParam({ document: e.target.value || null, item: null })}>
            <option value="">All documents</option>
            {documentOptions.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label} ({o.count})
              </option>
            ))}
          </select>
        </label>
        {(vendorId || documentId) && (
          <button className="btn-link" onClick={() => setParam({ vendor: null, document: null, item: null })}>
            Clear filters
          </button>
        )}
        <span className="ml-auto text-xs text-muted">{items.data ? `${list.length} items in ${groups.length} documents` : ""}</span>
      </FilterBar>
      {items.isError && <ErrorNote error={items.error} />}
      {items.isPending && <div className="animate-pulse-soft text-muted">Loading review queue…</div>}
      {items.isSuccess && !list.length && !item && (
        <div className="card">
          <EmptyState
            title={state === "open" ? "✓ Nothing waiting for review." : "No decisions recorded yet."}
            text={state === "open" ? "Uncertain results from new uploads will appear here." : undefined}
          />
        </div>
      )}
      {item && (
        <div className="flex flex-wrap items-start gap-3.5">
          <nav aria-label="Review items" className="card flex max-h-[calc(100vh-200px)] max-w-full flex-[1_1_260px] flex-col gap-0.5 overflow-auto p-1.5">
            {groups.map((g) => (
              <div key={g.key} className="flex flex-col gap-0.5">
                <div className="sticky top-0 z-[1] flex flex-col border-b border-line-soft bg-paper px-2.5 pt-2 pb-1.5">
                  <span className="text-[12px] font-semibold tracking-[.04em] text-muted-2 uppercase">{g.vendor}</span>
                  <span className="flex justify-between gap-2 text-xs">
                    {g.documentId ? (
                      <Link href={`/documents/${g.documentId}`} className="truncate font-medium">
                        {g.label}
                      </Link>
                    ) : (
                      <span className="truncate font-medium">{g.label}</span>
                    )}
                    <span className="shrink-0 font-mono text-muted">{g.items.length}</span>
                  </span>
                </div>
                {g.items.map((r) => {
              const on = r.id === item.id;
              return (
                <button
                  key={r.id}
                  onClick={() => setParam({ item: r.id })}
                  className="flex cursor-pointer flex-col gap-1 rounded-md border px-2.5 py-[9px] text-left text-ink hover:bg-sand-2"
                  style={{ borderColor: on ? "#1E3B2F" : "transparent", background: on ? "#FFFDF9" : "transparent" }}
                >
                  <span className="flex items-center justify-between gap-1.5">
                    <span className="text-[14px] font-semibold">{KIND_TITLE[r.item_kind] ?? humanize(r.item_kind)}</span>
                    {r.confidence != null && <span className="font-mono text-[12px] text-review">{Math.round(r.confidence * 100)}%</span>}
                  </span>
                  <span className="truncate text-xs text-muted">
                    {r.field}
                    {r.page_number ? ` · p. ${r.page_number}` : ""}
                  </span>
                  <Badge status={r.resolution ? RESOLUTION_STATUS[r.resolution] : "pending"} size="sm" />
                </button>
              );
                })}
              </div>
            ))}
          </nav>

          <section aria-label="Source page" className="min-w-0 flex-[3_1_380px] overflow-hidden rounded-lg border border-viewer-line bg-viewer">
            <div className="flex items-center gap-2.5 border-b border-line bg-paper px-3 py-[9px]">
              <span className="font-semibold">Source evidence</span>
              <span className="flex-1 truncate font-mono text-[12.5px] text-muted">
                {item.page_number ? `Page ${item.page_number} of ` : ""}
                {item.filename}
              </span>
              {item.document_id ? (
                <Link href={`/documents/${item.document_id}${item.page_number ? `?page=${item.page_number}` : ""}`} className="text-xs whitespace-nowrap text-forest underline">
                  Open document
                </Link>
              ) : (
                <Link href={`/vendor-files/${item.vendor_file_id}${item.page_number ? `?page=${item.page_number}` : ""}`} className="text-xs whitespace-nowrap text-forest underline">
                  Open file
                </Link>
              )}
            </div>
            <div className="flex justify-center p-[18px]">
              <div className="w-full max-w-[540px]">
                {item.page_number ? (
                  <SinglePage fileId={item.vendor_file_id} page={item.page_number} highlight={item.highlight} heading={item.document?.vendor_name} size="lg" />
                ) : (
                  <div className="p-6 text-center text-muted">This item isn&apos;t tied to one page.</div>
                )}
              </div>
            </div>
          </section>

          <section aria-label="Decision" className="flex min-w-0 flex-[2_1_300px] flex-col gap-3">
            <div className="card flex flex-col gap-3.5 p-4">
              <div className="flex flex-col gap-0.5 rounded-md border border-line-soft bg-subtle px-3 py-2 text-xs">
                <span className="text-muted">Working on</span>
                <span className="font-semibold text-ink">{item.document?.vendor_name ?? "Vendor not identified"}</span>
                <span>
                  {item.document ? (
                    <Link href={`/documents/${item.document.id}`}>{item.document.label}</Link>
                  ) : (
                    "No document"
                  )}
                  {item.document?.component_name ? ` · ${item.document.component_name}` : ""}
                </span>
                <span className="font-mono text-[12px] text-muted">
                  {item.filename}
                  {item.page_number ? ` · page ${item.page_number}` : ""}
                </span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-[12px] font-semibold tracking-[.06em] text-review uppercase">What needs review</span>
                <h2 className="m-0 text-[18px] font-semibold">{KIND_TITLE[item.item_kind] ?? humanize(item.item_kind)}</h2>
                <p className="m-0 text-[13.5px] leading-normal text-muted-2">{item.reason}</p>
              </div>
              <div className="flex flex-col gap-2 rounded-md border border-line bg-subtle p-3">
                <div className="flex justify-between gap-2 text-xs text-muted">
                  <span>Detected field</span>
                  <span className="truncate">{item.document?.label ?? item.filename}</span>
                </div>
                <span className="font-semibold">{item.field}</span>
                <div className="flex items-baseline justify-between gap-2.5">
                  <span className="text-xs text-muted">System value</span>
                  <span className={`text-right font-medium break-words ${item.item_kind === "page_text" ? "max-h-40 overflow-auto font-mono text-xs whitespace-pre-wrap" : "font-mono text-base"}`}>
                    {item.value}
                  </span>
                </div>
                {item.confidence != null && (
                  <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 text-xs">
                    <span className="text-muted">Confidence</span>
                    <div className="h-1 overflow-hidden rounded-sm bg-line-soft">
                      <div className="h-full bg-[#CDA54F]" style={{ width: `${Math.round(item.confidence * 100)}%` }} />
                    </div>
                    <span className="font-mono font-semibold text-review">◔ {Math.round(item.confidence * 100)}%</span>
                  </div>
                )}
                {item.detail && <span className="text-xs break-words text-muted-2">{item.detail}</span>}
              </div>

              {item.status === "resolved" ? (
                <div className="flex flex-col gap-2">
                  <Badge status={RESOLUTION_STATUS[item.resolution ?? ""] ?? "resolved"} />
                  <span className="text-[13.5px] text-muted-2">
                    Signed by {item.resolved_by ?? "—"} · {fmtDateTime(item.resolved_at)}
                  </span>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-2">
                  <button className="btn-primary px-2 py-[9px]" onClick={() => setDeciding("confirmed")}>
                    ✓ Confirm
                  </button>
                  <button
                    className="btn-secondary px-2 py-[9px]"
                    disabled={!item.correctable}
                    title={item.correctable ? undefined : "This kind of item can only be confirmed or set aside here."}
                    onClick={() => setDeciding("corrected")}
                  >
                    ✎ Correct
                  </button>
                  <button className="btn-secondary px-2 py-[9px]" onClick={() => setDeciding("not_applicable")}>
                    Not applicable
                  </button>
                </div>
              )}
            </div>
            <div className="card flex flex-col gap-2 px-4 py-3">
              <span className="section-label">History</span>
              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2.5 gap-y-0.5 border-t border-line-faint py-1.5 text-[13.5px]">
                <span>Routed to review: {item.reason}</span>
                <span className="font-mono text-[12.5px] whitespace-nowrap text-muted">{fmtDateTime(item.created_at)}</span>
                <span className="text-xs text-muted">System</span>
              </div>
              {item.resolved_at && (
                <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2.5 gap-y-0.5 border-t border-line-faint py-1.5 text-[13.5px]">
                  <span>{humanize(item.resolution)}</span>
                  <span className="font-mono text-[12.5px] whitespace-nowrap text-muted">{fmtDateTime(item.resolved_at)}</span>
                  <span className="text-xs text-muted">{item.resolved_by}</span>
                </div>
              )}
            </div>
          </section>
        </div>
      )}
      {deciding && item && (
        <DecisionDialog
          item={item}
          resolution={deciding}
          onClose={() => setDeciding(null)}
          onDone={() => {
            const next = ordered.find((r, i) => i > ordered.indexOf(item));
            setParam({ item: next?.id ?? null });
          }}
        />
      )}
    </Page>
  );
}

function DecisionDialog({ item, resolution, onClose, onDone }: { item: Item; resolution: Resolution; onClose: () => void; onDone: () => void }) {
  const resolve = useResolveReview();
  const toast = useToast();
  const types = useDocumentTypes();
  const vendors = useVendors();
  const [value, setValue] = useState(item.item_kind === "date" || item.item_kind === "attribute_value" ? (item.value === "Not stated" ? "" : item.value.split(" (")[0]!) : "");
  const [docType, setDocType] = useState(item.document?.document_type ?? "");
  const NEW_TYPE = "__new__";
  const [newType, setNewType] = useState("");
  const [vendorId, setVendorId] = useState(item.document?.vendor_id ?? "");
  const [componentId, setComponentId] = useState(item.document?.component_id ?? "");
  const components = useComponents(vendorId || undefined);
  const page = usePages(item.item_kind === "page_text" && resolution === "corrected" ? item.vendor_file_id : undefined, item.page_number ?? 1, item.page_number ?? 1);
  const [pageText, setPageText] = useState<string | null>(null);
  const text = pageText ?? page.data?.[0]?.text ?? "";
  const correcting = resolution === "corrected";

  const title = resolution === "confirmed" ? "Confirm the system value?" : resolution === "corrected" ? `Correct ${item.field}` : "Mark as not applicable?";
  const intro = (
    <div className="flex flex-col gap-3">
      <span>
        {resolution === "confirmed" && <>You confirm “{item.value.slice(0, 120)}” is right as read.</>}
        {resolution === "not_applicable" && <>The item is set aside; the value stays as it is.</>}
        {correcting && <>The corrected value replaces the system&apos;s; the old one stays in the audit trail.</>}
      </span>
      {correcting && (item.item_kind === "date" || item.item_kind === "attribute_value") && (
        <label className="field-label">
          {item.correction_hint ?? "Correct value"}
          {item.item_kind === "date" ? (
            <input className="input font-mono font-normal" type="date" value={value} onChange={(e) => setValue(e.target.value)} />
          ) : (
            <input className="input font-mono font-normal" value={value} onChange={(e) => setValue(e.target.value)} />
          )}
        </label>
      )}
      {correcting && item.item_kind === "document_type" && (
        <>
          <label className="field-label">
            Document type
            <select className="select text-[14px]" value={docType} onChange={(e) => setDocType(e.target.value)}>
              <option value="">Choose…</option>
              {types.data
                ?.filter((t) => t.active)
                .map((t) => (
                  <option key={t.id} value={t.name}>
                    {t.display_name}
                  </option>
                ))}
              <option value={NEW_TYPE}>Not in the list — type a new type…</option>
            </select>
          </label>
          {docType === NEW_TYPE && (
            <label className="field-label">
              New document type
              <input
                className="input font-normal"
                value={newType}
                onChange={(e) => setNewType(e.target.value)}
                placeholder="e.g. Safety Data Sheet"
                maxLength={120}
                autoFocus
              />
              <span className="font-normal text-muted">
                If it matches an existing or retired type, that one is reused. A new type is offered to the classifier for future documents.
              </span>
            </label>
          )}
        </>
      )}
      {correcting && item.item_kind === "vendor_identification" && (
        <>
          <label className="field-label">
            Vendor
            <select
              className="select text-[14px]"
              value={vendorId}
              onChange={(e) => {
                setVendorId(e.target.value);
                setComponentId("");
              }}
            >
              <option value="">Choose…</option>
              {vendors.data?.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field-label">
            Component (optional for company-level documents)
            <select className="select text-[14px]" value={componentId} onChange={(e) => setComponentId(e.target.value)} disabled={!vendorId}>
              <option value="">None</option>
              {components.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
      {correcting && item.item_kind === "page_text" && (
        <label className="field-label">
          Page {item.page_number} text
          <textarea className="input min-h-[220px] font-mono text-xs font-normal" value={text} onChange={(e) => setPageText(e.target.value)} />
        </label>
      )}
    </div>
  );

  return (
    <ReasonDialog
      title={title}
      intro={intro}
      confirmLabel={resolution === "corrected" ? "Sign correction" : resolution === "confirmed" ? "Sign confirmation" : "Sign decision"}
      sign
      onClose={onClose}
      onSubmit={async ({ reason, password }) => {
        const out = await resolve.mutateAsync({
          id: item.id,
          body: {
            resolution,
            reason,
            password,
            value: correcting ? (item.item_kind === "page_text" ? text : value) : null,
            document_type: correcting && item.item_kind === "document_type" && docType !== NEW_TYPE ? docType || null : null,
            new_document_type: correcting && item.item_kind === "document_type" && docType === NEW_TYPE ? newType.trim() || null : null,
            vendor_id: correcting && item.item_kind === "vendor_identification" ? vendorId || null : null,
            component_id: correcting && item.item_kind === "vendor_identification" ? componentId || null : null,
          },
        });
        toast(
          `Decision signed${item.item_kind === "document_type" && correcting ? ` — type set to ${out.item.value}` : ""}. ${out.documents_reevaluated} documents re-evaluated.`,
        );
        onDone();
      }}
    />
  );
}

type Option = { key: string; label: string; count: number };

/** Distinct values with how many items each has, most items first. */
function countBy(items: Item[], key: (i: Item) => string, label: (i: Item) => string): Option[] {
  const map = new Map<string, Option>();
  for (const i of items) {
    const k = key(i);
    const o = map.get(k) ?? { key: k, label: label(i), count: 0 };
    o.count += 1;
    map.set(k, o);
  }
  return [...map.values()].filter((o) => o.key !== "none").sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

/** Items grouped under their document (vendor + label), in queue order of each group's first item. */
function groupByDocument(items: Item[]) {
  const groups: { key: string; documentId: string | null; vendor: string; label: string; items: Item[] }[] = [];
  const byKey = new Map<string, (typeof groups)[number]>();
  for (const i of items) {
    const k = i.document?.id ?? `file-${i.vendor_file_id}`;
    let g = byKey.get(k);
    if (!g) {
      g = {
        key: k,
        documentId: i.document?.id ?? null,
        vendor: i.document?.vendor_name ?? "Vendor not identified",
        label: i.document ? `${i.document.label} · p. ${i.document.start_page}–${i.document.end_page}` : i.filename,
        items: [],
      };
      byKey.set(k, g);
      groups.push(g);
    }
    g.items.push(i);
  }
  return groups;
}
