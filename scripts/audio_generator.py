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

# Import audio_assets (sibling-first to dodge pywin32 namespace conflict on Windows)
try:
    import sys as _sys
    _script_dir = str(Path(__file__).resolve().parent)
    if _script_dir not in _sys.path:
        _sys.path.insert(0, _script_dir)
    from audio_assets import pick_bgm, pick_hook_sfx
except ImportError:
    from scripts.audio_assets import pick_bgm, pick_hook_sfx

load_dotenv(Path(__file__).parent.parent / ".env")

import argparse as _ap
_parser = _ap.ArgumentParser()
_parser.add_argument("job_key", nargs="?", default=date.today().isoformat())
_parser.add_argument("--version", choices=["short", "long"], default=None,
                     help="Pick script_short / script_long for dual-version output (default: legacy script)")
_args, _ = _parser.parse_known_args()

TODAY   = _args.job_key
VERSION = _args.version

BASE_DIR  = Path(__file__).parent.parent
PIPE_DIR  = BASE_DIR / "pipeline" / TODAY
NEWS_FILE = PIPE_DIR / "news.json"
AUDIO_DIR = PIPE_DIR / VERSION / "audio" if VERSION else PIPE_DIR / "audio"

API_KEY  = os.getenv("FISH_AUDIO_API_KEY", "")
DEFAULT_VOICE_ID = os.getenv("FISH_AUDIO_VOICE_ID", "")

# Per-strategy voice mapping (env vars are optional — fall back to default)
STRATEGY_VOICE_MAP = {
    "tech":          os.getenv("FISH_AUDIO_VOICE_TECH",          "") or DEFAULT_VOICE_ID,
    "entertainment": os.getenv("FISH_AUDIO_VOICE_ENTERTAINMENT", "") or DEFAULT_VOICE_ID,
    "finance":       os.getenv("FISH_AUDIO_VOICE_FINANCE",       "") or DEFAULT_VOICE_ID,
    "pet":           os.getenv("FISH_AUDIO_VOICE_PET",           "") or DEFAULT_VOICE_ID,
}


def resolve_voice_id(strategy: str | None) -> str:
    """Pick voice_id by strategy, falling back to default."""
    return STRATEGY_VOICE_MAP.get((strategy or "").lower(), DEFAULT_VOICE_ID)


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


LEADING_SILENCE_S = 0.3   # silence before SFX (gives breathing room)
SFX_BGM_GAP_S     = 0.2   # silence between SFX and voice
SFX_MAX_DUR_S     = 2.0   # hard cap — if user drops a full song in sfx/hook/, only first 2s used
BGM_DUCK_DB       = -12   # how much BGM dips when voice plays
BGM_BASE_DB       = -18   # BGM resting volume under voice


def _ffmpeg_path_arg(p: Path) -> str:
    """ffmpeg-safe path string (forward slashes, no escapes)."""
    return str(p).replace("\\", "/")


def mix_audio(voice: Path, out: Path, bgm: Path | None = None,
              hook_sfx: Path | None = None) -> float:
    """Mix voice with optional BGM (sidechain-ducked) and optional Hook SFX (prepended).

    Output structure when both BGM and SFX present:
      [silence 0.3s][hook_sfx][gap 0.2s][voice]
        all of the above mixed with [bgm_looped at -18dB, ducked to -30dB when voice signal]

    Returns the leading offset in seconds (silence + sfx duration + gap) so caller
    can shift timing.json. Returns 0.0 when no SFX is added.
    """
    voice_dur = get_duration(voice)

    # Case 1: no BGM and no SFX → just copy voice through
    if not bgm and not hook_sfx:
        if voice != out:
            import shutil
            shutil.copy(voice, out)
        return 0.0

    # Build leading audio: silence + sfx + gap (only if sfx provided)
    # SFX hard-capped to SFX_MAX_DUR_S so a full song dropped in sfx/hook/ can't inflate output
    leading_offset = 0.0
    sfx_dur        = 0.0
    if hook_sfx:
        raw_sfx_dur = get_duration(hook_sfx)
        sfx_dur = min(raw_sfx_dur, SFX_MAX_DUR_S)
        if raw_sfx_dur > SFX_MAX_DUR_S:
            print(f"      ⚠️  SFX {hook_sfx.name} 太長 ({raw_sfx_dur:.1f}s)，截取前 {SFX_MAX_DUR_S}s")
        leading_offset = LEADING_SILENCE_S + sfx_dur + SFX_BGM_GAP_S

    total_dur = leading_offset + voice_dur

    # Build ffmpeg filter graph
    cmd = [FFMPEG, "-y"]

    # Voice always input 0
    cmd += ["-i", _ffmpeg_path_arg(voice)]
    voice_idx = 0

    if hook_sfx:
        cmd += ["-i", _ffmpeg_path_arg(hook_sfx)]
        sfx_idx = 1
        next_idx = 2
    else:
        sfx_idx = None
        next_idx = 1

    if bgm:
        cmd += ["-stream_loop", "-1", "-i", _ffmpeg_path_arg(bgm)]
        bgm_idx = next_idx
    else:
        bgm_idx = None

    # Build filter
    filter_parts: list[str] = []

    if hook_sfx:
        # Silence(0.3s) + sfx(trimmed to SFX_MAX_DUR_S) + silence(0.2s) + voice → [vfull]
        filter_parts.append(
            f"[{sfx_idx}:a]atrim=0:{sfx_dur},asetpts=PTS-STARTPTS[sfxtrim];"
            f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={LEADING_SILENCE_S}[s1];"
            f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={SFX_BGM_GAP_S}[s2];"
            f"[s1][sfxtrim][s2][{voice_idx}:a]concat=n=4:v=0:a=1[vfull]"
        )
        voice_label = "vfull"
    else:
        voice_label = f"{voice_idx}:a"

    if bgm:
        # BGM trimmed to total_dur, lowered to BGM_BASE_DB, sidechain-ducked by voice
        filter_parts.append(
            f"[{bgm_idx}:a]atrim=0:{total_dur},volume={BGM_BASE_DB}dB[bgmraw];"
            f"[{voice_label}]asplit=2[vmain][vsc];"
            f"[bgmraw][vsc]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300:makeup=1[bgmducked];"
            f"[vmain][bgmducked]amix=inputs=2:duration=first:dropout_transition=0[mixout]"
        )
        out_label = "mixout"
    else:
        # Just the (silence+sfx+voice) chain
        out_label = voice_label

    filter_complex = ";".join(filter_parts) if filter_parts else None
    if filter_complex:
        cmd += ["-filter_complex", filter_complex, "-map", f"[{out_label}]"]
    else:
        cmd += ["-map", f"{voice_idx}:a"]

    cmd += ["-c:a", "libmp3lame", "-b:a", "192k", _ffmpeg_path_arg(out)]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"      ⚠️  ffmpeg mix 失敗，fallback 純人聲: {r.stderr[-200:]}")
        # Fallback: just copy voice
        import shutil
        shutil.copy(voice, out)
        return 0.0
    return leading_offset


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

def text_to_speech(text: str, out_path: Path, voice_id: str | None = None) -> None:
    if not API_KEY:
        raise RuntimeError("❌ 缺少 FISH_AUDIO_API_KEY")
    use_voice = voice_id or DEFAULT_VOICE_ID
    if not use_voice:
        raise RuntimeError("❌ 缺少 FISH_AUDIO_VOICE_ID（或 strategy 對應的 voice）")

    session = Session(API_KEY)
    chunks  = []
    for chunk in session.tts(TTSRequest(
        reference_id = use_voice,
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
    strategy = (data.get("strategy") or "").lower()
    voice_id = resolve_voice_id(strategy)
    audio_metadata: list[dict] = []

    voice_label = strategy or "default"
    print(f"🎙️  生成 {len(items)} 則語音（Fish Audio · {voice_label} voice）...")

    for i, item in enumerate(items, 1):
        combined = AUDIO_DIR / f"audio_{i:02d}.mp3"
        timing_f = AUDIO_DIR / f"audio_{i:02d}_timing.json"

        if combined.exists() and timing_f.exists():
            print(f"  [{i}] 已存在，跳過")
            continue

        # Pick script per version; legacy jobs use 'script'; dual-version uses script_short/long
        if VERSION == "short":
            script = item.get("script_short") or item.get("script") or item.get("summary", "")
        elif VERSION == "long":
            script = item.get("script_long")  or item.get("script") or item.get("summary", "")
        else:
            script = item.get("script") or item.get("summary", "")
        sentences = split_sentences(script)
        print(f"  [{i}] {item['title']} — {len(sentences)} 句...")

        sent_files = []
        timings    = []
        t_cursor   = 0.0

        for j, sent in enumerate(sentences, 1):
            sp = AUDIO_DIR / f"audio_{i:02d}_s{j:02d}.mp3"
            print(f"      句{j}: {sent[:30]}...")
            text_to_speech(sent, sp, voice_id=voice_id)
            dur = get_duration(sp)
            timings.append({"text": sent, "start": t_cursor, "end": t_cursor + dur})
            t_cursor += dur
            sent_files.append(sp)

        # Step A: concat sentences into raw narration (intermediate file)
        raw_voice = AUDIO_DIR / f"audio_{i:02d}_voice.mp3"
        if len(sent_files) == 1:
            sent_files[0].rename(raw_voice)
        else:
            concat_mp3(sent_files, raw_voice)
            for sp in sent_files:
                sp.unlink(missing_ok=True)

        # Step B: mix with BGM + SFX (or pass through if no assets)
        emotion = (item.get("emotion") or "").lower()
        bgm     = pick_bgm(emotion)
        sfx     = pick_hook_sfx(emotion)
        offset  = mix_audio(raw_voice, combined, bgm=bgm, hook_sfx=sfx)

        # Cleanup intermediate file
        raw_voice.unlink(missing_ok=True)

        # Step C: shift timing.json by leading_offset (if SFX prepended)
        if offset > 0:
            timings = [
                {"text": t["text"],
                 "start": t["start"] + offset,
                 "end":   t["end"]   + offset}
                for t in timings
            ]

        timing_f.write_text(
            json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        bgm_label = bgm.name if bgm else "(no BGM)"
        sfx_label = sfx.name if sfx else "(no SFX)"
        print(f"      ✅ {combined.name}（BGM={bgm_label}, SFX={sfx_label}, +{offset:.1f}s offset）")
        audio_metadata.append({
            "index":    i,
            "bgm":      bgm.name if bgm else None,
            "sfx":      sfx.name if sfx else None,
            "offset":   round(offset, 2),
            "duration": round(get_duration(combined), 2),
        })

    # Write audio metadata summary for UI display
    meta_file = AUDIO_DIR / "audio_metadata.json"
    meta_file.write_text(
        json.dumps({
            "voice_strategy": strategy or "",
            "voice_id_used":  voice_id,
            "items":          audio_metadata,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"📋 Audio metadata: {meta_file.name}")

    print(f"\n✅ 語音已存至 {AUDIO_DIR}")


if __name__ == "__main__":
    main()
