"""
web/scheduler_service.py — APScheduler (BackgroundScheduler)
"""
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date as date_cls
from web.db import get_setting, create_job
from web import job_runner

_scheduler = BackgroundScheduler()


def _daily_job():
    today = date_cls.today().isoformat()
    platforms = get_setting("platforms", "youtube,instagram").split(",")
    dry_run   = get_setting("dry_run", "false") == "true"
    job_id    = create_job(date=today, triggered_by="schedule",
                           platforms=",".join(platforms))
    job_runner.trigger_job(job_id=job_id, date=today,
                           platforms=platforms, dry_run=dry_run)


def start(hour: int = 8, minute: int = 0):
    _scheduler.add_job(_daily_job, "cron", hour=hour, minute=minute,
                       id="daily_pipeline", replace_existing=True)
    if not _scheduler.running:
        _scheduler.start()


def update_schedule(hour: int, minute: int):
    if _scheduler.running:
        _scheduler.reschedule_job("daily_pipeline", trigger="cron",
                                  hour=hour, minute=minute)


def shutdown():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
