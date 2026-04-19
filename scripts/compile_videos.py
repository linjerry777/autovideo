#!/usr/bin/env python3
"""
compile_videos.py — concatenate 2+ existing job outputs into a 合輯 video.

Use case: individual news / trending videos are ~20-40s (below TikTok's 60s
Creator Rewards threshold). Two stitched together naturally crosses 60s and
reuses already-rendered assets (zero extra Claude / render cost).

Usage:
    python scripts/compile_videos.py <target_date> <src_job_key1> <src_job_key2> [...] [--version short|long]

    Example:
      python scripts/compile_videos.py 2026-04-20 2026-04-19/job_92 2026-04-19/job_94 --version long

Writes:
    pipeline/<target_date>/compile_<timestamp>/output.mp4     (concat result)
    pipeline/<target_date>/compile_<timestamp>/news.json      (merged items)
    pipeline/<target_date>/compile_<timestamp>/thumbnail.png  (from first src)
"""
from __future__ import annotations
import argparse, io, json, os, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent


def _find_ffmpeg() -> str:
    """Locate ffmpeg — matches logic in video_composer.py."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    for root, _dirs, files in os.walk(winget_base):
        for f in files:
            if f.lower() == "ffmpeg.exe":
                return str(Path(root) / f)
    raise RuntimeError("ffmpeg not found — install via: winget install Gyan.FFmpeg")


def _resolve_src_video(src_dir: Path, version: str) -> Path | None:
    """Try short/output.mp4 → long/output.mp4 → legacy output.mp4 (in that order,
    but respecting the --version flag)."""
    candidates = [src_dir / version / "output.mp4", src_dir / "output.mp4"]
    # Also try the other version as fallback if primary is missing
    other = "long" if version == "short" else "short"
    candidates.append(src_dir / other / "output.mp4")
    for c in candidates:
        if c.exists():
            return c
    return None


def compile_videos(target_date: str, src_job_keys: list[str], version: str = "long") -> Path:
    ffmpeg = _find_ffmpeg()

    # Resolve all source videos first
    src_videos: list[Path] = []
    merged_items: list[dict] = []
    first_thumb: Path | None = None
    first_strategy = ""
    first_profile  = ""

    for jk in src_job_keys:
        src_dir = BASE_DIR / "pipeline" / jk
        if not src_dir.exists():
            raise RuntimeError(f"job dir not found: {src_dir}")
        video = _resolve_src_video(src_dir, version)
        if not video:
            raise RuntimeError(f"no output.mp4 found in {src_dir} (tried short/long/legacy)")
        src_videos.append(video)

        news_f = src_dir / "news.json"
        if news_f.exists():
            nd = json.loads(news_f.read_text(encoding="utf-8"))
            merged_items.extend(nd.get("items", []))
            first_strategy = first_strategy or (nd.get("strategy") or "")
            first_profile  = first_profile  or (nd.get("account_profile") or "")
        if first_thumb is None:
            t = src_dir / "thumbnail.png"
            if t.exists():
                first_thumb = t

    # Create output dir with timestamp suffix for uniqueness
    ts        = datetime.now().strftime("%H%M%S")
    out_name  = f"compile_{ts}"
    out_dir   = BASE_DIR / "pipeline" / target_date / out_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4   = out_dir / "output.mp4"

    # Build concat list file
    list_file = out_dir / "concat_list.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in src_videos) + "\n",
        encoding="utf-8",
    )

    # Re-encode for safety (concat demuxer needs identical codecs; re-encoding
    # handles mismatched sources cleanly). x264 + CRF 20 + aac 128k is our
    # established quality profile (matches video_composer.py defaults).
    print(f"🎬 concat {len(src_videos)} videos → {out_mp4.name}")
    for v in src_videos:
        size_mb = v.stat().st_size / 1_048_576
        print(f"   • {v.relative_to(BASE_DIR)} ({size_mb:.1f} MB)")
    cmd = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("❌ ffmpeg failed:")
        print(r.stderr[-2000:], file=sys.stderr)
        sys.exit(1)

    list_file.unlink(missing_ok=True)  # cleanup

    # Merged news.json
    merged_news = {
        "date":            f"{target_date}/{out_name}",
        "strategy":        first_strategy,
        "account_profile": first_profile,
        "layout_mode":     "article_rotate",
        "compiled_from":   src_job_keys,
        "items":           merged_items,
    }
    (out_dir / "news.json").write_text(
        json.dumps(merged_news, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Copy thumbnail from first source
    if first_thumb:
        shutil.copy2(first_thumb, out_dir / "thumbnail.png")

    size_mb = out_mp4.stat().st_size / 1_048_576
    print(f"✅ compile done → {out_mp4} ({size_mb:.1f} MB, {len(merged_items)} items)")
    return out_mp4


def main():
    p = argparse.ArgumentParser()
    p.add_argument("target_date", help="YYYY-MM-DD for the new compile job")
    p.add_argument("src_job_keys", nargs="+", help="Source job keys e.g. 2026-04-19/job_92")
    p.add_argument("--version", choices=["short", "long"], default="long",
                   help="Which version of the source videos to stitch (default long for TikTok >60s)")
    args = p.parse_args()

    if len(args.src_job_keys) < 2:
        sys.exit("需要至少 2 個來源 job key 才能合輯")

    compile_videos(args.target_date, args.src_job_keys, args.version)


if __name__ == "__main__":
    main()
