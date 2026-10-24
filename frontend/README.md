# DARKROOM frontend

Runs on http://localhost:3000 and talks to the backend on http://127.0.0.1:8000.

## Put it in the repo (replaces the old frontend)
1. In your clone of the repo, delete everything inside `frontend/` (old files such as `app/page.tsx` would clash with these).
2. Unzip this archive in the repo root, so you get `frontend/` next to `backend/`.
3. Nothing outside `frontend/` is touched.

## Run
    cd frontend
    npm install
    npm run dev          # http://localhost:3000

Start the backend on port 8000 as usual. The browser only talks to :3000; Next.js forwards every `/api/*`
and `/media/*` request to :8000 (see `next.config.mjs`), so there is no CORS to configure and nothing to
change after the push. Different backend address? Create `frontend/.env.local` with
`NEXT_PUBLIC_API=http://HOST:PORT` and restart.

## Pages (menu = the three-line button, top left)
- **Home**: probe desk (run bar), headline numbers, and every finding (newest first, filter by pattern and status). Click one for the finding detail.
- **What's on**: live Indian news on hidden charges and dark patterns, charts and the headline-to-probe flow, refreshed every 5 minutes.
- **Platforms**: one row per platform with its findings and a link to its latest finding.
- **Method**: how the numbers are worked out and the rules we keep.
- **Finding detail**: price ladder, rupee delta, legal clause, evidence checklist, recording.
The separate Findings page and the nested measurements dashboard were removed; Home already lists the findings.

## Connection check
The pill at the top right shows the backend state. Click it (or "Check connection") to re-test at once; the page also reconnects on its own and shows a toast when live data arrives.
If the backend is down, Home offers **Preview with sample data**: fictional platforms, clearly tagged "Sample", and a probe that replays a recorded sample run into the price-ladder screen. It switches to live data by itself when the backend comes up. Nothing is written to the backend.

## Live news (no backend involved)
`app/live-news/route.js` asks Google News India (en-IN) for dark patterns, hidden fees, CCPA actions and
consumer-pricing stories, keeps Indian publishers only (domains ending `.in` plus a list of Indian `.com`
outlets in `lib/news.js`), removes duplicates and returns JSON. The machine running the frontend needs internet.
If the feed fails, the page says so and everything else keeps working.

## Backend contract used (unchanged)
GET /api/health, GET /api/findings, GET /api/findings/{id}, POST /api/probes, GET /api/runs/{id}

## Real data only
There is no built-in data. An empty backend shows "No findings yet"; an unreachable backend shows a message.
If the news feed is unreachable, four saved headlines (dated 24 Oct 2026) are shown under a visible notice.
Optional: with the backend up, `npm run snapshot` saves its real findings to `public/data/snapshot.json`, which the
page shows under a visible "not connected" banner if the backend later goes down. No snapshot file means no data shown.
