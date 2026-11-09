"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { AnswerBody, asSources, citeLabel, SourceCards, statusOf, StatusWarnings, type Source } from "@/components/copilot/answer";
import { Badge, ErrorNote } from "@/components/ui/badge";
import { errorMessage, type Schemas } from "@/lib/api/client";
import { askFollowUp, keys, startConversation, useComponents, useConversation, useConversations, useDocument, useVendors } from "@/lib/api/hooks";
import { SinglePage } from "@/components/source-viewer";
import { fmtRelative } from "@/lib/format";

const SUGGESTIONS = [
  "What does the supplier say about natural rubber latex?",
  "Which documents for this component are older than three years?",
  "Do any of those outdated documents discuss coating requirements?",
  "Why was the Technical Support Bulletin flagged?",
  "Which lot numbers appear on the Quality Certificate?",
  "What does the Technical Support Bulletin say about storage?",
  "Are there any missing key document-control fields?",
];

type Message = Schemas["MessageOut"];

/**
 * Compliance Copilot on the real /conversations API. The conversation id is kept in
 * the URL (?c=), so a reload or a shared link reopens it. ?vendor= and ?q= come from
 * "Ask Copilot" buttons elsewhere.
 */
export default function CopilotPage() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const vendors = useVendors();
  const conversationId = params.get("c");
  const conversation = useConversation(conversationId);
  const history = useConversations();

  // ?vendor= may be an id (vendor pages) or a name (sample documents); it applies until the user picks.
  const vendorParam = params.get("vendor");
  const [vendorChoice, setVendorId] = useState<string | null>(null);
  const fromParam = vendorParam
    ? vendors.data?.find((x) => x.id === vendorParam || x.name.toLowerCase() === vendorParam.toLowerCase())?.id
    : undefined;
  const vendorId = vendorChoice ?? fromParam ?? "All";
  const [componentId, setComponentId] = useState("All");
  const components = useComponents(vendorId === "All" ? undefined : vendorId);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cite, setCite] = useState<Source | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);
  const autoAsked = useRef(false);

  const vendorName = vendors.data?.find((v) => v.id === vendorId)?.name;
  const componentName = components.data?.find((c) => c.id === componentId)?.name;
  const context = [vendorName && `Vendor: ${vendorName}`, componentName && `Component: ${componentName}`].filter(Boolean).join(" · ");

  const messages: Message[] = conversation.data?.messages ?? [];
  const busy = pending !== null;

  async function ask(text?: string) {
    const question = (text ?? input).trim();
    if (question.length < 3 || busy) return;
    // The API takes only the question; the chosen context travels inside it so the
    // assistant's understanding step scopes the search.
    const scoped = vendorName ? `Regarding ${vendorName}${componentName ? `, ${componentName}` : ""}: ${question}` : question;
    setPending(question);
    setInput("");
    setError(null);
    setCite(null);
    try {
      if (!conversationId) {
        const created = await startConversation(scoped);
        qc.setQueryData(keys.conversation(created.id), created);
        qc.invalidateQueries({ queryKey: keys.conversations });
        router.replace(`/copilot?c=${created.id}`, { scroll: false });
      } else {
        const reply = await askFollowUp(conversationId, scoped);
        qc.setQueryData(keys.conversation(conversationId), (old: Schemas["ConversationDetailOut"] | undefined) =>
          old
            ? {
                ...old,
                messages: [
                  ...old.messages,
                  { id: `local-${Date.now()}`, role: "user", content: scoped, route: null, sources: [], created_at: new Date().toISOString() },
                  reply,
                ],
              }
            : old,
        );
      }
    } catch (e) {
      setError(errorMessage(e));
      setInput(question);
    } finally {
      setPending(null);
    }
  }

  // "Ask Copilot about …" links arrive with ?q=: ask it once, after the context is applied.
  const q = params.get("q");
  useEffect(() => {
    if (!q || autoAsked.current || conversationId) return;
    if (vendorParam && !vendors.data) return;
    autoAsked.current = true;
    // A one-shot action triggered by arriving from an "Ask Copilot" link, like a click would be.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    ask(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, vendors.data]);

  useEffect(() => {
    const el = chatRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, pending]);

  const newChat = () => {
    setCite(null);
    setError(null);
    router.replace("/copilot", { scroll: false });
  };

  return (
    <div className="flex h-full min-h-0 flex-wrap">
      <section aria-label="Conversation" className="flex h-full min-h-0 min-w-0 flex-[999_1_560px] flex-col">
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line bg-subtle px-5 py-2.5">
          <span className="font-semibold">Compliance Copilot</span>
          <span className="min-w-0 flex-1 truncate text-xs text-muted">Context: {context || "All vendor documentation"}</span>
          {(messages.length > 0 || conversationId) && (
            <button className="btn-secondary btn-sm font-normal" onClick={newChat}>
              New conversation
            </button>
          )}
        </div>
        <div ref={chatRef} className="min-h-0 flex-1 overflow-auto p-5">
          <div className="mx-auto flex max-w-[820px] flex-col gap-4">
            {conversation.isError && <ErrorNote error={conversation.error} title="Could not open this conversation." />}
            {!conversationId && !busy && (
              <div className="flex flex-col gap-3.5 pt-6">
                <div className="flex flex-col gap-1.5">
                  <h1 className="m-0 text-xl font-semibold">Ask about vendor documentation</h1>
                  <p className="m-0 leading-[1.55] text-muted">
                    Answers come from extracted document data and document text, with page citations. Status warnings appear when a source is stale or approaching review.
                  </p>
                </div>
                <div className="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => ask(s)}
                      className="cursor-pointer rounded-md border border-line bg-paper px-[13px] py-[11px] text-left text-[14px] leading-[1.45] text-ink hover:border-sage"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="max-w-[80%] self-end rounded-[8px_8px_2px_8px] bg-forest px-3.5 py-2.5 leading-normal text-page">
                  {m.content}
                </div>
              ) : (
                <BotMessage key={m.id} message={m} onCite={setCite} />
              ),
            )}
            {pending && (
              <>
                <div className="max-w-[80%] self-end rounded-[8px_8px_2px_8px] bg-forest px-3.5 py-2.5 leading-normal text-page">{pending}</div>
                <div className="card flex animate-pulse-soft flex-col gap-2 px-4 py-3.5">
                  <span className="text-xs text-muted">Searching documentation…</span>
                  <div className="skeleton-bar h-[9px] w-[85%]" />
                  <div className="skeleton-bar h-[9px] w-[60%]" />
                </div>
              </>
            )}
            {error && <ErrorNote error={error} title="The question could not be answered." />}
          </div>
        </div>
        <div className="border-t border-line bg-paper px-5 py-3">
          <div className="mx-auto flex max-w-[820px] flex-col gap-1.5">
            <div className="flex items-end gap-2">
              <textarea
                aria-label="Ask a question"
                rows={2}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    ask();
                  }
                }}
                placeholder="Ask about vendors, components, documents or findings…"
                className="flex-1 resize-none rounded-md border border-line-strong bg-white px-3 py-[9px] text-sm leading-normal text-ink"
              />
              <button className="btn-primary px-[18px] py-2.5" disabled={input.trim().length < 3 || busy} onClick={() => ask()}>
                Ask
              </button>
            </div>
            <span className="text-[12.5px] text-muted">Verify cited pages before acting. Copilot does not make compliance decisions.</span>
          </div>
        </div>
      </section>

      <aside className="max-h-full min-h-0 max-w-full flex-[1_1_300px] overflow-auto border-l border-line bg-subtle">
        {cite ? (
          <CitePanel source={cite} onClose={() => setCite(null)} />
        ) : (
          <div className="flex flex-col gap-4 p-4">
            <div className="flex items-baseline justify-between">
              <h2 className="card-title">Context</h2>
              <button
                className="btn-link"
                onClick={() => {
                  setVendorId("All");
                  setComponentId("All");
                }}
              >
                Clear
              </button>
            </div>
            <label className="field-label">
              Vendor
              <select
                className="select text-[14px]"
                value={vendorId}
                onChange={(e) => {
                  setVendorId(e.target.value);
                  setComponentId("All");
                }}
              >
                <option value="All">All</option>
                {vendors.data?.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-label">
              Component
              <select className="select text-[14px]" value={componentId} onChange={(e) => setComponentId(e.target.value)} disabled={vendorId === "All"}>
                <option value="All">All</option>
                {vendorId !== "All" &&
                  components.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </select>
            </label>
            <p className="m-0 text-xs leading-normal text-muted">The context is added to your question, so the assistant searches that vendor&apos;s documentation.</p>
            {(history.data?.length ?? 0) > 0 && (
              <div className="flex flex-col gap-1 border-t border-line pt-3.5">
                <span className="text-xs font-semibold text-muted-2">Your conversations</span>
                {history.data!.slice(0, 12).map((c) => (
                  <Link
                    key={c.id}
                    href={`/copilot?c=${c.id}`}
                    className="flex justify-between gap-2 rounded-md px-2 py-1.5 text-[13.5px] text-ink no-underline hover:bg-paper hover:text-ink"
                    style={{ background: c.id === conversationId ? "#FFFDF9" : undefined, fontWeight: c.id === conversationId ? 600 : 400 }}
                  >
                    <span className="truncate">{c.title}</span>
                    <span className="shrink-0 font-mono text-[12px] text-muted">{fmtRelative(c.created_at)}</span>
                  </Link>
                ))}
              </div>
            )}
            {messages.length > 0 && (
              <div className="flex flex-col gap-1.5 border-t border-line pt-3.5">
                <span className="text-xs font-semibold text-muted-2">Suggested questions</span>
                {SUGGESTIONS.slice(0, 4).map((s) => (
                  <button
                    key={s}
                    onClick={() => ask(s)}
                    disabled={busy}
                    className="cursor-pointer rounded-md border border-line bg-paper px-2.5 py-2 text-left text-[13.5px] leading-[1.4] text-ink hover:border-sage disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

function BotMessage({ message, onCite }: { message: Message; onCite: (s: Source) => void }) {
  const sources = useMemo(() => asSources(message.sources), [message.sources]);
  const noEvidence = sources.length === 0;
  return (
    <article className="card flex flex-col gap-2.5 px-4 py-3.5 leading-[1.55]">
      <div className="flex justify-between gap-2 text-[12.5px] text-muted">
        <span className="font-semibold text-forest">Copilot</span>
        {message.route && <span>{ROUTE_LABEL[message.route] ?? message.route}</span>}
      </div>
      {noEvidence ? (
        <div className="flex flex-col gap-1 rounded-md border border-dashed border-line-strong px-3 py-2.5">
          {message.content.split(/\n+/).map((p, i) => (
            <span key={i} className={i === 0 ? "font-semibold" : "text-[13.5px] text-muted"}>
              {p}
            </span>
          ))}
        </div>
      ) : (
        <AnswerBody content={message.content} sources={sources} onCite={onCite} />
      )}
      <StatusWarnings sources={sources} />
      <SourceCards sources={sources} onCite={onCite} />
    </article>
  );
}

const ROUTE_LABEL: Record<string, string> = {
  content: "From document text",
  aggregate: "From the database",
  findings: "From compliance findings",
  cross_document: "Across documents",
  out_of_scope: "Outside the documentation",
};

function CitePanel({ source: s, onClose }: { source: Source; onClose: () => void }) {
  const key = statusOf(s);
  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between">
        <h2 className="card-title">Source [{s.number}]</h2>
        <button onClick={onClose} aria-label="Close source" className="size-7 cursor-pointer rounded-md border border-line-strong bg-paper text-forest">
          ×
        </button>
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="leading-[1.35] font-semibold">{s.document ?? (s.kind === "summary" ? "Database summary" : "Finding")}</span>
        {key && <Badge status={key} />}
        {key === "stale" && <span className="text-xs text-bad">Source document is currently marked Stale.</span>}
        {key === "approaching" && <span className="text-xs text-warn">Source document is approaching its review threshold.</span>}
        {s.status_reason && <span className="text-xs text-muted-2">{s.status_reason}</span>}
      </div>
      <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-2.5 gap-y-1 text-xs">
        <dt className="text-muted">Citation</dt>
        <dd className="m-0 font-mono">{citeLabel(s)}</dd>
        <dt className="text-muted">Kind</dt>
        <dd className="m-0">{s.kind === "passage" ? "Passage from the document" : s.kind === "record" ? "Extracted record" : s.kind === "finding" ? "Compliance finding" : "Database count"}</dd>
        {s.section && (
          <>
            <dt className="text-muted">Section</dt>
            <dd className="m-0">{s.section}</dd>
          </>
        )}
      </dl>
      <blockquote className="m-0 border-l-[3px] border-[#B8923A] bg-[#F6EBCB] px-3 py-2 text-[13.5px] leading-normal whitespace-pre-wrap">“{s.excerpt}”</blockquote>
      {s.document_id && <CitedPage documentId={s.document_id} page={s.pages?.[0] ?? null} excerpt={s.excerpt} />}
    </div>
  );
}

/** The cited page as read, with the passage marked, and links to the document and its file. */
function CitedPage({ documentId, page, excerpt }: { documentId: string; page: number | null; excerpt: string }) {
  const doc = useDocument(documentId);
  const d = doc.data;
  if (!d) return null;
  const p = page ?? d.start_page;
  return (
    <>
      <div className="rounded-md border border-viewer-line bg-viewer p-3">
        <SinglePage fileId={d.vendor_file_id} page={p} highlight={excerpt.slice(0, 160)} heading={d.vendor_name} size="sm" />
      </div>
      <div className="flex flex-wrap gap-2">
        <Link href={`/documents/${d.id}?page=${p}`} className="btn-primary btn-sm no-underline hover:text-page">
          Open document at page
        </Link>
        <Link href={`/vendor-files/${d.vendor_file_id}?page=${p}`} className="btn-secondary btn-sm font-normal no-underline">
          View in vendor file
        </Link>
      </div>
    </>
  );
}
