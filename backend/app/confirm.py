"""Confirm a spec's findings from the observations already stored. No credits.

    python -m app.confirm <probe_spec_id>
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from .db import ObservationRow, SessionLocal, init_db  # noqa: E402
from .main import confirm_spec  # noqa: E402


def main(spec_id: str) -> None:
    init_db()
    with SessionLocal() as db:
        rows = db.query(ObservationRow).filter(
            ObservationRow.probe_spec_id == spec_id).all()
        print(f"{spec_id}: {len(rows)} stored observation(s)")
        for o in rows:
            t = (o.state or {}).get("totals", {})
            print(f"  {o.observation_id}  {o.outcome:12}  listed {t.get('listed')} -> paid {t.get('payment_page')}")
    merged, total = confirm_spec(spec_id)
    print(f"{len(merged)} finding(s) across {total} completed observation(s):")
    for f in merged:
        print(f"  {f.finding_id}  {f.pattern}  {f.status}  {f.measure}  "
              f"reproduced in {f.evidence.get('reproduced_in')}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
