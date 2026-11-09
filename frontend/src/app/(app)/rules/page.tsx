"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { CreateRuleDialog } from "@/components/create-rule-dialog";
import { appliesTo, POLICY_EDITORS, SEVERITY_LABEL } from "@/components/rules";
import { Badge, EmptyState, ErrorNote } from "@/components/ui/badge";
import { LabeledSelect, Page, PageHeader } from "@/components/ui/page";
import { useMe, useRules } from "@/lib/api/hooks";
import { fmtDate, humanize } from "@/lib/format";

const STEPS = ["You write the policy", "System interprets it", "Validated & tested", "You approve", "Engine enforces"];

export default function RulesPage() {
  const router = useRouter();
  const rules = useRules();
  const me = useMe();
  const [statusF, setStatusF] = useState("All");
  const [appliesF, setAppliesF] = useState("All");
  const [direct, setDirect] = useState(false);
  const canEdit = POLICY_EDITORS.includes(me.data?.role ?? "");

  const rows = useMemo(
    () =>
      (rules.data ?? []).filter(
        (r) =>
          (statusF === "All" || (statusF === "Active" ? r.current.active : !r.current.active)) &&
          (appliesF === "All" || appliesTo(r) === appliesF),
      ),
    [rules.data, statusF, appliesF],
  );
  const appliesOpts = ["All", ...new Set((rules.data ?? []).map(appliesTo))];

  const createButton = canEdit ? (
    <>
      <button className="btn-secondary px-3.5 py-2 font-normal" onClick={() => setDirect(true)}>
        From parameters…
      </button>
      <Link href="/rules/new" className="btn-primary px-4 py-2 no-underline hover:text-page">
        + Create Rule
      </Link>
    </>
  ) : (
    <span title="Only Compliance Specialists and Admins create rules." className="btn-secondary cursor-not-allowed opacity-60">
      + Create Rule
    </span>
  );

  return (
    <Page>
      <PageHeader
        title="Rule engine"
        sub="Policies that determine document status and findings. Rules run deterministically; changes require approval and are versioned."
        actions={createButton}
      />
      <div role="note" className="card grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] overflow-hidden">
        {STEPS.map((s, i) => (
          <div key={s} className="flex flex-col gap-0.5 border-r border-line-soft px-3.5 py-2.5 last:border-r-0">
            <span className="font-mono text-[12px] text-muted-3">0{i + 1}</span>
            <span className="font-medium">{s}</span>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        <LabeledSelect label="Status" value={statusF} options={["All", "Active", "Disabled"]} onChange={setStatusF} />
        <LabeledSelect label="Applies to" value={appliesF} options={appliesOpts} onChange={setAppliesF} />
        <span className="ml-auto text-xs text-muted">{rows.length} rules</span>
      </div>
      {rules.isError && <ErrorNote error={rules.error} />}
      <section className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] border-collapse">
            <thead>
              <tr>
                {["Rule name", "Applies to", "Rule type", "Status", "Version", "Severity", "Last updated"].map((h) => (
                  <th key={h} className="th">
                    {h}
                  </th>
                ))}
                <th className="th">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rules.isPending &&
                Array.from({ length: 5 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={8} className="td">
                      <div className="skeleton-bar h-2.5 w-3/4 animate-pulse-soft" />
                    </td>
                  </tr>
                ))}
              {rows.map((r) => (
                <tr key={r.id} className="tr-link" style={{ opacity: r.current.active ? 1 : 0.7 }} onClick={() => router.push(`/rules/${r.id}`)}>
                  <td className="td py-2.5">
                    <Link href={`/rules/${r.id}`} onClick={(e) => e.stopPropagation()} className="font-semibold text-forest no-underline hover:underline">
                      {r.current.name}
                    </Link>
                    <div className="max-w-[380px] truncate text-xs text-muted">{r.current.source_text ? `“${r.current.source_text}”` : r.code}</div>
                  </td>
                  <td className="td py-2.5">{appliesTo(r)}</td>
                  <td className="td py-2.5">{humanize(r.kind)}</td>
                  <td className="td py-2.5">
                    <Badge status={r.current.active ? "active" : "disabled"} dashed />
                  </td>
                  <td className="td py-2.5 font-mono text-xs">v{r.current.version}</td>
                  <td className="td py-2.5 text-[13.5px]">{SEVERITY_LABEL[r.current.severity] ?? r.current.severity}</td>
                  <td className="td py-2.5 font-mono text-xs whitespace-nowrap">{fmtDate(r.current.created_at)}</td>
                  <td className="td py-2.5 text-right">
                    <span className="btn-secondary btn-sm">Open</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rules.isSuccess && !rows.length && (
          <EmptyState title={rules.data.length ? "No compliance rules match this filter." : "No compliance rules have been defined yet."}>
            {canEdit && (
              <Link href="/rules/new" className="btn-primary btn-sm no-underline hover:text-page">
                + Create Rule
              </Link>
            )}
          </EmptyState>
        )}
      </section>
      {direct && <CreateRuleDialog onClose={() => setDirect(false)} />}
    </Page>
  );
}
