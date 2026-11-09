export function Page({ children, max = 1480, tight = false }: { children: React.ReactNode; max?: number; tight?: boolean }) {
  return (
    <div className={`flex flex-col px-7 pb-10 ${tight ? "gap-3.5 pt-5" : "gap-4 pt-6"}`} style={{ maxWidth: max }}>
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  sub,
  eyebrow,
  actions,
}: {
  title: React.ReactNode;
  sub?: React.ReactNode;
  eyebrow?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1 className="m-0 text-[24px] leading-tight font-semibold text-pretty">{title}</h1>
        {sub && <p className="m-0 text-muted">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function FilterBar({ children }: { children: React.ReactNode }) {
  return <div className="card flex flex-wrap items-center gap-2 px-3 py-2.5">{children}</div>;
}

export function LabeledSelect({
  label,
  value,
  options,
  onChange,
  className = "",
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  className?: string;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted">
      {label}
      <select className={`select ${className}`} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
