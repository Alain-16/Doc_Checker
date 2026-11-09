"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import type { Schemas } from "@/lib/api/client";
import { fmtDate } from "@/lib/format";
import { complianceKey } from "@/lib/status";

export type Doc = Schemas["DocumentOut"];

export const docStatus = (d: Pick<Doc, "compliance_status" | "superseded">) => complianceKey(d.compliance_status, d.superseded);
export const pagesText = (d: Pick<Doc, "start_page" | "end_page">) => (d.start_page === d.end_page ? `${d.start_page}` : `${d.start_page}–${d.end_page}`);

export function Confidence({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-muted-3">—</span>;
  const pct = Math.round(value * 100);
  return pct < 80 ? (
    <span title="Below 80% review threshold" className="font-semibold text-review">
      ◔ {pct}%
    </span>
  ) : (
    <span className="text-[#6B746D]">{pct}%</span>
  );
}

/** Table of logical documents. "vendor" = compact vendor-detail columns, "full" = the Documents screen. */
export function DocRows({ docs, variant }: { docs: Doc[]; variant: "vendor" | "full" }) {
  const router = useRouter();
  const open = (id: string) => router.push(`/documents/${id}`);

  if (variant === "vendor") {
    return (
      <table className="w-full min-w-[860px] border-collapse">
        <thead>
          <tr>
            {["Document", "Type", "Number · Rev", "Governing date", "Status", "Pages"].map((h) => (
              <th key={h} className="th">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {docs.map((d) => (
            <tr key={d.id} className="tr-link" style={{ opacity: d.superseded ? 0.72 : 1 }} onClick={() => open(d.id)}>
              <td className="td max-w-[360px]">
                <Link href={`/documents/${d.id}`} onClick={(e) => e.stopPropagation()} className="font-medium text-forest no-underline hover:underline">
                  {d.title || d.label}
                </Link>
                <div className="text-xs text-muted">{d.component_name ?? "No component"}</div>
              </td>
              <td className="td">{d.document_type_label ?? "Unclassified"}</td>
              <td className="td font-mono text-xs">
                {d.document_number || "—"}
                {d.revision ? ` · Rev ${d.revision}` : ""}
              </td>
              <td className="td font-mono text-xs whitespace-nowrap">{d.governing_date ? fmtDate(d.governing_date) : "Not determined"}</td>
              <td className="td">
                <Badge status={docStatus(d)} />
              </td>
              <td className="td font-mono text-xs">{pagesText(d)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  return (
    <table className="w-full min-w-[1180px] border-collapse">
      <thead>
        <tr>
          <th className="th">Document</th>
          <th className="th">Vendor · Component</th>
          <th className="th">Type</th>
          <th className="th">Doc No.</th>
          <th className="th">Rev</th>
          <th className="th">Governing date</th>
          <th className="th">Status</th>
          <th className="th text-right">Confidence</th>
          <th className="th">Source file</th>
          <th className="th">
            <span className="sr-only">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {docs.map((d) => (
          <tr key={d.id} className="tr-link" style={{ opacity: d.superseded ? 0.72 : 1 }} onClick={() => open(d.id)}>
            <td className="td max-w-[320px]">
              <Link href={`/documents/${d.id}`} onClick={(e) => e.stopPropagation()} className="leading-[1.4] font-medium text-forest no-underline hover:underline">
                {d.title || d.label}
              </Link>
              <div className="text-xs text-muted">
                Pages {pagesText(d)}
                {d.open_reviews > 0 && <span className="ml-1.5 text-review">· {d.open_reviews} to review</span>}
              </div>
            </td>
            <td className="td">
              <div>{d.vendor_name ?? "Not identified"}</div>
              <div className="text-xs text-muted">{d.component_name ?? "—"}</div>
            </td>
            <td className="td">{d.document_type_label ?? "Unclassified"}</td>
            <td className="td font-mono text-xs whitespace-nowrap">{d.document_number || "—"}</td>
            <td className="td font-mono text-xs">{d.revision || "—"}</td>
            <td className="td font-mono text-xs whitespace-nowrap">{d.governing_date ? fmtDate(d.governing_date) : "Not determined"}</td>
            <td className="td">
              <Badge status={docStatus(d)} />
            </td>
            <td className="td text-right font-mono text-xs whitespace-nowrap">
              <Confidence value={d.classification_confidence} />
            </td>
            <td className="td max-w-[200px]">
              <Link
                href={`/vendor-files/${d.vendor_file_id}?page=${d.start_page}`}
                onClick={(e) => e.stopPropagation()}
                className="font-mono text-[12.5px] break-all text-forest no-underline hover:underline"
              >
                {d.filename}
              </Link>
            </td>
            <td className="td text-right">
              <Link href={`/documents/${d.id}`} onClick={(e) => e.stopPropagation()} className="btn-secondary btn-sm no-underline">
                Open
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
