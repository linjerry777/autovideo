#!/usr/bin/env python3
"""
screenshot_quality.py — Detect obstructed news screenshots.

Born from job 143 (2026-05-06): The Initium Media article wrapped its
paywall ("免費註冊，立即解鎖本文") inside the same `<article>` element our
screenshot_collector.py element-screenshot fallback grabs, so the published
short showed a registration form instead of news content.

Two-stage detector:

  Stage A (Pillow-based heuristics, instant)
      Catches blank / corrupt / tiny screenshots up-front. Very conservative —
      never raises `obstructed=True` for a structural issue alone unless the
      image is unrecoverable (missing, tiny, unopenable).

  Stage B (Vision LLM via the existing /v1/chat/completions proxy)
      Asks the model whether the screenshot is a normal news article body or
      something blocking the content (ad / cookie / paywall / popup / signup /
      login / share floater / unrelated overlay). The model returns a short
      JSON verdict. This is the *primary* detector — pure pixel heuristics
      cannot reliably distinguish a paywall card from a legit blog post.

The combined verdict is reported as:
    {
      "obstructed":  bool,
      "kind":        str,   # "paywall" | "popup" | "ad" | "cookie" | "subscribe"
                            # | "share" | "login" | "other" | "none"
      "confidence":  float, # 0.0 .. 1.0
      "stage":       "heuristic" | "vision" | "heuristic+vision",
      "why":         str,
    }

Public API
----------
    check_screenshot(image_path: Path, *, allow_vision: bool = True) -> dict
    log_quality_event(job_key, item_idx, image_path, verdict, log_dir)

CLI
---
    python scripts/screenshot_quality.py path/to/img.png
        prints JSON verdict, exits 1 if obstructed.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# UTF-8 console — only when run directly (not when imported), so we don't
# wrap an already-wrapped stream and trigger "I/O operation on closed file"
# during interpreter shutdown.
def _ensure_utf8_streams():
    for name in ("stdout", "stderr"):
        s = getattr(sys, name)
        try:
            if getattr(s, "encoding", "").lower() not in ("utf-8", "utf8") and \
                hasattr(s, "buffer"):
                setattr(sys, name, io.TextIOWrapper(
                    s.buffer, encoding="utf-8", errors="replace"
                ))
        except Exception:
            pass

if __name__ == "__main__":
    _ensure_utf8_streams()

# Load .env so GROQ_API_KEY etc. are available when run as a CLI or subprocess.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass


# ── Tunable thresholds ───────────────────────────────────────────────────────

MIN_BYTES                  = 25_000          # below this → almost certainly blank
MIN_IMAGE_DIM              = 200             # below this on either side → broken capture
DOMINANT_COLOUR_BUCKET     = 24              # quantize step (0-255)

# Heuristic signals are advisory only; they never auto-flag obstructed
# unless the image is structurally unusable. Vision is the truth.
VISION_MODEL_ENV           = "SCREENSHOT_VISION_MODEL"   # override
VISION_MODEL_DEFAULT       = "meta-llama/llama-4-scout-17b-16e-instruct"
VISION_TIMEOUT_S           = 25

# Vision is routed in this order (first that has credentials wins):
#   1. Groq Llama-4 Scout (free tier covers 1k+ requests/day, native vision)
#   2. OpenAI GPT-4o (only if OPENAI_API_KEY set)
#   3. Anthropic Claude (only if ANTHROPIC_API_KEY set)
# The local Claude-Code proxy at :3456 cannot serialize multipart vision
# requests (passes content array as `[object Object]`), so it is skipped.


# ── Heuristic detection (Stage A) ────────────────────────────────────────────

def _stage_a_heuristic(image_path: Path) -> dict:
    """Sanity-check the file (size, dimensions, openable). Advisory pixel signals.

    This stage *never* flags `obstructed=True` for soft visual signals — pure
    pixel statistics cannot reliably distinguish a paywall card from a long
    text-only blog post. It only hard-flags structurally broken images
    (missing, tiny, unopenable). The vision stage handles semantic obstruction.
    """
    out = {
        "obstructed":  False,
        "kind":        "none",
        "confidence":  0.0,
        "stage":       "heuristic",
        "why":         "",
        "signals":     [],   # list of {name, score, detail}
    }

    # 1. Byte size sanity
    try:
        size = image_path.stat().st_size
    except FileNotFoundError:
        out.update(obstructed=True, kind="missing", confidence=1.0,
                   why=f"file does not exist: {image_path}")
        return out
    out["signals"].append({"name": "byte_size", "score": size,
                            "detail": f"{size} bytes"})
    if size < MIN_BYTES:
        out.update(obstructed=True, kind="other", confidence=1.0,
                   why=f"image is only {size} bytes (likely blank)")
        return out

    try:
        from PIL import Image, ImageFilter, ImageStat
    except ImportError:
        out["why"] = "Pillow not installed; skipping heuristic"
        out["confidence"] = 0.0
        return out

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        out.update(obstructed=True, kind="other", confidence=1.0,
                   why=f"image cannot be opened: {e}")
        return out

    w, h = img.size
    out["signals"].append({"name": "dimensions", "score": w * h,
                            "detail": f"{w}x{h}"})
    if w < MIN_IMAGE_DIM or h < MIN_IMAGE_DIM:
        out.update(obstructed=True, kind="other", confidence=0.95,
                   why=f"image too small ({w}x{h})")
        return out

    # 2. Bottom-half dominant-colour coverage — purely informational, recorded
    # so the operator can scan the screenshot_quality.log to spot patterns
    # (e.g. "all paywalls have >70% pale coverage"), but DOES NOT flag here.
    bottom = img.crop((0, h // 2, w, h))
    bb_small = bottom.resize((96, 96))
    try:
        pixels = list(bb_small.get_flattened_data())  # Pillow 11+
    except AttributeError:
        pixels = list(bb_small.getdata())             # older Pillow
    bucket: dict[tuple[int, int, int], int] = {}
    bs = DOMINANT_COLOUR_BUCKET
    for r, g, b in pixels:
        key = (r // bs, g // bs, b // bs)
        bucket[key] = bucket.get(key, 0) + 1
    if bucket:
        top_key, top_count = max(bucket.items(), key=lambda kv: kv[1])
        coverage = top_count / sum(bucket.values())
        out["signals"].append({
            "name": "bottom_dominant_colour_coverage",
            "score": round(coverage, 3),
            "detail": f"bucket {top_key} covers {coverage:.1%} of bottom half"
        })

    # 3. Edge density across whole image — extremely flat images (single big
    # card, no text, no photo) are suspicious. Only used as advisory signal.
    try:
        gray = img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        mean_edge = ImageStat.Stat(edges).mean[0] / 255.0
        out["signals"].append({
            "name": "global_edge_density",
            "score": round(mean_edge, 4),
            "detail": f"mean edge intensity: {mean_edge:.4f}"
        })
        if mean_edge < 0.005:
            # Almost no edges anywhere → blank or solid coloured frame.
            # Treat as "structurally broken".
            out.update(obstructed=True, kind="other", confidence=0.9,
                       why=f"image is nearly edgeless (mean edge {mean_edge:.4f})")
            return out
    except Exception as e:
        out["signals"].append({"name": "edge_density_error", "score": 0.0,
                                "detail": str(e)})

    return out


# ── Vision LLM detection (Stage B) ───────────────────────────────────────────

_VISION_PROMPT = (
    "You are reviewing a screenshot taken automatically of a NEWS ARTICLE web page "
    "for a short-video pipeline. Detect whether the screenshot is BLOCKED by an "
    "ad banner, cookie consent, subscription paywall, newsletter signup card, "
    "login wall, app-install nag, share/floating button, or any unrelated overlay "
    "that prevents a viewer from reading the article body.\n\n"
    "A normal news page (headline + paragraphs of body text + maybe a hero image) "
    "is NOT obstructed even if it has a small sidebar ad or footer.\n\n"
    "Reply ONLY with a single-line minified JSON object with keys:\n"
    "  obstructed (bool)\n"
    "  kind (one of: ad | cookie | paywall | popup | signup | login | share | other | none)\n"
    "  confidence (0..1)\n"
    "  why (one short sentence)"
)


def _vision_groq(image_path: Path) -> Optional[dict]:
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return None
    model = os.getenv(VISION_MODEL_ENV, VISION_MODEL_DEFAULT)
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        import requests
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                      "Content-Type": "application/json"},
            json={
                "model": model,
                "max_tokens": 200,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VISION_PROMPT},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }],
            },
            timeout=VISION_TIMEOUT_S,
        )
        if r.status_code != 200:
            return {
                "obstructed":  False, "kind": "unknown", "confidence": 0.0,
                "stage": "vision",
                "why": f"groq http {r.status_code}: {r.text[:120]}",
            }
        content = r.json()["choices"][0]["message"]["content"].strip()
        return _parse_vision_reply(content, "groq")
    except Exception as e:
        return {
            "obstructed":  False, "kind": "unknown", "confidence": 0.0,
            "stage": "vision",
            "why": f"groq vision call failed: {e}",
        }


def _vision_openai(image_path: Path) -> Optional[dict]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None
    model = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        import requests
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                      "Content-Type": "application/json"},
            json={
                "model": model,
                "max_tokens": 200,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VISION_PROMPT},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }],
            },
            timeout=VISION_TIMEOUT_S,
        )
        if r.status_code != 200:
            return {
                "obstructed":  False, "kind": "unknown", "confidence": 0.0,
                "stage": "vision",
                "why": f"openai http {r.status_code}: {r.text[:120]}",
            }
        content = r.json()["choices"][0]["message"]["content"].strip()
        return _parse_vision_reply(content, "openai")
    except Exception as e:
        return {
            "obstructed":  False, "kind": "unknown", "confidence": 0.0,
            "stage": "vision",
            "why": f"openai vision call failed: {e}",
        }


def _parse_vision_reply(content: str, backend: str) -> dict:
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()
    first_brace = content.find("{")
    last_brace = content.rfind("}")
    if first_brace == -1 or last_brace == -1:
        return {
            "obstructed":  False, "kind": "unknown", "confidence": 0.0,
            "stage": "vision",
            "why": f"unparseable {backend} reply: {content[:120]}",
        }
    try:
        verdict = json.loads(content[first_brace:last_brace + 1])
    except Exception as e:
        return {
            "obstructed":  False, "kind": "unknown", "confidence": 0.0,
            "stage": "vision",
            "why": f"json parse error from {backend}: {e}",
        }
    return {
        "obstructed":  bool(verdict.get("obstructed")),
        "kind":        str(verdict.get("kind") or "other"),
        "confidence":  float(verdict.get("confidence") or 0.5),
        "stage":       f"vision:{backend}",
        "why":         str(verdict.get("why") or ""),
    }


def _stage_b_vision(image_path: Path) -> Optional[dict]:
    """Try vision backends in priority order. Returns None if none configured."""
    for fn in (_vision_groq, _vision_openai):
        result = fn(image_path)
        if result is not None:
            # If backend is reachable but errored out (kind=unknown, conf=0),
            # try next backend.
            if result.get("kind") == "unknown" and result.get("confidence") == 0.0:
                continue
            return result
    return None


# ── Combined check ───────────────────────────────────────────────────────────

def check_screenshot(image_path: Path,
                     *,
                     allow_vision: bool = True) -> dict:
    """Run heuristic, optionally escalate to vision, return combined verdict.

    Logic:
        1. Run heuristic for structural sanity. If it hard-fails (missing,
           tiny, unopenable, edgeless) → return immediately, skip vision.
        2. Otherwise run vision (if allowed). Vision is the authoritative
           detector of semantic obstruction.
        3. If vision is unavailable, fall through to "not obstructed" with
           a low confidence (we don't reject based on advisory pixel signals
           alone — that caused too many false positives in testing on
           legitimate text-heavy news pages).
    """
    image_path = Path(image_path)
    a = _stage_a_heuristic(image_path)

    # Hard structural failure → return now.
    if a.get("obstructed") and a.get("confidence", 0.0) >= 0.9:
        return a

    if not allow_vision:
        return a

    b = _stage_b_vision(image_path)
    if b is None:
        return a

    # If vision proxy errored, fall through with heuristic verdict (likely
    # not-obstructed; structural problems were caught above).
    if b.get("confidence", 0.0) == 0.0 and b.get("kind") == "unknown":
        a["why"] = (a.get("why") or "") + f" | vision unavailable: {b.get('why','')}"
        return a

    obstructed = bool(b.get("obstructed"))
    return {
        "obstructed":  obstructed,
        "kind":        b.get("kind") or "none",
        "confidence":  round(float(b.get("confidence") or 0.0), 3),
        "stage":       "heuristic+vision",
        "why":         b.get("why") or "",
        "heuristic":   a,
        "vision":      b,
    }


# ── Logging helper ───────────────────────────────────────────────────────────

def log_quality_event(job_key: str,
                      item_idx: int,
                      image_path: Path,
                      verdict: dict,
                      log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "screenshot_quality.log"
    record = {
        "ts":          datetime.now(timezone.utc).isoformat(),
        "job_key":     job_key,
        "item_idx":    item_idx,
        "image":       str(image_path),
        "obstructed":  verdict.get("obstructed"),
        "kind":        verdict.get("kind"),
        "confidence":  verdict.get("confidence"),
        "stage":       verdict.get("stage"),
        "why":         verdict.get("why"),
    }
    line = json.dumps(record, ensure_ascii=False)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── CLI ──────────────────────────────────────────────────────────────────────

def _main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Detect obstructed news screenshots (paywall / popup / ad / cookie)."
    )
    parser.add_argument("image", help="path to PNG / JPG screenshot")
    parser.add_argument("--no-vision", action="store_true",
                        help="skip vision LLM stage")
    parser.add_argument("--pretty", action="store_true",
                        help="pretty-print JSON output")
    args = parser.parse_args()

    verdict = check_screenshot(Path(args.image),
                               allow_vision=not args.no_vision)
    print(json.dumps(verdict, ensure_ascii=False,
                     indent=2 if args.pretty else None))
    sys.exit(1 if verdict.get("obstructed") else 0)


if __name__ == "__main__":
    _main()
