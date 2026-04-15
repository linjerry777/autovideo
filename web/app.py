"""
web/app.py — FastAPI application factory
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.db import init_db, get_setting
from web import job_runner, scheduler_service
from web.routes import jobs, events, media, settings, news, accounts


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 啟動
    init_db()
    job_runner.set_event_loop(asyncio.get_event_loop())
    hour   = int(get_setting("schedule_hour",   "8"))
    minute = int(get_setting("schedule_minute", "0"))
    scheduler_service.start(hour, minute)

    # Telegram Bot（若已設定 token 則自動啟動）
    tg_token    = get_setting("telegram_bot_token", "")
    tg_chat_ids = {c.strip() for c in get_setting("telegram_chat_ids", "").split(",") if c.strip()}
    if tg_token:
        from web.telegram_bot import start_bot
        start_bot(tg_token, tg_chat_ids)

    yield
    # 關閉
    scheduler_service.shutdown()
    from web.telegram_bot import stop_bot
    stop_bot()


app = FastAPI(title="AutoVideo API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(events.router)
app.include_router(media.router)
app.include_router(settings.router)
app.include_router(news.router)
app.include_router(accounts.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "AutoVideo API"}


# ── Serve local UI at /ui ──────────────────────────────────────────────────────
_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")
