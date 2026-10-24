"""Re-apply the current mapper and rules to a saved TinyFish run, replacing that
observation's old findings. Costs no credits. Use after fixing a rule:

    python -m app.remap samples/runs/<tinyfish_run_id>.json <observation_id> <platform>
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from . import rules, tinyfish  # noqa: E402
from .db import FindingRow, ObservationRow, SessionLocal, init_db  # noqa: E402


def main(run_path: str, observation_id: str, platform: str) -> None:
    init_db()
    run = json.loads(Path(run_path).read_text())
    with SessionLocal() as db:
        obs = db.get(ObservationRow, observation_id)
        if obs is None:
            sys.exit(f"observation {observation_id} not found")
        old = obs.state or {}
        js = tinyfish.to_journey_state(
            run, platform, obs.probe_spec_id, download_video=False,
            logged_in=(old.get("condition", {}).get("session") == "logged_in"))
        # keep identity and evidence from the original observation
        js.observation_id = observation_id
        js.artifacts.video_ref = old.get("artifacts", {}).get("video_ref")

        removed, old_ids = 0, {}
        for fr in db.query(FindingRow).all():
            if observation_id in fr.data.get("evidence", {}).get("observation_ids", []):
                old_ids[fr.pattern] = (fr.finding_id, fr.data.get("detected_at"))
                db.delete(fr)
                removed += 1
        db.flush()

        found = rules.evaluate(js) if js.outcome == "COMPLETED" else []
        for f in found:  # same pattern on the same run keeps its id and time
            if f.pattern in old_ids:
                f.finding_id, when = old_ids[f.pattern]
                if when:
                    f.detected_at = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        obs.state = json.loads(js.model_dump_json())
        obs.outcome = js.outcome
        for f in found:
            db.add(FindingRow(finding_id=f.finding_id, platform=f.platform,
                              pattern=f.pattern, status=f.status,
                              data=json.loads(f.model_dump_json())))
        db.commit()

    print(f"{observation_id}: outcome {js.outcome}, "
          f"listed {js.totals.listed} -> paid {js.totals.payment_page}")
    print(f"removed {removed} old finding(s), added {len(found)}:")
    for f in found:
        print("  ", f.pattern, f.measure)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
