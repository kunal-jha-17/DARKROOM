"""Fetch a TinyFish run that finished after the backend stopped waiting,
save it (credentials stripped), download its video, and re-score it.
Costs no credits.

    python -m app.fetch_run <tinyfish_run_id> <observation_id> <platform>
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from . import remap, tinyfish  # noqa: E402
from .db import ObservationRow, SessionLocal, init_db  # noqa: E402


def main(tf_run_id: str, observation_id: str, platform: str) -> None:
    run = tinyfish.get_run(tf_run_id)
    status = run.get("status")
    print(f"TinyFish run {tf_run_id}: {status}")
    print("last agent actions:", tinyfish.last_actions(run))
    if status not in ("COMPLETED", "FAILED", "CANCELLED"):
        sys.exit("still running - try again in a minute")

    tinyfish.save_run(run)
    path = tinyfish.RUN_LOG_DIR / f"{tf_run_id}.json"

    # The video link is fresh now (it expires after 15 min), so grab it.
    video = tinyfish.save_video(run)
    if video:
        init_db()
        with SessionLocal() as db:
            obs = db.get(ObservationRow, observation_id)
            if obs is not None:
                state = dict(obs.state or {})
                state.setdefault("artifacts", {})["video_ref"] = video
                obs.state = state
                db.commit()
        print("video saved:", video)

    remap.main(str(path), observation_id, platform)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
