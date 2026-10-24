"""Pure functions. No model, no network, no database.
This is what makes the output defensible."""
from __future__ import annotations

import re
import uuid

from .schemas import CLAUSE, Finding, JourneyState


# Add-ons the platform slips in are PRODUCTS -> basket_sneaking.
# Checked FIRST, because "Shipping protection" contains a fee word.
ADDON_WORDS = (
    "protection", "insurance", "warranty", "membership", "subscription",
    "plan", "donation", "contribution", "tip", "assurance", "cover",
)

# Charges -> drip_pricing, never basket_sneaking.
FEE_WORDS = (
    "fee", "fees", "charge", "charges", "delivery", "shipping", "handling",
    "packaging", "packing", "convenience", "platform", "surge", "tax", "gst",
)

# Whole words only, so "tip" does not match "Multipack" or "plan" "Planter".
_ADDON_RE = re.compile(r"\b(" + "|".join(ADDON_WORDS) + r")\b", re.I)
_FEE_RE = re.compile(r"\b(" + "|".join(FEE_WORDS) + r")\b", re.I)


def _is_fee(name: str) -> bool:
    if _ADDON_RE.search(name):
        return False
    return bool(_FEE_RE.search(name))


def _last_step(js: JourneyState, *keys: str):
    """Last step whose name contains any key. Live runs name steps
    'payment page' or 'Cart', not exactly 'payment' or 'cart'."""
    for s in reversed(js.steps):
        if any(k in s.name.lower() for k in keys):
            return s
    return None


def _fid() -> str:
    return f"f_{uuid.uuid4().hex[:6]}"


def drip_pricing(js: JourneyState) -> Finding | None:
    listed, paid = js.totals.listed, js.totals.payment_page
    if listed is None or paid is None or listed <= 0 or paid <= listed:
        return None
    delta = round(paid - listed, 2)
    return Finding(
        finding_id=_fid(),
        platform=js.platform,
        pattern="drip_pricing",
        severity="high" if delta / listed > 0.15 else "medium",
        measure={
            "delta_inr": delta,
            "delta_pct": round(delta / listed * 100, 2),
            "from": listed,
            "to": paid,
        },
        clause=CLAUSE["drip_pricing"],
        evidence={
            "observation_ids": [js.observation_id],
            "video_ref": js.artifacts.video_ref,
        },
    )


def basket_sneaking(js: JourneyState) -> Finding | None:
    """An item the platform ADDED - not a fee, and not the product we chose.
    Fees are drip_pricing; counting them here double-reports the same rupees."""
    cart = _last_step(js, "cart", "bag", "basket")
    final = _last_step(js, "payment") or _last_step(js, "checkout")
    if final is None:
        return None

    cart_names = {li.name for li in cart.line_items} if cart else set()
    added_later = [
        li for li in final.line_items
        if li.name not in cart_names and not li.added_by_us
    ]
    flagged = [
        li for li in final.line_items
        if not li.added_by_us and li.name in cart_names
    ]
    candidates = added_later or flagged

    sneaked = [li for li in candidates if not _is_fee(li.name)]
    if not sneaked:
        return None

    total = round(sum(li.amount for li in sneaked), 2)
    return Finding(
        finding_id=_fid(),
        platform=js.platform,
        pattern="basket_sneaking",
        severity="high",
        measure={
            "items": [li.name for li in sneaked],
            "amount_inr": total,
            "count": len(sneaked),
        },
        clause=CLAUSE["basket_sneaking"],
        evidence={
            "observation_ids": [js.observation_id],
            "video_ref": js.artifacts.video_ref,
        },
    )


def _first_timer(js: JourneyState):
    for s in js.steps:
        if s.timers:
            return s.timers[0]
    return None


def _first_stock(js: JourneyState):
    for s in js.steps:
        if s.stock_claims:
            return s.stock_claims[0]
    return None


def _num(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def false_urgency(earlier: JourneyState, later: JourneyState) -> Finding | None:
    """Needs two observations of the same spec, taken hours apart."""
    hours = abs((later.condition.captured_at - earlier.condition.captured_at)
                .total_seconds()) / 3600
    if hours < 1:
        return None

    t_old, t_new = _first_timer(earlier), _first_timer(later)
    if t_old and t_new and t_new.seconds_left is not None \
            and t_old.seconds_left is not None \
            and t_new.seconds_left >= t_old.seconds_left:
        return Finding(
            finding_id=_fid(), platform=later.platform,
            pattern="false_urgency",
            severity="high",
            measure={"timer_then": t_old.seconds_left,
                     "timer_now": t_new.seconds_left,
                     "hours_apart": round(hours, 1)},
            clause=CLAUSE["false_urgency"],
            evidence={"observation_ids": [earlier.observation_id,
                                          later.observation_id]},
        )

    s_old, s_new = _first_stock(earlier), _first_stock(later)
    if s_old and s_new and _num(s_old.text) is not None \
            and _num(s_old.text) == _num(s_new.text) and hours >= 20:
        return Finding(
            finding_id=_fid(), platform=later.platform,
            pattern="false_urgency",
            severity="medium",
            measure={"claim": s_new.text, "unchanged_for_hours": round(hours, 1)},
            clause=CLAUSE["false_urgency"],
            evidence={"observation_ids": [earlier.observation_id,
                                          later.observation_id]},
        )
    return None


def cancel_friction(subscribe: JourneyState, cancel: JourneyState) -> Finding | None:
    subs, cans = len(subscribe.steps), len(cancel.steps)
    if subs == 0 or cans / subs <= 3:
        return None
    return Finding(
        finding_id=_fid(), platform=cancel.platform,
        pattern="cancel_friction",
        severity="high",
        measure={"subscribe_steps": subs, "cancel_steps": cans,
                 "ratio": round(cans / subs, 1)},
        clause=CLAUSE["cancel_friction"],
        evidence={"observation_ids": [subscribe.observation_id,
                                      cancel.observation_id]},
    )


SINGLE_STATE_RULES = [drip_pricing, basket_sneaking]


def evaluate(js: JourneyState) -> list[Finding]:
    return [f for rule in SINGLE_STATE_RULES if (f := rule(js))]


def confirm(findings: list[Finding], total_observations: int) -> list[Finding]:
    """A rule firing once is a candidate. Firing in most runs is confirmed."""
    by_pattern: dict[str, list[Finding]] = {}
    for f in findings:
        by_pattern.setdefault(f.pattern, []).append(f)

    out = []
    for pattern, group in by_pattern.items():
        hits = len(group)
        merged = group[0]
        merged.evidence["reproduced_in"] = f"{hits} of {total_observations} observations"
        merged.evidence["observation_ids"] = [
            oid for g in group for oid in g.evidence.get("observation_ids", [])
        ]
        if hits > total_observations / 2:
            merged.status = "confirmed"
        out.append(merged)
    return out


def evaluate_many(states: list[JourneyState]) -> list[Finding]:
    """Pairwise rules that evaluate() cannot reach - needs 2+ observations."""
    out = []
    ordered = sorted(states, key=lambda s: s.condition.captured_at)
    if len(ordered) >= 2:
        f = false_urgency(ordered[0], ordered[-1])
        if f:
            out.append(f)
    return out
