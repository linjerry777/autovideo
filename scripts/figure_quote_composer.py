#!/usr/bin/env python3
"""Composer for figure quote Shorts.

This renderer is intentionally separate from video_composer.py. Figure quote
videos need the speaker's original audio first, then the AI narration analysis;
the regular news renderer treats video as silent B-roll.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
TODAY = sys.argv[1] if len(sys.argv) > 1 else "2026-05-13/figure_preview_tech"
PIPE_DIR = BASE_DIR / "pipeline" / TODAY
NEWS_FILE = PIPE_DIR / "news.json"
AUDIO_DIR = PIPE_DIR / "audio"
BROLL_DIR = PIPE_DIR / "broll"
SEG_DIR = PIPE_DIR / "figure_segments"
OUTPUT = PIPE_DIR / "output.mp4"

W, H = 1080, 1920
FONT_ZH = Path("C:/Windows/Fonts/msjh.ttc")
AUDIO_RATE = "48000"
AUDIO_CHANNELS = "2"


def find_ffmpeg() -> tuple[str, str]:
    if shutil.which("ffmpeg"):
        return "ffmpeg", "ffprobe"
    for root in [Path("C:/ffmpeg"), Path("C:/Program Files"), Path("C:/tools")]:
        if not root.exists():
            continue
        for f in root.rglob("ffmpeg.exe"):
            return str(f), str(f.with_name("ffprobe.exe"))
    raise RuntimeError("ffmpeg not found")


FFMPEG, FFPROBE = find_ffmpeg()


def run(cmd: list[str], desc: str) -> None:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1200,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{desc} failed:\n{result.stderr[-1200:]}")


def get_duration(path: Path) -> float:
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def ff_filter_path(path: Path | str) -> str:
    p = str(path).replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = p[0] + "\\:" + p[2:]
    return p


def ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return str(text).replace("{", "(").replace("}", ")").replace("\n", r"\N")


def wrap_zh(text: str, width: int = 12, max_lines: int = 3) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    if not text:
        return ""
    if re.search(r"[\u4e00-\u9fff]", text):
        chunks = [text[i : i + width] for i in range(0, len(text), width)]
    else:
        words = text.split()
        chunks: list[str] = []
        line = ""
        for word in words:
            next_line = word if not line else f"{line} {word}"
            if len(next_line) > width + 8 and line:
                chunks.append(line)
                line = word
            else:
                line = next_line
        if line:
            chunks.append(line)
    if len(chunks) > max_lines:
        chunks = chunks[: max_lines - 1] + ["".join(chunks[max_lines - 1 :])]
    return r"\N".join(chunks[:max_lines])


def make_ass(events: list[tuple[float, float, str, str]], out_path: Path) -> None:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Quote,Microsoft JhengHei,70,&H0000F7FF,&H000000FF,&H00101010,&HAA000000,1,0,0,0,100,100,0,0,1,5,1,2,70,70,260,1
Style: Main,Microsoft JhengHei,60,&H00FFFFFF,&H000000FF,&H00111111,&HAA000000,1,0,0,0,100,100,0,0,1,5,1,2,70,70,230,1
Style: Tag,Microsoft JhengHei,44,&H00C8FF32,&H000000FF,&H00111111,&H66000000,1,0,0,0,100,100,0,0,1,4,1,8,60,60,120,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = []
    for start, end, text, style in events:
        if end <= start or not str(text).strip():
            continue
        lines.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{ass_escape(text)}"
        )
    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def parse_transcript_lines(text: str) -> list[tuple[float, float, str]]:
    rows: list[tuple[float, float, str]] = []
    for match in re.finditer(r"\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\]\s*(.+)", text or ""):
        rows.append((float(match.group(1)), float(match.group(2)), match.group(3).strip()))
    return rows


def quote_focus_abs(item: dict) -> float | None:
    quote = (item.get("quote_original") or "").lower()
    words = re.findall(r"[a-zA-Z']+", quote)
    keywords = [w for w in words if len(w) >= 4]
    phrases = [" ".join(keywords[i : i + 2]) for i in range(max(0, len(keywords) - 1))]
    phrases += keywords
    for start, _end, line in parse_transcript_lines(item.get("transcript_window") or ""):
        lowered = line.lower()
        if any(p and p in lowered for p in phrases):
            return start
    return None


def build_video_filter(ass_path: Path, hook_path: Path, mood: str = "quote") -> str:
    if mood == "analysis":
        video = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},eq=brightness=-0.06:saturation=1.08[base]"
        )
    else:
        video = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},eq=brightness=-0.03:saturation=1.08[base]"
        )
    top = f"[base]drawbox=x=0:y=0:w={W}:h=168:color=black@0.62:t=fill[top]"
    hook = (
        f"[top]drawtext=fontfile='{ff_filter_path(FONT_ZH)}':"
        f"textfile='{ff_filter_path(hook_path)}':"
        f"fontsize=60:fontcolor=#F8D84A:"
        f"x=(w-text_w)/2:y=54:"
        f"shadowcolor=black@0.9:shadowx=3:shadowy=3[hook]"
    )
    subs = (
        f"[hook]subtitles='{ff_filter_path(ass_path)}':"
        f"fontsdir='{ff_filter_path('C:/Windows/Fonts')}'[v]"
    )
    return ";".join([video, top, hook, subs])


def render_speaker_part(item: dict, broll: Path, out_path: Path, tmp_dir: Path) -> float:
    clip_start = float(item.get("clip_start") or 0)
    broll_origin = max(0.0, clip_start - 2.0)
    focus_abs = quote_focus_abs(item) or clip_start
    local_start = max(0.0, focus_abs - broll_origin - 2.0)
    broll_dur = get_duration(broll)
    duration = min(14.0, max(8.0, broll_dur - local_start))

    hook_path = tmp_dir / "speaker_hook.txt"
    hook_path.write_text(item.get("hook") or item.get("title") or "重點來了", encoding="utf-8")
    ass_path = tmp_dir / "speaker.ass"
    quote = wrap_zh(item.get("quote_zh") or item.get("quote_original") or "", width=11)
    make_ass([(0.65, duration - 0.35, quote, "Quote")], ass_path)
    filters = build_video_filter(ass_path, hook_path, "quote")

    run(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{local_start:.3f}",
            "-i",
            str(broll),
            "-t",
            f"{duration:.3f}",
            "-filter_complex",
            filters,
            "-map",
            "[v]",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            AUDIO_RATE,
            "-ac",
            AUDIO_CHANNELS,
            "-r",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(out_path),
        ],
        "render speaker quote part",
    )
    return duration


def render_analysis_part(item: dict, broll: Path, audio: Path, out_path: Path, tmp_dir: Path) -> float:
    audio_dur = get_duration(audio)
    hook_path = tmp_dir / "analysis_hook.txt"
    hook_path.write_text("為什麼這句話重要", encoding="utf-8")

    timing_path = audio.with_name(audio.stem + "_timing.json")
    events: list[tuple[float, float, str, str]] = []
    if timing_path.exists():
        timing = json.loads(timing_path.read_text(encoding="utf-8"))
        for row in timing:
            events.append(
                (
                    float(row.get("start") or 0),
                    min(float(row.get("end") or audio_dur), audio_dur),
                    wrap_zh(row.get("text") or "", width=12, max_lines=2),
                    "Main",
                )
            )
    else:
        events.append((0.2, max(0.5, audio_dur - 0.3), wrap_zh(item.get("script") or "", 12, 3), "Main"))

    ass_path = tmp_dir / "analysis.ass"
    make_ass(events, ass_path)
    filters = build_video_filter(ass_path, hook_path, "analysis")

    run(
        [
            FFMPEG,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(broll),
            "-i",
            str(audio),
            "-t",
            f"{audio_dur:.3f}",
            "-filter_complex",
            filters,
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            AUDIO_RATE,
            "-ac",
            AUDIO_CHANNELS,
            "-r",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(out_path),
        ],
        "render analysis part",
    )
    return audio_dur


def concat(parts: list[Path], out_path: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as list_file:
        for part in parts:
            list_file.write(f"file '{str(part).replace(chr(92), '/')}'\n")
        list_path = Path(list_file.name)
    try:
        result = subprocess.run(
            [
                FFMPEG,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        if result.returncode == 0:
            return
        run(
            [
                FFMPEG,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                str(out_path),
            ],
            "concat figure quote parts",
        )
    finally:
        list_path.unlink(missing_ok=True)


def main() -> None:
    if not NEWS_FILE.exists():
        raise FileNotFoundError(NEWS_FILE)
    data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data.get("items") or []
    if not items:
        raise RuntimeError("news.json has no items")

    SEG_DIR.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="figure_quote_") as td:
        tmp_dir = Path(td)
        for i, item in enumerate(items, 1):
            broll = BROLL_DIR / f"broll_{i:02d}.mp4"
            audio = AUDIO_DIR / f"audio_{i:02d}.mp3"
            if not broll.exists():
                raise FileNotFoundError(broll)
            if not audio.exists():
                raise FileNotFoundError(audio)
            speaker = SEG_DIR / f"speaker_{i:02d}.mp4"
            analysis = SEG_DIR / f"analysis_{i:02d}.mp4"
            print(f"[{i}] render speaker original audio first")
            render_speaker_part(item, broll, speaker, tmp_dir)
            print(f"[{i}] render narration analysis")
            render_analysis_part(item, broll, audio, analysis, tmp_dir)
            parts.extend([speaker, analysis])

    print("concat figure quote output")
    concat(parts, OUTPUT)
    print(f"done: {OUTPUT}")


if __name__ == "__main__":
    main()
