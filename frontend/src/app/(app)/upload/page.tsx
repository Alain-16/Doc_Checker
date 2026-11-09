"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { ProcessingSteps } from "@/components/processing-steps";
import { Badge } from "@/components/ui/badge";
import { Page, PageHeader } from "@/components/ui/page";
import { useToast } from "@/components/ui/toast";
import { ApiError, errorMessage } from "@/lib/api/client";
import { uploadVendorFile, useComponents, useFileStatus, useResumeFile, useVendors } from "@/lib/api/hooks";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import { useStored } from "@/lib/use-stored";

const RECENT_KEY = "attest.recentUploads";
type Recent = { id: string; filename: string; at: string };

function parseRecent(raw: string | null): Recent[] {
  try {
    const list = JSON.parse(raw ?? "[]");
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

/**
 * Upload a vendor PDF → POST /vendor-files, then follow /vendor-files/{id}/status.
 * There is no vendor/component step: the pipeline identifies them from the document itself.
 */
export default function UploadPage() {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<1 | 2>(1);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<{ text: string; existing?: string } | null>(null);
  const [current, setCurrent] = useState<Recent | null>(null);
  const [storedRecent, setStoredRecent] = useStored(RECENT_KEY);
  const recent = parseRecent(storedRecent);

  const status = useFileStatus(current?.id ?? null, true);
  const s = status.data;
  const finished = s?.status === "completed";

  function choose(f: File | undefined) {
    setError(null);
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".pdf") && f.type !== "application/pdf") {
      setError({ text: "Only PDF files can be uploaded." });
      return;
    }
    setFile(f);
  }

  async function upload() {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const accepted = await uploadVendorFile(file);
      const r = { id: accepted.vendor_file_id, filename: file.name, at: new Date().toISOString() };
      setStoredRecent(JSON.stringify([r, ...recent.filter((x) => x.id !== r.id)].slice(0, 10)));
      setCurrent(r);
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : null;
      const existing = detail && typeof detail === "object" && "existing_vendor_file_id" in detail ? String((detail as Record<string, unknown>).existing_vendor_file_id) : undefined;
      setError({ text: existing ? "This file was already uploaded." : errorMessage(e), existing });
    } finally {
      setUploading(false);
    }
  }

  function reset() {
    setFile(null);
    setStep(1);
    setCurrent(null);
    setError(null);
  }

  const stepIdx = current ? (finished ? 4 : 3) : step;
  const steps = ["Upload PDF", "Review upload", "Processing", "Results"];

  return (
    <Page max={1100}>
      <PageHeader title="Upload document" sub="Upload a vendor PDF. It will be split into logical documents, classified, matched to its vendor and component, and checked against active rules." />
      <ol className="m-0 flex list-none flex-wrap gap-2 p-0">
        {steps.map((label, i) => {
          const n = i + 1;
          const done = n < stepIdx || (n === 4 && finished);
          const on = n === stepIdx && !done;
          return (
            <li key={label} className="card flex flex-[1_1_160px] items-center gap-2 px-3 py-2.5">
              <span
                className="flex size-6 shrink-0 items-center justify-center rounded-full border-[1.5px] text-xs font-semibold"
                style={{ background: done ? "#1E3B2F" : on ? "#FFFDF9" : "#F3EEE3", color: done ? "#F5F0E6" : "#1E3B2F", borderColor: done || on ? "#1E3B2F" : "#CBC2AE" }}
              >
                {done ? "✓" : n}
              </span>
              <span style={{ fontWeight: on ? 600 : 400 }}>{label}</span>
            </li>
          );
        })}
      </ol>

      {!current && (
        <section className="card flex flex-col gap-4 p-5">
          {step === 1 && (
            <>
              <h2 className="m-0 text-[16px] font-semibold">Upload PDF</h2>
              {!file ? (
                <button
                  onClick={() => input.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragging(false);
                    choose(e.dataTransfer.files[0]);
                  }}
                  className="flex cursor-pointer flex-col items-center gap-1.5 rounded-lg border-[1.5px] border-dashed px-5 py-10 text-ink hover:border-forest hover:bg-sand-2"
                  style={{ borderColor: dragging ? "#1E3B2F" : "#9AA39A", background: dragging ? "#F6F1E7" : "#FBF8F1" }}
                >
                  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#1E3B2F" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
                    <path d="M12 16V4M7 9l5-5 5 5M4 20h16" />
                  </svg>
                  <span className="font-semibold">Drop a PDF here or choose a file</span>
                  <span className="text-xs text-muted">Digital or scanned PDF · one vendor bundle may contain several documents and components</span>
                </button>
              ) : (
                <FileRow file={file} onRemove={() => setFile(null)} />
              )}
              <input ref={input} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => choose(e.target.files?.[0])} />
            </>
          )}
          {step === 2 && file && (
            <>
              <h2 className="m-0 text-[16px] font-semibold">Review upload</h2>
              <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-5 gap-y-2">
                <dt className="text-muted">File</dt>
                <dd className="m-0 font-mono text-[13.5px]">{file.name}</dd>
                <dt className="text-muted">Size</dt>
                <dd className="m-0">{fmtBytes(file.size)}</dd>
                <dt className="text-muted">Vendor &amp; component</dt>
                <dd className="m-0">Identified from the document during processing</dd>
              </dl>
              <p className="m-0 text-[13.5px] leading-normal text-muted-2">
                Extracted values below the confidence threshold are held for review. Statuses are calculated only by active, approved rules. The original file is stored
                unchanged.
              </p>
              <div>
                <button className="btn-primary px-[18px] py-[9px]" disabled={uploading} onClick={upload}>
                  {uploading ? "Uploading…" : "Upload and process"}
                </button>
              </div>
            </>
          )}
          {error && (
            <div role="alert" className="rounded-md border border-[#E2B2A8] bg-[#FBF1EE] px-3 py-2.5 text-[13.5px] text-bad">
              {error.text}{" "}
              {error.existing && (
                <Link href={`/vendor-files/${error.existing}`} className="text-bad underline">
                  Open the existing upload
                </Link>
              )}
            </div>
          )}
          <div className="flex justify-between border-t border-line-soft pt-3.5">
            <button className="btn-secondary font-normal" disabled={step === 1} onClick={() => setStep(1)}>
              Back
            </button>
            {step === 1 && (
              <button className="btn-primary" disabled={!file} onClick={() => setStep(2)}>
                Continue
              </button>
            )}
          </div>
        </section>
      )}

      {current && (
        <section className="card grid grid-cols-[repeat(auto-fit,minmax(min(100%,320px),1fr))] gap-6 p-5">
          <div className="flex flex-col">
            <h2 className="mt-0 mb-3.5 text-[16px] font-semibold">Processing {current.filename}</h2>
            {s ? <ProcessingSteps stages={s.stages} status={s.status} pageCount={s.page_count} /> : <span className="animate-pulse-soft text-muted">Starting…</span>}
          </div>
          <div className="flex flex-col gap-3">
            {s?.status === "failed" && <FailedNote id={current.id} error={s.error} />}
            {s && (s.status === "queued" || s.status === "running") && (
              <div className="rounded-lg border border-dashed border-line-strong p-6 leading-normal text-muted">
                You can leave this page. Processing continues and the file stays listed under Recent uploads.
              </div>
            )}
            {finished && s && <Results componentIds={s.component_ids} />}
            <div className="flex gap-2">
              <Link href={`/vendor-files/${current.id}`} className="btn-primary px-4 py-2 no-underline hover:text-page">
                View file
              </Link>
              <button className="btn-secondary px-3.5 py-2 font-normal" onClick={reset}>
                Upload another
              </button>
            </div>
          </div>
        </section>
      )}

      <section className="card overflow-hidden">
        <div className="border-b border-line px-4 py-3 font-semibold">Recent uploads (this browser)</div>
        {recent.map((r) => (
          <RecentRow key={r.id} item={r} />
        ))}
        {!recent.length && <div className="px-4 py-3 text-muted">Files you upload here are listed with their processing status.</div>}
      </section>
    </Page>
  );
}

function FileRow({ file, onRemove }: { file: File; onRemove: () => void }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-line bg-subtle px-3.5 py-3">
      <span className="flex h-[42px] w-[34px] shrink-0 items-end justify-center border border-line-strong bg-white pb-[3px] text-[9px] font-semibold text-bad">PDF</span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate font-mono text-[13.5px] font-medium">{file.name}</span>
        <span className="text-xs text-muted">{fmtBytes(file.size)}</span>
      </div>
      <button onClick={onRemove} className="cursor-pointer border-none bg-transparent text-xs text-bad underline">
        Remove
      </button>
    </div>
  );
}

function FailedNote({ id, error }: { id: string; error: string | null }) {
  const resume = useResumeFile();
  const toast = useToast();
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-lg border border-[#E2B2A8] bg-[#FBF1EE] p-3.5 text-[13.5px] text-bad">
      <strong className="font-semibold">Document processing failed.</strong>
      {error && <span>{error}</span>}
      <button
        className="btn-danger btn-sm self-start"
        disabled={resume.isPending}
        onClick={() =>
          resume.mutate(id, {
            onSuccess: () => toast("Retry queued — completed stages are skipped."),
            onError: (e) => toast(errorMessage(e), "error"),
          })
        }
      >
        Resume processing
      </button>
    </div>
  );
}

function Results({ componentIds }: { componentIds: string[] }) {
  const components = useComponents();
  const vendors = useVendors();
  const found = (components.data ?? []).filter((c) => componentIds.includes(c.id));
  return (
    <>
      <div className="flex flex-col gap-1 rounded-lg border border-[#BCD4B2] bg-[#E6EFE0] p-3.5">
        <span className="font-semibold text-ok">✓ Processing complete.</span>
        <span className="text-[13.5px] text-ok">
          {found.length ? `${found.length} component${found.length > 1 ? "s" : ""} identified.` : "No component was identified — check the review queue."}
        </span>
      </div>
      {found.length > 0 && (
        <div className="overflow-hidden rounded-md border border-line">
          {found.map((c) => (
            <Link
              key={c.id}
              href={`/vendors/${c.vendor_id}?tab=components`}
              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2.5 border-b border-line-soft bg-paper px-3 py-2 text-ink no-underline last:border-b-0 hover:bg-hover-row hover:text-ink"
            >
              <span>{c.name}</span>
              <span className="text-xs text-muted">{vendors.data?.find((v) => v.id === c.vendor_id)?.name}</span>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

function RecentRow({ item }: { item: Recent }) {
  const status = useFileStatus(item.id, true);
  const s = status.data;
  const key = s ? (s.status === "completed" ? "complete" : s.status) : null;
  return (
    <Link
      href={`/vendor-files/${item.id}`}
      className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 border-b border-line-soft px-4 py-[11px] text-ink no-underline last:border-b-0 hover:bg-hover-row hover:text-ink"
    >
      <span className="font-mono text-[13.5px] font-medium">{item.filename}</span>
      {key ? <Badge status={key} className="justify-self-end" /> : <span className="text-xs text-muted">{status.isError ? "Unavailable" : "…"}</span>}
      <span className="text-xs text-muted">
        {fmtDateTime(item.at)}
        {s ? ` · ${s.page_count} pages` : ""}
        {s?.error ? ` · ${s.error}` : ""}
      </span>
    </Link>
  );
}
