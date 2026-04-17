#!/usr/bin/env python3
"""
Audio Generator (Windows版)
用 Fish Audio 把每則新聞的 script 逐句轉成 MP3，記錄每句時長供字幕精準對齊
"""
import json, os, re, subprocess, sys, io, shutil, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
from datetime import date

from fish_audio_sdk import Session, TTSRequest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

TODAY     = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
BASE_DIR  = Path(__file__).parent.parent
PIPE_DIR  = BASE_DIR / "pipeline" / TODAY
NEWS_FILE = PIPE_DIR / "news.json"
AUDIO_DIR = PIPE_DIR / "audio"

API_KEY  = os.getenv("FISH_AUDIO_API_KEY", "")
VOICE_ID = os.getenv("FISH_AUDIO_VOICE_ID", "")


# ── ffmpeg/ffprobe 偵測 ───────────────────────────────────────────────

def find_ffmpeg() -> tuple[str, str]:
    if shutil.which("ffmpeg"):
        return "ffmpeg", "ffprobe"
    winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    for root, _, files in os.walk(winget_base):
        for f in files:
            if f.lower() == "ffmpeg.exe":
                d = Path(root)
                return str(d / "ffmpeg.EXE"), str(d / "ffprobe.EXE")
    raise RuntimeError("找不到 ffmpeg！請執行：winget install Gyan.FFmpeg")

FFMPEG, FFPROBE = find_ffmpeg()


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


def concat_mp3(src_files: list[Path], out: Path):
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for p in src_files:
            f.write(f"file '{str(p).replace(chr(92), '/')}'\n")
        lst = f.name
    subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", str(out)], capture_output=True)
    Path(lst).unlink(missing_ok=True)


# ── 句子切分 ─────────────────────────────────────────────────────────

def split_sentences(script: str, max_len: int = 25) -> list[str]:
    """Split script into subtitle-friendly chunks.

    Stage 1: split on 。！？
    Stage 2: any chunk > max_len (CJK chars) → split further on 、，；
    """
    parts = re.split(r'(?<=[。！？])\s*', script)
    parts = [p.strip() for p in parts if p.strip()]

    refined: list[str] = []
    for p in parts:
        if len(p) <= max_len:
            refined.append(p)
            continue
        # Split long chunk on 、 ， ；
        subparts = re.split(r'(?<=[、，；])\s*', p)
        subparts = [s.strip() for s in subparts if s.strip()]
        refined.extend(subparts if subparts else [p])

    return refined if refined else [script]


# ── TTS ──────────────────────────────────────────────────────────────

def text_to_speech(text: str, out_path: Path) -> None:
    if not API_KEY:
        raise RuntimeError("❌ 缺少 FISH_AUDIO_API_KEY")
    if not VOICE_ID:
        raise RuntimeError("❌ 缺少 FISH_AUDIO_VOICE_ID")

    session = Session(API_KEY)
    chunks  = []
    for chunk in session.tts(TTSRequest(
        reference_id = VOICE_ID,
        text         = text,
        format       = "mp3",
        mp3_bitrate  = 128,
        latency      = "normal",
    )):
        chunks.append(chunk)

    out_path.write_bytes(b"".join(chunks))


# ── 主程式 ───────────────────────────────────────────────────────────

def main():
    if not NEWS_FILE.exists():
        print(f"❌ 找不到新聞檔：{NEWS_FILE}", file=sys.stderr)
        sys.exit(1)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    data  = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data["items"]

    print(f"🎙️  生成 {len(items)} 則語音（Fish Audio 哈基米）...")

    for i, item in enumerate(items, 1):
        combined = AUDIO_DIR / f"audio_{i:02d}.mp3"
        timing_f = AUDIO_DIR / f"audio_{i:02d}_timing.json"

        if combined.exists() and timing_f.exists():
            print(f"  [{i}] 已存在，跳過")
            continue

        script    = item.get("script") or item.get("summary", "")
        sentences = split_sentences(script)
        print(f"  [{i}] {item['title']} — {len(sentences)} 句...")

        sent_files = []
        timings    = []
        t_cursor   = 0.0

        for j, sent in enumerate(sentences, 1):
            sp = AUDIO_DIR / f"audio_{i:02d}_s{j:02d}.mp3"
            print(f"      句{j}: {sent[:30]}...")
            text_to_speech(sent, sp)
            dur = get_duration(sp)
            timings.append({"text": sent, "start": t_cursor, "end": t_cursor + dur})
            t_cursor += dur
            sent_files.append(sp)

        # 合併所有句子 → 單一音訊檔
        if len(sent_files) == 1:
            sent_files[0].rename(combined)
        else:
            concat_mp3(sent_files, combined)
            for sp in sent_files:
                sp.unlink(missing_ok=True)

        timing_f.write_text(
            json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"      ✅ {combined.name}，總時長 {t_cursor:.1f}s")

    print(f"\n✅ 語音已存至 {AUDIO_DIR}")


if __name__ == "__main__":
    main()
