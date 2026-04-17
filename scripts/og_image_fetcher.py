#!/usr/bin/env python3
"""
og_image_fetcher.py — Fast hero-image extraction from news URLs.

Tries (in order):
  1. <meta property="og:image" content="...">
  2. <meta name="twitter:image" content="...">
  3. First significant <img> inside <article> or <main>

Each candidate is validated: HTTP 200 + content-type starts with image/ + either
Content-Length > 10KB OR a small PIL size check passing min_side.

Public API:
    fetch_hero_image(url, out_path, min_side=400) -> (ok: bool, source: str)
"""
import io
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
PAGE_TIMEOUT = 15
IMG_TIMEOUT  = 20


def _resolve_google_news(url: str) -> str:
    """Follow Google News redirect to the real article URL (if applicable)."""
    if "news.google.com" not in url:
        return url
    try:
        r = requests.get(url, allow_redirects=True, timeout=10,
                         headers={"User-Agent": UA})
        return r.url
    except Exception:
        return url


def _candidate_urls(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return [(image_url, source_tag), ...] in priority order."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []

    # og:image (most publishers)
    for meta in soup.find_all("meta", attrs={"property": "og:image"}):
        val = (meta.get("content") or "").strip()
        if val:
            out.append((urljoin(base_url, val), "og:image"))

    # twitter:image (Twitter Card fallback)
    for meta in soup.find_all("meta", attrs={"name": "twitter:image"}):
        val = (meta.get("content") or "").strip()
        if val:
            out.append((urljoin(base_url, val), "twitter:image"))

    # first <img> inside <article> or <main>
    for container_tag in ("article", "main"):
        container = soup.find(container_tag)
        if container:
            for img in container.find_all("img"):
                src = (img.get("src") or img.get("data-src") or "").strip()
                if src and not src.startswith("data:"):
                    out.append((urljoin(base_url, src), "article_img"))
                    break
        if any(s == "article_img" for _, s in out):
            break

    # De-dup while preserving order
    seen = set()
    unique = []
    for u, src in out:
        if u not in seen:
            seen.add(u)
            unique.append((u, src))
    return unique


def _validate_and_save(img_url: str, out_path: Path, min_side: int) -> bool:
    """Download image, check size via PIL, save on success."""
    try:
        r = requests.get(img_url, timeout=IMG_TIMEOUT,
                         headers={"User-Agent": UA})
        if r.status_code != 200:
            return False
        ctype = r.headers.get("Content-Type", "").lower()
        if not ctype.startswith("image/"):
            return False
        data = r.content
        if len(data) < 5_000:   # too small to be a hero image (likely tracker / placeholder)
            return False
        # Size check — cheap, no PIL if not available
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            w, h = img.size
            if max(w, h) < min_side:
                return False
        except ImportError:
            pass   # PIL not available; rely on byte-size + content-type
        out_path.write_bytes(data)
        return True
    except Exception:
        return False


def fetch_hero_image(url: str, out_path: Path, min_side: int = 400) -> tuple[bool, str]:
    """Fetch a hero image for `url`, save to `out_path`.

    Returns (True, source) where source is "og:image" | "twitter:image" | "article_img"
    on success. Returns (False, "") when no candidate validates."""
    if not url:
        return (False, "")
    real_url = _resolve_google_news(url)
    try:
        r = requests.get(real_url, timeout=PAGE_TIMEOUT,
                         headers={"User-Agent": UA})
        if r.status_code != 200 or not r.text:
            return (False, "")
        candidates = _candidate_urls(r.text, real_url)
    except Exception:
        return (False, "")

    for img_url, source in candidates:
        if _validate_and_save(img_url, out_path, min_side):
            return (True, source)
    return (False, "")


# ── CLI for debugging ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--out", default="out.jpg")
    parser.add_argument("--min-side", type=int, default=400)
    args = parser.parse_args()
    ok, source = fetch_hero_image(args.url, Path(args.out), args.min_side)
    print(f"{'✓' if ok else '✗'} {source or '(failed)'} → {args.out if ok else '-'}")
    sys.exit(0 if ok else 1)
