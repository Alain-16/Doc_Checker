"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useCrumbs } from "@/components/shell/crumbs";
import { appliesTo, ParamList, POLICY_EDITORS, SEVERITY_LABEL, type RuleDetail } from "@/components/rules";
import { Badge, EmptyState, ErrorNote } from "@/components/ui/badge";
import { ReasonDialog } from "@/components/ui/dialog";
import { Page } from "@/components/ui/page";
import { Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { api, call } from "@/lib/api/client";
import { useMe, useRule, useUpdateRule } from "@/lib/api/hooks";
import { fmtDate, fmtDateTime, humanize } from "@/lib/format";

type Version = RuleDetail["versions"][number];

export default function RuleDetailPage() {
  const { ruleId } = useParams<{ ruleId: string }>();
  const rule = useRule(ruleId);
  const me = useMe();
  const update = useUpdateRule(ruleId);
  const toast = useToast();
  const kinds = useQuery({ queryKey: ["rule-kinds"], queryFn: () => call(api.GET("/compliance-rules/kinds")), staleTime: Infinity });
  const [tab, setTab] = useState<"summary" | "history">("summary");
  const [cmp, setCmp] = useState<number | null>(null);
  const [dialog, setDialog] = useState<"edit" | "toggle" | null>(null);
  useCrumbs([{ label: "Rule Engine", href: "/rules" }, { label: rule.data?.current.name ?? "…" }]);

  if (rule.isError) return <Page><ErrorNote error={rule.error} /></Page>;
  if (!rule.data) return <Page><div className="animate-pulse-soft text-muted">Loading rule…</div></Page>;

  const r = rule.data;
  const cur = r.current;
  const canEdit = POLICY_EDITORS.includes(me.data?.role ?? "");
  const kind = kinds.data?.find((k) => k.kind === r.kind);
  const versions = [...r.versions].reverse(); // newest first

  const save = (changes: Partial<Pick<Version, "name" | "severity" | "parameters" | "active">>, reason: string, password: string) =>
    update.mutateAsync({
      name: changes.name ?? cur.name,
      severity: changes.severity ?? cur.severity,
      parameters: changes.parameters ?? cur.parameters,
      active: changes.active ?? cur.active,
      change_reason: reason,
      password,
    });

  return (
    <Page>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="eyebrow">{humanize(r.kind)} rule</span>
            <Badge status={cur.active ? "active" : "disabled"} />
            <span className="rounded border border-line-chip px-[7px] py-px font-mono text-xs">v{cur.version}</span>
          </div>
          <h1 className="m-0 text-[24px] font-semibold">{cur.name}</h1>
          <p className="m-0 text-muted">
            <span className="font-mono">{r.code}</span> · Applies to {appliesTo(r)} · Judges each {r.level} · Updated {fmtDate(cur.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canEdit && (
            <button className="btn-primary" onClick={() => setDialog("edit")}>
              Edit Rule
            </button>
          )}
          <button className="btn-secondary font-normal" onClick={() => setTab("history")}>
            View History
          </button>
          {canEdit && (
            <button className="btn-danger" onClick={() => setDialog("toggle")}>
              {cur.active ? "Disable" : "Enable"}
            </button>
          )}
        </div>
      </div>
      {!cur.active && (
        <div role="note" className="rounded-md border border-dashed border-[#D2CEC2] bg-[#ECEAE3] px-3.5 py-2.5 text-[#3E4C43]">
          ○ Disabled — this rule is not evaluated against documents. Findings it created remain for audit.
        </div>
      )}
      <Tabs
        tabs={[
          { key: "summary", label: "Summary" },
          { key: "history", label: `Version history (${r.versions.length})` },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "summary" && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,420px),1fr))] items-start gap-4">
          <div className="flex flex-col gap-4">
            <section className="card flex flex-col gap-2 p-4">
              <span className="section-label">Original policy</span>
              {cur.source_text ? (
                <blockquote className="m-0 border-l-[3px] border-gold pl-3 text-[16px] leading-[1.55]">“{cur.source_text}”</blockquote>
              ) : (
                <p className="m-0 text-muted">Configured directly, without a written policy.</p>
              )}
            </section>
            <section className="card overflow-hidden">
              <div className="border-b border-line px-4 py-3 text-xs font-semibold tracking-[.05em] text-muted-2 uppercase">System interpretation · approved</div>
              <ParamList params={cur.parameters} />
            </section>
          </div>
          <section className="card overflow-hidden">
            <div className="card-head">
              <span className="font-semibold">Rule definition</span>
              <span className="text-xs text-muted">Version {cur.version}</span>
            </div>
            <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-2 px-4 py-3.5 text-[13.5px]">
              <dt className="text-muted">Check</dt>
              <dd className="m-0">{kind?.description ?? humanize(r.kind)}</dd>
              <dt className="text-muted">Severity of findings</dt>
              <dd className="m-0">
                <Badge status={cur.severity} size="sm" />
              </dd>
              <dt className="text-muted">Applies to</dt>
              <dd className="m-0">{appliesTo(r)}</dd>
              <dt className="text-muted">Last change</dt>
              <dd className="m-0">{cur.change_reason}</dd>
              <dt className="text-muted">Signed</dt>
              <dd className="m-0 font-mono">{fmtDateTime(cur.created_at)}</dd>
            </dl>
            <div className="border-t border-line-soft bg-subtle px-4 py-2.5 text-xs text-muted">
              Documents evaluated and findings per rule will show here once a findings endpoint exists.
            </div>
          </section>
        </div>
      )}

      {tab === "history" && (
        <section className="card overflow-hidden">
          {versions.map((v, i) => {
            const prev = versions[i + 1];
            const open = cmp === v.version && !!prev;
            return (
              <div key={v.version} className="flex flex-col gap-2 border-b border-line-soft px-4 py-3.5 last:border-b-0">
                <div className="flex flex-wrap items-center gap-2.5">
                  <span className="font-semibold">Version {v.version}</span>
                  <Badge status={i === 0 ? (v.active ? "active" : "disabled") : "superseded"} />
                  <span className="text-xs text-muted">Signed {fmtDateTime(v.created_at)}</span>
                </div>
                <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-1 text-[13.5px]">
                  <span className="text-muted">Name</span>
                  <span>{v.name}</span>
                  <span className="text-muted">Policy</span>
                  <span>{v.source_text ? `“${v.source_text}”` : "—"}</span>
                  <span className="text-muted">Interpretation</span>
                  <span className="font-mono text-[12.5px] break-all">
                    {SEVERITY_LABEL[v.severity]} · {JSON.stringify(v.parameters)}
                  </span>
                  <span className="text-muted">Change</span>
                  <span>{v.change_reason}</span>
                </div>
                {prev && (
                  <button className="btn-link self-start" onClick={() => setCmp(open ? null : v.version)}>
                    {open ? "Hide comparison" : "Compare with previous"}
                  </button>
                )}
                {open && prev && (
                  <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-2.5">
                    <VersionBox v={prev} tone="old" />
                    <VersionBox v={v} tone="new" />
                  </div>
                )}
              </div>
            );
          })}
          {!versions.length && <EmptyState title="No versions." />}
        </section>
      )}

      {dialog === "toggle" && (
        <ReasonDialog
          title={cur.active ? `Disable “${cur.name}”?` : `Enable “${cur.name}”?`}
          intro={cur.active ? "Disabled rules are not evaluated. Findings they created remain for audit." : "The rule is evaluated again on the next run; every document is re-judged."}
          confirmLabel={cur.active ? "Disable rule" : "Enable rule"}
          danger={cur.active}
          sign
          onClose={() => setDialog(null)}
          onSubmit={async ({ reason, password }) => {
            await save({ active: !cur.active }, reason, password);
            toast(cur.active ? "Rule disabled. Findings it created remain for audit." : "Rule re-enabled. Statuses are being recalculated.");
          }}
        />
      )}
      {dialog === "edit" && <EditRuleDialog rule={r} onClose={() => setDialog(null)} onSave={save} />}
    </Page>
  );
}

function VersionBox({ v, tone }: { v: Version; tone: "old" | "new" }) {
  const old = tone === "old";
  return (
    <div
      className="flex flex-col gap-1 rounded-md border p-2.5 text-[13.5px]"
      style={{ borderColor: old ? "#E2B2A8" : "#BCD4B2", background: old ? "#FBF1EE" : "#EEF4EA" }}
    >
      <span className="font-semibold" style={{ color: old ? "#9A2B1E" : "#25603A" }}>
        {old ? "−" : "+"} Version {v.version}
      </span>
      <span>{v.source_text ? `“${v.source_text}”` : v.name}</span>
      <span className="font-mono text-[12.5px] break-all text-muted-2">
        {v.active ? "active" : "disabled"} · {v.severity} · {JSON.stringify(v.parameters)}
      </span>
    </div>
  );
}

function EditRuleDialog({
  rule,
  onClose,
  onSave,
}: {
  rule: RuleDetail;
  onClose: () => void;
  onSave: (changes: Partial<Pick<Version, "name" | "severity" | "parameters">>, reason: string, password: string) => Promise<unknown>;
}) {
  const [name, setName] = useState(rule.current.name);
  const [severity, setSeverity] = useState(rule.current.severity);
  const [json, setJson] = useState(JSON.stringify(rule.current.parameters, null, 2));
  let parsed: Record<string, unknown> | null = null;
  try {
    const p = JSON.parse(json);
    parsed = p && typeof p === "object" && !Array.isArray(p) ? p : null;
  } catch {}

  return (
    <ReasonDialog
      title={`Edit “${rule.current.name}”`}
      intro={
        <div className="flex flex-col gap-3">
          <span>Saving creates version {rule.current.version + 1}. The current version stays in effect until you sign.</span>
          <label className="field-label">
            Name
            <input className="input font-normal" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field-label">
            Severity of findings
            <select className="select text-[14px]" value={severity} onChange={(e) => setSeverity(e.target.value as typeof severity)}>
              {Object.entries(SEVERITY_LABEL).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="field-label">
            Parameters (technical definition)
            <textarea className="input min-h-[140px] font-mono text-xs font-normal" value={json} onChange={(e) => setJson(e.target.value)} spellCheck={false} />
            {!parsed && <span className="font-normal text-bad">Not valid JSON object.</span>}
          </label>
        </div>
      }
      confirmLabel="Sign new version"
      sign
      onClose={onClose}
      onSubmit={async ({ reason, password }) => {
        if (!parsed) throw new Error("Fix the parameters first: they must be a JSON object.");
        await onSave({ name, severity, parameters: parsed }, reason, password);
      }}
    />
  );
}
