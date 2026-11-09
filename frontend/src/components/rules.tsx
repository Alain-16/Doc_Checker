import type { Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

/** "Technical support bulletin", or what a rule without a document type judges. */
export function appliesTo(rule: { level: string; document_type?: string | null }): string {
  if (rule.document_type) return humanize(rule.document_type);
  if (rule.level === "component") return "Each component";
  if (rule.level === "vendor") return "Each vendor";
  return "All document types";
}

/** Roles allowed to create and change rules (backend POLICY_EDITORS). */
export const POLICY_EDITORS = ["compliance_specialist", "admin"];

export const SEVERITY_LABEL: Record<string, string> = { critical: "Critical", warning: "Warning", info: "Info" };

/** Rule parameters as readable rows: nested keys joined, lists comma-separated. */
export function ParamList({ params }: { params: Record<string, unknown> | null | undefined }) {
  const rows: [string, string][] = [];
  const walk = (value: unknown, path: string[]) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const [k, v] of Object.entries(value)) walk(v, [...path, k]);
      return;
    }
    let text: string;
    if (Array.isArray(value)) {
      text = value.length ? value.map((v) => (typeof v === "object" ? JSON.stringify(v) : humanize(String(v)))).join(", ") : "—";
    } else if (typeof value === "boolean") {
      text = value ? "Yes" : "No";
    } else if (value === null || value === undefined || value === "") {
      text = "—";
    } else {
      text = String(value);
    }
    rows.push([humanize(path.join(" · ")), text]);
  };
  walk(params ?? {}, []);
  if (!rows.length) return <p className="m-0 px-4 py-3 text-muted">No parameters.</p>;
  return (
    <dl className="m-0 px-4 py-1">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[190px_minmax(0,1fr)] gap-3 border-b border-line-faint py-[9px] last:border-b-0">
          <dt className="text-muted">{k}</dt>
          <dd className="m-0 font-medium break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export type Rule = Schemas["RuleOut"];
export type RuleDetail = Schemas["RuleDetailOut"];
export type DraftItem = {
  quote?: string;
  name?: string;
  status: "ready" | "needs_clarification" | "invalid";
  questions?: string[];
  problems?: string[];
  warnings?: string[];
  kind?: string | null;
  level?: string | null;
  document_type?: string | null;
  severity?: string;
  parameters?: Record<string, unknown> | null;
  new_attributes?: { name: string; display_name: string; description: string; value_type: string }[];
  new_document_types?: { name: string; display_name: string; description: string }[];
  read_back?: string | null;
  preview?: { checked: number; would_flag: number; examples: string[] } | null;
  documents_to_read?: number;
};
