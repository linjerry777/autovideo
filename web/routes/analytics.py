"""Per-video stats for the analytics UI page."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter

from web.db import get_conn, get_job_stats

router = APIRouter(prefix="/api/analytics")
BASE_DIR = Path(__file__).parent.parent.parent
PIPELINE_DIR = BASE_DIR / "pipeline"


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _trim(value, max_len: int = 140) -> str:
    text = str(value or "").strip()
    return text if len(text) <= max_len else text[: max_len - 1] + "..."


def _load_job_news(date: str, job_id: int) -> dict:
    """Best-effort read of the generated news item behind a job."""
    date_part = (date or "").replace("\\", "/").strip("/")
    candidates = [
        PIPELINE_DIR / date_part / f"job_{job_id}" / "news.json",
        PIPELINE_DIR / date_part / "news.json",
    ]
    for path in candidates:
        try:
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                items = data.get("items")
                if isinstance(items, list) and items:
                    return items[0] if isinstance(items[0], dict) else {}
                return data
            if isinstance(data, list) and data and isinstance(data[0], dict):
                return data[0]
        except Exception:
            continue
    return {}


def _job_thumbnail_url(date: str, job_id: int) -> str | None:
    date_part = (date or "").replace("\\", "/").strip("/")
    job_dir = PIPELINE_DIR / date_part / f"job_{job_id}"
    for ext in ("png", "jpg", "jpeg", "webp"):
        if (job_dir / f"thumbnail.{ext}").exists():
            return f"/pipeline_asset/{date_part}/job_{job_id}/thumbnail.{ext}"
    return None


def _normalize_platform_stats(stats: list[dict]) -> list[dict]:
    out = []
    for row in stats:
        item = dict(row)
        url = item.get("platform_url") or ""
        if item.get("platform") == "facebook" and url.startswith("/"):
            item["platform_url"] = f"https://www.facebook.com{url}"
        for key in ("views", "likes", "comments", "shares", "duration_seconds"):
            item[key] = _as_int(item.get(key))
        views = item["views"]
        actions = item["likes"] + item["comments"] + item["shares"]
        item["engagement_rate"] = round((actions / views) * 100, 2) if views else 0
        out.append(item)
    return sorted(out, key=lambda x: (x.get("views") or 0), reverse=True)


def _duplicate_platform_video_ids() -> set[tuple[str, str]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT platform, platform_video_id
            FROM video_stats
            WHERE platform_video_id IS NOT NULL AND platform_video_id != ''
            GROUP BY platform, platform_video_id
            HAVING COUNT(*) > 1
            """
        ).fetchall()
    return {(r["platform"], r["platform_video_id"]) for r in rows}


def _median(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2)


def _performance(total_views: int, baseline_views: int, platforms: list[dict]) -> str:
    if not platforms:
        return "needs_data"
    if baseline_views <= 0:
        return "tracking"
    ratio = total_views / baseline_views
    if ratio >= 1.5:
        return "winner"
    if ratio >= 0.85:
        return "steady"
    if ratio >= 0.45:
        return "watch"
    return "needs_cover"


@router.get("/overview")
def overview(limit: int = 50):
    """Recent videos grouped by job, aggregated across platforms."""
    with get_conn() as conn:
        jobs = conn.execute(
            """
            SELECT id AS job_id, date, topic, status, platforms, step_upload,
                   output_path, finished_at
            FROM jobs
            WHERE status='done'
            ORDER BY finished_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    suspicious_ids = _duplicate_platform_video_ids()
    suspect_stats_count = 0
    rows = []
    for j in jobs:
        raw_stats = _normalize_platform_stats(get_job_stats(j["job_id"]))
        stats = []
        for item in raw_stats:
            key = (item.get("platform"), item.get("platform_video_id"))
            if key in suspicious_ids:
                suspect_stats_count += 1
                continue
            stats.append(item)
        total_views = sum(p["views"] for p in stats)
        total_likes = sum(p["likes"] for p in stats)
        total_comments = sum(p["comments"] for p in stats)
        total_shares = sum(p["shares"] for p in stats)
        actions = total_likes + total_comments + total_shares
        news_item = _load_job_news(j["date"], j["job_id"])
        title = _trim(news_item.get("title") or j["topic"] or "(無主題)", 180)
        hook = _trim(news_item.get("hook") or "", 100)
        best_platform = stats[0]["platform"] if stats and stats[0]["views"] else None
        rows.append({
            "job_id": j["job_id"],
            "date": j["date"],
            "topic": j["topic"],
            "title": title,
            "hook": hook,
            "summary": _trim(news_item.get("summary") or "", 180),
            "status": j["status"],
            "step_upload": j["step_upload"],
            "output_path": j["output_path"],
            "finished_at": j["finished_at"],
            "thumbnail": _job_thumbnail_url(j["date"], j["job_id"]),
            "total_views": total_views,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_shares": total_shares,
            "engagement_rate": round((actions / total_views) * 100, 2) if total_views else 0,
            "best_platform": best_platform,
            "requested_platforms": [
                p.strip() for p in (j["platforms"] or "").split(",") if p.strip()
            ],
            "platforms": stats,
        })

    baseline_views = _median([r["total_views"] for r in rows if r["total_views"] > 0])
    platform_totals: dict[str, int] = {}
    for row in rows:
        row["baseline_views"] = baseline_views
        row["performance"] = _performance(row["total_views"], baseline_views, row["platforms"])
        for p in row["platforms"]:
            platform_totals[p["platform"]] = platform_totals.get(p["platform"], 0) + p["views"]

    total_views_all = sum(r["total_views"] for r in rows)
    total_actions_all = sum(r["total_likes"] + r["total_comments"] + r["total_shares"] for r in rows)
    top_platform = max(platform_totals, key=platform_totals.get) if platform_totals else None
    summary = {
        "total_videos": len(rows),
        "total_views": total_views_all,
        "avg_views": round(total_views_all / len(rows)) if rows else 0,
        "baseline_views": baseline_views,
        "engagement_rate": round((total_actions_all / total_views_all) * 100, 2) if total_views_all else 0,
        "top_platform": top_platform,
        "stats_available": any(r["platforms"] for r in rows),
        "suspect_stats_count": suspect_stats_count,
    }
    return {"jobs": rows, "summary": summary}


@router.get("/jobs/{job_id}")
def job_stats(job_id: int):
    return {"job_id": job_id, "platforms": _normalize_platform_stats(get_job_stats(job_id))}


@router.post("/refresh")
def refresh_analytics(limit: int = 30, job_id: int | None = None, all_done: bool = False):
    """Trigger analytics_fetcher.py in the background."""
    script = BASE_DIR / "scripts" / "analytics_fetcher.py"
    args = [sys.executable, "-X", "utf8", str(script)]
    if job_id:
        args += ["--job", str(job_id)]
    elif all_done:
        args += ["--all"]
    else:
        args += ["--limit", str(limit)]
    subprocess.Popen(
        args,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "message": "analytics refresh started"}
