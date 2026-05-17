#!/usr/bin/env python3
"""
Lecture composer — reels-style energy edition.

Inspired by the AutoVideo short-form pipeline (1080×1920 reels):
  - Bold ASS subtitles burned in (fade-in/out per chunk, drop shadow, JhengHei)
  - Subtle Ken Burns zoom on each slide (eval=frame)
  - Mascot (assets/brand/mascot.png) bottom-right watermark
  - 0.4s fade-in + fade-out on each segment (visual + audio)
  - BGM picked from assets/music/generic/, sidechain-ducked under voice (~12% loud)

Strategy (unchanged from v1): build per-segment MP4 then concat-demuxer.
Per-segment filters keep filter_complex graph small + memory-safe.

Output: 1920×1080 30fps H.264 + AAC, suitable for upload / Supabase.
"""
import argparse
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Constants ─────────────────────────────────────────────────────────
WIDTH, HEIGHT, FPS = 1920, 1080, 30

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ASSETS_DIR = REPO_ROOT / "assets"
MASCOT_PATH = ASSETS_DIR / "brand" / "mascot.png"
GENERIC_BGM_DIR = ASSETS_DIR / "music" / "generic"

# Subtitle styling — reels-style bold + outline + shadow (no box; clean look)
FONT_ZH = r"C:/Windows/Fonts/msjhbd.ttc"  # Microsoft JhengHei Bold
SUB_FONT_NAME = "Microsoft JhengHei"
SUB_FONT_SIZE = 72                   # bold ~7% of 1080
SUB_MARGIN_V = 80                    # px from bottom
SUB_PRIMARY = "&H00FFFFFF"           # white text (BGRA, AA=00 → opaque)
SUB_OUTLINE = "&H00000000"           # opaque black outline
SUB_BACK = "&H00000000"              # shadow colour (opaque black)
SUB_BORDER_STYLE = 1                 # 1=outline + drop shadow (no opaque box)
SUB_OUTLINE_W = 3                    # outline thickness
SUB_SHADOW_W = 2                     # offset shadow for depth

# Animation parameters
FADE_DUR = 0.4                       # segment fade-in/out
ZOOM_FACTOR_MAX = 1.05               # subtle Ken Burns end zoom
MASCOT_WIDTH = 140                   # mascot width in final composite
MASCOT_MARGIN = 36                   # px from edge

# BGM mixing (calmer than short-form because narration is denser)
BGM_BASE_DB = -22                    # resting BGM level
BGM_DUCK_THRESHOLD = 0.05
BGM_DUCK_RATIO = 8
BGM_MAKEUP = 1


def find_ffmpeg() -> str:
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    for root, _, files in os.walk(winget_base):
        for f in files:
            if f.lower() == "ffmpeg.exe":
                return str(Path(root) / "ffmpeg.EXE")
    raise RuntimeError("ffmpeg not found")


def find_ffprobe() -> str:
    if shutil.which("ffprobe"):
        return "ffprobe"
    winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    for root, _, files in os.walk(winget_base):
        for f in files:
            if f.lower() == "ffprobe.exe":
                return str(Path(root) / "ffprobe.EXE")
    raise RuntimeError("ffprobe not found")


FFMPEG = find_ffmpeg()
FFPROBE = find_ffprobe()


def _to_path(p) -> str:
    return str(p).replace("\\", "/")


def _ffmpeg_filter_path(p) -> str:
    """Escape Windows path for use *inside* a filter string (e.g. subtitles=)."""
    s = _to_path(p)
    # Escape colon after drive letter so libass/subtitles= doesn't split on it
    if len(s) >= 2 and s[1] == ":":
        s = s[0] + r"\:" + s[2:]
    return s


def get_duration(path: Path) -> float:
    r = subprocess.run([
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        _to_path(path),
    ], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


# ── Subtitle generation ───────────────────────────────────────────────

def _split_sentences(text: str, max_chars: int = 22) -> list[str]:
    """Split narration into subtitle-friendly chunks.

    Stage 1: split on 。！？ then ， 、 ；
    Stage 2: any chunk > max_chars → hard wrap at max_chars (rare).
    """
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[。！？])\s*", text)
    parts = [p.strip() for p in parts if p.strip()]

    refined: list[str] = []
    for p in parts:
        if len(p) <= max_chars:
            refined.append(p)
            continue
        sub = re.split(r"(?<=[，、；,;])\s*", p)
        sub = [s.strip() for s in sub if s.strip()]
        for s in sub:
            if len(s) <= max_chars:
                refined.append(s)
            else:
                # Hard wrap
                for i in range(0, len(s), max_chars):
                    refined.append(s[i:i + max_chars])
    return refined


def _ass_ts(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def make_segment_ass(narration: str, audio_dur: float, slide_dur: float,
                     out_path: Path) -> bool:
    """Write an ASS subtitle file for this segment.

    Returns True if any subtitle events were written, False if narration empty.
    Times are local to the segment (start at 0).
    Subtitle chunks are spread proportionally across the *audio* portion only,
    not the trailing silence — so subtitles end when the voice ends.
    """
    chunks = _split_sentences(narration)
    if not chunks:
        return False

    # Distribute across audio duration proportional to chunk char count
    total_chars = sum(len(c) for c in chunks) or 1
    cursor = 0.0
    spans: list[tuple[float, float, str]] = []
    # Keep a tiny pad so first sub doesn't pop at exactly t=0 (looks weird with fade)
    pad_in = min(0.15, audio_dur * 0.05)
    usable = max(0.5, audio_dur - pad_in)
    cursor = pad_in
    for chunk in chunks:
        share = (len(chunk) / total_chars) * usable
        start = cursor
        end = min(cursor + share, audio_dur)
        spans.append((start, end, chunk))
        cursor = end

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {WIDTH}\n"
        f"PlayResY: {HEIGHT}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{SUB_FONT_NAME},{SUB_FONT_SIZE},{SUB_PRIMARY},&H000000FF,"
        f"{SUB_OUTLINE},{SUB_BACK},1,0,0,0,100,100,2,0,"
        f"{SUB_BORDER_STYLE},{SUB_OUTLINE_W},{SUB_SHADOW_W},"
        f"2,80,80,{SUB_MARGIN_V},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for start, end, chunk in spans:
        # \fad(in_ms,out_ms) for soft fade. Pop-in pop-out felt too aggressive here.
        events.append(
            f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Sub,,0,0,0,,"
            f"{{\\fad(180,120)}}{chunk}"
        )

    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return True


# ── Per-segment build ─────────────────────────────────────────────────

def _build_segment(slide_png: Path, audio_mp3: Path | None, slide_dur: float,
                   audio_dur: float, narration: str, out_mp4: Path,
                   subs_dir: Path) -> None:
    """Build one segment with reels-style polish.

    Filter graph:
      [0:v] image  → scale → fps → zoompan (ken-burns) → fade → [v0]
      [1:v] mascot → scale to MASCOT_WIDTH → [m]
      [v0][m]  overlay (bottom-right) → subtitles → [vout]
      [2:a] audio (or silence) → apad to slide_dur → afade → [aout]
    """
    has_audio = audio_mp3 is not None
    fade_out_start = max(0.0, slide_dur - FADE_DUR)

    # Total frames for zoompan (so we can compute zoom progress)
    total_frames = max(int(slide_dur * FPS), 1)
    # zoompan formula: zoom slowly from 1.0 → ZOOM_FACTOR_MAX over total_frames
    z_expr = f"min(zoom+0.0008,{ZOOM_FACTOR_MAX})"

    # Subtitle build
    subs_dir.mkdir(parents=True, exist_ok=True)
    ass_path = subs_dir / f"{out_mp4.stem}.ass"
    have_subs = False
    if has_audio and narration:
        have_subs = make_segment_ass(narration, audio_dur, slide_dur, ass_path)

    # Build filter_complex
    # Note on zoompan: it operates frame-by-frame; we feed a static image looped at FPS.
    # zoompan output size: z stays at 1, so image is upsampled. We scale image larger
    # before zoompan to keep effective resolution (avoid blur from upscaling small px).
    pre_w = int(WIDTH * 1.2)   # 20% extra room for ken-burns
    pre_h = int(HEIGHT * 1.2)

    parts = []
    # Stay in RGB through subtitle render (libass writes 8-bit RGBA; YUV
    # conversion afterwards avoids Y-channel clipping that grays out white text).
    parts.append(
        f"[0:v]scale={pre_w}:{pre_h}:force_original_aspect_ratio=increase,"
        f"crop={pre_w}:{pre_h},setsar=1,fps={FPS},"
        f"zoompan=z='{z_expr}':d=1:s={WIDTH}x{HEIGHT}:fps={FPS}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'[v0]"
    )

    # Mascot watermark (input 1) — preserve alpha
    parts.append(
        f"[1:v]scale={MASCOT_WIDTH}:-1[m]"
    )

    # Overlay mascot bottom-right
    overlay_x = WIDTH - MASCOT_WIDTH - MASCOT_MARGIN
    # Mascot height after scale ≈ 164px (mascot is 848x993 → 140x163.9)
    overlay_y = HEIGHT - 165 - MASCOT_MARGIN
    parts.append(
        f"[v0][m]overlay={overlay_x}:{overlay_y}:format=auto[v1]"
    )

    # Subtitles (still in RGB)
    if have_subs:
        sub_path = _ffmpeg_filter_path(ass_path)
        fonts_dir = _ffmpeg_filter_path("C:/Windows/Fonts")
        parts.append(
            f"[v1]subtitles='{sub_path}':fontsdir='{fonts_dir}'[v2]"
        )
        last_v = "v2"
    else:
        last_v = "v1"

    # Fade-in + fade-out, then convert to yuv420p for libx264
    parts.append(
        f"[{last_v}]fade=t=in:st=0:d={FADE_DUR:.2f},"
        f"fade=t=out:st={fade_out_start:.2f}:d={FADE_DUR:.2f},"
        f"format=yuv420p[vout]"
    )

    # Audio: pad voice to slide_dur, fade in/out
    if has_audio:
        parts.append(
            f"[2:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad,atrim=0:{slide_dur:.3f},asetpts=N/SR/TB,"
            f"afade=t=in:st=0:d={FADE_DUR:.2f},"
            f"afade=t=out:st={fade_out_start:.2f}:d={FADE_DUR:.2f}[aout]"
        )
    else:
        parts.append(
            f"anullsrc=channel_layout=stereo:sample_rate=44100:d={slide_dur:.3f}[aout]"
        )

    filter_complex = ";".join(parts)

    # Inputs: 0 = slide, 1 = mascot. Audio input added conditionally as 2.
    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-framerate", str(FPS), "-t", f"{slide_dur:.3f}",
        "-i", _to_path(slide_png),
        "-loop", "1", "-i", _to_path(MASCOT_PATH),
    ]
    if has_audio:
        cmd += ["-i", _to_path(audio_mp3)]
    else:
        # Use lavfi anullsrc as input 2 so filter graph stays consistent;
        # but our parts above uses anullsrc inside filter_complex, so no extra input needed.
        # We must still NOT have ref to [2:a] though.
        pass

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{slide_dur:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        _to_path(out_mp4),
    ]

    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg seg build failed for {out_mp4.name}\n"
            f"--- cmd ---\n{' '.join(cmd)}\n"
            f"--- stderr ---\n{r.stderr[-3000:]}"
        )


# ── Concat + BGM mix ──────────────────────────────────────────────────

def _concat(parts: list[Path], out_mp4: Path) -> None:
    """Concat-demuxer all part files. Re-encode for clean timestamps."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for p in parts:
            abs_p = Path(p).resolve()
            f.write(f"file '{_to_path(abs_p)}'\n")
        list_file = f.name
    try:
        cmd = [
            FFMPEG, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            _to_path(out_mp4),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"concat failed:\n{r.stderr[-2000:]}")
    finally:
        Path(list_file).unlink(missing_ok=True)


def _pick_lecture_bgm() -> Path | None:
    """Pick a calm BGM track from assets/music/generic/.

    Lecture-friendly = piano / corporate / ambient (not phonk/aggressive).
    """
    if not GENERIC_BGM_DIR.exists():
        return None
    candidates = [p for p in GENERIC_BGM_DIR.iterdir()
                  if p.suffix.lower() in {".mp3", ".m4a", ".wav"}]
    if not candidates:
        return None
    # Prefer piano/calm titles deterministically: sort, pick first
    candidates.sort(key=lambda p: p.name.lower())
    # Prefer "piano" if available, else "background", else "technology"
    for kw in ("piano", "background", "technology"):
        for p in candidates:
            if kw in p.name.lower():
                return p
    return candidates[0]


def _mix_bgm(merged: Path, bgm: Path, out: Path) -> None:
    """Mix BGM (looped) under voice with sidechain ducking — same trick as
    scripts/audio_generator.py.
    """
    total_dur = get_duration(merged)
    fc = (
        f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{total_dur:.3f},"
        f"volume={BGM_BASE_DB}dB,"
        f"afade=t=in:st=0:d=1.5,"
        f"afade=t=out:st={max(0, total_dur-1.8):.3f}:d=1.8[bgmraw];"
        f"[0:a]asplit=2[vmain][vsc];"
        f"[bgmraw][vsc]sidechaincompress=threshold={BGM_DUCK_THRESHOLD}:"
        f"ratio={BGM_DUCK_RATIO}:attack=20:release=350:makeup={BGM_MAKEUP}[bgmducked];"
        f"[vmain][bgmducked]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )
    cmd = [
        FFMPEG, "-y",
        "-i", _to_path(merged),
        "-stream_loop", "-1", "-i", _to_path(bgm),
        "-filter_complex", fc,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        _to_path(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"BGM mix failed:\n{r.stderr[-2000:]}")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True,
                    help="<lesson>.segments.final.json from lecture_tts.py")
    ap.add_argument("--parts-dir", required=True,
                    help="Where to write per-segment mp4 parts (cached)")
    ap.add_argument("--out", required=True, help="Final mp4 path")
    ap.add_argument("--no-bgm", action="store_true",
                    help="Skip BGM mixing (voice-only, faster)")
    ap.add_argument("--no-mascot", action="store_true",
                    help="Skip mascot watermark")
    args = ap.parse_args()

    if not MASCOT_PATH.exists() and not args.no_mascot:
        print(f"⚠️  mascot not found at {MASCOT_PATH}, "
              "rendering without watermark", flush=True)

    data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    segments = data["segments"]

    parts_dir = Path(args.parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)
    subs_dir = parts_dir / "_subs"

    parts: list[Path] = []
    total_dur = 0.0
    for i, seg in enumerate(segments):
        slide_png = Path(seg["_slide_png"])
        audio_mp3 = Path(seg["_audio_mp3"]) if seg.get("_audio_mp3") else None
        audio_dur = float(seg.get("_audio_dur") or 0.0)
        slide_dur = float(seg.get("_slide_dur") or audio_dur or 3.0)
        if slide_dur < 1.0:
            slide_dur = 1.0
        narration = (seg.get("narration") or "").strip()
        out_part = parts_dir / f"part_{i:03d}.mp4"

        if out_part.exists() and out_part.stat().st_size > 0:
            print(f"  [{i:03d}] cached part ({slide_dur:.1f}s)")
        else:
            print(f"  [{i:03d}] {seg.get('kind','?'):<11} → {out_part.name} "
                  f"({slide_dur:.1f}s, subs={'y' if narration else 'n'})")
            _build_segment(
                slide_png=slide_png,
                audio_mp3=audio_mp3,
                slide_dur=slide_dur,
                audio_dur=audio_dur,
                narration=narration,
                out_mp4=out_part,
                subs_dir=subs_dir,
            )
        parts.append(out_part)
        total_dur += slide_dur

    print(f"\nConcatenating {len(parts)} parts → merged "
          f"(~{total_dur/60:.1f} min)")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # If BGM enabled: concat to intermediate, then mix BGM into final
    if args.no_bgm:
        _concat(parts, out)
    else:
        bgm = _pick_lecture_bgm()
        if bgm is None:
            print("  ⚠️  no BGM track in assets/music/generic/, skipping mix")
            _concat(parts, out)
        else:
            print(f"  🎵 BGM: {bgm.name}")
            tmp_merged = parts_dir / "_merged_voiceonly.mp4"
            _concat(parts, tmp_merged)
            _mix_bgm(tmp_merged, bgm, out)
            tmp_merged.unlink(missing_ok=True)

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"\n✅ {out}  ({size_mb:.1f} MB, {total_dur:.1f}s ≈ "
          f"{total_dur/60:.1f} min)")


if __name__ == "__main__":
    main()
