"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { docStatus } from "@/components/doc-table";
import { useComponents, useDocuments, useFindings, useRules, useVendors } from "@/lib/api/hooks";

type Result = { kind: string; title: string; sub: string; status?: string; href: string };

/** Header search across vendors, components and rules (live) plus sample documents and findings. */
export function GlobalSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const vendors = useVendors();
  const components = useComponents();
  const rules = useRules();
  const term = q.trim().toLowerCase();
  // Documents are searched on the server; open findings are few enough to filter here.
  const documents = useDocuments({ q: term }, open && term.length >= 2);
  const findings = useFindings({ status: "open" }, open && term.length >= 2);

  const results = useMemo<Result[]>(() => {
    if (term.length < 2) return [];
    const out: Result[] = [];
    const vendorName = new Map((vendors.data ?? []).map((v) => [v.id, v.name]));
    for (const v of vendors.data ?? []) {
      if ([v.name, ...v.aliases].some((n) => n.toLowerCase().includes(term))) {
        out.push({ kind: "Vendor", title: v.name, sub: `${(components.data ?? []).filter((c) => c.vendor_id === v.id).length} components`, href: `/vendors/${v.id}` });
      }
    }
    for (const c of components.data ?? []) {
      const hay = [c.name, c.vendor_part_number, c.internal_part_number, ...c.aliases].filter(Boolean).join(" ").toLowerCase();
      if (hay.includes(term)) {
        out.push({ kind: "Component", title: c.name, sub: vendorName.get(c.vendor_id) ?? "", href: `/vendors/${c.vendor_id}?tab=components` });
      }
    }
    for (const d of (documents.data ?? []).slice(0, 6)) {
      out.push({
        kind: "Document",
        title: d.title || d.label,
        sub: [d.label, d.vendor_name, d.component_name].filter(Boolean).join(" · "),
        status: docStatus(d),
        href: `/documents/${d.id}`,
      });
    }
    for (const f of findings.data ?? []) {
      if (`${f.rule_name} ${f.message} ${f.document?.label ?? ""}`.toLowerCase().includes(term)) {
        out.push({ kind: "Finding", title: f.rule_name, sub: `${f.message} · ${f.vendor_name ?? ""}`, status: f.severity, href: `/findings?open=${f.id}` });
      }
    }
    for (const r of rules.data ?? []) {
      const name = r.current.name;
      if (`${name} ${r.code} ${r.document_type ?? ""}`.toLowerCase().includes(term)) {
        out.push({ kind: "Rule", title: name, sub: `${r.document_type ?? "All document types"} · v${r.current.version}`, status: r.current.active ? "active" : "disabled", href: `/rules/${r.id}` });
      }
    }
    return out.slice(0, 10);
  }, [term, vendors.data, components.data, rules.data, documents.data, findings.data]);

  function go(href: string) {
    setOpen(false);
    setQ("");
    router.push(href);
  }

  return (
    <>
      <div className="relative ml-auto min-w-[180px] flex-[0_1_400px]">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#5C665E" strokeWidth="2" strokeLinecap="round" aria-hidden="true" className="absolute top-[9px] left-2.5">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
        <input
          aria-label="Global search"
          placeholder="Search vendors, components, documents, rules…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
            if (e.key === "Enter" && results[0]) go(results[0].href);
          }}
          className="w-full rounded-md border border-line-strong bg-input py-[7px] pr-2.5 pl-8 text-[14px] text-ink"
        />
        {open && (
          <div className="absolute top-10 right-0 left-0 z-30 flex max-h-[440px] min-w-[360px] flex-col gap-0.5 overflow-auto rounded-lg border border-[#D2CAB6] bg-paper p-1.5 shadow-[0_8px_24px_rgba(30,59,47,.16)]">
            {term.length < 2 && (
              <div className="p-2.5 leading-normal text-muted">
                Search by document number, vendor, component, finding or rule. 
              </div>
            )}
            {term.length >= 2 && !results.length && <div className="p-2.5 text-muted">No vendors, documents, findings or rules match “{q}”.</div>}
            {results.map((r, i) => (
              <button
                key={i}
                onClick={() => go(r.href)}
                className="flex w-full cursor-pointer items-start gap-2.5 rounded-md border-none bg-transparent px-2.5 py-2 text-left text-ink hover:bg-sand"
              >
                <span className="w-[78px] shrink-0 pt-0.5 text-[11.5px] tracking-[.05em] text-muted uppercase">{r.kind}</span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="font-medium">{r.title}</span>
                  <span className="text-xs text-muted">
                    {r.sub}
                  </span>
                </span>
                {r.status && <Badge status={r.status} />}
              </button>
            ))}
          </div>
        )}
      </div>
      {open && <div onClick={() => setOpen(false)} className="fixed inset-0 z-10" />}
    </>
  );
}
