"use client";

import Link from "next/link";
import { docStatus } from "@/components/doc-table";
import { SinglePage } from "@/components/source-viewer";
import { Badge } from "@/components/ui/badge";
import { Drawer } from "@/components/ui/dialog";
import type { Schemas } from "@/lib/api/client";
import { fmtDate, fmtDateTime, humanize } from "@/lib/format";
import { badge } from "@/lib/status";

export type Finding = Schemas["FindingOut"];

type Evidence = Record<string, unknown>;

/** The page a finding points at: its own `page`, or the first open review it is waiting on. */
export function findingPage(evidence: Evidence): number | null {
  if (typeof evidence.page === "number") return evidence.page;
  const reviews = evidence.reviews;
  if (Array.isArray(reviews)) {
    const first = reviews.find((r) => r && typeof r === "object" && typeof (r as Evidence).page === "number") as Evidence | undefined;
    if (first) return first.page as number;
  }
  return null;
}

/** Text to highlight on that page: the value as printed, when the rule recorded it. */
export function findingSnippet(evidence: Evidence): string | null {
  return typeof evidence.original_text === "string" ? evidence.original_text : null;
}

/** Evidence as readable lines, e.g. "Date: 2022-06-30", "Missing: Revision, Approved". */
export function evidenceLines(evidence: Evidence): [string, string][] {
  const out: [string, string][] = [];
  for (const [k, v] of Object.entries(evidence)) {
    if (k === "reviews" && Array.isArray(v)) {
      for (const r of v as Evidence[]) out.push([`Waiting for review (${humanize(String(r.kind))}, p. ${r.page ?? "—"})`, String(r.reason ?? "")]);
    } else if (Array.isArray(v)) {
      out.push([humanize(k), v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ")]);
    } else if (v !== null && typeof v === "object") {
      out.push([humanize(k), JSON.stringify(v)]);
    } else if (v !== null && v !== undefined && v !== "") {
      out.push([humanize(k), String(v)]);
    }
  }
  return out;
}

export function subjectName(f: Finding): string {
  if (f.document) return f.document.label;
  if (f.subject === "component") return f.component_name ?? "Component";
  return f.vendor_name ?? "Vendor";
}

/** Finding detail: why it was raised, the rule, the evidence page. Findings close themselves on re-evaluation. */
export function FindingDrawer({ finding: f, onClose }: { finding: Finding; onClose: () => void }) {
  const page = findingPage(f.evidence);
  const doc = f.document;
  const db = doc ? badge(docStatus(doc)) : null;
  return (
    <Drawer label="Finding detail" onClose={onClose}>
      <div className="flex items-start gap-3 border-b border-line px-5 py-4">
        <div className="flex flex-1 flex-col gap-2">
          <div className="flex flex-wrap gap-1.5">
            <Badge status={f.severity} suffix=" severity" />
            <Badge status={f.resolved ? "resolved" : "open"} />
          </div>
          <h2 className="m-0 text-[18px] leading-[1.35] font-semibold">{f.rule_name}</h2>
        </div>
        <button onClick={onClose} aria-label="Close" className="size-[30px] cursor-pointer rounded-md border border-line-strong bg-paper text-base text-forest">
          ×
        </button>
      </div>
      <div className="flex flex-1 flex-col gap-4 overflow-auto px-5 py-4">
        <p className="m-0 leading-[1.55]">{f.message}</p>
        <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-2 text-[13.5px]">
          <dt className="text-muted">Rule applied</dt>
          <dd className="m-0">
            <Link href={`/rules/${f.rule_id}`} className="font-medium text-forest underline">
              {f.rule_name} v{f.rule_version}
            </Link>
          </dd>
          <dt className="text-muted">About</dt>
          <dd className="m-0">
            {doc ? <Link href={`/documents/${doc.id}`}>{doc.label}</Link> : `${humanize(f.subject)}: ${subjectName(f)}`}
          </dd>
          {db && (
            <>
              <dt className="text-muted">Document status</dt>
              <dd className="m-0" style={{ color: db.fg }}>
                {db.icon} {db.label}
              </dd>
            </>
          )}
          <dt className="text-muted">Vendor · Component</dt>
          <dd className="m-0">
            {f.vendor_name ?? "—"} · {f.component_name ?? "—"}
          </dd>
          <dt className="text-muted">Status given</dt>
          <dd className="m-0">{badge(f.status === "approaching_review" ? "approaching" : f.status === "needs_review" ? "review" : f.status).label}</dd>
          {f.governing_date && (
            <>
              <dt className="text-muted">Governing date</dt>
              <dd className="m-0 font-mono">{fmtDate(f.governing_date)}</dd>
            </>
          )}
          {evidenceLines(f.evidence).map(([k, v], i) => (
            <div key={i} className="contents">
              <dt className="text-muted">{k}</dt>
              <dd className="m-0 font-mono text-[13px] break-words">{v}</dd>
            </div>
          ))}
          <dt className="text-muted">Raised</dt>
          <dd className="m-0 font-mono">{fmtDateTime(f.created_at)} · System</dd>
          <dt className="text-muted">Last evaluated</dt>
          <dd className="m-0 font-mono">{fmtDateTime(f.last_evaluated_at)}</dd>
        </dl>
        {f.resolved ? (
          <div className="rounded-md border border-[#BCD4B2] bg-[#E6EFE0] px-3 py-2.5 text-[13.5px] text-ok">
            ✓ Resolved by the rules engine on {fmtDateTime(f.resolved_at)} — the cause no longer applies.
          </div>
        ) : (
          <div className="rounded-md border border-line bg-subtle px-3 py-2.5 text-[13.5px] text-muted-2">
            Findings close themselves: replace the document, resolve its review items, or change the rule, and the next evaluation resolves it.
          </div>
        )}
        {doc && page && (
          <div className="flex flex-col gap-2">
            <span className="section-label">Evidence · page {page}</span>
            <div className="flex justify-center rounded-md border border-viewer-line bg-viewer p-3.5">
              <div className="w-full max-w-[380px]">
                <SinglePage fileId={doc.vendor_file_id} page={page} highlight={findingSnippet(f.evidence)} heading={f.vendor_name} />
              </div>
            </div>
          </div>
        )}
      </div>
      <div className="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-3">
        {doc && (
          <Link href={`/documents/${doc.id}${page ? `?page=${page}` : ""}`} className="btn-primary no-underline hover:text-page">
            View Evidence
          </Link>
        )}
      </div>
    </Drawer>
  );
}
