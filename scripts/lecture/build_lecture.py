#!/usr/bin/env python3
"""
End-to-end lecture builder.

Usage:
  python scripts/lecture/build_lecture.py \
      --lesson-id ch00 \
      --course-data C:/Users/User/Documents/GitHub/ai_lesson/lib/course-data.ts \
      --out data/output/lecture/ch00.mp4

Pipeline:
  1. dump_course_data.mjs   (course-data.ts → JSON)         [skipped if --skip-dump]
  2. lesson_to_segments.py  (lesson → segment plan)
  3. lecture_slides.py      (segments → 1920×1080 PNGs)
  4. lecture_tts.py         (Fish Audio TTS, cached)
  5. lecture_compose.py     (per-segment MP4 + concat)
"""
import argparse
import io
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent


def run(cmd: list[str], cwd: Path | None = None):
    print(f"\n$ {' '.join(cmd)}\n", flush=True)
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if r.returncode != 0:
        sys.exit(f"❌ step failed: {' '.join(cmd)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lesson-id", required=True, help="e.g. ch00")
    ap.add_argument("--course-data",
                    default="C:/Users/User/Documents/GitHub/ai_lesson/lib/course-data.ts",
                    help="Path to ai_lesson/lib/course-data.ts")
    ap.add_argument("--out", required=True, help="Final mp4 path")
    ap.add_argument("--skip-dump", action="store_true",
                    help="Reuse data/lecture-input/ai-lesson-claude-code.json")
    args = ap.parse_args()

    lesson_id = args.lesson_id
    work_dir = BASE / "data" / "lecture-work" / lesson_id
    work_dir.mkdir(parents=True, exist_ok=True)
    course_json = BASE / "data" / "lecture-input" / "ai-lesson-claude-code.json"

    # Step 1
    if not args.skip_dump or not course_json.exists():
        run(["npx", "tsx", str(HERE / "dump_course_data.mjs"),
             args.course_data, str(course_json)],
            cwd=BASE)

    # Step 2
    seg_json = BASE / "data" / "lecture-work" / f"{lesson_id}.segments.json"
    run([sys.executable, str(HERE / "lesson_to_segments.py"),
         "--input", str(course_json),
         "--lesson-id", lesson_id,
         "--out", str(seg_json)])

    # Step 3
    slides_dir = work_dir / "slides"
    run([sys.executable, str(HERE / "lecture_slides.py"),
         "--segments", str(seg_json),
         "--out-dir", str(slides_dir)])
    with_slides = work_dir / f"{lesson_id}.segments.with_slides.json"

    # Step 4
    audio_dir = work_dir / "audio"
    final_manifest = work_dir / f"{lesson_id}.segments.final.json"
    run([sys.executable, str(HERE / "lecture_tts.py"),
         "--manifest", str(with_slides),
         "--audio-dir", str(audio_dir),
         "--out-manifest", str(final_manifest)])

    # Step 5
    parts_dir = work_dir / "parts"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run([sys.executable, str(HERE / "lecture_compose.py"),
         "--manifest", str(final_manifest),
         "--parts-dir", str(parts_dir),
         "--out", str(out_path)])

    print(f"\n🎉 done: {out_path}")


if __name__ == "__main__":
    main()
