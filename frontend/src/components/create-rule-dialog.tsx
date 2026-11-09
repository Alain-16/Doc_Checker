"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { SEVERITY_LABEL } from "@/components/rules";
import { ReasonDialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import type { Schemas } from "@/lib/api/client";
import { useCreateRule, useDocumentTypes, useRuleKinds } from "@/lib/api/hooks";
import { humanize } from "@/lib/format";

/** Defaults from a kind's JSON Schema, so the parameters box starts from something valid-shaped. */
function defaultsOf(schema: Record<string, unknown>): Record<string, unknown> {
  const props = (schema.properties ?? {}) as Record<string, { default?: unknown; type?: string }>;
  return Object.fromEntries(Object.entries(props).map(([k, p]) => [k, p.default ?? (p.type === "array" ? [] : p.type === "boolean" ? false : null)]));
}

/**
 * Create a rule directly from a kind and its parameters (POST /compliance-rules),
 * for people who know the engine — the plain-language flow is the usual way.
 */
export function CreateRuleDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const kinds = useRuleKinds();
  const types = useDocumentTypes();
  const create = useCreateRule();
  const toast = useToast();
  const [kind, setKind] = useState<Schemas["RuleKind"] | "">("");
  const [level, setLevel] = useState<Schemas["RuleLevel"] | "">("");
  const [docType, setDocType] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [severity, setSeverity] = useState<Schemas["FindingSeverity"]>("warning");
  const [json, setJson] = useState("{}");
  const spec = kinds.data?.find((k) => k.kind === kind);
  let parsed: Record<string, unknown> | null = null;
  try {
    const p = JSON.parse(json);
    parsed = p && typeof p === "object" && !Array.isArray(p) ? p : null;
  } catch {}

  return (
    <ReasonDialog
      title="Create a rule from parameters"
      intro={
        <div className="flex flex-col gap-3">
          <span>Advanced: pick the check and set its parameters yourself. The new rule is signed and every document is re-judged.</span>
          <label className="field-label">
            Check
            <select
              className="select text-[14px]"
              value={kind}
              onChange={(e) => {
                const k = kinds.data?.find((x) => x.kind === e.target.value);
                setKind(e.target.value as Schemas["RuleKind"]);
                setLevel(k?.levels[0] ?? "");
                setJson(JSON.stringify(k ? defaultsOf(k.parameters_schema) : {}, null, 2));
              }}
            >
              <option value="">Choose…</option>
              {kinds.data?.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {humanize(k.kind)}
                </option>
              ))}
            </select>
            {spec && <span className="font-normal text-muted">{spec.description}</span>}
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="field-label">
              Judges
              <select className="select text-[14px]" value={level} onChange={(e) => setLevel(e.target.value as Schemas["RuleLevel"])} disabled={!spec}>
                {spec?.levels.map((l) => (
                  <option key={l} value={l}>
                    Each {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-label">
              Document type
              <select className="select text-[14px]" value={docType} onChange={(e) => setDocType(e.target.value)} disabled={level !== "document"}>
                <option value="">Every type</option>
                {types.data
                  ?.filter((t) => t.active)
                  .map((t) => (
                    <option key={t.id} value={t.name}>
                      {t.display_name}
                    </option>
                  ))}
              </select>
            </label>
            <label className="field-label">
              Code
              <input className="input font-mono font-normal" value={code} onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_"))} placeholder="COA_BATCH_AGE" />
            </label>
            <label className="field-label">
              Severity
              <select className="select text-[14px]" value={severity} onChange={(e) => setSeverity(e.target.value as Schemas["FindingSeverity"])}>
                {Object.entries(SEVERITY_LABEL).map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="field-label">
            Name
            <input className="input font-normal" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field-label">
            Parameters
            <textarea className="input min-h-[140px] font-mono text-xs font-normal" value={json} onChange={(e) => setJson(e.target.value)} spellCheck={false} />
            {!parsed && <span className="font-normal text-bad">Not a valid JSON object.</span>}
          </label>
        </div>
      }
      confirmLabel="Sign and create"
      sign
      onClose={onClose}
      onSubmit={async ({ reason, password }) => {
        if (!kind || !parsed || !code || !name) throw new Error("Choose the check, and give a code, a name and valid parameters.");
        const rule = await create.mutateAsync({
          code,
          kind,
          level: level || null,
          document_type: level === "document" && docType ? docType : null,
          name,
          severity,
          parameters: parsed,
          active: true,
          change_reason: reason,
          password,
        });
        toast(`Rule ${rule.code} created. Statuses are being recalculated.`);
        router.push(`/rules/${rule.id}`);
      }}
    />
  );
}
