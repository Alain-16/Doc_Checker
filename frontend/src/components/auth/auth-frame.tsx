/** The sign-in page's two-panel layout (brand panel + form), shared by login, invitation and reset pages. */
export function AuthFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen grid-cols-[repeat(auto-fit,minmax(360px,1fr))]">
      <div className="flex flex-col justify-between gap-10 bg-forest p-12 text-page">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-[7px] bg-gold text-lg font-semibold text-forest">A</div>
          <div className="flex flex-col">
            <span className="text-[18px] font-semibold">Attest</span>
            <span className="text-xs text-[#C9CFBF]">Document Intelligence &amp; Compliance</span>
          </div>
        </div>
        <div className="flex max-w-[460px] flex-col gap-5">
          <h1 className="m-0 text-[30px] leading-tight font-medium text-pretty">
            Vendor documentation, segmented, verified and traceable to the source page.
          </h1>
          <div className="flex flex-col gap-2.5 text-sm text-[#DCD6C6]">
            {["See what requires attention, and why", "Open the evidence behind every value", "Define policies — AI interprets, you approve"].map((t, i) => (
              <div key={t} className="flex gap-2.5">
                <span className="font-mono text-gold">0{i + 1}</span>
                {t}
              </div>
            ))}
          </div>
        </div>
        <div className="font-mono text-xs text-[#B9C2B0]">Audit trail enabled · All actions are recorded</div>
      </div>
      <div className="flex items-center justify-center bg-page px-6 py-12">{children}</div>
    </div>
  );
}

export function FormError({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p role="alert" className="m-0 rounded-md border border-[#E2B2A8] bg-[#FBF1EE] px-3 py-2 text-[13.5px] text-bad">
      {text}
    </p>
  );
}

export const authInput = "rounded-md border border-line-strong bg-paper px-3 py-2.5 text-sm font-normal text-ink";
export const authPrimary =
  "cursor-pointer rounded-md border-none bg-forest px-3.5 py-[11px] text-sm font-medium text-page hover:bg-forest-hover disabled:cursor-not-allowed disabled:opacity-60";
