const DATE = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });
const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });

/** "05 Nov 2026" — the design's date style. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : DATE.format(d);
}

/** "05 Nov 2026 07:00" */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : `${DATE.format(d)} ${TIME.format(d)}`;
}

/** "07:00", "Yesterday" or "03 Nov" — activity feed style. */
export function fmtRelative(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const days = Math.floor((now.setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86_400_000);
  if (days <= 0) return TIME.format(d);
  if (days === 1) return "Yesterday";
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short" }).format(d);
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

/** "M. Okafor" from "Maya Okafor". */
export function shortName(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length < 2) return name;
  return `${parts[0]![0]}. ${parts.slice(1).join(" ")}`;
}

export const ROLE_LABEL: Record<string, string> = {
  qa_analyst: "QA Analyst",
  compliance_specialist: "Compliance Specialist",
  admin: "Administrator",
};

export function humanize(snake: string | null | undefined): string {
  if (!snake) return "—";
  const s = snake.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function fmtBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
