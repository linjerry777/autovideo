"""Generate voice samples for comparison.

Usage:
    python scripts/voice_compare.py <job_key>

Reads news.json from pipeline/<job_key>/ and generates one MP3 per (voice, item)
to pipeline/<job_key>/voice_samples/<voice_name>/item_<n>.mp3

Uses script_long if present, else legacy script, else summary.
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from dotenv import load_dotenv
from fish_audio_sdk import Session, TTSRequest

load_dotenv()

VOICES = {
    "xiaoming_jianmo": "a9372068ed0740b48326cf9a74d7496a",
    "yingxiaohao_nv":  "3b0564702a264ce58f6d13e0b8f2bd74",
    "caocao":          "f6f293aabfe24e46aff0fc309c233d31",
}

BASE_DIR  = Path(__file__).resolve().parent.parent
API_KEY   = os.getenv("FISH_AUDIO_API_KEY")

def tts(text: str, voice_id: str, out: Path) -> None:
    session = Session(API_KEY)
    chunks = []
    for chunk in session.tts(TTSRequest(
        reference_id=voice_id, text=text,
        format="mp3", mp3_bitrate=128, latency="normal",
    )):
        chunks.append(chunk)
    out.write_bytes(b"".join(chunks))

def main():
    if not API_KEY:
        sys.exit("❌ FISH_AUDIO_API_KEY 沒設定")
    if len(sys.argv) < 2:
        sys.exit("usage: voice_compare.py <job_key>  e.g. 2026-04-17/job_79")

    job_key = sys.argv[1]
    pipe_dir = BASE_DIR / "pipeline" / job_key
    news_file = pipe_dir / "news.json"
    if not news_file.exists():
        sys.exit(f"❌ 找不到 {news_file}")

    data = json.loads(news_file.read_text(encoding="utf-8"))
    items = data.get("items", [])
    out_root = pipe_dir / "voice_samples"
    out_root.mkdir(parents=True, exist_ok=True)

    total = len(VOICES) * len(items)
    done = 0
    for voice_name, voice_id in VOICES.items():
        vdir = out_root / voice_name
        vdir.mkdir(exist_ok=True)
        for i, item in enumerate(items, 1):
            script = item.get("script_long") or item.get("script") or item.get("summary", "")
            if not script:
                continue
            out = vdir / f"item_{i:02d}.mp3"
            done += 1
            print(f"[{done}/{total}] {voice_name} item_{i} ({len(script)} 字)...", flush=True)
            try:
                tts(script, voice_id, out)
                print(f"  ✓ {out.relative_to(BASE_DIR)}  ({out.stat().st_size // 1024} KB)")
            except Exception as e:
                print(f"  ✗ {e}")

    print(f"\n✅ 完成，請聽 {out_root.relative_to(BASE_DIR)}/<voice>/item_<n>.mp3")

if __name__ == "__main__":
    main()
