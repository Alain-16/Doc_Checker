"use client";

import { useEffect, useId, useState } from "react";
import { errorMessage } from "@/lib/api/client";

/** Centered modal (the design's "Approve & Activate" confirmation). Esc closes. */
export function Modal({
  title,
  onClose,
  children,
  footer,
  role = "dialog",
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer: React.ReactNode;
  role?: "dialog" | "alertdialog";
}) {
  const id = useId();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(27,42,34,.35)] p-5"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role={role}
        aria-modal="true"
        aria-labelledby={id}
        className="flex max-h-[calc(100vh-40px)] w-full max-w-[500px] flex-col rounded-lg bg-paper shadow-[0_16px_40px_rgba(30,59,47,.25)]"
      >
        <div className="flex flex-col gap-2.5 overflow-auto px-5 py-[18px]">
          <h2 id={id} className="m-0 text-[18px] font-semibold">
            {title}
          </h2>
          {children}
        </div>
        <div className="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>
      </div>
    </div>
  );
}

/** Right-hand drawer (finding detail). */
export function Drawer({ label, onClose, children }: { label: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <>
      <div onClick={onClose} className="fixed inset-0 z-40 bg-[rgba(27,42,34,.28)]" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="fixed top-0 right-0 bottom-0 z-[41] flex w-[min(560px,100vw)] flex-col bg-paper shadow-[-8px_0_28px_rgba(30,59,47,.18)]"
      >
        {children}
      </aside>
    </>
  );
}

/**
 * Asks for a reason (and, for signed changes, the password again).
 * Part 11 §11.200: rule and policy changes are electronically signed, so the
 * backend re-checks the password; every audited change needs a reason ≥ 10 chars.
 */
export function ReasonDialog({
  title,
  intro,
  confirmLabel,
  sign = false,
  defaultReason = "",
  danger = false,
  onSubmit,
  onClose,
}: {
  title: string;
  intro?: React.ReactNode;
  confirmLabel: string;
  sign?: boolean;
  defaultReason?: string;
  danger?: boolean;
  onSubmit: (values: { reason: string; password: string }) => Promise<unknown>;
  onClose: () => void;
}) {
  const [reason, setReason] = useState(defaultReason);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valid = reason.trim().length >= 10 && (!sign || password.length > 0);

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ reason: reason.trim(), password });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={title}
      onClose={onClose}
      role="alertdialog"
      footer={
        <>
          <button className="btn-secondary font-normal" onClick={onClose}>
            Cancel
          </button>
          <button className={danger ? "btn-danger" : "btn-primary"} disabled={!valid || busy} onClick={() => submit()}>
            {busy ? "Saving…" : confirmLabel}
          </button>
        </>
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-3">
        {intro && <div className="leading-[1.55] text-muted-2">{intro}</div>}
        <label className="field-label">
          Reason for the audit trail
          <textarea
            className="input min-h-[72px] resize-y font-normal"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="At least 10 characters"
            autoFocus
          />
        </label>
        {sign && (
          <label className="field-label">
            Password — your electronic signature
            <input className="input font-normal" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
        )}
        {sign && <p className="m-0 text-xs text-muted">Your name, the time and this reason are recorded with the change.</p>}
        {error && (
          <p role="alert" className="m-0 text-[13.5px] text-bad">
            {error}
          </p>
        )}
        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
