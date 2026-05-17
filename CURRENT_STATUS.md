# AutoVideo Current Status

Last updated: 2026-05-18

## Active Shape

- Active UI: `http://localhost:9000/ui`, served by `web/static/index.html`.
- Active backend: FastAPI in `web/`.
- Active pipeline: Python scripts in `scripts/`, orchestrated by `web/job_runner.py`.
- Old `frontend/` Next/Vercel dashboard has been removed from this repo.
- Generated outputs remain local under `pipeline/` and are ignored by git.
- Local SQLite state remains under `data/` and is ignored by git.

## Autopilot

Current automatic lanes:

1. News
2. Entertainment/trending
3. Tech figure source-video analysis

Entertainment figure analysis is intentionally not scheduled. Historical
`figure_entertainment` metadata still exists for older jobs and manual uploads,
but autopilot should only create `figure_tech` jobs.

Current intended schedule:

- News: 18:00
- Entertainment/trending: 19:00
- Tech figure analysis: 20:00

Do not re-enable TikTok autopilot without explicit approval.

## Recent Work

- Analytics UI and backend now focus on per-video performance recovery.
- Upload-Post scheduling and retry behavior were hardened.
- Figure source/segment pool exists for tech figures.
- Figure quote composer has a safer top area for mobile platform chrome.
- Repository cleanup removed generated pipeline output from git tracking and
  removed the stale `frontend` gitlink.

## Current Product Direction

The useful work is improving retention, not adding more broad automation:

- Stronger first-frame hook/cover.
- Better tech figure source selection.
- More reliable per-platform analytics.
- Cleaner scheduling and upload recovery.
- Keep code paths small enough that autopilot behavior is easy to reason about.

## Do Not Do

- Do not delete `data/` or `pipeline/` without explicit user approval.
- Do not restart/steal active ports unless requested.
- Do not publish/repost scheduled videos without confirming when it affects live platforms.
- Do not revive the old Next.js frontend unless the user explicitly asks.
