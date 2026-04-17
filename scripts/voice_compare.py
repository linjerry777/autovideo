"""Generate voice samples for comparison.

Usage:
    python scripts/voice_compare.py <job_key>
    python scripts/voice_compare.py <job_key> --with-bgm   # also mix BGM + hook SFX

Reads news.json from pipeline/<job_key>/ and generates one MP3 per (voice, item)
to pipeline/<job_key>/voice_samples/<voice_name>/item_<n>.mp3

With --with-bgm, also writes item_<n>_mixed.mp3 using the real mix_audio()
path from audio_generator (BGM sidechain-ducked + hook SFX prepended).

Uses script_long if present, else legacy script, else summary.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from dotenv import load_dotenv
from fish_audio_sdk import Session, TTSRequest

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_assets import pick_bgm, pick_hook_sfx      # sibling import
from audio_generator import mix_audio                 # reuse real mixer

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
    ap = argparse.ArgumentParser()
    ap.add_argument("job_key", help="e.g. 2026-04-17/job_79")
    ap.add_argument("--with-bgm", action="store_true",
                    help="Also mix BGM + hook SFX using real mix_audio()")
    args = ap.parse_args()

    if not API_KEY:
        sys.exit("❌ FISH_AUDIO_API_KEY 沒設定")

    job_key = args.job_key
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
            raw_out = vdir / f"item_{i:02d}.mp3"
            done += 1
            print(f"[{done}/{total}] {voice_name} item_{i} ({len(script)} 字)...", flush=True)
            try:
                if not raw_out.exists():
                    tts(script, voice_id, raw_out)
                    print(f"  ✓ raw {raw_out.relative_to(BASE_DIR)}  ({raw_out.stat().st_size // 1024} KB)")
                else:
                    print(f"  ⟳ raw already exists, skip TTS")

                if args.with_bgm:
                    mixed = vdir / f"item_{i:02d}_mixed.mp3"
                    bgm = pick_bgm(item.get("emotion") or "generic")
                    sfx = pick_hook_sfx() if i == 1 else None   # only first item gets SFX, matches pipeline
                    mix_audio(raw_out, mixed, bgm=bgm, hook_sfx=sfx)
                    label = f"bgm={bgm.name if bgm else '(none)'}"
                    if sfx: label += f" + sfx={sfx.name}"
                    print(f"  🎵 mixed {mixed.relative_to(BASE_DIR)}  ({label})")
            except Exception as e:
                print(f"  ✗ {e}")

    print(f"\n✅ 完成，請聽 {out_root.relative_to(BASE_DIR)}/<voice>/item_<n>.mp3")
    if args.with_bgm:
        print(f"   混 BGM + SFX 版本：{out_root.relative_to(BASE_DIR)}/<voice>/item_<n>_mixed.mp3")

if __name__ == "__main__":
    main()
