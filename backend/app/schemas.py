from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- building blocks ----------

class Timer(BaseModel):
    label: str
    seconds_left: Optional[int] = None


class StockClaim(BaseModel):
    text: str
    value: Optional[int] = None


class LineItem(BaseModel):
    name: str
    amount: float
    added_by_us: bool = False  # False here is what proves basket sneaking


class Checkbox(BaseModel):
    label: str
    checked: bool


class Button(BaseModel):
    text: str
    role: Optional[str] = None


class Step(BaseModel):
    index: int
    name: str  # listing | cart | checkout | payment
    url: str
    price_displayed: Optional[float] = None
    currency: str = "INR"
    line_items: list[LineItem] = []
    timers: list[Timer] = []
    stock_claims: list[StockClaim] = []
    checkboxes: list[Checkbox] = []
    buttons: list[Button] = []
    screenshot_ref: Optional[str] = None


class Totals(BaseModel):
    listed: Optional[float] = None
    cart: Optional[float] = None
    payment_page: Optional[float] = None


class Artifacts(BaseModel):
    video_ref: Optional[str] = None
    dom_refs: list[str] = []
    hashes: dict[str, str] = {}


class Condition(BaseModel):
    session: Literal["fresh", "returning", "logged_in"] = "fresh"
    run_index: int = 0
    captured_at: datetime = Field(default_factory=datetime.utcnow)


# ---------- the three contracts ----------

Outcome = Literal[
    "COMPLETED", "FAILED", "SITE_BLOCKED", "TIMEOUT", "MAX_STEPS_EXCEEDED"
]


class JourneyState(BaseModel):
    observation_id: str
    probe_spec_id: str
    platform: str
    condition: Condition = Condition()
    steps: list[Step] = []
    totals: Totals = Totals()
    outcome: Outcome = "COMPLETED"
    artifacts: Artifacts = Artifacts()


class PathAction(BaseModel):
    action: Literal["goto", "click", "type", "wait", "capture"]
    url: Optional[str] = None
    selector: Optional[str] = None
    value: Optional[str] = None
    label: Optional[str] = None


class ProbeSpec(BaseModel):
    probe_spec_id: str
    platform: str
    journey: str = "purchase_to_payment"
    entry_url: str
    goal: str
    discovered_path: list[PathAction] = []
    stop_rule: str = "never_submit_payment"


Pattern = Literal[
    "drip_pricing", "basket_sneaking", "false_urgency",
    "cancel_friction", "confirm_shaming", "trick_wording",
]


class Finding(BaseModel):
    finding_id: str
    platform: str
    pattern: Pattern
    severity: Literal["low", "medium", "high"] = "medium"
    measure: dict = {}
    clause: str
    evidence: dict = {}
    status: Literal["candidate", "confirmed"] = "candidate"
    detected_at: datetime = Field(default_factory=datetime.utcnow)


CLAUSE = {
    "drip_pricing": "CCPA Guidelines for Prevention and Regulation of Dark Patterns, 2023 — drip pricing",
    "basket_sneaking": "CCPA Dark Patterns Guidelines, 2023 — basket sneaking",
    "false_urgency": "CCPA Dark Patterns Guidelines, 2023 — false urgency",
    "cancel_friction": "CCPA Dark Patterns Guidelines, 2023 — subscription trap",
    "confirm_shaming": "CCPA Dark Patterns Guidelines, 2023 — confirm shaming",
    "trick_wording": "CCPA Dark Patterns Guidelines, 2023 — trick wording",
}
