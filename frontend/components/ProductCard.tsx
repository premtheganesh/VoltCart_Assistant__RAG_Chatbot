import type { Product } from "@/lib/types";

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const wholeDollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
// "$129", but "$129.99" when there are cents
const price = (usd: number) => (Number.isInteger(usd) ? wholeDollars : dollars).format(usd);

function stock(stockLabel: string): { dot: string; text: string } {
  if (stockLabel.startsWith("out")) return { dot: "bg-danger", text: "Out of stock" };
  if (stockLabel.startsWith("low"))
    return { dot: "bg-low", text: stockLabel.replace("low stock", "Low stock") };
  return { dot: "bg-ok", text: "In stock" };
}

/** A product the answer recommends, with live price and stock from the catalog. */
export function ProductCard({ product: p }: { product: Product }) {
  const s = stock(p.stock);
  return (
    <article className="flex flex-col rounded-2xl border border-border bg-surface p-4 transition-shadow hover:shadow-[0_6px_24px_-12px_rgba(0,0,0,0.25)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            {p.category.replace("_", " ")}
          </p>
          <h3 className="mt-1 font-semibold leading-snug">{p.name}</h3>
        </div>
        <p className="shrink-0 text-lg font-semibold tabular-nums">{price(p.price_usd)}</p>
      </div>
      <p className="mt-2 line-clamp-2 text-sm leading-relaxed text-muted">{p.description}</p>
      <div className="mt-auto flex items-center justify-between pt-3 text-xs">
        <span className="tabular-nums text-muted">
          <span className="text-text">★ {p.rating.toFixed(1)}</span> ·{" "}
          {p.reviews.toLocaleString("en-US")} reviews
        </span>
        <span className="flex items-center gap-1.5 font-medium">
          <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} aria-hidden />
          {s.text}
        </span>
      </div>
    </article>
  );
}
