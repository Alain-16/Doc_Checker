"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { docStatus } from "@/components/doc-table";
import { FindingDrawer, subjectName } from "@/components/findings";
import { Badge, EmptyState, ErrorNote } from "@/components/ui/badge";
import { FilterBar, Page, PageHeader } from "@/components/ui/page";
import type { Schemas } from "@/lib/api/client";
import { useFinding, useFindings, useVendors } from "@/lib/api/hooks";
import { fmtDate } from "@/lib/format";
import { badge } from "@/lib/status";

export default function FindingsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const openId = params.get("open");
  const f = {
    severity: params.get("severity") ?? "All",
    status: (params.get("status") ?? "open") as "open" | "resolved" | "all",
    vendor: params.get("vendor") ?? "All",
    rule: params.get("rule") ?? "All",
  };
  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null || value === "All") next.delete(key);
    else next.set(key, value);
    router.replace(`/findings${next.size ? `?${next}` : ""}`, { scroll: false });
  };

  const vendors = useVendors();
  const findings = useFindings({
    status: f.status,
    severity: f.severity === "All" ? undefined : (f.severity as Schemas["FindingSeverity"]),
    vendor_id: f.vendor,
    rule_code: f.rule,
  });
  // The open finding may be outside the current filter (e.g. a resolved one linked from Activity).
  const inList = findings.data?.find((x) => x.id === openId);
  const single = useFinding(openId && findings.isSuccess && !inList ? openId : null);
  const open = inList ?? single.data;
  const all = useFindings({ status: "all" });
  const ruleOpts = useMemo(() => {
    const m = new Map<string, string>();
    for (const x of all.data ?? []) m.set(x.rule_code, x.rule_name);
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [all.data]);

  const rows = findings.data ?? [];

  return (
    <Page max={1600}>
      <PageHeader title="Compliance findings" sub="Created by active rules. Each finding links to the rule and the source evidence; findings resolve themselves on re-evaluation." />
      <FilterBar>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Severity
          <select className="select" value={f.severity} onChange={(e) => set("severity", e.target.value)}>
            {["All", "critical", "warning", "info"].map((o) => (
              <option key={o} value={o}>
                {o === "All" ? "All" : badge(o).label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Status
          <select className="select" value={f.status} onChange={(e) => set("status", e.target.value === "open" ? null : e.target.value)}>
            <option value="open">Open</option>
            <option value="resolved">Resolved</option>
            <option value="all">All</option>
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Vendor
          <select className="select max-w-[200px]" value={f.vendor} onChange={(e) => set("vendor", e.target.value)}>
            <option value="All">All</option>
            {vendors.data?.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Rule
          <select className="select max-w-[240px]" value={f.rule} onChange={(e) => set("rule", e.target.value)}>
            <option value="All">All</option>
            {ruleOpts.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <span className="ml-auto text-xs text-muted">{findings.data ? `${rows.length} findings` : ""}</span>
      </FilterBar>
      {findings.isError && <ErrorNote error={findings.error} />}
      <section className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1100px] border-collapse">
            <thead>
              <tr>
                {["Severity", "Finding", "Vendor · Component", "About", "Rule", "Status", "Raised"].map((h) => (
                  <th key={h} className="th">
                    {h}
                  </th>
                ))}
                <th className="th">
                  <span className="sr-only">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {findings.isPending &&
                Array.from({ length: 6 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={8} className="td">
                      <div className="skeleton-bar h-2.5 w-3/4 animate-pulse-soft" />
                    </td>
                  </tr>
                ))}
              {rows.map((x) => {
                const ds = x.document ? badge(docStatus(x.document)) : null;
                return (
                  <tr key={x.id} className="tr-link" style={{ background: openId === x.id ? "#F6EFDF" : undefined }} onClick={() => set("open", x.id)}>
                    <td className="td">
                      <Badge status={x.severity} />
                    </td>
                    <td className="td max-w-[380px] leading-[1.4]">
                      <div className="font-medium">{x.rule_name}</div>
                      <div className="text-xs text-muted-2">{x.message}</div>
                    </td>
                    <td className="td">
                      <div>{x.vendor_name ?? "—"}</div>
                      <div className="text-xs text-muted">{x.component_name ?? "—"}</div>
                    </td>
                    <td className="td">
                      <div className="text-xs">{subjectName(x)}</div>
                      {ds ? (
                        <div className="flex items-center gap-1 text-[12.5px]" style={{ color: ds.fg }}>
                          <span aria-hidden="true">{ds.icon}</span>
                          {ds.label}
                        </div>
                      ) : (
                        <div className="text-[12.5px] text-muted">{x.subject === "component" ? "Component as a whole" : "Vendor as a whole"}</div>
                      )}
                    </td>
                    <td className="td font-mono text-[12.5px] text-muted">
                      {x.rule_code} v{x.rule_version}
                    </td>
                    <td className="td">
                      <Badge status={x.resolved ? "resolved" : "open"} />
                    </td>
                    <td className="td font-mono text-xs whitespace-nowrap">{fmtDate(x.created_at)}</td>
                    <td className="td text-right">
                      <button className="btn-secondary btn-sm">Details</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {findings.isSuccess && !rows.length && (
          <EmptyState title="No compliance findings require attention." text="No findings match the selected severity, status, vendor and rule." />
        )}
      </section>
      {open && <FindingDrawer finding={open} onClose={() => set("open", null)} />}
    </Page>
  );
}
