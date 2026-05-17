#!/usr/bin/env python3
"""Transcript cache + local Whisper fallback for figure source videos."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
TRANSCRIPT_DIR = BASE_DIR / "data" / "figure_transcripts"


def video_id_from_url(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{6,})", url or "")
    return match.group(1) if match else ""


def video_id_for(video: dict | str) -> str:
    if isinstance(video, dict):
        return str(video.get("id") or video_id_from_url(str(video.get("url") or ""))).strip()
    return video_id_from_url(str(video))


def transcript_path(video: dict | str) -> Path:
    video_id = video_id_for(video)
    if not video_id:
        raise ValueError("cannot resolve video id for transcript cache")
    return TRANSCRIPT_DIR / f"{video_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_transcript(
    video: dict,
    cues: list[dict],
    *,
    source: str,
    model_name: str,
    language: str = "",
) -> Path:
    path = transcript_path(video)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_cues = []
    for cue in cues:
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        clean_cues.append({
            "start": round(float(cue.get("start") or 0), 3),
            "end": round(float(cue.get("end") or 0), 3),
            "text": text,
        })
    payload = {
        "video_id": video_id_for(video),
        "url": video.get("url") or "",
        "title": video.get("title") or "",
        "source": source,
        "model": model_name,
        "language": language,
        "cue_count": len(clean_cues),
        "created_at": _now(),
        "cues": clean_cues,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_transcript(video: dict | str) -> list[dict]:
    path = transcript_path(video)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    cues = data.get("cues") or []
    return cues if isinstance(cues, list) else []


def _yt_dlp_cmd() -> list[str]:
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def _run(cmd: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
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
    raise RuntimeError("ffmpeg not found")


def download_audio(video_url: str, out_dir: Path) -> Path:
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
        raise RuntimeError(f"yt-dlp audio download failed: {result.stderr[-500:]}")
    return candidates[0]


def prepare_audio_sample(audio_path: Path, out_dir: Path, max_minutes: int = 60) -> Path:
    out = out_dir / "transcribe.wav"
    duration = max(60, int(max_minutes) * 60)
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        str(audio_path),
        "-t",
        str(duration),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(out),
    ]
    result = _run(cmd, timeout=900)
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"ffmpeg audio prep failed: {result.stderr[-500:]}")
    return out


def transcribe_audio_local(
    audio_path: Path,
    *,
    model_name: str = "base",
    language: str = "en",
) -> tuple[list[dict], str]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=os.getenv("WHISPER_DEVICE", "cpu"), compute_type="int8")
    segments, info = model.transcribe(
        str(audio_path),
        language=language or None,
        vad_filter=True,
        beam_size=3,
    )
    cues = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            cues.append({
                "start": round(float(seg.start), 3),
                "end": round(float(seg.end), 3),
                "text": text,
            })
    return cues, getattr(info, "language", language or "")


def transcribe_video_local(
    video: dict,
    *,
    model_name: str = "base",
    language: str = "en",
    max_minutes: int = 60,
    force: bool = False,
) -> list[dict]:
    if not force:
        cached = load_transcript(video)
        if cached:
            return cached
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        audio = download_audio(str(video.get("url") or ""), tmp_dir)
        wav = prepare_audio_sample(audio, tmp_dir, max_minutes=max_minutes)
        cues, detected_language = transcribe_audio_local(
            wav,
            model_name=model_name,
            language=language,
        )
    save_transcript(
        video,
        cues,
        source="local_whisper",
        model_name=model_name,
        language=detected_language,
    )
    return cues
