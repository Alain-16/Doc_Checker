"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useCrumbs } from "@/components/shell/crumbs";
import { appliesTo, ParamList, POLICY_EDITORS, SEVERITY_LABEL, type DraftItem } from "@/components/rules";
import { Badge, ErrorNote, SkeletonBlock } from "@/components/ui/badge";
import { ReasonDialog } from "@/components/ui/dialog";
import { Page } from "@/components/ui/page";
import { useToast } from "@/components/ui/toast";
import { api, call, errorMessage, type Schemas } from "@/lib/api/client";
import { keys, useClarifyDraft, useConfirmDraft, useCreateDraft, useMe } from "@/lib/api/hooks";
import { humanize } from "@/lib/format";

const STARTERS = [
  "Technical Support Bulletins must be reviewed every 3 years. Warn QA six months before they become overdue.",
  "Every Quality Certificate must contain at least one lot number.",
  "If a lot number exists, a manufacturing date must also exist.",
  "Documents with extraction confidence below 80% must be sent for human review.",
  "Compliance Bulletins must be reviewed when the regulatory risk is significant.",
];

/**
 * QA writes the policy in plain language → POST /rule-drafts (an LLM structures it into rules)
 * → QA answers any questions (clarify) → QA signs the ready rules into force (confirm).
 * The draft id lives in the URL, so a reload resumes the same draft.
 */
export default function CreateRulePage() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const qc = useQueryClient();
  const me = useMe();
  const draftId = params.get("draft");
  const [typed, setPolicy] = useState<string | null>(null);
  const [answers, setAnswers] = useState("");
  const [showJson, setShowJson] = useState<Record<number, boolean>>({});
  const [selected, setSelected] = useState<number[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  useCrumbs([{ label: "Rule Engine", href: "/rules" }, { label: "Create Rule" }]);

  const draft = useQuery({
    queryKey: keys.draft(draftId ?? "none"),
    queryFn: () => call(api.GET("/rule-drafts/{draft_id}", { params: { path: { draft_id: draftId! } } })),
    enabled: !!draftId,
    staleTime: Infinity,
  });
  const create = useCreateDraft();
  const clarify = useClarifyDraft();
  const confirm = useConfirmDraft();

  // Until the user types, the text box shows the draft's own policy (reload / shared link).
  const policy = typed ?? draft.data?.source_text ?? "";

  const showDraft = (d: Schemas["DraftOut"]) => {
    qc.setQueryData(keys.draft(d.id), d);
    setSelected(null);
    setAnswers("");
    router.replace(`/rules/new?draft=${d.id}`, { scroll: false });
  };

  const items = (draft.data?.items ?? []) as DraftItem[];
  const readyIdx = items.map((it, i) => (it.status === "ready" ? i : -1)).filter((i) => i >= 0);
  const chosen = selected ?? readyIdx;
  const questions = items.flatMap((it) => (it.status === "needs_clarification" ? (it.questions ?? []) : []));
  const working = create.isPending || clarify.isPending;
  const confirmed = draft.data?.status === "confirmed";

  if (me.data && !POLICY_EDITORS.includes(me.data.role)) {
    return (
      <Page>
        <ErrorNote title="Only Compliance Specialists and Admins create rules." error="Ask one of them to add this policy." />
      </Page>
    );
  }

  return (
    <Page>
      <div className="flex flex-col gap-1">
        <h1 className="m-0 text-[24px] font-semibold">Create rule</h1>
        <p className="m-0 text-muted">Nothing is enforced until an authorized user approves the rule.</p>
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,460px),1fr))] items-start gap-4">
        <section className="card flex flex-col gap-3 p-[18px]">
          <label htmlFor="policy" className="text-[16px] font-semibold">
            Describe your compliance policy
          </label>
          <span className="-mt-1.5 text-[13.5px] text-muted">Write it as you would in an SOP. No syntax required. Several rules in one text are fine.</span>
          <textarea
            id="policy"
            rows={5}
            value={policy}
            onChange={(e) => setPolicy(e.target.value)}
            placeholder={STARTERS[0]}
            className="resize-y rounded-md border border-line-strong bg-white p-3 text-sm leading-[1.55] text-ink"
          />
          <div className="flex flex-wrap gap-2">
            <button
              className="btn-primary px-4 py-2"
              disabled={policy.trim().length < 10 || working}
              onClick={() => create.mutate(policy.trim(), { onSuccess: showDraft, onError: (e) => toast(errorMessage(e), "error") })}
            >
              {draftId ? "Reinterpret" : "Interpret Rule"}
            </button>
            <Link href="/rules" className="btn-secondary px-3.5 py-2 font-normal no-underline">
              Cancel
            </Link>
          </div>
          <div className="mt-1 flex flex-col gap-1.5">
            <span className="text-xs font-semibold text-muted-2">Examples</span>
            {STARTERS.map((t) => (
              <button
                key={t}
                onClick={() => setPolicy(t)}
                className="cursor-pointer rounded-md border border-line bg-subtle px-2.5 py-2 text-left text-[13.5px] leading-[1.45] text-ink hover:border-sage"
              >
                “{t}”
              </button>
            ))}
          </div>
        </section>

        <div className="flex min-w-0 flex-col gap-3.5">
          {working && <SkeletonBlock label="Interpreting policy… (an AI model reads it; this can take up to a minute)" />}
          {!working && !draftId && (
            <div className="rounded-lg border border-dashed border-line-strong p-7 text-center leading-[1.55] text-muted">
              The system interpretation will appear here. You will review it, see what it would flag in today&apos;s documents, and approve it before anything changes.
            </div>
          )}
          {!working && draft.isPending && draftId && <SkeletonBlock label="Loading draft…" />}
          {draft.isError && <ErrorNote error={draft.error} />}

          {!working &&
            items.map((it, i) => (
              <DraftItemCard
                key={i}
                item={it}
                selectable={it.status === "ready" && !confirmed}
                selected={chosen.includes(i)}
                onSelect={(on) => setSelected(on ? [...chosen, i] : chosen.filter((x) => x !== i))}
                showJson={!!showJson[i]}
                onToggleJson={() => setShowJson((s) => ({ ...s, [i]: !s[i] }))}
              />
            ))}

          {!working && draft.data && questions.length > 0 && !confirmed && (
            <section className="card flex flex-col gap-2.5 p-4">
              <span className="font-semibold">Answer the open questions</span>
              <ul className="m-0 pl-[18px] text-[13.5px] leading-[1.6] text-muted-2">
                {questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
              <textarea
                rows={3}
                value={answers}
                onChange={(e) => setAnswers(e.target.value)}
                placeholder="Your answers, in plain language"
                className="resize-y rounded-md border border-line-strong bg-white p-2.5 text-[14px]"
              />
              <button
                className="btn-primary self-start"
                disabled={answers.trim().length < 2}
                onClick={() =>
                  clarify.mutate({ id: draft.data.id, answers: answers.trim() }, { onSuccess: showDraft, onError: (e) => toast(errorMessage(e), "error") })
                }
              >
                Send answers
              </button>
            </section>
          )}

          {!working && draft.data && !confirmed && (
            <div className="card flex flex-wrap items-center gap-2 px-3.5 py-3">
              <span className="text-xs text-muted">
                {readyIdx.length ? `${chosen.length} of ${readyIdx.length} ready rules selected` : "No rule is ready to approve yet."}
              </span>
              <span className="flex-1" />
              <Link href="/rules" className="cursor-pointer border-none bg-transparent text-[14px] text-muted underline">
                Cancel
              </Link>
              {chosen.length > 0 ? (
                <button className="btn-primary px-4 py-2" onClick={() => setConfirming(true)}>
                  Approve &amp; Activate
                </button>
              ) : (
                <span title="Resolve the questions first" className="rounded-md bg-[#E4DFD3] px-4 py-2 text-[14px] font-medium text-muted">
                  Approve &amp; Activate — nothing ready
                </span>
              )}
            </div>
          )}
          {confirmed && (
            <div className="rounded-md border border-[#BCD4B2] bg-[#E6EFE0] px-3.5 py-3 text-ok">
              ✓ This draft has been signed into force. <Link href="/rules">Back to the rule list</Link>
            </div>
          )}
        </div>
      </div>

      {confirming && draft.data && (
        <ReasonDialog
          title={`Approve and activate ${chosen.length === 1 ? `“${items[chosen[0]!]?.name ?? "rule"}”` : `${chosen.length} rules`}?`}
          intro={
            <>
              Activation re-evaluates every document&apos;s status and findings in the background. Rules that need new attributes first read the
              documents already on file. Your approval is your electronic signature.
            </>
          }
          confirmLabel="Approve & Activate"
          sign
          onClose={() => setConfirming(false)}
          onSubmit={async ({ reason, password }) => {
            const out = await confirm.mutateAsync({ id: draft.data.id, body: { items: chosen, change_reason: reason, password } });
            toast(
              `Activated ${out.rule_codes.join(", ")}. ${out.reading_documents ? "Reading existing documents for new attributes, then re-evaluating." : "Statuses and findings are being recalculated."}`,
            );
            router.push("/rules");
          }}
        />
      )}
    </Page>
  );
}

function DraftItemCard({
  item,
  selectable,
  selected,
  onSelect,
  showJson,
  onToggleJson,
}: {
  item: DraftItem;
  selectable: boolean;
  selected: boolean;
  onSelect: (on: boolean) => void;
  showJson: boolean;
  onToggleJson: () => void;
}) {
  if (item.status === "invalid") {
    return (
      <section role="alert" className="flex flex-col gap-3 rounded-lg border border-[#E2B2A8] bg-paper p-[18px]">
        <div className="flex items-start gap-2.5">
          <span aria-hidden="true" className="flex size-[22px] shrink-0 items-center justify-center rounded bg-[#F7E1DC] font-semibold text-bad">
            !
          </span>
          <div className="flex flex-col gap-1">
            <span className="text-[16px] font-semibold">{item.name ? `“${item.name}” cannot be automated as written.` : "This policy cannot currently be automated exactly as written."}</span>
            <span className="leading-normal text-muted-2">The system will not approximate it. Clarify the part below so it can be evaluated from stored document data.</span>
          </div>
        </div>
        {item.quote && <div className="border-l-[3px] border-[#B5503F] bg-[#FBF1EE] px-3 py-2 text-[14px] leading-normal">“{item.quote}”</div>}
        <ul className="m-0 pl-[18px] text-[13.5px] leading-[1.6] text-muted-2">
          {(item.problems ?? []).map((p) => (
            <li key={p}>{p}</li>
          ))}
          <li>Rewrite as a measurable condition on a supported field — for example “older than 3 years”, “lot number is present”, or “confidence below 80%”.</li>
        </ul>
      </section>
    );
  }

  return (
    <section className="card overflow-hidden" style={selected ? { borderColor: "#1E3B2F" } : undefined}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
        <div className="flex items-start gap-2.5">
          {selectable && (
            <input type="checkbox" aria-label={`Approve ${item.name}`} checked={selected} onChange={(e) => onSelect(e.target.checked)} className="mt-1 size-4 accent-forest" />
          )}
          <div className="flex flex-col gap-0.5">
            <span className="eyebrow">System interpretation · requires your review</span>
            <span className="text-[16px] font-semibold">{item.name ?? "Untitled rule"}</span>
          </div>
        </div>
        <Badge status={item.status} dashed />
      </div>
      {item.quote && <div className="border-b border-line-soft bg-subtle px-4 py-2.5 text-[13.5px] text-muted-2">From your policy: “{item.quote}”</div>}
      {item.read_back && <p className="m-0 border-b border-line-soft px-4 py-3 leading-[1.55]">{item.read_back}</p>}
      {item.status === "ready" && (
        <dl className="m-0 px-4 py-1.5">
          {[
            ["Applies to", appliesTo({ level: item.level ?? "document", document_type: item.document_type })],
            ["Rule type", humanize(item.kind)],
            ["Judges", humanize(item.level)],
            ["Severity of findings", SEVERITY_LABEL[item.severity ?? ""] ?? humanize(item.severity)],
          ].map(([k, v]) => (
            <div key={k} className="grid grid-cols-[190px_minmax(0,1fr)] gap-3 border-b border-line-faint py-[9px] last:border-b-0">
              <dt className="text-muted">{k}</dt>
              <dd className="m-0 font-medium">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {item.status === "needs_clarification" && (item.questions?.length ?? 0) > 0 && (
        <div className="border-t border-line-soft px-4 py-3">
          <span className="section-label">Questions before this can be a rule</span>
          <ul className="mt-1.5 mb-0 pl-[18px] text-[13.5px] leading-[1.6]">
            {item.questions!.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </div>
      )}
      {((item.new_attributes?.length ?? 0) > 0 || (item.new_document_types?.length ?? 0) > 0) && (
        <div className="border-t border-line-soft bg-subtle px-4 py-2.5 text-[13.5px] text-muted-2">
          {item.new_attributes?.map((a) => (
            <div key={a.name}>
              New key attribute: <strong className="font-medium text-ink">{a.display_name}</strong> — {a.description}
            </div>
          ))}
          {item.new_document_types?.map((t) => (
            <div key={t.name}>
              New document type: <strong className="font-medium text-ink">{t.display_name}</strong>
            </div>
          ))}
          {!!item.documents_to_read && <div>{item.documents_to_read} documents already on file will be read for the new attributes after approval.</div>}
        </div>
      )}
      {(item.warnings?.length ?? 0) > 0 && (
        <div className="border-t border-[#E3CC8A] bg-[#FBF4E2] px-4 py-2.5 text-[13.5px] text-warn">
          {item.warnings!.map((w) => (
            <div key={w}>◆ {w}</div>
          ))}
        </div>
      )}
      {item.preview && (
        <div className="border-t border-line-soft">
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
            <span className="font-semibold">Impact preview</span>
            <span className="rounded border border-dashed border-sage px-2 py-0.5 text-[12.5px] text-[#3E4C43]">Preview only — production statuses are not changed</span>
          </div>
          <div className="grid grid-cols-2 border-y border-line-soft">
            <div className="flex flex-col gap-0.5 border-r border-line-soft px-4 py-3">
              <span className="text-xs text-muted">Evaluated</span>
              <span className="font-mono text-xl font-semibold">{item.preview.checked}</span>
            </div>
            <div className="flex flex-col gap-0.5 px-4 py-3">
              <span className="text-xs text-muted">! Would be flagged</span>
              <span className="font-mono text-xl font-semibold text-bad">{item.preview.would_flag}</span>
            </div>
          </div>
          {item.preview.examples.length > 0 && (
            <ul className="m-0 list-none px-4 py-2">
              {item.preview.examples.map((ex) => (
                <li key={ex} className="border-b border-line-faint py-1.5 text-[13.5px] last:border-b-0">
                  {ex}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {item.status === "ready" && (
        <div className="border-t border-line-soft px-4 py-2.5">
          <button className="btn-link" onClick={onToggleJson}>
            {showJson ? "Hide technical definition" : "View technical definition"}
          </button>
          {showJson && (
            <>
              <div className="mt-2 rounded-md border border-line-soft">
                <ParamList params={item.parameters ?? {}} />
              </div>
              <pre className="mt-2.5 mb-0 overflow-auto rounded-md bg-forest p-3 font-mono text-[12.5px] leading-[1.55] text-[#E9E3D4]">
                {JSON.stringify({ kind: item.kind, level: item.level, document_type: item.document_type, severity: item.severity, parameters: item.parameters }, null, 2)}
              </pre>
            </>
          )}
        </div>
      )}
    </section>
  );
}
