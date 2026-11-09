import { badge, type BadgeStyle } from "@/lib/status";

type Props = {
  status?: string | null;
  style?: BadgeStyle;
  suffix?: string;
  dashed?: boolean;
  size?: "md" | "sm" | "xs";
  className?: string;
};

/** Status pill: colour + icon + label, so status never relies on colour alone. */
export function Badge({ status, style, suffix, dashed, size = "md", className = "" }: Props) {
  const b = style ?? badge(status);
  const sizing =
    size === "md"
      ? "px-2 py-px text-xs leading-5"
      : size === "sm"
        ? "px-[7px] text-[12.5px] leading-[19px]"
        : "px-1.5 text-[12px] leading-[18px]";
  return (
    <span
      className={`inline-flex w-fit items-center gap-[5px] rounded border font-medium whitespace-nowrap ${sizing} ${dashed ? "border-dashed" : ""} ${className}`}
      style={{ color: b.fg, background: b.bg, borderColor: b.bd }}
    >
      <span aria-hidden="true">{b.icon}</span>
      {b.label}
      {suffix}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton-bar h-2.5 ${className}`} />;
}

export function SkeletonBlock({ label, lines = [40, 80, 65, 72] }: { label?: string; lines?: number[] }) {
  return (
    <div className="card flex animate-pulse-soft flex-col gap-3 p-[18px]">
      {label && <span className="text-[14px] text-muted">{label}</span>}
      {lines.map((w, i) => (
        <div key={i} className="skeleton-bar h-2.5" style={{ width: `${w}%` }} />
      ))}
    </div>
  );
}

export function ErrorNote({ error, title = "Could not load this from the server." }: { error: unknown; title?: string }) {
  const text = error instanceof Error ? error.message : String(error ?? "");
  return (
    <div role="alert" className="rounded-md border border-[#E2B2A8] bg-[#FBF1EE] px-3.5 py-2.5 text-[13.5px] text-bad">
      <strong className="font-semibold">{title}</strong> {text}
    </div>
  );
}

export function EmptyState({ title, text, children }: { title: string; text?: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2.5 px-6 py-12 text-center">
      <span className="text-sm font-semibold">{title}</span>
      {text && <span className="max-w-[460px] leading-normal text-muted">{text}</span>}
      {children}
    </div>
  );
}
