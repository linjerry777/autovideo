# Playwright Stealth Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `playwright_stealth` 背景素材模式，使用 Node.js playwright-extra + stealth plugin，從新聞 URL 擷取截圖、頁面圖片、嵌入影片，取代現有無 stealth 的 screenshot_collector.py。

**Architecture:** Python `_call_script` 呼叫 `scripts/playwright_scraper.py`，該腳本再用 subprocess 呼叫 `node scraper/index.js`。Node 腳本讀取 `pipeline/{job_key}/news.json`，對每篇新聞 URL 啟動 stealth 瀏覽器，擷取截圖+圖片+影片，輸出到 `pipeline/{job_key}/screenshots/`，最後寫出 `manifest.json`。`job_runner.py` 在 `bg_mode == "playwright_stealth"` 時呼叫此腳本。

**Tech Stack:** Node.js 22, playwright-extra, playwright-extra-plugin-stealth, playwright (Chromium); Python 3.11, subprocess

---

## File Map

| 動作 | 路徑 | 說明 |
|------|------|------|
| Create | `scraper/package.json` | Node.js 套件宣告 |
| Create | `scraper/index.js` | Stealth 瀏覽器 CLI 進入點 |
| Create | `scripts/playwright_scraper.py` | Python → Node subprocess 橋接 |
| Modify | `web/job_runner.py:224-238` | 新增 playwright_stealth 分支 |
| Modify | `web/routes/settings.py:18` | SettingsUpdate 新增 playwright_stealth 選項說明 |

---

## Task 1: Node.js 專案初始化 + 套件安裝

**Files:**
- Create: `scraper/package.json`

- [ ] **Step 1: 建立 `scraper/package.json`**

```json
{
  "name": "autovideo-scraper",
  "version": "1.0.0",
  "description": "Playwright stealth scraper for AutoVideo pipeline",
  "main": "index.js",
  "scripts": {
    "scrape": "node index.js"
  },
  "dependencies": {
    "playwright-extra": "^4.3.6",
    "playwright-extra-plugin-stealth": "^2.11.2",
    "playwright": "^1.44.0"
  }
}
```

- [ ] **Step 2: 安裝 npm 依賴**

```bash
cd AutoVideo/scraper
npm install
npx playwright install chromium
```

預期輸出：`added N packages` + `Chromium X.X.X downloaded`

- [ ] **Step 3: 確認安裝成功**

```bash
node -e "require('playwright-extra'); require('playwright-extra-plugin-stealth'); console.log('OK')"
```

預期輸出：`OK`

- [ ] **Step 4: Commit**

```bash
cd AutoVideo
git add scraper/package.json scraper/package-lock.json
git commit -m "chore: init playwright-extra stealth scraper node project"
```

---

## Task 2: Node.js Stealth Scraper 主體

**Files:**
- Create: `scraper/index.js`

- [ ] **Step 1: 建立 `scraper/index.js`**

```js
#!/usr/bin/env node
/**
 * AutoVideo Playwright Stealth Scraper
 * Usage: node index.js --pipe-dir "pipeline/2026-04-13/job_1"
 *
 * Reads:  {pipe-dir}/news.json
 * Writes: {pipe-dir}/screenshots/news_01.png
 *         {pipe-dir}/screenshots/news_01_img_0.jpg
 *         {pipe-dir}/screenshots/news_01_vid_0.mp4 (if downloadable)
 *         {pipe-dir}/screenshots/manifest.json
 */

const { chromium } = require('playwright-extra');
const stealth = require('playwright-extra-plugin-stealth');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const { URL } = require('url');

chromium.use(stealth());

// ── CLI args ──────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const pipeDirIdx = args.indexOf('--pipe-dir');
if (pipeDirIdx === -1 || !args[pipeDirIdx + 1]) {
  console.error('Usage: node index.js --pipe-dir <path>');
  process.exit(1);
}
const PIPE_DIR = path.resolve(args[pipeDirIdx + 1]);
const NEWS_FILE = path.join(PIPE_DIR, 'news.json');
const SHOTS_DIR = path.join(PIPE_DIR, 'screenshots');

if (!fs.existsSync(NEWS_FILE)) {
  console.error(`news.json not found: ${NEWS_FILE}`);
  process.exit(1);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const proto = url.startsWith('https') ? https : http;
    const file = fs.createWriteStream(dest);
    proto.get(url, { timeout: 15000 }, res => {
      if (res.statusCode !== 200) {
        file.close();
        fs.unlink(dest, () => {});
        return reject(new Error(`HTTP ${res.statusCode}`));
      }
      res.pipe(file);
      file.on('finish', () => file.close(resolve));
    }).on('error', err => {
      file.close();
      fs.unlink(dest, () => {});
      reject(err);
    });
  });
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function dismissPopups(page) {
  const selectors = [
    "button[id*='cookie']",
    "button[class*='close']",
    "button[aria-label*='Close']",
    "button[aria-label*='close']",
    "[class*='modal'] button",
    "[id*='popup'] button",
    "[class*='subscribe'] button[class*='close']",
  ];
  for (const sel of selectors) {
    try {
      const btn = await page.$(sel);
      if (btn && await btn.isVisible()) {
        await btn.click();
        await sleep(400);
        break;
      }
    } catch (_) {}
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────
(async () => {
  fs.mkdirSync(SHOTS_DIR, { recursive: true });

  const newsData = JSON.parse(fs.readFileSync(NEWS_FILE, 'utf-8'));
  const items = newsData.items || [];

  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    viewport: { width: 1280, height: 800 },
    locale: 'zh-TW',
    timezoneId: 'Asia/Taipei',
  });

  // 封鎖廣告 + 字體加速載入
  await context.route(/\.(woff2?|ttf|otf|gif|svg)(\?.*)?$/, r => r.abort());
  await context.route(/\/(ads|analytics|tracker|gtm)\//i, r => r.abort());

  const manifest = [];

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const idx  = String(i + 1).padStart(2, '0');
    const url  = item.source_url || item.url || '';
    const title = item.title || item.hook || '';

    const entry = { index: i + 1, url, title, screenshot: null, images: [], videos: [], youtube_urls: [] };

    if (!url) {
      console.log(`[${idx}] 無 URL，跳過`);
      manifest.push(entry);
      continue;
    }

    const page = await context.newPage();
    try {
      console.log(`[${idx}] 訪問: ${url.slice(0, 80)}...`);
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await sleep(2500 + Math.random() * 1000);  // 模擬人類等待
      await dismissPopups(page);
      await page.evaluate(() => window.scrollTo(0, 0));

      // ── 截圖 ────────────────────────────────────────────────────────────
      const shotPath = path.join(SHOTS_DIR, `news_${idx}.png`);
      await page.screenshot({ path: shotPath, fullPage: false });
      const shotSize = fs.statSync(shotPath).size;
      if (shotSize < 25000) {
        console.log(`  ⚠️  截圖疑似空白 (${Math.round(shotSize/1024)}KB)，略過`);
        fs.unlinkSync(shotPath);
      } else {
        console.log(`  ✅ 截圖 ${Math.round(shotSize/1024)}KB`);
        entry.screenshot = `screenshots/news_${idx}.png`;
      }

      // ── 抓頁面圖片（最多 3 張）─────────────────────────────────────────
      const imgSrcs = await page.evaluate(() => {
        const imgs = Array.from(document.querySelectorAll(
          'article img[src], .article img[src], main img[src], .content img[src]'
        ));
        return imgs
          .map(el => el.src)
          .filter(src => src && src.startsWith('http') && !src.includes('icon') && !src.includes('logo'))
          .slice(0, 3);
      });

      for (let j = 0; j < imgSrcs.length; j++) {
        const imgPath = path.join(SHOTS_DIR, `news_${idx}_img_${j}.jpg`);
        try {
          await downloadFile(imgSrcs[j], imgPath);
          const imgSize = fs.statSync(imgPath).size;
          if (imgSize > 10000) {
            entry.images.push(`screenshots/news_${idx}_img_${j}.jpg`);
            console.log(`  📷 圖片 ${j}: ${Math.round(imgSize/1024)}KB`);
          } else {
            fs.unlinkSync(imgPath);
          }
        } catch (e) {
          console.log(`  ⚠️  圖片 ${j} 下載失敗: ${e.message}`);
        }
      }

      // ── 抓嵌入影片 ──────────────────────────────────────────────────────
      const vidData = await page.evaluate(() => {
        const videoEls = Array.from(document.querySelectorAll('video[src], video source[src]'));
        const videoSrcs = videoEls.map(el => el.src).filter(Boolean).slice(0, 2);

        const iframes = Array.from(document.querySelectorAll('iframe[src]'));
        const ytUrls = iframes
          .map(el => el.src)
          .filter(src => src.includes('youtube.com') || src.includes('youtu.be'))
          .slice(0, 2);

        return { videoSrcs, ytUrls };
      });

      for (let j = 0; j < vidData.videoSrcs.length; j++) {
        const vidPath = path.join(SHOTS_DIR, `news_${idx}_vid_${j}.mp4`);
        try {
          await downloadFile(vidData.videoSrcs[j], vidPath);
          const vidSize = fs.statSync(vidPath).size;
          if (vidSize > 50000) {
            entry.videos.push(`screenshots/news_${idx}_vid_${j}.mp4`);
            console.log(`  🎬 影片 ${j}: ${Math.round(vidSize/1024)}KB`);
          } else {
            fs.unlinkSync(vidPath);
          }
        } catch (e) {
          console.log(`  ⚠️  影片 ${j} 下載失敗: ${e.message}`);
        }
      }

      entry.youtube_urls = vidData.ytUrls;
      if (vidData.ytUrls.length > 0) {
        console.log(`  🎥 YouTube: ${vidData.ytUrls.join(', ')}`);
      }

    } catch (e) {
      console.log(`  ❌ 失敗: ${e.message}`);
    } finally {
      await page.close();
    }

    manifest.push(entry);
  }

  await browser.close();

  const manifestPath = path.join(SHOTS_DIR, 'manifest.json');
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf-8');
  console.log(`\n✅ 完成，manifest → ${manifestPath}`);
})();
```

- [ ] **Step 2: 手動測試 scraper（用一個真實 job_key）**

先確認 `pipeline/` 底下有一個 job 的 `news.json`：

```bash
ls AutoVideo/pipeline/
# 選一個存在的 job_key，例如 2026-04-13/job_1
node AutoVideo/scraper/index.js --pipe-dir AutoVideo/pipeline/2026-04-13/job_1
```

預期：
- `pipeline/2026-04-13/job_1/screenshots/news_01.png` 存在
- `pipeline/2026-04-13/job_1/screenshots/manifest.json` 存在且格式正確

若無現有 pipeline，用以下指令建立測試用 news.json：

```bash
mkdir -p AutoVideo/pipeline/test_stealth/job_0/screenshots
cat > AutoVideo/pipeline/test_stealth/job_0/news.json << 'EOF'
{
  "date": "test_stealth/job_0",
  "items": [
    {
      "title": "Euphoria Season 3 premieres",
      "url": "https://variety.com",
      "source_url": "https://variety.com"
    },
    {
      "title": "Coachella 2026",
      "url": "https://www.billboard.com",
      "source_url": "https://www.billboard.com"
    }
  ]
}
EOF
node AutoVideo/scraper/index.js --pipe-dir AutoVideo/pipeline/test_stealth/job_0
```

- [ ] **Step 3: 確認 manifest.json 格式**

```bash
cat AutoVideo/pipeline/test_stealth/job_0/screenshots/manifest.json
```

預期每個 entry 包含 `screenshot`、`images`、`videos`、`youtube_urls` 欄位。

- [ ] **Step 4: Commit**

```bash
cd AutoVideo
git add scraper/index.js
git commit -m "feat: add playwright-extra stealth scraper node script"
```

---

## Task 3: Python 橋接腳本

**Files:**
- Create: `scripts/playwright_scraper.py`

- [ ] **Step 1: 建立 `scripts/playwright_scraper.py`**

```python
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

BASE_DIR   = Path(__file__).parent.parent
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
    # 印出 Node 的輸出
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
```

- [ ] **Step 2: 手動測試 Python 橋接**

```bash
cd AutoVideo
python scripts/playwright_scraper.py test_stealth/job_0
```

預期輸出：
```
🚀 啟動 Playwright stealth scraper: ...
[01] 訪問: https://variety.com...
  ✅ 截圖 XXX KB
...
✅ Playwright scraper 完成，2 篇新聞
```

- [ ] **Step 3: Commit**

```bash
git add scripts/playwright_scraper.py
git commit -m "feat: add python bridge for playwright stealth scraper"
```

---

## Task 4: job_runner.py 整合

**Files:**
- Modify: `web/job_runner.py:224-238`

- [ ] **Step 1: 讀取目前 job_runner.py 的 screenshot 段落（Line 224–238）確認位置**

```python
# 目前的程式碼（大約在 Line 224-238）：
bg_mode = get_setting("background_mode", "screenshot")
su("screenshot", "running")
if bg_mode == "broll":
    ok, out = _call_script("broll_fetcher.py", job_key, [], log_path)
    if not ok:
        # B-roll 抓取失敗不是致命錯誤：fallback 到截圖
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n[WARN] B-roll 失敗，改用截圖模式\n")
        ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)
else:
    ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)
```

- [ ] **Step 2: 修改為三分支邏輯（加入 playwright_stealth）**

將上述段落改為：

```python
bg_mode = get_setting("background_mode", "screenshot")
su("screenshot", "running")
if bg_mode == "broll":
    ok, out = _call_script("broll_fetcher.py", job_key, [], log_path)
    if not ok:
        # B-roll 抓取失敗不是致命錯誤：fallback 到截圖
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n[WARN] B-roll 失敗，改用截圖模式\n")
        ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)
elif bg_mode == "playwright_stealth":
    ok, out = _call_script("playwright_scraper.py", job_key, [], log_path)
    if not ok:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n[WARN] Playwright stealth 失敗，改用截圖模式\n")
        ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)
else:
    ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)
```

- [ ] **Step 3: 更新 settings.py 的 SettingsUpdate 型別說明**

在 `web/routes/settings.py` 的 `background_mode` 欄位說明加上 playwright_stealth：

```python
# 背景模式
background_mode: str | None = None   # "screenshot" | "broll" | "playwright_stealth"
```

- [ ] **Step 4: Commit**

```bash
git add web/job_runner.py web/routes/settings.py
git commit -m "feat: add playwright_stealth background mode to job_runner"
```

---

## Task 5: 端對端驗證

- [ ] **Step 1: 啟動 Python 後端**

```bash
cd AutoVideo
python -m uvicorn web.app:app --reload --port 8000
```

- [ ] **Step 2: 用 curl 或前端設定 background_mode**

```bash
curl -X PUT http://localhost:8000/api/settings \
  -H "Content-Type: application/json" \
  -d '{"background_mode": "playwright_stealth"}'
```

預期回應包含 `"background_mode": "playwright_stealth"`

- [ ] **Step 3: 前端觸發一個新 job，使用現有新聞**

在瀏覽器打開 `http://localhost:3000`（或後端前端的 URL），選幾則新聞，按「開始生成」。

- [ ] **Step 4: 觀察 job log 確認 scraper 執行**

```bash
# 找最新的 job log
ls -lt AutoVideo/pipeline/*/job_*/run.log | head -1
cat AutoVideo/pipeline/<date>/job_<id>/run.log
```

預期 log 中出現：
```
=== playwright_scraper.py ===
🚀 啟動 Playwright stealth scraper: ...
✅ Playwright scraper 完成，N 篇新聞
```

- [ ] **Step 5: 確認截圖產出**

```bash
ls AutoVideo/pipeline/<date>/job_<id>/screenshots/
# 應出現 news_01.png, manifest.json 等
```

- [ ] **Step 6: 讓 job 跑完，確認影片正常生成**

job 完成後，確認 `pipeline/<date>/job_<id>/output.mp4` 存在且可播放。

- [ ] **Step 7: 最終 commit**

```bash
cd AutoVideo
git add .
git commit -m "feat: playwright stealth scraper end-to-end verified"
```

---

## 錯誤排查速查

| 錯誤 | 原因 | 解法 |
|------|------|------|
| `Cannot find module 'playwright-extra'` | npm install 未執行 | `cd scraper && npm install` |
| `Executable doesn't exist at ...chromium` | Playwright Chromium 未安裝 | `cd scraper && npx playwright install chromium` |
| `node: command not found` | PATH 問題 | 確認 `node --version` 可執行 |
| 截圖全部 `< 25KB` | 頁面被擋（paywall/bot check） | 正常現象，`manifest.json` 仍會寫出 |
| `manifest.json 未產生` | Node 腳本 crash | 看 `run.log` 的 Node stderr |
