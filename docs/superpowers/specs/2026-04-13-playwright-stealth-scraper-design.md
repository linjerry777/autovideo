# Playwright Stealth Scraper — Design Spec

**Date:** 2026-04-13  
**Project:** AutoVideo  
**Author:** Jerry Lin

---

## 1. 目標

為 AutoVideo pipeline 的 Step 2（背景素材抓取）新增 `playwright_stealth` 模式。  
使用 Node.js `playwright-extra` + `playwright-extra-plugin-stealth` 取代現有的無 stealth Playwright 截圖，同時擷取：

- 全頁截圖（取代 screenshotone.com + 解決付費牆問題）
- 新聞頁面內的高解析度圖片
- 新聞頁面內的嵌入影片（`<video>` src + YouTube iframe）

---

## 2. 架構概覽

```
AutoVideo/
├── scraper/                        ← 新增（Node.js）
│   ├── package.json
│   └── index.js                    ← CLI 進入點，接受 --pipe-dir 參數
│
├── scripts/
│   ├── playwright_scraper.py       ← 新增：subprocess 橋接 Node scraper
│   ├── screenshot_collector.py     ← 保留不動（fallback）
│   └── broll_fetcher.py            ← 保留不動
│
└── web/
    └── job_runner.py               ← 新增 playwright_stealth 分支
```

---

## 3. Node.js Scraper（`scraper/index.js`）

### 3.1 執行方式

```bash
node scraper/index.js --pipe-dir "pipeline/2026-04-13/job_1"
```

讀取 `{pipe-dir}/news.json`，對每篇新聞的 URL 進行訪問，輸出到 `{pipe-dir}/screenshots/`。

### 3.2 反偵測設定

```js
const { chromium } = require('playwright-extra')
const stealth = require('playwright-extra-plugin-stealth')
chromium.use(stealth())

const browser = await chromium.launch({ headless: false })  // headless:false 更難偵測
const context = await browser.newContext({
  userAgent: '...真實 UA...',
  viewport: { width: 1280, height: 800 },
  locale: 'zh-TW',
  timezoneId: 'Asia/Taipei',
})
```

### 3.3 每個 URL 的擷取流程

1. `page.goto(url)` + 等待 domcontentloaded
2. 關閉 cookie/popup 彈窗
3. **截圖** → `screenshots/news_{i:02d}.png`
4. **抓圖片**：`querySelectorAll('article img, .article img, main img')` 取 src，下載前 3 張 → `screenshots/news_{i:02d}_img_{j}.jpg`
5. **抓影片**：`querySelectorAll('video source, video[src]')` + YouTube iframe `src` → `screenshots/news_{i:02d}_vid_{j}.mp4`（若為 YouTube 記錄 URL 供後續處理）

### 3.4 輸出 manifest

每篇新聞輸出到 `screenshots/manifest.json`：

```json
[
  {
    "index": 1,
    "url": "https://...",
    "title": "...",
    "screenshot": "screenshots/news_01.png",
    "images": ["screenshots/news_01_img_0.jpg"],
    "videos": ["screenshots/news_01_vid_0.mp4"],
    "youtube_urls": ["https://youtube.com/watch?v=..."]
  }
]
```

---

## 4. Python 橋接（`scripts/playwright_scraper.py`）

```
scripts/playwright_scraper.py {job_key}
```

流程：
1. 確認 `scraper/node_modules` 存在；若無，執行 `npm install` in `scraper/`
2. `subprocess.run(['node', 'scraper/index.js', '--pipe-dir', pipe_dir])`
3. 若 Node 退出碼非 0，印出錯誤並 `sys.exit(1)`
4. 確認 `screenshots/manifest.json` 存在，否則 `sys.exit(1)`

---

## 5. job_runner.py 整合

**修改位置：** `web/job_runner.py` Line 224–238

```python
bg_mode = get_setting("background_mode", "screenshot")
su("screenshot", "running")
if bg_mode == "broll":
    ok, out = _call_script("broll_fetcher.py", job_key, [], log_path)
    if not ok:
        ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)
elif bg_mode == "playwright_stealth":
    ok, out = _call_script("playwright_scraper.py", job_key, [], log_path)
    if not ok:
        # fallback 到原有截圖
        ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)
else:
    ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)
```

---

## 6. 設定方式

後台 Settings 新增選項（`web/routes/settings.py` + 前端 Settings 頁）：

```
background_mode = "screenshot" | "broll" | "playwright_stealth"
```

或直接在 DB 手動設定（初期）：

```sql
UPDATE settings SET value = 'playwright_stealth' WHERE key = 'background_mode';
```

---

## 7. 安裝需求

```bash
# Node.js scraper 依賴
cd AutoVideo/scraper
npm install playwright-extra playwright-extra-plugin-stealth playwright

# 安裝 Chromium
npx playwright install chromium
```

Python 端不需新增依賴（用 subprocess 呼叫 Node）。

---

## 8. 不在此 spec 範圍內

- YouTube 影片下載（yt-dlp 整合）→ 後續 Phase 2
- 自動排程觸發 scraper → 後續 Phase 2（目前手動在前端觸發）
- 前端 Settings UI 新增 background_mode 選項 → 後續
- 影片合成使用抓到的影片素材（目前 video_composer.py 只吃圖片）→ 後續

---

## 9. 成功標準

- [ ] `node scraper/index.js --pipe-dir pipeline/test/job_1` 可獨立跑通
- [ ] 對 3 個新聞 URL 各產出截圖 + 至少 1 張圖片
- [ ] `playwright_scraper.py` 作為 `_call_script` 正確呼叫並拿到 manifest
- [ ] 設定 `background_mode=playwright_stealth` 後，跑一次完整 job 成功產出影片
