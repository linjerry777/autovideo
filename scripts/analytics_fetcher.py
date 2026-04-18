"""analytics_fetcher.py — pull per-video stats for recent jobs.

For each recent 'done' job, try to resolve:
  • YouTube video ID via Data API (search channel recent uploads by title+finished_at)
  • Facebook Page video via Graph API (page /videos, match by created_time)

Writes into video_stats table (upsert by job_id+platform).

Usage:
    python scripts/analytics_fetcher.py                # refresh last 30 jobs
    python scripts/analytics_fetcher.py --limit 100
    python scripts/analytics_fetcher.py --job 84       # single job
    python scripts/analytics_fetcher.py --platform youtube

Env vars:
    YOUTUBE_API_KEY          — Data API v3 key (quota: 10k units/day, each call ~3)
    YOUTUBE_CHANNEL_ID       — optional; if empty we take first connected channel
    META_PAGE_ACCESS_TOKEN   — Facebook Page token with pages_read_engagement
    META_FB_PAGE_ID          — FB page ID to query (default set in .env)
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from web.db import get_conn, upsert_video_stat   # noqa: E402

YT_API_KEY   = os.getenv("YOUTUBE_API_KEY", "")
YT_CHANNEL   = os.getenv("YOUTUBE_CHANNEL_ID", "")
FB_TOKEN     = os.getenv("META_PAGE_ACCESS_TOKEN", "")
FB_PAGE_ID   = os.getenv("META_FB_PAGE_ID", "1100141579843223")  # 雙層甜甜圈 default


def _http_json(url: str, timeout: int = 15) -> dict:
    req = Request(url, headers={"User-Agent": "AutoVideo-Analytics/1.0"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ── YouTube ──────────────────────────────────────────────────────────────────

def _yt_resolve_channel_id() -> str | None:
    """If YOUTUBE_CHANNEL_ID not set, fetch our own channel via key (requires forHandle/forUsername)."""
    global YT_CHANNEL
    if YT_CHANNEL:
        return YT_CHANNEL
    # Without explicit channel ID we can't easily discover channel from API key alone.
    # User must set YOUTUBE_CHANNEL_ID in .env for best results.
    return None


def _yt_search_recent(query: str, after_iso: str) -> dict | None:
    """Find the most recent YouTube video on our channel matching the query title.

    Returns {id, title, publishedAt, thumbnail_url} or None.
    """
    channel = _yt_resolve_channel_id()
    if not channel or not YT_API_KEY:
        return None
    params = {
        "part":       "snippet",
        "channelId":  channel,
        "q":          query[:60],
        "type":       "video",
        "order":      "date",
        "maxResults": 5,
        "publishedAfter": after_iso,
        "key":        YT_API_KEY,
    }
    try:
        data = _http_json(f"https://www.googleapis.com/youtube/v3/search?{urlencode(params)}")
    except Exception as e:
        print(f"  [yt.search] {e}", file=sys.stderr)
        return None
    items = data.get("items", [])
    if not items:
        return None
    top = items[0]
    return {
        "id":            top["id"]["videoId"],
        "title":         top["snippet"]["title"],
        "publishedAt":   top["snippet"]["publishedAt"],
        "thumbnail_url": top["snippet"]["thumbnails"].get("high", {}).get("url") or top["snippet"]["thumbnails"]["default"]["url"],
    }


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
    s = items[0]["statistics"]
    # duration is ISO8601 like PT1M3S; convert
    iso = items[0].get("contentDetails", {}).get("duration", "PT0S")
    dur = _parse_iso8601_duration(iso)
    return {
        "views":    int(s.get("viewCount",   0)),
        "likes":    int(s.get("likeCount",   0)),
        "comments": int(s.get("commentCount", 0)),
        "duration_seconds": dur,
    }


def _parse_iso8601_duration(iso: str) -> int:
    """PT1M3S → 63. Minimal parser (seconds only, no days/hours beyond H)."""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def fetch_youtube_for_job(job_id: int, job_topic: str, job_finished_at: str) -> bool:
    if not YT_API_KEY:
        return False
    after = _shift_iso(job_finished_at, minutes=-5)      # search from slightly before finished_at
    query = (job_topic or "")[:60]
    found = _yt_search_recent(query, after)
    if not found:
        return False
    stats = _yt_stats(found["id"]) or {}
    upsert_video_stat(
        job_id, "youtube",
        platform_video_id = found["id"],
        platform_url      = f"https://www.youtube.com/watch?v={found['id']}",
        title             = found["title"],
        thumbnail_url     = found["thumbnail_url"],
        **stats,
    )
    print(f"  ✅ YT #{job_id} {found['id']}: {stats.get('views',0)} views")
    return True


# ── Facebook ─────────────────────────────────────────────────────────────────

def _fb_page_videos(since_unix: int) -> list[dict]:
    if not (FB_TOKEN and FB_PAGE_ID):
        return []
    params = {
        "fields":       "id,title,description,created_time,permalink_url,picture,length,views",
        "limit":        10,
        "since":        since_unix,
        "access_token": FB_TOKEN,
    }
    try:
        data = _http_json(f"https://graph.facebook.com/v25.0/{FB_PAGE_ID}/videos?{urlencode(params)}")
    except HTTPError as e:
        print(f"  [fb.videos] HTTP {e.code}: {e.read()[:200]}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  [fb.videos] {e}", file=sys.stderr)
        return []
    return data.get("data", [])


def _fb_video_reactions(video_id: str) -> dict:
    """Fetch reaction / comment totals via Graph API."""
    fields = "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)"
    params = {"fields": fields, "access_token": FB_TOKEN}
    try:
        data = _http_json(f"https://graph.facebook.com/v25.0/{video_id}?{urlencode(params)}")
    except Exception:
        return {}
    likes    = data.get("reactions", {}).get("summary", {}).get("total_count", 0)
    comments = data.get("comments",  {}).get("summary", {}).get("total_count", 0)
    return {"likes": int(likes), "comments": int(comments)}


def fetch_facebook_for_job(job_id: int, job_topic: str, job_finished_at: str) -> bool:
    if not (FB_TOKEN and FB_PAGE_ID):
        return False
    # FB's "since" takes unix timestamp; widen window to 30min before finished_at
    try:
        dt    = datetime.fromisoformat(job_finished_at.replace("Z", "+00:00"))
        since = int(dt.timestamp()) - 1800
    except Exception:
        return False
    vids = _fb_page_videos(since)
    if not vids:
        return False
    # Match: first video whose title contains the job_topic prefix (loose match)
    topic_prefix = (job_topic or "").strip()[:20]
    match = None
    for v in vids:
        if topic_prefix and topic_prefix in (v.get("title","") + v.get("description","")):
            match = v
            break
    if not match:
        match = vids[0]   # fall back to most-recent-after-job

    reactions = _fb_video_reactions(match["id"])
    upsert_video_stat(
        job_id, "facebook",
        platform_video_id = match["id"],
        platform_url      = match.get("permalink_url") or f"https://www.facebook.com/{match['id']}",
        title             = match.get("title") or match.get("description", "")[:80],
        thumbnail_url     = match.get("picture"),
        views             = int(match.get("views", 0)),
        duration_seconds  = int(match.get("length", 0)),
        **reactions,
    )
    print(f"  ✅ FB #{job_id} {match['id']}: {match.get('views',0)} views")
    return True


# ── utilities ────────────────────────────────────────────────────────────────

def _shift_iso(iso_str: str, minutes: int = 0) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.now(timezone.utc)
    return (dt + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _recent_done_jobs(limit: int = 30) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, topic, finished_at FROM jobs
            WHERE status='done' AND finished_at IS NOT NULL
            ORDER BY finished_at DESC LIMIT ?
            """, (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--job",   type=int, help="Single job id")
    ap.add_argument("--platform", choices=["youtube", "facebook", "all"], default="all")
    args = ap.parse_args()

    if args.job:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, topic, finished_at FROM jobs WHERE id=?", (args.job,)
            ).fetchone()
        jobs = [dict(row)] if row else []
    else:
        jobs = _recent_done_jobs(args.limit)

    print(f"📊 refreshing analytics for {len(jobs)} job(s)…")

    for j in jobs:
        jid, topic, fin = j["id"], j.get("topic") or "", j.get("finished_at") or ""
        if not fin:
            continue
        if args.platform in ("youtube", "all"):
            fetch_youtube_for_job(jid, topic, fin)
        if args.platform in ("facebook", "all"):
            fetch_facebook_for_job(jid, topic, fin)

    print("✅ done")


if __name__ == "__main__":
    main()
