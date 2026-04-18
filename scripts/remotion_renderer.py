#!/usr/bin/env python3
"""
Remotion Renderer — Python bridge for the Remotion-based animated compositor.

Usage:
    python scripts/remotion_renderer.py 2026-04-14

This script:
1. Reads pipeline/DATE/news.json
2. Resolves audio paths + timing files + screenshot paths
3. Gets audio durations via ffprobe
4. Calls: npx remotion render src/index.tsx NewsVideo <output> --props='<json>'
5. Output → pipeline/DATE/output_remotion.mp4

Environment variables:
    RENDER_MODE        Must be "remotion" (this script is only called when set)
    REMOTION_DIR       Optional override for the remotion/ project directory
    PIPELINE_DIR       Optional override for pipeline root dir
"""

import base64
import io
import json
import os
import subprocess
import sys
from pathlib import Path

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from datetime import date

# ── Paths ──────────────────────────────────────────────────────────────────────
import argparse as _ap
_parser = _ap.ArgumentParser()
_parser.add_argument("job_key", nargs="?", default=date.today().isoformat())
_parser.add_argument("--version", choices=["short", "long"], default=None)
_args, _ = _parser.parse_known_args()

TODAY   = _args.job_key
VERSION = _args.version

BASE_DIR    = Path(__file__).resolve().parent.parent
PIPELINE_ROOT = Path(os.environ.get("PIPELINE_DIR", BASE_DIR / "pipeline")).resolve()
PIPE_DIR    = PIPELINE_ROOT / TODAY
NEWS_FILE   = PIPE_DIR / "news.json"
SHOTS_DIR   = PIPE_DIR / "screenshots"
if VERSION:
    AUDIO_DIR = PIPE_DIR / VERSION / "audio"
    OUTPUT    = PIPE_DIR / VERSION / "output.mp4"
else:
    AUDIO_DIR = PIPE_DIR / "audio"
    OUTPUT    = PIPE_DIR / "output.mp4"

REMOTION_DIR = Path(os.environ.get("REMOTION_DIR", BASE_DIR / "remotion")).resolve()


# ── ffprobe helper ─────────────────────────────────────────────────────────────
def _find_ffprobe() -> str:
    """Locate ffprobe (mirrors logic from video_composer.py)."""
    import shutil
    if shutil.which("ffprobe"):
        return "ffprobe"
    winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / \
        "Microsoft/WinGet/Packages"
    for root, _dirs, files in os.walk(winget_base):
        for f in files:
            if f.lower() == "ffprobe.exe":
                return str(Path(root) / f)
    raise RuntimeError("ffprobe not found — install ffmpeg: winget install Gyan.FFmpeg")


def get_duration(path: Path) -> float:
    ffprobe = _find_ffprobe()
    r = subprocess.run(
        [ffprobe, "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1",
         str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise RuntimeError(f"Could not read duration from {path}: {r.stderr.strip()}")


# ── File-to-data-URL helper ────────────────────────────────────────────────────
def file_to_data_url(path: Path, mime: str) -> str:
    """Encode a local file as a base64 data URL so Remotion's Chromium can load it."""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


# ── Scene resolver (fills scene_recipe for free-text scene_type) ──────────────
PRESET_SCENE_KEYS = {"fire", "race", "money", "robot", "warning", "trophy", "default", ""}

def resolve_scenes_inplace(news_file: Path) -> int:
    """Call Claude to resolve free-text scene_type → scene_recipe.
    Writes back to news.json. Returns count of items resolved."""
    try:
        # Import lazy so this script can run without the web package in some setups
        sys.path.insert(0, str(BASE_DIR))
        from web.claude_client import resolve_scene_recipe
    except Exception as e:
        print(f"  [scene] resolver unavailable: {e}", file=sys.stderr)
        return 0

    data = json.loads(news_file.read_text(encoding="utf-8"))
    items = data.get("items", [])
    resolved = 0
    for item in items:
        st = (item.get("scene_type") or "").strip()
        if not st or st in PRESET_SCENE_KEYS:
            continue
        if item.get("scene_recipe"):  # already cached
            continue
        print(f"  [scene] resolving {st!r}...", file=sys.stderr)
        recipe = resolve_scene_recipe(st, context_title=item.get("title", ""))
        if recipe:
            item["scene_recipe"] = recipe
            resolved += 1
            print(f"  [scene] got {len(recipe.get('layers', []))} layers", file=sys.stderr)
        else:
            print(f"  [scene] resolve failed; will fall back to default", file=sys.stderr)
    if resolved:
        news_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return resolved


# ── Props builder ──────────────────────────────────────────────────────────────
def build_props(pipe_dir: Path, news_file: Path) -> dict:
    """
    Read news.json and resolve all file paths → return props dict
    matching the NewsVideoProps TypeScript interface.
    """
    raw = json.loads(news_file.read_text(encoding="utf-8"))
    items_raw = raw.get("items", [])

    items_out = []
    for i, item in enumerate(items_raw, 1):
        audio_path  = AUDIO_DIR / f"audio_{i:02d}.mp3"
        # Prefer user-edited version if it exists
        edited_shot = pipe_dir / "screenshots" / f"news_{i:02d}_edited.png"
        orig_shot   = pipe_dir / "screenshots" / f"news_{i:02d}.png"
        shot_path   = Path(item.get("screenshot") or (edited_shot if edited_shot.exists() else orig_shot))
        timing_path = AUDIO_DIR / f"audio_{i:02d}_timing.json"

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        duration = get_duration(audio_path)

        timing = None
        if timing_path.exists():
            try:
                timing = json.loads(timing_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  Warning: could not read timing {timing_path}: {e}", file=sys.stderr)

        # Encode as base64 data URLs — Remotion's Chromium blocks file:// local resources
        screenshot_url = file_to_data_url(shot_path, "image/png") if shot_path.exists() else ""
        audio_url = file_to_data_url(audio_path, "audio/mpeg")

        items_out.append({
            "hook":         item.get("hook", "AI 快訊"),
            "stat_badge":   item.get("stat_badge") or "",
            "title":        item.get("title", ""),
            "script":       (
                item.get("script_short") if VERSION == "short"
                else item.get("script_long") if VERSION == "long"
                else item.get("script")
            ) or item.get("summary", ""),
            "source":       item.get("source") or item.get("source_name", ""),
            "scene_type":   item.get("scene_type", ""),
            "scene_recipe": item.get("scene_recipe"),
            "screenshot":   screenshot_url,
            "audio":        audio_url,
            "timing":       timing,
            "duration":     duration,
        })

    # layout_mode: default "visual" (image full-bleed); accept "text" for legacy look
    layout_mode = (raw.get("layout_mode") or "visual").lower()
    if layout_mode not in ("visual", "text"):
        layout_mode = "visual"

    # Optional brand mascot (persistent bottom-right overlay across all items)
    mascot_path = BASE_DIR / "assets" / "brand" / "mascot.png"
    mascot_url  = file_to_data_url(mascot_path, "image/png") if mascot_path.exists() else ""

    return {
        "date":        TODAY,
        "items":       items_out,
        "layout_mode": layout_mode,
        "mascot":      mascot_url,
    }


# ── Remotion render ────────────────────────────────────────────────────────────
def render(props: dict, output: Path):
    """
    Run: npx remotion render src/index.tsx NewsVideo <output> --props=<file>
    inside the remotion/ directory.

    Props are written to a temp JSON file to avoid Windows command-line length
    limits (WinError 206) when screenshots/audio are base64-encoded data URLs.
    """
    import tempfile

    print(f"Running Remotion render → {output.name}", file=sys.stderr)
    print(f"  Items: {len(props['items'])}", file=sys.stderr)
    for item in props["items"]:
        print(f"    - {item['title'][:60]}... (duration={item['duration']:.1f}s)", file=sys.stderr)

    # Write props to a temp file so we don't hit Windows MAX_CMD_LINE limits
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tf:
        json.dump(props, tf, ensure_ascii=False)
        props_file = tf.name

    try:
        cmd = [
            "npx", "remotion", "render",
            "src/index.tsx",
            "NewsVideo",
            str(output).replace("\\", "/"),
            f"--props={props_file.replace(chr(92), '/')}",
            "--overwrite",
            "--codec", "h264",
            "--crf", "18",
            "--concurrency", "4",
        ]

        result = subprocess.run(
            cmd,
            cwd=str(REMOTION_DIR),
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=(sys.platform == "win32"),
        )
    finally:
        try:
            os.unlink(props_file)
        except OSError:
            pass

    if result.returncode != 0:
        raise RuntimeError(f"Remotion render failed (exit {result.returncode})")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    if not NEWS_FILE.exists():
        print(f"ERROR: news.json not found: {NEWS_FILE}", file=sys.stderr)
        sys.exit(1)

    # Ensure node_modules exist
    nm = REMOTION_DIR / "node_modules"
    if not nm.exists():
        print("Installing Remotion dependencies (npm install)...", file=sys.stderr)
        subprocess.run(["npm", "install"], cwd=str(REMOTION_DIR), check=True)

    print(f"Resolving scene recipes...", file=sys.stderr)
    resolved = resolve_scenes_inplace(NEWS_FILE)
    if resolved:
        print(f"  Resolved {resolved} scene recipe(s)", file=sys.stderr)

    print(f"Building props from {NEWS_FILE}", file=sys.stderr)
    props = build_props(PIPE_DIR, NEWS_FILE)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    render(props, OUTPUT)

    print(f"\nDone: {OUTPUT}", file=sys.stdout)


if __name__ == "__main__":
    main()
