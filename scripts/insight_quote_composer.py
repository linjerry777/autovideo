#!/usr/bin/env python3
"""Quote + DORO insight composer.

Builds the format Jerry asked for:
1. original speaker quote, with bilingual subtitles
2. DORO-style Chinese analysis, without the generic quote-account logo
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import argparse
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
_parser = argparse.ArgumentParser()
_parser.add_argument("job_key", nargs="?", default="2026-05-13/figure_preview_tech")
_parser.add_argument("--version", choices=["short", "long"], default=None)
_args, _unknown = _parser.parse_known_args()

JOB_KEY = _args.job_key
VERSION = _args.version
PIPE_DIR = BASE_DIR / "pipeline" / JOB_KEY
VERSION_DIR = PIPE_DIR / VERSION if VERSION else PIPE_DIR
NEWS_FILE = PIPE_DIR / "news.json"
BROLL = PIPE_DIR / "broll" / "broll_01.mp4"
AUDIO_DIR = VERSION_DIR / "audio"
ANALYSIS_AUDIO = AUDIO_DIR / "audio_01.mp3"
ANALYSIS_TIMING = AUDIO_DIR / "audio_01_timing.json"
SEG_DIR = VERSION_DIR / "insight_segments"
OUTPUT = VERSION_DIR / "output.mp4"
PREVIEW_OUTPUT = VERSION_DIR / "insight_quote_output.mp4"
OUTRO_TEXT = "追蹤我，聽更多名人解析。"
OUTRO_AUDIO = BASE_DIR / "assets" / "audio" / "outro_follow_figure.mp3"
DORO_LOGO = BASE_DIR / "assets" / "brand" / "doro_insight_logo.png"

W, H = 1080, 1920
TOP_SAFE_SHIFT = 90
VIDEO_Y = 250 + TOP_SAFE_SHIFT
VIDEO_H = 1010
TITLE_Y1 = 190
TITLE_Y2 = 250
TOP_LOGO_Y = 190
ANALYSIS_HEADER_H = 235 + TOP_SAFE_SHIFT
ANALYSIS_TITLE_Y = 170
ANALYSIS_UNDERLINE_Y = 252
ANALYSIS_LOGO_Y = 170
AUDIO_RATE = "48000"
AUDIO_CHANNELS = "2"
FONT_ZH = Path("C:/Windows/Fonts/msjh.ttc")

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

FALLBACK_ZH = {
    "But like, honestly, the models are now so smart": "老實說，模型現在已經很聰明",
    "that for most of the things most people want to do,": "對多數人想做的事來說",
    "they're good enough.": "它們已經夠好了",
    "I hope that'll change over time": "我希望這會隨時間改變",
    "because people will raise their expectations.": "因為人們會提高期待",
    "But like, if you're kind of using ChatGPT as a standard user,": "但如果你只是一般使用者",
    "the model capability is very smart.": "模型能力已經很強",
    "But we have to build a great product,": "但我們必須打造偉大的產品",
    "not just a great model.": "而不只是偉大的模型",
    "And so there will be a lot of people with great models,": "所以很多人都會有很強的模型",
    "and we will try to build the best product.": "我們要做的是最好的產品",
}


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


def ff_path(path: Path | str) -> str:
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


def wrap_text(text: str, width: int, max_lines: int = 2) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    if not text:
        return ""
    if re.search(r"[\u4e00-\u9fff]", text):
        chunks = [text[i : i + width] for i in range(0, len(text), width)]
    else:
        chunks = []
        line = ""
        for word in text.split():
            candidate = word if not line else f"{line} {word}"
            if len(candidate) > width and line:
                chunks.append(line)
                line = word
            else:
                line = candidate
        if line:
            chunks.append(line)
    if len(chunks) > max_lines:
        chunks = chunks[: max_lines - 1] + [" ".join(chunks[max_lines - 1 :])]
    return r"\N".join(chunks[:max_lines])


def parse_transcript(text: str) -> list[dict]:
    cues = []
    for match in re.finditer(r"\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\]\s*(.+)", text or ""):
        cues.append({"start": float(match.group(1)), "end": float(match.group(2)), "text": match.group(3).strip()})
    return cues


def quote_focus_abs(item: dict, cues: list[dict]) -> float | None:
    quote = (item.get("quote_original") or "").lower()
    keywords = [w for w in re.findall(r"[a-zA-Z']+", quote) if len(w) >= 4]
    phrases = [" ".join(keywords[i : i + 2]) for i in range(max(0, len(keywords) - 1))]
    phrases += keywords
    for cue in cues:
        line = cue["text"].lower()
        if any(p and p in line for p in phrases):
            return cue["start"]
    return None


def zh_for(line: str) -> str:
    normalized = re.sub(r"\s+", " ", line).strip()
    if normalized in FALLBACK_ZH:
        return FALLBACK_ZH[normalized]
    lowered = normalized.lower()
    for key, value in FALLBACK_ZH.items():
        if key.lower() in lowered or lowered in key.lower():
            return value
    return normalized


def clean_subtitle_text(text: str, *, leading: bool = False) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if leading:
        text = text.lstrip("」』”)]）】〉》,，。；;：:、 ")
    return text


def needs_translation(text: str) -> bool:
    text = str(text or "")
    if not text.strip():
        return False
    return not re.search(r"[\u4e00-\u9fff]", text)


def translate_quote_captions(captions: list[dict]) -> list[dict]:
    targets = [cap["en"] for cap in captions if needs_translation(cap.get("zh"))]
    if not targets:
        return captions

    cache_path = PIPE_DIR / "quote_caption_zh.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    except Exception:
        cache = {}

    missing = [line for line in targets if line not in cache]
    if missing:
        try:
            from web.claude_client import call_claude

            prompt = """請把以下英文短影音字幕逐句翻成自然繁體中文，只輸出 JSON array。
規則：
- 輸出數量必須和輸入數量相同。
- 不要加解釋。
- 保留 AI、GitHub、ChatGPT 等產品名。
- 移除像 SATYA NADELLA: 這種說話者標籤，只翻真正內容。
- 每句控制在 22 個中文字以內，適合字幕。

英文字幕：
""" + json.dumps(missing, ensure_ascii=False, indent=2)
            raw, _usage = call_claude(prompt, timeout=180)
            match = re.search(r"\[[\s\S]*\]", raw or "")
            translated = json.loads(match.group(0)) if match else []
            if len(translated) == len(missing):
                for src, zh in zip(missing, translated):
                    cache[src] = clean_subtitle_text(str(zh))
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[WARN] quote caption translation failed: {exc}", file=sys.stderr)

    for cap in captions:
        if needs_translation(cap.get("zh")) and cap.get("en") in cache:
            cap["zh"] = cache[cap["en"]]
    return captions


def title_for(item: dict) -> str:
    figure = item.get("figure_name") or "科技大佬"
    if str(figure).lower().startswith("sam"):
        return "Sam Altman：模型不夠，產品才是勝負"
    return f"{figure}：{item.get('hook') or item.get('title') or '這句話值得聽'}"


def split_title_lines(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if "：" in text:
        left, right = text.split("：", 1)
        for sep in ("，", "：", " - ", " | "):
            if sep in right:
                a, b = right.split(sep, 1)
                return [f"{left}：{a}".strip(), b.strip()]
        if len(text) > 18:
            return [f"{left}：{right[:6]}".strip(), right[6:].strip()]
    if len(text) <= 18:
        return [text]
    return [text[:18], text[18:36]]


def make_quote_ass(captions: list[dict], out_path: Path) -> None:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Bilingual,Microsoft JhengHei,58,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,1,2,56,56,300,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = []
    for cap in captions:
        zh = ass_escape(wrap_text(cap["zh"], 16, 2))
        en = ass_escape(wrap_text(cap["en"], 34, 2))
        text = rf"{zh}\N{{\fs38\b0}}{en}"
        lines.append(f"Dialogue: 0,{ass_time(cap['start'])},{ass_time(cap['end'])},Bilingual,,0,0,0,,{text}")
    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def make_analysis_ass(rows: list[dict], offset: float, duration: float, out_path: Path) -> None:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Insight,Microsoft JhengHei,62,&H00FFFFFF,&H000000FF,&H00000000,&H90000000,1,0,0,0,100,100,0,0,1,5,1,2,70,70,285,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = []
    for row in rows:
        start = max(0.0, float(row.get("start") or 0) - offset)
        end = min(duration, max(start + 0.4, float(row.get("end") or 0) - offset))
        text_raw = clean_subtitle_text(row.get("text") or "", leading=start <= 0.08)
        text = ass_escape(wrap_text(text_raw, 13, 2))
        if text:
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Insight,,0,0,0,,{text}")
    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def quote_captions(item: dict, start_abs: float, duration: float, local_offset: float) -> list[dict]:
    captions = []
    end_abs = start_abs + duration
    for cue in parse_transcript(item.get("transcript_window") or ""):
        if cue["end"] < start_abs or cue["start"] > end_abs:
            continue
        start = max(0.0, cue["start"] - local_offset)
        end = min(duration, max(start + 0.5, cue["end"] - local_offset))
        en = clean_subtitle_text(cue["text"])
        captions.append({"start": start, "end": end, "zh": zh_for(en), "en": en})
    return translate_quote_captions(captions)


def render_quote_part(item: dict, out_path: Path, tmp: Path) -> float:
    cues = parse_transcript(item.get("transcript_window") or "")
    clip_start = float(item.get("clip_start") or 0)
    broll_origin = max(0.0, clip_start - 2.0)
    focus = quote_focus_abs(item, cues) or clip_start
    first_after_clip = next((c["start"] for c in cues if c["start"] >= clip_start), clip_start)
    start_abs = max(clip_start, min(first_after_clip, focus - 18.0))
    local_start = max(0.0, start_abs - broll_origin)
    local_offset = broll_origin + local_start
    duration = min(23.0, max(12.0, get_duration(BROLL) - local_start))

    title_lines = split_title_lines(title_for(item))
    title_1 = tmp / "quote_title_1.txt"
    title_2 = tmp / "quote_title_2.txt"
    title_1.write_text(title_lines[0] if title_lines else "", encoding="utf-8")
    title_2.write_text(title_lines[1] if len(title_lines) > 1 else "", encoding="utf-8")
    subs = tmp / "quote.ass"
    make_quote_ass(quote_captions(item, start_abs, duration, local_offset), subs)

    filters = [
            f"color=c=black:s={W}x{H}:r=30:d={duration:.3f}[canvas]",
            (
                f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},crop={W}:{VIDEO_H}:0:(ih-{VIDEO_H})/2,"
                f"eq=brightness=-0.02:saturation=1.05[main]"
            ),
            f"[canvas][main]overlay=0:{VIDEO_Y}[v0]",
            (
                f"[v0]drawtext=fontfile='{ff_path(FONT_ZH)}':textfile='{ff_path(title_1)}':"
                f"fontsize=58:fontcolor=#FFF03A:x=58:y={TITLE_Y1}:borderw=3:bordercolor=black[v1]"
            ),
            (
                f"[v1]drawtext=fontfile='{ff_path(FONT_ZH)}':textfile='{ff_path(title_2)}':"
                f"fontsize=58:fontcolor=#FFF03A:x=58:y={TITLE_Y2}:borderw=3:bordercolor=black[v2]"
            ),
    ]
    last = "v2"
    if DORO_LOGO.exists():
        filters += [
            f"[1:v]scale=72:72,format=rgba[logo]",
            f"[{last}][logo]overlay=W-w-54:{TOP_LOGO_Y}[v3]",
        ]
        last = "v3"
    filters.append(f"[{last}]subtitles='{ff_path(subs)}':fontsdir='{ff_path('C:/Windows/Fonts')}'[v]")
    cmd = [
            FFMPEG,
            "-y",
            "-ss",
            f"{local_start:.3f}",
            "-i",
            str(BROLL),
    ]
    if DORO_LOGO.exists():
        cmd += ["-loop", "1", "-i", str(DORO_LOGO)]
    cmd += [
            "-t",
            f"{duration:.3f}",
            "-filter_complex",
            ";".join(filters),
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
    ]
    run(cmd, "render quote part")
    return duration


def render_bridge_part(out_path: Path, tmp: Path) -> float:
    duration = 1.35
    title = tmp / "bridge_title.txt"
    subtitle = tmp / "bridge_subtitle.txt"
    title.write_text("這句話其實在講...", encoding="utf-8")
    subtitle.write_text("不是模型多強，而是產品怎麼被使用", encoding="utf-8")

    filters = [
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"boxblur=14:2,eq=brightness=-0.42:saturation=0.75[bg]",
        f"[bg]drawbox=x=0:y=0:w={W}:h={H}:color=black@0.22:t=fill[v0]",
        (
            f"[v0]drawtext=fontfile='{ff_path(FONT_ZH)}':textfile='{ff_path(title)}':"
            f"fontsize=78:fontcolor=#FFF03A:x=(w-text_w)/2:y=700:borderw=4:bordercolor=black[v1]"
        ),
        (
            f"[v1]drawtext=fontfile='{ff_path(FONT_ZH)}':textfile='{ff_path(subtitle)}':"
            f"fontsize=46:fontcolor=white:x=(w-text_w)/2:y=825:borderw=3:bordercolor=black[v2]"
        ),
    ]
    last = "v2"
    if DORO_LOGO.exists():
        filters += [
            f"[1:v]scale=112:112,format=rgba[logo]",
            f"[{last}][logo]overlay=(W-w)/2:520[v3]",
        ]
        last = "v3"
    filters.append(f"[{last}]fade=t=in:st=0:d=0.20,fade=t=out:st={duration - 0.25:.3f}:d=0.25[v]")

    cmd = [
        FFMPEG,
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(BROLL),
    ]
    audio_index = "1"
    if DORO_LOGO.exists():
        cmd += ["-loop", "1", "-i", str(DORO_LOGO)]
        audio_index = "2"
    cmd += [
        "-f",
        "lavfi",
        "-t",
        f"{duration:.3f}",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-t",
        f"{duration:.3f}",
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[v]",
        "-map",
        f"{audio_index}:a:0",
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
    ]
    run(cmd, "render bridge part")
    return duration


def analysis_start(rows: list[dict]) -> float:
    for row in rows:
        text = str(row.get("text") or "")
        if "意思" in text or "AI" in text:
            return float(row.get("start") or 0)
    return float(rows[2].get("start") or 0) if len(rows) > 2 else 0.0


def render_analysis_part(item: dict, out_path: Path, tmp: Path) -> float:
    rows = json.loads(ANALYSIS_TIMING.read_text(encoding="utf-8")) if ANALYSIS_TIMING.exists() else []
    start = analysis_start(rows)
    total = get_duration(ANALYSIS_AUDIO)
    duration = max(6.0, total - start)

    title = tmp / "analysis_title.txt"
    title.write_text("DORO 拆解：這句話在講什麼", encoding="utf-8")
    subs = tmp / "analysis.ass"
    make_analysis_ass(rows, start, duration, subs)

    filters = [
            f"color=c=black:s={W}x{H}:r=30:d={duration:.3f}[canvas]",
            (
                f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},crop={W}:{VIDEO_H}:0:(ih-{VIDEO_H})/2,"
                f"eq=brightness=-0.18:saturation=0.9[main]"
            ),
            f"[canvas][main]overlay=0:{VIDEO_Y}[v0]",
            f"[v0]drawbox=x=0:y=0:w={W}:h={ANALYSIS_HEADER_H}:color=black@0.90:t=fill[v1]",
            (
                f"[v1]drawtext=fontfile='{ff_path(FONT_ZH)}':textfile='{ff_path(title)}':"
                f"fontsize=56:fontcolor=#FFF03A:x=58:y={ANALYSIS_TITLE_Y}:borderw=3:bordercolor=black[v2]"
            ),
            f"[v2]drawbox=x=58:y={ANALYSIS_UNDERLINE_Y}:w=190:h=8:color=#FFF03A@0.95:t=fill[v3]",
    ]
    last = "v3"
    if DORO_LOGO.exists():
        filters += [
            f"[2:v]scale=88:88,format=rgba[logo]",
            f"[{last}][logo]overlay=W-w-54:{ANALYSIS_LOGO_Y}[v4]",
        ]
        last = "v4"
    filters += [
        f"[{last}]subtitles='{ff_path(subs)}':fontsdir='{ff_path('C:/Windows/Fonts')}'[vsub]",
        f"[vsub]fade=t=in:st=0:d=0.18[v]",
    ]
    cmd = [
            FFMPEG,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(BROLL),
            "-ss",
            f"{start:.3f}",
            "-i",
            str(ANALYSIS_AUDIO),
    ]
    if DORO_LOGO.exists():
        cmd += ["-loop", "1", "-i", str(DORO_LOGO)]
    cmd += [
            "-t",
            f"{duration:.3f}",
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-af",
            "afade=t=in:st=0:d=0.18",
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
    ]
    run(cmd, "render analysis part")
    return duration


def ensure_outro_audio() -> Path | None:
    if OUTRO_AUDIO.exists() and OUTRO_AUDIO.stat().st_size > 1000:
        return OUTRO_AUDIO
    api_key = os.getenv("FISH_AUDIO_API_KEY", "")
    voice_id = (
        os.getenv("FISH_AUDIO_VOICE_TECH", "")
        or os.getenv("FISH_AUDIO_VOICE_ID", "")
    )
    if not api_key or not voice_id:
        return None
    try:
        from fish_audio_sdk import Session, TTSRequest

        OUTRO_AUDIO.parent.mkdir(parents=True, exist_ok=True)
        session = Session(api_key)
        chunks = []
        for chunk in session.tts(TTSRequest(
            reference_id=voice_id,
            text=OUTRO_TEXT,
            format="mp3",
            mp3_bitrate=128,
            latency="normal",
        )):
            chunks.append(chunk)
        OUTRO_AUDIO.write_bytes(b"".join(chunks))
        return OUTRO_AUDIO if OUTRO_AUDIO.exists() else None
    except Exception as exc:
        print(f"[WARN] outro TTS failed: {exc}", file=sys.stderr)
        return None


def render_outro_part(out_path: Path, tmp: Path) -> float:
    audio = ensure_outro_audio()
    title = tmp / "outro_title.txt"
    subtitle = tmp / "outro_subtitle.txt"
    title.write_text("追蹤我", encoding="utf-8")
    subtitle.write_text("聽更多名人解析", encoding="utf-8")
    duration = max(3.35, min(4.25, get_duration(audio) + 1.0 if audio else 3.6))

    filters = [
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=18:3,eq=brightness=-0.45:saturation=0.65[bg]",
            f"[bg]drawbox=x=0:y=0:w={W}:h={H}:color=black@0.28:t=fill[v0]",
    ]
    last = "v0"
    if DORO_LOGO.exists():
        filters += [
            f"[2:v]scale=300:300,format=rgba[logo]",
            f"[{last}][logo]overlay=(W-w)/2:315[vlogo]",
        ]
        last = "vlogo"
    filters += [
            (
                f"[{last}]drawtext=fontfile='{ff_path(FONT_ZH)}':textfile='{ff_path(title)}':"
                f"fontsize=110:fontcolor=white:x=(w-text_w)/2:y=710:borderw=4:bordercolor=black[v2]"
            ),
            (
                f"[v2]drawtext=fontfile='{ff_path(FONT_ZH)}':textfile='{ff_path(subtitle)}':"
                f"fontsize=64:fontcolor=#FFF03A:x=(w-text_w)/2:y=875:borderw=3:bordercolor=black[v3]"
            ),
            f"[v3]fade=t=in:st=0:d=0.22,fade=t=out:st={duration - 0.55:.3f}:d=0.55[v]",
    ]
    cmd = [
        FFMPEG,
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(BROLL),
    ]
    if audio:
        cmd += ["-i", str(audio)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    if DORO_LOGO.exists():
        cmd += ["-loop", "1", "-i", str(DORO_LOGO)]
    cmd += [
        "-t",
        f"{duration:.3f}",
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[v]",
        "-map",
        "1:a:0",
        "-af",
        f"afade=t=in:st=0:d=0.18,afade=t=out:st={duration - 0.55:.3f}:d=0.55",
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
    ]
    run(cmd, "render outro part")
    return duration


def concat(parts: list[Path], out_path: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for part in parts:
            f.write(f"file '{str(part).replace(chr(92), '/')}'\n")
        list_path = Path(f.name)
    try:
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(out_path)], "concat")
    finally:
        list_path.unlink(missing_ok=True)


def main() -> None:
    data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data.get("items") or []
    if not items:
        raise RuntimeError("news.json has no items")
    if not BROLL.exists():
        raise FileNotFoundError(BROLL)
    if not ANALYSIS_AUDIO.exists():
        raise FileNotFoundError(ANALYSIS_AUDIO)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="insight_quote_") as td:
        tmp = Path(td)
        quote = SEG_DIR / "quote.mp4"
        analysis = SEG_DIR / "analysis.mp4"
        outro = SEG_DIR / "outro.mp4"
        render_quote_part(items[0], quote, tmp)
        render_analysis_part(items[0], analysis, tmp)
        render_outro_part(outro, tmp)
        concat([quote, analysis, outro], OUTPUT)
        shutil.copyfile(OUTPUT, PREVIEW_OUTPUT)
    print(f"done: {OUTPUT}")


if __name__ == "__main__":
    main()
