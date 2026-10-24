import { inr } from "@/lib/api";
import type { Step } from "@/lib/types";

const LABEL: Record<string, string> = {
  listing: "Price shown on listing",
  cart: "In the cart",
  checkout: "At checkout",
  payment: "Payment page total",
};

export default function PriceLadder({ steps }: { steps: Step[] }) {
  const priced = steps.filter((s) => s.price_displayed != null);
  if (priced.length === 0) return null;
  const first = priced[0].price_displayed!;
  const last = priced[priced.length - 1].price_displayed!;

  return (
    <section className="mt-8 rounded-xl border border-neutral-800">
      <h2 className="border-b border-neutral-800 px-5 py-3 text-xs font-semibold uppercase tracking-wider text-neutral-500">
        What the price did
      </h2>
      <ul>
        {priced.map((s, i) => {
          const price = s.price_displayed!;
          const prev = i === 0 ? price : priced[i - 1].price_displayed!;
          const jump = price - prev;
          const isLast = i === priced.length - 1;
          const slipped = s.line_items.filter((l) => !l.added_by_us);
          return (
            <li
              key={s.index}
              className={`px-5 py-3 ${isLast ? "bg-neutral-900/60 font-semibold" : ""} ${i > 0 ? "border-t border-neutral-900" : ""}`}
            >
              <div className="flex items-baseline justify-between gap-4">
                <span className="text-sm">{LABEL[s.name] ?? s.name}</span>
                <span className="flex items-baseline gap-3">
                  {jump > 0 && <span className="text-xs text-amber-400">+{inr(jump)}</span>}
                  <span className="tabular-nums">{inr(price)}</span>
                </span>
              </div>
              {jump > 0 && slipped.length > 0 && (
                <p className="mt-1 text-xs font-normal text-amber-400/80">
                  Added by the platform: {slipped.map((l) => `${l.name} ${inr(l.amount)}`).join(", ")}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {last > first && (
        <p className="border-t border-neutral-800 px-5 py-3 text-sm">
          <span className="font-semibold text-blue-300">{inr(last - first)} more</span>{" "}
          <span className="text-neutral-400">than the price that was advertised</span>
        </p>
      )}
    </section>
  );
}
