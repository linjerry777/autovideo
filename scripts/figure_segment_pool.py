#!/usr/bin/env python3
"""
Build reusable short-video quote segments from figure source videos.

This turns one long/interview source in figure_source_candidates into several
figure_quote_segments rows. Autopilot can then consume segments one by one
instead of wasting the rest of a long source after one short.
"""
from __future__ import annotations

import argparse
import json
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
from scripts import figure_source_pool
from scripts import figure_transcript_cache
from web import db


def _segment_count_for_source(source_url: str) -> int:
    return sum(
        1
        for row in db.list_figure_quote_segments(None, limit=10000)
        if row.get("source_url") == source_url
    )


def _extract_segments(raw: str) -> list[dict]:
    text = raw or ""
    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        data = json.loads(obj_match.group(0))
        if isinstance(data, dict) and isinstance(data.get("segments"), list):
            return data["segments"]
    arr_match = re.search(r"\[[\s\S]*\]", text)
    if arr_match:
        data = json.loads(arr_match.group(0))
        if isinstance(data, list):
            return data
    raise RuntimeError(f"LLM did not return segment JSON: {text[:300]}")


def normalize_segments(raw_segments: list[dict], cues: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for item in raw_segments:
        try:
            start = max(0.0, float(item.get("start_seconds") or 0))
            end = float(item.get("end_seconds") or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        duration = end - start
        if duration < 18 or duration > 55:
            continue

        quote = str(item.get("quote_zh") or item.get("quote_original") or "").strip()
        script_long = str(item.get("script_long") or item.get("script_short") or "").strip()
        if not quote or len(script_long) < 20:
            continue

        normalized.append({
            "quote_original": str(item.get("quote_original") or quote).strip(),
            "quote_zh": quote,
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "hook": str(item.get("hook") or "這句太狠").strip(),
            "title": str(item.get("title") or "名人金句解析").strip(),
            "summary": str(item.get("summary") or quote[:40]).strip(),
            "bullets_json": item.get("bullets") or [],
            "script_short": str(item.get("script_short") or script_long[:70]).strip(),
            "script_long": script_long,
            "scene_type": str(item.get("scene_type") or "default").strip(),
            "emotion": str(item.get("emotion") or "curiosity").strip(),
            "virality_score": int(item.get("virality_score") or 0),
            "virality_reason": str(item.get("virality_reason") or "").strip(),
            "transcript_window": collector.window_text(cues, start - 5, end + 5),
        })
    return normalized


def _load_cues(source: dict, whisper_fallback: bool = False) -> list[dict]:
    video = {
        "id": source.get("video_id") or "",
        "url": source.get("url") or "",
        "title": source.get("title") or "",
    }
    if source.get("transcript_source") == "local_whisper":
        cues = figure_transcript_cache.load_transcript(video)
        if cues:
            return cues

    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        cues = collector._download_captions(source["url"], tmp_dir)
        if cues:
            return cues
        if whisper_fallback:
            return figure_transcript_cache.transcribe_video_local(
                video,
                model_name="base",
                language="en",
                max_minutes=60,
            )
    return []


def analyze_source_segments(group: str, source: dict, cues: list[dict], desired: int = 6) -> list[dict]:
    from web.claude_client import call_claude

    lane = "科技大咖" if group == "tech" else "娛樂咖"
    transcript = collector._chunk_transcript(cues, max_chars=10000)
    prompt = f"""請用繁體中文回答，只輸出 JSON。
你是短影音剪輯企劃。請從以下 YouTube 逐字稿中，挑出 {desired} 段可各自做成 Shorts 的「{lane}金句解析」片段。

影片標題：{source.get('title')}
頻道：{source.get('channel')}
URL：{source.get('url')}

逐字稿時間段：
{transcript}

要求：
- 每段 start_seconds / end_seconds 長度 18-45 秒。
- 每段都要是不同觀點，不要挑寒暄、片頭、重複段落。
- script_short / script_long 是 Doro 中文旁白解析，不是逐字稿重複。
- 若逐字稿不是中文，quote_zh 要翻成自然繁中。
- 不能捏造不存在的逐字引言。
- 科技大咖偏 AI、產業、產品、工作方式；娛樂咖偏人生、幕後、情緒洞察。
- 依照短影音潛力排序，最強的放前面。

JSON schema:
{{
  "segments": [
    {{
      "quote_original": "原文金句",
      "quote_zh": "繁中金句",
      "start_seconds": 123.4,
      "end_seconds": 158.0,
      "hook": "5-8字強 hook",
      "title": "15字內標題",
      "summary": "40字內摘要",
      "bullets": ["短金句1", "短金句2", "短金句3"],
      "script_short": "45-70字，先說某某說了什麼，再解析為什麼",
      "script_long": "85-120字，含金句、解析、對觀眾的行動提醒",
      "scene_type": "robot | warning | trophy | default",
      "emotion": "curiosity | surprise | joy | fear",
      "virality_score": 1,
      "virality_reason": "一句話"
    }}
  ]
}}"""
    raw, _usage = call_claude(prompt, timeout=240)
    return normalize_segments(_extract_segments(raw), cues)


def build_segments_for_source(
    source: dict,
    desired: int = 6,
    whisper_fallback: bool = False,
) -> list[int]:
    group = source.get("group_name") or "tech"
    cues = _load_cues(source, whisper_fallback=whisper_fallback)
    if len(cues) < 8:
        raise RuntimeError(f"not enough transcript cues: {len(cues)}")
    segments = analyze_source_segments(group, source, cues, desired=desired)
    ids: list[int] = []
    for segment in segments:
        ids.append(db.upsert_figure_quote_segment({
            **segment,
            "source_candidate_id": source.get("id"),
            "group_name": group,
            "figure_name": source.get("figure_name") or "",
            "topic": source.get("topic") or figure_source_pool.infer_topic(
                source.get("title") or "",
                source.get("query") or "",
            ),
            "source_url": source.get("url") or "",
            "source_title": source.get("title") or "",
            "source_channel": source.get("channel") or "YouTube",
            "source_published_at": source.get("source_published_at") or "",
            "video_id": source.get("video_id") or "",
            "status": "available",
        }))
    return ids


def build_group(
    group: str,
    target_segments: int = 120,
    per_source: int = 6,
    max_sources: int = 5,
    max_duration: int = 900,
    whisper_fallback: bool = False,
) -> dict:
    db.init_db()
    sources = [
        row for row in db.list_figure_source_candidates(group, limit=5000)
        if row.get("status") == "available" and int(row.get("caption_count") or 0) >= 8
        and 120 <= int(row.get("duration_seconds") or 0) <= max_duration
    ]
    sources.sort(key=lambda row: (
        _segment_count_for_source(row.get("url") or ""),
        int(row.get("duration_seconds") or 999999),
        -(int(row.get("caption_count") or 0)),
    ))
    current = len([
        row for row in db.list_figure_quote_segments(group, limit=10000)
        if row.get("status") == "available"
    ])
    attempted = 0
    processed = 0
    created = 0
    failed = 0

    for source in sources:
        if current >= target_segments or attempted >= max_sources:
            break
        if _segment_count_for_source(source.get("url") or "") >= per_source:
            continue
        attempted += 1
        print(f"[segments] source={source.get('figure_name')} title={source.get('title', '')[:80]}", flush=True)
        try:
            ids = build_segments_for_source(
                source,
                desired=per_source,
                whisper_fallback=whisper_fallback,
            )
        except Exception as exc:
            failed += 1
            print(f"[segments] failed: {str(exc)[:180]}", flush=True)
            continue
        processed += 1
        created += len(ids)
        current += len(ids)
        print(f"[segments] created={len(ids)} current={current}", flush=True)

    return {
        "group": group,
        "available_segments": current,
        "created": created,
        "attempted_sources": attempted,
        "processed_sources": processed,
        "failed_sources": failed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=["tech", "entertainment"], default="tech")
    parser.add_argument("--target-segments", type=int, default=120)
    parser.add_argument("--per-source", type=int, default=6)
    parser.add_argument("--max-sources", type=int, default=5)
    parser.add_argument("--max-duration", type=int, default=900)
    parser.add_argument("--whisper-fallback", action="store_true")
    args = parser.parse_args()

    result = build_group(
        args.group,
        target_segments=args.target_segments,
        per_source=args.per_source,
        max_sources=args.max_sources,
        max_duration=args.max_duration,
        whisper_fallback=args.whisper_fallback,
    )
    print(f"[segments] summary {result}", flush=True)


if __name__ == "__main__":
    main()
