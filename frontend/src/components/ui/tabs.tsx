"use client";

type Tab<K extends string> = { key: K; label: string };

export function Tabs<K extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: Tab<K>[];
  value: K;
  onChange: (key: K) => void;
}) {
  return (
    <div role="tablist" className="flex gap-0.5 overflow-x-auto border-b border-line-head">
      {tabs.map((t) => {
        const on = t.key === value;
        return (
          <button
            key={t.key}
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.key)}
            className={`-mb-px cursor-pointer border-b-2 bg-transparent px-3.5 py-[9px] text-[14px] whitespace-nowrap ${on ? "border-forest font-semibold text-forest" : "border-transparent text-muted"}`}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

export function Segmented<K extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: K[];
  value: K;
  onChange: (key: K) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex overflow-hidden rounded-md border border-line-strong">
      {options.map((o) => {
        const on = o === value;
        return (
          <button
            key={o}
            aria-pressed={on}
            onClick={() => onChange(o)}
            className={`cursor-pointer border-r border-line px-3 py-1.5 text-xs font-medium last:border-r-0 ${on ? "bg-forest text-page" : "bg-paper text-forest"}`}
          >
            {o}
          </button>
        );
      })}
    </div>
  );
}
