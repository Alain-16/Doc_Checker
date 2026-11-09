"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/api/client";
import { useAcknowledgeAlert, useAlert, useAlerts, useAlertSummary } from "@/lib/api/hooks";
import { fmtDateTime, humanize } from "@/lib/format";

/** The bell: live alert count from /alerts/summary, and the alert inbox with "acknowledge". */
export function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const summary = useAlertSummary();
  const alerts = useAlerts(open);
  const ack = useAcknowledgeAlert();
  const toast = useToast();
  const unread = summary.data?.open ?? 0;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={`Notifications, ${unread} open`}
        aria-expanded={open}
        title="Notifications"
        className="relative flex cursor-pointer rounded-md border border-line bg-paper p-1.5 text-forest hover:bg-sand"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
          <path d="M6 16V11a6 6 0 0112 0v5l1.5 2h-15zM10 20h4" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-[5px] -right-[5px] flex h-[17px] min-w-[17px] items-center justify-center rounded-[9px] bg-bad px-1 text-[11px] font-semibold text-white">
            {unread}
          </span>
        )}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute top-10 right-0 z-30 flex max-h-[480px] w-[380px] flex-col overflow-hidden rounded-lg border border-[#D2CAB6] bg-paper shadow-[0_8px_24px_rgba(30,59,47,.16)]">
            <div className="flex items-baseline justify-between border-b border-line px-3.5 py-2.5">
              <span className="font-semibold">Alerts</span>
              <span className="text-xs text-muted">
                {summary.data ? `${summary.data.open} open · ${summary.data.acknowledged} acknowledged` : ""}
              </span>
            </div>
            <div className="flex-1 overflow-auto">
              {alerts.isPending && <div className="p-3.5 text-muted">Loading alerts…</div>}
              {alerts.isError && <div className="p-3.5 text-bad">{errorMessage(alerts.error)}</div>}
              {alerts.data?.length === 0 && <div className="p-3.5 text-muted">No open alerts. Everything is up to date.</div>}
              {alerts.data?.map((a) => (
                <div key={a.id} className="flex flex-col gap-1.5 border-b border-line-soft px-3.5 py-2.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge status={a.severity} size="xs" />
                    <Badge status={a.status} size="xs" />
                    {a.escalated_at && <span className="text-[12px] font-medium text-bad">Escalated</span>}
                    <span className="ml-auto font-mono text-[12px] text-muted">{fmtDateTime(a.created_at)}</span>
                  </div>
                  <button
                    onClick={() => setExpanded(expanded === a.id ? null : a.id)}
                    aria-expanded={expanded === a.id}
                    className="cursor-pointer border-none bg-transparent p-0 text-left font-medium text-ink hover:underline"
                  >
                    {a.title}
                  </button>
                  <span className="text-[13.5px] leading-normal text-muted-2">{a.message}</span>
                  {expanded === a.id && <AlertDetail id={a.id} onNavigate={() => setOpen(false)} />}
                  <div className="flex items-center gap-2 text-xs text-muted">
                    <span>{humanize(a.event)}</span>
                    {a.status === "open" && (
                      <button
                        className="btn-secondary btn-sm ml-auto"
                        disabled={ack.isPending}
                        onClick={() =>
                          ack.mutate(
                            { id: a.id },
                            {
                              onSuccess: () => {
                                toast("Alert acknowledged. Reminders and escalation stop.");
                                summary.refetch();
                              },
                              onError: (e) => toast(errorMessage(e), "error"),
                            },
                          )
                        }
                      >
                        Acknowledge
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** Alert evidence, where it points, and who was told when (deliveries). */
function AlertDetail({ id, onNavigate }: { id: string; onNavigate: () => void }) {
  const alert = useAlert(id);
  const a = alert.data;
  if (alert.isPending) return <span className="text-xs text-muted">Loading…</span>;
  if (!a) return <span className="text-xs text-bad">{errorMessage(alert.error)}</span>;
  const target = a.finding_id
    ? `/findings?open=${a.finding_id}`
    : a.document_id
      ? `/documents/${a.document_id}`
      : a.vendor_file_id
        ? `/vendor-files/${a.vendor_file_id}`
        : a.vendor_id
          ? `/vendors/${a.vendor_id}`
          : a.event === "review_overdue"
            ? "/review"
            : null;
  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-line-soft bg-subtle p-2 text-[12.5px]">
      {Object.entries(a.evidence).map(([k, v]) => (
        <div key={k} className="grid grid-cols-[100px_minmax(0,1fr)] gap-2">
          <span className="text-muted">{humanize(k)}</span>
          <span className="font-mono break-words">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
        </div>
      ))}
      {a.deliveries.length > 0 && (
        <div className="flex flex-col gap-0.5 border-t border-line-soft pt-1.5">
          <span className="text-muted">Deliveries</span>
          {a.deliveries.map((d, i) => (
            <span key={i} className="font-mono">
              {humanize(d.kind)} · {humanize(d.channel)} · {humanize(d.status)} · {fmtDateTime(d.sent_at ?? d.created_at)}
            </span>
          ))}
        </div>
      )}
      {a.acknowledgement_note && <span>Note: {a.acknowledgement_note}</span>}
      {target && (
        <Link href={target} onClick={onNavigate} className="self-start text-forest underline">
          Open
        </Link>
      )}
    </div>
  );
}
