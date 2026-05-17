"""Pull per-video stats for recent published jobs.

The matcher is intentionally conservative. If a platform video cannot be
matched by job title/hook plus publish window, it is skipped instead of falling
back to the latest video. That prevents one viral/recent post from polluting
many jobs with the same metrics.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DIR = BASE_DIR / "pipeline"
sys.path.insert(0, str(BASE_DIR))

from web.db import get_conn, upsert_video_stat  # noqa: E402

YT_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YT_CHANNEL = os.getenv("YOUTUBE_CHANNEL_ID", "")
FB_TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN", "")
FB_PAGE_ID = os.getenv("META_FB_PAGE_ID", "1100141579843223")
UPLOAD_POST_KEY = os.getenv("UPLOAD_POST_KEY", "")
UP_BASE = "https://api.upload-post.com/api"


def _http_json(url: str, timeout: int = 15) -> dict:
    req = Request(url, headers={"User-Agent": "AutoVideo-Analytics/1.1"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _read_json(path: Path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _job_dir(date: str, job_id: int) -> Path:
    return PIPELINE_DIR / (date or "").replace("\\", "/").strip("/") / f"job_{job_id}"


def _first_news_item(job_dir: Path) -> dict:
    data = _read_json(job_dir / "news.json")
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def _platform_meta(job_dir: Path) -> dict:
    data = _read_json(job_dir / "platform_meta.json")
    return data if isinstance(data, dict) else {}


def _schedule_entries(job_dir: Path) -> list[dict]:
    data = _read_json(job_dir / "schedule_log.json")
    return data if isinstance(data, list) else []


def _parse_dt(value: str | None, tz_name: str = "UTC") -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo:
        return dt.astimezone(timezone.utc)
    try:
        local_tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        local_tz = timezone.utc
    return dt.replace(tzinfo=local_tz).astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _context_for_job(job: dict) -> dict:
    job_id = int(job["id"])
    job_dir = _job_dir(job.get("date") or "", job_id)
    news = _first_news_item(job_dir)
    meta = _platform_meta(job_dir)
    schedule = _schedule_entries(job_dir)
    scheduled = {}
    request_ids = {}
    for ent in schedule:
        platform = ent.get("platform")
        if platform:
            scheduled[platform] = _parse_dt(ent.get("scheduled_date"), ent.get("timezone") or "UTC")
            if ent.get("request_id"):
                request_ids[platform] = ent.get("request_id")

    def platform_title(platform: str) -> str:
        section = meta.get(platform) if isinstance(meta.get(platform), dict) else {}
        return section.get("title") or ""

    candidates = [
        job.get("topic"),
        news.get("title"),
        news.get("hook"),
        platform_title("youtube"),
        platform_title("facebook"),
    ]
    clean_candidates = []
    for text in candidates:
        text = str(text or "").strip()
        if text and text not in clean_candidates:
            clean_candidates.append(text)

    facebook_meta = meta.get("facebook") if isinstance(meta.get("facebook"), dict) else {}
    return {
        "job_id": job_id,
        "job_dir": job_dir,
        "finished_at": _parse_dt(job.get("finished_at")),
        "keywords": clean_candidates,
        "scheduled": scheduled,
        "request_ids": request_ids,
        "facebook_page_id": facebook_meta.get("facebook_page_id") or FB_PAGE_ID,
    }


def _claim_platform_video(platform: str, video_id: str, job_id: int) -> int:
    """Make a matched platform video id belong to one job only.

    A real platform video id cannot represent many local jobs. If older loose
    matching polluted the table, remove the other rows once a strict match
    succeeds for the current job.
    """
    if not video_id:
        return 0
    with get_conn() as conn:
        cur = conn.execute(
            """
            DELETE FROM video_stats
            WHERE platform=? AND platform_video_id=? AND job_id != ?
            """,
            (platform, video_id, job_id),
        )
        return cur.rowcount or 0


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[@#]\S+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _match_score(text: str, keywords: list[str]) -> float:
    hay = _norm(text)
    if not hay:
        return 0.0
    scores = []
    for keyword in keywords:
        key = _norm(keyword)
        if not key:
            continue
        short_key = key[:80]
        if short_key and short_key in hay:
            scores.append(1.0)
        if hay and hay[:80] in key:
            scores.append(0.9)
        scores.append(SequenceMatcher(None, short_key, hay[:120]).ratio())
    return max(scores or [0.0])


def _window(ctx: dict, platform: str, before_hours: int, after_hours: int) -> tuple[datetime, datetime]:
    anchor = ctx["scheduled"].get(platform) or ctx.get("finished_at") or datetime.now(timezone.utc)
    return anchor - timedelta(hours=before_hours), anchor + timedelta(hours=after_hours)


def _parse_iso8601_duration(iso: str) -> int:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _upload_post_status(request_id: str) -> dict | None:
    if not (UPLOAD_POST_KEY and request_id):
        return None
    params = {"request_id": request_id}
    req = Request(
        f"{UP_BASE}/uploadposts/status?{urlencode(params)}",
        headers={"Authorization": f"Apikey {UPLOAD_POST_KEY}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  [upload-post.status] {e}", file=sys.stderr)
        return None
    results = data.get("results") if isinstance(data, dict) else None
    if isinstance(results, list) and results:
        return results[0] if isinstance(results[0], dict) else None
    return data if isinstance(data, dict) else None


def _youtube_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(
        r"(?:youtube\.com/(?:watch\?.*?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})",
        url,
    )
    return match.group(1) if match else None


def _facebook_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"facebook\.com/(?:reel|watch)/?/?(?:\?v=)?([0-9]+)", url)
    if match:
        return match.group(1)
    match = re.search(r"/(?:reel|videos)/([0-9]+)", url)
    return match.group(1) if match else None


# YouTube ------------------------------------------------------------------


def _yt_search(query: str, after: datetime, before: datetime) -> list[dict]:
    if not (YT_API_KEY and YT_CHANNEL and query):
        return []
    params = {
        "part": "snippet",
        "channelId": YT_CHANNEL,
        "q": query[:80],
        "type": "video",
        "order": "date",
        "maxResults": 10,
        "publishedAfter": _iso(after),
        "publishedBefore": _iso(before),
        "key": YT_API_KEY,
    }
    try:
        data = _http_json(f"https://www.googleapis.com/youtube/v3/search?{urlencode(params)}")
    except Exception as e:
        print(f"  [yt.search] {e}", file=sys.stderr)
        return []
    out = []
    for item in data.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not video_id:
            continue
        thumbs = snippet.get("thumbnails", {})
        out.append({
            "id": video_id,
            "title": snippet.get("title", ""),
            "publishedAt": snippet.get("publishedAt"),
            "thumbnail_url": (
                thumbs.get("high", {}).get("url")
                or thumbs.get("medium", {}).get("url")
                or thumbs.get("default", {}).get("url")
            ),
        })
    return out


def _yt_stats(video_id: str) -> dict | None:
    params = {"part": "statistics,contentDetails", "id": video_id, "key": YT_API_KEY}
    try:
        data = _http_json(f"https://www.googleapis.com/youtube/v3/videos?{urlencode(params)}")
    except Exception as e:
        print(f"  [yt.stats] {e}", file=sys.stderr)
        return None
    items = data.get("items", [])
    if not items:
        return None
    stats = items[0].get("statistics", {})
    iso = items[0].get("contentDetails", {}).get("duration", "PT0S")
    return {
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
        "duration_seconds": _parse_iso8601_duration(iso),
    }


def fetch_youtube_for_job(job: dict) -> bool:
    if not YT_API_KEY:
        return False
    ctx = _context_for_job(job)
    request_id = ctx["request_ids"].get("youtube")
    if request_id:
        status = _upload_post_status(request_id) or {}
        video_id = status.get("platform_post_id") or _youtube_id_from_url(status.get("post_url"))
        if video_id:
            stats = _yt_stats(video_id) or {}
            removed = _claim_platform_video("youtube", video_id, ctx["job_id"])
            upsert_video_stat(
                ctx["job_id"],
                "youtube",
                platform_video_id=video_id,
                platform_url=status.get("post_url") or f"https://www.youtube.com/watch?v={video_id}",
                title=status.get("post_title") or (ctx["keywords"][0] if ctx["keywords"] else ""),
                thumbnail_url=f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                **stats,
            )
            extra = f", removed {removed} duplicate row(s)" if removed else ""
            print(f"  YT #{ctx['job_id']} {video_id}: {stats.get('views', 0)} views via Upload-Post{extra}")
            return True

    if not YT_CHANNEL:
        print(f"  [yt.skip] #{ctx['job_id']} missing YOUTUBE_CHANNEL_ID and no Upload-Post URL")
        return False
    if not ctx["keywords"]:
        print(f"  [yt.skip] #{ctx['job_id']} has no match keywords")
        return False
    after, before = _window(ctx, "youtube", before_hours=8, after_hours=36)
    candidates: dict[str, dict] = {}
    for keyword in ctx["keywords"][:4]:
        for item in _yt_search(keyword, after, before):
            item["score"] = max(item.get("score", 0), _match_score(item["title"], ctx["keywords"]))
            candidates[item["id"]] = item
    if not candidates:
        return False
    found = max(candidates.values(), key=lambda x: x.get("score", 0))
    if found.get("score", 0) < 0.38:
        print(f"  [yt.skip] #{ctx['job_id']} weak match: {found.get('title')} ({found.get('score'):.2f})")
        return False
    stats = _yt_stats(found["id"]) or {}
    removed = _claim_platform_video("youtube", found["id"], ctx["job_id"])
    upsert_video_stat(
        ctx["job_id"],
        "youtube",
        platform_video_id=found["id"],
        platform_url=f"https://www.youtube.com/watch?v={found['id']}",
        title=found["title"],
        thumbnail_url=found.get("thumbnail_url"),
        **stats,
    )
    extra = f", removed {removed} duplicate row(s)" if removed else ""
    print(f"  YT #{ctx['job_id']} {found['id']}: {stats.get('views', 0)} views{extra}")
    return True


# Facebook -----------------------------------------------------------------


def _fb_page_videos(page_id: str, since_unix: int, until_unix: int) -> list[dict]:
    if not (FB_TOKEN and page_id):
        return []
    params = {
        "fields": "id,title,description,created_time,permalink_url,picture,length,views",
        "limit": 50,
        "since": since_unix,
        "until": until_unix,
        "access_token": FB_TOKEN,
    }
    try:
        data = _http_json(f"https://graph.facebook.com/v25.0/{page_id}/videos?{urlencode(params)}")
    except HTTPError as e:
        print(f"  [fb.videos] HTTP {e.code}: {e.read()[:200]}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  [fb.videos] {e}", file=sys.stderr)
        return []
    return data.get("data", [])


def _fb_video_reactions(video_id: str) -> dict:
    fields = "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)"
    params = {"fields": fields, "access_token": FB_TOKEN}
    try:
        data = _http_json(f"https://graph.facebook.com/v25.0/{video_id}?{urlencode(params)}")
    except Exception:
        return {}
    return {
        "likes": int(data.get("reactions", {}).get("summary", {}).get("total_count", 0)),
        "comments": int(data.get("comments", {}).get("summary", {}).get("total_count", 0)),
    }


def _fb_video_details(video_id: str) -> dict:
    if not (FB_TOKEN and video_id):
        return {}
    fields = "id,title,description,permalink_url,picture,length,views"
    params = {"fields": fields, "access_token": FB_TOKEN}
    try:
        return _http_json(f"https://graph.facebook.com/v25.0/{video_id}?{urlencode(params)}")
    except Exception as e:
        print(f"  [fb.video] {e}", file=sys.stderr)
        return {}


def fetch_facebook_for_job(job: dict) -> bool:
    if not FB_TOKEN:
        return False
    ctx = _context_for_job(job)
    request_id = ctx["request_ids"].get("facebook")
    if request_id:
        status = _upload_post_status(request_id) or {}
        video_id = status.get("platform_post_id") or _facebook_id_from_url(status.get("post_url"))
        if video_id:
            details = _fb_video_details(video_id)
            reactions = _fb_video_reactions(video_id)
            permalink = (
                details.get("permalink_url")
                or status.get("post_url")
                or f"https://www.facebook.com/{video_id}"
            )
            if permalink.startswith("/"):
                permalink = "https://www.facebook.com" + permalink
            removed = _claim_platform_video("facebook", video_id, ctx["job_id"])
            upsert_video_stat(
                ctx["job_id"],
                "facebook",
                platform_video_id=video_id,
                platform_url=permalink,
                title=details.get("title") or status.get("post_title") or (ctx["keywords"][0] if ctx["keywords"] else ""),
                thumbnail_url=details.get("picture"),
                views=int(details.get("views", 0)),
                duration_seconds=int(details.get("length", 0)),
                **reactions,
            )
            extra = f", removed {removed} duplicate row(s)" if removed else ""
            print(f"  FB #{ctx['job_id']} {video_id}: {int(details.get('views', 0))} views via Upload-Post{extra}")
            return True

    if not (ctx["facebook_page_id"] and ctx["keywords"]):
        print(f"  [fb.skip] #{ctx['job_id']} has no page id or keywords")
        return False
    after, before = _window(ctx, "facebook", before_hours=4, after_hours=36)
    videos = _fb_page_videos(ctx["facebook_page_id"], int(after.timestamp()), int(before.timestamp()))
    scored = []
    for video in videos:
        text = f"{video.get('title', '')} {video.get('description', '')}"
        score = _match_score(text, ctx["keywords"])
        if score >= 0.38:
            scored.append((score, video))
    if not scored:
        print(f"  [fb.skip] #{ctx['job_id']} no confident match")
        return False
    score, match = max(scored, key=lambda x: x[0])
    reactions = _fb_video_reactions(match["id"])
    permalink = match.get("permalink_url") or f"https://www.facebook.com/{match['id']}"
    if permalink.startswith("/"):
        permalink = "https://www.facebook.com" + permalink
    removed = _claim_platform_video("facebook", match["id"], ctx["job_id"])
    upsert_video_stat(
        ctx["job_id"],
        "facebook",
        platform_video_id=match["id"],
        platform_url=permalink,
        title=match.get("title") or match.get("description", "")[:80],
        thumbnail_url=match.get("picture"),
        views=int(match.get("views", 0)),
        duration_seconds=int(match.get("length", 0)),
        **reactions,
    )
    extra = f", removed {removed} duplicate row(s)" if removed else ""
    print(f"  FB #{ctx['job_id']} {match['id']}: {match.get('views', 0)} views (score {score:.2f}{extra})")
    return True


def _done_jobs(limit: int | None = 30) -> list[dict]:
    with get_conn() as conn:
        if limit is None:
            rows = conn.execute(
                """
                SELECT id, date, topic, finished_at
                FROM jobs
                WHERE status='done' AND finished_at IS NOT NULL
                ORDER BY finished_at DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, date, topic, finished_at
                FROM jobs
                WHERE status='done' AND finished_at IS NOT NULL
                ORDER BY finished_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def _job_by_id(job_id: int) -> list[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, date, topic, finished_at FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    return [dict(row)] if row else []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--all", dest="all_done", action="store_true", help="Refresh all done jobs")
    parser.add_argument("--job", type=int, help="Single job id")
    parser.add_argument("--platform", choices=["youtube", "facebook", "all"], default="all")
    parser.add_argument("--sleep-every", type=int, default=10)
    parser.add_argument("--sleep-seconds", type=float, default=1.5)
    args = parser.parse_args()

    if args.job:
        jobs = _job_by_id(args.job)
    elif args.all_done:
        jobs = _done_jobs(limit=None)
    else:
        jobs = _done_jobs(args.limit)
    print(f"refreshing analytics for {len(jobs)} job(s)")

    for idx, job in enumerate(jobs, start=1):
        if args.platform in ("youtube", "all"):
            fetch_youtube_for_job(job)
        if args.platform in ("facebook", "all"):
            fetch_facebook_for_job(job)
        if (
            args.sleep_every
            and args.sleep_seconds > 0
            and idx < len(jobs)
            and idx % args.sleep_every == 0
        ):
            time.sleep(args.sleep_seconds)

    print("done")


if __name__ == "__main__":
    main()
