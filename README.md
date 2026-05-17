# AutoVideo

AutoVideo is a local AI short-video autopilot for collecting topics, generating
scripts and narration, rendering 9:16 videos, and publishing to social platforms
through Upload-Post.

## Current App

The current UI is the FastAPI static dashboard:

```text
http://localhost:9000/ui
```

The old Next.js/Vercel `frontend/` dashboard is no longer used in this repo.

## Start

```batch
start.bat
```

Codex Pro / CliRelay route:

```batch
start-codex-pro.bat
```

Manual backend:

```bash
python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 9000
```

Initialize the local database:

```bash
python -c "from web.db import init_db; init_db()"
```

## Layout

```text
web/       FastAPI backend, API routes, scheduler, static UI
scripts/   standalone pipeline steps
remotion/  optional Remotion renderer
assets/    brand assets plus local music/SFX placeholders
data/      local SQLite DB, ignored
pipeline/  generated job outputs, ignored
tests/     Python tests
```

## Autopilot Lanes

- News
- Entertainment/trending
- Tech figure source-video analysis

Generated videos, DB files, logs, and local scratch folders are ignored by git.
See `AGENTS.md` for detailed development notes.
