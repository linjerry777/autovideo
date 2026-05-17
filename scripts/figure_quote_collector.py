#!/usr/bin/env python3
"""
Figure Quote Collector

YouTube MVP for the "名人原片解析" autopilot lane:
1. Search YouTube for configured figures.
2. Pull captions/transcript.
3. Ask the LLM to select a quotable segment and write Doro-style analysis.
4. Download that source-video segment into broll/broll_01.mp4.
5. Write news.json so the existing audio/video/publisher pipeline can continue.

X / IG sources are intentionally left for a later connector phase because they
usually require logged-in sessions and are much less stable for unattended jobs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

from scripts import figure_transcript_cache


TECH_FIGURES = [
    "黃仁勳 Jensen Huang",
    "張忠謀 Morris Chang",
    "Sam Altman",
    "Satya Nadella",
    "Lisa Su",
    "Elon Musk AI",
    "Mark Zuckerberg AI",
]

ENTERTAINMENT_FIGURES = [
    "蔡康永 訪談",
    "小S 訪談",
    "周杰倫 訪談",
    "劉德華 訪談",
    "林志玲 訪談",
    "吳宗憲 訪談",
]


def _yt_dlp_cmd() -> list[str]:
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def _run(cmd: list[str], *, timeout: int = 900, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    for root, _dirs, files in os.walk(winget_base):
        for f in files:
            if f.lower() == "ffmpeg.exe":
                return str(Path(root) / f)
    raise RuntimeError("找不到 ffmpeg")


def parse_timecode(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    else:
        return float(value)
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_vtt(raw: str) -> list[dict]:
    cues: list[dict] = []
    time_re = re.compile(
        r"(?P<start>\d{2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
        r"(?P<end>\d{2}:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})"
    )
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        time_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), -1)
        if time_idx < 0:
            continue
        match = time_re.search(lines[time_idx])
        if not match:
            continue
        text_lines = lines[time_idx + 1 :]
        text = " ".join(text_lines)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        cues.append({
            "start": round(parse_timecode(match.group("start")), 3),
            "end": round(parse_timecode(match.group("end")), 3),
            "text": text,
        })
    return cues


def window_text(cues: list[dict], start: float, end: float) -> str:
    rows = []
    for cue in cues:
        if cue["end"] < start or cue["start"] > end:
            continue
        rows.append(f"[{cue['start']:.1f}-{cue['end']:.1f}] {cue['text']}")
    return "\n".join(rows)


def _chunk_transcript(cues: list[dict], max_chars: int = 12000) -> str:
    rows = []
    last_end = 0.0
    buf = []
    for cue in cues:
        buf.append(cue["text"])
        last_end = cue["end"]
        if len(" ".join(buf)) >= 260:
            rows.append(f"[{max(0, cue['start'] - 12):.0f}-{last_end:.0f}] {' '.join(buf)}")
            buf = []
        if sum(len(r) for r in rows) >= max_chars:
            break
    if buf and sum(len(r) for r in rows) < max_chars:
        rows.append(f"[{max(0, last_end - 20):.0f}-{last_end:.0f}] {' '.join(buf)}")
    return "\n".join(rows)[:max_chars]


def _used_urls() -> set[str]:
    used: set[str] = set()
    for news_file in (BASE_DIR / "pipeline").glob("*/*/news.json"):
        try:
            data = json.loads(news_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in data.get("items", []):
            url = item.get("source_url") or item.get("url") or ""
            if url:
                used.add(url)
    return used


def _settings_csv(key: str, default: str) -> list[str]:
    try:
        from web.db import get_setting
        raw = get_setting(key, default)
    except Exception:
        raw = os.getenv(key.upper(), default)
    return [x.strip() for x in str(raw or default).split(",") if x.strip()]


def figure_names(group: str) -> list[str]:
    if group == "entertainment":
        default = ",".join(ENTERTAINMENT_FIGURES)
        return _settings_csv("autopilot_figure_entertainment_names", default)
    default = ",".join(TECH_FIGURES)
    return _settings_csv("autopilot_figure_tech_names", default)


def search_queries(group: str, names: list[str]) -> list[str]:
    if group == "entertainment":
        return [f"{name} 訪談 金句 人生 觀點" for name in names]
    return [f"{name} keynote interview AI future leadership" for name in names]


def _published_at(data: dict) -> str:
    raw = str(data.get("upload_date") or data.get("release_date") or "").strip()
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    ts = data.get("timestamp") or data.get("release_timestamp")
    if ts:
        try:
            return date.fromtimestamp(int(ts)).isoformat()
        except Exception:
            return ""
    return raw


def _search_youtube(query: str, limit: int) -> list[dict]:
    cmd = _yt_dlp_cmd() + [
        "--dump-json",
        "--flat-playlist",
        f"ytsearch{limit}:{query}",
    ]
    result = _run(cmd, timeout=180)
    if result.returncode != 0:
        return []
    items = []
    for line in result.stdout.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        video_id = data.get("id")
        if not video_id:
            continue
        url = data.get("url") or f"https://www.youtube.com/watch?v={video_id}"
        if not str(url).startswith("http"):
            url = f"https://www.youtube.com/watch?v={video_id}"
        items.append({
            "id": video_id,
            "url": url,
            "title": data.get("title") or "",
            "duration": data.get("duration"),
            "channel": data.get("channel") or data.get("uploader") or "YouTube",
            "source_published_at": _published_at(data),
            "query": query,
        })
    return items


def _pool_candidate(group: str, used: set[str]) -> tuple[dict, list[dict]] | None:
    try:
        from web.db import mark_figure_source_status, pick_figure_source_candidate
    except Exception:
        return None

    row = pick_figure_source_candidate(group, used_urls=used, min_caption_count=8)
    if not row:
        return None

    video = {
        "id": row.get("video_id") or "",
        "url": row.get("url") or "",
        "title": row.get("title") or "",
        "duration": row.get("duration_seconds") or 0,
        "channel": row.get("channel") or "YouTube",
        "query": row.get("query") or "source-pool",
        "figure_name": row.get("figure_name") or "",
        "topic": row.get("topic") or "",
        "transcript_source": row.get("transcript_source") or "youtube",
        "source_published_at": row.get("source_published_at") or "",
        "source_pool_id": row.get("id"),
    }
    print(f"[pool] using candidate: {video['title'][:80]}", flush=True)
    cues = []
    if video.get("transcript_source") == "local_whisper":
        cues = figure_transcript_cache.load_transcript(video)
        if cues:
            print(f"    loaded cached transcript cues={len(cues)}", flush=True)
    if not cues:
        with tempfile.TemporaryDirectory() as td:
            tmp_dir = Path(td)
            cues = _download_captions(video["url"], tmp_dir)
    print(f"    cues={len(cues)}", flush=True)
    if len(cues) >= 8:
        return video, cues

    mark_figure_source_status(video["url"], "stale", f"caption_count_now={len(cues)}")
    return None


def _cues_from_segment_window(window: str, start: float, end: float) -> list[dict]:
    cues: list[dict] = []
    line_re = re.compile(r"^\[(?P<start>\d+(?:\.\d+)?)-(?P<end>\d+(?:\.\d+)?)\]\s*(?P<text>.*)$")
    for line in (window or "").splitlines():
        match = line_re.match(line.strip())
        if not match:
            continue
        text = match.group("text").strip()
        if not text:
            continue
        cues.append({
            "start": float(match.group("start")),
            "end": float(match.group("end")),
            "text": text,
        })
    if cues:
        return cues
    return [{"start": start, "end": end, "text": window or ""}]


def _pool_segment(group: str) -> tuple[dict, list[dict], dict, int] | None:
    try:
        from web.db import pick_figure_quote_segment
    except Exception:
        return None

    row = pick_figure_quote_segment(group, min_score=0)
    if not row:
        return None

    start = float(row.get("start_seconds") or 0)
    end = float(row.get("end_seconds") or start + 30)
    bullets_raw = row.get("bullets_json") or "[]"
    try:
        bullets = json.loads(bullets_raw) if isinstance(bullets_raw, str) else bullets_raw
    except Exception:
        bullets = []
    video = {
        "id": row.get("video_id") or "",
        "url": row.get("source_url") or "",
        "title": row.get("source_title") or "",
        "duration": 0,
        "channel": row.get("source_channel") or "YouTube",
        "query": "segment-pool",
        "figure_name": row.get("figure_name") or "",
        "topic": row.get("topic") or "",
        "source_published_at": row.get("source_published_at") or "",
        "source_segment_id": row.get("id"),
    }
    analysis = {
        "figure_name": row.get("figure_name") or "",
        "quote_original": row.get("quote_original") or row.get("quote_zh") or "",
        "quote_zh": row.get("quote_zh") or row.get("quote_original") or "",
        "start_seconds": start,
        "end_seconds": end,
        "hook": row.get("hook") or "這句太狠",
        "title": row.get("title") or "名人金句解析",
        "summary": row.get("summary") or "",
        "bullets": bullets if isinstance(bullets, list) else [],
        "script_short": row.get("script_short") or "",
        "script_long": row.get("script_long") or row.get("script_short") or "",
        "scene_type": row.get("scene_type") or "default",
        "emotion": row.get("emotion") or "curiosity",
        "virality_score": int(row.get("virality_score") or 0),
        "virality_reason": row.get("virality_reason") or "片段池預選金句。",
    }
    cues = _cues_from_segment_window(row.get("transcript_window") or "", start, end)
    print(f"[segment] using quote segment #{row.get('id')}: {analysis['title']}", flush=True)
    return video, cues, analysis, int(row["id"])


def _video_info(video_url: str) -> dict:
    cmd = _yt_dlp_cmd() + ["--dump-json", "--skip-download", video_url]
    result = _run(cmd, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp metadata failed: {result.stderr[-500:]}")
    data = json.loads(result.stdout.splitlines()[0])
    return {
        "id": data.get("id") or "",
        "url": video_url,
        "title": data.get("title") or "",
        "duration": data.get("duration"),
        "channel": data.get("channel") or data.get("uploader") or "YouTube",
        "source_published_at": _published_at(data),
        "query": "direct-url",
    }


def _download_captions(video_url: str, out_dir: Path) -> list[dict]:
    out_tpl = str(out_dir / "captions.%(ext)s")
    cmd = _yt_dlp_cmd() + [
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "zh.*,en.*,zh-Hant,zh-TW,zh-CN,zh,zh-Hans,en",
        "--sub-format", "vtt",
        "-o", out_tpl,
        video_url,
    ]
    result = _run(cmd, timeout=300)
    if result.returncode != 0:
        return []
    cues: list[dict] = []
    for path in sorted(out_dir.glob("captions*.vtt")):
        parsed = parse_vtt(path.read_text(encoding="utf-8", errors="replace"))
        if len(parsed) > len(cues):
            cues = parsed
    return cues


def _download_audio(video_url: str, out_dir: Path) -> Path:
    out_tpl = str(out_dir / "source_audio.%(ext)s")
    cmd = _yt_dlp_cmd() + [
        "-f", "ba/b",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "6",
        "-o", out_tpl,
        video_url,
    ]
    result = _run(cmd, timeout=1200)
    candidates = sorted(out_dir.glob("source_audio.*"))
    if result.returncode != 0 or not candidates:
        raise RuntimeError(f"yt-dlp 音訊下載失敗: {result.stderr[-500:]}")
    return candidates[0]


def _split_audio(audio_path: Path, out_dir: Path, chunk_seconds: int = 600) -> list[Path]:
    if audio_path.stat().st_size <= 23 * 1024 * 1024:
        return [audio_path]
    ffmpeg = _ffmpeg()
    split_tpl = out_dir / "audio_chunk_%03d.mp3"
    cmd = [
        ffmpeg, "-y", "-i", str(audio_path),
        "-f", "segment", "-segment_time", str(chunk_seconds),
        "-c:a", "libmp3lame", "-b:a", "48k",
        str(split_tpl),
    ]
    result = _run(cmd, timeout=900)
    chunks = sorted(out_dir.glob("audio_chunk_*.mp3"))
    if result.returncode != 0 or not chunks:
        raise RuntimeError(f"ffmpeg 音訊切段失敗: {result.stderr[-500:]}")
    return chunks


def _transcribe_audio_file(audio_path: Path) -> list[dict]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("字幕不存在，且缺少 OPENAI_API_KEY，無法 Whisper 轉文字")
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
    with audio_path.open("rb") as f:
        resp = client.audio.transcriptions.create(
            model=model,
            file=f,
            response_format="verbose_json",
        )
    raw_segments = getattr(resp, "segments", None) or []
    cues = []
    for seg in raw_segments:
        if isinstance(seg, dict):
            start, end, text = seg.get("start"), seg.get("end"), seg.get("text")
        else:
            start, end, text = getattr(seg, "start", None), getattr(seg, "end", None), getattr(seg, "text", None)
        if text:
            cues.append({"start": float(start or 0), "end": float(end or 0), "text": str(text).strip()})
    if cues:
        return cues
    text = getattr(resp, "text", "") or ""
    return [{"start": 0.0, "end": 60.0, "text": text.strip()}] if text.strip() else []


def _transcribe_video(video_url: str, out_dir: Path) -> list[dict]:
    audio = _download_audio(video_url, out_dir)
    chunks = _split_audio(audio, out_dir)
    all_cues: list[dict] = []
    offset = 0.0
    for chunk in chunks[:6]:  # cap MVP transcription to roughly the first hour
        cues = _transcribe_audio_file(chunk)
        for cue in cues:
            all_cues.append({
                "start": round(float(cue["start"]) + offset, 3),
                "end": round(float(cue["end"]) + offset, 3),
                "text": cue["text"],
            })
        if cues:
            offset += max(float(c["end"]) for c in cues)
    return all_cues


def _choose_candidate(group: str) -> tuple[dict, list[dict]]:
    used = _used_urls()
    pooled = _pool_candidate(group, used)
    if pooled:
        return pooled

    for query in search_queries(group, figure_names(group)):
        print(f"🔎 搜尋 YouTube：{query}", flush=True)
        for video in _search_youtube(query, limit=5):
            if video["url"] in used:
                continue
            dur = int(video.get("duration") or 0)
            if dur and dur < 120:
                continue
            print(f"  試影片：{video['title'][:80]}", flush=True)
            with tempfile.TemporaryDirectory() as td:
                tmp_dir = Path(td)
                cues = _download_captions(video["url"], tmp_dir)
                print(f"    字幕 cues={len(cues)}", flush=True)
                if len(cues) < 8 and os.getenv("OPENAI_API_KEY"):
                    print("    無字幕，改用 Whisper fallback", flush=True)
                    try:
                        cues = _transcribe_video(video["url"], tmp_dir)
                    except Exception:
                        cues = []
            if len(cues) >= 8:
                return video, cues
    raise RuntimeError("找不到可用的 YouTube 名人影片或字幕")


def _analyze_quote(group: str, video: dict, cues: list[dict]) -> dict:
    from web.claude_client import call_claude

    lane = "科技大咖" if group == "tech" else "娛樂咖"
    transcript = _chunk_transcript(cues)
    prompt = f"""請用繁體中文回答，只輸出 JSON。
你是短影音剪輯企劃。請從以下 YouTube 逐字稿中，挑一段最適合做「{lane}金句解析」的片段。

影片標題：{video.get('title')}
頻道：{video.get('channel')}
URL：{video.get('url')}

逐字稿時間段：
{transcript}

要求：
- 找一句有觀點、衝突或啟發的金句，不要挑寒暄。
- start_seconds / end_seconds 要落在逐字稿時間附近，長度 18-45 秒。
- script_short / script_long 是 Doro 旁白解析，不是逐字稿重複。
- 若逐字稿不是中文，quote_zh 要翻成自然繁中。
- 不能捏造不存在的逐字引言。
- 娛樂咖可偏人生/幕後/情緒洞察；科技大咖要偏 AI、產業、產品、工作方式。

JSON schema:
{{
  "figure_name": "人物名",
  "quote_original": "原文金句，短一點",
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
}}"""
    print("🧠 LLM 分析金句與解析腳本...", flush=True)
    raw, _usage = call_claude(prompt, timeout=180)
    match = re.search(r"\{[\s\S]*\}", raw or "")
    if not match:
        raise RuntimeError(f"LLM 沒回 JSON: {(raw or '')[:300]}")
    data = json.loads(match.group(0))
    start = float(data.get("start_seconds") or 0)
    end = float(data.get("end_seconds") or start + 30)
    if end <= start:
        end = start + 30
    data["start_seconds"] = max(0.0, start)
    data["end_seconds"] = min(max(data["start_seconds"] + 18, end), data["start_seconds"] + 45)
    return data


def _download_clip(video_url: str, start: float, end: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"⬇️  下載低解析原片到本地暫存，再裁 {start:.1f}-{end:.1f}s", flush=True)
    tmp = out_path.with_suffix(".source.%(ext)s")
    cmd = _yt_dlp_cmd() + [
        # Download a modest local source first, then trim locally. yt-dlp's
        # remote --download-sections path can hang for minutes on googlevideo
        # URLs when ffmpeg tries to seek/cut precisely.
        "-f", "bv*[height<=480]+ba/b[height<=480]/b",
        "--merge-output-format", "mp4",
        "-o", str(tmp),
        video_url,
    ]
    result = _run(cmd, timeout=1200)
    candidates = sorted(out_path.parent.glob(out_path.stem + ".source.*"))
    if result.returncode != 0 or not candidates:
        raise RuntimeError(f"yt-dlp 下載來源影片失敗: {result.stderr[-500:]}")
    downloaded = candidates[0]
    ffmpeg = _ffmpeg()
    trim_cmd = [
        ffmpeg, "-y",
        "-ss", str(max(0, start - 2)),
        "-i", str(downloaded),
        "-t", str(max(8, end - start + 5)),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print("✂️  本地 ffmpeg 裁切 9:16 broll...", flush=True)
    trim = _run(trim_cmd, timeout=600)
    downloaded.unlink(missing_ok=True)
    if trim.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"ffmpeg 裁切片段失敗: {trim.stderr[-500:]}")


def build_news_item(group: str, video: dict, analysis: dict, cues: list[dict]) -> dict:
    figure = analysis.get("figure_name") or video.get("channel") or ("科技大咖" if group == "tech" else "娛樂咖")
    quote = analysis.get("quote_zh") or analysis.get("quote_original") or ""
    script_long = analysis.get("script_long") or f"{figure}說：{quote}。這句話真正重要的是，它提醒我們別只看表面，要看背後的選擇。"
    script_short = analysis.get("script_short") or script_long[:70]
    return {
        "hook": analysis.get("hook") or "這句太狠",
        "hook_variants": analysis.get("hook_variants") or ["這句太狠", "別只聽表面", "他在提醒你"],
        "title": analysis.get("title") or f"{figure}金句解析",
        "summary": analysis.get("summary") or f"{figure}金句：{quote[:28]}",
        "bullets": analysis.get("bullets") or ["不是表面", "看懂底層", "用在今天"],
        "script_short": script_short,
        "script_long": script_long,
        "script": script_long,
        "scene_type": analysis.get("scene_type") or ("robot" if group == "tech" else "default"),
        "virality_score": int(analysis.get("virality_score") or 7),
        "virality_reason": analysis.get("virality_reason") or "名人原片加觀點解析，適合短影音停留。",
        "emotion": analysis.get("emotion") or "curiosity",
        "source_url": video.get("url"),
        "source_name": video.get("channel") or "YouTube",
        "source_published_at": video.get("source_published_at") or "",
        "source_segment_id": video.get("source_segment_id") or "",
        "url": video.get("url"),
        "source": video.get("channel") or "YouTube",
        "figure_name": figure,
        "quote_original": analysis.get("quote_original") or quote,
        "quote_zh": quote,
        "clip_start": analysis.get("start_seconds"),
        "clip_end": analysis.get("end_seconds"),
        "transcript_window": window_text(
            cues,
            float(analysis.get("start_seconds") or 0) - 5,
            float(analysis.get("end_seconds") or 0) + 5,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_key", nargs="?", default=date.today().isoformat())
    parser.add_argument("--group", choices=["tech", "entertainment"], default="tech")
    parser.add_argument("--strategy", default="")
    parser.add_argument("--profile", default="")
    parser.add_argument("--url", default="", help="Direct YouTube URL for preview/debug.")
    args = parser.parse_args()

    pipe_dir = BASE_DIR / "pipeline" / args.job_key
    broll_dir = pipe_dir / "broll"
    pipe_dir.mkdir(parents=True, exist_ok=True)
    broll_dir.mkdir(parents=True, exist_ok=True)

    strategy = args.strategy or ("figure_tech" if args.group == "tech" else "figure_entertainment")
    segment_id = None
    if args.url:
        video = _video_info(args.url)
        print(f"🎯 使用指定影片：{video['title'][:100]}", flush=True)
        with tempfile.TemporaryDirectory() as td:
            tmp_dir = Path(td)
            cues = _download_captions(video["url"], tmp_dir)
            print(f"    字幕 cues={len(cues)}", flush=True)
            if len(cues) < 8 and os.getenv("OPENAI_API_KEY"):
                print("    無字幕，改用 Whisper fallback", flush=True)
                cues = _transcribe_video(video["url"], tmp_dir)
        if len(cues) < 8:
            raise RuntimeError("指定影片沒有可用字幕，且 Whisper fallback 不可用")
        analysis = _analyze_quote(args.group, video, cues)
    else:
        pooled_segment = _pool_segment(args.group)
        if pooled_segment:
            video, cues, analysis, segment_id = pooled_segment
        else:
            video, cues = _choose_candidate(args.group)
            analysis = _analyze_quote(args.group, video, cues)
    _download_clip(video["url"], float(analysis["start_seconds"]), float(analysis["end_seconds"]), broll_dir / "broll_01.mp4")
    try:
        if segment_id:
            from web.db import mark_figure_quote_segment_used
            mark_figure_quote_segment_used(segment_id)
        else:
            from web.db import mark_figure_source_used
            mark_figure_source_used(video["url"])
    except Exception:
        pass

    item = build_news_item(args.group, video, analysis, cues)
    news = {
        "date": args.job_key,
        "content_type": "figure_quote",
        "figure_group": args.group,
        "account_profile": args.profile,
        "strategy": strategy,
        "layout_mode": "visual",
        "items": [item],
    }
    (pipe_dir / "news.json").write_text(json.dumps(news, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ figure quote ready: {item['title']} ({video['url']})")


if __name__ == "__main__":
    main()
