#!/usr/bin/env python3
"""
Lecture TTS — generate one MP3 per segment + measure duration.

Reads <lesson>.segments.with_slides.json (output of lecture_slides.py),
writes audio_NNN.mp3 next to slides, and produces
<lesson>.segments.final.json with duration + audio path on each segment.

Reuses Fish Audio session machinery from scripts/audio_generator.py.
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from fish_audio_sdk import Session, TTSRequest

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

API_KEY = os.getenv("FISH_AUDIO_API_KEY", "")

# Lecture-mode voice. Falls back to FISH_AUDIO_VOICE_ID. Jerry can override
# with FISH_AUDIO_VOICE_LECTURE for a calmer narration voice if desired.
VOICE_ID = (
    os.getenv("FISH_AUDIO_VOICE_LECTURE")
    or os.getenv("FISH_AUDIO_VOICE_ID")
    or ""
)


def find_ffprobe() -> str:
    if shutil.which("ffprobe"):
        return "ffprobe"
    winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    for root, _, files in os.walk(winget_base):
        for f in files:
            if f.lower() == "ffprobe.exe":
                return str(Path(root) / "ffprobe.EXE")
    raise RuntimeError("ffprobe not found")


FFPROBE = find_ffprobe()


def get_duration(path: Path) -> float:
    r = subprocess.run([
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def tts(text: str, out: Path, session: Session) -> None:
    chunks = []
    for chunk in session.tts(TTSRequest(
        reference_id=VOICE_ID,
        text=text,
        format="mp3",
        mp3_bitrate=128,
        latency="normal",
    )):
        chunks.append(chunk)
    out.write_bytes(b"".join(chunks))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True,
                    help="Path to <lesson>.segments.with_slides.json")
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--out-manifest", required=True)
    args = ap.parse_args()

    if not API_KEY:
        print("❌ FISH_AUDIO_API_KEY missing", file=sys.stderr)
        sys.exit(1)
    if not VOICE_ID:
        print("❌ FISH_AUDIO_VOICE_ID missing", file=sys.stderr)
        sys.exit(1)

    manifest = Path(args.manifest)
    audio_dir = Path(args.audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_manifest = Path(args.out_manifest)

    data = json.loads(manifest.read_text(encoding="utf-8"))
    segments = data["segments"]

    print(f"🎙️ TTS for {len(segments)} segments (voice={VOICE_ID[:8]}…)")
    session = Session(API_KEY)

    total_audio = 0.0
    for i, seg in enumerate(segments):
        narration = (seg.get("narration") or "").strip()
        out_path = audio_dir / f"audio_{i:03d}.mp3"
        if not narration:
            print(f"  [{i:03d}] (empty narration, skipping)")
            seg["_audio_mp3"] = None
            seg["_audio_dur"] = 0.0
            continue
        if out_path.exists() and out_path.stat().st_size > 0:
            dur = get_duration(out_path)
            print(f"  [{i:03d}] cached ({dur:.1f}s) {narration[:40]}…")
        else:
            print(f"  [{i:03d}] {narration[:40]}…")
            tts(narration, out_path, session)
            dur = get_duration(out_path)
            print(f"          → {dur:.1f}s")
        seg["_audio_mp3"] = str(out_path)
        seg["_audio_dur"] = dur
        # Apply min_duration / tail_pause for slide hold-time downstream
        min_dur = float(seg.get("min_duration") or 0.0)
        tail = float(seg.get("tail_pause") or 0.0)
        seg["_slide_dur"] = max(dur + tail, min_dur)
        total_audio += seg["_slide_dur"]

    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print(f"\n✅ Total estimated video length: {total_audio/60:.1f} min "
          f"({total_audio:.1f}s)")
    print(f"✅ Manifest: {out_manifest}")


if __name__ == "__main__":
    main()
