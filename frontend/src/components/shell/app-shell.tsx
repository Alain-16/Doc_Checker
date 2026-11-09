"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useStored } from "@/lib/use-stored";
import { ApiError, setUnauthorizedHandler } from "@/lib/api/client";
import { useDashboard, useLogout, useMe } from "@/lib/api/hooks";
import { initials, ROLE_LABEL } from "@/lib/format";
import { useToast } from "@/components/ui/toast";
import { CrumbProvider, useCrumbState } from "./crumbs";
import { GlobalSearch } from "./global-search";
import { ICONS, NAV, navKeyFor, TITLES } from "./nav";
import { NotificationsBell } from "./notifications";

const SIDEBAR_KEY = "attest.sidebarCollapsed";

/** Signed-in layout: guards the session, then renders sidebar + header + page. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useMe();

  useEffect(() => {
    setUnauthorizedHandler(() => router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`));
    return () => setUnauthorizedHandler(null);
  }, [router]);

  const unauthorized = me.error instanceof ApiError && me.error.status === 401;
  useEffect(() => {
    if (unauthorized) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthorized, router, pathname]);

  if (me.isPending || unauthorized) {
    return (
      <div className="flex h-screen items-center justify-center text-muted">
        <span className="animate-pulse-soft">Checking your session…</span>
      </div>
    );
  }
  if (me.isError) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 p-6 text-center">
        <strong className="text-sm">The Attest server is not reachable.</strong>
        <span className="max-w-[440px] text-muted">{me.error.message} — is the FastAPI backend running on the address set in BACKEND_URL?</span>
        <button className="btn-secondary" onClick={() => me.refetch()}>
          Try again
        </button>
      </div>
    );
  }

  return (
    <CrumbProvider>
      <div className="flex h-screen min-h-0">
        <Sidebar name={me.data.full_name} role={ROLE_LABEL[me.data.role] ?? me.data.role} />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header name={me.data.full_name} role={ROLE_LABEL[me.data.role] ?? me.data.role} />
          <main id="main" className="relative min-h-0 flex-1 overflow-auto">
            {children}
          </main>
        </div>
      </div>
    </CrumbProvider>
  );
}

function Sidebar({ name, role }: { name: string; role: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();
  const logout = useLogout();
  const dash = useDashboard();
  const counts = { findings: dash.data?.totals.open_findings, reviews: dash.data?.open_reviews };
  const [stored, setStored] = useStored(SIDEBAR_KEY);
  const collapsed = stored === "1";
  const toggle = () => setStored(collapsed ? "0" : "1");
  const active = navKeyFor(pathname);
  const expanded = !collapsed;

  return (
    <nav
      aria-label="Primary"
      className="flex shrink-0 flex-col bg-forest text-[#E9E3D4] transition-[width] duration-150"
      style={{ width: collapsed ? 60 : 232 }}
    >
      <div className="flex h-14 items-center gap-2.5 border-b border-[rgba(245,240,230,.12)] px-3.5">
        <div className="flex size-[30px] shrink-0 items-center justify-center rounded-md bg-gold text-[16px] font-semibold text-forest">A</div>
        {expanded && (
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-semibold text-page">Attest</span>
            <span className="text-[12px] text-[#B9C2B0]">Compliance workspace</span>
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 py-2.5">
        {NAV.map((n) => {
          const on = n.key === active;
          const count = n.count ? counts[n.count] : undefined;
          return (
            <Link
              key={n.key}
              href={n.href}
              title={n.label}
              aria-label={n.label}
              aria-current={on ? "page" : undefined}
              className="flex w-full items-center gap-[11px] rounded-md px-2.5 py-2 text-left text-[14px] no-underline hover:bg-[rgba(245,240,230,.06)]"
              style={{
                background: on ? "rgba(245,240,230,.12)" : undefined,
                boxShadow: `inset 3px 0 0 ${on ? "#C8B48A" : "transparent"}`,
                color: on ? "#FFFFFF" : "#D9D3C3",
                fontWeight: on ? 600 : 400,
              }}
            >
              <NavIcon d={ICONS[n.key]} />
              {expanded && <span className="flex-1 whitespace-nowrap">{n.label}</span>}
              {expanded && !!count && (
                <span
                  className="rounded-[9px] bg-[rgba(200,180,138,.22)] px-1.5 font-mono text-[12px] text-[#EADFC4]"
                >
                  {count}
                </span>
              )}
            </Link>
          );
        })}
      </div>
      <div className="flex flex-col gap-1 border-t border-[rgba(245,240,230,.12)] px-2 py-2.5">
        <button
          onClick={() => toast("Help & support: contact your QA system administrator.")}
          title="Help & support"
          aria-label="Help and support"
          className="flex cursor-pointer items-center gap-[11px] rounded-md border-none bg-transparent px-2.5 py-[7px] text-[14px] text-[#D9D3C3] hover:bg-[rgba(245,240,230,.08)]"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M9.5 9.5a2.5 2.5 0 114 2c-1 .6-1.5 1.2-1.5 2.3M12 17v.01" />
          </svg>
          {expanded && <span>Help &amp; support</span>}
        </button>
        <div className="flex items-center gap-2.5 px-1.5 py-2">
          <div className="flex size-[30px] shrink-0 items-center justify-center rounded-full bg-sage text-xs font-semibold text-page">{initials(name)}</div>
          {expanded && (
            <>
              <div className="flex min-w-0 flex-1 flex-col leading-[1.3]">
                <span className="truncate font-medium text-page">{name}</span>
                <span className="text-[12px] text-[#B9C2B0]">{role}</span>
              </div>
              <button
                onClick={() => logout.mutate(undefined, { onSettled: () => router.replace("/login") })}
                title="Sign out"
                aria-label="Sign out"
                className="cursor-pointer rounded border-none bg-transparent p-1 text-[#D9D3C3] hover:bg-[rgba(245,240,230,.1)]"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
                  <path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10" />
                </svg>
              </button>
            </>
          )}
        </div>
        <button
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex cursor-pointer items-center gap-[11px] rounded-md border-none bg-transparent px-2.5 py-[7px] text-xs text-[#B9C2B0] hover:bg-[rgba(245,240,230,.08)]"
        >
          <NavIcon d={collapsed ? "M9 6l6 6-6 6" : "M15 6l-6 6 6 6"} />
          {expanded && <span>Collapse sidebar</span>}
        </button>
      </div>
    </nav>
  );
}

function NavIcon({ d }: { d: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="shrink-0">
      <path d={d} />
    </svg>
  );
}

function Header({ name, role }: { name: string; role: string }) {
  const pathname = usePathname();
  const explicit = useCrumbState();
  const key = navKeyFor(pathname);
  const crumbs = explicit ?? [{ label: key ? TITLES[key] : "" }];

  return (
    <header className="relative z-20 flex h-14 shrink-0 items-center gap-4 border-b border-line bg-paper px-5">
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 overflow-hidden text-[14px]">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <span key={i} className="flex min-w-0 items-center gap-1.5">
              {i > 0 && (
                <span aria-hidden="true" className="text-[#A39C8C]">
                  /
                </span>
              )}
              {c.href && !last ? (
                <Link href={c.href} className="whitespace-nowrap text-muted no-underline hover:text-forest hover:underline">
                  {c.label}
                </Link>
              ) : (
                <span className="truncate font-semibold whitespace-nowrap text-ink">{c.label}</span>
              )}
            </span>
          );
        })}
      </nav>
      <GlobalSearch />
      <select aria-label="Workspace" title="Workspaces are not configured yet (sample)" className="select">
        <option>EU Fill-Finish · Production</option>
        <option>EU Fill-Finish · Validation</option>
      </select>
      <NotificationsBell />
      <div
        title={`${name} · ${role}`}
        className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sage text-xs font-semibold text-page"
      >
        {initials(name)}
      </div>
    </header>
  );
}
