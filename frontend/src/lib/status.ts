/** Badge palette from the design: every status, severity and decision has a colour set and an icon. */
export type BadgeStyle = { label: string; fg: string; bg: string; bd: string; icon: string };

export const BADGES = {
  current: { label: "Current", fg: "#25603A", bg: "#E6EFE0", bd: "#BCD4B2", icon: "✓" },
  approaching: { label: "Approaching Review", fg: "#7A5300", bg: "#F8EDCD", bd: "#E3CC8A", icon: "◷" },
  stale: { label: "Stale", fg: "#9A2B1E", bg: "#F7E1DC", bd: "#E2B2A8", icon: "!" },
  review: { label: "Needs Review", fg: "#8A4B12", bg: "#F4E6D6", bd: "#DDBF9C", icon: "?" },
  superseded: { label: "Superseded", fg: "#4F5A53", bg: "#ECEAE3", bd: "#D2CEC2", icon: "↺" },
  open: { label: "Open", fg: "#1E3B2F", bg: "#EFEBE1", bd: "#D2CAB6", icon: "○" },
  acknowledged: { label: "Acknowledged", fg: "#1E3B2F", bg: "#E3E8DC", bd: "#B9C4AE", icon: "◉" },
  resolved: { label: "Resolved", fg: "#25603A", bg: "#E6EFE0", bd: "#BCD4B2", icon: "✓" },
  active: { label: "Active", fg: "#25603A", bg: "#E6EFE0", bd: "#BCD4B2", icon: "●" },
  draft: { label: "Draft", fg: "#6B4E00", bg: "#FBF3DC", bd: "#E3CC8A", icon: "✎" },
  disabled: { label: "Disabled", fg: "#4F5A53", bg: "#ECEAE3", bd: "#D2CEC2", icon: "○" },
  archived: { label: "Archived", fg: "#4F5A53", bg: "#F3F1EB", bd: "#D2CEC2", icon: "▫" },
  high: { label: "High", fg: "#9A2B1E", bg: "#F7E1DC", bd: "#E2B2A8", icon: "▲" },
  medium: { label: "Medium", fg: "#7A5300", bg: "#F8EDCD", bd: "#E3CC8A", icon: "◆" },
  low: { label: "Low", fg: "#3E4C43", bg: "#EAECE5", bd: "#CDD3C6", icon: "●" },
  // Backend severities (FindingSeverity) mapped onto the same scale.
  critical: { label: "Critical", fg: "#9A2B1E", bg: "#F7E1DC", bd: "#E2B2A8", icon: "▲" },
  warning: { label: "Warning", fg: "#7A5300", bg: "#F8EDCD", bd: "#E3CC8A", icon: "◆" },
  info: { label: "Info", fg: "#3E4C43", bg: "#EAECE5", bd: "#CDD3C6", icon: "●" },
  pending: { label: "Pending", fg: "#8A4B12", bg: "#F4E6D6", bd: "#DDBF9C", icon: "?" },
  confirmed: { label: "Confirmed", fg: "#25603A", bg: "#E6EFE0", bd: "#BCD4B2", icon: "✓" },
  corrected: { label: "Corrected", fg: "#1E3B2F", bg: "#E3E8DC", bd: "#B9C4AE", icon: "✎" },
  na: { label: "Not applicable", fg: "#4F5A53", bg: "#ECEAE3", bd: "#D2CEC2", icon: "–" },
  failed: { label: "Failed", fg: "#9A2B1E", bg: "#F7E1DC", bd: "#E2B2A8", icon: "!" },
  complete: { label: "Complete", fg: "#25603A", bg: "#E6EFE0", bd: "#BCD4B2", icon: "✓" },
  running: { label: "Processing", fg: "#7A5300", bg: "#F8EDCD", bd: "#E3CC8A", icon: "●" },
  queued: { label: "Queued", fg: "#4F5A53", bg: "#ECEAE3", bd: "#D2CEC2", icon: "◷" },
  ready: { label: "Ready", fg: "#25603A", bg: "#E6EFE0", bd: "#BCD4B2", icon: "✓" },
  needs_clarification: { label: "Needs clarification", fg: "#8A4B12", bg: "#F4E6D6", bd: "#DDBF9C", icon: "?" },
  invalid: { label: "Cannot be automated", fg: "#9A2B1E", bg: "#F7E1DC", bd: "#E2B2A8", icon: "!" },
} satisfies Record<string, BadgeStyle>;

export type StatusKey = keyof typeof BADGES;

export function badge(key: string | null | undefined): BadgeStyle {
  return (key && (BADGES as Record<string, BadgeStyle>)[key]) || BADGES.open;
}

/** Health bar colours. */
export const BAR: Record<"current" | "approaching" | "stale" | "review", string> = {
  current: "#6E9466",
  approaching: "#CDA54F",
  stale: "#B5503F",
  review: "#A9784A",
};

/** Backend ComplianceStatus → design status key. */
export function complianceKey(status: string | null | undefined, superseded = false): StatusKey {
  if (superseded) return "superseded";
  switch (status) {
    case "current":
      return "current";
    case "approaching_review":
      return "approaching";
    case "stale":
      return "stale";
    case "needs_review":
      return "review";
    default:
      return "open";
  }
}
