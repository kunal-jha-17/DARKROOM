"""Turns a raw finding into something a compliance team can act on.

Four things, all derived from the finding we already have - nothing new is
measured here, so this file cannot break the detection pipeline.

  1. precedent   - the CCPA order that fined this exact pattern
  2. fix         - what to change, in one line
  3. harm        - the pattern priced at the platform's real order volume
  4. benchmark   - how this platform compares with its peers

Every number that came from outside carries its source.
"""
from __future__ import annotations


# --- 1. What the regulator actually fined, per pattern -----------------------
# Source: CCPA orders reported Aug 2026 (nine platforms, ~Rs 20 lakh total).
PRECEDENT = {
    "drip_pricing": {
        "case": "Zepto Marketplace",
        "fine_inr": 700000,
        "date": "2026-08",
        "note": "handling charge added during checkout after a lower price was shown",
    },
    "basket_sneaking": {
        "case": "Zepto Marketplace",
        "fine_inr": 700000,
        "date": "2026-08",
        "note": "membership automatically included in the cart",
    },
    "confirm_shaming": {
        "case": "PhysicsWallah",
        "fine_inr": 500000,
        "date": "2026-06",
        "note": "pre-selected Rs 10 donation with persuasive messaging",
    },
    "false_urgency": {
        "case": "CCPA Dark Patterns Guidelines, 2023",
        "fine_inr": None,
        "date": "2023-11",
        "note": "falsely stating or implying urgency; no published order yet",
    },
    "cancel_friction": {
        "case": "CCPA Dark Patterns Guidelines, 2023",
        "fine_inr": None,
        "date": "2023-11",
        "note": "subscription trap; no published order yet",
    },
    "trick_wording": {
        "case": "SpiceJet",
        "fine_inr": 100000,
        "date": "2026-07",
        "note": "pre-ticked checkboxes and trick wording on the booking flow",
    },
}

# Ceiling under the Consumer Protection Act, 2019 (sections 20-21).
PENALTY_CEILING = {"first": 1000000, "repeat": 5000000}


# --- 2. What to change ------------------------------------------------------
# The fix is almost never "remove the revenue" - it is "disclose it earlier".
FIX = {
    "drip_pricing": (
        "Show every mandatory charge on the listing page, not at payment. "
        "The fee itself is legal - hiding it until checkout is not."
    ),
    "basket_sneaking": (
        "Nothing may be added to the cart without an explicit opt-in. "
        "Un-tick it by default and let the shopper choose."
    ),
    "false_urgency": (
        "Only show a timer or stock count that is true. "
        "A timer that resets, or a count frozen for days, is a false statement."
    ),
    "cancel_friction": (
        "Cancelling must take no more steps than subscribing. "
        "Put cancel on the same screen as the subscription."
    ),
    "confirm_shaming": (
        "Remove guilt or fear from the decline option. "
        "Both choices should read neutrally."
    ),
    "trick_wording": (
        "Remove double negatives and inverted opt-outs. "
        "A checkbox should mean what it appears to mean."
    ),
}


# --- 3. Real platform scale -------------------------------------------------
# Only verified figures go in here. A platform that is not listed falls back to
# a clearly-labelled illustration, never an invented number.
PLATFORM_SCALE = {
    "meesho": {
        "orders_per_year": 2_670_000_000,
        "period": "FY26, year ended March 2026",
        "source": "Meesho FY26 results - 267 crore orders, NMV Rs 41,560 crore",
    },
}

ILLUSTRATIVE_ORDERS_PER_YEAR = 3_650_000  # 10,000 checkouts a day, stated as such

# Share of checkouts a pattern is assumed to touch. Deliberately conservative:
# we measured it on the journeys we ran, we did not measure the whole catalogue.
ASSUMED_AFFECTED_RATE = 0.01


def _rupees(n: float) -> str:
    """Indian-style short form: crore / lakh."""
    if n >= 1_00_00_000:
        return f"Rs {n / 1_00_00_000:,.1f} crore"
    if n >= 1_00_000:
        return f"Rs {n / 1_00_000:,.1f} lakh"
    return f"Rs {n:,.0f}"


def _per_checkout_amount(finding: dict) -> float | None:
    """How many rupees this pattern moves on one checkout."""
    m = finding.get("measure") or {}
    for key in ("delta_inr", "amount_inr"):
        v = m.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def harm_at_scale(finding: dict) -> dict | None:
    """Price the pattern at the platform's real order volume.

    Returns None when there is no rupee amount to multiply - we do not
    manufacture a number for patterns that do not move money directly.
    """
    per = _per_checkout_amount(finding)
    if per is None:
        return None

    key = (finding.get("platform") or "").strip().lower()
    scale = PLATFORM_SCALE.get(key)

    if scale:
        orders = scale["orders_per_year"]
        basis = f"{scale['period']} - {scale['source']}"
        illustrative = False
    else:
        orders = ILLUSTRATIVE_ORDERS_PER_YEAR
        basis = "illustration only: 10,000 checkouts a day. Real volume not published."
        illustrative = True

    affected = orders * ASSUMED_AFFECTED_RATE
    annual = per * affected

    return {
        "per_checkout_inr": per,
        "orders_per_year": orders,
        "assumed_affected_rate": ASSUMED_AFFECTED_RATE,
        "affected_checkouts_per_year": int(affected),
        "annual_consumer_harm_inr": int(annual),
        "annual_consumer_harm_readable": _rupees(annual),
        "basis": basis,
        "illustrative": illustrative,
        "method": (
            f"{_rupees(per)} per affected checkout x "
            f"{ASSUMED_AFFECTED_RATE:.0%} of {orders:,} annual orders"
        ),
    }


def benchmark(finding: dict, all_findings: list[dict]) -> dict:
    """How this platform compares with the others we have audited."""
    platform = finding.get("platform")
    per_platform: dict[str, int] = {}
    for f in all_findings:
        if f.get("status") == "confirmed" or f.get("status") == "candidate":
            per_platform[f.get("platform", "?")] = per_platform.get(f.get("platform", "?"), 0) + 1

    mine = per_platform.get(platform, 0)
    others = [v for k, v in per_platform.items() if k != platform]
    peer_avg = round(sum(others) / len(others), 1) if others else None

    return {
        "this_platform_findings": mine,
        "platforms_audited": len(per_platform),
        "peer_average_findings": peer_avg,
        "position": (
            "above peer average" if peer_avg is not None and mine > peer_avg
            else "at or below peer average" if peer_avg is not None
            else "no peers audited yet"
        ),
    }


def report(finding: dict, all_findings: list[dict] | None = None) -> dict:
    """The full enriched record the dashboard and the PDF render."""
    pattern = finding.get("pattern", "")
    prec = PRECEDENT.get(pattern)

    return {
        "finding": finding,
        "precedent": prec,
        "penalty_ceiling": PENALTY_CEILING,
        "recommended_fix": FIX.get(pattern, "Review this flow against the 2023 guidelines."),
        "harm_at_scale": harm_at_scale(finding),
        "benchmark": benchmark(finding, all_findings or []),
        "verification": {
            "status": "not_retested",
            "how": (
                "The journey path is saved. After the fix ships we replay the "
                "identical path and verify the pattern is gone."
            ),
        },
        "disclaimer": (
            "Measurements, not verdicts. Figures describe what the interface "
            "displayed during automated sessions that never completed a payment. "
            "Harm estimates state their assumptions and are not claims about "
            "actual losses."
        ),
    }
