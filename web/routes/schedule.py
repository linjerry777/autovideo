"""
web/routes/schedule.py — 📅 排程預覽 API

Aggregates each job's schedule_log.json (written by publisher.py) + predicts
pending slots for jobs that are still being built. Returns a flat list the
static UI groups into a 7-day calendar view.
"""
from datetime import datetime, timedelta
from pathlib import Path
import json

from fastapi import APIRouter, Query

from web.db import list_jobs
from web.golden_hours import next_golden_slot, GOLDEN_HOUR_FIRST

router = APIRouter(prefix="/api")

BASE_DIR = Path(__file__).resolve().parent.parent.parent


_STRATEGY_LABEL = {
    "tech":          "科技",
    "tech_tutorial": "科技教學",
    "quote_analysis": "語錄解析",
    "figure_tech": "科技大咖",
    "figure_entertainment": "娛樂咖",
    "entertainment": "娛樂",
    "finance":       "財經",
    "pet":           "寵物",
    "generic":       "新聞",
}


def _load_job_meta(job_id: int, date: str) -> dict:
    """Pull strategy + first title + account from pipeline/<date>/job_<id>/news.json."""
    pipe_dir  = BASE_DIR / "pipeline" / date / f"job_{job_id}"
    news_file = pipe_dir / "news.json"
    out = {
        "strategy":       "",
        "first_title":    "",
        "account_profile": "",
        "thumbnail":      "",
        "pipe_dir":       pipe_dir,
    }
    if news_file.exists():
        try:
            data = json.loads(news_file.read_text(encoding="utf-8"))
            out["strategy"]        = (data.get("strategy") or "").lower()
            out["account_profile"] = data.get("account_profile") or ""
            items = data.get("items") or []
            if items:
                out["first_title"] = items[0].get("title") or items[0].get("hook") or ""
        except Exception:
            pass
    thumb = pipe_dir / "thumbnail.png"
    if thumb.exists():
        out["thumbnail"] = f"/pipeline_asset/{date}/job_{job_id}/thumbnail.png"
    return out


@router.get("/schedule/upcoming")
def schedule_upcoming(days: int = Query(7, ge=1, le=30)):
    """Return all scheduled / published posts in the next `days` days.

    Sources:
      - `schedule_log.json` written by publisher.py (authoritative; contains
        scheduled_date + status + request_id after a publish attempt)
      - For pending/failed jobs, we predict using next_golden_slot so the
        timeline is never empty while autopilot is still rendering
    """
    now     = datetime.now()
    horizon = now + timedelta(days=days)
    entries: list[dict] = []

    # Scan recent jobs (past 7 days + future-ish) so the 7-day calendar sees
    # newly-queued autopilot jobs as well as published ones.
    jobs = list_jobs(limit=200)

    for job in jobs:
        jid  = job["id"]
        date = job["date"]
        meta = _load_job_meta(jid, date)
        log_file = meta["pipe_dir"] / "schedule_log.json"

        # Already-published case — read the source of truth
        if log_file.exists():
            try:
                log = json.loads(log_file.read_text(encoding="utf-8"))
            except Exception:
                log = []
            for ent in log:
                # Skip cancelled — user explicitly killed these on Upload-Post
                if ent.get("status") == "cancelled":
                    continue
                when = ent.get("scheduled_date") or ""
                if not when:
                    continue
                try:
                    when_dt = datetime.fromisoformat(when)
                except Exception:
                    continue
                if when_dt < now - timedelta(days=2) or when_dt > horizon:
                    continue
                entries.append({
                    "when":           when,
                    "platform":       ent.get("platform", ""),
                    "account":        ent.get("profile", "") or meta["account_profile"],
                    "job_id":         jid,
                    "job_date":       date,
                    "title":          meta["first_title"],
                    "strategy":       meta["strategy"],
                    "strategy_label": _STRATEGY_LABEL.get(meta["strategy"], ""),
                    "thumbnail":      meta["thumbnail"],
                    "video_version":  ent.get("video_version", "legacy"),
                    "status":         ent.get("status", "pending"),
                    "request_id":     ent.get("request_id", ""),
                })
            continue

        # Pending / unpublished: only predict for jobs that are actually
        # in-flight. Legacy done jobs without a schedule log shouldn't pollute
        # the upcoming view.
        step_upload = job.get("step_upload") or ""
        if job.get("status") in ("failed", "cancelled", "done"):
            continue
        if step_upload in ("done", "dry_run", "failed"):
            continue
        if step_upload not in ("pending", "uploading", "review"):
            continue

        platforms = (job.get("platforms") or "").split(",")
        for p in platforms:
            p = p.strip()
            if not p or p not in GOLDEN_HOUR_FIRST:
                continue
            when = next_golden_slot(p, tz="Asia/Taipei")
            if not when:
                continue
            try:
                when_dt = datetime.fromisoformat(when)
            except Exception:
                continue
            if when_dt > horizon:
                continue
            entries.append({
                "when":           when,
                "platform":       p,
                "account":        meta["account_profile"],
                "job_id":         jid,
                "job_date":       date,
                "title":          meta["first_title"] or (job.get("topic") or ""),
                "strategy":       meta["strategy"],
                "strategy_label": _STRATEGY_LABEL.get(meta["strategy"], ""),
                "thumbnail":      meta["thumbnail"],
                "video_version":  "",
                "status":         "predicted",
                "request_id":     "",
            })

    entries.sort(key=lambda e: e["when"])
    return {"days": days, "entries": entries}
