import copy
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx

from .schemas import JourneyState, PathAction, ProbeSpec  # noqa: F401

AGENT = "https://agent.tinyfish.ai/v1/automation"
RUNS = "https://agent.tinyfish.ai/v1/runs"

# TinyFish's video_url is a pre-signed S3 link that expires after 15 minutes,
# so recordings are downloaded here as soon as a run finishes.
EVIDENCE_DIR = Path(__file__).resolve().parents[1] / "evidence"


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


def _price(v) -> Optional[float]:
    """The agent returns 0 when it could not find a price. Treat that as unknown,
    otherwise a missing total would look like a real ₹0 and break drip_pricing."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _seconds(text: Optional[str]) -> Optional[int]:
    """'Ends in 02:14:05', '14:05 left' or '2h 14m' -> seconds. None if no time found."""
    if not text:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
        return a * 3600 + b * 60 + int(c) if c is not None else a * 60 + b
    total, found = 0, False
    for n, unit in re.findall(r"(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)\b", text, re.I):
        found = True
        u = unit.lower()[0]
        total += int(n) * (3600 if u == "h" else 60 if u == "m" else 1)
    return total if found else None


def _count(text: Optional[str]) -> Optional[int]:
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def save_video(run: dict) -> Optional[str]:
    """Download the run's recording before its pre-signed link expires.
    Returns the path the API serves it at, or None if there is no video."""
    url = run.get("video_url")
    run_id = run.get("run_id")
    if not url or not run_id:
        return None
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        dest = EVIDENCE_DIR / f"{run_id}.webm"
        with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return f"/evidence/{run_id}.webm"
    except Exception as e:
        print("tinyfish: could not download video:", e)
        return None


def redact(run: dict) -> dict:
    """Copy of a run that is safe to commit: strips the temporary AWS
    credentials embedded in the pre-signed video and stream links."""
    out = copy.deepcopy(run)
    for key in ("video_url", "streaming_url"):
        if out.get(key):
            out[key] = out[key].split("?")[0] + "?<redacted>"
    return out


def to_journey_state(run: dict, platform: str, spec_id: str,
                     run_index: int = 0, download_video: bool = True) -> JourneyState:
    """Map a TinyFish run onto our contract. A bare list/text lands in result.result."""
    result = run.get("result") or {}
    if isinstance(result, dict) and "result" in result and "steps" not in result:
        result = result["result"]
    if not isinstance(result, dict):
        result = {}

    steps = []
    for i, s in enumerate(result.get("steps") or []):
        steps.append({
            "index": i,
            "name": (s.get("name") or f"step{i}").strip().lower(),
            "url": s.get("url") or "",
            "price_displayed": _price(s.get("price_displayed")),
            "line_items": [
                {"name": li["name"], "amount": float(li["amount"]), "added_by_us": False}
                for li in (s.get("line_items") or [])
                if li.get("name") and li.get("amount") is not None
            ],
            "timers": ([{"label": s["timer_text"], "seconds_left": _seconds(s["timer_text"])}]
                       if s.get("timer_text") else []),
            "stock_claims": ([{"text": s["stock_text"], "value": _count(s["stock_text"])}]
                             if s.get("stock_text") else []),
        })

    # The goal adds exactly ONE product, so the first line item to appear in the
    # journey is ours. Mark it added_by_us wherever it shows up; anything else
    # at checkout was put there by the platform (the basket-sneaking signal).
    ours = next((s["line_items"][0]["name"] for s in steps if s["line_items"]), None)
    if ours:
        key = ours.strip().lower()
        for s in steps:
            for li in s["line_items"]:
                if li["name"].strip().lower() == key:
                    li["added_by_us"] = True

    status = run.get("status", "FAILED")
    err = (run.get("error") or {}).get("code", "")
    outcome = status if status in ("COMPLETED", "FAILED") else "FAILED"
    if status == "TIMEOUT":
        outcome = "TIMEOUT"
    if err in ("SITE_BLOCKED", "TIMEOUT", "MAX_STEPS_EXCEEDED"):
        outcome = err
    # The agent reports COMPLETED even when it gave up (e.g. "not a valid
    # website"). No recorded checkout steps means the journey did not happen.
    if outcome == "COMPLETED" and not steps:
        outcome = "FAILED"

    # Per-action page snapshots TinyFish keeps for the run (the agent's own steps,
    # not our journey steps). Kept as evidence references.
    dom_refs = [a["html"] for a in (run.get("steps") or []) if a.get("html")]
    video_ref = save_video(run) if download_video else None

    return JourneyState(
        observation_id=f"obs_{uuid.uuid4().hex[:8]}",
        probe_spec_id=spec_id,
        platform=platform,
        condition={"session": "fresh", "run_index": run_index},
        steps=steps,
        totals={
            "listed": _price(result.get("listed_price")),
            "payment_page": _price(result.get("payment_page_total")),
        },
        outcome=outcome,
        artifacts={"video_ref": video_ref, "dom_refs": dom_refs},
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
