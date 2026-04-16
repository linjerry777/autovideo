# Trending Shorts Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在「生成影片」頁加入「🔥 趨勢模式」Tab，讓使用者從 Reddit/YouTube/PTT 選題，AI 自動分析格式（top5/explainer/reaction/story）與帳號分類，產出原創短影音並上傳對應帳號。

**Architecture:** 新增 `enrich_trending_items()` 函數（同 `enrich_news_items()` 模式），透過新的 `/api/trending/enrich` endpoint 讓前端呼叫。`TriggerRequest` 加入 `account_profile` 欄位，傳遞給 `publisher.py --profile`。UI 在現有「生成影片」頁頂部加 tab 切換，趨勢模式有自己的 Step 1（選來源）和 Step 3（確認格式+帳號）。

**Tech Stack:** Python/FastAPI, Alpine.js, SQLite, Claude API (via claude_client.py), Upload-Post SDK

---

## File Map

| 檔案 | 動作 | 說明 |
|------|------|------|
| `web/claude_client.py` | Modify | 新增 `enrich_trending_items()` |
| `web/routes/trending.py` | Create | POST /api/trending/enrich |
| `web/routes/jobs.py` | Modify | TriggerRequest 加 `account_profile` |
| `web/job_runner.py` | Modify | `_run_pipeline` + `trigger_job` 加 `account_profile` |
| `scripts/publisher.py` | Modify | 加 `--profile` CLI 參數 |
| `web/routes/settings.py` | Modify | 加三個 profile 欄位 |
| `web/app.py` | Modify | 註冊 trending router |
| `web/static/index.html` | Modify | Tab UI + 趨勢 Step 1 + Step 3 確認卡 |

---

## Task 1: `enrich_trending_items()` in claude_client.py

**Files:**
- Modify: `web/claude_client.py` (after `enrich_news_items()`, around line 113)

- [ ] **Step 1: 在 `web/claude_client.py` 結尾加入函數**

```python
def enrich_trending_items(raw_items: list[dict]) -> list[dict]:
    """
    raw_items: [{title, summary, url, source, source_type}, ...]
    回傳: [{format, category, hook, title, script, scene_type,
            source_url, source_name, account_suggestion}, ...]

    format: top5 | explainer | reaction | story
    category: tech | entertainment | finance
    """
    lines = "\n".join([
        f"{i+1}. [{it.get('source','')}] {it['title']}\n   {it.get('summary','')[:120]}"
        for i, it in enumerate(raw_items)
    ])

    prompt = f"""請使用繁體中文回答。
以下是從社群平台抓取的熱門話題，請為每則選擇最適合的短影音格式，並生成對應腳本。

{lines}

格式說明：
- top5：排名揭曉節奏「第5是...第1竟然是...」（適合列舉、比較類話題）
- explainer：教育科普節奏「你知道嗎？X其實是...背後原因是...」（適合知識、解釋類）
- reaction：反應評論節奏「全網都在討論X，但沒人告訴你...」（適合爭議、驚訝類）
- story：敘事案例節奏「他靠這個方法...結果...」（適合人物、事件類）

分類說明：
- tech：AI、科技、軟體、遊戲、電腦相關
- entertainment：影視、音樂、運動、迷因、名人、奇聞
- finance：投資、市場、創業、經濟、公司

每則請用以下 JSON 格式（照順序）：
{{
  "format": "top5 | explainer | reaction | story 擇一",
  "category": "tech | entertainment | finance 擇一",
  "hook": "開場鉤子（5-8字，製造懸念或衝擊）",
  "title": "標題（15字以內，中文）",
  "script": "旁白腳本（80字以內，依格式結構生成，像在跟朋友說話）",
  "scene_type": "動畫場景：fire/race/money/robot/warning/trophy/default 擇一",
  "account_suggestion": "科技帳號 | 娛樂帳號 | 財經帳號 擇一",
  "source_url": "原始 URL",
  "source_name": "來源名稱"
}}

請直接回傳 JSON 陣列，不要加任何其他文字或 markdown。"""

    raw, usage = call_claude(prompt)
    if not raw:
        raise ValueError("Claude 回傳空白內容")
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        raw = match.group(0)
    else:
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw.strip())
    try:
        items = json.loads(raw)
        if isinstance(items, dict):
            items = [items]
        _last_usage.update(usage)
        return items
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude 回傳無效 JSON：{e}\n原始內容：{raw[:300]}")
```

- [ ] **Step 2: 快速煙霧測試（不真的呼叫 Claude）**

```python
# 在 Python REPL 確認 import 沒報錯
python -c "from web.claude_client import enrich_trending_items; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add web/claude_client.py
git commit -m "feat: add enrich_trending_items() for format+category analysis"
```

---

## Task 2: `web/routes/trending.py` — POST /api/trending/enrich

**Files:**
- Create: `web/routes/trending.py`

- [ ] **Step 1: 建立檔案**

```python
"""
web/routes/trending.py — Trending content enrichment endpoint
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/trending")


class EnrichRequest(BaseModel):
    items: list[dict]   # [{title, summary, url, source, source_type}, ...]


@router.post("/enrich")
def enrich_trending(req: EnrichRequest):
    """
    Call Claude to analyze trending items and assign format + account category.
    Input:  [{title, summary, url, source, source_type}, ...]
    Output: [{format, category, hook, title, script, scene_type,
              account_suggestion, source_url, source_name}, ...]
    """
    if not req.items:
        raise HTTPException(400, "items 不能為空")
    if len(req.items) > 5:
        raise HTTPException(400, "最多 5 則")

    from web.claude_client import enrich_trending_items
    try:
        enriched = enrich_trending_items(req.items)
    except Exception as e:
        raise HTTPException(500, f"Claude 分析失敗: {e}")

    return {"items": enriched}
```

- [ ] **Step 2: 在 `web/app.py` 註冊 router**

找到現有的 router 註冊區塊（約第 13 行）：
```python
from web.routes import jobs, events, media, settings, news, accounts
```
改成：
```python
from web.routes import jobs, events, media, settings, news, accounts, trending
```

並在 `app.include_router(accounts.router)` 之後加：
```python
app.include_router(trending.router)
```

- [ ] **Step 3: 測試 endpoint（server 需已啟動）**

```bash
curl -X POST http://localhost:8000/api/trending/enrich \
  -H "Content-Type: application/json" \
  -d '{"items":[{"title":"Reddit最熱遊戲討論","summary":"玩家熱議最難上手的遊戲","url":"https://reddit.com/r/gaming/xxx","source":"Reddit","source_type":"reddit"}]}'
```

Expected: `{"items":[{"format":"...","category":"...","hook":"...","title":"...","script":"...",...}]}`

- [ ] **Step 4: Commit**

```bash
git add web/routes/trending.py web/app.py
git commit -m "feat: add POST /api/trending/enrich endpoint"
```

---

## Task 3: `account_profile` 傳遞鏈 — jobs → job_runner → publisher

**Files:**
- Modify: `web/routes/jobs.py:43-51` (TriggerRequest)
- Modify: `web/job_runner.py:198-200` (_run_pipeline signature)
- Modify: `web/job_runner.py:348-361` (trigger_job signature)
- Modify: `scripts/publisher.py:116-125` (argparse)

- [ ] **Step 1: `TriggerRequest` 加 `account_profile` 欄位**

在 `web/routes/jobs.py` 的 `TriggerRequest`（約第 43 行）：
```python
class TriggerRequest(BaseModel):
    date:               str | None        = None
    topic:              str | None        = None
    lang:               str               = "zh-TW"
    platforms:          list[str]         = ["youtube", "instagram"]
    dry_run:            bool              = False
    selected_news:      list[dict] | None = None
    selected_cache_ids: list[int] | None  = None
    account_profile:    str | None        = None   # 覆蓋預設 Upload-Post profile
```

- [ ] **Step 2: `trigger()` endpoint 把 `account_profile` 傳下去**

在 `web/routes/jobs.py` 的 `trigger()` 函數，`trigger_job(...)` 呼叫處（約第 70 行）改為：
```python
    started = job_runner.trigger_job(
        job_id          = job_id,
        date            = run_date,
        topic           = req.topic,
        platforms       = req.platforms,
        dry_run         = dry_run,
        pre_news        = req.selected_news,
        account_profile = req.account_profile,
    )
```

- [ ] **Step 3: `trigger_job()` 加 `account_profile` 參數**

在 `web/job_runner.py` 的 `trigger_job()` 函數（約第 348 行）：
```python
def trigger_job(job_id: int, date: str, topic: str | None = None,
                platforms: list[str] = None, skip_upload: bool = False,
                dry_run: bool = False,
                pre_news: list[dict] | None = None,
                account_profile: str | None = None) -> bool:
    """Returns True if job was started, False if already running."""
    global _running_job_id
    if platforms is None:
        platforms = get_setting("platforms", "youtube,instagram").split(",")
    if not _lock.acquire(blocking=False):
        return False
    _running_job_id = job_id
    t = threading.Thread(
        target=_run_pipeline,
        args=(job_id, date, topic, platforms, skip_upload, dry_run, pre_news, account_profile),
        daemon=True,
    )
    t.start()
    return True
```

- [ ] **Step 4: `_run_pipeline()` 加 `account_profile`，存入 news.json metadata**

在 `web/job_runner.py` 的 `_run_pipeline()` 函數簽名（約第 198 行）：
```python
def _run_pipeline(job_id: int, date: str, topic: str | None,
                  platforms: list[str], skip_upload: bool, dry_run: bool,
                  pre_news: list[dict] | None = None,
                  account_profile: str | None = None):
```

在函數內 `news_file.write_text(...)` 寫入 news.json 的地方（pre_news 分支，約第 225 行），把 account_profile 一起寫進 metadata：
```python
            news_file.write_text(
                _json.dumps(
                    {"date": job_key, "account_profile": account_profile or "", "items": enriched},
                    ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
```

在 Step 5 上傳段（約第 321 行），把 account_profile 傳給 publisher：
```python
        # ── Step 5: 上傳 (需用戶手動觸發) ─────────────────────────
        output_mp4 = pipe_dir / "output.mp4"
        # 將 account_profile 存進 DB，上傳時使用
        if account_profile:
            update_job(job_id, topic=f"{topic or ''}|profile:{account_profile}")
        su("upload", "pending")
```

Wait — 更簡單的做法：把 account_profile 存在 job 的 `topic` 欄位是個 hack，改成正確做法：**存在 news.json，publisher.py 讀它**。

改寫 Step 4 publisher 呼叫（在 `web/routes/jobs.py` 的 `upload_job()`，約第 131 行）：
```python
    # 讀取 news.json 的 account_profile（若有）
    news_file = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "news.json"
    profile_override = ""
    if news_file.exists():
        try:
            import json as _j
            nd = _j.loads(news_file.read_text(encoding="utf-8"))
            profile_override = nd.get("account_profile", "")
        except Exception:
            pass

    plat_args = ["--platforms"] + platforms
    if dry_run:
        plat_args += ["--dry-run"]
    if profile_override:
        plat_args += ["--profile", profile_override]
```

- [ ] **Step 5: `scripts/publisher.py` 加 `--profile` 參數**

在 `scripts/publisher.py` 的 argparse 區塊（約第 116 行）加：
```python
    parser.add_argument("--profile", default=None,
                        help="Upload-Post profile 名稱（覆蓋 UPLOAD_POST_PROFILE env var）")
```

在 `args = parser.parse_args()` 之後（約第 128 行）加：
```python
    if args.profile:
        global PROFILE
        PROFILE = args.profile
```

- [ ] **Step 6: Commit**

```bash
git add web/routes/jobs.py web/job_runner.py scripts/publisher.py
git commit -m "feat: add account_profile routing through trigger→pipeline→publisher"
```

---

## Task 4: Settings — 三個 profile 欄位

**Files:**
- Modify: `web/routes/settings.py`
- Modify: `web/static/index.html`

- [ ] **Step 1: `SettingsUpdate` 加三個欄位**

在 `web/routes/settings.py` 的 `SettingsUpdate`（約第 39 行）加：
```python
    # Trending account profiles
    trending_profile_tech:          str | None = None
    trending_profile_entertainment: str | None = None
    trending_profile_finance:       str | None = None
```

- [ ] **Step 2: UI 設定頁加欄位**

在 `web/static/index.html` 的 `settingsFields` 陣列（約第 1343 行）加：
```javascript
      ['trending_profile_tech',          '趨勢 — 科技帳號 profile 名稱',  'text', 'tech_yt'],
      ['trending_profile_entertainment', '趨勢 — 娛樂帳號 profile 名稱',  'text', 'entertainment_yt'],
      ['trending_profile_finance',       '趨勢 — 財經帳號 profile 名稱',  'text', 'finance_yt'],
```

加在 `['pexels_api_key', ...]` 之後。

- [ ] **Step 3: Commit**

```bash
git add web/routes/settings.py web/static/index.html
git commit -m "feat: add trending account profile settings (tech/entertainment/finance)"
```

---

## Task 5: UI — Tab 切換 + 趨勢 Step 1

**Files:**
- Modify: `web/static/index.html`

> 背景知識：現有「生成影片」頁從 `newStep` 狀態機控制，值為 `config / fetching / select / triggering / pipeline`。趨勢模式加入 `trendingConfig / trendingFetching / trendingSelect / trendingAnalyzing / trendingConfirm` 五個新狀態，以及 `videoMode: 'news' | 'trending'` 切換變數。

- [ ] **Step 1: 加 `videoMode` 和趨勢狀態到 Alpine data**

找到 `newStep: 'config',`（約第 1297 行），在它後面加：
```javascript
    videoMode: 'news',          // 'news' | 'trending'
    trendingStep: 'config',     // config | fetching | select | analyzing | confirm
    trendingItems: [],          // 從 trending sources 抓到的原始項目
    trendingEnriched: [],       // Claude 分析後的結果（含 format/category/script）
    trendingSelectedIds: new Set(),
    trendingSelectedSources: new Set(['reddit', 'youtube_tw', 'bilibili']),
```

- [ ] **Step 2: 加 Tab 切換器 HTML**

找到「生成影片」頁的標題區塊（`<h1>` 或最上層 div，約第 296 行），在標題下方、Step 卡片上方加：
```html
      <!-- Mode Tab -->
      <div class="flex gap-1 p-1 bg-gray-100 rounded-xl w-fit mb-4">
        <button type="button"
          @click="videoMode='news'; newStep='config'"
          :class="videoMode==='news' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'"
          class="px-4 py-1.5 rounded-lg text-sm font-medium transition-all">
          📰 新聞模式
        </button>
        <button type="button"
          @click="videoMode='trending'; trendingStep='config'"
          :class="videoMode==='trending' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'"
          class="px-4 py-1.5 rounded-lg text-sm font-medium transition-all">
          🔥 趨勢模式
        </button>
      </div>
```

- [ ] **Step 3: 把現有新聞 UI 包在 `x-show="videoMode==='news'"`**

找到 `<div x-show="newStep==='config'"` 的**父容器**，在它外面用 `<div x-show="videoMode==='news'">` 包住整個新聞流程區塊，到 `</div>` 結束。

- [ ] **Step 4: 加趨勢模式 Step 1 (config) HTML**

在新聞模式 div 之後加趨勢模式整體容器：
```html
      <!-- ══ 趨勢模式 ══ -->
      <div x-show="videoMode==='trending'">

        <!-- Step 1: 選來源 -->
        <div x-show="trendingStep==='config'" class="glass rounded-2xl p-6 space-y-5">
          <div>
            <p class="text-[11px] text-gray-400 uppercase tracking-wide mb-2">趨勢來源（不需關鍵字，直接抓熱門）</p>
            <div class="flex flex-wrap gap-2">
              <template x-for="[id, icon, label] in [
                ['reddit','🤖','Reddit'],['youtube_tw','▶️','YouTube TW'],['youtube_us','▶️','YouTube US'],
                ['ptt','🏛️','PTT'],['bilibili','📺','Bilibili'],['zhihu','💬','知乎'],['dcard','🃏','Dcard']
              ]" :key="id">
                <button type="button" @click="trendingToggleSource(id)"
                  :class="trendingSelectedSources.has(id)
                    ? 'bg-orange-50 border-orange-300 text-orange-700 ring-1 ring-orange-200'
                    : 'bg-gray-50 border-gray-200 text-gray-400 hover:border-gray-300'"
                  class="border rounded-lg px-3 py-1.5 text-sm font-medium transition-all flex items-center gap-1">
                  <span x-show="trendingSelectedSources.has(id)" class="text-orange-600 text-xs">✓</span>
                  <span x-text="icon + ' ' + label"></span>
                </button>
              </template>
            </div>
          </div>
          <button @click="fetchTrending()"
            :disabled="trendingSelectedSources.size === 0"
            class="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-orange-500 text-white hover:bg-orange-600 transition-all">
            🔥 抓取趨勢
          </button>
        </div>

        <!-- Step 2: fetching -->
        <div x-show="trendingStep==='fetching'" class="glass rounded-2xl p-12 text-center">
          <div class="w-10 h-10 rounded-full border-2 border-orange-500 border-t-transparent animate-spin mx-auto mb-4"></div>
          <p class="text-sm text-gray-500">正在抓取熱門話題…</p>
        </div>

        <!-- Step 3: select (reuse same grouped UI) -->
        <div x-show="trendingStep==='select'" class="space-y-3">
          <div class="flex items-center justify-between">
            <p class="text-sm text-gray-600">選擇要製作的話題（最多 5 則）</p>
            <div class="flex gap-2">
              <span class="text-sm text-gray-400" x-text="`${trendingSelectedIds.size}/5 已選`"></span>
              <button @click="trendingStep='config'" class="text-xs text-gray-500 border border-gray-200 rounded-lg px-2.5 py-1 hover:border-gray-300">修改來源</button>
              <button @click="fetchTrending(true)" class="text-xs text-orange-600 border border-orange-200 rounded-lg px-2.5 py-1 hover:border-orange-300">🔄 重抓</button>
            </div>
          </div>
          <template x-for="group in groupedTrending()" :key="group.source_type">
            <div class="glass rounded-2xl overflow-hidden">
              <div class="flex items-center gap-2 px-4 py-2 border-b border-gray-100">
                <span class="text-xs font-semibold px-2 py-0.5 rounded-full border"
                  :class="(_sourceConfig[group.source_type]||{}).cls||'text-gray-600 bg-gray-100 border-gray-200'"
                  x-text="group.label"></span>
                <span class="text-xs text-gray-400" x-text="`${group.items.length} 則`"></span>
              </div>
              <div class="divide-y divide-gray-50 max-h-72 overflow-y-auto">
                <template x-for="item in group.items" :key="item.url || item.title">
                  <label class="flex items-start gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors"
                    :class="trendingSelectedIds.has(item.url || item.title) ? 'bg-orange-50' : ''">
                    <input type="checkbox" class="mt-1 accent-orange-500"
                      :disabled="!trendingSelectedIds.has(item.url || item.title) && trendingSelectedIds.size >= 5"
                      :checked="trendingSelectedIds.has(item.url || item.title)"
                      @change="trendingToggleItem(item)">
                    <div class="flex-1 min-w-0">
                      <p class="text-sm font-medium text-gray-800 line-clamp-2" x-text="item.title"></p>
                      <p class="text-xs text-gray-400 mt-0.5 truncate" x-text="item.summary"></p>
                    </div>
                  </label>
                </template>
              </div>
            </div>
          </template>
          <button @click="analyzeTrending()"
            :disabled="trendingSelectedIds.size === 0"
            :class="trendingSelectedIds.size === 0 ? 'opacity-40 cursor-not-allowed' : 'hover:bg-orange-600'"
            class="w-full py-3 rounded-xl text-sm font-semibold bg-orange-500 text-white transition-all">
            🤖 AI 分析格式與帳號（<span x-text="trendingSelectedIds.size"></span> 則）
          </button>
        </div>

        <!-- Step 4: analyzing -->
        <div x-show="trendingStep==='analyzing'" class="glass rounded-2xl p-12 text-center">
          <div class="w-10 h-10 rounded-full border-2 border-orange-500 border-t-transparent animate-spin mx-auto mb-4"></div>
          <p class="text-sm text-gray-500">Claude 分析格式與帳號分類中…</p>
        </div>

        <!-- Step 5: confirm -->
        <div x-show="trendingStep==='confirm'" class="space-y-4">
          <div class="flex items-center justify-between mb-2">
            <p class="text-sm font-medium text-gray-700">確認格式 & 帳號，可修改後送出</p>
            <button @click="trendingStep='select'" class="text-xs text-gray-500 border border-gray-200 rounded-lg px-2.5 py-1">← 重選</button>
          </div>
          <template x-for="(item, idx) in trendingEnriched" :key="idx">
            <div class="glass rounded-2xl p-5 space-y-3">
              <div class="flex items-center gap-2 flex-wrap">
                <!-- Format badge (clickable cycle) -->
                <button @click="cycleTrendingFormat(idx)"
                  class="text-xs font-semibold px-3 py-1 rounded-full border transition-all"
                  :class="{
                    'bg-blue-50 border-blue-200 text-blue-700': item.format==='explainer',
                    'bg-purple-50 border-purple-200 text-purple-700': item.format==='top5',
                    'bg-red-50 border-red-200 text-red-700': item.format==='reaction',
                    'bg-amber-50 border-amber-200 text-amber-700': item.format==='story',
                  }"
                  x-text="{'top5':'🏆 Top5','explainer':'💡 解說','reaction':'😲 反應','story':'📖 故事'}[item.format]||item.format">
                </button>
                <!-- Account badge (clickable cycle) -->
                <button @click="cycleTrendingAccount(idx)"
                  class="text-xs font-semibold px-3 py-1 rounded-full border bg-gray-50 border-gray-200 text-gray-700 hover:border-orange-300 transition-all"
                  x-text="item.account_suggestion + ' ▾'">
                </button>
                <span class="text-xs text-gray-400 ml-auto" x-text="item.source_name"></span>
              </div>
              <p class="text-sm font-semibold text-gray-800" x-text="item.hook + ' — ' + item.title"></p>
              <textarea
                x-model="trendingEnriched[idx].script"
                rows="3"
                class="w-full text-sm bg-white border border-gray-200 rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-orange-300 resize-none">
              </textarea>
            </div>
          </template>
          <button @click="triggerTrendingJobs()"
            class="w-full py-3 rounded-xl text-sm font-semibold bg-orange-500 text-white hover:bg-orange-600 transition-all">
            🚀 送出產生影片（<span x-text="trendingEnriched.length"></span> 則）
          </button>
        </div>

      </div>
      <!-- ══ 趨勢模式 end ══ -->
```

- [ ] **Step 5: Commit（只含 HTML 結構，JS 下一個 Task 加）**

```bash
git add web/static/index.html
git commit -m "feat: add trending mode tab UI and steps HTML"
```

---

## Task 6: UI — 趨勢模式 Alpine.js 方法

**Files:**
- Modify: `web/static/index.html` (JS section)

- [ ] **Step 1: 加輔助方法**

找到 `toggleSource(id)` 函數（約第 1461 行），在它後面加：

```javascript
    trendingToggleSource(id) {
      const s = new Set(this.trendingSelectedSources)
      s.has(id) ? s.delete(id) : s.add(id)
      this.trendingSelectedSources = s
    },

    trendingToggleItem(item) {
      const key = item.url || item.title
      const s = new Set(this.trendingSelectedIds)
      if (s.has(key)) {
        s.delete(key)
      } else if (s.size < 5) {
        s.add(key)
      }
      this.trendingSelectedIds = s
    },

    groupedTrending() {
      const ORDER = ['reddit','youtube_tw','youtube_us','ptt','dcard','bilibili','zhihu']
      const groups = {}
      for (const item of this.trendingItems) {
        const k = item.source_type || 'other'
        ;(groups[k] = groups[k] || []).push(item)
      }
      const keys = ORDER.filter(k => groups[k]).concat(Object.keys(groups).filter(k => !ORDER.includes(k)))
      return keys.map(k => ({
        source_type: k,
        label: (this._sourceConfig[k] || {}).label || k,
        cls: (this._sourceConfig[k] || {}).cls || 'text-gray-600 bg-gray-100 border-gray-200',
        items: groups[k],
      }))
    },

    async fetchTrending(force = false) {
      this.trendingStep = 'fetching'
      try {
        const srcParam = [...this.trendingSelectedSources].join(',')
        const forceParam = force ? '&force=true' : ''
        const data = await this.api('GET', `/api/news/fetch?topic=&lang=zh-TW&sources=${srcParam}${forceParam}`)
        this.trendingItems = (data.items || [])
        this.trendingSelectedIds = new Set()
        this.trendingStep = 'select'
      } catch (e) {
        this.showToast('抓取失敗：' + e.message)
        this.trendingStep = 'config'
      }
    },

    async analyzeTrending() {
      const selected = this.trendingItems.filter(it =>
        this.trendingSelectedIds.has(it.url || it.title)
      )
      this.trendingStep = 'analyzing'
      try {
        const res = await this.api('POST', '/api/trending/enrich', { items: selected })
        this.trendingEnriched = res.items || []
        this.trendingStep = 'confirm'
      } catch (e) {
        this.showToast('AI 分析失敗：' + e.message)
        this.trendingStep = 'select'
      }
    },

    cycleTrendingFormat(idx) {
      const formats = ['top5', 'explainer', 'reaction', 'story']
      const cur = this.trendingEnriched[idx].format
      const next = formats[(formats.indexOf(cur) + 1) % formats.length]
      this.trendingEnriched[idx] = { ...this.trendingEnriched[idx], format: next }
    },

    cycleTrendingAccount(idx) {
      const accounts = ['科技帳號', '娛樂帳號', '財經帳號']
      const cur = this.trendingEnriched[idx].account_suggestion
      const next = accounts[(accounts.indexOf(cur) + 1) % accounts.length]
      this.trendingEnriched[idx] = { ...this.trendingEnriched[idx], account_suggestion: next }
    },

    _accountToProfile(suggestion) {
      // Map account_suggestion → Upload-Post profile name from settings
      const map = {
        '科技帳號':  this.settings.trending_profile_tech          || '',
        '娛樂帳號':  this.settings.trending_profile_entertainment  || '',
        '財經帳號':  this.settings.trending_profile_finance        || '',
      }
      return map[suggestion] || ''
    },

    async triggerTrendingJobs() {
      if (this.trendingEnriched.length === 0) return
      const today = new Date().toISOString().split('T')[0]
      let successCount = 0
      for (const item of this.trendingEnriched) {
        const profile = this._accountToProfile(item.account_suggestion)
        const newsItem = {
          hook:        item.hook,
          title:       item.title,
          script:      item.script,
          summary:     item.script,
          scene_type:  item.scene_type || 'default',
          source_url:  item.source_url || '',
          source_name: item.source_name || '',
          source:      item.source_name || '',
          url:         item.source_url || '',
        }
        try {
          await this.api('POST', '/api/jobs/trigger', {
            date:            today,
            topic:           item.title,
            lang:            'zh-TW',
            platforms:       ['youtube', 'tiktok', 'instagram'],
            dry_run:         false,
            selected_news:   [newsItem],
            account_profile: profile || null,
          })
          successCount++
        } catch (e) {
          this.showToast(`送出失敗：${item.title.slice(0,20)} — ${e.message}`)
        }
      }
      if (successCount > 0) {
        this.showToast(`已送出 ${successCount} 個 job，請至控制台查看`)
        this.videoMode = 'news'
        this.trendingStep = 'config'
        this.trendingEnriched = []
        this.trendingSelectedIds = new Set()
        await this.loadDashboard()
      }
    },
```

- [ ] **Step 2: 確認 settings 在 init 時載入**

確認 `init()` 函數（約第 1354 行）有把 settings 存到 `this.settings`：
```javascript
    async init() {
      await this.loadDashboard()
      try {
        const s = await this.api('GET', '/api/settings')
        this.uploadKeySet = !!(s.upload_post_key)
        this.youtubeKeySet = !!(s.youtube_key_set)
        this.settings = s   // ← 確認這行存在
      } catch (_) {}
    },
```

如果 `this.settings = s` 不在，加上去。

- [ ] **Step 3: Commit**

```bash
git add web/static/index.html
git commit -m "feat: add trending mode Alpine.js methods (fetch/analyze/confirm/trigger)"
```

---

## Task 7: 端對端測試

- [ ] **Step 1: 重啟 server**

```
Ctrl+C → python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 8000
```

- [ ] **Step 2: 設定趨勢帳號 profiles**

前往 `http://localhost:8000/ui` → 設定頁 → 填入：
- 趨勢 — 科技帳號 profile 名稱：你在 Upload-Post 的科技帳號 profile 名
- 其他兩個可先留空

- [ ] **Step 3: 測試完整流程**

1. 前往「生成影片」
2. 點「🔥 趨勢模式」tab
3. 選 Reddit + YouTube TW
4. 點「🔥 抓取趨勢」
5. 勾選 2-3 則
6. 點「🤖 AI 分析格式與帳號」
7. 確認卡片出現，嘗試點擊格式 badge 切換（top5→explainer→reaction→story）
8. 嘗試點擊帳號 badge 切換
9. 修改腳本
10. 點「🚀 送出」
11. 前往控制台確認 job 出現

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "feat: trending shorts pipeline complete e2e"
```
