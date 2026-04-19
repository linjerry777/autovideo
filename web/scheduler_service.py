"""
web/scheduler_service.py — APScheduler (BackgroundScheduler)

Daily autopilot (opt-in via `autopilot_enabled` setting):
  fires at (schedule_hour, schedule_minute), runs two back-to-back jobs:
    1. News autopilot (strategy=generic)
    2. Trending autopilot (strategy=entertainment, single YT TW top trend)

Both go through job_runner.trigger_job(autopilot=True). The queue inside
trigger_job sequences them so only one runs at a time.

Safety: `autopilot_dry_run` defaults to true — publisher prints preview only.
Flip to false once you trust the pipeline.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date as date_cls

from web.db import get_setting, create_job
from web import job_runner

log = logging.getLogger("scheduler_service")

_scheduler = BackgroundScheduler()

# Defaults applied when autopilot settings are missing. Keep aligned with the
# settings row documented in web/db.py.
_DEFAULT_PLATFORMS = "youtube,instagram,facebook,threads,x,tiktok"


def _bool_setting(key: str, default: bool) -> bool:
    return str(get_setting(key, str(default).lower())).lower() == "true"


def _fire_news_autopilot(today: str, platforms: list[str], dry_run: bool) -> None:
    strategy = get_setting("autopilot_news_strategy", "generic") or "generic"
    profile  = get_setting("autopilot_news_profile",  "pet")     or "pet"
    job_id   = create_job(date=today, triggered_by="autopilot_news",
                          platforms=",".join(platforms))
    log.info("[autopilot] news job %s strategy=%s profile=%s dry_run=%s",
             job_id, strategy, profile, dry_run)
    job_runner.trigger_job(
        job_id=job_id, date=today, topic=None,
        platforms=platforms, dry_run=dry_run,
        pre_news=None,                # scheduled path → news_collector.py
        account_profile=profile,
        strategy=strategy,
        autopilot=True,
    )


def _pick_trending_items(n: int = 3) -> list[dict]:
    """Return top N raw YT TW trends (enrich_news_items-compatible shape),
    skipping URLs already made into videos. 3 items gives us a ~60-80s long
    version that qualifies for TikTok Creator Rewards (>60s threshold)."""
    try:
        from web.routes.news import _fetch_all, _load_used_urls
    except Exception as e:
        log.warning("[autopilot] trending fetch import failed: %s", e)
        return []
    raw = _fetch_all(keyword="", lang="zh-TW", selected_sources=["youtube_tw"])
    if not raw:
        return []
    used = _load_used_urls()
    fresh = [it for it in raw if it.get("url") not in used][:n]
    return [{
        "title":       it.get("title", ""),
        "summary":     it.get("summary", "") or it.get("title", ""),
        "url":         it.get("url", ""),
        "source":      it.get("source", "YouTube TW"),
        "source_type": it.get("source_type", "youtube"),
    } for it in fresh]


def _fire_trending_autopilot(today: str, platforms: list[str], dry_run: bool) -> None:
    items = _pick_trending_items(n=3)
    if not items:
        log.info("[autopilot] all YT TW trends already made — skipping trending job")
        return
    strategy = get_setting("autopilot_trending_strategy", "entertainment") or "entertainment"
    profile  = get_setting("autopilot_trending_profile",  "pet")           or "pet"
    job_id   = create_job(date=today, triggered_by="autopilot_trending",
                          platforms=",".join(platforms))
    log.info("[autopilot] trending job %s items=%d top=%s strategy=%s profile=%s dry_run=%s",
             job_id, len(items), items[0]["title"][:50], strategy, profile, dry_run)
    job_runner.trigger_job(
        job_id=job_id, date=today, topic=None,
        platforms=platforms, dry_run=dry_run,
        pre_news=items,               # 3 raw items → compilation video
        account_profile=profile,
        strategy=strategy,
        autopilot=True,
    )


def _daily_job() -> None:
    """Called once per day by APScheduler at (schedule_hour, schedule_minute)."""
    if not _bool_setting("autopilot_enabled", False):
        # Legacy manual-review pipeline (what used to run unconditionally).
        _legacy_daily()
        return

    today     = date_cls.today().isoformat()
    platforms = (get_setting("autopilot_platforms", _DEFAULT_PLATFORMS)
                 or _DEFAULT_PLATFORMS).split(",")
    platforms = [p.strip() for p in platforms if p.strip()]
    dry_run   = _bool_setting("autopilot_dry_run", True)

    if _bool_setting("autopilot_news_enabled", True):
        _fire_news_autopilot(today, platforms, dry_run)
    if _bool_setting("autopilot_trending_enabled", True):
        _fire_trending_autopilot(today, platforms, dry_run)


def _legacy_daily() -> None:
    """Pre-autopilot behavior: create 1 job and let user click through UI."""
    today     = date_cls.today().isoformat()
    platforms = get_setting("platforms", "youtube,instagram").split(",")
    dry_run   = get_setting("dry_run", "false") == "true"
    job_id    = create_job(date=today, triggered_by="schedule",
                           platforms=",".join(platforms))
    job_runner.trigger_job(job_id=job_id, date=today,
                           platforms=platforms, dry_run=dry_run)


def start(hour: int = 8, minute: int = 0) -> None:
    _scheduler.add_job(_daily_job, "cron", hour=hour, minute=minute,
                       id="daily_pipeline", replace_existing=True)
    if not _scheduler.running:
        _scheduler.start()


def update_schedule(hour: int, minute: int) -> None:
    if _scheduler.running:
        _scheduler.reschedule_job("daily_pipeline", trigger="cron",
                                  hour=hour, minute=minute)


def run_now() -> None:
    """Manual trigger — used by UI 'run autopilot now' button / API probe."""
    _daily_job()


def shutdown() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
