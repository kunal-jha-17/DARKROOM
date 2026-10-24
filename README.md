# DARKROOM

**Dark patterns caught on live Indian checkouts, with evidence.**

Built by **Team CryptiX** for **HackIIITD Esya '26**.

DARKROOM sends an AI browser agent to shop on real e-commerce sites. The agent adds a product to the cart, walks to the payment page and stops. It never pays. DARKROOM records the displayed price at every step, then applies plain rules to the recording. A ₹499 item that costs ₹626 on the payment page becomes a finding, with the price ladder, the legal clause and the run recording as proof.

> DARKROOM reports measurements, not verdicts. Figures describe what the interface displayed during an automated session that never completed a payment. Platforms are offered a right of reply before publication.

## How it works

1. **Probe.** A probe is started with a platform name and an entry URL. The backend asks the [TinyFish](https://agent.tinyfish.ai) browser agent to shop up to the payment page, and downloads the run recording before its link expires.
2. **Journey state.** The agent's output is mapped into a `JourneyState`: the steps (listing, cart, checkout, payment), the price shown at each step, the line items, timers and stock claims. Items already in the account's cart before the run are left out of the public view.
3. **Rules.** Pure functions in `backend/app/rules.py` (no model, no network, no database) compare the steps and produce findings.
4. **Confirmation.** A rule that fires once gives a **candidate**. A finding is **confirmed** only when it was reproduced in at least 2 runs and in most of them. The API also downgrades a "confirmed" finding to a candidate if it has no measured number, no recording or no legal clause.
5. **Dashboard.** The Next.js frontend lists findings and shows each one with its price ladder and evidence.

### What it detects

| Pattern | Rule |
| --- | --- |
| Drip pricing | The payment total is higher than the listed price plus anything else the shopper added. The difference is reported in rupees and percent. |
| Basket sneaking | The platform added a product (protection, warranty, donation and similar) that is not a fee and not the item the agent chose. |
| False urgency | Needs two observations hours apart. A countdown timer that did not go down, or an identical stock claim after 20 hours or more. |
| Subscription trap | Cancelling takes more than 3 times as many steps as subscribing. |

`confirm_shaming` and `trick_wording` have labels and legal clauses defined, but no rule yet.

Each finding cites the matching clause from the CCPA Guidelines for Prevention and Regulation of Dark Patterns, 2023.

## Repository layout

```
DARKROOM/
├── frontend/                 Next.js dashboard
│   ├── app/                  pages: / (findings list), /f/[id] (finding detail)
│   ├── components/           FindingCard, PriceLadder, RunBar, StatusBadge
│   └── lib/                  api.ts, measure.ts, types.ts, sample.ts
└── backend/                  FastAPI service
    ├── app/
    │   ├── main.py           API routes and the probe and replay workers
    │   ├── rules.py          dark-pattern rules and confirmation
    │   ├── tinyfish.py       TinyFish client and the journey-state mapper
    │   ├── schemas.py        Finding, JourneyState, ProbeSpec and clauses
    │   ├── db.py             SQLAlchemy models (Postgres or SQLite)
    │   ├── confirm.py        CLI: re-confirm a spec from stored runs
    │   ├── remap.py          CLI: re-score a saved run after a rule change
    │   └── fetch_run.py      CLI: fetch a run that finished late
    ├── tests/fixtures/       example findings and journey states
    └── samples/              saved example runs (not read by the API)
```

## Getting started

Requirements: Node.js 20.9 or newer, Python 3, and either PostgreSQL or SQLite for storage.

### 1. Backend (port 8000)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS and Linux
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill it in:

```
TINYFISH_API_KEY=
DATABASE_URL=postgresql://darkroom:darkroom@localhost:5432/darkroom
TINYFISH_PROFILE_ID=
```

| Variable | Purpose |
| --- | --- |
| `TINYFISH_API_KEY` | Needed to run live probes. Stored findings are served without it. |
| `DATABASE_URL` | Postgres by default. For SQLite, use `sqlite:///./darkroom.db`. |
| `TINYFISH_PROFILE_ID` | A saved TinyFish browser profile, so login and OTP walls are already passed. Used by logged-in probes. |

Start it:

```bash
uvicorn app.main:app --reload --port 8000
```

The database tables are created on startup. No sample or seed data is ever loaded, so the dashboard starts empty until a probe finishes. Never commit `.env`.

### 2. Frontend (port 3000)

```bash
cd frontend
npm install
```

Create `frontend/.env.local`. It is ignored by Git, so each person makes their own:

```
NEXT_PUBLIC_API=http://localhost:8000
NEXT_PUBLIC_SAMPLE_FALLBACK=0
NEXT_PUBLIC_DEMO_URL=
```

| Variable | Purpose |
| --- | --- |
| `NEXT_PUBLIC_API` | Backend base URL. |
| `NEXT_PUBLIC_SAMPLE_FALLBACK` | Set to `1` to show the sample data in `lib/sample.ts` when the backend is down. A banner says when sample data is showing. |
| `NEXT_PUBLIC_DEMO_URL` | Pre-fills the run bar's entry URL for demos. |

```bash
npm run dev
```

Open http://localhost:3000. Ports are fixed: frontend on 3000, backend on 8000. The backend allows CORS only for `http://localhost:3000` and `http://127.0.0.1:3000`.

## API

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/health` | `{ "ok": true }` |
| GET | `/api/findings` | `{ "findings": Finding[] }`, newest first |
| GET | `/api/findings/{id}` | `{ "finding": Finding, "journey_states": JourneyState[] }`, or 404 |
| POST | `/api/probes` | Body `{platform, entry_url}`, returns `{ run_id, status }`. Optional: `intent`, `session` (`fresh` or `logged_in`), `profile_id`, `budget`. |
| GET | `/api/runs/{id}` | `{ status, progress, ... }`, plus `finding_id` when done. Status is `PENDING`, `RUNNING`, `COMPLETED` or `FAILED`. |
| GET | `/api/presets` | Platforms with tested settings (Flipkart and Meesho) |
| POST | `/api/specs/{id}/replay` | Body `{runs: 3}`. Re-runs a stored probe several times, then re-confirms its findings. |
| GET | `/api/media/{file}` | Run recordings |

Probes for Flipkart and Meesho pick up tested settings automatically (logged-in session and a price ceiling), so the dashboard only needs to send `{platform, entry_url}`. Run status is kept in memory, so it resets when the backend restarts, while findings are stored in the database.

A finding looks like this:

```json
{
  "finding_id": "f_1184",
  "platform": "Platform A",
  "pattern": "drip_pricing",
  "severity": "high",
  "measure": { "delta_inr": 127.0, "delta_pct": 25.45, "from": 499.0, "to": 626.0 },
  "clause": "CCPA Guidelines for Prevention and Regulation of Dark Patterns, 2023 — drip pricing",
  "evidence": {
    "observation_ids": ["obs_7f3a"],
    "video_ref": null,
    "reproduced_in": "5 of 6 observations"
  },
  "status": "confirmed",
  "detected_at": "2026-10-24T09:31:02Z"
}
```

The shape of `measure` depends on the pattern:

- `drip_pricing`: `delta_inr`, `delta_pct`, `from`, `to`
- `basket_sneaking`: `items`, `amount_inr`, `count`
- `false_urgency`: either `claim` and `unchanged_for_hours`, or `timer_then`, `timer_now` and `hours_apart`
- `cancel_friction`: `subscribe_steps`, `cancel_steps`, `ratio`

## Maintenance scripts

Run these from `backend/`. Only `fetch_run` contacts TinyFish.

```bash
python -m app.confirm <probe_spec_id>                            # re-confirm findings from stored observations
python -m app.remap samples/runs/<run>.json <obs_id> <platform>  # re-score a saved run after fixing a rule
python -m app.fetch_run <tinyfish_run_id> <obs_id> <platform>    # fetch a run that finished after the backend stopped waiting
```

## Notes for contributors

- Every network call in the frontend goes through `frontend/lib/api.ts`, and every `fetch` uses `cache: "no-store"`. Without it, Next.js can cache the first response and show an empty list.
- Do not edit `backend/` in a frontend commit, or the other way round.
- Pull before you push: `git pull --rebase origin main`, then `git push`.
- Commit messages follow `feat(frontend): ...`, `fix(backend): ...` and so on.
- The files in `backend/samples/` and `backend/tests/fixtures/` are illustrative examples (Platform A, B and C). They are not results of real runs, and the API never reads them.
- `backend/.env`, `*.db`, `backend/evidence/` and `backend/samples/runs/` are ignored by Git.

## Team

Team CryptiX, HackIIITD Esya '26.

<!-- add member names and GitHub handles here -->
