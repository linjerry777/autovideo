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

# Per-strategy voice IDs (optional — fall back to FISH_AUDIO_VOICE_ID)
FISH_AUDIO_VOICE_TECH=          # tech strategy 用沉穩男聲
FISH_AUDIO_VOICE_ENTERTAINMENT= # entertainment 用活潑女聲
FISH_AUDIO_VOICE_FINANCE=       # finance 用專業男聲
FISH_AUDIO_VOICE_PET=           # pet 用可愛女聲
```

---

## Doro mascot LoRA (2026-05-06+, optional)

跨專案 4 個 doro LoRA 已訓好，可換 mascot 用 doro 變體（古風/水墨/翡翠）取代當前 `assets/brand/mascot.png`。

- 登錄表 + prompt 模板：**`C:\Users\User\Documents\GitHub\DORO_LORA_REGISTRY.md`** ← 必讀
- 預生成透明 PNG：`C:\Users\User\Documents\GitHub\open-carrusel\public\uploads\doro-lora\demo-{gufeng,feicui,shumo}-cut.png`
- 注意：訓 LoRA / ComfyUI 推理會搶 GPU，pipeline 跑時要避開（kohya 訓練排程在凌晨）

預設仍用既有 `mascot.png`，要切換 mascot path 在 env 改。

---

## Upload-Post Feature Coverage

We use Upload-Post's per-platform API extensively. Coverage per platform:

**YouTube** — `youtube_title`, `youtube_description`, `tags[]`, `categoryId`, `defaultLanguage`, `defaultAudioLanguage`, `privacyStatus`, `containsSyntheticMedia`, `selfDeclaredMadeForKids`, `embeddable`, `publicStatsViewable`, `license`, `thumbnail` (auto from `pipeline/.../thumbnail.png`)

**TikTok** — `tiktok_title`, `privacy_level`, `is_aigc` (2026 compliance), `cover_timestamp`, `disable_duet/comment/stitch`, `brand_content_toggle`, `brand_organic_toggle`

**Instagram Reels** — `instagram_title`, `first_comment` (hashtag spam), `collaborators`, `user_tags`, `media_type=REELS`

**Facebook Reels** — `facebook_title`, `facebook_description`, `facebook_media_type`, `video_state` (PUBLISHED/DRAFT)

**Threads** — `threads_title`, `threads_topic_tag`

**X (Twitter)** — `x_title`, `poll_options`, `poll_duration`, `reply_settings`, `x_long_text_as_post`

**Pinterest** — `pinterest_title`, `pinterest_description`, `pinterest_board_id` (REQUIRED), `pinterest_link`, `pinterest_alt_text`

**Reddit** — `reddit_title`, `subreddit` (REQUIRED), `flair_id`

**Scheduling** — `scheduled_date` + `timezone` (pass-through to Upload-Post's queue; no local scheduler)

---

## Audio Assets (Step 3 — 3-layer audio)

`audio_generator.py` mixes 3 layers when assets exist; gracefully falls back to voice-only when they don't.

```
assets/
├─ music/<emotion>/*.mp3   ← BGM, picked by news.json items[i].emotion
│   (surprise / fear / joy / curiosity / anger / generic)
└─ sfx/hook/*.mp3          ← Hook SFX prepended to first sentence (~0.4s)
```

- BGM is sidechain-ducked under voice (-18dB resting, dips to ~-30dB when voice plays)
- Hook SFX adds ~0.9s to total audio length; `timing.json` offsets shift accordingly
- See `assets/README.md` for recommended sources (YouTube Audio Library, Pixabay)

Per-strategy voice mapping via env: `FISH_AUDIO_VOICE_{TECH,ENTERTAINMENT,FINANCE,PET}`. Each can be set to a different Fish Audio reference_id; missing keys fall back to `FISH_AUDIO_VOICE_ID`.

Per-platform customization lives in `pipeline/{date}/job_{id}/platform_meta.json`. UI edits via Alpine modal at `page='upload'`. Compliance defaults (`is_aigc=true`, `containsSyntheticMedia=true`) are seeded — users can uncheck for non-AI content.

---

## Development Notes

- **Async/Sync mix**: FastAPI is async; pipeline steps run in a background thread (sync). Do not `await` inside pipeline scripts.
- **Each script is standalone**: `scripts/*.py` accept a date string argument and read/write from `pipeline/YYYY-MM-DD/`. They can be run independently for debugging.
- **`dry_run=true`**: Skips publishing step; useful for testing the full pipeline.
- **`BACKGROUND_MODE`**: Controls how news article background is rendered — `screenshot` (Playwright screenshot), `blur` (blurred image), or `playwright_stealth` (stealth scraper via Node.js bridge).
- **Frontend**: `frontend/` is a Next.js App Router project. Before writing Next.js code, read `frontend/node_modules/next/dist/docs/` as noted in `frontend/AGENTS.md` — this version may have breaking changes.
- **ffmpeg required**: Must be installed separately. `winget install Gyan.FFmpeg` on Windows.
