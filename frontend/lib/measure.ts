import { inr } from "./api";
import type { Finding } from "./types";

const n = (v: unknown) => (typeof v === "number" ? v : Number(v ?? 0));
const s = (v: unknown) => String(v ?? "");

// One sentence a human understands, per pattern. Unknown patterns fall back to the clause.
export function headline(f: Finding): string {
  const m = f.measure;
  switch (f.pattern) {
    case "drip_pricing":
      return `${inr(n(m.delta_inr))} added after the price was shown`;
    case "basket_sneaking": {
      const count = n(m.count ?? (Array.isArray(m.items) ? m.items.length : 1));
      return `${count} item${count === 1 ? "" : "s"} added without consent, ${inr(n(m.amount_inr))}`;
    }
    case "false_urgency":
      return `"${s(m.claim)}" unchanged for ${n(m.unchanged_for_hours)}h`;
    case "cancel_friction":
      return `${n(m.cancel_steps)} steps to cancel vs ${n(m.subscribe_steps)} to subscribe`;
    default:
      return f.clause;
  }
}

// Big number for the detail page. null = no headline number for this pattern.
export function bigNumber(f: Finding): { value: string; caption: string } | null {
  const m = f.measure;
  switch (f.pattern) {
    case "drip_pricing":
      return { value: inr(n(m.delta_inr)), caption: `added between the listed price and the payment page, ${n(m.delta_pct)}% more than advertised` };
    case "basket_sneaking":
      return { value: inr(n(m.amount_inr)), caption: "added to the basket without the shopper asking" };
    case "false_urgency":
      return { value: `${n(m.unchanged_for_hours)}h`, caption: `"${s(m.claim)}" stayed the same the whole time` };
    default:
      return null;
  }
}
