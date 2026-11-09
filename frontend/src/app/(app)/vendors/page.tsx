"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { EmptyState, ErrorNote } from "@/components/ui/badge";
import { Page, PageHeader } from "@/components/ui/page";
import { Segmented } from "@/components/ui/tabs";
import { useComponents, useIndustryProfile, useVendors, useVendorStats } from "@/lib/api/hooks";
import { fmtDate } from "@/lib/format";

const HEALTH_OPTS = ["All", "Has stale", "Needs review", "No open issues"] as const;
type Health = (typeof HEALTH_OPTS)[number];
type SortKey = "name" | "comps" | "docs" | "current" | "stale" | "review" | "findings" | "last";
const PAGE_SIZE = 8;

const COLS: [string, SortKey, "left" | "right"][] = [
  ["Vendor", "name", "left"],
  ["Components", "comps", "right"],
  ["Documents", "docs", "right"],
  ["Current", "current", "right"],
  ["Stale", "stale", "right"],
  ["Needs review", "review", "right"],
  ["Open findings", "findings", "right"],
  ["Last update", "last", "right"],
];

export default function VendorsPage() {
  const router = useRouter();
  const vendors = useVendors();
  const components = useComponents();
  const stats = useVendorStats();
  const profile = useIndustryProfile();
  const [query, setQuery] = useState("");
  const [health, setHealth] = useState<Health>("All");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "name", dir: 1 });
  const [page, setPage] = useState(1);

  const plural = profile.data?.vendor_label_plural ?? "Vendors";

  const rows = useMemo(() => {
    const byVendor = new Map((stats.data ?? []).map((x) => [x.vendor_id, x]));
    return (vendors.data ?? []).map((v) => {
      const s = byVendor.get(v.id);
      return {
        id: v.id,
        name: v.name,
        comps: s?.components ?? 0,
        docs: s?.documents ?? null,
        current: s?.current ?? null,
        stale: s?.stale ?? null,
        review: s?.needs_review ?? null,
        findings: s?.open_findings ?? null,
        last: s?.last_upload ?? null,
      };
    });
  }, [vendors.data, stats.data]);

  const filtered = useMemo(() => {
    let list = rows.filter((v) => v.name.toLowerCase().includes(query.toLowerCase()));
    if (health === "Has stale") list = list.filter((v) => (v.stale ?? 0) > 0);
    if (health === "Needs review") list = list.filter((v) => (v.review ?? 0) > 0);
    if (health === "No open issues") list = list.filter((v) => v.findings === 0);
    return [...list].sort((a, b) => {
      const x = a[sort.key];
      const y = b[sort.key];
      if (x == null) return 1;
      if (y == null) return -1;
      if (sort.key === "last") return (new Date(x as string).getTime() - new Date(y as string).getTime()) * sort.dir;
      return (typeof x === "string" ? x.localeCompare(y as string) : (x as number) - (y as number)) * sort.dir;
    });
  }, [rows, query, health, sort]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pg = Math.min(page, pages);
  const visible = filtered.slice((pg - 1) * PAGE_SIZE, pg * PAGE_SIZE);
  const num = (n: number | null) => (n == null ? "—" : n.toLocaleString("en-US"));

  return (
    <Page>
      <PageHeader
        title={plural}
        sub={vendors.data ? `${vendors.data.length} ${plural.toLowerCase()} · ${components.data?.length ?? "…"} components` : "Loading…"}
      />
      <div className="flex flex-wrap items-center gap-2.5">
        <input
          aria-label={`Search ${plural.toLowerCase()}`}
          placeholder={`Search ${plural.toLowerCase()}`}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
          className="input flex-[0_1_280px]"
        />
        <Segmented
          label="Filter by health"
          options={[...HEALTH_OPTS]}
          value={health}
          onChange={(h) => {
            setHealth(h);
            setPage(1);
          }}
        />
      </div>
      {vendors.isError && <ErrorNote error={vendors.error} />}
      <section className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] border-collapse">
            <thead>
              <tr>
                {COLS.map(([label, key, align]) => {
                  const on = sort.key === key;
                  return (
                    <th key={key} aria-sort={on ? (sort.dir > 0 ? "ascending" : "descending") : "none"} className="th p-0" style={{ textAlign: align }}>
                      <button
                        onClick={() => setSort((s) => ({ key, dir: s.key === key ? (-s.dir as 1 | -1) : key === "name" ? 1 : -1 }))}
                        className="w-full cursor-pointer border-none bg-transparent px-3 py-2 text-[12px] font-semibold tracking-[.05em] whitespace-nowrap text-th uppercase"
                        style={{ textAlign: align }}
                      >
                        {label} {on ? (sort.dir > 0 ? "↑" : "↓") : ""}
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {vendors.isPending &&
                Array.from({ length: 5 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={8} className="td">
                      <div className="skeleton-bar h-2.5 w-2/3 animate-pulse-soft" />
                    </td>
                  </tr>
                ))}
              {visible.map((v) => (
                <tr key={v.id} className="tr-link" onClick={() => router.push(`/vendors/${v.id}`)}>
                  <td className="td py-2.5">
                    <Link href={`/vendors/${v.id}`} onClick={(e) => e.stopPropagation()} className="font-semibold text-forest no-underline hover:underline">
                      {v.name}
                    </Link>
                  </td>
                  <td className="td py-2.5 text-right font-mono">{v.comps}</td>
                  <td className="td py-2.5 text-right font-mono">{num(v.docs)}</td>
                  <td className="td py-2.5 text-right font-mono text-ok">{num(v.current)}</td>
                  <td className="td py-2.5 text-right font-mono" style={{ color: (v.stale ?? 0) > 8 ? "#9A2B1E" : undefined, fontWeight: (v.stale ?? 0) > 8 ? 600 : 400 }}>
                    {num(v.stale)}
                  </td>
                  <td className="td py-2.5 text-right font-mono" style={{ color: (v.review ?? 0) > 0 ? "#8A4B12" : undefined }}>
                    {num(v.review)}
                  </td>
                  <td className="td py-2.5 text-right font-mono">{num(v.findings)}</td>
                  <td className="td py-2.5 text-right font-mono text-xs whitespace-nowrap">{v.last ? fmtDate(v.last) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {vendors.isSuccess && !filtered.length && (
          <EmptyState
            title={rows.length ? "No vendors match these filters." : "No vendors yet."}
            text={rows.length ? undefined : "Vendors are created automatically when an uploaded file is processed."}
          >
            {!rows.length && (
              <Link href="/upload" className="btn-primary no-underline hover:text-page">
                Upload Document
              </Link>
            )}
          </EmptyState>
        )}
        <div className="flex items-center justify-between border-t border-line-soft px-3.5 py-2.5 text-xs text-muted">
          <span>{filtered.length ? `Showing ${(pg - 1) * PAGE_SIZE + 1}–${Math.min(pg * PAGE_SIZE, filtered.length)} of ${filtered.length} vendors` : "0 vendors"}</span>
          <div className="flex gap-1.5">
            <button className="btn-secondary btn-sm font-normal" disabled={pg <= 1} onClick={() => setPage(pg - 1)}>
              Previous
            </button>
            <button className="btn-secondary btn-sm font-normal" disabled={pg >= pages} onClick={() => setPage(pg + 1)}>
              Next
            </button>
          </div>
        </div>
      </section>
    </Page>
  );
}
