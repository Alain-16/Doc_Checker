export const ICONS = {
  overview: "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
  vendors: "M3 21V9l9-5 9 5v12M9 21v-6h6v6",
  documents: "M6 2h9l5 5v15H6zM14 2v6h6M9 13h8M9 17h8",
  findings: "M12 3l10 18H2zM12 10v5M12 18v.01",
  review: "M9 11l3 3 8-8M20 12v8H4V4h11",
  rules: "M4 6h16M4 12h10M4 18h6M17 15l3 3-3 3",
  copilot: "M4 5h16v11H9l-5 4zM8 10h8",
  reports: "M5 3h14v18H5zM9 8h6M9 12h6M9 16h4",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  settings: "M12 9a3 3 0 100 6 3 3 0 000-6zM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2",
} as const;

export type NavKey = keyof typeof ICONS;

/** `count` names the live counter shown next to the item (from /dashboard). */
export const NAV: { key: NavKey; label: string; href: string; count?: "findings" | "reviews" }[] = [
  { key: "overview", label: "Overview", href: "/overview" },
  { key: "vendors", label: "Vendors", href: "/vendors" },
  { key: "documents", label: "Documents", href: "/documents" },
  { key: "findings", label: "Compliance Findings", href: "/findings", count: "findings" },
  { key: "review", label: "Review Queue", href: "/review", count: "reviews" },
  { key: "rules", label: "Rule Engine", href: "/rules" },
  { key: "copilot", label: "Compliance Copilot", href: "/copilot" },
  { key: "reports", label: "Reports", href: "/reports" },
  { key: "upload", label: "Upload Document", href: "/upload" },
  { key: "settings", label: "Settings", href: "/settings" },
];

/** Which nav item a path belongs to (detail pages light up their list). */
export function navKeyFor(pathname: string): NavKey | null {
  if (pathname.startsWith("/vendor-files")) return "documents";
  const first = pathname.split("/")[1] ?? "";
  return (NAV.find((n) => n.href === `/${first}`)?.key ?? null) as NavKey | null;
}

export const TITLES: Record<NavKey, string> = Object.fromEntries(NAV.map((n) => [n.key, n.label])) as Record<NavKey, string>;
