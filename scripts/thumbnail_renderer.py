#!/usr/bin/env python3
"""
Thumbnail Renderer — render a 1080×1920 PNG cover for a job using Remotion `still`.

Usage:
    python scripts/thumbnail_renderer.py 2026-04-17
    python scripts/thumbnail_renderer.py 2026-04-17/job_5
"""
import base64, io, json, os, subprocess, sys, tempfile
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


def file_to_data_url(path: Path, mime: str) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def build_props() -> dict:
    if not NEWS_FILE.exists():
        raise FileNotFoundError(f"news.json not found: {NEWS_FILE}")
    raw = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = raw.get("items", [])
    if not items:
        raise ValueError("news.json has no items")
    first = items[0]
    # Prefer explicit screenshot path on the item, else pipeline/screenshots/news_01.png
    edited_shot = PIPE_DIR / "screenshots" / "news_01_edited.png"
    orig_shot   = PIPE_DIR / "screenshots" / "news_01.png"
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
