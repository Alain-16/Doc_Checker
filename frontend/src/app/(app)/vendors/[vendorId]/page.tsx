"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { DocRows } from "@/components/doc-table";
import { FindingDrawer, subjectName } from "@/components/findings";
import { useCrumbs } from "@/components/shell/crumbs";
import { Badge, EmptyState, ErrorNote } from "@/components/ui/badge";
import { ReasonDialog } from "@/components/ui/dialog";
import { HealthBar } from "@/components/ui/health";
import { Page, PageHeader } from "@/components/ui/page";
import { Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import {
  useAssignOwner,
  useComponents,
  useComponentStats,
  useDocuments,
  useFindings,
  useMe,
  useOwners,
  useRemoveOwner,
  useUsers,
  useVendorFiles,
  useVendors,
  useVendorStats,
} from "@/lib/api/hooks";
import { fmtBytes, fmtDate } from "@/lib/format";
import { badge } from "@/lib/status";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "components", label: "Components" },
  { key: "documents", label: "Documents" },
  { key: "findings", label: "Findings" },
  { key: "copilot", label: "Ask Copilot" },
] as const;
type TabKey = (typeof TABS)[number]["key"];
const HEALTH_KEYS = ["current", "approaching", "stale", "review"] as const;

export default function VendorDetailPage() {
  const { vendorId } = useParams<{ vendorId: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const vendors = useVendors();
  const components = useComponents(vendorId);
  const vendorStats = useVendorStats();
  const compStats = useComponentStats(vendorId);
  const vendor = vendors.data?.find((v) => v.id === vendorId);
  const tab = (TABS.find((t) => t.key === params.get("tab"))?.key ?? "overview") as TabKey;
  const compSel = params.get("component") ?? "All";
  const docs = useDocuments({ vendor_id: vendorId, component_id: compSel }, tab === "documents");
  const findings = useFindings({ vendor_id: vendorId, status: "open" }, tab === "findings" || tab === "overview");
  const files = useVendorFiles(vendorId);
  const [openFinding, setOpenFinding] = useState<string | null>(null);

  useCrumbs([{ label: "Vendors", href: "/vendors" }, { label: vendor?.name ?? "…" }]);

  const setParam = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    router.replace(`/vendors/${vendorId}${next.size ? `?${next}` : ""}`, { scroll: false });
  };

  if (vendors.isError) return <Page><ErrorNote error={vendors.error} /></Page>;
  if (vendors.isPending) return <Page><div className="animate-pulse-soft text-muted">Loading vendor…</div></Page>;
  if (!vendor) {
    return (
      <Page>
        <EmptyState title="Vendor not found." text="It may have been merged or renamed.">
          <Link href="/vendors" className="btn-secondary no-underline">
            Back to vendors
          </Link>
        </EmptyState>
      </Page>
    );
  }

  const stats = vendorStats.data?.find((s) => s.vendor_id === vendor.id);
  const comps = components.data ?? [];
  const cstat = (id: string) => compStats.data?.find((c) => c.component_id === id);
  const copilotHref = (q?: string) => `/copilot?vendor=${encodeURIComponent(vendor.id)}${q ? `&q=${encodeURIComponent(q)}` : ""}`;
  const healthParts = (s: { current: number; approaching: number; stale: number; needs_review: number }) =>
    HEALTH_KEYS.map((k) => ({ key: k, count: k === "review" ? s.needs_review : s[k] }));
  const finding = findings.data?.find((f) => f.id === openFinding);

  const statCells: [string, string | number, string, string, string][] = [
    ["Components", comps.length, "▦", "#1E3B2F", "#1B2A22"],
    ["Documents", stats?.documents ?? "—", "▤", "#1E3B2F", "#1B2A22"],
    ["Current", stats?.current ?? "—", "✓", "#25603A", "#1B2A22"],
    ["Stale", stats?.stale ?? "—", "!", "#9A2B1E", "#9A2B1E"],
    ["Open findings", stats?.open_findings ?? "—", "▲", "#9A2B1E", "#1B2A22"],
  ];

  return (
    <Page>
      <PageHeader
        eyebrow="Vendor"
        title={vendor.name}
        sub={
          <>
            {vendor.aliases.length > 0 && <>Also known as {vendor.aliases.join(", ")} · </>}
            {stats?.last_upload ? `Last documentation upload ${fmtDate(stats.last_upload)}` : "No documentation uploaded yet"}
          </>
        }
        actions={
          <>
            <Link href="/upload" className="btn-secondary no-underline">
              Upload package
            </Link>
            <Link href={copilotHref()} className="btn-primary no-underline hover:text-page">
              Ask Copilot about this vendor
            </Link>
          </>
        }
      />
      <div className="card grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))]">
        {statCells.map(([label, value, icon, fg, vfg]) => (
          <div key={label} className="flex flex-col gap-1 border-r border-line-soft px-4 py-3 last:border-r-0">
            <span className="flex items-center gap-1.5 text-xs text-muted">
              <span aria-hidden="true" style={{ color: fg }}>
                {icon}
              </span>
              {label}
            </span>
            <span className="font-mono text-xl font-semibold" style={{ color: vfg }}>
              {value}
            </span>
          </div>
        ))}
      </div>

      <Tabs tabs={[...TABS]} value={tab} onChange={(k) => setParam({ tab: k === "overview" ? null : k })} />

      {tab === "overview" && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,420px),1fr))] items-start gap-4">
          <section className="card flex flex-col gap-3.5 px-4 py-3.5">
            <h2 className="card-title">Documentation health</h2>
            {stats && stats.documents > 0 ? (
              <>
                <HealthBar parts={healthParts(stats)} total={stats.documents} />
                <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2">
                  {healthParts(stats).map(({ key, count }) => (
                    <div key={key} className="flex items-center gap-2">
                      <span aria-hidden="true" style={{ color: badge(key).fg }}>
                        {badge(key).icon}
                      </span>
                      <span className="flex-1">{badge(key).label}</span>
                      <span className="font-mono font-medium">{count}</span>
                    </div>
                  ))}
                </div>
                {stats.superseded > 0 && <span className="text-xs text-muted">{stats.superseded} superseded documents kept as history.</span>}
              </>
            ) : (
              <p className="m-0 text-muted">No processed documents for this vendor yet.</p>
            )}
            <h3 className="mt-2 mb-0 text-[14px] font-semibold">Source files</h3>
            <div className="flex flex-col rounded-md border border-line-soft">
              {files.data?.map((f) => (
                <Link
                  key={f.id}
                  href={`/vendor-files/${f.id}`}
                  className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 border-b border-line-soft px-3 py-[9px] text-ink no-underline last:border-b-0 hover:bg-hover-row hover:text-ink"
                >
                  <span className="truncate font-mono text-xs font-medium">{f.filename}</span>
                  <span className="text-xs text-muted">{fmtDate(f.created_at)}</span>
                  <span className="text-xs text-muted">
                    {f.page_count} pages · {f.document_count} logical documents · {fmtBytes(f.file_size_bytes)}
                  </span>
                  <span className="text-xs text-forest underline">View segmentation</span>
                </Link>
              ))}
              {files.isSuccess && !files.data.length && <p className="m-0 p-3 text-muted">No files yet.</p>}
            </div>
          </section>
          <div className="flex flex-col gap-4">
            <section className="card">
              <div className="card-head">
                <h2 className="card-title">Open findings</h2>
                <button className="btn-link" onClick={() => setParam({ tab: "findings" })}>
                  All
                </button>
              </div>
              {(findings.data ?? []).slice(0, 5).map((f) => (
                <button
                  key={f.id}
                  onClick={() => setOpenFinding(f.id)}
                  className="grid w-full cursor-pointer grid-cols-[86px_minmax(0,1fr)] items-center gap-3 border-b border-line-soft bg-transparent px-4 py-2.5 text-left text-ink last:border-b-0 hover:bg-hover-row"
                >
                  <Badge status={f.severity} size="sm" />
                  <span className="flex flex-col">
                    <span className="font-medium">{f.rule_name}</span>
                    <span className="truncate text-xs text-muted">{f.message}</span>
                  </span>
                </button>
              ))}
              {findings.isSuccess && !findings.data.length && <p className="m-0 p-4 text-muted">No open findings.</p>}
            </section>
            <OwnersPanel vendorId={vendor.id} components={comps} />
          </div>
        </div>
      )}

      {tab === "components" && (
        <section className="card overflow-x-auto">
          {components.isError && <ErrorNote error={components.error} />}
          <table className="w-full min-w-[920px] border-collapse">
            <thead>
              <tr>
                <th className="th">Component</th>
                <th className="th">Part numbers</th>
                <th className="th w-[220px]">Document health</th>
                {["Docs", "Current", "Approaching", "Stale", "Needs review", "Findings"].map((h) => (
                  <th key={h} className="th text-right">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {comps.map((c) => {
                const s = cstat(c.id);
                return (
                  <tr key={c.id} className="tr-link" onClick={() => setParam({ tab: "documents", component: c.id })}>
                    <td className="td py-2.5">
                      <span className="font-semibold text-forest">{c.name}</span>
                      {c.description && <div className="max-w-[320px] text-xs text-muted">{c.description}</div>}
                    </td>
                    <td className="td py-2.5 font-mono text-xs">
                      {c.vendor_part_number && <div>Vendor: {c.vendor_part_number}</div>}
                      {c.internal_part_number && <div>Internal: {c.internal_part_number}</div>}
                      {!c.vendor_part_number && !c.internal_part_number && "—"}
                    </td>
                    <td className="td py-2.5">{s && s.documents > 0 ? <HealthBar height={8} parts={healthParts(s)} total={s.documents} /> : <span className="text-xs text-muted-3">—</span>}</td>
                    <td className="td py-2.5 text-right font-mono">{s?.documents ?? 0}</td>
                    <td className="td py-2.5 text-right font-mono">{s?.current ?? 0}</td>
                    <td className="td py-2.5 text-right font-mono">{s?.approaching ?? 0}</td>
                    <td className="td py-2.5 text-right font-mono font-semibold text-bad">{s?.stale ?? 0}</td>
                    <td className="td py-2.5 text-right font-mono">{s?.needs_review ?? 0}</td>
                    <td className="td py-2.5 text-right font-mono">{s?.open_findings ?? 0}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {components.isSuccess && !comps.length && <EmptyState title="No components identified for this vendor yet." />}
        </section>
      )}

      {tab === "documents" && (
        <div className="flex flex-col gap-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-muted">
              Component
              <select className="select text-[14px]" value={compSel} onChange={(e) => setParam({ component: e.target.value === "All" ? null : e.target.value })}>
                <option value="All">All</option>
                {comps.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <span className="text-xs text-muted">{docs.data ? `${docs.data.length} documents` : ""}</span>
          </div>
          <section className="card overflow-x-auto">
            {docs.isPending && <div className="animate-pulse-soft p-4 text-muted">Loading documents…</div>}
            {docs.isError && <ErrorNote error={docs.error} />}
            {docs.data && docs.data.length > 0 && <DocRows docs={docs.data} variant="vendor" />}
            {docs.isSuccess && !docs.data.length && <EmptyState title="No documents to show." />}
          </section>
        </div>
      )}

      {tab === "findings" && (
        <section className="card overflow-hidden">
          {findings.data?.map((f) => (
            <button
              key={f.id}
              onClick={() => setOpenFinding(f.id)}
              className="grid w-full cursor-pointer grid-cols-[96px_minmax(0,1fr)_auto] items-center gap-3 border-b border-line-soft bg-transparent px-4 py-[11px] text-left text-ink last:border-b-0 hover:bg-hover-row"
            >
              <Badge status={f.severity} />
              <span className="flex flex-col gap-0.5">
                <span className="font-medium">{f.rule_name}</span>
                <span className="text-xs text-muted">
                  {subjectName(f)} · {f.component_name ?? "—"} · {f.message}
                </span>
              </span>
              <Badge status="open" />
            </button>
          ))}
          {findings.isSuccess && !findings.data.length && <div className="p-10 text-center text-muted">No compliance findings require attention for this vendor.</div>}
        </section>
      )}

      {tab === "copilot" && (
        <section className="card flex max-w-[760px] flex-col gap-3.5 p-5">
          <div className="flex flex-col gap-1">
            <h2 className="m-0 text-[16px] font-semibold">Ask Copilot with this vendor as context</h2>
            <p className="m-0 leading-normal text-muted">Answers are limited to {vendor.name} documentation and cite source pages.</p>
          </div>
          <div className="flex flex-col gap-1.5">
            {[
              `What compliance documentation is currently outdated for ${vendor.name}?`,
              "Which documents need review, and why?",
              ...(comps[0] ? [`Which documents for ${comps[0].name} are older than three years?`] : []),
              "Which lot numbers appear on the Quality Certificate?",
            ].map((q) => (
              <Link
                key={q}
                href={copilotHref(q)}
                className="rounded-md border border-line bg-subtle px-3 py-2.5 text-left text-[14px] text-ink no-underline hover:border-sage hover:bg-paper hover:text-ink"
              >
                {q}
              </Link>
            ))}
          </div>
        </section>
      )}
      {finding && <FindingDrawer finding={finding} onClose={() => setOpenFinding(null)} />}
    </Page>
  );
}

/** Owners get this vendor's (or component's) alerts first. Admin-only on the server. */
function OwnersPanel({ vendorId, components }: { vendorId: string; components: { id: string; name: string }[] }) {
  const me = useMe();
  const isAdmin = me.data?.role === "admin";
  const owners = useOwners({}, isAdmin);
  const users = useUsers(isAdmin);
  const assign = useAssignOwner();
  const remove = useRemoveOwner();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [userId, setUserId] = useState("");
  const [subject, setSubject] = useState("vendor");
  const [removing, setRemoving] = useState<string | null>(null);
  const compIds = new Set(components.map((c) => c.id));
  const mine = (owners.data ?? []).filter((o) => o.vendor_id === vendorId || (o.component_id && compIds.has(o.component_id)));
  const compName = (id: string | null) => components.find((c) => c.id === id)?.name;

  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Owners</h2>
        {isAdmin && (
          <button className="btn-link" onClick={() => setAdding(true)}>
            + Assign owner
          </button>
        )}
      </div>
      {!isAdmin && <p className="m-0 p-4 text-[13.5px] text-muted">Owners receive this vendor&apos;s alerts first. Only Administrators view and assign them.</p>}
      {isAdmin &&
        mine.map((o) => (
          <div key={o.id} className="flex items-center justify-between gap-3 border-b border-line-soft px-4 py-2.5 last:border-b-0">
            <span className="flex flex-col">
              <span className="font-medium">{o.user_name}</span>
              <span className="text-xs text-muted">{o.component_id ? `Component: ${compName(o.component_id)}` : "Whole vendor"} · since {fmtDate(o.created_at)}</span>
            </span>
            <button className="btn-danger btn-sm" onClick={() => setRemoving(o.id)}>
              Remove
            </button>
          </div>
        ))}
      {isAdmin && owners.isSuccess && !mine.length && <p className="m-0 p-4 text-[13.5px] text-muted">No owners: alerts go to everyone with the alert policy&apos;s role.</p>}
      {adding && (
        <ReasonDialog
          title="Assign an owner"
          intro={
            <div className="flex flex-col gap-3">
              <label className="field-label">
                Person
                <select className="select text-[14px]" value={userId} onChange={(e) => setUserId(e.target.value)}>
                  <option value="">Choose…</option>
                  {users.data
                    ?.filter((u) => u.is_active)
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.full_name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="field-label">
                Responsible for
                <select className="select text-[14px]" value={subject} onChange={(e) => setSubject(e.target.value)}>
                  <option value="vendor">The whole vendor</option>
                  {components.map((c) => (
                    <option key={c.id} value={c.id}>
                      Component: {c.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          }
          confirmLabel="Assign"
          onClose={() => setAdding(false)}
          onSubmit={async ({ reason }) => {
            if (!userId) throw new Error("Choose a person.");
            await assign.mutateAsync({
              user_id: userId,
              vendor_id: subject === "vendor" ? vendorId : null,
              component_id: subject === "vendor" ? null : subject,
              reason,
            });
            toast("Owner assigned. Recorded in audit trail.");
          }}
        />
      )}
      {removing && (
        <ReasonDialog
          title="Remove this owner?"
          confirmLabel="Remove"
          danger
          onClose={() => setRemoving(null)}
          onSubmit={async ({ reason }) => {
            await remove.mutateAsync({ id: removing, reason });
            toast("Owner removed. Recorded in audit trail.");
          }}
        />
      )}
    </section>
  );
}
