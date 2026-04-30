#!/usr/bin/env python3
"""
sync_doro_palace_videos.py — push recent AutoVideo jobs to doro-palace's
`data/from-video.json` so the /from-ig page can render the video gallery.

Run after publisher.py succeeds (or on demand). Idempotent.

Usage:
    python scripts/sync_doro_palace_videos.py            # sync last 12 done jobs
    python scripts/sync_doro_palace_videos.py --max 20
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from web.db import list_jobs

BASE_DIR = Path(__file__).parent.parent
DEFAULT_DORO_PALACE = BASE_DIR.parent / "doro-palace"
TARGET_REL = "data/from-video.json"


def load_strategy(pipe_dir: Path) -> str:
    news = pipe_dir / "news.json"
    if not news.exists():
        return "generic"
    try:
        d = json.loads(news.read_text(encoding="utf-8"))
        return (d.get("strategy") or "generic").lower()
    except Exception:
        return "generic"


def load_first_title(pipe_dir: Path, fallback: str = "") -> str:
    news = pipe_dir / "news.json"
    if not news.exists():
        return fallback
    try:
        d = json.loads(news.read_text(encoding="utf-8"))
        items = d.get("items") or []
        if items:
            return items[0].get("title") or items[0].get("hook") or fallback
    except Exception:
        pass
    return fallback


def load_summary(pipe_dir: Path) -> str:
    news = pipe_dir / "news.json"
    if not news.exists():
        return ""
    try:
        d = json.loads(news.read_text(encoding="utf-8"))
        items = d.get("items") or []
        if not items:
            return ""
        # Combine first two scripts/summaries truncated.
        parts = []
        for it in items[:2]:
            s = (it.get("script") or it.get("summary") or "").strip()
            if s:
                parts.append(s[:80])
        return " · ".join(parts)
    except Exception:
        return ""


def load_thumbnail_url(pipe_dir: Path) -> str:
    f = pipe_dir / "thumbnail_url.txt"
    if f.exists():
        url = f.read_text(encoding="utf-8").strip()
        if url.startswith("http"):
            return url
    return ""


def load_platform_urls(pipe_dir: Path) -> dict[str, str]:
    """Resolve real post URLs by querying Upload-Post for each request_id in
    schedule_log.json. Falls back to empty dict if status query fails."""
    log_path = pipe_dir / "schedule_log.json"
    if not log_path.exists():
        return {}
    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    urls: dict[str, str] = {}
    try:
        from upload_post import UploadPostClient
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
        api_key = os.getenv("UPLOAD_POST_KEY", "")
        if not api_key:
            return {}
        c = UploadPostClient(api_key)
    except Exception:
        return {}

    for ent in log:
        plat = ent.get("platform")
        rid  = ent.get("request_id")
        if not plat or not rid or ent.get("status") != "uploaded":
            continue
        try:
            r = c.get_status(rid)
            for it in r.get("results", []):
                if it.get("success") and it.get("post_url"):
                    urls[plat] = it["post_url"]
                    break
        except Exception:
            continue
    return urls


def build_items(max_items: int = 12) -> list[dict]:
    jobs = list_jobs(limit=80)
    items = []
    for j in jobs:
        if j.get("status") != "done" or j.get("step_upload") != "done":
            continue
        pipe_dir = BASE_DIR / "pipeline" / j["date"] / f"job_{j['id']}"
        if not pipe_dir.exists():
            continue
        urls = load_platform_urls(pipe_dir)
        if not urls:
            continue   # no live posts → skip entirely
        items.append({
            "key":          f"job_{j['id']}",
            "title":        load_first_title(pipe_dir, fallback=j.get("topic") or ""),
            "publishedAt":  j.get("finished_at") or j.get("started_at") or "",
            "thumbnailUrl": load_thumbnail_url(pipe_dir),
            "strategy":     load_strategy(pipe_dir),
            "summary":      load_summary(pipe_dir),
            "platforms":    urls,
        })
        if len(items) >= max_items:
            break
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=12, help="Max jobs to include")
    parser.add_argument("--target", default=str(DEFAULT_DORO_PALACE / TARGET_REL),
                        help="Output JSON path")
    args = parser.parse_args()

    target = Path(args.target)
    target.parent.mkdir(parents=True, exist_ok=True)

    items = build_items(args.max)
    payload = {
        "_doc": "Auto-synced from AutoVideo by sync_doro_palace_videos.py — do not hand-edit.",
        "items": items,
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ wrote {len(items)} items to {target}")


if __name__ == "__main__":
    main()
