"""Pure functions. No model, no network, no database.
This is what makes the output defensible."""
from __future__ import annotations

import re
import uuid

from .schemas import CLAUSE, Finding, JourneyState


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
    checkout = [s for s in js.steps if s.name in ("checkout", "payment")]
    if not checkout:
        return None
    sneaked = [li for li in checkout[-1].line_items if not li.added_by_us]
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
