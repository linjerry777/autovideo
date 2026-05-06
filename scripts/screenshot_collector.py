#!/usr/bin/env python3
"""
screenshot_collector.py — 截圖每篇新聞頁面作為影片背景
優先：Playwright 截圖原始網頁
備案：Unsplash 搜圖（需設定 UNSPLASH_KEY）
最後：video_composer 自動生成漸層佔位圖

After each capture we run scripts.screenshot_quality.check_screenshot()
to detect obstructions (paywall / cookie / popup / ad / signup wall) and
auto-reject + retry / fall back to OG image / mark for manual review.

Per-item verdicts are written to:
    pipeline/<date>/job_<id>/screenshots/quality.json

Schema:
    {
      "items": [
        { "idx": 1, "image": "news_01.png", "obstructed": true,
          "kind": "paywall", "confidence": 0.9, "stage": "vision:groq",
          "why": "...", "source": "playwright:article|og:image|...",
          "attempts": 2 },
        ...
      ],
      "any_obstructed": bool
    }

`job_runner.py` reads `any_obstructed`; if true it sets the job to
`manual_review` status (no publish) and pings Telegram.
"""
import json, os, sys, io, requests
from pathlib import Path
from urllib.parse import quote

# Import siblings (works both when run as script and imported as module)
# Note: pywin32 installs a `scripts` namespace package at site-packages/win32/scripts,
# which shadows our local `scripts/` dir. Import sibling module by name instead,
# ensuring the script's own directory is on sys.path.
try:
    import sys as _sys
    from pathlib import Path as _Path
    _script_dir = str(_Path(__file__).resolve().parent)
    if _script_dir not in _sys.path:
        _sys.path.insert(0, _script_dir)
    from og_image_fetcher import fetch_hero_image
    from screenshot_quality import check_screenshot, log_quality_event
except ModuleNotFoundError:
    # Fallback: someone is importing us as `scripts.screenshot_collector` from repo root
    from scripts.og_image_fetcher import fetch_hero_image
    from scripts.screenshot_quality import check_screenshot, log_quality_event

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

TODAY     = sys.argv[1] if len(sys.argv) > 1 else ""
BASE_DIR  = Path(__file__).parent.parent
PIPE_DIR  = BASE_DIR / "pipeline" / TODAY
NEWS_FILE = PIPE_DIR / "news.json"
SHOTS_DIR = PIPE_DIR / "screenshots"
QUALITY_FILE = SHOTS_DIR / "quality.json"
QUALITY_LOG_DIR = BASE_DIR / "data"

VIEWPORT_W    = 1200
VIEWPORT_H    = 800
UNSPLASH_KEY  = os.getenv("UNSPLASH_KEY", "")

# Set OBSTRUCTION_DETECT=0 in the environment to disable post-capture vision
# screening (e.g. for offline debugging without GROQ_API_KEY).
OBSTRUCTION_DETECT = os.getenv("OBSTRUCTION_DETECT", "1") != "0"


YT_ID_RE = None   # lazy-compiled


# ── Aggressive overlay-removal CSS injected before screenshot ────────────────
# 2026-05-06: job 143 captured Initium Media's 「免費註冊，立即解鎖本文」
# registration card because it is rendered INSIDE the same <article> element
# we screenshot. Add strong selectors for register/login/paywall/gate/lock
# overlays and unhide siblings so the actual body is reachable.
PAYWALL_REMOVAL_CSS = """
    [class*='paywall' i],
    [class*='pay-wall' i],
    [id*='paywall' i],
    [class*='subscribe' i][class*='wall' i],
    [class*='subscribe' i][class*='gate' i],
    [class*='register-wall' i],
    [class*='registration' i][class*='wall' i],
    [class*='register' i][class*='gate' i],
    [class*='register' i][class*='card' i],
    [class*='member' i][class*='wall' i],
    [class*='member' i][class*='gate' i],
    [class*='login-wall' i],
    [class*='gate-wall' i],
    [class*='content-gate' i],
    [class*='article-gate' i],
    [class*='unlock' i][class*='content' i],
    [class*='premium' i][class*='wall' i],
    [class*='cookie-banner' i], [id*='cookie-banner' i],
    [class*='cookie-consent' i], [id*='cookie-consent' i],
    [class*='cookie-notice' i], [id*='cookie-notice' i],
    [class*='gdpr' i],
    [class*='newsletter' i][class*='popup' i],
    [class*='newsletter' i][class*='modal' i],
    [class*='newsletter' i][class*='signup' i],
    [class*='newsletter' i][class*='subscribe' i],
    [class*='modal-overlay' i],
    [class*='modal-backdrop' i],
    [class*='overlay-backdrop' i],
    [class*='lightbox' i],
    [class*='popup-overlay' i],
    [class*='subscribe-modal' i],
    [class*='signup-modal' i],
    [class*='register-modal' i],
    [class*='login-modal' i],
    [class*='ad-banner' i],
    [class*='advert' i],
    [id*='ad-banner' i],
    [id*='gpt-ad' i],
    [class*='banner-ad' i],
    [class*='top-bar-ad' i],
    [role='dialog'],
    [role='alertdialog'],
    [aria-modal='true'],
    [class*='sticky' i][class*='header' i],
    [class*='floating' i][class*='cta' i],
    [class*='floating-button' i],
    [class*='social-share' i][class*='float' i],
    [class*='share-floating' i],
    [style*='position: fixed' i][style*='bottom' i],
    [style*='position:fixed' i][style*='bottom' i] {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }
    /* Ensure body scroll wasn't locked by removed modal */
    html, body {
        overflow: auto !important;
        position: static !important;
    }
"""


def _youtube_thumbnail(url: str, out_path: Path) -> tuple[bool, str]:
    """If url is a YouTube video, fetch its thumbnail directly (skip Playwright).

    Returns (ok, label). Tries maxres → hqdefault → mq. YouTube guarantees hqdefault exists.
    """
    global YT_ID_RE
    if not YT_ID_RE:
        import re as _re
        YT_ID_RE = _re.compile(
            r"(?:youtube\.com/(?:watch\?.*?v=|shorts/|embed/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})"
        )
    m = YT_ID_RE.search(url or "")
    if not m:
        return (False, "")
    vid = m.group(1)
    for variant in ("maxresdefault.jpg", "hqdefault.jpg", "mqdefault.jpg"):
        thumb_url = f"https://img.youtube.com/vi/{vid}/{variant}"
        try:
            r = requests.get(thumb_url, timeout=10)
            # YouTube returns a grey placeholder for missing maxres — check size
            if r.ok and len(r.content) > 5_000:
                out_path.write_bytes(r.content)
                return (True, f"youtube-thumb:{variant}")
        except Exception:
            continue
    return (False, "")


def _unsplash_fallback(query: str, out_path: Path) -> bool:
    """用 Unsplash 搜尋關鍵字，下載第一張圖片。成功回傳 True。"""
    if not UNSPLASH_KEY:
        return False
    try:
        q   = quote(query)
        url = f"https://api.unsplash.com/photos/random?query={q}&orientation=landscape&client_id={UNSPLASH_KEY}"
        r   = requests.get(url, timeout=15)
        if not r.ok:
            return False
        img_url = r.json()["urls"]["regular"]
        img_r   = requests.get(img_url, timeout=20)
        out_path.write_bytes(img_r.content)
        return True
    except Exception as e:
        print(f"    ⚠️  Unsplash 備案失敗：{e}")
        return False


def _capture_via_playwright(page, url: str, shot_path: Path,
                            extra_strip: bool = False) -> tuple[bool, str]:
    """Navigate + dismiss popups + element-screenshot.

    Returns (success, source_label).
    `extra_strip=True` enables a more aggressive scroll + repeated style injection
    used on retries, in case the offending overlay is lazy-loaded.
    """
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    # Initial wait for JS hydration + image lazy-load
    page.wait_for_timeout(2500)

    # 1. Dismiss common cookie / newsletter / paywall buttons
    DISMISS_SELECTORS = [
        "button[id*='cookie'][id*='accept' i]",
        "button[class*='cookie'][class*='accept' i]",
        "button[aria-label*='Accept' i]",
        "button[aria-label*='同意' i]",
        "button[aria-label*='Close' i]",
        "button[aria-label*='close' i]",
        "button[aria-label*='關閉' i]",
        "button[class*='close'][class*='modal' i]",
        "button[class*='dismiss' i]",
        "[class*='cookie-banner' i] button",
        "[id*='popup' i] button[class*='close' i]",
        "[role='dialog'] button[aria-label*='close' i]",
    ]
    for sel in DISMISS_SELECTORS:
        try:
            for btn in page.query_selector_all(sel)[:3]:
                if btn.is_visible():
                    btn.click(timeout=1000)
                    page.wait_for_timeout(200)
        except Exception:
            pass

    # 2. Inject aggressive paywall-removal CSS
    page.add_style_tag(content=PAYWALL_REMOVAL_CSS)

    # 2.5. On retry: scroll to top + re-inject (some sites lazy-mount overlays)
    if extra_strip:
        try:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(400)
            page.add_style_tag(content=PAYWALL_REMOVAL_CSS)
            page.wait_for_timeout(300)
            # Forcefully delete fixed overlays via JS too
            page.evaluate("""() => {
                document.querySelectorAll('*').forEach(el => {
                    const cs = getComputedStyle(el);
                    if ((cs.position === 'fixed' || cs.position === 'sticky') &&
                        (parseInt(cs.zIndex || '0') > 100 || el.offsetWidth >
                         window.innerWidth * 0.6)) {
                        el.style.display = 'none';
                    }
                });
            }""")
        except Exception:
            pass

    # 3. Try to capture article element first
    ARTICLE_SELECTORS = [
        "article",
        "[role='main']",
        "main article",
        "main",
        "[itemprop='articleBody']",
        ".article-body",
        ".article-content",
        ".post-content",
        ".entry-content",
        "#article-body",
        "#content",
    ]
    for sel in ARTICLE_SELECTORS:
        try:
            el = page.query_selector(sel)
            if not el:
                continue
            box = el.bounding_box()
            if not box or box["height"] < 300 or box["width"] < 300:
                continue
            el.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(700)
            el.screenshot(path=str(shot_path))
            return (True, f"playwright:element:{sel}")
        except Exception:
            continue

    # 4. fallback: viewport screenshot
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(shot_path), full_page=False)
        size = shot_path.stat().st_size
        if size < 25_000:
            shot_path.unlink(missing_ok=True)
            return (False, "")
        return (True, "playwright:viewport")
    except Exception:
        return (False, "")


def main():
    if not NEWS_FILE.exists():
        print(f"❌ 找不到新聞檔：{NEWS_FILE}", file=sys.stderr)
        sys.exit(1)

    data  = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data["items"]
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)

    quality_records: list[dict] = []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        # 阻擋廣告、字體、追蹤器，加速載入
        page.route("**/*.{woff,woff2,ttf,otf,gif,svg}", lambda r: r.abort())
        page.route("**/ads/**", lambda r: r.abort())
        page.route("**/analytics/**", lambda r: r.abort())

        for i, item in enumerate(items, 1):
            raw_url   = item.get("source_url") or item.get("url") or ""
            shot_path = SHOTS_DIR / f"news_{i:02d}.png"

            if shot_path.exists():
                print(f"  [{i}] 截圖已存在，跳過")
                # Still record quality (so the job_runner gate can re-check)
                if OBSTRUCTION_DETECT:
                    v = check_screenshot(shot_path)
                    quality_records.append({
                        "idx": i, "image": shot_path.name,
                        "source": "preexisting",
                        "attempts": 0,
                        **{k: v.get(k) for k in
                           ("obstructed", "kind", "confidence", "stage", "why")}
                    })
                    log_quality_event(TODAY, i, shot_path, v, QUALITY_LOG_DIR)
                continue

            # ── 解析 Google 追蹤 URL → 取得真實網址 ─────────────────
            url = raw_url
            if "news.google.com" in raw_url:
                try:
                    resp = requests.get(raw_url, allow_redirects=True, timeout=10,
                                        headers={"User-Agent": "Mozilla/5.0"})
                    url = resp.url
                    print(f"  [{i}] 解析後 URL：{url[:80]}...")
                except Exception:
                    url = raw_url  # 解析失敗就用原始 URL

            # ── Helper: run quality check + retry / fall through ────────
            def _accept_or_reject(source: str, attempts: int) -> tuple[bool, dict]:
                if not OBSTRUCTION_DETECT:
                    return (True, {"obstructed": False, "kind": "none",
                                   "confidence": 0.0, "stage": "disabled",
                                   "why": "OBSTRUCTION_DETECT=0"})
                v = check_screenshot(shot_path)
                log_quality_event(TODAY, i, shot_path, v, QUALITY_LOG_DIR)
                v["source"] = source
                v["attempts"] = attempts
                if v.get("obstructed"):
                    print(f"    🚫 截圖偵測到遮擋：{v.get('kind')} "
                          f"(信心 {v.get('confidence')}, why: {v.get('why','')[:80]})")
                    return (False, v)
                print(f"    ✅ 截圖品質檢查通過 ({v.get('stage')}, "
                      f"信心 {v.get('confidence')})")
                return (True, v)

            captured_source: str | None = None
            attempts = 0
            verdict: dict | None = None

            # ── 方法 -1：YouTube 連結直接抓 thumbnail（無 UI chrome）─────
            if url:
                yt_ok, yt_source = _youtube_thumbnail(url, shot_path)
                if yt_ok:
                    size_kb = shot_path.stat().st_size // 1024
                    print(f"  [{i}] ✅ {yt_source} ({size_kb}KB)")
                    attempts = 1
                    ok, verdict = _accept_or_reject(yt_source, attempts)
                    if ok:
                        captured_source = yt_source
                    else:
                        # YouTube thumb obstructed is rare; just discard
                        shot_path.unlink(missing_ok=True)

            # ── 方法 0：OG image（最快、最高品質、最不怕反爬）─────────
            if captured_source is None and url:
                ok_og, og_source = fetch_hero_image(url, shot_path)
                if ok_og:
                    size_kb = shot_path.stat().st_size // 1024
                    print(f"  [{i}] ✅ {og_source} ({size_kb}KB)")
                    attempts += 1
                    ok, verdict = _accept_or_reject(og_source, attempts)
                    if ok:
                        captured_source = og_source
                    else:
                        shot_path.unlink(missing_ok=True)

            # ── 方法 1：Playwright 智能截圖 + 品質檢查 + 一次重試 ─────────
            if captured_source is None and url:
                print(f"  [{i}] 智能截圖：{url[:80]}...")
                for retry in (False, True):
                    try:
                        ok_pw, pw_source = _capture_via_playwright(
                            page, url, shot_path, extra_strip=retry)
                    except Exception as e:
                        print(f"  [{i}] ⚠️ 截圖失敗：{e}")
                        ok_pw, pw_source = False, ""
                    if not ok_pw:
                        continue
                    size_kb = shot_path.stat().st_size // 1024
                    print(f"  [{i}] ✅ {pw_source} ({size_kb}KB){' [重試]' if retry else ''}")
                    attempts += 1
                    ok, verdict = _accept_or_reject(pw_source, attempts)
                    if ok:
                        captured_source = pw_source
                        break
                    # On retry path also failed → drop and try next stage
                    shot_path.unlink(missing_ok=True)

            # ── 方法 2：Unsplash 搜圖（最後 fallback）──────────────────
            if captured_source is None:
                keyword = item.get("title") or item.get("hook") or "technology news"
                print(f"    🔍 Unsplash 搜圖：{keyword[:40]}...")
                if _unsplash_fallback(keyword, shot_path):
                    print(f"  [{i}] ✅ Unsplash 備案成功")
                    captured_source = "unsplash"
                    attempts += 1
                    # Unsplash is generic stock — never "obstructed"
                    verdict = {"obstructed": False, "kind": "none",
                               "confidence": 1.0, "stage": "fallback",
                               "why": "unsplash stock image", "source": "unsplash",
                               "attempts": attempts}
                else:
                    print(f"  [{i}] ℹ️  無法取得圖片，video_composer 將補漸層佔位圖")

            # ── Record quality outcome for job_runner gate ───────────────
            if captured_source is None:
                # Nothing captured — mark as obstructed so job_runner can
                # decide whether to manual-review (no source available).
                quality_records.append({
                    "idx": i, "image": shot_path.name,
                    "obstructed": True, "kind": "missing", "confidence": 1.0,
                    "stage": "no_capture",
                    "why": "all capture methods failed or returned obstructed images",
                    "source": "none", "attempts": attempts,
                })
            else:
                rec = {"idx": i, "image": shot_path.name,
                        "source": captured_source, "attempts": attempts}
                if verdict:
                    rec.update({k: verdict.get(k) for k in
                                ("obstructed", "kind", "confidence",
                                 "stage", "why")})
                else:
                    rec.update({"obstructed": False, "kind": "none",
                                "confidence": 0.0, "stage": "skipped", "why": ""})
                quality_records.append(rec)

        browser.close()

    # ── Persist per-job quality summary ──────────────────────────────────
    summary = {
        "items":           quality_records,
        "any_obstructed":  any(r.get("obstructed") for r in quality_records),
        "obstructed_kinds": sorted({
            r.get("kind") for r in quality_records
            if r.get("obstructed") and r.get("kind") not in (None, "", "none")
        }),
    }
    QUALITY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    print(f"📊 截圖品質報告：{QUALITY_FILE}")
    print(f"   any_obstructed={summary['any_obstructed']} "
          f"kinds={summary['obstructed_kinds']}")

    print("✅ 截圖步驟完成")


if __name__ == "__main__":
    main()
