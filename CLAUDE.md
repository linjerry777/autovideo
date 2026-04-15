# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AutoVideo is a fully automated AI-powered short video generation and multi-platform publishing system. It converts news/topics into 9:16 portrait short videos (TikTok, YouTube Shorts, Instagram Reels) with no manual intervention.

**Note:** `README.md` and `AutoVideo Pipeline.md` describe an older architecture. The actual codebase uses `web/` + `scripts/` structure documented here.

---

## Running the System

### Quick Start (Windows)
```batch
start.bat
# Starts: Claude API Proxy (:3456), Backend API (:8000)
# UI served at: http://localhost:8000/ui
```

### Manual Start
```bash
# Backend only
python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 8000

# Frontend (Next.js, separate port)
cd frontend && npm run dev   # http://localhost:3000
```

### Database Init (first time)
```bash
python -c "from web.db import init_db; init_db()"
```

### Run a Single Pipeline Step Manually
```bash
python scripts/news_collector.py 2026-04-13
python scripts/screenshot_collector.py 2026-04-13
python scripts/audio_generator.py 2026-04-13
python scripts/video_composer.py 2026-04-13
python scripts/publisher.py 2026-04-13
```

### Course Video Pipeline
```bash
python generate_course_videos.py            # All 7 chapters
python generate_course_videos.py 01 03 07   # Specific chapters
```

### Trigger via API
```bash
curl -X POST http://localhost:8000/api/jobs/trigger \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-04-13", "platforms":["youtube"], "dry_run":true}'

curl http://localhost:8000/api/events/1   # SSE progress stream
```

---

## Architecture

### Directory Structure
```
AutoVideo/
├── web/                      # FastAPI backend
│   ├── app.py                # FastAPI factory + lifespan
│   ├── db.py                 # SQLite CRUD (data/dashboard.db)
│   ├── job_runner.py         # Background thread executor + SSE broadcasts
│   ├── scheduler_service.py  # APScheduler daily cron trigger
│   ├── claude_client.py      # Claude API integration
│   └── routes/               # jobs, news, media, settings, events, accounts
├── scripts/                  # Pipeline modules (called by job_runner)
│   ├── news_collector.py     # Google News + RSS scraping
│   ├── screenshot_collector.py  # Playwright webpage screenshots
│   ├── audio_generator.py    # Fish Audio TTS → sentence-level MP3s
│   ├── broll_fetcher.py      # Pexels B-roll video download
│   ├── video_composer.py     # FFmpeg main mixer (1080×1920)
│   └── publisher.py          # Upload-Post multi-platform publish
├── frontend/                 # Next.js 16 + TypeScript + Tailwind dashboard
├── pipeline/                 # Job output: pipeline/YYYY-MM-DD/{news.json,screenshots/,audio/,output.mp4}
├── data/dashboard.db         # SQLite database
├── generate_course_videos.py # CLI for 7-chapter course video series
└── start.bat                 # Windows launcher
```

### Pipeline Flow
```
APScheduler (daily) or POST /api/jobs/trigger
    → job_runner.trigger_job() → Background Thread
        1. news_collector.py    → pipeline/DATE/news.json
        2. screenshot_collector.py → pipeline/DATE/screenshots/*.png  (Playwright)
        3. audio_generator.py   → pipeline/DATE/audio/*.mp3  (Fish Audio TTS)
        4. video_composer.py    → pipeline/DATE/output.mp4   (FFmpeg, 1080×1920)
        5. publisher.py         → TikTok / YouTube Shorts / Instagram Reels
        6. db.update_job()      → status='done'
    → SSE events broadcast to GET /api/events/{job_id}
```

### Video Layout (1080×1920)
- Top: Gold hook text
- Center: Blurred background + article screenshot
- Bottom: White subtitles
- Font: Microsoft JhengHei (CJK)

### Database (SQLite: `data/dashboard.db`)
Three tables:
- **`jobs`**: `{id, date, status, triggered_by, platforms, step_news/screenshot/audio/video/upload, output_path, error, started_at, finished_at}`
- **`settings`**: key-value store for `schedule_hour`, `schedule_minute`, `platforms`, `dry_run`, `background_mode`
- **`news_cache`**: `{id, topic, lang, fetch_date, title, summary, url, source, screenshot_blocked}`

### SSE Events
`job_runner._broadcast(job_id, **kwargs)` sends real-time step progress. Frontend subscribes via `GET /api/events/{job_id}`.

---

## Key Environment Variables

```env
OPENAI_API_KEY=          # GPT-4o (script generation)
ANTHROPIC_API_KEY=       # Claude API
GROQ_API_KEY=            # Groq (news summarization)
FISH_AUDIO_API_KEY=      # TTS
FISH_AUDIO_VOICE_ID=     # e.g., Laura
PEXELS_API_KEY=          # B-roll (optional)
UPLOAD_POST_KEY=         # Multi-platform publish
DB_PATH=./data/dashboard.db
PIPELINE_DIR=./pipeline
SCHEDULE_HOUR=8
DRY_RUN=false
SKIP_UPLOAD=false
BACKGROUND_MODE=screenshot   # 'screenshot' | 'blur' | 'playwright_stealth'
```

---

## Development Notes

- **Async/Sync mix**: FastAPI is async; pipeline steps run in a background thread (sync). Do not `await` inside pipeline scripts.
- **Each script is standalone**: `scripts/*.py` accept a date string argument and read/write from `pipeline/YYYY-MM-DD/`. They can be run independently for debugging.
- **`dry_run=true`**: Skips publishing step; useful for testing the full pipeline.
- **`BACKGROUND_MODE`**: Controls how news article background is rendered — `screenshot` (Playwright screenshot), `blur` (blurred image), or `playwright_stealth` (stealth scraper via Node.js bridge).
- **Frontend**: `frontend/` is a Next.js App Router project. Before writing Next.js code, read `frontend/node_modules/next/dist/docs/` as noted in `frontend/AGENTS.md` — this version may have breaking changes.
- **ffmpeg required**: Must be installed separately. `winget install Gyan.FFmpeg` on Windows.
