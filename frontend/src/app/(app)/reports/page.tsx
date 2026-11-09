"use client";

import Link from "next/link";
import { useState } from "react";
import { docStatus, pagesText } from "@/components/doc-table";
import { findingPage, subjectName } from "@/components/findings";
import { Badge, ErrorNote } from "@/components/ui/badge";
import { Page, PageHeader } from "@/components/ui/page";
import { useToast } from "@/components/ui/toast";
import { useDocuments, useDocumentTypes, useFindings, useMe, useRules, useVendors, useVendorStats } from "@/lib/api/hooks";
import { fmtDate, fmtDateTime, shortName } from "@/lib/format";
import { badge } from "@/lib/status";

const REPORT_TYPES: [string, string, string][] = [
  ["vendor", "Vendor Documentation Health", "Status distribution per vendor"],
  ["component", "Component Documentation Summary", "All logical documents, with governing dates"],
  ["stale", "Stale Documents", "Documents beyond their configured review threshold"],
  ["approaching", "Documents Approaching Review", "Documents inside the warning window"],
  ["findings", "Open Findings", "Open findings with rule and evidence page"],
  ["audit", "Audit Preparation Summary", "Current, superseded and stale documents with evidence references"],
  ["rule", "Rule Impact Summary", "Open findings per active rule"],
];
const RANGE_OPTS = ["All dates", "Last 12 months", "Last 3 years", "Older than 3 years"];

type Cell = { text: string; mono?: boolean; status?: string; href?: string };
type Table = { head: string[]; rows: Cell[][]; summary: [string, number][] };

export default function ReportsPage() {
  const toast = useToast();
  const me = useMe();
  const rules = useRules();
  const vendors = useVendors();
  const types = useDocumentTypes();
  const stats = useVendorStats();
  const [report, setReport] = useState("stale");
  const [vendor, setVendor] = useState("All");
  const [type, setType] = useState("All");
  const [range, setRange] = useState("All dates");
  const [rule, setRule] = useState("All");
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const docs = useDocuments({ vendor_id: vendor, document_type: type }, !!generatedAt);
  const findings = useFindings({ status: "open", vendor_id: vendor, rule_code: rule }, !!generatedAt);
  const reset = (set: (v: string) => void) => (v: string) => {
    set(v);
    setGeneratedAt(null);
  };

  const def = REPORT_TYPES.find((r) => r[0] === report)!;
  const inRange = (iso: string | null | undefined) => {
    if (range === "All dates") return true;
    if (!iso) return false;
    // Measured from when the report was generated, so the report is reproducible.
    const years = (new Date(generatedAt ?? iso).getTime() - new Date(iso).getTime()) / (365.25 * 86_400_000);
    return range === "Last 12 months" ? years <= 1 : range === "Last 3 years" ? years <= 3 : years > 3;
  };

  function build(): Table | null {
    if (report === "vendor") {
      if (!stats.data || !vendors.data) return null;
      const rows = stats.data.filter((s) => vendor === "All" || s.vendor_id === vendor);
      return {
        head: ["Vendor", "Documents", "Current", "Approaching", "Stale", "Needs review", "Open findings", "Last upload"],
        rows: rows.map((s) => [
          { text: vendors.data.find((v) => v.id === s.vendor_id)?.name ?? "—", href: `/vendors/${s.vendor_id}` },
          { text: String(s.documents), mono: true },
          { text: String(s.current), mono: true },
          { text: String(s.approaching), mono: true },
          { text: String(s.stale), mono: true },
          { text: String(s.needs_review), mono: true },
          { text: String(s.open_findings), mono: true },
          { text: s.last_upload ? fmtDate(s.last_upload) : "—", mono: true },
        ]),
        summary: [
          ["Vendors", rows.length],
          ["Documents", rows.reduce((a, s) => a + s.documents, 0)],
          ["Stale", rows.reduce((a, s) => a + s.stale, 0)],
          ["Needs review", rows.reduce((a, s) => a + s.needs_review, 0)],
        ],
      };
    }
    if (report === "findings" || report === "rule") {
      if (!findings.data) return null;
      const fs = findings.data.filter((f) => inRange(f.governing_date ?? f.created_at));
      if (report === "rule") {
        const byRule = new Map<string, { name: string; ruleId: string; n: number; critical: number }>();
        for (const f of fs) {
          const e = byRule.get(f.rule_code) ?? { name: f.rule_name, ruleId: f.rule_id, n: 0, critical: 0 };
          e.n += 1;
          if (f.severity === "critical") e.critical += 1;
          byRule.set(f.rule_code, e);
        }
        const active = (rules.data ?? []).filter((r) => r.current.active && (rule === "All" || r.code === rule));
        return {
          head: ["Rule", "Code", "Version", "Open findings", "Critical"],
          rows: active.map((r) => {
            const e = byRule.get(r.code);
            return [
              { text: r.current.name, href: `/rules/${r.id}` },
              { text: r.code, mono: true },
              { text: `v${r.current.version}`, mono: true },
              { text: String(e?.n ?? 0), mono: true },
              { text: String(e?.critical ?? 0), mono: true },
            ];
          }),
          summary: [
            ["Active rules", active.length],
            ["Open findings", fs.length],
            ["Critical", fs.filter((f) => f.severity === "critical").length],
            ["Vendors", new Set(fs.map((f) => f.vendor_id)).size],
          ],
        };
      }
      return {
        head: ["Finding", "Vendor · Component", "About", "Severity", "Raised", "Evidence"],
        rows: fs.map((f) => {
          const p = findingPage(f.evidence);
          return [
            { text: `${f.rule_name}: ${f.message}`, href: `/findings?open=${f.id}` },
            { text: `${f.vendor_name ?? "—"} · ${f.component_name ?? "—"}` },
            { text: subjectName(f) },
            { text: badge(f.severity).label, status: f.severity },
            { text: fmtDate(f.created_at), mono: true },
            { text: p ? `p. ${p}` : "—", mono: true, href: f.document ? `/documents/${f.document.id}${p ? `?page=${p}` : ""}` : undefined },
          ];
        }),
        summary: [
          ["Findings", fs.length],
          ["Critical", fs.filter((f) => f.severity === "critical").length],
          ["Warning", fs.filter((f) => f.severity === "warning").length],
          ["Vendors", new Set(fs.map((f) => f.vendor_id)).size],
        ],
      };
    }
    if (!docs.data) return null;
    let ds = docs.data.filter((d) => inRange(d.governing_date));
    if (report === "stale") ds = ds.filter((d) => !d.superseded && d.compliance_status === "stale");
    else if (report === "approaching") ds = ds.filter((d) => !d.superseded && d.compliance_status === "approaching_review");
    else if (report === "component") ds = ds.filter((d) => !d.superseded);
    return {
      head: ["Document", "Vendor · Component", "Type", "Governing date", "Status", "Reason", "Evidence"],
      rows: ds.map((d) => [
        { text: d.label, mono: true, href: `/documents/${d.id}` },
        { text: `${d.vendor_name ?? "—"} · ${d.component_name ?? "—"}` },
        { text: d.document_type_label ?? "Unclassified" },
        { text: d.governing_date ? fmtDate(d.governing_date) : "Not determined", mono: true },
        { text: badge(docStatus(d)).label, status: docStatus(d) },
        { text: d.status_reason ?? "" },
        { text: `${d.filename} p. ${pagesText(d)}`, mono: true, href: `/vendor-files/${d.vendor_file_id}?page=${d.start_page}` },
      ]),
      summary: [
        ["Documents", ds.length],
        ["Vendors", new Set(ds.map((d) => d.vendor_id)).size],
        ["Stale", ds.filter((d) => !d.superseded && d.compliance_status === "stale").length],
        ["Superseded", ds.filter((d) => d.superseded).length],
      ],
    };
  }

  const table = generatedAt ? build() : null;
  const loading = !!generatedAt && !table;
  const vendorName = vendors.data?.find((v) => v.id === vendor)?.name;
  const typeName = types.data?.find((t) => t.name === type)?.display_name;
  const ruleName = rules.data?.find((r) => r.code === rule)?.current.name;
  const filterText = [vendorName, typeName, range !== "All dates" ? range : null, ruleName].filter(Boolean).join(" · ") || "No filters";

  function exportCsv() {
    if (!table) return;
    const lines = [table.head, ...table.rows.map((r) => r.map((c) => c.text))];
    const csv = lines.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${def[1].replace(/\s+/g, "_")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast(`Exported CSV — ${table.rows.length} rows.`);
  }

  const selects: [string, string, [string, string][], (v: string) => void][] = [
    ["Vendor", vendor, [["All", "All"], ...(vendors.data ?? []).map((v): [string, string] => [v.id, v.name])], reset(setVendor)],
    ["Document type", type, [["All", "All"], ...(types.data ?? []).map((t): [string, string] => [t.name, t.display_name])], reset(setType)],
    ["Date range", range, RANGE_OPTS.map((o): [string, string] => [o, o]), reset(setRange)],
    ["Compliance rule", rule, [["All", "All"], ...(rules.data ?? []).filter((r) => r.current.active).map((r): [string, string] => [r.code, r.current.name])], reset(setRule)],
  ];

  return (
    <Page>
      <PageHeader title="Reports" sub="Built from the documents and findings on file. Every row links to its source." />
      <div className="grid grid-cols-[minmax(240px,300px)_minmax(0,1fr)] items-start gap-4">
        <nav aria-label="Report types" className="card flex flex-col gap-0.5 p-1.5">
          {REPORT_TYPES.map(([k, t, d]) => {
            const on = k === report;
            return (
              <button
                key={k}
                aria-pressed={on}
                onClick={() => {
                  setReport(k);
                  setGeneratedAt(null);
                }}
                className="flex cursor-pointer flex-col gap-0.5 rounded-md border px-2.5 py-[9px] text-left text-ink hover:bg-sand-2"
                style={{ borderColor: on ? "#1E3B2F" : "transparent", background: on ? "#FFFDF9" : "transparent" }}
              >
                <span className="text-[14px] font-semibold">{t}</span>
                <span className="text-xs leading-[1.4] text-muted">{d}</span>
              </button>
            );
          })}
        </nav>
        <div className="flex min-w-0 flex-col gap-3.5">
          <section className="card flex flex-col gap-3 px-4 py-3.5">
            <div className="flex flex-col gap-0.5">
              <span className="text-[16px] font-semibold">{def[1]}</span>
              <span className="text-[13.5px] text-muted">{def[2]}</span>
            </div>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2.5">
              {selects.map(([label, value, opts, onChange]) => (
                <label key={label} className="flex flex-col gap-1 text-xs font-medium text-muted-2">
                  {label}
                  <select className="select text-[13.5px]" value={value} onChange={(e) => onChange(e.target.value)}>
                    {opts.map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="btn-primary px-4 py-2" onClick={() => setGeneratedAt(new Date().toISOString())}>
                Generate Report
              </button>
              {table && (
                <>
                  <button className="btn-secondary px-3.5 py-2 font-normal" onClick={() => window.print()}>
                    Export PDF
                  </button>
                  <button className="btn-secondary px-3.5 py-2 font-normal" onClick={exportCsv}>
                    Export CSV
                  </button>
                </>
              )}
            </div>
          </section>
          {(docs.isError || findings.isError) && <ErrorNote error={docs.error ?? findings.error} />}
          {!generatedAt && <div className="rounded-lg border border-dashed border-line-strong p-9 text-center text-muted">Choose filters and generate to preview the report.</div>}
          {loading && (
            <div className="card flex animate-pulse-soft flex-col gap-2.5 p-4">
              {[30, 90, 85, 88].map((w) => (
                <div key={w} className="skeleton-bar h-2.5" style={{ width: `${w}%` }} />
              ))}
            </div>
          )}
          {table && (
            <section className="overflow-hidden rounded-lg border border-line bg-white">
              <div className="flex flex-wrap justify-between gap-3 border-b border-line px-[18px] py-4">
                <div className="flex flex-col gap-0.5">
                  <span className="eyebrow">Attest · Compliance report</span>
                  <span className="text-base font-semibold">{def[1]}</span>
                  <span className="text-xs text-muted">
                    Generated {fmtDateTime(generatedAt)} by {shortName(me.data?.full_name ?? "")} · Filters: {filterText}
                  </span>
                </div>
              </div>
              <div className="grid grid-cols-4 border-b border-line-soft">
                {table.summary.map(([l, v]) => (
                  <div key={l} className="flex flex-col gap-0.5 border-r border-line-soft px-[18px] py-2.5 last:border-r-0">
                    <span className="text-xs text-muted">{l}</span>
                    <span className="font-mono text-lg font-semibold">{v}</span>
                  </div>
                ))}
              </div>
              {table.rows.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[800px] border-collapse">
                    <thead>
                      <tr>
                        {table.head.map((h) => (
                          <th key={h} className="th border-b-0 py-[7px]">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {table.rows.map((row, i) => (
                        <tr key={i}>
                          {row.map((c, j) => (
                            <td key={j} className={`border-t border-line-soft px-3 py-2 align-top ${c.mono ? "font-mono text-xs" : "text-[13.5px]"}`}>
                              {c.status ? (
                                <Badge status={c.status} />
                              ) : c.href ? (
                                <Link href={c.href} className="text-forest underline">
                                  {c.text}
                                </Link>
                              ) : (
                                c.text
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="p-8 text-center text-muted">Nothing matches these report filters.</div>
              )}
            </section>
          )}
        </div>
      </div>
    </Page>
  );
}
