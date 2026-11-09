import { Suspense } from "react";
import { AppShell } from "@/components/shell/app-shell";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <Suspense fallback={<div className="flex h-screen items-center justify-center text-muted">Loading…</div>}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
