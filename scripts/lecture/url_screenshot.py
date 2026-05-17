#!/usr/bin/env python3
"""
URL screenshot capture for lecture link slides.

Visits a URL in headless Chromium and captures a 1280×720 viewport PNG. Results
are cached on disk by URL hash so re-runs don't re-fetch.

Usage as a library:
    from url_screenshot import capture_url, capture_urls_batch
    png_path = capture_url("https://claude.ai/download", cache_dir)
    # → Path or None on failure (timeout / refused / 404)

Auth-walled pages (e.g. dashboard.stripe.com → login redirect) capture the
login page, which is fine — it's what the viewer actually sees too.
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


SHOT_W, SHOT_H = 1280, 720
NAV_TIMEOUT_MS = 20_000
SETTLE_MS = 2_500


def _slug_for_url(url: str) -> str:
    """Stable, readable filename for a URL. host_path[:40]_hash6.png"""
    parsed = urlparse(url)
    host = (parsed.netloc or "").replace(":", "_")
    path = (parsed.path or "/").strip("/")
    raw = f"{host}_{path}".lower()
    raw = re.sub(r"[^a-z0-9._-]+", "_", raw)
    raw = raw.strip("_") or "root"
    if len(raw) > 60:
        raw = raw[:60]
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:6]
    return f"{raw}_{h}.png"


def cache_path_for(url: str, cache_dir: Path) -> Path:
    return cache_dir / _slug_for_url(url)


def capture_url(url: str, cache_dir: Path, page=None,
                force: bool = False) -> Path | None:
    """Capture a URL screenshot to cache_dir. Returns the path or None.

    If `page` is None, spins up its own browser (slow, only use for one-offs).
    Pass an existing Playwright page for batch use.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_path_for(url, cache_dir)
    if out.exists() and out.stat().st_size > 5_000 and not force:
        return out

    own_browser = False
    pw = browser = ctx = None
    if page is None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": SHOT_W, "height": SHOT_H},
            device_scale_factor=1,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        own_browser = True

    try:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except Exception as e:
            print(f"    [url-shot] goto failed: {url} → {e}")
            return None

        # Try networkidle but don't fail the whole capture if it times out
        try:
            page.wait_for_load_state("networkidle", timeout=6_000)
        except Exception:
            pass
        page.wait_for_timeout(SETTLE_MS)

        # Best-effort: dismiss common cookie / consent popups
        DISMISS = [
            "button[aria-label*='Accept' i]",
            "button[aria-label*='accept' i]",
            "button[aria-label*='同意' i]",
            "button[id*='cookie'][id*='accept' i]",
            "button[class*='cookie'][class*='accept' i]",
            "[id*='cookie-banner' i] button",
        ]
        for sel in DISMISS:
            try:
                for btn in page.query_selector_all(sel)[:2]:
                    if btn.is_visible():
                        btn.click(timeout=800)
                        page.wait_for_timeout(200)
            except Exception:
                pass

        try:
            page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass

        try:
            page.screenshot(path=str(out), full_page=False, omit_background=False)
        except Exception as e:
            print(f"    [url-shot] screenshot failed: {url} → {e}")
            return None

        size = out.stat().st_size if out.exists() else 0
        if size < 5_000:
            print(f"    [url-shot] suspiciously small ({size}B), discarding")
            out.unlink(missing_ok=True)
            return None

        return out
    finally:
        if own_browser:
            try:
                ctx.close()
                browser.close()
                pw.stop()
            except Exception:
                pass


def capture_urls_batch(urls: list[str], cache_dir: Path) -> dict[str, Path | None]:
    """Capture many URLs sharing one browser context. Returns {url: path or None}."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path | None] = {}

    # Filter to ones we actually need to fetch
    todo: list[str] = []
    for u in urls:
        cached = cache_path_for(u, cache_dir)
        if cached.exists() and cached.stat().st_size > 5_000:
            result[u] = cached
        else:
            todo.append(u)

    if not todo:
        return result

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                viewport={"width": SHOT_W, "height": SHOT_H},
                device_scale_factor=1,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()
            for u in todo:
                print(f"  [url-shot] {u}")
                p = capture_url(u, cache_dir, page=page)
                result[u] = p
                if p:
                    print(f"     ✅ {p.name} ({p.stat().st_size//1024}KB)")
                else:
                    print(f"     ⚠️  failed → fallback to URL pill")
            ctx.close()
        finally:
            browser.close()

    return result


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    # Quick smoke test
    if len(sys.argv) < 2:
        print("Usage: python url_screenshot.py <url> [<url>...]")
        sys.exit(1)
    cache = Path(__file__).resolve().parent.parent.parent / "data" / "lecture-work" / "_url_cache"
    res = capture_urls_batch(sys.argv[1:], cache)
    for u, p in res.items():
        print(f"{u} → {p}")
