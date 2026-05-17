#!/usr/bin/env python3
"""Pure quote clip composer.

This matches the common "famous quote" Shorts format:
- original speaker audio only
- yellow headline at the top
- Chinese subtitle + smaller English subtitle at the bottom
- small account mark at the bottom
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
JOB_KEY = sys.argv[1] if len(sys.argv) > 1 else "2026-05-13/figure_preview_tech"
PIPE_DIR = BASE_DIR / "pipeline" / JOB_KEY
NEWS_FILE = PIPE_DIR / "news.json"
BROLL_DIR = PIPE_DIR / "broll"
OUTPUT = PIPE_DIR / "wisdom_quote_output.mp4"

W, H = 1080, 1920
VIDEO_Y = 250
VIDEO_H = 1010
FONT_ZH = Path("C:/Windows/Fonts/msjh.ttc")


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
        chunks: list[str] = []
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
        cues.append(
            {
                "start": float(match.group(1)),
                "end": float(match.group(2)),
                "text": match.group(3).strip(),
            }
        )
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


def make_ass(captions: list[dict], out_path: Path) -> None:
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
        lines.append(
            f"Dialogue: 0,{ass_time(cap['start'])},{ass_time(cap['end'])},Bilingual,,0,0,0,,{text}"
        )
    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def build_captions(item: dict, start_abs: float, end_abs: float, local_offset: float) -> list[dict]:
    manual = item.get("wisdom_captions")
    if isinstance(manual, list) and manual:
        return [
            {
                "start": max(0.0, float(c.get("start") or 0)),
                "end": max(0.2, float(c.get("end") or 0)),
                "zh": c.get("zh") or c.get("text") or "",
                "en": c.get("en") or "",
            }
            for c in manual
        ]

    captions = []
    for cue in parse_transcript(item.get("transcript_window") or ""):
        if cue["end"] < start_abs or cue["start"] > end_abs:
            continue
        start = max(0.0, cue["start"] - local_offset)
        end = max(start + 0.5, cue["end"] - local_offset)
        captions.append({"start": start, "end": end, "zh": zh_for(cue["text"]), "en": cue["text"]})
    return captions


def title_for(item: dict) -> str:
    if item.get("wisdom_title"):
        return str(item["wisdom_title"])
    figure = item.get("figure_name") or "名人"
    if figure.lower().startswith("sam"):
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


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def render(item: dict, broll: Path) -> None:
    cues = parse_transcript(item.get("transcript_window") or "")
    clip_start = float(item.get("clip_start") or 0)
    broll_origin = max(0.0, clip_start - 2.0)
    focus = quote_focus_abs(item, cues) or clip_start

    first_after_clip = next((c["start"] for c in cues if c["start"] >= clip_start), clip_start)
    start_abs = max(clip_start, min(first_after_clip, focus - 18.0))
    end_abs = min(start_abs + 23.0, max((c["end"] for c in cues), default=start_abs + 22.0))
    local_start = max(0.0, start_abs - broll_origin)
    local_offset = broll_origin + local_start
    duration = min(max(8.0, end_abs - start_abs), max(8.0, get_duration(broll) - local_start))

    captions = build_captions(item, start_abs, start_abs + duration, local_offset)
    if not captions:
        captions = [
            {
                "start": 0.2,
                "end": duration - 0.2,
                "zh": item.get("quote_zh") or item.get("hook") or "",
                "en": item.get("quote_original") or "",
            }
        ]

    with tempfile.TemporaryDirectory(prefix="wisdom_quote_") as td:
        tmp = Path(td)
        title_lines = [line for line in split_title_lines(title_for(item)) if line]
        title_1_path = tmp / "title_1.txt"
        title_2_path = tmp / "title_2.txt"
        ass_path = tmp / "subs.ass"
        write_text(title_1_path, title_lines[0] if title_lines else "")
        write_text(title_2_path, title_lines[1] if len(title_lines) > 1 else "")
        make_ass(captions, ass_path)

        filters = ";".join(
            [
                f"color=c=black:s={W}x{H}:r=30:d={duration:.3f}[canvas]",
                (
                    f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                    f"crop={W}:{H},crop={W}:{VIDEO_H}:0:(ih-{VIDEO_H})/2,"
                    f"eq=brightness=-0.02:saturation=1.05[main]"
                ),
                f"[canvas][main]overlay=0:{VIDEO_Y}[v0]",
                (
                    f"[v0]drawtext=fontfile='{ff_path(FONT_ZH)}':"
                    f"textfile='{ff_path(title_1_path)}':"
                    f"fontsize=58:fontcolor=#FFF03A:"
                    f"x=58:y=54:borderw=3:bordercolor=black[v1]"
                ),
                (
                    f"[v1]drawtext=fontfile='{ff_path(FONT_ZH)}':"
                    f"textfile='{ff_path(title_2_path)}':"
                    f"fontsize=58:fontcolor=#FFF03A:"
                    f"x=58:y=126:borderw=3:bordercolor=black[v2]"
                ),
                (
                    f"[v2]subtitles='{ff_path(ass_path)}':"
                    f"fontsdir='{ff_path('C:/Windows/Fonts')}'[vsub]"
                ),
                (
                    f"[vsub]drawtext=fontfile='{ff_path(FONT_ZH)}':text='○':"
                    f"fontsize=92:fontcolor=white:x=(w-text_w)/2:y=1698[v3]"
                ),
                (
                    f"[v3]drawtext=fontfile='{ff_path(FONT_ZH)}':text='言':"
                    f"fontsize=48:fontcolor=white:x=(w-text_w)/2:y=1721[v]"
                ),
            ]
        )

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
                "-r",
                "30",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                str(OUTPUT),
            ],
            "render wisdom quote clip",
        )


def main() -> None:
    data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data.get("items") or []
    if not items:
        raise RuntimeError("news.json has no items")
    broll = BROLL_DIR / "broll_01.mp4"
    if not broll.exists():
        raise FileNotFoundError(broll)
    render(items[0], broll)
    print(f"done: {OUTPUT}")


if __name__ == "__main__":
    main()
