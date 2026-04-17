#!/usr/bin/env python3
"""
screenshot_collector.py — 截圖每篇新聞頁面作為影片背景
優先：Playwright 截圖原始網頁
備案：Unsplash 搜圖（需設定 UNSPLASH_KEY）
最後：video_composer 自動生成漸層佔位圖
"""
import json, os, sys, io, requests
from pathlib import Path
from urllib.parse import quote

# Import og_image_fetcher (works both when run as script and imported as module)
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
except ModuleNotFoundError:
    # Fallback: someone is importing us as `scripts.screenshot_collector` from repo root
    from scripts.og_image_fetcher import fetch_hero_image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

TODAY     = sys.argv[1] if len(sys.argv) > 1 else ""
BASE_DIR  = Path(__file__).parent.parent
PIPE_DIR  = BASE_DIR / "pipeline" / TODAY
NEWS_FILE = PIPE_DIR / "news.json"
SHOTS_DIR = PIPE_DIR / "screenshots"

VIEWPORT_W    = 1200
VIEWPORT_H    = 800
UNSPLASH_KEY  = os.getenv("UNSPLASH_KEY", "")


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


def main():
    if not NEWS_FILE.exists():
        print(f"❌ 找不到新聞檔：{NEWS_FILE}", file=sys.stderr)
        sys.exit(1)

    data  = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data["items"]
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)

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

            # ── 方法 0：OG image（最快、最高品質、最不怕反爬）─────────
            if url:
                ok, og_source = fetch_hero_image(url, shot_path)
                if ok:
                    size_kb = shot_path.stat().st_size // 1024
                    print(f"  [{i}] ✅ {og_source} ({size_kb}KB)")
                    continue

            # ── 方法 1：Playwright 截圖（OG 失敗 fallback）────────────
            if url:
                print(f"  [{i}] 截圖：{url[:80]}...")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)   # 等 JS 渲染
                    # 嘗試關掉 cookie/訂閱彈窗
                    for sel in ["button[id*='cookie']", "button[class*='close']",
                                "button[aria-label*='Close']", "button[aria-label*='close']",
                                "[class*='modal'] button", "[id*='popup'] button"]:
                        try:
                            btn = page.query_selector(sel)
                            if btn and btn.is_visible():
                                btn.click()
                                page.wait_for_timeout(500)
                                break
                        except Exception:
                            pass
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(path=str(shot_path), full_page=False)

                    # 檢查截圖大小
                    size = shot_path.stat().st_size
                    if size < 25_000:
                        print(f"    ⚠️  截圖疑似空白（{size//1024}KB），嘗試備案...")
                        shot_path.unlink(missing_ok=True)
                    else:
                        print(f"  [{i}] ✅ 截圖成功 ({size//1024}KB)")
                        continue
                except Exception as e:
                    print(f"  [{i}] ⚠️ 截圖失敗：{e}")

            # ── 方法 2：Unsplash 搜圖（最後 fallback）──────────────────
            keyword = item.get("title") or item.get("hook") or "technology news"
            print(f"    🔍 Unsplash 搜圖：{keyword[:40]}...")
            if _unsplash_fallback(keyword, shot_path):
                print(f"  [{i}] ✅ Unsplash 備案成功")
            else:
                print(f"  [{i}] ℹ️  無法取得圖片，video_composer 將補漸層佔位圖")

        browser.close()

    print("✅ 截圖步驟完成")


if __name__ == "__main__":
    main()
