export type Pattern =
  | "drip_pricing" | "basket_sneaking" | "false_urgency"
  | "cancel_friction" | "confirm_shaming" | "trick_wording";
export type Status = "candidate" | "confirmed";

export interface Finding {
  finding_id: string;
  platform: string;
  pattern: Pattern;
  severity: "low" | "medium" | "high";
  measure: Record<string, unknown>;
  clause: string;
  evidence: {
    observation_ids?: string[];
    video_ref?: string | null;
    reproduced_in?: string;
  };
  status: Status;
  detected_at: string;
}

export interface LineItem { name: string; amount: number; added_by_us: boolean }

export interface Step {
  index: number;
  name: string;
  url: string;
  price_displayed: number | null;
  line_items: LineItem[];
  timers: { label: string; seconds_left?: number }[];
  stock_claims: { text: string; value?: number }[];
}

export interface JourneyState {
  observation_id: string;
  platform: string;
  steps: Step[];
  totals: { listed?: number; cart?: number; payment_page?: number };
  outcome: string;
  artifacts: { video_ref?: string | null };
}

export const PATTERN_LABEL: Record<Pattern, string> = {
  drip_pricing: "Drip pricing",
  basket_sneaking: "Basket sneaking",
  false_urgency: "False urgency",
  cancel_friction: "Subscription trap",
  confirm_shaming: "Confirm shaming",
  trick_wording: "Trick wording",
};
