"use client";

import { useState } from "react";
import { POLICY_EDITORS } from "@/components/rules";
import { Badge, EmptyState, ErrorNote } from "@/components/ui/badge";
import { ReasonDialog } from "@/components/ui/dialog";
import { Page, PageHeader } from "@/components/ui/page";
import { Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { errorMessage, type Schemas } from "@/lib/api/client";
import {
  useAlertPolicies,
  useAlertPolicyHistory,
  useAttributes,
  useCreateAttribute,
  useDocumentTypes,
  useIndustryProfile,
  useInviteUser,
  useMe,
  usePresets,
  useSetDigest,
  useUpdateAlertPolicy,
  useUpdateAttribute,
  useUpdateProfile,
  useUserAction,
  useUsers,
} from "@/lib/api/hooks";
import { fmtDateTime, humanize, ROLE_LABEL } from "@/lib/format";

type TabKey = "attributes" | "types" | "alerts" | "roles" | "general";

export default function SettingsPage() {
  const [tab, setTab] = useState<TabKey>("attributes");
  return (
    <Page max={1200}>
      <PageHeader title="Settings" sub="Administrative configuration. Compliance rules are managed in the Rule Engine." />
      <Tabs
        tabs={[
          { key: "attributes", label: "Key attributes" },
          { key: "types", label: "Document types" },
          { key: "alerts", label: "Alert policies" },
          { key: "roles", label: "Users & roles" },
          { key: "general", label: "General" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "attributes" && <AttributesTab />}
      {tab === "types" && <DocTypesTab />}
      {tab === "alerts" && <AlertPoliciesTab />}
      {tab === "roles" && <RolesTab />}
      {tab === "general" && <GeneralTab />}
    </Page>
  );
}

/* ---------- Key attributes (live: /key-attributes) ---------- */

function AttributesTab() {
  const attrs = useAttributes();
  const me = useMe();
  const update = useUpdateAttribute();
  const toast = useToast();
  const [toggling, setToggling] = useState<Schemas["AttributeOut"] | null>(null);
  const [adding, setAdding] = useState(false);
  const canEdit = POLICY_EDITORS.includes(me.data?.role ?? "");

  if (attrs.isError) return <ErrorNote error={attrs.error} />;
  const core = (attrs.data ?? []).filter((a) => a.attribute_group === "core");
  const org = (attrs.data ?? []).filter((a) => a.attribute_group !== "core");

  return (
    <>
      <section className="card flex flex-col gap-2.5 p-4">
        <div className="flex flex-col gap-0.5">
          <h2 className="card-title">Core document-control attributes</h2>
          <span className="text-[13.5px] text-muted">Always extracted. Cannot be disabled.</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {attrs.isPending && <span className="animate-pulse-soft text-muted">Loading…</span>}
          {core.map((a) => (
            <span key={a.id} title={a.description} className="rounded border border-line-chip bg-sand px-[9px] py-[3px] text-xs">
              {a.display_name}
            </span>
          ))}
          {attrs.isSuccess && !core.length && <span className="text-muted">None configured.</span>}
        </div>
      </section>
      <section className="card overflow-hidden">
        <div className="flex flex-col gap-0.5 border-b border-line px-4 py-3.5">
          <div className="flex items-center justify-between gap-2">
            <h2 className="card-title">Organization key attributes</h2>
            {canEdit && (
              <button className="btn-secondary btn-sm" onClick={() => setAdding(true)}>
                + Add attribute
              </button>
            )}
          </div>
          <span className="text-[13.5px] text-muted">
            Extracted only where a document explicitly states them. Turning one back on reads the documents that missed it.
            {!canEdit && " Only Compliance Specialists and Admins change them."}
          </span>
        </div>
        {org.map((a) => (
          <div key={a.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-line-soft px-4 py-3 last:border-b-0">
            <div className="flex flex-col gap-0.5">
              <span className="font-medium">
                {a.display_name}
                {a.required && <span className="ml-2 text-[12px] font-normal text-review">required</span>}
              </span>
              <span className="text-xs text-muted">
                {a.description} · {humanize(a.attribute_group)} · {humanize(a.value_type)} · Found in: {a.document_type ? humanize(a.document_type) : "all document types"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-16 text-right text-xs text-muted">{a.active ? "Extracting" : "Off"}</span>
              <button
                role="switch"
                aria-checked={a.active}
                aria-label={a.display_name}
                disabled={!canEdit}
                onClick={() => setToggling(a)}
                className="relative h-[22px] w-[38px] cursor-pointer rounded-[11px] border-none p-0 disabled:cursor-not-allowed disabled:opacity-60"
                style={{ background: a.active ? "#1E3B2F" : "#CBC2AE" }}
              >
                <span className="absolute top-0.5 size-[18px] rounded-full bg-paper transition-[left] duration-150" style={{ left: a.active ? 18 : 2 }} />
              </button>
            </div>
          </div>
        ))}
        {attrs.isSuccess && !org.length && <EmptyState title="No organization attributes yet." text="They are added when a signed rule needs one, or by an editor." />}
      </section>
      {adding && <AddAttributeDialog onClose={() => setAdding(false)} />}
      {toggling && (
        <ReasonDialog
          title={`${toggling.active ? "Stop" : "Start"} extracting “${toggling.display_name}”?`}
          intro={toggling.active ? "Values already read are kept. New documents won't be read for it." : "Documents already on file are read for it automatically."}
          confirmLabel={toggling.active ? "Turn off" : "Turn on"}
          onClose={() => setToggling(null)}
          onSubmit={async ({ reason }) => {
            await update.mutateAsync({ id: toggling.id, body: { active: !toggling.active, reason } });
            toast(`${toggling.display_name} ${toggling.active ? "extraction disabled. Existing values are retained." : "extraction enabled."}`);
          }}
        />
      )}
    </>
  );
}

/* ---------- Document types (live: /document-types) ---------- */

function DocTypesTab() {
  const types = useDocumentTypes();
  if (types.isError) return <ErrorNote error={types.error} />;
  return (
    <section className="card overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse">
        <thead>
          <tr>
            <th className="th">Document type</th>
            <th className="th">Origin</th>
            <th className="th text-right">Current documents</th>
            <th className="th text-right">Active rules</th>
            <th className="th">Status</th>
          </tr>
        </thead>
        <tbody>
          {types.data?.map((t) => (
            <tr key={t.id} style={{ opacity: t.active ? 1 : 0.6 }}>
              <td className="td py-2.5">
                <div className="font-medium">{t.display_name}</div>
                <div className="max-w-[460px] text-xs text-muted">{t.description}</div>
              </td>
              <td className="td py-2.5">{humanize(t.origin)}</td>
              <td className="td py-2.5 text-right font-mono">{t.document_count}</td>
              <td className="td py-2.5 text-right font-mono">{t.active_rules}</td>
              <td className="td py-2.5">
                <Badge status={t.active ? "active" : "archived"} size="sm" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {types.isSuccess && !types.data.length && <EmptyState title="No document types yet." text="Types are discovered from documents, or named by signed rules." />}
      <div className="border-t border-line-soft px-3.5 py-2.5 text-xs text-muted">
        Types are discovered by the classifier from real documents, or created by a signed rule. Retired types come back when a document shows them again.
      </div>
    </section>
  );
}

/* ---------- Alert policies (live: /alert-policies) ---------- */

const EVENT_LABEL: Record<string, string> = {
  finding: "Compliance findings",
  coming_due: "Documents coming due",
  review_overdue: "Review items left open",
};

function AlertPoliciesTab() {
  const policies = useAlertPolicies();
  const me = useMe();
  const canEdit = POLICY_EDITORS.includes(me.data?.role ?? "");
  const [editing, setEditing] = useState<Schemas["PolicyOut"] | null>(null);
  const [history, setHistory] = useState<Schemas["AlertEvent"] | null>(null);
  if (policies.isError) return <ErrorNote error={policies.error} />;
  return (
    <>
      <section className="card overflow-hidden">
        <div className="flex flex-col gap-0.5 border-b border-line px-4 py-3.5">
          <h2 className="card-title">When people are alerted</h2>
          <span className="text-[13.5px] text-muted">Each change is a new signed version. Turning an event off resolves its open alerts at once.</span>
        </div>
        {policies.data?.map((p) => (
          <div key={p.event} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-line-soft px-4 py-3 last:border-b-0">
            <div className="flex flex-col gap-1">
              <span className="flex items-center gap-2 font-medium">
                {EVENT_LABEL[p.event] ?? humanize(p.event)}
                <Badge status={p.enabled ? "active" : "disabled"} size="xs" />
                <span className="font-mono text-[12px] text-muted">v{p.version}</span>
              </span>
              <span className="text-xs text-muted">
                To {ROLE_LABEL[p.audience_role]} · reminder every {p.reminder_days} d · escalate critical after {p.escalate_critical_after_days} d, others after {p.escalate_after_days} d
              </span>
              <span className="font-mono text-[12px] break-all text-muted-2">{JSON.stringify(p.parameters)}</span>
            </div>
            <div className="flex gap-1.5">
              <button className="btn-secondary btn-sm font-normal" onClick={() => setHistory(history === p.event ? null : p.event)}>
                History
              </button>
              {canEdit && (
                <button className="btn-primary btn-sm" onClick={() => setEditing(p)}>
                  Edit
                </button>
              )}
            </div>
            {history === p.event && <PolicyHistory event={p.event} />}
          </div>
        ))}
        {policies.isSuccess && !policies.data.length && <EmptyState title="No alert policies configured." />}
      </section>
      {editing && <EditPolicyDialog policy={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function PolicyHistory({ event }: { event: Schemas["AlertEvent"] }) {
  const versions = useAlertPolicyHistory(event);
  return (
    <div className="col-span-2 flex flex-col gap-1 rounded-md border border-line-soft bg-subtle p-2.5 text-xs">
      {versions.isPending && <span className="text-muted">Loading…</span>}
      {[...(versions.data ?? [])].reverse().map((v) => (
        <div key={v.version} className="grid grid-cols-[48px_150px_minmax(0,1fr)] gap-2">
          <span className="font-mono">v{v.version}</span>
          <span className="font-mono text-muted">{fmtDateTime(v.created_at)}</span>
          <span>
            {v.enabled ? "On" : "Off"} · {ROLE_LABEL[v.audience_role]} — {v.change_reason}
          </span>
        </div>
      ))}
    </div>
  );
}

function EditPolicyDialog({ policy, onClose }: { policy: Schemas["PolicyOut"]; onClose: () => void }) {
  const update = useUpdateAlertPolicy();
  const toast = useToast();
  const [enabled, setEnabled] = useState(policy.enabled);
  const [role, setRole] = useState(policy.audience_role);
  const [reminder, setReminder] = useState(policy.reminder_days);
  const [critical, setCritical] = useState(policy.escalate_critical_after_days);
  const [others, setOthers] = useState(policy.escalate_after_days);
  const [json, setJson] = useState(JSON.stringify(policy.parameters, null, 2));
  let parsed: Record<string, unknown> | null = null;
  try {
    const p = JSON.parse(json);
    parsed = p && typeof p === "object" && !Array.isArray(p) ? p : null;
  } catch {}
  const num = (set: (n: number) => void) => (e: React.ChangeEvent<HTMLInputElement>) => set(Math.max(1, Number(e.target.value) || 1));
  return (
    <ReasonDialog
      title={`Alert policy — ${EVENT_LABEL[policy.event] ?? humanize(policy.event)}`}
      intro={
        <div className="grid grid-cols-2 gap-3">
          <label className="col-span-2 flex items-center gap-2 text-[14px]">
            <input type="checkbox" className="size-4 accent-forest" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Raise alerts for this event
          </label>
          <label className="field-label col-span-2">
            Audience role (when nobody owns the vendor or component)
            <select className="select text-[14px]" value={role} onChange={(e) => setRole(e.target.value as Schemas["UserRole"])}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </label>
          <label className="field-label">
            Reminder every (days)
            <input className="input font-normal" type="number" min={1} value={reminder} onChange={num(setReminder)} />
          </label>
          <label className="field-label">
            Escalate critical after (days)
            <input className="input font-normal" type="number" min={1} value={critical} onChange={num(setCritical)} />
          </label>
          <label className="field-label">
            Escalate others after (days)
            <input className="input font-normal" type="number" min={1} value={others} onChange={num(setOthers)} />
          </label>
          <label className="field-label col-span-2">
            Event settings
            <textarea className="input min-h-[90px] font-mono text-xs font-normal" value={json} onChange={(e) => setJson(e.target.value)} spellCheck={false} />
            {!parsed && <span className="font-normal text-bad">Not a valid JSON object.</span>}
          </label>
        </div>
      }
      confirmLabel="Sign new version"
      sign
      onClose={onClose}
      onSubmit={async ({ reason, password }) => {
        if (!parsed) throw new Error("Fix the event settings first: they must be a JSON object.");
        await update.mutateAsync({
          event: policy.event,
          body: {
            enabled,
            audience_role: role,
            reminder_days: reminder,
            escalate_critical_after_days: critical,
            escalate_after_days: others,
            parameters: parsed,
            change_reason: reason,
            password,
          },
        });
        toast("Alert policy saved as a new signed version.");
      }}
    />
  );
}

/* ---------- Add a key attribute (live: POST /key-attributes) ---------- */

const VALUE_TYPES: Schemas["AttributeValueType"][] = ["text", "text_list", "date", "status", "number", "records"];

function AddAttributeDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateAttribute();
  const types = useDocumentTypes();
  const toast = useToast();
  const [display, setDisplay] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [valueType, setValueType] = useState<Schemas["AttributeValueType"]>("text");
  const [query, setQuery] = useState("");
  const [docType, setDocType] = useState("");
  const [fields, setFields] = useState("");
  const [required, setRequired] = useState(false);
  const slug = name || display.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return (
    <ReasonDialog
      title="Add a key attribute"
      intro={
        <div className="flex flex-col gap-3">
          <span>Documents already on file are read for it automatically.</span>
          <label className="field-label">
            Display name
            <input className="input font-normal" value={display} onChange={(e) => setDisplay(e.target.value)} placeholder="Liability cover" />
          </label>
          <label className="field-label">
            Key (lower_snake_case; can&apos;t change later)
            <input className="input font-mono font-normal" value={slug} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field-label">
            What to look for (the unit, for a number)
            <textarea className="input min-h-[60px] font-normal" value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <label className="field-label">
            Passage to search for in each document
            <input className="input font-normal" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="insurance liability coverage amount" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="field-label">
              Value type
              <select className="select text-[14px]" value={valueType} onChange={(e) => setValueType(e.target.value as Schemas["AttributeValueType"])}>
                {VALUE_TYPES.map((v) => (
                  <option key={v} value={v}>
                    {humanize(v)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-label">
              Document type
              <select className="select text-[14px]" value={docType} onChange={(e) => setDocType(e.target.value)}>
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
          </div>
          {valueType === "records" && (
            <label className="field-label">
              Row fields (comma-separated)
              <input className="input font-mono font-normal" value={fields} onChange={(e) => setFields(e.target.value)} placeholder="lot_number, manufacturing_date" />
            </label>
          )}
          <label className="flex items-center gap-2 text-[14px]">
            <input type="checkbox" className="size-4 accent-forest" checked={required} onChange={(e) => setRequired(e.target.checked)} />
            Required — a document that doesn&apos;t state it gets a finding
          </label>
        </div>
      }
      confirmLabel="Add attribute"
      onClose={onClose}
      onSubmit={async ({ reason }) => {
        await create.mutateAsync({
          name: slug,
          display_name: display,
          description,
          value_type: valueType,
          search_query: query,
          document_type: docType || null,
          record_fields: valueType === "records" ? fields.split(",").map((f) => f.trim()).filter(Boolean) : [],
          required,
          reason,
        });
        toast(`${display} added. Existing documents are being read for it.`);
      }}
    />
  );
}

/* ---------- Users & roles (live: /users, Admin only) ---------- */

const ROLES: Schemas["UserRole"][] = ["qa_analyst", "compliance_specialist", "admin"];
// What each role can do, as enforced by the backend's route dependencies.
const PERM_COLS = ["Upload & follow files", "Ask Copilot", "Acknowledge alerts", "Create & change rules", "Edit key attributes & alert policies", "Manage users & owners"];
const PERMS: Record<string, boolean[]> = {
  qa_analyst: [true, true, true, false, false, false],
  compliance_specialist: [true, true, true, true, true, false],
  admin: [true, true, true, true, true, true],
};

type UserAction = { kind: "role"; user: Schemas["UserOut"]; role: Schemas["UserRole"] } | { kind: "unlock" | "deactivate"; user: Schemas["UserOut"] };

function RolesTab() {
  const me = useMe();
  const isAdmin = me.data?.role === "admin";
  const users = useUsers(isAdmin);
  const act = useUserAction();
  const toast = useToast();
  const [action, setAction] = useState<UserAction | null>(null);

  return (
    <>
      {isAdmin ? (
        <>
          <InviteForm />
          <section className="card overflow-x-auto">
            {users.isError && <ErrorNote error={users.error} />}
            <table className="w-full min-w-[860px] border-collapse">
              <thead>
                <tr>
                  {["User", "Role", "Status", "Last sign-in"].map((h) => (
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
                {users.data?.map((u) => {
                  const self = u.email === me.data?.email;
                  return (
                    <tr key={u.id} style={{ opacity: u.is_active ? 1 : 0.6 }}>
                      <td className="td py-2.5">
                        <div className="font-medium">
                          {u.full_name}
                          {self && <span className="ml-1.5 text-xs font-normal text-muted">(you)</span>}
                        </div>
                        <div className="text-xs text-muted">{u.email}</div>
                      </td>
                      <td className="td py-2.5">
                        <select
                          aria-label={`Role of ${u.full_name}`}
                          className="select"
                          value={u.role}
                          disabled={self || !u.is_active}
                          onChange={(e) => setAction({ kind: "role", user: u, role: e.target.value as Schemas["UserRole"] })}
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {ROLE_LABEL[r]}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="td py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {!u.is_active ? (
                            <Badge status="disabled" size="sm" style={{ label: "Deactivated", fg: "#4F5A53", bg: "#ECEAE3", bd: "#D2CEC2", icon: "○" }} />
                          ) : u.locked_at ? (
                            <Badge status="stale" size="sm" style={{ label: "Locked", fg: "#9A2B1E", bg: "#F7E1DC", bd: "#E2B2A8", icon: "!" }} />
                          ) : !u.invite_accepted ? (
                            <Badge status="pending" size="sm" style={{ label: "Invited", fg: "#8A4B12", bg: "#F4E6D6", bd: "#DDBF9C", icon: "✉" }} />
                          ) : (
                            <Badge status="active" size="sm" />
                          )}
                          {u.is_active && u.invite_accepted && !u.mfa_enabled && <span className="text-[12px] text-review">No 2FA yet</span>}
                        </div>
                      </td>
                      <td className="td py-2.5 font-mono text-xs">{fmtDateTime(u.last_login_at)}</td>
                      <td className="td py-2.5 text-right whitespace-nowrap">
                        {u.locked_at && u.is_active && (
                          <button className="btn-secondary btn-sm mr-1.5" onClick={() => setAction({ kind: "unlock", user: u })}>
                            Unlock
                          </button>
                        )}
                        {u.is_active && !self && (
                          <button className="btn-danger btn-sm" onClick={() => setAction({ kind: "deactivate", user: u })}>
                            Deactivate
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        </>
      ) : (
        <div className="card px-4 py-3 text-muted">User management is limited to Administrators. Your role: {ROLE_LABEL[me.data?.role ?? ""] ?? "—"}.</div>
      )}

      <section className="card overflow-x-auto">
        <table className="w-full min-w-[820px] border-collapse">
          <thead>
            <tr>
              <th className="th">Role</th>
              {PERM_COLS.map((c) => (
                <th key={c} className="th px-2.5 text-center tracking-[.04em]">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROLES.map((role) => (
              <tr key={role}>
                <td className="td py-2.5">
                  <div className="font-medium">{ROLE_LABEL[role]}</div>
                  {users.data && <div className="text-xs text-muted">{users.data.filter((u) => u.role === role && u.is_active).length} users</div>}
                </td>
                {PERMS[role]!.map((on, i) => (
                  <td key={i} className="td p-2.5 text-center">
                    <span
                      role="img"
                      aria-label={`${PERM_COLS[i]} for ${ROLE_LABEL[role]}: ${on ? "allowed" : "not allowed"}`}
                      className="inline-flex size-5 items-center justify-center rounded border-[1.5px] text-xs leading-none text-page"
                      style={{ background: on ? "#1E3B2F" : "#FFFDF9", borderColor: on ? "#1E3B2F" : "#CBC2AE" }}
                    >
                      {on ? "✓" : ""}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="border-t border-line-soft px-3.5 py-2.5 text-xs text-muted">
          Permissions are fixed per role by the server. Rule changes are electronically signed; role changes are recorded in the audit trail.
        </div>
      </section>

      {action && (
        <ReasonDialog
          title={
            action.kind === "role"
              ? `Change ${action.user.full_name}'s role to ${ROLE_LABEL[action.role]}?`
              : action.kind === "unlock"
                ? `Unlock ${action.user.full_name}?`
                : `Deactivate ${action.user.full_name}?`
          }
          intro={action.kind === "deactivate" ? "They are signed out everywhere and can no longer sign in. The account is kept for the audit trail." : undefined}
          confirmLabel={action.kind === "role" ? "Change role" : action.kind === "unlock" ? "Unlock" : "Deactivate"}
          danger={action.kind === "deactivate"}
          onClose={() => setAction(null)}
          onSubmit={async ({ reason }) => {
            await act.mutateAsync(action.kind === "role" ? { kind: "role", id: action.user.id, role: action.role, reason } : { kind: action.kind, id: action.user.id, reason });
            toast("Saved. Change recorded in audit trail.");
          }}
        />
      )}
    </>
  );
}

function InviteForm() {
  const invite = useInviteUser();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Schemas["UserRole"]>("qa_analyst");
  return (
    <form
      className="card flex flex-wrap items-end gap-2.5 px-4 py-3.5"
      onSubmit={(e) => {
        e.preventDefault();
        invite.mutate(
          { email, full_name: name, role },
          {
            onSuccess: () => {
              toast(`Invitation emailed to ${email}.`);
              setEmail("");
              setName("");
            },
            onError: (err) => toast(errorMessage(err), "error"),
          },
        );
      }}
    >
      <span className="w-full font-semibold">Invite a user</span>
      <label className="field-label flex-[1_1_200px]">
        Full name
        <input className="input font-normal" required value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field-label flex-[1_1_220px]">
        Work email
        <input className="input font-normal" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="field-label">
        Role
        <select className="select text-[14px]" value={role} onChange={(e) => setRole(e.target.value as Schemas["UserRole"])}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABEL[r]}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" className="btn-primary" disabled={invite.isPending}>
        {invite.isPending ? "Sending…" : "Send invitation"}
      </button>
    </form>
  );
}

/* ---------- General ---------- */

function GeneralTab() {
  const me = useMe();
  const profile = useIndustryProfile();
  const setDigest = useSetDigest();
  const toast = useToast();
  const [digest, setDigestValue] = useState<Schemas["DigestFrequency"] | null>(null);
  const [editingProfile, setEditingProfile] = useState(false);
  const value = digest ?? me.data?.digest_frequency ?? "daily";

  return (
    <section className="card grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-4 p-4">
      <label className="field-label">
        Warning digest (your email summary of non-urgent alerts)
        <select className="select text-[14px]" value={value} onChange={(e) => setDigestValue(e.target.value as Schemas["DigestFrequency"])}>
          <option value="daily">Daily</option>
          <option value="weekly">Weekly on Monday</option>
          <option value="none">Off — in-app only</option>
        </select>
        <span className="font-normal text-muted">Critical alerts and escalations are always emailed at once.</span>
      </label>
      <div className="flex flex-col gap-1.5 text-xs">
        <span className="flex items-center justify-between font-medium text-muted-2">
          Industry profile
          {me.data?.role === "admin" && (
            <button className="btn-link font-normal" onClick={() => setEditingProfile(true)}>
              Change
            </button>
          )}
        </span>
        {profile.data ? (
          <span className="leading-normal">
            <strong className="font-medium">{profile.data.industry}</strong> — {profile.data.description}
            <br />
            <span className="text-muted">
              Labels: {profile.data.vendor_label} / {profile.data.component_label}
            </span>
          </span>
        ) : (
          <span className="text-muted">{profile.isError ? errorMessage(profile.error) : "Loading…"}</span>
        )}
      </div>
      <dl className="col-span-full m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3.5 gap-y-1.5 border-t border-line-soft pt-3.5 text-[13.5px]">
        <dt className="text-muted">Signed in as</dt>
        <dd className="m-0">
          {me.data?.full_name} · {me.data?.email} · {ROLE_LABEL[me.data?.role ?? ""]}
        </dd>
        <dt className="text-muted">Evaluation schedule</dt>
        <dd className="m-0">On every upload and rule change; scheduled re-evaluation by the worker</dd>
        <dt className="text-muted">Audit trail</dt>
        <dd className="m-0">Enabled · every change records who, when and why</dd>
      </dl>
      {editingProfile && profile.data && <ProfileDialog profile={profile.data} onClose={() => setEditingProfile(false)} />}
      <div>
        <button
          className="btn-primary px-4 py-2"
          disabled={!digest || digest === me.data?.digest_frequency || setDigest.isPending}
          onClick={() =>
            setDigest.mutate(value, {
              onSuccess: () => {
                setDigestValue(null);
                toast("Settings saved. Change recorded in audit trail.");
              },
              onError: (e) => toast(errorMessage(e), "error"),
            })
          }
        >
          Save settings
        </button>
      </div>
    </section>
  );
}

function ProfileDialog({ profile, onClose }: { profile: Schemas["ProfileOut"]; onClose: () => void }) {
  const presets = usePresets(true);
  const update = useUpdateProfile();
  const toast = useToast();
  const [preset, setPreset] = useState(profile.preset ?? "");
  const base = (preset && presets.data?.[preset]) || profile;
  const [vendorLabel, setVendorLabel] = useState<string | null>(null);
  const [vendorPlural, setVendorPlural] = useState<string | null>(null);
  const [componentLabel, setComponentLabel] = useState<string | null>(null);
  const [componentPlural, setComponentPlural] = useState<string | null>(null);
  const field = (label: string, value: string | null, fallback: string, set: (v: string) => void) => (
    <label className="field-label">
      {label}
      <input className="input font-normal" value={value ?? fallback} onChange={(e) => set(e.target.value)} />
    </label>
  );
  return (
    <ReasonDialog
      title="Industry profile"
      intro={
        <div className="flex flex-col gap-3">
          <span>Applies to documents processed and questions asked from now on; documents already processed keep their types and names.</span>
          <label className="field-label">
            Preset
            <select className="select text-[14px]" value={preset} onChange={(e) => setPreset(e.target.value)}>
              <option value="">Keep current ({profile.industry})</option>
              {Object.entries(presets.data ?? {}).map(([k, p]) => (
                <option key={k} value={k}>
                  {p.industry}
                </option>
              ))}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            {field("Vendor label", vendorLabel, base.vendor_label, setVendorLabel)}
            {field("Vendor label (plural)", vendorPlural, base.vendor_label_plural, setVendorPlural)}
            {field("Component label", componentLabel, base.component_label, setComponentLabel)}
            {field("Component label (plural)", componentPlural, base.component_label_plural, setComponentPlural)}
          </div>
        </div>
      }
      confirmLabel="Save profile"
      onClose={onClose}
      onSubmit={async ({ reason }) => {
        await update.mutateAsync({
          preset: preset || null,
          vendor_label: vendorLabel,
          vendor_label_plural: vendorPlural,
          component_label: componentLabel,
          component_label_plural: componentPlural,
          reason,
        });
        toast("Industry profile saved. Recorded in audit trail.");
      }}
    />
  );
}
