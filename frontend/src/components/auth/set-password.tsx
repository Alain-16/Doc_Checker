"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { api, call, errorMessage } from "@/lib/api/client";
import { authInput, authPrimary, FormError } from "./auth-frame";

/** Emailed-link pages: accept an invitation or finish a password reset (both choose a password). */
export function SetPassword({ purpose }: { purpose: "invite" | "reset" }) {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== again) return setError("The two passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      const body = { token, password };
      await call(purpose === "invite" ? api.POST("/auth/invitations/accept", { body }) : api.POST("/auth/password-reset/complete", { body }));
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const title = purpose === "invite" ? "Welcome to Attest" : "Choose a new password";
  if (!token) {
    return (
      <div className="flex w-full max-w-[380px] flex-col gap-3">
        <h2 className="m-0 text-[24px] font-semibold">{title}</h2>
        <FormError text="This link is incomplete. Open the link from your email again." />
      </div>
    );
  }
  if (done) {
    return (
      <div className="flex w-full max-w-[380px] flex-col gap-4">
        <h2 className="m-0 text-[24px] font-semibold">Password saved</h2>
        <p className="m-0 text-muted">
          {purpose === "invite" ? "Your account is ready. On first sign-in you'll set up your authenticator app." : "You can sign in with your new password."}
        </p>
        <Link href="/login" className={`${authPrimary} text-center no-underline hover:text-page`}>
          Go to sign in
        </Link>
      </div>
    );
  }
  return (
    <form onSubmit={submit} className="flex w-full max-w-[380px] flex-col gap-[18px]">
      <div className="flex flex-col gap-1">
        <h2 className="m-0 text-[24px] font-semibold">{title}</h2>
        <p className="m-0 text-muted">{purpose === "invite" ? "Choose the password for your account." : "This link can be used once."}</p>
      </div>
      <label className="flex flex-col gap-1.5 font-medium">
        New password
        <input className={authInput} type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1.5 font-medium">
        Repeat password
        <input className={authInput} type="password" autoComplete="new-password" required value={again} onChange={(e) => setAgain(e.target.value)} />
      </label>
      <FormError text={error} />
      <button type="submit" className={authPrimary} disabled={busy}>
        {busy ? "Saving…" : "Save password"}
      </button>
    </form>
  );
}
