"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { DocRows } from "@/components/doc-table";
import { EmptyState, ErrorNote } from "@/components/ui/badge";
import { FilterBar, Page, PageHeader } from "@/components/ui/page";
import type { Schemas } from "@/lib/api/client";
import { useComponents, useDocuments, useDocumentTypes, useVendors } from "@/lib/api/hooks";

const STATUS_OPTS: [string, string][] = [
  ["All", "Status: All"],
  ["current", "Current"],
  ["approaching_review", "Approaching Review"],
  ["stale", "Stale"],
  ["needs_review", "Needs Review"],
  ["superseded", "Superseded"],
];
const DATE_OPTS = ["All", "Before 2020", "2020–2023", "2024 or later", "Not determined"];
const CONF_OPTS = ["All", "Below 80%", "80% and above"];

/** Filters live in the URL so Overview links ("?status=stale") and the back button work. */
export default function DocumentsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const f = {
    q: params.get("q") ?? "",
    vendor: params.get("vendor") ?? "All",
    comp: params.get("component") ?? "All",
    type: params.get("type") ?? "All",
    status: params.get("status") ?? "All",
    date: params.get("date") ?? "All",
    conf: params.get("confidence") ?? "All",
  };
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (!value || value === "All") next.delete(key);
    else next.set(key, value);
    if (key === "vendor") next.delete("component");
    router.replace(`/documents${next.size ? `?${next}` : ""}`, { scroll: false });
  };

  const vendors = useVendors();
  const components = useComponents(f.vendor === "All" ? undefined : f.vendor);
  const types = useDocumentTypes();
  // Server-side filters; date range, confidence and "superseded" are applied here.
  const docs = useDocuments({
    vendor_id: f.vendor,
    component_id: f.comp,
    document_type: f.type,
    status: f.status !== "All" && f.status !== "superseded" ? (f.status as Schemas["ComplianceStatus"]) : undefined,
    q: f.q.trim() || undefined,
  });

  const rows = (docs.data ?? []).filter((d) => {
      const y = d.governing_date ? Number(d.governing_date.slice(0, 4)) : null;
      const conf = d.classification_confidence;
      return (
        (f.status !== "superseded" || d.superseded) &&
        (f.conf === "All" || (conf != null && (f.conf === "Below 80%" ? conf < 0.8 : conf >= 0.8))) &&
        (f.date === "All" ||
          (f.date === "Not determined" ? !y : f.date === "Before 2020" ? !!y && y < 2020 : f.date === "2020–2023" ? !!y && y >= 2020 && y <= 2023 : !!y && y >= 2024))
      );
  });

  const active = !!f.q || [f.vendor, f.comp, f.type, f.status, f.date, f.conf].some((x) => x !== "All");

  return (
    <Page max={1600}>
      <PageHeader
        title="Documents"
        sub={docs.data ? `Logical documents segmented from vendor files · ${rows.length} documents shown` : "Logical documents segmented from vendor files"}
        actions={
          <Link href="/upload" className="btn-primary no-underline hover:text-page">
            Upload Document
          </Link>
        }
      />
      <FilterBar>
        <input
          aria-label="Search documents"
          placeholder="Number, title, vendor, component, file…"
          value={f.q}
          onChange={(e) => set("q", e.target.value)}
          className="flex-[1_1_220px] rounded-md border border-line-strong bg-input px-2.5 py-1.5 text-[14px]"
        />
        <select aria-label="Vendor" className="select max-w-[180px]" value={f.vendor} onChange={(e) => set("vendor", e.target.value)}>
          <option value="All">Vendor: All</option>
          {vendors.data?.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
        <select aria-label="Component" className="select max-w-[170px]" value={f.comp} onChange={(e) => set("component", e.target.value)}>
          <option value="All">Component: All</option>
          {components.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select aria-label="Document type" className="select max-w-[170px]" value={f.type} onChange={(e) => set("type", e.target.value)}>
          <option value="All">Document type: All</option>
          {types.data?.map((t) => (
            <option key={t.id} value={t.name}>
              {t.display_name}
            </option>
          ))}
        </select>
        <select aria-label="Status" className="select" value={f.status} onChange={(e) => set("status", e.target.value)}>
          {STATUS_OPTS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <select aria-label="Governing date range" className="select" value={f.date} onChange={(e) => set("date", e.target.value)}>
          {DATE_OPTS.map((o) => (
            <option key={o} value={o}>
              {o === "All" ? "Governing date: All" : o}
            </option>
          ))}
        </select>
        <select aria-label="Confidence" className="select" value={f.conf} onChange={(e) => set("confidence", e.target.value)}>
          {CONF_OPTS.map((o) => (
            <option key={o} value={o}>
              {o === "All" ? "Confidence: All" : o}
            </option>
          ))}
        </select>
        {active && (
          <button className="btn-link" onClick={() => router.replace("/documents", { scroll: false })}>
            Clear filters
          </button>
        )}
      </FilterBar>
      {docs.isError && <ErrorNote error={docs.error} />}
      <section className="card overflow-hidden">
        <div className="overflow-x-auto">
          {docs.isPending ? (
            <div className="flex animate-pulse-soft flex-col gap-3 p-4">
              {Array.from({ length: 8 }, (_, i) => (
                <div key={i} className="skeleton-bar h-2.5" style={{ width: `${70 + ((i * 7) % 25)}%` }} />
              ))}
            </div>
          ) : (
            rows.length > 0 && <DocRows docs={rows} variant="full" />
          )}
        </div>
        {docs.isSuccess && !rows.length && (
          <EmptyState
            title={active ? "No documents match these filters." : "No documents yet."}
            text={active ? "Try a different status or date range, or clear all filters." : "Upload a vendor file: it is split into logical documents automatically."}
          >
            {active ? (
              <button className="btn-secondary btn-sm" onClick={() => router.replace("/documents", { scroll: false })}>
                Clear filters
              </button>
            ) : (
              <Link href="/upload" className="btn-primary btn-sm no-underline hover:text-page">
                Upload Document
              </Link>
            )}
          </EmptyState>
        )}
      </section>
    </Page>
  );
}
