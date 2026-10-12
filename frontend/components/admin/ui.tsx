/** Small building blocks shared by the admin pages. */

export function PageTitle({ title, intro, action }: { title: string; intro?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-4xl leading-none">{title}</h1>
        {intro && <p className="mt-2 max-w-[60ch] text-sm text-muted">{intro}</p>}
      </div>
      {action}
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="tablist" className="mb-4 inline-flex rounded-full border border-border bg-surface p-1 text-sm">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          type="button"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-full px-3.5 py-1.5 transition-colors ${
            value === o.value ? "bg-ink text-on-ink" : "text-muted hover:text-text"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

const TONES = {
  neutral: "bg-surface-2 text-muted",
  accent: "bg-accent text-on-accent",
  warn: "bg-warn-bg text-warn-text",
  ok: "bg-surface-2 text-ok",
  danger: "bg-surface-2 text-danger",
};

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof TONES; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-border px-6 py-12 text-center">
      <p className="font-medium">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-[48ch] text-sm text-muted">{children}</p>}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="mb-4 flex items-center justify-between gap-4 rounded-xl bg-warn-bg px-4 py-3 text-sm text-warn-text">
      <span>{message}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="font-medium underline underline-offset-2">
          Try again
        </button>
      )}
    </div>
  );
}

export function Loading() {
  return <p className="py-10 text-center text-sm text-muted">Loading…</p>;
}

export const card = "rounded-2xl border border-border bg-surface";
