# Trending Shorts Pipeline — Design Spec

## Goal

新增「趨勢模式」到現有「生成影片」頁，讓使用者從 Reddit / YouTube / PTT 等平台的 hot feed 選題，AI 自動分析格式與帳號分類，產出原創短影音並上傳至對應帳號。與現有新聞 pipeline 完全獨立，共用渲染與上傳基礎設施。

## Architecture

```
[ 生成影片 ] 頁
    ├── Tab: 📰 新聞模式  (現有，不動)
    └── Tab: 🔥 趨勢模式  (新增)
              │
              ▼
         Step 1: 選趨勢來源 (Reddit/YouTube/PTT/Bilibili/知乎)
              │  不需關鍵字，直接抓 hot feed
              ▼
         Step 2: 選內容 (共用現有 UI，勾 1-5 則)
              │
              ▼
         Step 3: AI 分析 → enrich_trending_items()
              │  輸出：格式 + 帳號分類 + 腳本
              ▼
         Step 4: 確認 & 修改 (使用者可改格式/帳號/腳本)
              │
              ▼
         Step 5: 送出 → job_runner.trigger_job(account_profile=...)
                        (沿用現有渲染 + 上傳)
```

## Components

### 1. `web/claude_client.py` — `enrich_trending_items()`

輸入：趨勢項目清單 `[{title, summary, url, source, source_type}, ...]`

輸出：每則一個物件：
```json
{
  "format":           "top5 | explainer | reaction | story",
  "category":         "tech | entertainment | finance",
  "hook":             "開場鉤子（5-8字）",
  "title":            "標題（15字以內）",
  "script":           "腳本（依格式結構生成）",
  "scene_type":       "fire | robot | money | ...",
  "account_suggestion": "科技帳號 | 娛樂帳號 | 財經帳號"
}
```

**四種格式的腳本結構：**
- `top5`：「第5是...第4是...第1竟然是...」排名揭曉節奏
- `explainer`：「你知道嗎？X其實是...背後原因是...」教育科普節奏
- `reaction`：「全網都在討論X，但沒人告訴你...」反應評論節奏
- `story`：「他靠這個方法...結果...」敘事案例節奏

**分類邏輯：**
- `tech`：AI、科技、軟體、遊戲、電腦
- `entertainment`：影視、音樂、運動、迷因、名人、奇聞
- `finance`：投資、市場、創業、經濟、公司財報

### 2. `web/routes/settings.py` — 帳號 profile 對應

新增三個設定欄位（存 DB，對應 Upload-Post profile 名稱）：

| 欄位 | 說明 |
|------|------|
| `trending_profile_tech` | 科技帳號的 Upload-Post profile 名 |
| `trending_profile_entertainment` | 娛樂帳號的 Upload-Post profile 名 |
| `trending_profile_finance` | 財經帳號的 Upload-Post profile 名 |

### 3. `web/routes/jobs.py` — trigger 加 `account_profile`

`POST /api/jobs/trigger` 加選填參數 `account_profile: str`，覆蓋 Upload-Post 使用的 profile。

### 4. `web/static/index.html` — UI

**Tab 切換器**（生成影片頁頂部）：
```
[ 📰 新聞模式 ]  [ 🔥 趨勢模式 ]
```

**趨勢模式 Step 1**：
- 來源選擇只顯示趨勢來源（Reddit / YouTube TW / YouTube US / PTT / Bilibili / 知乎）
- 無關鍵字欄位
- 「抓取趨勢」按鈕

**趨勢模式 Step 3（新）— 格式 & 帳號確認**：
每則選中的內容顯示一張確認卡：
```
┌─────────────────────────────────────────┐
│ [reaction]  [娛樂帳號 ▾]               │
│ 標題：...                               │
│ 腳本：...（可編輯 textarea）            │
└─────────────────────────────────────────┘
```
- format badge 可點擊改格式（top5 / explainer / reaction / story）
- 帳號 badge 可點擊改成其他帳號
- 腳本 textarea 可直接編輯

## Data Flow

```
使用者勾選 trending items
    ↓ POST /api/trending/enrich  (新 endpoint)
    ↓ enrich_trending_items() → Claude
    ↓ 回傳 enriched items 給前端暫存
使用者確認/修改
    ↓ POST /api/jobs/trigger (per item)
    ↓ { cache_ids, account_profile, ... }
    ↓ job_runner → 現有 pipeline
```

## Settings UI 新增欄位

設定頁「帳號路由」新區塊：
```
科技帳號 (Upload-Post profile):     [________]
娛樂帳號 (Upload-Post profile):     [________]
財經帳號 (Upload-Post profile):     [________]
```

## Files Changed

| 檔案 | 變動 |
|------|------|
| `web/claude_client.py` | 新增 `enrich_trending_items()` |
| `web/routes/trending.py` | 新增，POST /api/trending/enrich |
| `web/routes/jobs.py` | trigger 加 `account_profile` 參數 |
| `web/routes/settings.py` | 加三個 profile 欄位 |
| `web/app.py` | 註冊 trending router |
| `web/static/index.html` | Tab UI + 趨勢 Step 1 + Step 3 確認卡 |

## Out of Scope

- 排程自動抓趨勢（手動觸發即可，未來再加）
- 多語言腳本（全中文）
- 新建帳號流程（帳號由使用者在 Upload-Post 自行建立）
