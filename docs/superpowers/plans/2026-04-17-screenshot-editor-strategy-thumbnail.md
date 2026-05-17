# Screenshot Editor + Content Strategy + Auto Thumbnail Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three polish features: (1) MS-Paint-style screenshot editor for the screenshot-review step, (2) per-content-type strategy selector that tunes script length / Hook style / platform targets, (3) auto-generated 1080×1920 thumbnail rendered by Remotion `still`.

**Architecture:**
- **Screenshot editor**: Integrate `tui-image-editor` via CDN in the Alpine.js SPA — modal overlay, loads the image, save posts the edited PNG as base64 to a new backend endpoint that overwrites the file on disk.
- **Content strategy**: A single `strategy` enum (`tech` / `entertainment` / `finance` / `pet`) selected in the news-config step, threaded through `TriggerRequest` → `job_runner` → `claude_client.enrich_news_items(strategy)`. Strategy switches the Claude prompt (target word count + Hook style) and frontend default platforms set.
- **Auto thumbnail**: New `Thumbnail` composition in Remotion (single static frame, 1080×1920). `scripts/thumbnail_renderer.py` calls `npx remotion still` after the main video step; saves to `pipeline/.../thumbnail.png`. Frontend shows it on the done view; served by a new `/api/media/jobs/{id}/thumbnail` endpoint.

**Tech Stack:** tui-image-editor (Fabric.js-based), Alpine.js, FastAPI + Python, Claude/Ollama via proxy, Remotion 4.x + `@remotion/cli still`.

---

## File Map

| File | Change |
|------|--------|
| `web/static/index.html` | tui-image-editor CDN, edit button + modal, strategy dropdown, thumbnail preview on done page |
| `web/routes/jobs.py` | `POST /api/jobs/{id}/screenshots/{n}/upload` endpoint; add `strategy` field to `TriggerRequest` |
| `web/routes/media.py` | `GET /api/media/jobs/{id}/thumbnail` endpoint |
| `web/job_runner.py` | Thread `strategy` through `trigger_job`, `_run_pipeline`, `resume_from_audio`; call thumbnail renderer after video step |
| `web/claude_client.py` | `enrich_news_items(raw_items, topic, strategy)` — strategy-aware prompt |
| `remotion/src/Thumbnail.tsx` | NEW — 1080×1920 static frame component |
| `remotion/src/index.tsx` | Register `Thumbnail` composition alongside `NewsVideo` |
| `scripts/thumbnail_renderer.py` | NEW — calls `npx remotion still Thumbnail …` |

---

## Task 1: Screenshot editor — backend upload endpoint

**Files:**
- Modify: `web/routes/jobs.py`

Frontend will POST the edited PNG as base64 (data URL). Backend decodes and overwrites `pipeline/DATE/job_N/screenshots/news_{n:02d}.png`.

- [ ] **Step 1: Add `UploadScreenshotRequest` model + endpoint**

After the existing `retake_screenshot` function in `web/routes/jobs.py` (around line 257), add:

```python
import base64 as _base64


class UploadScreenshotRequest(BaseModel):
    data_url: str   # "data:image/png;base64,<b64>"


@router.post("/jobs/{job_id}/screenshots/{n}/upload")
def upload_screenshot(job_id: int, n: int, body: UploadScreenshotRequest):
    """Overwrite screenshot n with client-edited PNG (base64 data URL)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    news_file = pipe_dir / "news.json"
    if not news_file.exists():
        raise HTTPException(400, "news.json not found")

    data  = _json.loads(news_file.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if n < 1 or n > len(items):
        raise HTTPException(400, f"Item {n} out of range (1–{len(items)})")

    # Strip data URL prefix and decode
    url = body.data_url
    if "," in url:
        url = url.split(",", 1)[1]
    try:
        png_bytes = _base64.b64decode(url)
    except Exception:
        raise HTTPException(400, "Invalid base64 payload")

    shots_dir = pipe_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shots_dir / f"news_{n:02d}.png"
    shot_path.write_bytes(png_bytes)

    return {"ok": True, "url": f"/api/media/jobs/{job_id}/screenshots/{shot_path.name}"}
```

- [ ] **Step 2: Smoke-test**

```bash
# 1×1 transparent PNG data URL
curl -s -X POST http://localhost:8000/api/jobs/999/screenshots/1/upload \
  -H "Content-Type: application/json" \
  -d '{"data_url":"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="}'
```
Expected: `{"detail":"Job not found"}` — proves the route is registered.

- [ ] **Step 3: Commit**

```bash
git add web/routes/jobs.py
git commit -m "feat: POST /api/jobs/{id}/screenshots/{n}/upload for edited PNGs"
```

---

## Task 2: Screenshot editor — tui-image-editor modal in frontend

**Files:**
- Modify: `web/static/index.html`

Load `tui-image-editor@3.15.3` from CDN. Add an "編輯" button per screenshot that opens a full-screen modal with the editor initialized to the current image. Save → POST the data URL to the new endpoint → update the thumbnail in place.

- [ ] **Step 1: Add tui-image-editor CDN in `<head>`**

After the Tailwind and Alpine.js script tags near the top of `<head>` (~line 8), add:

```html
<!-- tui-image-editor (MS-Paint-style screenshot editing) -->
<link rel="stylesheet" href="https://uicdn.toast.com/tui-color-picker/latest/tui-color-picker.min.css">
<link rel="stylesheet" href="https://uicdn.toast.com/tui-image-editor/latest/tui-image-editor.min.css">
<script src="https://uicdn.toast.com/tui.code-snippet/v1.5.2/tui-code-snippet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/fabric.js/4.2.0/fabric.min.js"></script>
<script src="https://uicdn.toast.com/tui-color-picker/latest/tui-color-picker.min.js"></script>
<script src="https://uicdn.toast.com/tui-image-editor/latest/tui-image-editor.min.js"></script>
```

- [ ] **Step 2: Add Alpine state fields**

Find the Alpine `data` block (~line 1455). After `scriptOverrides: {},` add:

```js
// Screenshot editor modal
editorOpen: false,
editorShotIndex: null,
editorInstance: null,
```

- [ ] **Step 3: Add `openEditor()` / `closeEditor()` / `saveEditor()` methods**

In the methods section, add near `retakeScreenshot` (~line 1975):

```js
openEditor(shotIndex) {
  const shot = this.screenshots.find(s => s.index === shotIndex)
  if (!shot || !shot.url) {
    this.showToast('此項沒有可編輯的圖片')
    return
  }
  this.editorShotIndex = shotIndex
  this.editorOpen = true
  // Wait for modal to mount before instantiating
  this.$nextTick(() => {
    const el = document.getElementById('tui-editor-container')
    if (!el) return
    el.innerHTML = ''
    this.editorInstance = new tui.ImageEditor(el, {
      includeUI: {
        loadImage: {
          path: 'http://localhost:8000' + shot.url + '?t=' + Date.now(),
          name: 'screenshot',
        },
        theme: { 'common.bi.image': '', 'common.backgroundColor': '#f9fafb' },
        menu: ['crop', 'flip', 'rotate', 'draw', 'shape', 'icon', 'text', 'filter'],
        initMenu: 'draw',
        uiSize: { width: '100%', height: '100%' },
        menuBarPosition: 'bottom',
      },
      cssMaxWidth: 900,
      cssMaxHeight: 600,
      usageStatistics: false,
    })
  })
},

closeEditor() {
  if (this.editorInstance) {
    try { this.editorInstance.destroy() } catch (e) {}
    this.editorInstance = null
  }
  this.editorOpen = false
  this.editorShotIndex = null
},

async saveEditor() {
  if (!this.editorInstance) return
  try {
    const dataUrl = this.editorInstance.toDataURL({ format: 'png' })
    const res = await this.api('POST',
      `/api/jobs/${this.currentJob.id}/screenshots/${this.editorShotIndex}/upload`,
      { data_url: dataUrl })
    // Refresh screenshot URL (bust cache via timestamp)
    const idx = this.screenshots.findIndex(s => s.index === this.editorShotIndex)
    if (idx !== -1 && res.url) {
      this.screenshots[idx] = {
        ...this.screenshots[idx],
        url: res.url + '?t=' + Date.now(),
      }
    }
    this.showToast('已儲存編輯後圖片')
    this.closeEditor()
  } catch (e) { this.showToast('儲存失敗：' + e.message) }
},
```

- [ ] **Step 4: Add "編輯" button to each screenshot card**

Find the per-shot action row in the screenshot review section (~line 649):
```html
                      <button @click="retakeScreenshot(shot.index)"
                        class="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5 transition-all hover:border-gray-300">
                        重拍
                      </button>
```

Add another button right before it:
```html
                      <button @click="openEditor(shot.index)" x-show="shot.url && shot.type !== 'broll'"
                        class="text-xs text-blue-600 hover:text-blue-700 border border-blue-200 bg-blue-50 hover:bg-blue-100 rounded-lg px-3 py-1.5 transition-all">
                        🖌️ 編輯
                      </button>
```

- [ ] **Step 5: Add editor modal at the bottom of the main Alpine `<div>`**

Find the closing `</div>` of the outermost `x-data="app()"` container. Before it, add:

```html
<!-- ── Screenshot Editor Modal ─────────────────────────────────────── -->
<div x-show="editorOpen" x-cloak
     class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6">
  <div class="bg-white rounded-2xl w-[95vw] h-[90vh] flex flex-col overflow-hidden shadow-2xl">
    <div class="flex items-center justify-between px-5 py-3 border-b border-gray-100">
      <p class="text-sm font-semibold text-gray-700">
        🖌️ 編輯截圖 #<span x-text="editorShotIndex"></span>
      </p>
      <div class="flex gap-2">
        <button @click="closeEditor()"
          class="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5">
          取消
        </button>
        <button @click="saveEditor()"
          class="text-xs text-white bg-green-600 hover:bg-green-700 rounded-lg px-4 py-1.5 font-medium">
          儲存
        </button>
      </div>
    </div>
    <div id="tui-editor-container" class="flex-1 overflow-hidden"></div>
  </div>
</div>
```

- [ ] **Step 6: Manual test**

1. Run a job to screenshot-review stage
2. Click 🖌️ 編輯 on any shot → modal opens with tui-image-editor
3. Draw a red circle on the image, click 儲存
4. Modal closes, thumbnail updates to show the edited version
5. Check `pipeline/DATE/job_N/screenshots/news_01.png` — verify pixel change
6. Click 確認截圖繼續 — pipeline completes with the edited image

- [ ] **Step 7: Commit**

```bash
git add web/static/index.html
git commit -m "feat: tui-image-editor modal for in-browser screenshot editing"
```

---

## Task 3: Content strategy — backend plumbing

**Files:**
- Modify: `web/claude_client.py`
- Modify: `web/routes/jobs.py`
- Modify: `web/job_runner.py`

Strategy is one of four values: `tech` / `entertainment` / `finance` / `pet`. It affects the Claude prompt (target word count + Hook style) for `enrich_news_items`. It is stored in `news.json` under `strategy` alongside `account_profile`.

**Strategy table** (use this mapping exactly):

| Strategy | Script target | Hook style |
|----------|---------------|------------|
| `tech` | 80–110 字 | 先說結論 (1 秒內拋出核心賣點) |
| `entertainment` | 30–50 字 | 情緒衝擊 (驚喜/反轉/搞笑) |
| `finance` | 80–110 字 | 數字衝擊 (先報數字再解釋) |
| `pet` | 40–60 字 | 可愛/互動 (特寫情緒) |

- [ ] **Step 1: Update `enrich_news_items` signature and prompt in `claude_client.py`**

Find the function at line 66. Replace the whole function with:

```python
_STRATEGY_PRESETS = {
    "tech":          {"script_len": "80~110 字",
                      "hook_style": "先說結論（1 秒內拋出核心賣點），適合技術解說"},
    "entertainment": {"script_len": "30~50 字",
                      "hook_style": "情緒衝擊（驚喜/反轉/搞笑），開頭必須在 1 秒內抓住注意力"},
    "finance":       {"script_len": "80~110 字",
                      "hook_style": "數字衝擊（先報關鍵數字再解釋），語氣專業"},
    "pet":           {"script_len": "40~60 字",
                      "hook_style": "可愛/互動（特寫情緒，用問句或感嘆引發共鳴）"},
}


def enrich_news_items(raw_items: list[dict], topic: str | None = None,
                     strategy: str | None = None) -> list[dict]:
    """
    raw_items: [{title, summary, url, source}, ...]
    strategy:  tech | entertainment | finance | pet   (None → 預設科技風格)
    回傳: [{hook, title, summary, script, scene_type, source_url, source_name}, ...]
    """
    preset = _STRATEGY_PRESETS.get((strategy or "tech").lower(), _STRATEGY_PRESETS["tech"])
    lines = "\n".join([
        f"{i+1}. [{it['source']}] {it['title']}\n   URL: {it['url']}\n   {it.get('summary','')[:120]}"
        for i, it in enumerate(raw_items)
    ])
    topic_line = f"主題背景：{topic}\n\n" if topic else ""
    prompt = f"""請使用繁體中文回答。
{topic_line}以下是用戶選定的新聞，請為每則生成短影音所需的內容。

內容策略：
- 腳本長度：{preset['script_len']}
- Hook 風格：{preset['hook_style']}

{lines}

每則請用以下 JSON 格式（照順序）：
{{
  "hook": "開場鉤子（5-8字，按上述 Hook 風格生成）",
  "title": "標題（15字以內，中文）",
  "summary": "摘要（40字以內，中文，口語化）",
  "script": "旁白腳本（依上述腳本長度，像在跟朋友說話）",
  "scene_type": "動畫場景類型（從以下擇一，依據新聞主題）：fire（攻擊/爆炸/燃燒）, race（競賽/追趕/對決）, money（融資/估值/賺錢）, robot（AI/機器人/科技突破）, warning（爭議/警告/風險）, trophy（創紀錄/得獎/突破）, default（其他）",
  "source_url": "原始 URL（從列表複製）",
  "source_name": "媒體名稱"
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

- [ ] **Step 2: Add `strategy` to `TriggerRequest` in `jobs.py`**

Find `TriggerRequest` class (~line 43). Add one field:

```python
class TriggerRequest(BaseModel):
    date:               str | None        = None
    topic:              str | None        = None
    lang:               str               = "zh-TW"
    platforms:          list[str]         = ["youtube", "instagram"]
    dry_run:            bool              = False
    selected_news:      list[dict] | None = None
    selected_cache_ids: list[int] | None  = None
    account_profile:    str | None        = None
    strategy:           str | None        = None   # tech|entertainment|finance|pet
```

- [ ] **Step 3: Pass `strategy` through `trigger()` endpoint**

In the `trigger()` function (~line 55), update the `job_runner.trigger_job()` call:

```python
    started = job_runner.trigger_job(
        job_id          = job_id,
        date            = run_date,
        topic           = req.topic,
        platforms       = req.platforms,
        dry_run         = dry_run,
        pre_news        = req.selected_news,
        account_profile = req.account_profile,
        strategy        = req.strategy,
    )
```

- [ ] **Step 4: Thread `strategy` through `job_runner.py`**

In `web/job_runner.py`:

4a. Update `trigger_job()` signature (~line 351):
```python
def trigger_job(job_id: int, date: str, topic: str | None = None,
                platforms: list[str] = None, skip_upload: bool = False,
                dry_run: bool = False,
                pre_news: list[dict] | None = None,
                account_profile: str | None = None,
                strategy: str | None = None) -> bool:
```

4b. Add `strategy` to the queue dict (in the queue push block):
```python
        _job_queue.append({
            "job_id": job_id, "date": date, "topic": topic,
            "platforms": platforms, "skip_upload": skip_upload,
            "dry_run": dry_run, "pre_news": pre_news,
            "account_profile": account_profile,
            "strategy": strategy,
        })
```

4c. Pass `strategy` to the Thread args:
```python
    t = threading.Thread(
        target=_run_pipeline,
        args=(job_id, date, topic, platforms, skip_upload, dry_run,
              pre_news, account_profile, strategy),
        daemon=True,
    )
```

4d. Update `_run_pipeline()` signature (~line 198):
```python
def _run_pipeline(job_id: int, date: str, topic: str | None,
                  platforms: list[str], skip_upload: bool, dry_run: bool,
                  pre_news: list[dict] | None = None,
                  account_profile: str | None = None,
                  strategy: str | None = None):
```

4e. Use `strategy` inside `_run_pipeline` — find the `enrich_news_items(pre_news, topic)` call (~line 225) and update:
```python
                enriched = enrich_news_items(pre_news, topic, strategy)
```

Also write `strategy` to news.json in the same block:
```python
            news_file.write_text(
                _json.dumps(
                    {"date": job_key,
                     "account_profile": account_profile or "",
                     "strategy": strategy or "",
                     "items": enriched},
                    ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
```

- [ ] **Step 5: Update `replace_item` in `jobs.py` to respect strategy**

Find `replace_item` (~line 265). Read strategy from news.json and pass it through:

```python
    # Load strategy from news.json if present
    strategy = data.get("strategy") or None

    # Claude 重新生成腳本（單篇）
    raw = [{...}]
    try:
        enriched = enrich_news_items(raw, job.get("topic"), strategy)
    except Exception as e:
        raise HTTPException(500, f"Claude 生成失敗: {e}")
```

- [ ] **Step 6: Smoke-test `enrich_news_items` directly**

```bash
python -c "
from web.claude_client import enrich_news_items
r = enrich_news_items([{'title':'AI 突破','summary':'...','url':'http://x','source':'test'}], None, 'entertainment')
print(r[0]['script'])
print('len:', len(r[0]['script']))
"
```
Expected: script around 30–50 characters, informal/energetic tone.

- [ ] **Step 7: Commit**

```bash
git add web/claude_client.py web/routes/jobs.py web/job_runner.py
git commit -m "feat: strategy enum threads through pipeline + varies Claude prompt"
```

---

## Task 4: Content strategy — frontend selector

**Files:**
- Modify: `web/static/index.html`

Add a dropdown in the news-config step. On selection, update the default `uploadPlatforms` set based on the strategy. Pass `strategy` in the trigger API call.

- [ ] **Step 1: Add `strategy` to Alpine data**

In the data block, after `selectedSources: new Set([...]),` (~line 1446):
```js
strategy: 'tech',   // tech | entertainment | finance | pet
```

- [ ] **Step 2: Define strategy-to-platforms map + helper**

Add to the Alpine methods section (near `setSourcePreset`, ~line 1750):

```js
_STRATEGY_PLATFORMS: {
  tech:          ['youtube', 'tiktok', 'x'],
  entertainment: ['tiktok', 'instagram', 'facebook'],
  finance:       ['youtube', 'x', 'linkedin'],
  pet:           ['tiktok', 'instagram', 'facebook'],
},

applyStrategyPlatforms() {
  const plats = this._STRATEGY_PLATFORMS[this.strategy] || this._STRATEGY_PLATFORMS.tech
  this.uploadPlatforms = new Set(plats)
},
```

- [ ] **Step 3: Add strategy dropdown to the news-config UI**

Find the news config `<div x-show="newStep==='config'">` section (search for `newStep==='config'`). Inside it, above the source toggles, add:

```html
<div class="space-y-2">
  <p class="text-[11px] text-gray-400 uppercase tracking-wide mb-1">內容策略</p>
  <div class="flex flex-wrap gap-2">
    <template x-for="[id, icon, label, desc] in [
      ['tech',          '🔬', '科技',   '30-60s · 先說結論 · YouTube'],
      ['entertainment', '🎭', '娛樂',   '7-15s · 情緒衝擊 · TikTok+IG'],
      ['finance',       '💰', '財經',   '30-60s · 數字衝擊 · YouTube+X'],
      ['pet',           '🤖', 'AI寵物', '15-30s · 可愛互動 · TikTok+IG']
    ]" :key="id">
      <button type="button" @click="strategy=id; applyStrategyPlatforms()"
        :class="strategy===id
          ? 'bg-green-50 border-green-300 text-green-700 ring-1 ring-green-200'
          : 'bg-gray-50 border-gray-200 text-gray-400 hover:border-gray-300'"
        class="border rounded-lg px-3 py-2 text-sm font-medium transition-all text-left flex flex-col gap-0.5 min-w-[170px]">
        <span x-text="icon + ' ' + label" class="text-sm"></span>
        <span x-text="desc" class="text-[10px] text-gray-400 font-normal"></span>
      </button>
    </template>
  </div>
</div>
```

- [ ] **Step 4: Pass `strategy` in `triggerJob()` call**

Find `triggerJob()` (search for `async triggerJob`). Update the POST body:

```js
await this.api('POST', '/api/jobs/trigger', {
  date:           today,
  topic:          this.newTopic || null,
  lang:           'zh-TW',
  platforms:      [...this.uploadPlatforms],
  dry_run:        false,
  selected_news:  selected,
  strategy:       this.strategy,
})
```

Also pass strategy in `triggerTrendingJobs()` (~line 1708):
```js
await this.api('POST', '/api/jobs/trigger', {
  ...
  strategy:        this._accountToStrategy(item.account_suggestion),
  account_profile: profile || null,
})
```

Add the helper near `_accountToProfile`:
```js
_accountToStrategy(suggestion) {
  return { '科技帳號': 'tech', '娛樂帳號': 'entertainment', '財經帳號': 'finance' }[suggestion] || 'tech'
},
```

- [ ] **Step 5: Manual test**

1. On generate page, click 🎭 娛樂 — verify green highlight + upload platforms box shows TikTok/Instagram/Facebook
2. Fetch news → select 1 → trigger job
3. In script review, verify generated script is ~30-50 chars (short, energetic)
4. Switch to 🔬 科技 strategy, run again with same news → script should be ~80-110 chars

- [ ] **Step 6: Commit**

```bash
git add web/static/index.html
git commit -m "feat: content strategy selector in news-config step"
```

---

## Task 5: Thumbnail — Remotion static composition

**Files:**
- Create: `remotion/src/Thumbnail.tsx`
- Modify: `remotion/src/index.tsx`

Single-frame 1080×1920 PNG. Big Hook at the top, screenshot centered, small title at bottom. Designed to read at thumbnail size: high contrast, ≤3 visible words in the hook.

- [ ] **Step 1: Create `remotion/src/Thumbnail.tsx`**

```tsx
import React from "react";
import { AbsoluteFill, Img } from "remotion";

const FONT_CJK = '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif';

export interface ThumbnailProps {
  hook:       string;
  title:      string;
  screenshot: string;   // data URL or http URL
  palette?:   { bg1: string; bg2: string; bg3: string; accent: string; glow: string };
}

const DEFAULT_PALETTE = {
  bg1: "#1a0033", bg2: "#4a148c", bg3: "#880e4f",
  accent: "#ff6bcb", glow: "rgba(255,107,203,0.5)",
};

export const Thumbnail: React.FC<ThumbnailProps> = ({ hook, title, screenshot, palette }) => {
  const p = palette ?? DEFAULT_PALETTE;

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(150deg, ${p.bg1} 0%, ${p.bg2} 55%, ${p.bg3} 100%)`,
      }}
    >
      {/* Corner glow */}
      <div
        style={{
          position: "absolute",
          left: -200, top: 200,
          width: 900, height: 900,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${p.glow} 0%, transparent 65%)`,
          filter: "blur(60px)",
        }}
      />

      {/* HOOK — huge, gradient text, top third */}
      <div
        style={{
          position: "absolute",
          top: 180,
          left: 0, right: 0,
          display: "flex", justifyContent: "center",
        }}
      >
        <span
          style={{
            fontFamily: FONT_CJK,
            fontSize: 220,
            fontWeight: 900,
            letterSpacing: 12,
            textAlign: "center",
            padding: "0 60px",
            lineHeight: 1.05,
            background: `linear-gradient(180deg, #ffffff 0%, ${p.accent} 100%)`,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            filter: `drop-shadow(0 0 40px ${p.glow})`,
          }}
        >
          {hook || "AI快訊"}
        </span>
      </div>

      {/* Screenshot — middle, rounded */}
      {screenshot && (
        <div
          style={{
            position: "absolute",
            left: 80, right: 80,
            top: 720,
            height: 700,
            borderRadius: 40,
            overflow: "hidden",
            boxShadow: `0 40px 100px rgba(0,0,0,0.7), 0 0 0 4px ${p.accent}60`,
          }}
        >
          <Img src={screenshot} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
      )}

      {/* Title badge — bottom */}
      <div
        style={{
          position: "absolute",
          bottom: 140,
          left: 60, right: 60,
          textAlign: "center",
        }}
      >
        <span
          style={{
            fontFamily: FONT_CJK,
            fontSize: 64,
            fontWeight: 800,
            color: "#ffffff",
            backgroundColor: "rgba(0,0,0,0.65)",
            borderRadius: 28,
            padding: "20px 40px",
            letterSpacing: 2,
            display: "inline-block",
            textShadow: "0 4px 20px rgba(0,0,0,0.9)",
            border: `2px solid ${p.accent}80`,
          }}
        >
          {title}
        </span>
      </div>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 2: Register `Thumbnail` composition in `remotion/src/index.tsx`**

Open `remotion/src/index.tsx` and add (do NOT remove the existing NewsVideo composition):

```tsx
import { Thumbnail, ThumbnailProps } from "./Thumbnail";
```

Inside the `RemotionRoot` return, alongside the existing `<Composition id="NewsVideo" ... />`, add:

```tsx
      <Composition
        id="Thumbnail"
        component={Thumbnail}
        durationInFrames={1}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          hook: "AI 快訊",
          title: "範例標題",
          screenshot: "",
        } as ThumbnailProps}
      />
```

- [ ] **Step 3: TypeScript check**

```bash
cd remotion && npx tsc --noEmit
```
Expected: 0 errors.

- [ ] **Step 4: Manual render test**

```bash
cd remotion
npx remotion still src/index.tsx Thumbnail test-thumb.png \
  --props='{"hook":"破千萬","title":"測試標題","screenshot":""}'
```
Expected: `test-thumb.png` created, 1080×1920, shows "破千萬" hook on gradient background. Delete after verification.

- [ ] **Step 5: Commit**

```bash
cd ..
git add remotion/src/Thumbnail.tsx remotion/src/index.tsx
git commit -m "feat: Thumbnail composition (1080x1920 single-frame PNG)"
```

---

## Task 6: Thumbnail — Python renderer script

**Files:**
- Create: `scripts/thumbnail_renderer.py`

Mirror `remotion_renderer.py` but call `npx remotion still` and render from the first news item only. Save to `pipeline/{date}/thumbnail.png` (or `pipeline/{date}/job_N/thumbnail.png`).

- [ ] **Step 1: Create the script**

```python
#!/usr/bin/env python3
"""
Thumbnail Renderer — render a 1080×1920 PNG cover for a job using Remotion `still`.

Usage:
    python scripts/thumbnail_renderer.py 2026-04-17
    python scripts/thumbnail_renderer.py 2026-04-17/job_5
"""
import base64, io, json, os, subprocess, sys, tempfile
from pathlib import Path
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

TODAY = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

BASE_DIR      = Path(__file__).resolve().parent.parent
PIPELINE_ROOT = Path(os.environ.get("PIPELINE_DIR", BASE_DIR / "pipeline")).resolve()
PIPE_DIR      = PIPELINE_ROOT / TODAY
NEWS_FILE     = PIPE_DIR / "news.json"
REMOTION_DIR  = Path(os.environ.get("REMOTION_DIR", BASE_DIR / "remotion")).resolve()
OUTPUT        = PIPE_DIR / "thumbnail.png"


def file_to_data_url(path: Path, mime: str) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def build_props() -> dict:
    if not NEWS_FILE.exists():
        raise FileNotFoundError(f"news.json not found: {NEWS_FILE}")
    raw = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = raw.get("items", [])
    if not items:
        raise ValueError("news.json has no items")
    first = items[0]
    # Prefer explicit screenshot path on the item, else pipeline/screenshots/news_01.png
    shot_path = Path(first.get("screenshot") or PIPE_DIR / "screenshots" / "news_01.png")
    screenshot_url = file_to_data_url(shot_path, "image/png") if shot_path.exists() else ""
    return {
        "hook":       first.get("hook", "AI 快訊"),
        "title":      first.get("title", ""),
        "screenshot": screenshot_url,
    }


def render(props: dict, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tf:
        json.dump(props, tf, ensure_ascii=False)
        props_file = tf.name
    try:
        cmd = [
            "npx", "remotion", "still",
            "src/index.tsx",
            "Thumbnail",
            str(output).replace("\\", "/"),
            f"--props={props_file.replace(chr(92), '/')}",
            "--image-format=png",
        ]
        print(f"Running Remotion still → {output.name}", file=sys.stderr)
        result = subprocess.run(
            cmd, cwd=str(REMOTION_DIR),
            text=True, encoding="utf-8", errors="replace",
            shell=(sys.platform == "win32"),
        )
    finally:
        try: os.unlink(props_file)
        except OSError: pass

    if result.returncode != 0:
        raise RuntimeError(f"Remotion still failed (exit {result.returncode})")


def main():
    props = build_props()
    render(props, OUTPUT)
    print(f"\nDone: {OUTPUT}", file=sys.stdout)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual test with an existing completed job**

```bash
python scripts/thumbnail_renderer.py 2026-04-17/job_1
```
Expected: `pipeline/2026-04-17/job_1/thumbnail.png` created, 1080×1920, contains hook+screenshot+title.

- [ ] **Step 3: Commit**

```bash
git add scripts/thumbnail_renderer.py
git commit -m "feat: scripts/thumbnail_renderer.py for auto-cover rendering"
```

---

## Task 7: Thumbnail — integrate into pipeline

**Files:**
- Modify: `web/job_runner.py`
- Modify: `web/routes/media.py`
- Modify: `web/static/index.html`

Run `thumbnail_renderer.py` after the video step (best-effort; failure does not fail the job). Add a media endpoint so frontend can preview. Show thumbnail on the done view with a download button.

- [ ] **Step 1: Call thumbnail_renderer in `_run_pipeline` after video step**

In `web/job_runner.py`, find the video step success handling (~line 322, after `su("video", "done")`). Add:

```python
        # ── Step 4.5: Thumbnail (best-effort) ────────────────────────
        try:
            ok_th, _ = _call_script("thumbnail_renderer.py", job_key, [], log_path)
            if not ok_th:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\n[WARN] thumbnail render failed (non-fatal)\n")
        except Exception as _e:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[WARN] thumbnail render exception: {_e}\n")
```

Do the same in `resume_from_audio` (~line 159, after `_step_update(job_id, date, "video", "done")`).

- [ ] **Step 2: Add thumbnail endpoint in `web/routes/media.py`**

Look at the existing `video_by_job` pattern in `media.py` and add a matching `thumbnail_by_job` endpoint. Typical structure:

```python
@router.get("/media/jobs/{job_id}/thumbnail")
def thumbnail_by_job(job_id: int):
    from web.db import get_job
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    path = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "thumbnail.png"
    if not path.exists():
        raise HTTPException(404, "thumbnail not yet generated")
    return FileResponse(str(path), media_type="image/png")
```

(Adjust imports — `BASE_DIR`, `FileResponse`, `HTTPException` — to match how the existing `video_by_job` handler is written in your file.)

- [ ] **Step 3: Show thumbnail on the done view**

In `web/static/index.html`, find the "Done: Video + Upload" section (search for `currentJob?.status==='done'`). Inside that block, above the `<video>` element, add:

```html
<div class="glass rounded-2xl overflow-hidden">
  <div class="flex items-center justify-between px-5 py-3 border-b border-gray-100">
    <p class="text-xs font-semibold text-gray-500">封面縮圖 (1080×1920)</p>
    <a :href="'http://localhost:8000/api/media/jobs/' + currentJob?.id + '/thumbnail?t=' + encodeURIComponent(currentJob?.finished_at || currentJob?.id)"
       download="thumbnail.png"
       class="text-xs text-green-600 hover:text-green-700 border border-green-200 rounded-lg px-3 py-1">
      下載
    </a>
  </div>
  <img :src="'http://localhost:8000/api/media/jobs/' + currentJob?.id + '/thumbnail?t=' + encodeURIComponent(currentJob?.finished_at || currentJob?.id)"
       class="w-full max-h-80 object-contain bg-black"
       @error="$event.target.style.display='none'"
       alt="thumbnail">
</div>
```

- [ ] **Step 4: End-to-end test**

1. Run a job to completion
2. Verify `pipeline/DATE/job_N/thumbnail.png` exists
3. Open the job detail page — thumbnail should display above the video
4. Click 下載 — browser downloads `thumbnail.png`

- [ ] **Step 5: Commit**

```bash
git add web/job_runner.py web/routes/media.py web/static/index.html
git commit -m "feat: auto-generate thumbnail after video step + preview in UI"
```

---

## Self-Review

**1. Spec coverage:**
- 截圖小畫家編輯 → Task 1 (upload endpoint) + Task 2 (tui-image-editor modal) ✅
- 各平台不同策略 → Task 3 (Claude prompt + pipeline) + Task 4 (UI selector) ✅
- 預覽圖自動生成 → Task 5 (Remotion composition) + Task 6 (renderer script) + Task 7 (pipeline integration + UI) ✅

**2. Placeholder scan:** All steps have exact code. One item in Task 7 Step 2 references "adjust imports to match existing `video_by_job`" — this is intentional (the exact import style depends on how media.py is written) and the structural code is shown in full.

**3. Type consistency:**
- `strategy` field is `str | None` in `TriggerRequest`, `trigger_job()`, `_run_pipeline()`, and `enrich_news_items()` — consistent ✅
- `_STRATEGY_PRESETS` keys (`tech`, `entertainment`, `finance`, `pet`) match `_STRATEGY_PLATFORMS` keys in the frontend — consistent ✅
- `ThumbnailProps` interface (hook, title, screenshot) matches what `thumbnail_renderer.py` builds and what `defaultProps` in `index.tsx` declares — consistent ✅
