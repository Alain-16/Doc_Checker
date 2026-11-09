/**
 * The pipeline stages, in the order the worker runs them (backend/src/workers/pipeline.py STAGES),
 * with the design's plain-language labels.
 */
export const STAGES: [string, string][] = [
  ["read_pages", "Reading pages"],
  ["segment", "Splitting into documents"],
  ["classify", "Classifying documents"],
  ["identify_vendor", "Identifying vendor and component"],
  ["chunk", "Preparing for search"],
  ["embed", "Indexing content for Copilot"],
  ["extract_dates", "Extracting dates"],
  ["extract_key_attributes", "Extracting key fields"],
  ["supersede", "Checking superseded revisions"],
  ["evaluate_compliance", "Applying compliance rules"],
];

type Props = { stages: Record<string, unknown>; status: string; pageCount: number };

export function ProcessingSteps({ stages, status, pageCount }: Props) {
  const rows: { label: string; sub: string; state: "done" | "current" | "failed" | "todo" }[] = [
    { label: "Uploaded", sub: `${pageCount} pages`, state: "done" },
    ...STAGES.map(([key, label]) => {
      const s = stages[key];
      const state: "done" | "current" | "failed" | "todo" =
        s === "completed" ? "done" : s === "failed" ? "failed" : s === "running" ? "current" : "todo";
      return { label, sub: state === "failed" ? "Failed" : state === "current" ? "In progress…" : "", state };
    }),
  ];
  const finished = status === "completed";
  rows.push({ label: "Complete", sub: "", state: finished ? "done" : "todo" });

  return (
    <div className="flex flex-col">
      {rows.map((p, i) => {
        const look =
          p.state === "done"
            ? { glyph: "✓", bg: "#1E3B2F", fg: "#F5F0E6", bd: "#1E3B2F" }
            : p.state === "current"
              ? { glyph: "●", bg: "#C8B48A", fg: "#1E3B2F", bd: "#B39A63" }
              : p.state === "failed"
                ? { glyph: "!", bg: "#F7E1DC", fg: "#9A2B1E", bd: "#E2B2A8" }
                : { glyph: "", bg: "#FFFDF9", fg: "#1E3B2F", bd: "#CBC2AE" };
        return (
          <div key={p.label} className="grid grid-cols-[22px_minmax(0,1fr)] gap-3">
            <div className="flex flex-col items-center">
              <span
                className={`flex size-[22px] items-center justify-center rounded-full border-[1.5px] text-[12px] ${p.state === "current" ? "animate-pulse-soft" : ""}`}
                style={{ background: look.bg, color: look.fg, borderColor: look.bd }}
              >
                {look.glyph}
              </span>
              {i < rows.length - 1 && <span className="min-h-3.5 w-[1.5px] flex-1" style={{ background: p.state === "done" ? "#1E3B2F" : "#DDD4C2" }} />}
            </div>
            <div className="flex flex-col pt-px pb-3">
              <span style={{ color: p.state === "todo" ? "#7A827B" : p.state === "failed" ? "#9A2B1E" : "#1B2A22", fontWeight: p.state === "current" ? 600 : 400 }}>
                {p.label}
              </span>
              {p.sub && <span className="text-xs text-muted">{p.sub}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
