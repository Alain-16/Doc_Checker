"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";

type Toast = { text: string; tone: "ok" | "error" };
const ToastContext = createContext<(text: string, tone?: Toast["tone"]) => void>(() => {});

/** `const toast = useToast(); toast("Saved.")` — bottom-right confirmation, as in the design. */
export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const show = useCallback((text: string, tone: Toast["tone"] = "ok") => {
    setToast({ text, tone });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), tone === "error" ? 6000 : 3400);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast && (
        <div
          role="status"
          aria-live="polite"
          className={`fixed right-5 bottom-5 z-[100] flex max-w-[420px] items-center gap-2.5 rounded-md px-4 py-[11px] text-[14px] text-page shadow-[0_8px_24px_rgba(30,59,47,.25)] ${toast.tone === "error" ? "bg-bad" : "bg-forest"}`}
        >
          <span aria-hidden="true" className="text-gold">
            {toast.tone === "error" ? "!" : "✓"}
          </span>
          {toast.text}
        </div>
      )}
    </ToastContext.Provider>
  );
}
