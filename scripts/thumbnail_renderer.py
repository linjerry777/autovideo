#!/usr/bin/env python3
"""
Thumbnail Renderer — render a 1080×1920 PNG cover for a job using Remotion `still`.

Usage:
    python scripts/thumbnail_renderer.py 2026-04-17
    python scripts/thumbnail_renderer.py 2026-04-17/job_5
"""
import base64, io, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

TODAY = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

BASE_DIR      = Path(__file__).resolve().parent.parent
PIPELINE_ROOT = Path(os.environ.get("PIPELINE_DIR", BASE_DIR / "pipeline")).resolve()
PIPE_DIR      = PIPELINE_ROOT / TODAY
NEWS_FILE     = PIPE_DIR / "news.json"
REMOTION_DIR  = Path(os.environ.get("REMOTION_DIR", BASE_DIR / "remotion")).resolve()
OUTPUT        = PIPE_DIR / "thumbnail.png"
DORO_LOGO     = BASE_DIR / "assets" / "brand" / "doro_insight_logo.png"


def file_to_data_url(path: Path, mime: str) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def find_ffmpeg() -> str | None:
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    for root in [Path("C:/ffmpeg"), Path("C:/Program Files"), Path("C:/tools")]:
        if not root.exists():
            continue
        for f in root.rglob("ffmpeg.exe"):
            return str(f)
    return None


def ensure_figure_frame() -> Path | None:
    edited_shot = PIPE_DIR / "screenshots" / "news_01_edited.png"
    orig_shot = PIPE_DIR / "screenshots" / "news_01.png"
    if edited_shot.exists():
        return edited_shot
    broll = PIPE_DIR / "broll" / "broll_01.mp4"
    if not broll.exists():
        return orig_shot if orig_shot.exists() else None
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return orig_shot if orig_shot.exists() else None
    orig_shot.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            "4",
            "-i",
            str(broll),
            "-frames:v",
            "1",
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            str(orig_shot),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return orig_shot if result.returncode == 0 and orig_shot.exists() else (orig_shot if orig_shot.exists() else None)


def build_props() -> dict:
    if not NEWS_FILE.exists():
        raise FileNotFoundError(f"news.json not found: {NEWS_FILE}")
    raw = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = raw.get("items", [])
    if not items:
        raise ValueError("news.json has no items")
    first = items[0]
    content_type = raw.get("content_type") or first.get("content_type") or ""
    # Prefer explicit screenshot path on the item, else pipeline/screenshots/news_01.png
    edited_shot = PIPE_DIR / "screenshots" / "news_01_edited.png"
    orig_shot   = PIPE_DIR / "screenshots" / "news_01.png"
    if content_type == "figure_quote":
        shot_value = first.get("screenshot") or ensure_figure_frame()
        shot_path = Path(shot_value) if shot_value else None
        figure = first.get("figure_name") or "科技名人"
        title = first.get("title") or first.get("summary") or first.get("quote_zh") or ""
        return {
            "variant":    "figure_quote",
            "hook":       first.get("hook", "這句值得聽"),
            "title":      f"{figure}：{title}" if title and figure not in title else title,
            "figure":     figure,
            "screenshot": file_to_data_url(shot_path, "image/png") if shot_path and shot_path.exists() and shot_path.is_file() else "",
            "logo":       file_to_data_url(DORO_LOGO, "image/png") if DORO_LOGO.exists() else "",
        }
    shot_path = Path(first.get("screenshot") or (edited_shot if edited_shot.exists() else orig_shot))
    screenshot_url = file_to_data_url(shot_path, "image/png") if shot_path.exists() else ""
    return {
        "hook":       first.get("hook", "AI 快訊"),
        "title":      first.get("title", ""),
        "screenshot": screenshot_url,
    }


def render(props: dict, output: Path):
    output.unlink(missing_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tf:
        json.dump(props, tf, ensure_ascii=False)
        props_file = tf.name
    try:
        cmd = [
            "npx", "remotion", "still",
            "src/index.tsx",
            "Thumbnail",
            str(output).replace("\\", "/"),
            f"--props={props_file.replace(chr(92), '/')}",
            "--image-format=png",
        ]
        print(f"Running Remotion still → {output.name}", file=sys.stderr)
        result = subprocess.run(
            cmd, cwd=str(REMOTION_DIR),
            text=True, encoding="utf-8", errors="replace",
            shell=(sys.platform == "win32"),
        )
    finally:
        try: os.unlink(props_file)
        except OSError: pass

    if result.returncode != 0:
        raise RuntimeError(f"Remotion still failed (exit {result.returncode})")


def main():
    props = build_props()
    render(props, OUTPUT)
    print(f"\nDone: {OUTPUT}", file=sys.stdout)


if __name__ == "__main__":
    main()
