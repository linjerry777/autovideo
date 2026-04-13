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


if __name__ == "__main__":
    ensure_deps()
    run_scraper()
    verify_manifest()
