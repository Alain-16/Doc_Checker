"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { docStatus } from "@/components/doc-table";
import { subjectName } from "@/components/findings";
import { Badge, ErrorNote } from "@/components/ui/badge";
import { ActivityList, HealthBar } from "@/components/ui/health";
import { Page, PageHeader } from "@/components/ui/page";
import { useDashboard, useFindings, useRules } from "@/lib/api/hooks";
import { fmtDate, fmtDateTime, fmtRelative } from "@/lib/format";
import { badge, BAR } from "@/lib/status";

const ACTIVITY_ICON: Record<string, string> = { upload: "↑", finding: "!", finding_resolved: "✓", review: "✎", rule: "▤" };

export default function OverviewPage() {
  const router = useRouter();
  const dash = useDashboard();
  const rules = useRules();
  const findings = useFindings({ status: "open" });
  const activeRules = rules.data?.filter((r) => r.current.active).length;
  const d = dash.data;
  const t = d?.totals;
  const pct = (n: number) => (t && t.documents ? ((n / t.documents) * 100).toFixed(1) : "0.0");

  const kpis = t
    ? [
        { label: "Active documents", value: t.documents, sub: `across ${d.vendors} vendors${t.superseded ? ` · ${t.superseded} superseded` : ""}`, status: null, href: "/documents" },
        { label: "Current", value: t.current, sub: `${pct(t.current)}% of active`, status: "current", href: "/documents?status=current" },
        { label: "Approaching review", value: t.approaching, sub: "within the warning window", status: "approaching", href: "/documents?status=approaching_review" },
        { label: "Stale", value: t.stale, sub: "beyond review threshold", status: "stale", href: "/documents?status=stale" },
        { label: "Needs review", value: t.needs_review, sub: `${d.open_reviews} items in the review queue`, status: "review", href: "/documents?status=needs_review" },
        { label: "Open findings", value: t.open_findings, sub: `${d.findings_by_severity.critical ?? 0} critical`, status: "critical", href: "/findings" },
      ]
    : [];
  const health = t
    ? (["current", "approaching", "stale", "review"] as const).map((k) => ({ key: k, count: k === "review" ? t.needs_review : t[k] }))
    : [];
  const statusParam = { current: "current", approaching: "approaching_review", stale: "stale", review: "needs_review" };
  const attention = (findings.data ?? []).slice(0, 8);

  return (
    <Page>
      <PageHeader
        title="What requires attention today"
        sub={
          <>
            {d?.last_evaluated_at ? `Statuses evaluated ${fmtDateTime(d.last_evaluated_at)}` : "Not evaluated yet"} against {activeRules ?? "…"} active rules ·{" "}
            {d?.vendors ?? "…"} vendors
            {d && d.files_processing > 0 && ` · ${d.files_processing} file${d.files_processing > 1 ? "s" : ""} processing`}
            {d && d.files_failed > 0 && <span className="text-bad"> · {d.files_failed} failed</span>}
          </>
        }
        actions={
          <>
            <Link href="/review" className="btn-secondary no-underline">
              Open Review Queue
            </Link>
            <Link href="/upload" className="btn-primary no-underline hover:text-page">
              Upload Document
            </Link>
          </>
        }
      />
      {dash.isError && <ErrorNote error={dash.error} />}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(168px,1fr))] gap-3">
        {dash.isPending &&
          Array.from({ length: 6 }, (_, i) => <div key={i} className="card h-[106px] animate-pulse-soft" />)}
        {kpis.map((k) => {
          const b = k.status ? badge(k.status) : { fg: "#1E3B2F", bg: "#EFEBE1", bd: "#D2CAB6", icon: "▤" };
          return (
            <Link key={k.label} href={k.href} className="card flex flex-col gap-2 px-4 py-3.5 text-left text-ink no-underline hover:border-sage hover:text-ink">
              <span className="flex items-center gap-[7px] text-xs font-medium text-muted-2">
                <span
                  aria-hidden="true"
                  className="inline-flex size-[18px] items-center justify-center rounded border text-[12px]"
                  style={{ color: b.fg, background: b.bg, borderColor: b.bd }}
                >
                  {b.icon}
                </span>
                {k.label}
              </span>
              <span className="font-mono text-[26px] font-semibold tracking-[-0.02em]">{k.value.toLocaleString("en-US")}</span>
              <span className="text-xs text-muted">{k.sub}</span>
            </Link>
          );
        })}
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,520px),1fr))] items-start gap-4">
        <div className="flex min-w-0 flex-col gap-4">
          <section className="card overflow-hidden">
            <div className="card-head">
              <h2 className="card-title">Attention required</h2>
              <Link href="/findings" className="text-xs font-medium text-forest underline">
                All findings
              </Link>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse">
                <thead>
                  <tr>
                    <th className="th">Vendor · Component</th>
                    <th className="th">About</th>
                    <th className="th">Issue</th>
                    <th className="th">Severity</th>
                    <th className="th">Raised</th>
                    <th className="th">
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {attention.map((f) => (
                    <tr key={f.id} className="tr-link" onClick={() => router.push(`/findings?open=${f.id}`)}>
                      <td className="td">
                        <div className="font-medium">{f.vendor_name ?? "—"}</div>
                        <div className="text-xs text-muted">{f.component_name ?? "—"}</div>
                      </td>
                      <td className="td">
                        <div className="text-xs">{subjectName(f)}</div>
                        {f.document && <Badge status={docStatus(f.document)} size="xs" />}
                      </td>
                      <td className="td max-w-[280px]">
                        <div className="font-medium">{f.rule_name}</div>
                        <div className="text-xs text-muted-2">{f.message}</div>
                      </td>
                      <td className="td">
                        <Badge status={f.severity} />
                      </td>
                      <td className="td font-mono text-xs whitespace-nowrap">{fmtDate(f.created_at)}</td>
                      <td className="td text-right">
                        <span className="btn-secondary btn-sm">View</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {findings.isSuccess && !attention.length && <div className="p-6 text-center text-muted">✓ No open findings.</div>}
          </section>

          <section className="card">
            <div className="border-b border-line px-4 py-3">
              <h2 className="card-title">Recent activity</h2>
            </div>
            {d && d.activity.length > 0 ? (
              <ActivityList
                items={d.activity.map((a) => ({ icon: ACTIVITY_ICON[a.kind] ?? "◎", text: a.text, who: a.who, when: fmtRelative(a.at), href: a.link }))}
              />
            ) : (
              <p className="m-0 p-4 text-muted">{d ? "No activity yet." : "Loading…"}</p>
            )}
          </section>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <section className="card flex flex-col gap-3.5 px-4 py-3.5">
            <div className="flex items-baseline justify-between">
              <h2 className="card-title">Documentation health</h2>
              <span className="font-mono text-xs text-muted">{t ? `${t.documents.toLocaleString("en-US")} docs` : ""}</span>
            </div>
            {t && <HealthBar parts={health} total={t.documents} />}
            <div className="flex flex-col gap-0.5">
              {health.map(({ key, count }) => {
                const b = badge(key);
                return (
                  <Link
                    key={key}
                    href={`/documents?status=${statusParam[key]}`}
                    className="grid grid-cols-[12px_minmax(0,1fr)_auto_54px] items-center gap-2.5 rounded px-1 py-1.5 text-left text-[14px] text-ink no-underline hover:bg-sand-2 hover:text-ink"
                  >
                    <span className="size-2.5 rounded-sm" style={{ background: BAR[key] }} />
                    <span className="flex items-center gap-1.5">
                      <span aria-hidden="true" className="w-3 text-center text-[12px]" style={{ color: b.fg }}>
                        {b.icon}
                      </span>
                      {b.label}
                    </span>
                    <span className="font-mono font-medium">{count.toLocaleString("en-US")}</span>
                    <span className="text-right font-mono text-xs text-muted">{pct(count)}%</span>
                  </Link>
                );
              })}
            </div>
          </section>

          <section className="card">
            <div className="flex items-baseline justify-between border-b border-line px-4 py-3">
              <h2 className="card-title">Upcoming review</h2>
              <span className="text-xs text-muted">Approaching their threshold</span>
            </div>
            <div className="flex flex-col">
              {d?.upcoming.map((u) => (
                <Link
                  key={u.id}
                  href={`/documents/${u.id}`}
                  className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 border-b border-line-faint px-4 py-2.5 text-left text-ink no-underline hover:bg-hover-row hover:text-ink"
                >
                  <span className="font-mono text-xs font-medium">{u.label}</span>
                  <span className="text-right font-mono text-xs text-warn">{u.governing_date ? fmtDate(u.governing_date) : "—"}</span>
                  <span className="col-span-2 text-xs text-muted">
                    {[u.vendor_name, u.component_name].filter(Boolean).join(" · ")}
                    {u.status_reason ? ` — ${u.status_reason}` : ""}
                  </span>
                </Link>
              ))}
              {d && !d.upcoming.length && <p className="m-0 p-4 text-muted">No documents are approaching review.</p>}
            </div>
          </section>
        </div>
      </div>
    </Page>
  );
}
