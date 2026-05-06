#!/usr/bin/env python3
"""
test_screenshot_quality.py — fixture-based smoke test.

Replays scripts/screenshot_quality.check_screenshot() against the captured
screenshots from real pipeline runs to verify the obstruction detector keeps
catching the regression that motivated it (job 143 / 2026-05-06 — Initium
Media paywall) without false-positively flagging legitimate news pages.

Run:
    python scripts/test_screenshot_quality.py

Exit code 0 = all assertions hold.  Exit code 1 = at least one fixture
behaved unexpectedly (verdict mismatch).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# Ensure UTF-8 console for emojis on Windows.
for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name)
    if getattr(_s, "encoding", "").lower() not in ("utf-8", "utf8") and \
        hasattr(_s, "buffer"):
        setattr(sys, _name, io.TextIOWrapper(
            _s.buffer, encoding="utf-8", errors="replace"
        ))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from screenshot_quality import check_screenshot  # noqa: E402

# (path, expected_obstructed, label, allowed_kinds)
# When obstructed=True we accept any of allowed_kinds (vision models word
# things differently — paywall vs login vs signup are all "blocked").
FIXTURES: list[tuple[str, bool, str, set[str]]] = [
    (
        "pipeline/2026-05-06/job_143/screenshots/news_01.png",
        True,
        "job 143 / item 1 — Initium Media paywall (regression)",
        {"paywall", "login", "signup", "popup"},
    ),
    (
        "pipeline/2026-05-06/job_143/screenshots/news_02.png",
        False,
        "job 143 / item 2 — TechNews legit body",
        set(),
    ),
    (
        "pipeline/2026-05-06/job_143/screenshots/news_03.png",
        False,
        "job 143 / item 3 — Yahoo legit body",
        set(),
    ),
    (
        "pipeline/2026-05-05/job_138/screenshots/news_01.png",
        False,
        "job 138 / item 1 — TechNews DRAM (legit)",
        set(),
    ),
    (
        "pipeline/2026-05-05/job_138/screenshots/news_02.png",
        False,
        "job 138 / item 2 — TechNews retail AI (legit)",
        set(),
    ),
]


def main() -> int:
    fails: list[str] = []
    for rel, exp_obstructed, label, allowed_kinds in FIXTURES:
        path = ROOT / rel
        if not path.exists():
            print(f"  ⚠️  skip (file missing): {rel}")
            continue
        v = check_screenshot(path)
        ob = bool(v.get("obstructed"))
        kind = v.get("kind", "")
        conf = v.get("confidence", 0.0)
        flag = "🚫" if ob else "✅"
        print(f"  {flag} {label}\n     {rel}\n     "
              f"obstructed={ob}, kind={kind}, conf={conf}, "
              f"why={(v.get('why') or '')[:80]}")
        if ob != exp_obstructed:
            fails.append(
                f"FAIL: {label} → expected obstructed={exp_obstructed}, got {ob}"
            )
            continue
        if exp_obstructed and allowed_kinds and kind not in allowed_kinds:
            fails.append(
                f"FAIL: {label} → expected kind in {allowed_kinds}, got '{kind}'"
            )

    print()
    if fails:
        print("=== FAILURES ===")
        for line in fails:
            print(f"  {line}")
        return 1
    print(f"✅ all {len(FIXTURES)} fixtures passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
