import json
import threading
import uuid
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
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SEED = Path(__file__).resolve().parents[2] / "seed"
RUNS: dict[str, dict] = {}  # in-memory run status, fine for a hackathon

# Downloaded recordings, served at /evidence/<run_id>.webm for the dashboard.
tinyfish.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=tinyfish.EVIDENCE_DIR), name="evidence")


@app.on_event("startup")
def _startup():
    try:
        init_db()
    except Exception as e:  # never let a DB hiccup take the API down
        print("db init failed, serving seed only:", e)


@app.get("/api/health")
def health():
    return {"ok": True}


def _seed_findings() -> list[dict]:
    f = SEED / "findings.json"
    return json.loads(f.read_text()) if f.exists() else []


def _seed_states() -> list[dict]:
    f = SEED / "journey_states.json"
    return json.loads(f.read_text()) if f.exists() else []


@app.get("/api/findings")
def list_findings():
    """DB first; falls back to seed so the dashboard is never empty."""
    try:
        with SessionLocal() as db:
            rows = db.query(FindingRow).order_by(FindingRow.created_at.desc()).all()
            if rows:
                return {"findings": [r.data for r in rows]}
    except Exception:
        pass
    return {"findings": _seed_findings()}


@app.get("/api/findings/{finding_id}")
def get_finding(finding_id: str):
    try:
        with SessionLocal() as db:
            row = db.get(FindingRow, finding_id)
            if row:
                ids = row.data.get("evidence", {}).get("observation_ids", [])
                states = [
                    o.state for o in db.query(ObservationRow)
                    .filter(ObservationRow.observation_id.in_(ids)).all()
                ]
                return {"finding": row.data, "journey_states": states}
    except Exception:
        pass
    for f in _seed_findings():
        if f["finding_id"] == finding_id:
            ids = set(f.get("evidence", {}).get("observation_ids", []))
            states = [s for s in _seed_states() if s["observation_id"] in ids]
            return {"finding": f, "journey_states": states}
    raise HTTPException(404, "finding not found")


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


def _resolve_profile(session: str, profile_id: Optional[str]) -> Optional[str]:
    if session != "logged_in":
        return None
    pid = tinyfish._profile(profile_id)
    if not pid:
        raise ValueError("session=logged_in needs a profile_id or TINYFISH_PROFILE_ID in .env")
    return pid


def _execute(run_id: str, req: ProbeRequest):
    RUNS[run_id] = {"status": "RUNNING", "progress": "discovering path"}
    try:
        profile_id = _resolve_profile(req.session, req.profile_id)
        started = tinyfish.discover(req.platform, req.entry_url, profile_id=profile_id)
        run = tinyfish.poll(started["run_id"])
        spec_id = f"spec_{uuid.uuid4().hex[:6]}"
        spec = ProbeSpec(
            probe_spec_id=spec_id, platform=req.platform,
            entry_url=req.entry_url,
            goal=tinyfish.GOAL.format(site=req.platform, budget=600),
        )
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

        RUNS[run_id] = {
            "status": "COMPLETED" if js.outcome == "COMPLETED" else js.outcome,
            "progress": f"{len(found)} finding(s)",
            "probe_spec_id": spec_id,
            "observation_id": js.observation_id,
            "finding_id": found[0].finding_id if found else None,
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
    return RUNS.get(run_id, {"status": "UNKNOWN", "progress": ""})


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
            js = tinyfish.replay(spec, run_index=len(states), profile_id=profile_id)
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
