import type { Finding, JourneyState } from "./types";

export const SAMPLE_FINDINGS: Finding[] = [
  {
    finding_id: "f_1184", platform: "Platform A", pattern: "drip_pricing", severity: "high",
    measure: { delta_inr: 127, delta_pct: 25.45, from: 499, to: 626 },
    clause: "CCPA Guidelines for Prevention and Regulation of Dark Patterns, 2023 — drip pricing",
    evidence: { observation_ids: ["obs_7f3a"], video_ref: null, reproduced_in: "5 of 6 observations" },
    status: "confirmed", detected_at: "2026-10-24T09:31:02Z",
  },
  {
    finding_id: "f_1185", platform: "Platform B", pattern: "basket_sneaking", severity: "medium",
    measure: { count: 1, items: ["Donation add-on"], amount_inr: 10 },
    clause: "CCPA Guidelines for Prevention and Regulation of Dark Patterns, 2023 — basket sneaking",
    evidence: { observation_ids: ["obs_8b21"], video_ref: null, reproduced_in: "3 of 3 observations" },
    status: "confirmed", detected_at: "2026-10-24T09:12:40Z",
  },
  {
    finding_id: "f_1186", platform: "Platform C", pattern: "false_urgency", severity: "low",
    measure: { claim: "Only 2 left!", unchanged_for_hours: 6 },
    clause: "CCPA Guidelines for Prevention and Regulation of Dark Patterns, 2023 — false urgency",
    evidence: { observation_ids: ["obs_9c07"], video_ref: null, reproduced_in: "2 of 4 observations" },
    status: "candidate", detected_at: "2026-10-24T08:50:11Z",
  },
];

const step = (index: number, name: string, price: number, line_items: JourneyState["steps"][0]["line_items"] = []) => ({
  index, name, url: "https://example.com/" + name, price_displayed: price,
  line_items, timers: [], stock_claims: [],
});

export const SAMPLE_JOURNEY: JourneyState = {
  observation_id: "obs_7f3a", platform: "Platform A",
  steps: [
    step(0, "listing", 499, [{ name: "Item", amount: 499, added_by_us: true }]),
    step(1, "cart", 499, [{ name: "Item", amount: 499, added_by_us: true }]),
    step(2, "checkout", 567, [
      { name: "Item", amount: 499, added_by_us: true },
      { name: "Delivery fee", amount: 68, added_by_us: false },
    ]),
    step(3, "payment", 626, [
      { name: "Item", amount: 499, added_by_us: true },
      { name: "Delivery fee", amount: 68, added_by_us: false },
      { name: "Platform fee", amount: 59, added_by_us: false },
    ]),
  ],
  totals: { listed: 499, cart: 499, payment_page: 626 },
  outcome: "stopped_before_payment",
  artifacts: { video_ref: null },
};
