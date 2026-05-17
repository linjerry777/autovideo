# Step 1 Polish — Sources Trim + Strategy Visibility + Dedup + Layout Preview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up the 生成新影片 page based on real usage: (A) drop 4 low-quality news sources, (B) surface strategy's invisible effects, (C) show "已做過 / 曾封鎖" badges + "載入更多" on news picker, (D) add preview thumbnails + better copy to Visual/Text radio.

**Architecture:**
- **A (sources)** — Remove `v2ex, 36kr, sspai, huxiu` from `ALL_SOURCES` in `web/routes/news.py` and the matching `CURATED_RSS` entries. No frontend button change needed (UI reads from `/api/news/sources` dynamically via existing code — verify).
- **B (strategy visibility)** — Update the 4 strategy card `desc` strings in `index.html` to explicitly show script-length target + auto-selected platforms. Add a tiny current-strategy banner at the top of the script-review panels ("📋 當前策略：科技 · 腳本 80-110 字 · 上傳 YT+TT+X").
- **C (dedup + blocked + load-more)** — Scan `pipeline/*/job_*/news.json` to build `{url: [job_ids]}` index; scan `news_cache` table for `screenshot_blocked` flags. Both maps merged into `/api/news/fetch` response as `made_before` and `screenshot_blocked` per item. New optional `exclude_urls=<csv>` param lets frontend exclude already-shown items for the "載入更多" button. UI adds two badges + one button.
- **D (layout preview)** — Generate 2 sample JPGs (`visual.jpg` + `text.jpg`) once at build time by rendering job 69 in both modes + extracting frame 60. Copy to `web/static/preview/`. Update the radio UI to show `<img>` thumbnails side by side with clearer copy.

**Tech Stack:** FastAPI routes, Alpine.js, vanilla HTML, ffmpeg (frame extract), Remotion (already set up).

---

## File Map

| File | Change |
|------|--------|
| `web/routes/news.py` | Remove `v2ex/36kr/sspai/huxiu` from `ALL_SOURCES` + `CURATED_RSS`; add `made_before`/`screenshot_blocked` enrichment + `exclude_urls` param to `/api/news/fetch` |
| `web/static/index.html` | Update strategy card descriptions; add strategy-effect banner in script_review; add "已做過" + "曾封鎖" badges on news picker cards; "載入更多" button; replace Visual/Text radio with thumbnail-based version |
| `web/static/preview/visual.jpg` | CREATE — 400×711 sample frame (1080×1920 → resized) from visual-mode render |
| `web/static/preview/text.jpg` | CREATE — same for text-mode render |

---

## Task 1: (A) Remove 4 low-quality news sources

**Files:**
- Modify: `web/routes/news.py` — `ALL_SOURCES` (~line 55) + `CURATED_RSS` (~line 490)

Drop `v2ex`, `36kr`, `sspai`, `huxiu`. Keep `ithome` (neutral tech news, still useful). The generic RSS scraper path still works for `ithome` alone.

- [ ] **Step 1: Remove entries from `ALL_SOURCES`**

In `web/routes/news.py`, find the `ALL_SOURCES = {...}` dict (~line 40-65). Locate these 4 lines:

```python
    "v2ex":         {"label": "V2EX",               "icon": "💻", "default": False, "group": "zh"},
    "36kr":         {"label": "36氪",               "icon": "📰", "default": False, "group": "zh"},
    "sspai":        {"label": "少數派",             "icon": "✏️", "default": False, "group": "zh"},
    "ithome":       {"label": "IT之家",             "icon": "🏠", "default": False, "group": "zh"},
    "huxiu":        {"label": "虎嗅",               "icon": "🐯", "default": False, "group": "zh"},
```

Remove all except `ithome`. After the edit, only `ithome` remains from the curated-RSS group.

- [ ] **Step 2: Remove entries from `CURATED_RSS`**

Find `CURATED_RSS = {...}` (~line 490). Current:

```python
CURATED_RSS = {
    "v2ex":  "https://www.v2ex.com/index.xml",
    "36kr":  "https://36kr.com/feed",
    "sspai": "https://sspai.com/feed",
    "ithome":"https://www.ithome.com/rss/",
    "huxiu": "https://www.huxiu.com/rss/",
}
```

Replace with:

```python
CURATED_RSS = {
    "ithome": "https://www.ithome.com/rss/",
}
```

- [ ] **Step 3: Syntax check + /api/news/sources smoke test**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
python -X utf8 -c "import ast; ast.parse(open('web/routes/news.py').read()); print('OK')"
```
Expected: `OK`

Backend auto-reloads. Verify:

```bash
curl -s --max-time 5 http://localhost:8000/api/news/sources | python -X utf8 -c "
import sys, json
d = json.loads(sys.stdin.read())
keys = sorted(d.keys())
print('total sources:', len(keys))
print('removed:', [k for k in ['v2ex','36kr','sspai','huxiu'] if k in keys])
print('still have ithome:', 'ithome' in keys)
"
```
Expected: `total sources: 11`, `removed: []`, `still have ithome: True`.

- [ ] **Step 4: Frontend check (UI auto-sync)**

The UI button list is rendered from `/api/news/sources`. Browser hard-reload (Ctrl+F5) the 生成新影片 page — v2ex/36氪/少數派/虎嗅 buttons disappear automatically. Only ITHome stays in the 中文熱門 row.

Verify via grep that no hardcoded frontend reference exists:

```bash
grep -nE "v2ex|36kr|sspai|huxiu" web/static/index.html
```
Expected: NO matches (or only in unrelated comments — if any hit, check context).

- [ ] **Step 5: Commit**

```bash
git add web/routes/news.py
git commit -m "chore: drop v2ex/36kr/sspai/huxiu sources (low-value for TW short-video use case)"
```

---

## Task 2: (B) Strategy card descriptions + effect banner

**Files:**
- Modify: `web/static/index.html` — strategy cards (search for `_STRATEGY_PLATFORMS` or the 4-card x-for); script review top banner

Reveal the 3 invisible effects: script length target, auto-selected platforms, voice mapping (if configured).

- [ ] **Step 1: Update the 4 strategy card descriptions**

Find the strategy card `<template x-for="[id, icon, label, desc]...">` in the news config page. The current 4-entry array looks like:

```html
    <template x-for="[id, icon, label, desc] in [
      ['tech',          '🔬', '科技',   '30-60s · 先說結論 · YouTube'],
      ['entertainment', '🎭', '娛樂',   '7-15s · 情緒衝擊 · TikTok+IG'],
      ['finance',       '💰', '財經',   '30-60s · 數字衝擊 · YouTube+X'],
      ['pet',           '🤖', 'AI寵物', '15-30s · 可愛互動 · TikTok+IG']
    ]" :key="id">
```

Replace the 4 entries with more concrete effect hints:

```html
    <template x-for="[id, icon, label, desc] in [
      ['tech',          '🔬', '科技',   '腳本 80-110 字 · 先說結論 · 自動發 YT+TT+X'],
      ['entertainment', '🎭', '娛樂',   '腳本 30-50 字 · 情緒衝擊 · 自動發 TT+IG+FB'],
      ['finance',       '💰', '財經',   '腳本 80-110 字 · 數字衝擊 · 自動發 YT+X+LinkedIn'],
      ['pet',           '🤖', 'AI寵物', '腳本 40-60 字 · 可愛互動 · 自動發 TT+IG+FB']
    ]" :key="id">
```

- [ ] **Step 2: Add strategy-effect banner at top of BOTH script_review panels**

Find the layout-mode radio block (added in plan P8 — starts with `<div class="flex items-center gap-4 py-3 px-5 glass rounded-2xl flex-wrap">`). That block already exists in both panels.

Right ABOVE that layout radio block (so the banner sits above the radio), insert this strategy banner:

```html
          <!-- Current strategy banner -->
          <div x-show="scriptItems.length > 0" class="glass rounded-2xl px-5 py-2.5 flex items-center gap-2 flex-wrap text-xs">
            <span class="font-semibold text-gray-500">📋 當前策略：</span>
            <span x-text="({
              tech:          '🔬 科技 · 腳本 80-110 字 · 預設發 YouTube+TikTok+X',
              entertainment: '🎭 娛樂 · 腳本 30-50 字 · 預設發 TikTok+IG+Facebook',
              finance:       '💰 財經 · 腳本 80-110 字 · 預設發 YouTube+X+LinkedIn',
              pet:           '🤖 AI寵物 · 腳本 40-60 字 · 預設發 TikTok+IG+Facebook'
            })[strategy] || '預設策略'"></span>
            <span class="text-gray-400">(生成時決定，完成後無法更改)</span>
          </div>
```

Apply to BOTH `script_review` panels (the one in new-job pipeline view + the one in job-detail page).

- [ ] **Step 3: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('card_updated:', '自動發 YT+TT+X' in s); print('banner_count:', s.count('📋 當前策略'))"
```
Expected: `card_updated: True`, `banner_count: 2`.

- [ ] **Step 4: Commit**

```bash
git add web/static/index.html
git commit -m "feat: strategy cards show script length + platforms; current-strategy banner in script review"
```

---

## Task 3: (C) Backend — dedup + blocked + exclude_urls

**Files:**
- Modify: `web/routes/news.py` — `/api/news/fetch` endpoint

Build 2 lookup maps before returning items:
1. `{url: [job_ids]}` from scanning `pipeline/*/job_*/news.json` files
2. `{url: True}` from `news_cache` where `screenshot_blocked=1`

Merge into each item as `made_before: bool`, `past_jobs: [...]` (capped at 3), `screenshot_blocked: bool`.

Also: accept `exclude_urls` query param (comma-separated) that filters results.

- [ ] **Step 1: Add helper that scans pipeline dirs**

In `web/routes/news.py`, near the top (after imports, before `ALL_SOURCES`), add:

```python
import json as _json
from pathlib import Path as _Path


def _load_used_urls() -> dict[str, list[int]]:
    """Scan pipeline/*/job_*/news.json to build {source_url: [job_ids]} map.

    Used to tag fetched news items with `made_before` + `past_jobs` so users
    can see which stories have already been turned into videos.
    Fast in practice (file I/O ~5ms per job, typically <100 jobs).
    """
    repo_root = _Path(__file__).resolve().parent.parent.parent
    pipeline_root = repo_root / "pipeline"
    used: dict[str, list[int]] = {}
    if not pipeline_root.exists():
        return used
    for job_dir in pipeline_root.glob("*/job_*"):
        news_file = job_dir / "news.json"
        if not news_file.exists():
            continue
        try:
            data = _json.loads(news_file.read_text(encoding="utf-8"))
            job_id = int(job_dir.name.replace("job_", ""))
            for item in data.get("items", []):
                url = item.get("source_url") or item.get("url") or ""
                if url:
                    used.setdefault(url, []).append(job_id)
        except Exception:
            continue
    return used


def _load_blocked_urls() -> set[str]:
    """Return set of URLs flagged screenshot_blocked=1 in news_cache."""
    try:
        from web.db import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT url FROM news_cache WHERE screenshot_blocked=1 AND url IS NOT NULL"
            ).fetchall()
            return {r[0] for r in rows if r[0]}
    except Exception:
        return set()
```

- [ ] **Step 2: Tag items + accept `exclude_urls` in `/api/news/fetch`**

Find the `/api/news/fetch` route handler in `web/routes/news.py` (search for `@router.get("/news/fetch")` or the function that returns `{"items": ...}`). Near the end of that function — AFTER items are collected but BEFORE the `return {"items": items}` line — insert this enrichment block:

```python
    # Dedup / blocked tagging + optional exclude_urls filter
    used_map    = _load_used_urls()
    blocked_set = _load_blocked_urls()
    exclude_set = set()
    if exclude_urls:
        exclude_set = {u.strip() for u in exclude_urls.split(",") if u.strip()}

    enriched = []
    for it in items:
        u = it.get("url", "")
        if u in exclude_set:
            continue
        past = used_map.get(u, [])
        it["made_before"]         = bool(past)
        it["past_jobs"]            = past[-3:]    # last 3 job ids
        it["screenshot_blocked"]   = u in blocked_set
        enriched.append(it)

    items = enriched
```

Now update the `fetch_news` function SIGNATURE to accept `exclude_urls`. Find the existing signature, which looks like:

```python
@router.get("/news/fetch")
def fetch_news(
    topic:   str = "",
    lang:    str = "zh-TW",
    sources: str = None,
    force:   bool = False,
):
```

Change to:

```python
@router.get("/news/fetch")
def fetch_news(
    topic:   str = "",
    lang:    str = "zh-TW",
    sources: str = None,
    force:   bool = False,
    exclude_urls: str = "",
):
```

- [ ] **Step 3: Syntax + smoke tests**

```bash
python -X utf8 -c "import ast; ast.parse(open('web/routes/news.py').read()); print('OK')"
```
Expected: `OK`

Test the helper standalone:
```bash
python -X utf8 -c "
from web.routes.news import _load_used_urls, _load_blocked_urls
used = _load_used_urls()
blocked = _load_blocked_urls()
print(f'used_urls count:    {len(used)}')
print(f'blocked_urls count: {len(blocked)}')
# Sample
for u, jobs in list(used.items())[:2]:
    print(f'  {u[:60]}... → jobs {jobs}')
"
```
Expected: non-zero counts (assuming prior jobs exist); sample prints URL + job_ids.

Live test the endpoint:
```bash
curl -s --max-time 20 "http://localhost:8000/api/news/fetch?topic=AI&lang=zh-TW&sources=google&force=true" \
  | python -X utf8 -c "
import sys, json
d = json.loads(sys.stdin.read())
items = d.get('items', [])
print(f'total: {len(items)}')
tagged = sum(1 for it in items if 'made_before' in it)
print(f'tagged with made_before: {tagged}/{len(items)}')
if items:
    s = items[0]
    print(f'sample: made_before={s.get(\"made_before\")} blocked={s.get(\"screenshot_blocked\")} past_jobs={s.get(\"past_jobs\")}')
"
```
Expected: all items have `made_before`, `screenshot_blocked`, `past_jobs` keys.

Test exclude_urls:
```bash
# Get first URL, then fetch again excluding it
FIRST_URL=$(curl -s --max-time 20 "http://localhost:8000/api/news/fetch?topic=AI&sources=google" | python -X utf8 -c "
import sys, json
d = json.loads(sys.stdin.read())
print(d['items'][0]['url'] if d.get('items') else '')
")
echo "First URL: $FIRST_URL"

curl -s --max-time 20 "http://localhost:8000/api/news/fetch?topic=AI&sources=google&exclude_urls=$FIRST_URL&force=true" | python -X utf8 -c "
import sys, json, urllib.parse
excl = '$FIRST_URL'
d = json.loads(sys.stdin.read())
items = d.get('items', [])
print(f'after exclude: {len(items)}')
print(f'excluded url still present: {any(it[\"url\"] == excl for it in items)}')
"
```
Expected: `excluded url still present: False`.

- [ ] **Step 4: Commit**

```bash
git add web/routes/news.py
git commit -m "feat: /api/news/fetch tags items with made_before + screenshot_blocked; supports exclude_urls"
```

---

## Task 4: (C) Frontend — "已做過" + "曾封鎖" badges

**Files:**
- Modify: `web/static/index.html` — news picker cards

Show two small badges on each news item card in the selection panel. Use Grep to find the news item template.

- [ ] **Step 1: Find the news card template**

```bash
grep -n "x-text=\"item.title\"" web/static/index.html | head -5
```
Expected: 1-2 matches in the news selection area (search for surrounding `<label>` and `<input type="checkbox">`).

- [ ] **Step 2: Add badges into the card**

Find the news card markup — it looks like:

```html
                    <label class="flex items-start gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors"
                      :class="trendingSelectedIds.has(item.url || item.title) ? 'bg-orange-50' : ''">
                      <input type="checkbox" ...>
                      <div class="flex-1 min-w-0">
                        <p class="text-sm font-medium text-gray-800 line-clamp-2" x-text="item.title"></p>
                        <p class="text-xs text-gray-400 mt-0.5 truncate" x-text="item.summary"></p>
                      </div>
                    </label>
```

This is the trending mode card. Find the **news mode** news cards too — they look similar but live under the news-mode `newsPool` / `newsItems`. Grep:

```bash
grep -n 'x-text="item.title"' web/static/index.html
```
Expected: 2+ matches (news + trending modes). We want the news-mode one.

In the news-mode card (the one that iterates `newsPool` or `newsItems`), inside the `<div class="flex-1 min-w-0">` right below the `summary <p>`, add:

```html
                        <div class="flex items-center gap-1.5 mt-1 flex-wrap">
                          <span x-show="item.made_before"
                            class="text-[10px] px-1.5 py-0.5 rounded-md bg-amber-50 text-amber-700 border border-amber-200"
                            :title="'已做過，job #' + (item.past_jobs || []).join(', #')">
                            ⚠️ 已做過 <span x-text="'#' + ((item.past_jobs || []).join(', #'))"></span>
                          </span>
                          <span x-show="item.screenshot_blocked"
                            class="text-[10px] px-1.5 py-0.5 rounded-md bg-red-50 text-red-700 border border-red-200">
                            🚫 曾封鎖
                          </span>
                        </div>
```

- [ ] **Step 3: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('made_before_badge:', '已做過' in s); print('blocked_badge:', '曾封鎖' in s); print('past_jobs_ref:', 'item.past_jobs' in s)"
```
Expected: all 3 True.

- [ ] **Step 4: Commit**

```bash
git add web/static/index.html
git commit -m "feat: news cards show ⚠️ 已做過 + 🚫 曾封鎖 badges"
```

---

## Task 5: (C) Frontend — "載入更多" button

**Files:**
- Modify: `web/static/index.html` — news selection panel

Below the news list, add a button that re-calls `/api/news/fetch?exclude_urls=...` with the URLs currently displayed, then appends new unique items.

- [ ] **Step 1: Add `loadMoreNews()` method**

In Alpine methods (search for `async fetchNews`), add a new method near it:

```js
async loadMoreNews() {
  if (this.newLangs.size === 0) return
  this.appending = true
  try {
    const langs = [...this.newLangs]
    const srcParam = this.selectedSources.size > 0 ? `&sources=${[...this.selectedSources].join(',')}` : ''
    const kw = this.newTopic || 'AI 人工智慧 科技'
    const excludeUrls = this.newsPool.map(it => it.url).filter(Boolean).join(',')
    const excludeParam = excludeUrls ? `&exclude_urls=${encodeURIComponent(excludeUrls)}` : ''
    const forceParam = '&force=true'   // bypass cache so we get fresher items
    const results = await Promise.all(
      langs.map(lang =>
        this.api('GET', `/api/news/fetch?topic=${encodeURIComponent(kw)}&lang=${lang}${srcParam}${excludeParam}${forceParam}`)
          .then(data => this._tagItems(data.items || [], lang))
          .catch(() => [])
      )
    )
    const merged = this._dedup(results.flat())
    // Append only items not already in newsPool (extra safety)
    const existing = new Set(this.newsPool.map(x => x.url))
    const additions = merged.filter(it => !existing.has(it.url))
    this.newsPool = [...this.newsPool, ...additions]
    this.newsItems = [...this.newsPool]
    if (additions.length === 0) {
      this.showToast('沒有更多新聞可載入（所有來源已掃過）')
    } else {
      this.showToast(`載入 ${additions.length} 則新聞`)
    }
  } catch (e) {
    this.showToast('載入失敗：' + e.message)
  } finally {
    this.appending = false
  }
},
```

- [ ] **Step 2: Add the button at the bottom of the news list**

Find the news selection panel — search for the "產生影片" button (`x-text="'產生影片'"` or similar) inside the news-mode section. Right BEFORE that button, insert:

```html
          <button @click="loadMoreNews()" :disabled="appending"
            :class="appending ? 'opacity-40 cursor-wait' : 'hover:border-gray-400'"
            class="w-full py-3 rounded-xl text-sm font-medium border border-dashed border-gray-300 bg-gray-50 text-gray-600 transition-all flex items-center justify-center gap-2">
            <span x-show="!appending">+ 載入更多新聞</span>
            <span x-show="appending">載入中…</span>
          </button>
```

- [ ] **Step 3: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('loadMore_method:', 'loadMoreNews' in s); print('exclude_urls_used:', 'exclude_urls' in s); print('button:', '載入更多新聞' in s)"
```
Expected: all 3 True.

- [ ] **Step 4: Commit**

```bash
git add web/static/index.html
git commit -m "feat: + 載入更多新聞 button uses exclude_urls to avoid duplicates"
```

---

## Task 6: (D) Layout preview thumbnails + better copy

**Files:**
- Create: `web/static/preview/visual.jpg` (extracted frame)
- Create: `web/static/preview/text.jpg` (extracted frame)
- Modify: `web/static/index.html` — Visual/Text radio block

Render job 69 in both modes → extract frame 60 → save as JPGs → update radio UI to show thumbnails.

- [ ] **Step 1: Generate the 2 preview frames**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
mkdir -p web/static/preview

# Visual mode render (default)
python -X utf8 -c "
import json
from pathlib import Path
p = Path('pipeline/2026-04-17/job_69/news.json')
data = json.loads(p.read_text(encoding='utf-8'))
data.pop('layout_mode', None)   # let default 'visual' kick in
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
"
rm -f pipeline/2026-04-17/job_69/output.mp4
python -X utf8 scripts/remotion_renderer.py 2026-04-17/job_69 2>&1 | tail -3

# Extract visual frame at 2s
FFMPEG="/c/Users/User/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin/ffmpeg.exe"
"$FFMPEG" -y -i pipeline/2026-04-17/job_69/output.mp4 -ss 3 -frames:v 1 -vf scale=400:-1 -q:v 3 web/static/preview/visual.jpg 2>/dev/null && echo "  ✓ visual.jpg"

# Text mode render
python -X utf8 -c "
import json
from pathlib import Path
p = Path('pipeline/2026-04-17/job_69/news.json')
data = json.loads(p.read_text(encoding='utf-8'))
data['layout_mode'] = 'text'
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
"
rm -f pipeline/2026-04-17/job_69/output.mp4
python -X utf8 scripts/remotion_renderer.py 2026-04-17/job_69 2>&1 | tail -3

"$FFMPEG" -y -i pipeline/2026-04-17/job_69/output.mp4 -ss 3 -frames:v 1 -vf scale=400:-1 -q:v 3 web/static/preview/text.jpg 2>/dev/null && echo "  ✓ text.jpg"

# Revert news.json to visual (default)
python -X utf8 -c "
import json
from pathlib import Path
p = Path('pipeline/2026-04-17/job_69/news.json')
data = json.loads(p.read_text(encoding='utf-8'))
data.pop('layout_mode', None)
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print('news.json reverted (no layout_mode)')
"

ls -la web/static/preview/
```

Expected: both `visual.jpg` and `text.jpg` exist, ~10-30 KB each (400px wide JPG at quality 3).

- [ ] **Step 2: Update the layout radio UI**

Find the layout radio block in `index.html` (grep `版面風格`). There are 2 instances (both panels). In EACH, replace the inner radio labels with thumbnail-based cards.

Current:

```html
            <label class="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" x-model="layoutMode" value="visual" @change="saveLayoutMode()" class="accent-green-500">
              <span>🎬 視覺優先 <span class="text-[10px] text-gray-400">（圖片全螢幕 + Ken Burns）</span></span>
            </label>
            <label class="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" x-model="layoutMode" value="text" @change="saveLayoutMode()" class="accent-green-500">
              <span>✨ 文字優先 <span class="text-[10px] text-gray-400">（漸層 + 浮光）</span></span>
            </label>
```

Replace with:

```html
            <label class="cursor-pointer group"
              :class="layoutMode === 'visual' ? 'ring-2 ring-green-500 rounded-xl' : ''">
              <input type="radio" x-model="layoutMode" value="visual" @change="saveLayoutMode()" class="sr-only">
              <div class="flex items-center gap-3 border border-gray-200 rounded-xl p-2 group-hover:border-gray-300">
                <img src="/static/preview/visual.jpg" class="w-14 h-24 object-cover rounded-md" alt="visual preview">
                <div class="flex-1">
                  <p class="text-sm font-medium text-gray-700">🎬 視覺優先</p>
                  <p class="text-[10px] text-gray-400 leading-tight">新聞圖片填滿畫面<br>像新聞台風格</p>
                </div>
              </div>
            </label>
            <label class="cursor-pointer group"
              :class="layoutMode === 'text' ? 'ring-2 ring-green-500 rounded-xl' : ''">
              <input type="radio" x-model="layoutMode" value="text" @change="saveLayoutMode()" class="sr-only">
              <div class="flex items-center gap-3 border border-gray-200 rounded-xl p-2 group-hover:border-gray-300">
                <img src="/static/preview/text.jpg" class="w-14 h-24 object-cover rounded-md" alt="text preview">
                <div class="flex-1">
                  <p class="text-sm font-medium text-gray-700">✨ 文字優先</p>
                  <p class="text-[10px] text-gray-400 leading-tight">彩色漸層背景<br>文字卡片風格</p>
                </div>
              </div>
            </label>
```

Apply to BOTH panels.

- [ ] **Step 3: Confirm static file route serves the preview dir**

The FastAPI app serves `/static/*` from `web/static/`. No new route needed. Verify:

```bash
curl -s --max-time 5 -o /dev/null -w "visual.jpg: %{http_code}\n" http://localhost:8000/static/preview/visual.jpg
curl -s --max-time 5 -o /dev/null -w "text.jpg: %{http_code}\n" http://localhost:8000/static/preview/text.jpg
```
Expected: both `HTTP 200`.

- [ ] **Step 4: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('visual_img:', '/static/preview/visual.jpg' in s); print('text_img:', '/static/preview/text.jpg' in s); print('new_copy:', '新聞台風格' in s); print('thumbnail_count:', s.count('/static/preview/'))"
```
Expected: all 3 True; `thumbnail_count: 4` (2 images × 2 panels).

- [ ] **Step 5: Commit**

```bash
git add web/static/preview/ web/static/index.html
git commit -m "feat: layout radio now shows visual/text preview thumbnails + clearer copy"
```

---

## Task 7: E2E validation

**Files:**
- None modified — smoke test checklist.

- [ ] **Step 1: All 4 sources removed + ITHome stays**

```bash
curl -s --max-time 5 http://localhost:8000/api/news/sources | python -X utf8 -c "
import sys, json
d = json.loads(sys.stdin.read())
keys = set(d.keys())
removed_ok = all(k not in keys for k in ['v2ex','36kr','sspai','huxiu'])
ithome_ok  = 'ithome' in keys
print(f'removed_ok: {removed_ok} (4 sources gone)')
print(f'ithome_ok: {ithome_ok}')
print(f'total sources: {len(keys)}')
"
```
Expected: both `True`, total = 11.

- [ ] **Step 2: Strategy banner + card visibility**

Open `http://localhost:8000/ui` → 生成新影片 → news mode. Hard-refresh (Ctrl+F5).

Visual check:
- 4 strategy cards show "腳本 N 字" and "自動發 ..." platform list
- 中文熱門 row no longer shows V2EX / 36氪 / 少數派 / 虎嗅 (only ITHome)
- After triggering a job into script_review: top of panel shows "📋 當前策略：🔬 科技 · 腳本 80-110 字 · 預設發 YouTube+TikTok+X"

- [ ] **Step 3: Dedup + blocked + load-more round-trip**

```bash
# Fetch a batch
python -X utf8 -c "
import urllib.request, json
with urllib.request.urlopen('http://localhost:8000/api/news/fetch?topic=AI&sources=google&force=true', timeout=20) as r:
    d = json.loads(r.read())
items = d.get('items', [])
print(f'fetched: {len(items)}')
tagged = sum(1 for it in items if 'made_before' in it)
print(f'tagged: {tagged}/{len(items)}')
any_made = any(it.get('made_before') for it in items)
any_blocked = any(it.get('screenshot_blocked') for it in items)
print(f'some made_before: {any_made}')
print(f'some blocked:     {any_blocked}')
"
```
Expected: all items tagged; `any_made` likely `True` (job history exists), `any_blocked` varies.

Visual check on UI news picker: ⚠️ 已做過 #NN + 🚫 曾封鎖 badges appear on relevant cards.

- [ ] **Step 4: Load-more button works**

Open UI → news mode → 抓取新聞 → scroll to bottom → click "+ 載入更多新聞". Verify new items append without duplicates (check count before/after).

- [ ] **Step 5: Layout radio preview thumbnails**

Open a job in `script_review` state → see:
- Strategy banner at top
- Layout radio with 2 thumbnail cards (visual.jpg + text.jpg)
- Hover/click works; selected has green ring; `saveLayoutMode()` PATCH fires with toast

Cleanup pre-existing test job 69 outputs (left over from preview gen):
```bash
rm -f pipeline/2026-04-17/job_69/output.mp4
```

- [ ] **Step 6: Commit (empty marker)**

```bash
git commit --allow-empty -m "test: Step 1 polish (sources trim + strategy banner + dedup badges + load more + layout preview) E2E verified"
```

---

## Self-Review

**1. Spec coverage:**
- (A) Remove 4 low-value sources → Task 1 ✅
- (B) Strategy card effect visibility → Task 2 (card desc + banner) ✅
- (C1) Made-before tagging → Task 3 (backend) + Task 4 (badge) ✅
- (C2) Screenshot-blocked flag → Task 3 (backend) + Task 4 (badge) ✅
- (C3) Load-more support → Task 3 (exclude_urls param) + Task 5 (button) ✅
- (D) Layout preview thumbnails + copy → Task 6 ✅

**2. Placeholder scan:** All steps have concrete code. The Step 2 "exclude_urls via ?param=" approach avoids URL-length limits because modern browsers accept 2000+ chars and we cap `newsPool` implicitly via Google News RSS's 30-item ceiling.

**3. Type consistency:**
- `made_before: bool`, `past_jobs: [int]`, `screenshot_blocked: bool` — defined in Task 3 backend, consumed in Task 4 UI as matching keys ✅
- `exclude_urls: str` (comma-separated) — Task 3 signature, Task 5 frontend sends comma-joined ✅
- `layoutMode: 'visual' | 'text'` — unchanged from prior plans ✅

**4. Scope check:** Single subsystem (news generation page + script review UI). 7 tasks total. Fits in one plan.
