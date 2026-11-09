"use client";

import { useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AuthFrame, authInput, authPrimary, FormError } from "@/components/auth/auth-frame";
import { api, call, errorMessage } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";

type Step = { kind: "password" } | { kind: "setup"; uri: string | null } | { kind: "code" } | { kind: "forgot"; sent: boolean };

export default function LoginPage() {
  return (
    <AuthFrame>
      <Suspense>
        <SignIn />
      </Suspense>
    </AuthFrame>
  );
}

/** Two-step sign-in: password, then the authenticator code (first time: scan the QR code first). */
function SignIn() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>({ kind: "password" });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const next = params.get("next");
  const destination = next && next.startsWith("/") && !next.startsWith("//") ? next : "/overview";

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const submitPassword = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      const { mfa } = await call(api.POST("/auth/login", { body: { email, password } }));
      if (mfa === "setup") {
        const { otpauth_uri } = await call(api.POST("/auth/mfa/setup"));
        setStep({ kind: "setup", uri: otpauth_uri });
      } else {
        setStep({ kind: "code" });
      }
    });
  };

  const submitCode = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      const me = await call(api.POST("/auth/mfa/verify", { body: { code: code.replace(/\s/g, "") } }));
      qc.setQueryData(keys.me, me);
      router.replace(destination);
    });
  };

  const submitForgot = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      await call(api.POST("/auth/password-reset/request", { body: { email } }));
      setStep({ kind: "forgot", sent: true });
    });
  };

  if (step.kind === "forgot") {
    return (
      <form onSubmit={submitForgot} className="flex w-full max-w-[380px] flex-col gap-[18px]">
        <div className="flex flex-col gap-1">
          <h2 className="m-0 text-[24px] font-semibold">Reset your password</h2>
          <p className="m-0 leading-normal text-muted">We email a single-use link to choose a new password.</p>
        </div>
        {step.sent ? (
          <p role="status" className="m-0 rounded-md border border-[#BCD4B2] bg-[#E6EFE0] px-3 py-2.5 text-ok">
            If an account exists for {email}, a reset link is on its way.
          </p>
        ) : (
          <>
            <label className="flex flex-col gap-1.5 font-medium">
              Work email
              <input className={authInput} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <FormError text={error} />
            <button type="submit" className={authPrimary} disabled={busy}>
              {busy ? "Sending…" : "Send reset link"}
            </button>
          </>
        )}
        <button type="button" className="btn-link self-start" onClick={() => setStep({ kind: "password" })}>
          Back to sign in
        </button>
      </form>
    );
  }

  if (step.kind === "setup" || step.kind === "code") {
    const secret = step.kind === "setup" && step.uri ? new URL(step.uri).searchParams.get("secret") : null;
    return (
      <form onSubmit={submitCode} className="flex w-full max-w-[380px] flex-col gap-[18px]">
        <div className="flex flex-col gap-1">
          <h2 className="m-0 text-[24px] font-semibold">{step.kind === "setup" ? "Set up two-factor sign-in" : "Enter your code"}</h2>
          <p className="m-0 leading-normal text-muted">
            {step.kind === "setup"
              ? "Scan this code with your authenticator app, then enter the 6-digit code it shows."
              : "Open your authenticator app and enter the 6-digit code for Attest."}
          </p>
        </div>
        {step.kind === "setup" && step.uri && (
          <div className="flex flex-col items-center gap-2 rounded-lg border border-line bg-paper p-4">
            <QRCodeSVG value={step.uri} size={176} fgColor="#1E3B2F" bgColor="#FFFDF9" />
            {secret && (
              <span className="text-center text-xs text-muted">
                Can’t scan? Enter this key: <span className="font-mono break-all text-ink">{secret}</span>
              </span>
            )}
          </div>
        )}
        <label className="flex flex-col gap-1.5 font-medium">
          Authentication code
          <input
            className={`${authInput} font-mono tracking-[.3em]`}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={7}
            required
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </label>
        <FormError text={error} />
        <button type="submit" className={authPrimary} disabled={busy || code.replace(/\s/g, "").length < 6}>
          {busy ? "Verifying…" : "Verify and sign in"}
        </button>
        <button
          type="button"
          className="btn-link self-start"
          onClick={() => {
            setStep({ kind: "password" });
            setCode("");
            setError(null);
          }}
        >
          Use a different account
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={submitPassword} className="flex w-full max-w-[380px] flex-col gap-[18px]">
      <div className="flex flex-col gap-1">
        <h2 className="m-0 text-[24px] font-semibold">Sign in</h2>
        <p className="m-0 text-muted">Quality and Compliance workspace</p>
      </div>
      <label className="flex flex-col gap-1.5 font-medium">
        Work email
        <input className={authInput} type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1.5 font-medium">
        <span className="flex items-baseline justify-between">
          Password
          <button
            type="button"
            className="btn-link font-normal"
            onClick={() => {
              setError(null);
              setStep({ kind: "forgot", sent: false });
            }}
          >
            Forgot password?
          </button>
        </span>
        <input className={authInput} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      <FormError text={error} />
      <button type="submit" className={authPrimary} disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
      <div className="flex items-center gap-2.5 text-xs text-muted">
        <span className="h-px flex-1 bg-line-head" />
        or
        <span className="h-px flex-1 bg-line-head" />
      </div>
      <button
        type="button"
        disabled
        title="Single sign-on is not configured for this installation."
        className="cursor-not-allowed rounded-md border border-line-strong bg-paper px-3.5 py-2.5 text-sm font-medium text-forest opacity-60"
      >
        Continue with company SSO
      </button>
      <p className="m-0 text-xs leading-normal text-muted">
        Access is limited to authorized Quality and Compliance personnel. Contact your QA system administrator for access requests.
      </p>
    </form>
  );
}
