#!/usr/bin/env python3
"""
audio_assets.py — Pick BGM / SFX from local asset library.

Folder layout (relative to repo root):
    assets/music/<emotion>/*.mp3   ← random pick per emotion
    assets/sfx/hook/*.mp3          ← random pick

Public API:
    pick_bgm(emotion: str) -> Path | None
    pick_hook_sfx(emotion: str | None = None) -> Path | None

Returns None when no usable asset exists, so callers can fall through
to voice-only output without crashing.
"""
import random
from pathlib import Path

REPO_ROOT  = Path(__file__).resolve().parent.parent
MUSIC_ROOT = REPO_ROOT / "assets" / "music"
SFX_ROOT   = REPO_ROOT / "assets" / "sfx"

# Known emotions (matches Step 1 schema). Unknown → generic only.
KNOWN_EMOTIONS = {"surprise", "fear", "joy", "curiosity", "anger"}


def _pick_random(folder: Path) -> Path | None:
    """Return a random .mp3 from folder (recursive=False), or None."""
    if not folder.exists() or not folder.is_dir():
        return None
    candidates = [p for p in folder.iterdir() if p.suffix.lower() == ".mp3" and p.is_file()]
    if not candidates:
        return None
    return random.choice(candidates)


def pick_bgm(emotion: str | None) -> Path | None:
    """Pick a BGM track for the given emotion.

    Fallback chain: <emotion>/ → generic/ → None
    """
    em = (emotion or "").lower()
    if em in KNOWN_EMOTIONS:
        choice = _pick_random(MUSIC_ROOT / em)
        if choice:
            return choice
    return _pick_random(MUSIC_ROOT / "generic")


def pick_hook_sfx(emotion: str | None = None) -> Path | None:
    """Pick a hook SFX. Currently emotion is unused but accepted for
    forward-compat in case we add per-emotion SFX later."""
    return _pick_random(SFX_ROOT / "hook")


# ── CLI for debugging ─────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--emotion", default="surprise")
    args = parser.parse_args()
    bgm = pick_bgm(args.emotion)
    sfx = pick_hook_sfx(args.emotion)
    print(f"emotion={args.emotion}")
    print(f"  bgm: {bgm or '(none)'}")
    print(f"  sfx: {sfx or '(none)'}")
    sys.exit(0)
