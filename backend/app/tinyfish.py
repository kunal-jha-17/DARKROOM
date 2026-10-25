import copy
import json
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
    # serve stored findings even when TINYFISH_API_KEY is not set yet.
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
        # Flat fallbacks: live runs fill top-level fields more reliably than steps.
        "product_name": {"type": "string"},
        "cart_items_before_adding": {"type": "array", "items": {"type": "string"}},
        "payment_line_items": {
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
    },
    "required": ["steps", "listed_price", "payment_page_total"],
}

GOAL = (
    "FIRST open the cart on {site}. If it already has any items, list their names in "
    "'cart_items_before_adding', then REMOVE them all so the cart is empty. "
    "{pick}"
    "Add exactly ONE to the cart. Proceed until the payment page is displayed. "
    "CRITICAL: do NOT enter any card details and do NOT submit payment. Stop at "
    "the payment page. "
    "Record, for every step: the price displayed, every line item in the cart with "
    "its amount, the text of any countdown timer, the text of any stock warning, "
    "and the final total shown on the payment page. "
    "The 'steps' array MUST have one entry for each page you visit, named exactly "
    "'listing', 'cart', 'checkout' or 'payment', each with its url and price. "
    "Also fill 'product_name', and 'payment_line_items' with EVERY row in the "
    "payment page's price breakdown (product, delivery, fees, add-ons, discounts "
    "as negative amounts). "
    "If a login, OTP, signup wall or bot check stops you, do NOT sign in: stop there "
    "and still return every step you reached (listing, cart, etc.) with what you saw. "
    "After recording the payment page, go back and remove the product from the "
    "cart so the account is left empty. "
    "Return JSON only."
)

# Fast path: reach the payment page FIRST, record it, tidy up only if time allows.
# A timeout during cleanup then still leaves us a complete measurement.
GOAL_FAST = (
    "{pick}"
    "Add exactly ONE to the cart. Go straight to the payment page. "
    "CRITICAL: do NOT enter any card details and do NOT submit payment. Stop at "
    "the payment page. "
    "Record, for every step: the price displayed, every line item in the cart with "
    "its amount, the text of any countdown timer, the text of any stock warning, "
    "and the final total shown on the payment page. "
    "The 'steps' array MUST have one entry for each page you visit, named exactly "
    "'listing', 'cart', 'checkout' or 'payment', each with its url and price. "
    "Also fill 'product_name', and 'payment_line_items' with EVERY row in the "
    "payment page's price breakdown (product, delivery, fees, add-ons, discounts "
    "as negative amounts). "
    "If a login, OTP, signup wall or bot check stops you, do NOT sign in: stop there "
    "and still return every step you reached with what you saw. "
    "ONLY after the payment page is recorded, if there is time, empty the cart. "
    "Returning the JSON matters more than emptying the cart. "
    "Return JSON only."
)

# Words the agent uses in its own action log when a site stops it.
_BLOCKED_RE = re.compile(
    r"\b(blocked|login required|sign[- ]?in required|requires? (login|sign[- ]?in|auth)"
    r"|auth(entication)? (wall|required|requirement)|otp|captcha|access denied"
    r"|not accessible|inaccessible|unreachable|empty responses?|geo[- ]?block\w*)\b",
    re.I,
)


def _profile(profile_id: Optional[str]) -> Optional[str]:
    """Explicit profile, else TINYFISH_PROFILE_ID from .env, else none (fresh run)."""
    return profile_id or os.environ.get("TINYFISH_PROFILE_ID") or None


def _with_profile(payload: dict, profile_id: Optional[str]) -> dict:
    """Attach a signed-in Browser Context Profile so login/OTP walls are already
    passed. The profile's account must have NO saved card or UPI."""
    if profile_id:
        payload["use_profile"] = True
        payload["profile_id"] = profile_id
    return payload


_PRODUCT_PATH = re.compile(
    r"(/p/|/dp/|/gp/product/|/product[s]?/|/item[s]?/|/itm|/buy/|[?&](pid|productid|sku)=)", re.I)
_LISTING_PATH = re.compile(r"(/search|[?&](q|query|k|keyword)=|/pl/|/clp/|/category|/c/|/collections?/)", re.I)


def classify_url(url: Optional[str]) -> str:
    """'product' (one product page), 'listing' (category/search) or 'home'.
    Audits never need a product link: a homepage or category page is enough,
    and the agent picks a product itself."""
    if not url:
        return "home"
    rest = re.sub(r"^https?://[^/]+", "", url.strip())
    if _PRODUCT_PATH.search(rest):
        return "product"
    if _LISTING_PATH.search(rest) or rest.strip("/"):
        return "listing"
    return "home"


def _pick(entry_url: Optional[str], budget: int) -> str:
    kind = classify_url(entry_url)
    if kind == "product":
        return ("Then go back to the start page " + (entry_url or "") + " - that product "
                "is the one to audit. Use THIS product whatever its price; if it needs a "
                "size or variant, pick the cheapest available one. If it cannot be "
                "bought (out of stock or not deliverable), pick the closest similar "
                "product instead and say so in 'product_name'. ")
    if kind == "listing":
        return ("Then go back to the start page " + (entry_url or "") + " and choose a "
                f"product from it priced under {budget} rupees that is in stock and "
                "deliverable. ")
    return (f"Then pick any product on the site priced under {budget} rupees that is "
            "in stock and deliverable to the saved address. Choose it yourself; no "
            "product link is needed. ")


def build_goal(platform: str, budget: int, intent: Optional[str] = None,
               entry_url: Optional[str] = None) -> str:
    """Base goal plus platform-specific notes (e.g. how to order food)."""
    _tmpl = GOAL if os.environ.get("DARKROOM_THOROUGH") == "1" else GOAL_FAST
    goal = _tmpl.format(site=platform, pick=_pick(entry_url, budget))
    if intent:
        goal += (" Platform-specific instructions (follow these, but every rule "
                 f"above still applies, especially never paying): {intent.strip()}")
    return goal


def _start(url: str, goal: str, profile_id: Optional[str]) -> dict:
    """Start one agent run. Probes and replays use exactly this payload, so a
    replay is directly comparable to the original run and is recorded too."""
    headers = _headers()
    payload = _with_profile({
        "url": url,
        "goal": goal,
        "output_schema": JOURNEY_SCHEMA,
        "browser_profile": "stealth",
        # Do NOT send max_steps: it is beta-gated and returns 403 on a normal key.
        "agent_config": {"max_duration_seconds": 600},
        # capture_config is account-gated: a 403 means your key is not enabled.
        "capture_config": {"screenshots": True, "recording": True, "html": True},
    }, profile_id)
    r = httpx.post(f"{AGENT}/run-async", headers=headers, json=payload, timeout=60)
    if r.status_code == 403:
        # fall back without capture rather than failing the run
        print("tinyfish: capture_config rejected (403), retrying without capture")
        payload.pop("capture_config")
        r = httpx.post(f"{AGENT}/run-async", headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def discover(platform: str, entry_url: str, budget: int = 600,
             profile_id: Optional[str] = None, intent: Optional[str] = None) -> dict:
    """Run the Agent API once to map a platform's checkout. Returns the raw run."""
    return _start(entry_url, build_goal(platform, budget, intent, entry_url), profile_id)


def get_run(run_id: str) -> dict:
    r = httpx.get(f"{RUNS}/{run_id}", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def cancel(run_id: str) -> None:
    """Stop a TinyFish run so a stuck agent stops using credits."""
    try:
        httpx.post(f"{RUNS}/{run_id}/cancel", headers=_headers(), timeout=30)
    except Exception as e:
        print("tinyfish: cancel failed:", e)


def poll(run_id: str, timeout_s: int = 900, on_progress=None) -> dict:
    """Poll until terminal. Safer than SSE, which cannot resume.
    on_progress(data) is called on every poll so callers can show live actions.
    TinyFish does not always enforce max_duration_seconds, so after timeout_s we
    cancel the run ourselves instead of letting it loop on our credits."""
    deadline = time.time() + timeout_s
    data: dict = {}
    while time.time() < deadline:
        try:
            data = get_run(run_id)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            # One slow or dropped status check is not a failed run: retry.
            print("tinyfish: status check failed, retrying:", e)
            time.sleep(5)
            continue
        if data.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
            return data
        if on_progress:
            try:
                on_progress(data)
            except Exception:
                pass
        time.sleep(5)
    cancel(run_id)
    # Keep whatever TinyFish has so far (actions, video) and fetch once more,
    # since cancelling finalises the run and its recording.
    try:
        data = get_run(run_id)
    except Exception:
        pass
    data = dict(data or {}, run_id=run_id)
    data["status"] = "TIMEOUT"
    return data


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


# Breakdown rows that summarise the order rather than being an item or a fee.
_SUMMARY_RE = re.compile(
    r"\bprice \(\d+ items?\)"
    r"|\b(product price|items? total|sub ?-?total|order total|grand total"
    r"|total amount|total|amount payable|you pay|to pay|discounts?|savings|you save"
    r"|coupon|mrp|special price)\b", re.I)

# Agent filler meaning "nothing there": N/A, none, "no stock warnings visible",
# or a timer it saw on some OTHER product.
_EMPTY_CLAIM_RE = re.compile(
    r"^\s*(n/?a|none|nil|null|-+|no\b.*|.*\bnot (visible|shown|found|present)\b.*"
    r"|.*\bother products?\b.*)\s*$", re.I)


_UNAVAILABLE_RE = re.compile(
    r"\b(out of stock|not available|unavailable|sold out|no longer|not deliverable"
    r"|currently not)\b", re.I)


def _claim(text: Optional[str]) -> Optional[str]:
    if not text or _EMPTY_CLAIM_RE.match(text):
        return None
    return text


def _timer(text: Optional[str]) -> Optional[str]:
    """A countdown only if it states a time ('Ends in 02:14:05', '2h 30m').
    Badges like 'Top Discount of the Sale' are not timers."""
    t = _claim(text)
    return t if t and _seconds(t) is not None else None


def _stock(text: Optional[str]) -> Optional[str]:
    """A scarcity claim ('Only 2 left'), not an unavailability notice."""
    t = _claim(text)
    return t if t and not _UNAVAILABLE_RE.search(t) else None


def _is_summary(name: str) -> bool:
    return bool(_SUMMARY_RE.search(name))


_STOP = {"the", "and", "for", "with", "set", "of", "pack", "item", "from", "listing", "new"}


def _tokens(name: str) -> set:
    return {w.rstrip("s") for w in re.findall(r"[a-z]{3,}", name.lower())} - _STOP


def _is_ours(name: str, amount: float, product: str, listed: Optional[float]) -> bool:
    """The product we added. Names drift between pages ('OWO Heavy Duty Bullet
    Jar Set...' on the listing, 'Mixer Grinder Jars' at payment), so match on
    shared words or on the listed price."""
    if listed is not None and abs(amount - listed) < 1:
        return True
    return bool(product) and len(_tokens(name) & _tokens(product)) >= 2


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


def last_actions(run: dict, n: int = 5) -> list:
    return [a.get("action") for a in (run.get("steps") or [])[-n:] if a.get("action")]


RUN_LOG_DIR = Path(__file__).resolve().parents[1] / "samples" / "runs"


def save_run(run: dict) -> None:
    """Keep every raw run (credentials stripped) so a failure can be explained.
    samples/runs/ is git-ignored; copy a good one up to samples/ to commit it."""
    try:
        RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
        (RUN_LOG_DIR / f"{run.get('run_id', 'unknown')}.json").write_text(
            json.dumps(redact(run), indent=2))
    except Exception as e:
        print("tinyfish: could not save run log:", e)


def redact(run: dict) -> dict:
    """Copy of a run that is safe to commit: strips the temporary AWS
    credentials embedded in the pre-signed video and stream links."""
    out = copy.deepcopy(run)
    for key in ("video_url", "streaming_url"):
        if out.get(key):
            out[key] = out[key].split("?")[0] + "?<redacted>"
    return out


def to_journey_state(run: dict, platform: str, spec_id: str,
                     run_index: int = 0, download_video: bool = True,
                     logged_in: bool = False) -> JourneyState:
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
                and float(li["amount"]) > 0 and not _is_summary(li["name"])
            ],
            "timers": ([{"label": _timer(s.get("timer_text")),
                         "seconds_left": _seconds(_timer(s.get("timer_text")))}]
                       if _timer(s.get("timer_text")) else []),
            "stock_claims": ([{"text": _stock(s.get("stock_text")),
                               "value": _count(_stock(s.get("stock_text")))}]
                             if _stock(s.get("stock_text")) else []),
        })

    listed = _price(result.get("listed_price"))
    paid = _price(result.get("payment_page_total"))
    pay_items = [
        {"name": li["name"], "amount": float(li["amount"]), "added_by_us": False}
        for li in (result.get("payment_line_items") or [])
        if li.get("name") and li.get("amount") is not None
        and float(li["amount"]) > 0 and not _is_summary(li["name"])
    ]
    # Live runs often return the totals but leave 'steps' empty. If the agent
    # reported both ends of the journey, rebuild the minimum two steps from them
    # so the run counts and the rules can read it.
    if not steps and listed is not None and paid is not None:
        product = result.get("product_name") or "product"
        steps = [
            {"index": 0, "name": "listing", "url": run.get("url") or "",
             "price_displayed": listed, "line_items": [],
             "timers": [], "stock_claims": []},
            {"index": 1, "name": "payment", "url": "",
             "price_displayed": paid,
             "line_items": pay_items or [{"name": product, "amount": listed,
                                          "added_by_us": True}],
             "timers": [], "stock_claims": []},
        ]
    elif pay_items:
        # Prefer the full breakdown on the payment step when the agent gave one.
        pay_step = next((s for s in reversed(steps) if "payment" in s["name"]), None)
        if pay_step is not None and len(pay_items) > len(pay_step["line_items"]):
            pay_step["line_items"] = pay_items

    # Mark the product we added, at most one row per step. Everything else at
    # checkout was not chosen by us: a fee (drip pricing), an add-on (basket
    # sneaking) or something already in the cart before we started.
    product = (result.get("product_name") or "").strip()
    if not product:
        product = next((s["line_items"][0]["name"] for s in steps if s["line_items"]), "")
    for st in steps:
        for li in st["line_items"]:
            if _is_ours(li["name"], li["amount"], product, listed):
                li["added_by_us"] = True
                break

    # The payment breakdown often lists only fees. Show our product there too,
    # so the journey reads "earphones ₹139 + delivery ₹40", not just the fee.
    pay_step = next((st for st in reversed(steps) if st["name"] == "payment"
                     or "payment" in st["name"]), None)
    if pay_step is not None and not any(li["added_by_us"] for li in pay_step["line_items"]):
        mine = next((li for st in steps for li in st["line_items"] if li["added_by_us"]), None)
        if mine is None and listed is not None and product:
            mine = {"name": product, "amount": listed, "added_by_us": True}
        if mine is not None:
            pay_step["line_items"].insert(0, {"name": mine["name"], "amount": mine["amount"],
                                              "added_by_us": True})

    # Items the agent found in the cart before adding ours (account leftovers).
    pre_existing = [n for n in (result.get("cart_items_before_adding") or [])
                    if isinstance(n, str) and n.strip()]
    for st in steps:
        for li in st["line_items"]:
            if not li["added_by_us"] and any(
                    len(_tokens(li["name"]) & _tokens(n)) >= 1 or
                    li["name"].strip().lower() == n.strip().lower() for n in pre_existing):
                li["pre_existing"] = True

    status = run.get("status", "FAILED")
    err = (run.get("error") or {}).get("code", "")
    outcome = status if status in ("COMPLETED", "FAILED") else "FAILED"
    if status == "TIMEOUT":
        outcome = "TIMEOUT"
    if err in ("SITE_BLOCKED", "TIMEOUT", "MAX_STEPS_EXCEEDED"):
        outcome = err
    # The agent reports COMPLETED even when a login/OTP wall or bot check stopped
    # it. Its own action log says so; record that as SITE_BLOCKED.
    actions = " | ".join(a.get("action") or "" for a in (run.get("steps") or [])[-3:])
    reached_payment = any("payment" in s["name"] for s in steps)
    if outcome == "COMPLETED" and not reached_payment and _BLOCKED_RE.search(actions):
        outcome = "SITE_BLOCKED"
    # No recorded checkout steps at all means the journey did not happen.
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
        condition={"session": "logged_in" if logged_in or run.get("profile_attached")
                   else "fresh", "run_index": run_index},
        steps=steps,
        totals={
            "listed": _price(result.get("listed_price")),
            "payment_page": _price(result.get("payment_page_total")),
        },
        outcome=outcome,
        artifacts={"video_ref": video_ref, "dom_refs": dom_refs},
    )


def replay(spec: ProbeSpec, run_index: int,
           profile_id: Optional[str] = None, on_progress=None) -> JourneyState:
    """Re-run a KNOWN path. Same goal, same site, so runs stay comparable.
    Until the Browser API is wired, this re-runs the agent with the path pinned
    in the goal, which is already far more stable than a free exploration."""
    pinned = spec.goal or build_goal(spec.platform, 600, None, spec.entry_url)
    if spec.discovered_path:
        trail = " -> ".join(
            a.label or a.action for a in spec.discovered_path if a.label or a.action
        )
        pinned += f" Follow exactly this path: {trail}."
    started = _start(spec.entry_url, pinned, profile_id)
    run = poll(started["run_id"], on_progress=on_progress)
    save_run(run)
    return to_journey_state(run, spec.platform, spec.probe_spec_id, run_index,
                            logged_in=bool(profile_id))


# ---------- one-time login setup (Browser Context Profiles) ----------

def create_profile(name: str) -> dict:
    """Create an empty profile. Then sign in to the site once in the TinyFish
    dashboard's setup browser (you type the OTP), save it, and put the
    profile id in .env as TINYFISH_PROFILE_ID."""
    r = httpx.post(f"{AGENT.rsplit('/automation', 1)[0]}/profiles", headers=_headers(),
                   json={"name": name, "set_as_default": False}, timeout=30)
    r.raise_for_status()
    return r.json()
