#!/usr/bin/env python3
"""
Build and maintain the source-video candidate pool for figure quote autopilot.

The pool stores videos that already passed the expensive part of discovery:
YouTube search + caption availability check. Daily autopilot can then pick from
SQLite instead of doing a fragile live search every time.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts import figure_quote_collector as collector
from scripts import figure_transcript_cache
from web import db


TECH_QUERY_TEMPLATES = [
    "{name} AI interview",
    "{name} keynote AI",
    "{name} AI agents",
    "{name} future of work",
    "{name} leadership interview",
    "{name} fireside chat AI",
    "{name} podcast artificial intelligence",
]

TECH_EXTRA_FIGURES = [
    "Bill Gates AI",
    "Mustafa Suleyman AI",
    "Demis Hassabis AI",
    "Andrew Ng AI",
    "Fei-Fei Li AI",
    "Geoffrey Hinton AI",
    "Yann LeCun AI",
    "Andrej Karpathy AI",
    "Dario Amodei AI",
    "Ilya Sutskever AI",
    "Reid Hoffman AI",
    "Jeff Bezos AI",
    "Tim Cook AI",
    "Marc Andreessen AI",
    "Ben Horowitz AI",
    "Eric Schmidt AI",
    "Kai-Fu Lee AI",
    "Aravind Srinivas AI",
    "Arthur Mensch AI",
    "Mira Murati AI",
    "Clement Delangue AI",
    "Aidan Gomez AI",
    "Alexandr Wang AI",
]

ENTERTAINMENT_QUERY_TEMPLATES = [
    "{name} 訪談 金句",
    "{name} 人生 觀點 訪談",
    "{name} 深度訪談",
    "{name} podcast 訪談",
]


def infer_topic(title: str, query: str = "") -> str:
    text = f"{title} {query}".lower()
    if re.search(r"\b(ai agents?|agentic|copilot|assistant)\b", text):
        return "AI agents"
    if re.search(r"\b(gpu|nvidia|amd|chip|semiconductor|data center|datacenter)\b", text):
        return "chips/GPU"
    if re.search(r"\b(future of work|workplace|productivity|jobs?|career)\b", text):
        return "future of work"
    if re.search(r"\b(startup|founder|venture|entrepreneur)\b", text):
        return "startup/business"
    if re.search(r"\b(leadership|ceo|management|culture)\b", text):
        return "leadership"
    if re.search(r"\b(ai|artificial intelligence|machine learning|llm)\b", text):
        return "AI strategy"
    if re.search(r"(人生|觀點|金句|訪談)", text):
        return "life insight"
    return "general"


def is_promising_source(title: str, query: str = "") -> bool:
    text = f"{title} {query}".lower()
    bad_patterns = [
        r"\breveals?\b",
        r"\breacts?\b",
        r"\bwarns?\b",
        r"\bprediction\b",
        r"\bno idea what's coming\b",
        r"\bshocking\b",
        r"\bbrutally honest\b",
        r"懶人包",
        r"重點",
        r"最新訪談",
    ]
    if any(re.search(pattern, text) for pattern in bad_patterns):
        return False
    good_patterns = [
        r"\binterview\b",
        r"\bkeynote\b",
        r"\bfireside chat\b",
        r"\bconversation\b",
        r"\bpodcast\b",
        r"\btalk\b",
        r"訪談",
        r"對談",
        r"演講",
    ]
    return any(re.search(pattern, text) for pattern in good_patterns)


def expanded_queries(group: str) -> list[tuple[str, str]]:
    names = collector.figure_names(group)
    if group == "tech":
        seen = {name.lower() for name in names}
        names += [name for name in TECH_EXTRA_FIGURES if name.lower() not in seen]
    templates = ENTERTAINMENT_QUERY_TEMPLATES if group == "entertainment" else TECH_QUERY_TEMPLATES
    return [(name, tpl.format(name=name)) for name in names for tpl in templates]


def _video_id_from_url(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{6,})", url or "")
    return match.group(1) if match else ""


def _source_published_at(video: dict, status: str) -> str:
    published = str(video.get("source_published_at") or "").strip()
    if published or status != "available":
        return published
    try:
        return collector._video_info(video.get("url") or "").get("source_published_at") or ""
    except Exception as exc:
        print(f"[pool] metadata date skipped: {str(exc)[:120]}", flush=True)
        return ""


def _available_count(group: str) -> int:
    rows = db.list_figure_source_candidates(group, limit=1000)
    return sum(1 for row in rows if row.get("status") == "available" and int(row.get("caption_count") or 0) >= 8)


def scan_group(
    group: str,
    target: int = 60,
    per_query_limit: int = 5,
    max_checked: int = 240,
    recheck_no_captions: bool = False,
    whisper_fallback_limit: int = 0,
) -> dict:
    db.init_db()
    used = collector._used_urls()
    db.sync_figure_source_usage(used)

    checked = 0
    available_added = 0
    skipped_used = 0
    skipped_known = 0
    failed_captions = 0
    whisper_used = 0

    for figure_name, query in expanded_queries(group):
        if _available_count(group) >= target or checked >= max_checked:
            break
        print(f"[pool] search group={group} figure={figure_name} query={query}", flush=True)
        for video in collector._search_youtube(query, limit=per_query_limit):
            if _available_count(group) >= target or checked >= max_checked:
                break
            url = video.get("url") or ""
            if not url:
                continue
            known = {
                row["url"]: row
                for row in db.list_figure_source_candidates(group, limit=5000)
            }
            known_status = known.get(url, {}).get("status")
            if url in known and known_status in {"available", "used"}:
                skipped_known += 1
                continue
            if url in known and known_status == "no_captions" and not recheck_no_captions:
                skipped_known += 1
                continue
            if url in used:
                skipped_used += 1
                db.upsert_figure_source_candidate({
                    "group_name": group,
                    "figure_name": figure_name,
                    "topic": infer_topic(video.get("title", ""), query),
                    "query": query,
                    "video_id": video.get("id") or _video_id_from_url(url),
                    "url": url,
                    "title": video.get("title") or "",
                    "channel": video.get("channel") or "YouTube",
                    "duration_seconds": int(video.get("duration") or 0),
                    "source_published_at": _source_published_at(video, "used"),
                    "caption_count": 0,
                    "status": "used",
                })
                continue

            duration = int(video.get("duration") or 0)
            if duration and duration < 120:
                continue

            checked += 1
            with tempfile.TemporaryDirectory() as td:
                tmp_dir = Path(td)
                cues = collector._download_captions(url, tmp_dir)
                transcript_source = "youtube"
                if (
                    len(cues) < 8
                    and whisper_used < whisper_fallback_limit
                    and is_promising_source(video.get("title", ""), query)
                ):
                    print(f"[pool] whisper fallback title={video.get('title', '')[:70]}", flush=True)
                    try:
                        cues = figure_transcript_cache.transcribe_video_local(
                            {
                                "id": video.get("id") or _video_id_from_url(url),
                                "url": url,
                                "title": video.get("title") or "",
                            },
                            model_name="base",
                            language="en",
                            max_minutes=60,
                        )
                        transcript_source = "local_whisper"
                        whisper_used += 1
                    except Exception as exc:
                        print(f"[pool] whisper failed: {str(exc)[:140]}", flush=True)
            caption_count = len(cues)
            status = "available" if caption_count >= 8 else "no_captions"
            if status == "available":
                available_added += 1
            else:
                failed_captions += 1

            db.upsert_figure_source_candidate({
                "group_name": group,
                "figure_name": figure_name,
                "topic": infer_topic(video.get("title", ""), query),
                "query": query,
                "video_id": video.get("id") or _video_id_from_url(url),
                "url": url,
                "title": video.get("title") or "",
                "channel": video.get("channel") or "YouTube",
                "duration_seconds": duration,
                "source_published_at": _source_published_at(video, status),
                "caption_count": caption_count,
                "transcript_source": transcript_source,
                "status": status,
                "fail_reason": "" if status == "available" else f"caption_count={caption_count}",
            })
            print(
                f"[pool] {status} captions={caption_count} title={video.get('title', '')[:70]}",
                flush=True,
            )

    return {
        "group": group,
        "available_total": _available_count(group),
        "available_added": available_added,
        "checked": checked,
        "skipped_used": skipped_used,
        "skipped_known": skipped_known,
        "failed_captions": failed_captions,
        "whisper_used": whisper_used,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=["tech", "entertainment", "all"], default="tech")
    parser.add_argument("--target", type=int, default=60)
    parser.add_argument("--per-query-limit", type=int, default=5)
    parser.add_argument("--max-checked", type=int, default=240)
    parser.add_argument("--recheck-no-captions", action="store_true")
    parser.add_argument("--whisper-fallback-limit", type=int, default=0)
    args = parser.parse_args()

    groups = ["tech", "entertainment"] if args.group == "all" else [args.group]
    for group in groups:
        result = scan_group(
            group,
            target=args.target,
            per_query_limit=args.per_query_limit,
            max_checked=args.max_checked,
            recheck_no_captions=args.recheck_no_captions,
            whisper_fallback_limit=args.whisper_fallback_limit,
        )
        print(f"[pool] summary {result}", flush=True)


if __name__ == "__main__":
    main()
