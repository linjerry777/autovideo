#!/usr/bin/env python3
"""
scripts/playwright_scraper.py — Python → Node.js Playwright stealth 橋接
用法: python playwright_scraper.py {job_key}
  job_key: e.g. "2026-04-13/job_1"
"""
import io, json, subprocess, sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR    = Path(__file__).parent.parent
SCRAPER_DIR = BASE_DIR / "scraper"

TODAY = sys.argv[1] if len(sys.argv) > 1 else ""
if not TODAY:
    print("❌ 缺少 job_key 參數", file=sys.stderr)
    sys.exit(1)

PIPE_DIR = BASE_DIR / "pipeline" / TODAY


def ensure_deps():
    """若 node_modules 不存在則執行 npm install"""
    nm = SCRAPER_DIR / "node_modules"
    if not nm.exists():
        print("📦 Installing Node.js dependencies...")
        result = subprocess.run(
            ["npm", "install"],
            cwd=str(SCRAPER_DIR),
            capture_output=True, text=True, encoding="utf-8"
        )
        if result.returncode != 0:
            print(f"❌ npm install 失敗:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)
        print("✅ npm install 完成")


def run_scraper():
    print(f"🚀 啟動 Playwright stealth scraper: {PIPE_DIR}")
    result = subprocess.run(
        ["node", str(SCRAPER_DIR / "index.js"), "--pipe-dir", str(PIPE_DIR)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300  # 5 分鐘上限
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        print(f"❌ Node scraper 失敗（exit {result.returncode}）", file=sys.stderr)
        sys.exit(1)


def verify_manifest():
    manifest_path = PIPE_DIR / "screenshots" / "manifest.json"
    if not manifest_path.exists():
        print("❌ manifest.json 未產生，scraper 可能無輸出", file=sys.stderr)
        sys.exit(1)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    has_screenshot = any(e.get("screenshot") for e in data)
    if not has_screenshot:
        print("⚠️  警告：所有頁面截圖均失敗，後續步驟將使用 fallback")
    print(f"✅ Playwright scraper 完成，{len(data)} 篇新聞")


def override_youtube_thumbnails():
    """Post-process: for any item whose URL is YouTube, replace the page screenshot
    with the clean YT thumbnail (maxresdefault.jpg). Mirrors screenshot_collector's
    shortcut so the playwright_stealth background_mode also gets clean YT visuals.
    """
    news_file = PIPE_DIR / "news.json"
    if not news_file.exists():
        return
    try:
        import sys as _sys
        _script_dir = str(Path(__file__).resolve().parent)
        if _script_dir not in _sys.path:
            _sys.path.insert(0, _script_dir)
        from screenshot_collector import _youtube_thumbnail
    except ImportError as e:
        print(f"  [override] import failed: {e}", file=sys.stderr)
        return

    data  = json.loads(news_file.read_text(encoding="utf-8"))
    items = data.get("items", [])
    shots_dir = PIPE_DIR / "screenshots"
    overridden = 0
    for i, it in enumerate(items, 1):
        url = it.get("source_url") or it.get("url") or ""
        shot_path = shots_dir / f"news_{i:02d}.png"
        ok, src = _youtube_thumbnail(url, shot_path)
        if ok:
            print(f"  [{i}] 🔄 覆蓋為乾淨 YT thumbnail ({src})")
            overridden += 1
    if overridden:
        print(f"✅ {overridden} 張 YT 頁截圖已換成 thumbnail")


if __name__ == "__main__":
    ensure_deps()
    run_scraper()
    verify_manifest()
    override_youtube_thumbnails()
