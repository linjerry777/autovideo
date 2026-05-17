# AGENTS.md

Guidance for Codex and other coding agents working in this repository.

## Project Overview

AutoVideo is a local AI short-video autopilot. It collects news/trends/source
videos, writes scripts, generates narration, renders 9:16 videos, and publishes
through Upload-Post.

The active app is the FastAPI backend plus the static dashboard in `web/static`.
The old Next.js/Vercel `frontend/` dashboard has been removed from this repo and
is not part of the current local flow.

## Running

### Windows

```batch
start.bat
```

This starts:

- Claude proxy on `:3456`
- FastAPI backend on `:9000`
- UI at `http://localhost:9000/ui`

Codex Pro / CliRelay route:

```batch
start-codex-pro.bat
```

### Manual Backend

```bash
python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 9000
```

### Database Init

```bash
python -c "from web.db import init_db; init_db()"
```

## Active Architecture

```text
AutoVideo/
├─ web/                    FastAPI backend + static UI
│  ├─ app.py               app setup, routers, scheduler startup
│  ├─ db.py                SQLite schema and CRUD helpers
│  ├─ job_runner.py        queued background pipeline executor
│  ├─ scheduler_service.py APScheduler autopilot jobs
│  ├─ claude_client.py     LLM/CliRelay/OpenAI integration
│  ├─ routes/              API routers
│  └─ static/index.html    active dashboard
├─ scripts/                standalone pipeline steps
├─ remotion/               optional Remotion renderer
├─ assets/                 brand assets, music and SFX placeholders
├─ data/                   local SQLite DB, ignored
├─ pipeline/               generated job outputs, ignored
└─ tests/                  Python tests
```

## Main Pipeline

`job_runner.trigger_job()` runs these steps in a background thread:

1. Collect or receive items (`news_collector.py` or autopilot preloaded items)
2. Capture screenshots / media
3. Generate audio (`audio_generator.py`)
4. Render video (`video_composer.py`, `remotion_renderer.py`, or figure composer)
5. Render thumbnail
6. Publish with `publisher.py` when autopilot upload is enabled
7. Update SQLite and broadcast SSE events

Dual-version jobs write `short/output.mp4` and `long/output.mp4`. Legacy jobs
write `output.mp4` at the job root. Keep both paths compatible.

## Autopilot

Current scheduled lanes:

- News autopilot
- Entertainment/trending autopilot
- Tech figure source-video analysis

Entertainment figure analysis is intentionally not scheduled. Historical
`figure_entertainment` metadata remains for old jobs and manual uploads.

Current schedule settings live in SQLite `settings`:

- `schedule_hour`, `schedule_minute`
- `autopilot_enabled`
- `autopilot_news_enabled`
- `autopilot_trending_enabled`
- `autopilot_figure_enabled`
- `autopilot_trending_offset_hours`
- `autopilot_figure_tech_offset_hours`

Do not re-enable TikTok autopilot casually; it has been intentionally removed
from the default fan-out while the account recovers.

## Important Local State

These are intentionally ignored and should not be committed:

- `.env`
- `data/`
- `pipeline/`
- `logs/`
- `output/`
- `.codex_tmp/`, `.dev_logs/`, `.playwright-mcp/`
- local downloaded music/SFX MP3 files

Do not delete `data/` or `pipeline/` unless the user explicitly asks. They hold
the active dashboard DB and generated videos.

## Useful Commands

```bash
python scripts/news_collector.py 2026-05-18
python scripts/audio_generator.py 2026-05-18/job_123 --version short
python scripts/insight_quote_composer.py 2026-05-18/job_123 --version short
python scripts/publisher.py 2026-05-18/job_123 --platforms youtube instagram --profile yt
python scripts/analytics_fetcher.py --all
python -m py_compile web/app.py web/job_runner.py web/scheduler_service.py
```

## Environment

Common variables:

```env
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GROQ_API_KEY=
FISH_AUDIO_API_KEY=
FISH_AUDIO_VOICE_ID=
UPLOAD_POST_KEY=
PEXELS_API_KEY=
YOUTUBE_API_KEY=
DB_PATH=./data/dashboard.db
PIPELINE_DIR=./pipeline
BACKGROUND_MODE=screenshot
LLM_PROVIDER=codex
LLM_PROXY_URL=http://127.0.0.1:3458
LLM_MODEL=gpt-5.5
```

Optional per-strategy voices:

```env
FISH_AUDIO_VOICE_TECH=
FISH_AUDIO_VOICE_ENTERTAINMENT=
FISH_AUDIO_VOICE_FINANCE=
FISH_AUDIO_VOICE_PET=
```

## Development Notes

- FastAPI is async, but pipeline scripts run synchronously in a background thread.
- Pipeline scripts must remain runnable as standalone CLI tools.
- Prefer small compatibility-preserving changes. Old jobs may still depend on
  legacy `output.mp4`, `script`, and `figure_entertainment` metadata.
- Use `rg` for search.
- Do not restart or steal active ports unless the user asks.
- Do not commit secrets or generated pipeline output.
