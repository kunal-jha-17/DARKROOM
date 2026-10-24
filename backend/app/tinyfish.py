import os
import time
import uuid

import httpx

from .schemas import JourneyState, PathAction, ProbeSpec  # noqa: F401

AGENT = "https://agent.tinyfish.ai/v1/automation"
RUNS = "https://agent.tinyfish.ai/v1/runs"


def _headers() -> dict:
    # Read the key at call time, not import time, so main.py can start and
    # serve seed data even when TINYFISH_API_KEY is not set yet.
    key = os.environ.get("TINYFISH_API_KEY")
    if not key:
        raise RuntimeError("TINYFISH_API_KEY is not set (put it in backend/.env)")
    return {"X-API-Key": key, "Content-Type": "application/json"}


# Forces typed JSON back instead of prose. Keep it small - deep schemas get rejected.
JOURNEY_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "price_displayed": {"type": "number"},
                    "line_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "amount": {"type": "number"},
                            },
                            "required": ["name", "amount"],
                        },
                    },
                    "timer_text": {"type": "string"},
                    "stock_text": {"type": "string"},
                },
                "required": ["name", "url"],
            },
        },
        "listed_price": {"type": "number"},
        "payment_page_total": {"type": "number"},
    },
    "required": ["steps"],
}

GOAL = (
    "On {site}, find a product priced under {budget} rupees. "
    "Add exactly ONE to the cart. Proceed until the payment page is displayed. "
    "CRITICAL: do NOT enter any card details and do NOT submit payment. Stop at "
    "the payment page. "
    "Record, for every step: the price displayed, every line item in the cart with "
    "its amount, the text of any countdown timer, the text of any stock warning, "
    "and the final total shown on the payment page. Return JSON only."
)


def discover(platform: str, entry_url: str, budget: int = 600) -> dict:
    """Run the Agent API once to map a platform's checkout. Returns the raw run."""
    headers = _headers()
    payload = {
        "url": entry_url,
        "goal": GOAL.format(site=platform, budget=budget),
        "output_schema": JOURNEY_SCHEMA,
        "browser_profile": "stealth",
        # Do NOT send max_steps: it is beta-gated and returns 403 on a normal key.
        "agent_config": {"max_duration_seconds": 300},
        # capture_config is account-gated: a 403 means your key is not enabled.
        "capture_config": {"screenshots": True, "recording": True, "html": True},
    }
    r = httpx.post(f"{AGENT}/run-async", headers=headers, json=payload, timeout=60)
    if r.status_code == 403:
        # fall back without capture rather than failing the run
        print("tinyfish: capture_config rejected (403), retrying without capture")
        payload.pop("capture_config")
        r = httpx.post(f"{AGENT}/run-async", headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def poll(run_id: str, timeout_s: int = 360) -> dict:
    """Poll until terminal. Safer than SSE, which cannot resume."""
    headers = _headers()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = httpx.get(f"{RUNS}/{run_id}", headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
            return data
        time.sleep(5)
    return {"status": "TIMEOUT", "run_id": run_id}


def to_journey_state(run: dict, platform: str, spec_id: str,
                     run_index: int = 0) -> JourneyState:
    """Map a TinyFish run onto our contract. A bare list/text lands in result.result."""
    result = run.get("result") or {}
    if isinstance(result, dict) and "result" in result and "steps" not in result:
        result = result["result"]
    if not isinstance(result, dict):
        result = {}

    steps = []
    for i, s in enumerate(result.get("steps", [])):
        steps.append({
            "index": i,
            "name": s.get("name", f"step{i}"),
            "url": s.get("url", ""),
            "price_displayed": s.get("price_displayed"),
            "line_items": [
                {"name": li["name"], "amount": li["amount"], "added_by_us": False}
                for li in s.get("line_items", [])
            ],
            "timers": ([{"label": s["timer_text"]}] if s.get("timer_text") else []),
            "stock_claims": ([{"text": s["stock_text"]}] if s.get("stock_text") else []),
        })

    status = run.get("status", "FAILED")
    err = (run.get("error") or {}).get("code", "")
    outcome = status if status in ("COMPLETED", "FAILED") else "FAILED"
    if status == "TIMEOUT":
        outcome = "TIMEOUT"
    if err in ("SITE_BLOCKED", "TIMEOUT", "MAX_STEPS_EXCEEDED"):
        outcome = err

    return JourneyState(
        observation_id=f"obs_{uuid.uuid4().hex[:8]}",
        probe_spec_id=spec_id,
        platform=platform,
        condition={"session": "fresh", "run_index": run_index},
        steps=steps,
        totals={
            "listed": result.get("listed_price"),
            "payment_page": result.get("payment_page_total"),
        },
        outcome=outcome,
        artifacts={"video_ref": run.get("video_url")},
    )


def replay(spec: ProbeSpec, run_index: int) -> JourneyState:
    """Re-run a KNOWN path. Same goal, same site, so runs stay comparable.
    Until the Browser API is wired, this re-runs the agent with the path pinned
    in the goal, which is already far more stable than a free exploration."""
    headers = _headers()
    pinned = GOAL.format(site=spec.platform, budget=600)
    if spec.discovered_path:
        trail = " -> ".join(
            a.label or a.action for a in spec.discovered_path if a.label or a.action
        )
        pinned += f" Follow exactly this path: {trail}."
    payload = {
        "url": spec.entry_url,
        "goal": pinned,
        "output_schema": JOURNEY_SCHEMA,
        "agent_config": {"max_duration_seconds": 300},
    }
    r = httpx.post(f"{AGENT}/run-async", headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    run = poll(r.json()["run_id"])
    return to_journey_state(run, spec.platform, spec.probe_spec_id, run_index)
