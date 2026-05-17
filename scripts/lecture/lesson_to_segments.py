#!/usr/bin/env python3
"""
Lesson → Segments planner.

Takes a lesson dict (one of the entries from dump_course_data.mjs output) and
produces a flat list of "segments". Each segment is one slide + one voiceover
chunk, the atomic unit our pipeline renders + concatenates.

Segment types:
  - title       : course/lesson title splash
  - intro       : description voiceover, key points list shown
  - step_title  : "Step N: <title>" header card, brief
  - step_body   : body text + voiceover
  - code        : code block monospace, narrated "請看這段指令..."
  - claude      : claude prompt block (orange-tinted), narrated "把這段貼給 Claude..."
  - warning     : red warning box
  - tip         : amber tip box
  - link        : "打開這個網址：..." with URL shown
  - outro       : next-chapter teaser

Output JSON written next to lesson, one file per lesson:
  {lesson_id}.segments.json
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _clean(text: str) -> str:
    """Tidy text for narration (collapse whitespace, strip)."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def _narration_for_body(body: str) -> str:
    """Body text is usually already speakable. Keep newlines as natural pauses
    by collapsing them to commas/periods only when not already punctuated."""
    if not body:
        return ""
    # Replace double-newlines with period+space (paragraph break → sentence break)
    text = re.sub(r"\n{2,}", "。", body)
    # Single newline within paragraph → comma if not punctuated
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _narration_for_code(code: dict) -> str:
    """Decide what voiceover to play while a code block is on-screen."""
    lang = (code or {}).get("lang", "").lower()
    if lang == "bash":
        return "這幾個指令直接貼到終端機執行。"
    if lang == "sql":
        return "這段 SQL 貼到 Supabase 的 SQL Editor 執行。"
    if lang == "json":
        return "這是預期回傳的格式。"
    if lang == "text":
        # text blocks are usually a list of links or a checklist — narrate generically
        return "螢幕上這段內容請仔細看一下。"
    return "請看一下這段。"


def _narration_for_claude_prompt() -> str:
    return "把這段提示貼給 Claude，讓它幫你執行。"


def _narration_for_warning(warning: str) -> str:
    return "注意這個重點。" + _clean(warning)


def _narration_for_tip(tip: str) -> str:
    return "小提示。" + _clean(tip)


def _narration_for_link(link: dict) -> str:
    text = (link or {}).get("text", "")
    return f"連結放在描述欄。{text}。" if text else "相關連結放在描述欄。"


def plan_segments(lesson: dict, course_title: str, next_lesson: dict | None) -> list[dict]:
    segments: list[dict] = []

    # 1. Title splash
    segments.append({
        "kind": "title",
        "course_title": course_title,
        "lesson_id": lesson["id"],
        "lesson_title": lesson["title"],
        "lesson_duration": lesson["duration"],
        "narration": (
            f"歡迎來到《{course_title}》。"
            f"這是 {lesson['id'].upper()},  {lesson['title']}。"
        ),
        "min_duration": 4.0,
    })

    # 2. Intro — description + keyPoints
    key_points = lesson.get("keyPoints", []) or []
    description = lesson.get("description", "") or ""
    intro_narration = _narration_for_body(description)
    if key_points:
        intro_narration += "這一章的重點有這幾個： " + "； ".join(key_points) + "。"
    segments.append({
        "kind": "intro",
        "lesson_title": lesson["title"],
        "description": description,
        "key_points": key_points,
        "narration": intro_narration,
        "tail_pause": 1.5,
    })

    # 3. Steps
    steps = lesson.get("steps", []) or []
    for idx, step in enumerate(steps, 1):
        # 3a. Step title card
        segments.append({
            "kind": "step_title",
            "step_index": idx,
            "step_total": len(steps),
            "step_title": step.get("title", ""),
            "narration": f"步驟 {idx}：{step.get('title','')}。",
            "min_duration": 4.0,
            "tail_pause": 1.0,
        })
        # 3b. Body
        body = step.get("body") or ""
        if body:
            segments.append({
                "kind": "step_body",
                "step_index": idx,
                "step_title": step.get("title", ""),
                "body": body,
                "narration": _narration_for_body(body),
            })
        # 3c. Code block (if any) — extended hold so viewer can read it
        code = step.get("code")
        if code:
            content_len = len(code.get("content") or "")
            # ~80 CJK/code chars per second of comfortable reading
            read_pause = max(4.0, min(content_len / 25.0, 18.0))
            segments.append({
                "kind": "code",
                "step_index": idx,
                "step_title": step.get("title", ""),
                "code_lang": (code.get("lang") or "").lower(),
                "code_content": code.get("content") or "",
                "narration": _narration_for_code(code),
                "tail_pause": read_pause,
            })
        # 3d. Claude prompt — give viewer time to read it
        claude_prompt = step.get("claude")
        if claude_prompt:
            content_len = len(claude_prompt)
            read_pause = max(5.0, min(content_len / 22.0, 18.0))
            segments.append({
                "kind": "claude",
                "step_index": idx,
                "step_title": step.get("title", ""),
                "prompt": claude_prompt,
                "narration": _narration_for_claude_prompt(),
                "tail_pause": read_pause,
            })
        # 3e. Warning
        warning = step.get("warning")
        if warning:
            segments.append({
                "kind": "warning",
                "step_index": idx,
                "step_title": step.get("title", ""),
                "warning": warning,
                "narration": _narration_for_warning(warning),
                "tail_pause": 1.5,
            })
        # 3f. Tip
        tip = step.get("tip")
        if tip:
            segments.append({
                "kind": "tip",
                "step_index": idx,
                "step_title": step.get("title", ""),
                "tip": tip,
                "narration": _narration_for_tip(tip),
                "tail_pause": 1.5,
            })
        # 3g. Link
        link = step.get("link")
        if link:
            segments.append({
                "kind": "link",
                "step_index": idx,
                "step_title": step.get("title", ""),
                "link_text": link.get("text", ""),
                "link_url": link.get("url", ""),
                "narration": _narration_for_link(link),
                "min_duration": 5.0,
                "tail_pause": 1.5,
            })

    # 4. Outro
    outro_narration = (
        f"以上是 {lesson['id'].upper()} 的內容。"
    )
    if next_lesson is not None:
        outro_narration += (
            f"下一章 {next_lesson['id'].upper()}：{next_lesson['title']}。"
            "我們下集見。"
        )
    else:
        outro_narration += "感謝收看。"

    segments.append({
        "kind": "outro",
        "lesson_id": lesson["id"],
        "next_lesson_id": next_lesson["id"] if next_lesson else None,
        "next_lesson_title": next_lesson["title"] if next_lesson else None,
        "narration": outro_narration,
        "min_duration": 6.0,
        "tail_pause": 2.0,
    })

    return segments


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/lecture-input/ai-lesson-claude-code.json")
    p.add_argument("--lesson-id", required=True, help="e.g. ch00")
    p.add_argument("--out", default=None,
                   help="Output JSON path (defaults to data/lecture-work/<lesson_id>.segments.json)")
    args = p.parse_args()

    base = Path(__file__).resolve().parent.parent.parent
    in_path = (base / args.input) if not Path(args.input).is_absolute() else Path(args.input)
    data = json.loads(in_path.read_text(encoding="utf-8"))

    lessons = data.get("lessons", [])
    course_title = data.get("course_title", "")
    found = None
    next_lesson = None
    for i, l in enumerate(lessons):
        if l["id"] == args.lesson_id:
            found = l
            if i + 1 < len(lessons):
                next_lesson = lessons[i + 1]
            break
    if found is None:
        print(f"❌ lesson_id {args.lesson_id!r} not found", file=sys.stderr)
        sys.exit(1)

    segments = plan_segments(found, course_title, next_lesson)
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = base / "data" / "lecture-work" / f"{args.lesson_id}.segments.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({
            "course_title": course_title,
            "lesson_id": args.lesson_id,
            "lesson_title": found["title"],
            "segments": segments,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ {len(segments)} segments → {out_path}")


if __name__ == "__main__":
    main()
