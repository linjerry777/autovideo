#!/usr/bin/env python3
"""Generate an image2 thumbnail for figure insight clips.

The image model creates the cinematic portrait/background. FFmpeg overlays the
Chinese title afterwards so the text stays readable and correct.
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
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
JOB_KEY = sys.argv[1] if len(sys.argv) > 1 else "2026-05-13/figure_preview_tech"
PIPE_DIR = BASE_DIR / "pipeline" / JOB_KEY
NEWS_FILE = PIPE_DIR / "news.json"
RAW_IMAGE = PIPE_DIR / "thumbnail_image2_raw.png"
OUTPUT = PIPE_DIR / "thumbnail.png"
FONT_ZH = Path("C:/Windows/Fonts/msjh.ttc")
W, H = 1080, 1920


def ffmpeg() -> str:
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    for root in [Path("C:/ffmpeg"), Path("C:/Program Files"), Path("C:/tools")]:
        if not root.exists():
            continue
        for f in root.rglob("ffmpeg.exe"):
            return str(f)
    raise RuntimeError("ffmpeg not found")


FFMPEG = ffmpeg()


def ff_path(path: Path | str) -> str:
    p = str(path).replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = p[0] + "\\:" + p[2:]
    return p


def title_lines(text: str, width: int = 9, max_lines: int = 3) -> list[str]:
    text = str(text).strip()
    text = text.replace("，", "\n").replace(",", "\n")
    text = re.sub(r"[^\w\u4e00-\u9fff\n]+", "", text)
    text = re.sub(r"\n+", "\n", text).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if 1 < len(lines) <= max_lines:
        return lines
    text = re.sub(r"\s+", "", "".join(lines) if lines else text)
    chunks = [text[i : i + width] for i in range(0, len(text), width)]
    if len(chunks) > max_lines:
        chunks = chunks[: max_lines - 1] + ["".join(chunks[max_lines - 1 :])]
    return [chunk for chunk in chunks[:max_lines] if chunk]


def build_text(item: dict) -> tuple[str, str, str]:
    figure = item.get("figure_name") or "科技大佬"
    hook = item.get("hook") or item.get("title") or "這句話值得聽"
    if str(figure).lower().startswith("sam"):
        title = "模型不夠\n產品才是勝負"
    else:
        title = hook
    return str(figure), title, "DORO 拆解"


def generate_base(item: dict) -> None:
    if RAW_IMAGE.exists() and RAW_IMAGE.stat().st_size > 10_000:
        return
    from web.claude_client import generate_image

    figure, title, _series = build_text(item)
    prompt = f"""
Create a vertical 9:16 YouTube Shorts cover image, cinematic editorial style.
Subject: {figure}, technology leader / founder interview analysis.
Mood: premium tech media, high contrast, black and electric blue background with a warm yellow accent.
Composition: dramatic close-up portrait inspired by conference/interview lighting, face on upper half, enough dark negative space for Chinese headline overlays.
Do not include any text, letters, logos, watermarks, captions, UI, or symbols in the image.
No generic stock-photo look. Make it feel like a sharp tech-news thumbnail about this idea: {title}.
"""
    generate_image(prompt.strip(), RAW_IMAGE, size="1024x1792", timeout=240)


def overlay_text(item: dict) -> None:
    figure, title, series = build_text(item)
    with tempfile.TemporaryDirectory(prefix="figure_thumb_") as td:
        tmp = Path(td)
        figure_f = tmp / "figure.txt"
        title_line_files = []
        series_f = tmp / "series.txt"
        figure_f.write_text(figure, encoding="utf-8")
        for i, line in enumerate(title_lines(title), 1):
            p = tmp / f"title_{i}.txt"
            p.write_text(line, encoding="utf-8")
            title_line_files.append(p)
        series_f.write_text(series, encoding="utf-8")
        filter_parts = [
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},eq=contrast=1.08:saturation=1.08[base]",
            f"[base]drawbox=x=0:y=0:w={W}:h={H}:color=black@0.18:t=fill[v0]",
            f"[v0]drawbox=x=0:y=0:w={W}:h=360:color=black@0.72:t=fill[v1]",
            f"[v1]drawtext=fontfile='{ff_path(FONT_ZH)}':textfile='{ff_path(series_f)}':fontsize=44:fontcolor=#FFF03A:x=58:y=58:borderw=2:bordercolor=black[v2]",
            f"[v2]drawtext=fontfile='{ff_path(FONT_ZH)}':textfile='{ff_path(figure_f)}':fontsize=62:fontcolor=white:x=58:y=128:borderw=3:bordercolor=black[v3]",
        ]
        prev = "v3"
        for i, p in enumerate(title_line_files, 1):
            out = f"vt{i}"
            y = 1180 + (i - 1) * 120
            filter_parts.append(
                f"[{prev}]drawtext=fontfile='{ff_path(FONT_ZH)}':textfile='{ff_path(p)}':"
                f"fontsize=92:fontcolor=#FFF03A:x=58:y={y}:borderw=5:bordercolor=black[{out}]"
            )
            prev = out
        filter_parts.append(f"[{prev}]drawbox=x=58:y=1520:w=250:h=10:color=#FFF03A@0.95:t=fill[v]")
        filters = ";".join(filter_parts)
        result = subprocess.run(
            [
                FFMPEG,
                "-y",
                "-i",
                str(RAW_IMAGE),
                "-filter_complex",
                filters,
                "-map",
                "[v]",
                "-frames:v",
                "1",
                str(OUTPUT),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-1200:])


def main() -> None:
    data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    item = (data.get("items") or [{}])[0]
    generate_base(item)
    overlay_text(item)
    print(f"done: {OUTPUT}")


if __name__ == "__main__":
    main()
