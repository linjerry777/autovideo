"""
web/app.py — FastAPI application factory
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    yield
    # 關閉
    scheduler_service.shutdown()


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
