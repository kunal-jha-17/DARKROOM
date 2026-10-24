import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv

# Load backend/.env before anything reads DATABASE_URL or TINYFISH_API_KEY.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import rules, tinyfish  # noqa: E402
from .db import FindingRow, ObservationRow, SessionLocal, SpecRow, init_db  # noqa: E402
from .schemas import Finding, JourneyState, ProbeSpec  # noqa: E402

app = FastAPI(title="DARKROOM")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

RUNS: dict[str, dict] = {}  # in-memory run status, fine for a hackathon

# Recordings downloaded from TinyFish. Served under /api/media so they travel
# through the frontend's existing /api proxy; /evidence kept for old links.
tinyfish.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/media", StaticFiles(directory=tinyfish.EVIDENCE_DIR), name="media")
app.mount("/evidence", StaticFiles(directory=tinyfish.EVIDENCE_DIR), name="evidence")


@app.on_event("startup")
def _startup():
    # Findings live in the database (SQLite file or Postgres), so they survive
    # restarts. No seed or sample data is ever loaded.
    init_db()


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------- read side: only real, stored data ----------

def _video(ref):
    """Public path for a recording, or None if the file is not on disk,
    so the API never hands out a link that 404s."""
    if not ref:
        return None
    if ref.startswith("http"):
        return ref
    name = os.path.basename(ref)
    if not (tinyfish.EVIDENCE_DIR / name).is_file():
        return None
    return f"/api/media/{name}"


def _utc(ts):
    """ISO 8601 UTC. Older rows were stored without a timezone; they are UTC."""
    if not ts:
        return ts
    if ts.endswith("Z") or "+" in ts[10:]:
        return ts
    return ts + "Z"


_STEP_NAMES = (("pay", "payment"), ("checkout", "checkout"), ("address", "checkout"),
               ("summary", "checkout"), ("cart", "cart"), ("bag", "cart"),
               ("basket", "cart"))


def _step_name(name: str) -> str:
    n = (name or "").lower()
    return next((v for k, v in _STEP_NAMES if k in n), "listing")


def _public_state(state: dict) -> dict:
    st = json.loads(json.dumps(state))
    arts = st.setdefault("artifacts", {})
    arts["video_ref"] = _video(arts.get("video_ref"))
    arts.pop("dom_refs", None)  # TinyFish-internal links, need its API key
    steps = []
    for step in st.get("steps", []):
        step["name"] = _step_name(step.get("name"))
        # Items already in the account's cart are not part of the audited
        # journey and may be personal; keep them out of the public view.
        items = step.get("line_items", [])
        kept = [li for li in items if not li.get("pre_existing")]
        if items and not kept:
            continue  # the account's old cart, before the agent cleared it
        step["line_items"] = kept
        steps.append(step)
    # Drop cart-clearing steps that are now empty and carry no price.
    st["steps"] = [s for s in steps if s["line_items"] or s.get("price_displayed")
                   or s["name"] == "payment"]
    for i, s in enumerate(st["steps"]):
        s["index"] = i
    return st


def _reproduced_in(db, finding: dict) -> str:
    """'N of M observations', computed from stored rows: N observations carry
    this finding, M completed observations exist for the same probe spec(s)."""
    ids = finding.get("evidence", {}).get("observation_ids", [])
    if not ids:
        return "0 of 0 observations"
    obs = db.query(ObservationRow).filter(ObservationRow.observation_id.in_(ids)).all()
    specs = {o.probe_spec_id for o in obs}
    total = db.query(ObservationRow).filter(
        ObservationRow.probe_spec_id.in_(specs),
        ObservationRow.outcome == "COMPLETED").count() if specs else 0
    hits = sum(1 for o in obs if o.outcome == "COMPLETED")
    return f"{hits} of {max(total, hits)} observations"


def _has_number(measure: dict) -> bool:
    return any(isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0
               for v in (measure or {}).values())


def _public_finding(db, data: dict) -> dict:
    f = json.loads(json.dumps(data))
    ev = f.setdefault("evidence", {})
    ev["video_ref"] = _video(ev.get("video_ref"))
    ev["reproduced_in"] = _reproduced_in(db, f)
    f["detected_at"] = _utc(f.get("detected_at"))
    # Integrity: confirmed only with a measured number, a recording and a clause.
    if f.get("status") == "confirmed" and not (
            _has_number(f.get("measure")) and ev["video_ref"] and f.get("clause")):
        f["status"] = "candidate"
    return f


@app.get("/api/findings")
def list_findings():
    with SessionLocal() as db:
        found = [_public_finding(db, r.data) for r in db.query(FindingRow).all()]
    found.sort(key=lambda f: f.get("detected_at") or "", reverse=True)
    return {"findings": found}


@app.get("/api/findings/{finding_id}")
def get_finding(finding_id: str):
    with SessionLocal() as db:
        row = db.get(FindingRow, finding_id)
        if row is None:
            raise HTTPException(404, "finding not found")
        finding = _public_finding(db, row.data)
        ids = finding["evidence"].get("observation_ids", [])
        states = [_public_state(o.state) for o in db.query(ObservationRow)
                  .filter(ObservationRow.observation_id.in_(ids)).all()]
    return {"finding": finding, "journey_states": states}


# ---------- persistence helpers ----------

def _save_state(db, js: JourneyState) -> None:
    db.add(ObservationRow(
        observation_id=js.observation_id, probe_spec_id=js.probe_spec_id,
        platform=js.platform, outcome=js.outcome,
        state=json.loads(js.model_dump_json())))


def _save_finding(db, f: Finding) -> None:
    db.merge(FindingRow(
        finding_id=f.finding_id, platform=f.platform,
        pattern=f.pattern, status=f.status,
        data=json.loads(f.model_dump_json())))


# ---------- probes: discover once ----------

class ProbeRequest(BaseModel):
    platform: str
    entry_url: str
    intent: Optional[str] = None
    # "logged_in" uses a saved TinyFish Browser Context Profile so login/OTP
    # walls are already passed. profile_id falls back to TINYFISH_PROFILE_ID.
    session: Literal["fresh", "logged_in"] = "fresh"
    profile_id: Optional[str] = None
    # Price ceiling for the product the agent picks. Cheaper items are more
    # likely to sit below free-delivery thresholds, where fees show up.
    budget: int = 600


def _resolve_profile(session: str, profile_id: Optional[str]) -> Optional[str]:
    if session != "logged_in":
        return None
    pid = tinyfish._profile(profile_id)
    if not pid:
        raise ValueError("session=logged_in needs a profile_id or TINYFISH_PROFILE_ID in .env")
    return pid


def _live(run_id: str, label: str):
    """Progress callback: surface the agent's latest actions while it runs."""
    def update(data: dict):
        RUNS[run_id] = {
            "status": "RUNNING",
            "progress": label,
            "agent_actions": tinyfish.last_actions(data),
            "steps_taken": data.get("num_of_steps"),
            "live_view_url": data.get("streaming_url"),
            "tinyfish_run_id": data.get("run_id"),
        }
    return update


def _execute(run_id: str, req: ProbeRequest):
    RUNS[run_id] = {"status": "RUNNING", "progress": "discovering path"}
    try:
        profile_id = _resolve_profile(req.session, req.profile_id)
        started = tinyfish.discover(req.platform, req.entry_url, budget=req.budget,
                                    profile_id=profile_id, intent=req.intent)
        run = tinyfish.poll(started["run_id"],
                            on_progress=_live(run_id, "discovering path"))
        spec_id = f"spec_{uuid.uuid4().hex[:6]}"
        spec = ProbeSpec(
            probe_spec_id=spec_id, platform=req.platform,
            entry_url=req.entry_url,
            goal=tinyfish.build_goal(req.platform, req.budget, req.intent),
        )
        tinyfish.save_run(run)  # full agent log, for debugging failed runs
        js = tinyfish.to_journey_state(run, req.platform, spec_id,
                                       logged_in=bool(profile_id))

        RUNS[run_id] = {"status": "RUNNING", "progress": "evaluating rules"}
        found = rules.evaluate(js) if js.outcome == "COMPLETED" else []

        with SessionLocal() as db:
            # profile_id rides alongside the frozen ProbeSpec so replays reuse it
            db.add(SpecRow(probe_spec_id=spec_id, platform=spec.platform,
                           data={**json.loads(spec.model_dump_json()),
                                 "profile_id": profile_id}))
            _save_state(db, js)
            for f in found:
                _save_finding(db, f)
            db.commit()

        why = {"SITE_BLOCKED": "site blocked the agent",
               "TIMEOUT": "run timed out and was stopped",
               "MAX_STEPS_EXCEEDED": "agent ran out of steps"}.get(js.outcome,
                                                                   "agent did not reach payment")
        RUNS[run_id] = {
            "status": "COMPLETED" if js.outcome == "COMPLETED" else "FAILED",
            "outcome": js.outcome,
            "progress": (f"{len(found)} finding(s)" if js.outcome == "COMPLETED" else why),
            "probe_spec_id": spec_id,
            "observation_id": js.observation_id,
            "finding_id": found[0].finding_id if found else None,
            # why it ended: the agent's own last few actions
            "agent_actions": tinyfish.last_actions(run),
            "profile_attached": run.get("profile_attached"),
            "tinyfish_run_id": run.get("run_id"),
        }
    except Exception as e:
        RUNS[run_id] = {"status": "FAILED", "progress": str(e)[:200]}


@app.post("/api/probes")
def create_probe(req: ProbeRequest):
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    RUNS[run_id] = {"status": "PENDING", "progress": "queued"}
    threading.Thread(target=_execute, args=(run_id, req), daemon=True).start()
    return {"run_id": run_id, "status": "PENDING"}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


# ---------- replay many + confirm ----------

class ReplayRequest(BaseModel):
    runs: int = 3


def _replay(run_id: str, spec_id: str, n: int):
    try:
        with SessionLocal() as db:
            row = db.get(SpecRow, spec_id)
            if not row:
                raise ValueError(f"spec {spec_id} not found")
            spec = ProbeSpec(**row.data)
            profile_id = row.data.get("profile_id")
            prior = [JourneyState(**o.state) for o in db.query(ObservationRow)
                     .filter(ObservationRow.probe_spec_id == spec_id).all()]

        states = list(prior)
        for i in range(n):
            RUNS[run_id] = {"status": "RUNNING", "progress": f"replay {i + 1} of {n}"}
            js = tinyfish.replay(spec, run_index=len(states), profile_id=profile_id,
                                 on_progress=_live(run_id, f"replay {i + 1} of {n}"))
            with SessionLocal() as db:
                _save_state(db, js)
                db.commit()
            states.append(js)

        RUNS[run_id] = {"status": "RUNNING", "progress": "confirming findings"}
        completed = [s for s in states if s.outcome == "COMPLETED"]
        candidates = [f for s in completed for f in rules.evaluate(s)]
        confirmed = rules.confirm(candidates, len(completed))
        confirmed += rules.evaluate_many(completed)

        with SessionLocal() as db:
            # replace this spec's per-run candidates with the merged findings
            obs_ids = {s.observation_id for s in states}
            for fr in db.query(FindingRow).filter(
                    FindingRow.platform == spec.platform).all():
                if set(fr.data.get("evidence", {}).get("observation_ids", [])) & obs_ids:
                    db.delete(fr)
            for f in confirmed:
                _save_finding(db, f)
            db.commit()

        RUNS[run_id] = {
            "status": "COMPLETED",
            "progress": f"{len(confirmed)} finding(s) across {len(completed)} observations",
            "probe_spec_id": spec_id,
            "finding_id": confirmed[0].finding_id if confirmed else None,
        }
    except Exception as e:
        RUNS[run_id] = {"status": "FAILED", "progress": str(e)[:200]}


@app.post("/api/specs/{spec_id}/replay")
def replay_spec(spec_id: str, req: ReplayRequest = ReplayRequest()):
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    RUNS[run_id] = {"status": "PENDING", "progress": "queued"}
    threading.Thread(target=_replay, args=(run_id, spec_id, req.runs),
                     daemon=True).start()
    return {"run_id": run_id, "status": "PENDING"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
