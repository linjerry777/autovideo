"""web/routes/analytics.py — per-video stats for the analytics UI page."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException

from web.db import get_conn, list_video_stats, get_job_stats

router = APIRouter(prefix="/api/analytics")
BASE_DIR = Path(__file__).parent.parent.parent


@router.get("/overview")
def overview(limit: int = 50):
    """Recent videos grouped by job, aggregated across platforms.

    Returns: [{job_id, date, topic, status, finished_at, platforms: [...]}, ...]
    """
    with get_conn() as conn:
        jobs = conn.execute(
            """
            SELECT id AS job_id, date, topic, status, finished_at
            FROM jobs
            WHERE status='done'
            ORDER BY finished_at DESC
            LIMIT ?
            """, (limit,)
        ).fetchall()
    result = []
    total_views_all = 0
    for j in jobs:
        stats = get_job_stats(j["job_id"])
        total_views = sum(s.get("views", 0) for s in stats)
        total_likes = sum(s.get("likes", 0) for s in stats)
        total_comments = sum(s.get("comments", 0) for s in stats)
        total_views_all += total_views
        result.append({
            "job_id":        j["job_id"],
            "date":          j["date"],
            "topic":         j["topic"],
            "status":        j["status"],
            "finished_at":   j["finished_at"],
            "total_views":   total_views,
            "total_likes":   total_likes,
            "total_comments": total_comments,
            "platforms":     stats,
        })
    return {"jobs": result, "summary": {"total_videos": len(result), "total_views": total_views_all}}


@router.get("/jobs/{job_id}")
def job_stats(job_id: int):
    stats = get_job_stats(job_id)
    if not stats:
        return {"job_id": job_id, "platforms": []}
    return {"job_id": job_id, "platforms": stats}


@router.post("/refresh")
def refresh_analytics(limit: int = 30, job_id: int | None = None):
    """Trigger analytics_fetcher.py in background."""
    script = BASE_DIR / "scripts" / "analytics_fetcher.py"
    args = [sys.executable, "-X", "utf8", str(script)]
    if job_id:
        args += ["--job", str(job_id)]
    else:
        args += ["--limit", str(limit)]
    # Fire-and-forget; caller polls /overview later
    subprocess.Popen(args, cwd=str(BASE_DIR),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "message": "analytics refresh 觸發中（背景執行，稍候重新整理）"}
