import Link from "next/link";
import { badge, BAR } from "@/lib/status";

export function HealthBar({ parts, total, height = 14 }: { parts: { key: string; count: number }[]; total: number; height?: number }) {
  return (
    <div
      role="img"
      aria-label={parts.map((p) => `${badge(p.key).label} ${total ? ((p.count / total) * 100).toFixed(1) : 0}%`).join(", ")}
      className="flex gap-0.5 overflow-hidden rounded-[3px] bg-line-soft"
      style={{ height }}
    >
      {parts.map((p) => (
        <div key={p.key} style={{ width: `${total ? (p.count / total) * 100 : 0}%`, background: BAR[p.key as keyof typeof BAR] }} />
      ))}
    </div>
  );
}

type Activity = { icon: string; text: string; who: string; when: string; href?: string | null };

export function ActivityList({ items }: { items: Activity[] }) {
  return (
    <ol className="m-0 list-none px-4 pt-1.5 pb-2.5">
      {items.map((a, i) => {
        const body = (
          <>
            <span aria-hidden="true" className="flex size-[22px] items-center justify-center rounded-full bg-[#EFEBE1] text-[12px] text-forest">
              {a.icon}
            </span>
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="leading-[1.45] break-words">{a.text}</span>
              <span className="text-xs text-muted">{a.who}</span>
            </div>
            <span className="font-mono text-xs whitespace-nowrap text-muted">{a.when}</span>
          </>
        );
        const cls = "grid grid-cols-[22px_minmax(0,1fr)_auto] items-start gap-2.5 py-2";
        return (
          <li key={i} className="border-b border-line-faint last:border-b-0">
            {a.href ? (
              <Link href={a.href} className={`${cls} text-ink no-underline hover:bg-hover-row hover:text-ink`}>
                {body}
              </Link>
            ) : (
              <div className={cls}>{body}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
