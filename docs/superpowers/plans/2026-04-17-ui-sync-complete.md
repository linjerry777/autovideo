# UI Sync — Layout Toggle + Audio Metadata + Assets Status Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 3 UI gaps that accumulated during Steps 3–4 upgrades: (1) **Visual/Text layout toggle** in script-review (users no longer need to hand-edit `news.json`); (2) **Audio metadata display** so users can see which BGM/SFX/voice was picked per item instead of the audio step being a black box; (3) **Assets status panel** in settings so users know whether `assets/music/*` and `assets/sfx/*` have files before kicking off a job.

**Architecture:**
- **Layout toggle**: new `PATCH /api/jobs/{id}/layout_mode` endpoint (atomic write like `platform_meta`). Frontend radio in both `script_review` panels (new-job + job-detail). On entry, fetch current value via existing `GET /api/jobs/{id}/news`.
- **Audio metadata**: `audio_generator.py` writes `pipeline/.../audio/audio_metadata.json` at end of `main()` with `{voice_strategy, items: [{index, bgm, sfx, offset, duration}]}`. New `GET /api/jobs/{id}/audio_metadata` endpoint serves it. Frontend shows a collapsible "🎙️ 音訊詳情" card on the job-detail page once `step_audio` is done.
- **Assets status**: new `GET /api/assets/status` endpoint returns per-folder MP3 counts. Frontend settings page shows a status block with per-emotion row + SFX row + amber warning banner when all folders are empty.

**Tech Stack:** FastAPI (3 new endpoints), Alpine.js (radio, collapsible card, status panel), no new deps.

---

## File Map

| File | Change |
|------|--------|
| `web/routes/jobs.py` | Add `PATCH /api/jobs/{id}/layout_mode` + `GET /api/jobs/{id}/audio_metadata` endpoints |
| `web/routes/settings.py` | Add `GET /api/assets/status` endpoint |
| `scripts/audio_generator.py` | Write `audio_metadata.json` at end of `main()` |
| `web/static/index.html` | Layout radio (2 panels) + audio metadata card (job-detail) + assets status panel (settings page) |

---

## Task 1: Backend — Layout mode PATCH endpoint

**Files:**
- Modify: `web/routes/jobs.py`

Add a small atomic-write endpoint that updates `news.json["layout_mode"]` to `"visual"` or `"text"`.

- [ ] **Step 1: Add `LayoutModeUpdate` model + PATCH endpoint**

In `web/routes/jobs.py`, find the existing `put_platform_meta` function (search for `@router.put("/jobs/{job_id}/platform_meta")`). Right after its closing bracket, add:

```python
class LayoutModeUpdate(BaseModel):
    layout_mode: str   # "visual" | "text"


@router.patch("/jobs/{job_id}/layout_mode")
def patch_layout_mode(job_id: int, body: LayoutModeUpdate):
    """Update layout_mode in news.json (atomic write). Values: visual | text."""
    if body.layout_mode not in ("visual", "text"):
        raise HTTPException(400, "layout_mode must be 'visual' or 'text'")

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    news_file = pipe_dir / "news.json"
    if not news_file.exists():
        raise HTTPException(400, "news.json not found")

    data = _json.loads(news_file.read_text(encoding="utf-8"))
    data["layout_mode"] = body.layout_mode

    tmp = news_file.with_suffix(".json.tmp")
    tmp.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, news_file)
    return {"ok": True, "layout_mode": body.layout_mode}
```

`os`, `_json`, `HTTPException`, `BaseModel`, `BASE_DIR`, `get_job` are already imported — verify before assuming.

- [ ] **Step 2: Syntax check**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
python -X utf8 -c "import ast; ast.parse(open('web/routes/jobs.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Live test (backend auto-reloads)**

```bash
# Verify endpoint registered
python -X utf8 -c "
from web.routes import jobs
paths = [r.path for r in jobs.router.routes if 'layout_mode' in r.path]
print('routes:', paths)
"
```
Expected: `routes: ['/api/jobs/{job_id}/layout_mode']`

Test live:
```bash
curl -s --max-time 5 -X PATCH http://localhost:8000/api/jobs/69/layout_mode \
  -H "Content-Type: application/json" \
  -d '{"layout_mode":"text"}'
echo ""

# Verify news.json was updated
python -X utf8 -c "
import json
d = json.load(open('pipeline/2026-04-17/job_69/news.json', encoding='utf-8'))
print('layout_mode:', d.get('layout_mode'))
"

# Revert
curl -s --max-time 5 -X PATCH http://localhost:8000/api/jobs/69/layout_mode \
  -H "Content-Type: application/json" \
  -d '{"layout_mode":"visual"}'
echo ""

# Test invalid value
curl -s --max-time 5 -X PATCH http://localhost:8000/api/jobs/69/layout_mode \
  -H "Content-Type: application/json" \
  -d '{"layout_mode":"bogus"}'
echo ""
```

Expected:
- First PATCH: `{"ok":true,"layout_mode":"text"}`
- news.json print: `layout_mode: text`
- Second PATCH: `{"ok":true,"layout_mode":"visual"}`
- Invalid value: `{"detail":"layout_mode must be 'visual' or 'text'"}` (400)

- [ ] **Step 4: Commit**

```bash
git add web/routes/jobs.py
git commit -m "feat: PATCH /api/jobs/{id}/layout_mode — atomic write of news.json"
```

---

## Task 2: Frontend — Visual/Text radio in script review

**Files:**
- Modify: `web/static/index.html`

Add a `<radio>` pair at the top of BOTH `script_review` panels. On entry, fetch current value from `GET /api/jobs/{id}/news`. On change, PATCH backend. Show toast on success.

- [ ] **Step 1: Add Alpine data field**

Find the Alpine `data` block. Near `scriptItems: []` or `replacePanelOpen: null,` (both are close to each other), add:

```js
layoutMode: 'visual',   // 'visual' | 'text' — synced to news.json via PATCH
```

- [ ] **Step 2: Add `loadLayoutMode()` + `saveLayoutMode()` methods**

In the Alpine methods section, add near `continueJob()` or `savePlatformMeta()`:

```js
async loadLayoutMode(jobId) {
  try {
    const news = await this.api('GET', `/api/jobs/${jobId}/news`)
    this.layoutMode = news.layout_mode || 'visual'
  } catch (e) {
    this.layoutMode = 'visual'
  }
},

async saveLayoutMode() {
  if (!this.currentJob) return
  try {
    await this.api('PATCH', `/api/jobs/${this.currentJob.id}/layout_mode`,
                   { layout_mode: this.layoutMode })
    const label = this.layoutMode === 'visual' ? '視覺優先' : '文字優先'
    this.showToast(`版面 → ${label}`)
  } catch (e) { this.showToast('切換失敗：' + e.message) }
},
```

- [ ] **Step 3: Hook `loadLayoutMode` into the script_review entry**

Find where `scriptItems` gets populated (search for `scriptItems = ` or `this.scriptItems =`). Whenever you see a load-items call, call `loadLayoutMode` alongside. A simpler approach: watch `step_screenshot` and load when it hits `script_review`.

Find the SSE event handler or the `openJob` method (search for `async openJob`). Add to the method body, right after `this.currentJob = ...`:

```js
      if (this.currentJob && ['script_review','review','running','done'].some(s =>
            this.currentJob.step_screenshot === s || this.currentJob.step_audio === s ||
            this.currentJob.step_video === s || this.currentJob.status === 'done')) {
        this.loadLayoutMode(this.currentJob.id)
      }
```

Simpler alternative: just call `loadLayoutMode` inside `openJob` unconditionally — the endpoint returns 404 cleanly if news.json doesn't exist, and our `catch` falls back to `'visual'`. So:

```js
      if (this.currentJob) {
        this.loadLayoutMode(this.currentJob.id)
      }
```

Put that right before the closing brace of `openJob`.

- [ ] **Step 4: Add radio UI in BOTH script_review panels**

Use Grep to find the 2 panels:
```bash
grep -n "currentJob?.step_screenshot === 'script_review'" web/static/index.html
```
Expected: 2 matches.

In EACH panel, find the block that contains `<p class="text-sm">腳本已生成` or similar entry-level text. Just BEFORE the `<template x-for="(item, i) in scriptItems"` template, insert:

```html
          <!-- Layout mode toggle (visual vs text) -->
          <div class="flex items-center gap-4 py-3 px-5 glass rounded-2xl flex-wrap">
            <p class="text-xs font-semibold text-gray-500">版面風格</p>
            <label class="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" x-model="layoutMode" value="visual" @change="saveLayoutMode()" class="accent-green-500">
              <span>🎬 視覺優先 <span class="text-[10px] text-gray-400">（圖片全螢幕 + Ken Burns）</span></span>
            </label>
            <label class="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" x-model="layoutMode" value="text" @change="saveLayoutMode()" class="accent-green-500">
              <span>✨ 文字優先 <span class="text-[10px] text-gray-400">（漸層 + 浮光）</span></span>
            </label>
          </div>
```

- [ ] **Step 5: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('radio:', 'layoutMode' in s); print('load_method:', 'loadLayoutMode' in s); print('save_method:', 'saveLayoutMode' in s); print('radio_count:', s.count('saveLayoutMode()'))"
```
Expected: `radio: True`, `load_method: True`, `save_method: True`, `radio_count: 2` (one per panel × 2 radio buttons = 4 × @change... wait, 2 panels × 2 radios each = 4 but they all call saveLayoutMode(). So count is ≥4. Adjust: just check >= 2.)

Let me restate: `radio_count` can be 2 (if the radio markup appears twice across panels) or higher (each radio button has an @change). Verify with `>= 2`.

Better grep:
```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); import re; panels=len(re.findall(r'版面風格', s)); btns=s.count('saveLayoutMode()'); print('panels_with_radio:', panels); print('save_calls:', btns)"
```
Expected: `panels_with_radio: 2` and `save_calls >= 4` (2 panels × 2 radios).

- [ ] **Step 6: Commit**

```bash
git add web/static/index.html
git commit -m "feat: Visual/Text 版面切換 radio in script review panels"
```

---

## Task 3: Audio metadata writing

**Files:**
- Modify: `scripts/audio_generator.py`

At the end of `main()`, write a summary JSON alongside `audio_XX.mp3` files: `{voice_strategy, items: [{index, bgm, sfx, offset, duration}]}`.

- [ ] **Step 1: Collect metadata in the loop + write at end**

Find the per-item loop in `main()` in `scripts/audio_generator.py`. Currently near the end there's:

```python
        bgm_label = bgm.name if bgm else "(no BGM)"
        sfx_label = sfx.name if sfx else "(no SFX)"
        print(f"      ✅ {combined.name}（BGM={bgm_label}, SFX={sfx_label}, +{offset:.1f}s offset）")
```

Right BEFORE `main()`'s final `print(f"\n✅ 語音已存至 {AUDIO_DIR}")` line, we need to track + write metadata. Modify the loop to collect metadata, then write after.

At the start of `main()`, just after `items = data["items"]`, add:

```python
    audio_metadata: list[dict] = []
```

Inside the per-item loop, right after the `bgm_label` / `sfx_label` / `print(...)` lines, add:

```python
        audio_metadata.append({
            "index":    i,
            "bgm":      bgm.name if bgm else None,
            "sfx":      sfx.name if sfx else None,
            "offset":   round(offset, 2),
            "duration": round(get_duration(combined), 2),
        })
```

At the end of `main()`, just before the final `print(f"\n✅ 語音已存至 {AUDIO_DIR}")`, add:

```python
    # Write audio metadata summary for UI display
    meta_file = AUDIO_DIR / "audio_metadata.json"
    meta_file.write_text(
        json.dumps({
            "voice_strategy": strategy or "",
            "voice_id_used":  voice_id,
            "items":          audio_metadata,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"📋 Audio metadata: {meta_file.name}")
```

- [ ] **Step 2: Syntax + dry test**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/audio_generator.py').read()); print('OK')"
```
Expected: `OK`

Regenerate audio for job 69 to produce a fresh metadata file:
```bash
rm -f pipeline/2026-04-17/job_69/audio/audio_*.mp3 pipeline/2026-04-17/job_69/audio/*.json
python -X utf8 scripts/audio_generator.py 2026-04-17/job_69 2>&1 | tail -10
echo "---"
cat pipeline/2026-04-17/job_69/audio/audio_metadata.json
```

Expected: audio_metadata.json contains `voice_strategy`, `voice_id_used` (possibly empty), and `items` array with 1 entry (job 69 has 1 item) containing `bgm: null`, `sfx: null`, `offset: 0.0`, `duration: ~10.4`.

- [ ] **Step 3: Commit**

```bash
git add scripts/audio_generator.py
git commit -m "feat: audio_generator writes audio_metadata.json summary per job"
```

---

## Task 4: Audio metadata GET + UI card

**Files:**
- Modify: `web/routes/jobs.py` — add `GET /api/jobs/{id}/audio_metadata` endpoint
- Modify: `web/static/index.html` — collapsible card on job-detail page

- [ ] **Step 1: Add GET endpoint in `web/routes/jobs.py`**

In `web/routes/jobs.py`, right after the `patch_layout_mode` function (added in Task 1), add:

```python
@router.get("/jobs/{job_id}/audio_metadata")
def get_audio_metadata(job_id: int):
    """Return audio pipeline metadata (voice, BGM/SFX pick per item, offsets)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    p = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "audio" / "audio_metadata.json"
    if not p.exists():
        return {"voice_strategy": "", "voice_id_used": "", "items": []}
    return _json.loads(p.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Syntax check**

```bash
python -X utf8 -c "import ast; ast.parse(open('web/routes/jobs.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Live test**

```bash
curl -s --max-time 5 http://localhost:8000/api/jobs/69/audio_metadata | python -m json.tool
```
Expected: JSON showing `voice_strategy` + `items` array (from Task 3).

- [ ] **Step 4: Add Alpine state + loader**

In the Alpine data block, add:

```js
audioMetadata: null,   // {voice_strategy, voice_id_used, items: [...]} or null
audioMetaExpanded: false,
```

In methods, add near `loadLayoutMode`:

```js
async loadAudioMetadata(jobId) {
  try {
    const m = await this.api('GET', `/api/jobs/${jobId}/audio_metadata`)
    this.audioMetadata = m.items && m.items.length > 0 ? m : null
  } catch (e) {
    this.audioMetadata = null
  }
},
```

In `openJob()`, right after the existing `loadLayoutMode` call (from Task 2), add:

```js
      this.loadAudioMetadata(this.currentJob.id)
```

- [ ] **Step 5: Add UI card on job-detail page**

Find the job-detail page container `<div x-show="page==='job'">`. Inside it, after the step progress block (the one with 5 step indicators) and BEFORE any step-specific blocks, add:

```html
      <!-- Audio metadata (shown once audio step has produced metadata) -->
      <div x-show="audioMetadata" class="glass rounded-2xl overflow-hidden">
        <button @click="audioMetaExpanded = !audioMetaExpanded"
          class="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-gray-50 transition-colors">
          <div class="flex items-center gap-2">
            <span class="text-xs font-semibold text-gray-600">🎙️ 音訊詳情</span>
            <span class="text-[10px] text-gray-400"
              x-text="audioMetadata?.voice_strategy ? audioMetadata.voice_strategy + ' voice' : 'default voice'"></span>
          </div>
          <span x-text="audioMetaExpanded ? '▼' : '▶'" class="text-xs text-gray-400"></span>
        </button>
        <div x-show="audioMetaExpanded" class="border-t border-gray-100 p-4 space-y-2">
          <template x-for="it in (audioMetadata?.items || [])" :key="it.index">
            <div class="flex items-center gap-3 text-xs">
              <span class="bg-gray-100 text-gray-600 rounded-md px-2 py-0.5 font-mono"
                x-text="'#' + it.index"></span>
              <span class="text-gray-500" x-text="it.duration + 's'"></span>
              <span class="text-emerald-600" x-text="it.bgm ? '🎵 ' + it.bgm : '—'"></span>
              <span class="text-blue-600" x-text="it.sfx ? '🔔 ' + it.sfx : '—'"></span>
              <span x-show="it.offset > 0" class="text-gray-400" x-text="'+' + it.offset + 's'"></span>
            </div>
          </template>
        </div>
      </div>
```

- [ ] **Step 6: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('audioMeta_state:', 'audioMetadata' in s); print('load_method:', 'loadAudioMetadata' in s); print('ui_card:', '🎙️ 音訊詳情' in s); print('route_check:', '/audio_metadata' in s)"
```
Expected: all 4 True.

- [ ] **Step 7: Commit**

```bash
git add web/routes/jobs.py web/static/index.html
git commit -m "feat: GET /api/jobs/{id}/audio_metadata + collapsible 音訊詳情 card"
```

---

## Task 5: Assets status endpoint + settings UI panel

**Files:**
- Modify: `web/routes/settings.py` — add `GET /api/assets/status`
- Modify: `web/static/index.html` — status block in settings page

- [ ] **Step 1: Add status endpoint in `web/routes/settings.py`**

In `web/routes/settings.py`, at the bottom of the file (after the `list_llm_models` endpoint), add:

```python
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MUSIC_EMOTIONS = ["surprise", "fear", "joy", "curiosity", "anger", "generic"]


@router.get("/assets/status")
def get_assets_status():
    """Count MP3 files in assets/music/* and assets/sfx/hook."""
    music_root = BASE_DIR / "assets" / "music"
    sfx_root   = BASE_DIR / "assets" / "sfx" / "hook"

    music = {}
    for emotion in MUSIC_EMOTIONS:
        folder = music_root / emotion
        if folder.exists() and folder.is_dir():
            music[emotion] = len([p for p in folder.iterdir() if p.suffix.lower() == ".mp3" and p.is_file()])
        else:
            music[emotion] = 0

    sfx_count = 0
    if sfx_root.exists() and sfx_root.is_dir():
        sfx_count = len([p for p in sfx_root.iterdir() if p.suffix.lower() == ".mp3" and p.is_file()])

    total = sum(music.values()) + sfx_count
    return {
        "music":       music,
        "sfx_hook":    sfx_count,
        "total_files": total,
    }
```

- [ ] **Step 2: Syntax check**

```bash
python -X utf8 -c "import ast; ast.parse(open('web/routes/settings.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Live test**

```bash
curl -s --max-time 5 http://localhost:8000/api/assets/status | python -m json.tool
```
Expected: JSON with `music` (dict of 6 emotion keys → integer counts), `sfx_hook` (integer), `total_files` (integer sum). All zeros since assets are empty unless user added any.

- [ ] **Step 4: Alpine state + loader**

In the Alpine data block, add:

```js
assetsStatus: null,   // { music: {...}, sfx_hook: N, total_files: N }
```

In methods, near `loadSettings`:

```js
async loadAssetsStatus() {
  try {
    this.assetsStatus = await this.api('GET', '/api/assets/status')
  } catch (e) {
    this.assetsStatus = null
  }
},
```

Find `loadSettings` in the methods section. Change it to also load assets status:

```js
    async loadSettings() {
      try {
        this.settings = await this.api('GET', '/api/settings')
      } catch (e) { this.showToast('載入設定失敗：' + e.message) }
      this.loadAssetsStatus()
    },
```

- [ ] **Step 5: Add UI panel in settings page**

Find the settings page container (search for `page==='settings'`). Inside it, add a new block at the top (before existing settings form):

```html
<!-- Audio Assets Status -->
<div x-show="assetsStatus" class="glass rounded-2xl p-5 space-y-3">
  <div class="flex items-center justify-between">
    <p class="text-sm font-semibold text-gray-700">🎵 Audio Assets 狀態</p>
    <span class="text-xs text-gray-400" x-text="(assetsStatus?.total_files || 0) + ' MP3 檔'"></span>
  </div>

  <!-- All-empty warning -->
  <div x-show="(assetsStatus?.total_files || 0) === 0"
    class="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-700 flex items-start gap-2">
    <span>⚠️</span>
    <div>
      <p class="font-medium">尚未放入任何音樂或音效</p>
      <p class="text-amber-600 mt-0.5">Pipeline 會 fallback 到純人聲（不影響運作）。詳情見 <code class="bg-amber-100 rounded px-1">assets/README.md</code></p>
    </div>
  </div>

  <!-- Music per emotion -->
  <div class="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
    <template x-for="[emotion, label] in [
      ['surprise','😲 驚訝'],['fear','😨 驚恐'],['joy','😂 好笑'],
      ['curiosity','🤔 好奇'],['anger','😡 憤怒'],['generic','📦 通用']
    ]" :key="emotion">
      <div class="flex items-center justify-between px-2 py-1 rounded-md"
        :class="(assetsStatus?.music?.[emotion] || 0) > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-50 text-gray-400'">
        <span x-text="label"></span>
        <span class="font-mono" x-text="(assetsStatus?.music?.[emotion] || 0)"></span>
      </div>
    </template>
  </div>

  <!-- SFX -->
  <div class="flex items-center justify-between px-2 py-1 rounded-md text-xs"
    :class="(assetsStatus?.sfx_hook || 0) > 0 ? 'bg-blue-50 text-blue-700' : 'bg-gray-50 text-gray-400'">
    <span>🔔 Hook SFX</span>
    <span class="font-mono" x-text="(assetsStatus?.sfx_hook || 0) + ' 首'"></span>
  </div>
</div>
```

- [ ] **Step 6: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('assetsStatus:', 'assetsStatus' in s); print('loadAssets:', 'loadAssetsStatus' in s); print('ui_panel:', 'Audio Assets 狀態' in s); print('warn_banner:', '尚未放入任何音樂或音效' in s)"
```
Expected: all 4 True.

- [ ] **Step 7: Commit**

```bash
git add web/routes/settings.py web/static/index.html
git commit -m "feat: GET /api/assets/status + Audio Assets 狀態 panel in settings"
```

---

## Task 6: E2E validation

**Files:**
- None modified — end-to-end smoke test only.

- [ ] **Step 1: Verify all 3 endpoints registered**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
python -X utf8 -c "
from web.routes import jobs, settings
paths = [r.path for r in jobs.router.routes if 'layout_mode' in r.path or 'audio_metadata' in r.path]
print('jobs routes:', paths)
paths2 = [r.path for r in settings.router.routes if 'assets' in r.path]
print('settings routes:', paths2)
"
```

Expected: 3 routes total — `/api/jobs/{job_id}/layout_mode`, `/api/jobs/{job_id}/audio_metadata`, `/api/assets/status`.

- [ ] **Step 2: End-to-end layout toggle cycle**

```bash
# Toggle to text
curl -s --max-time 5 -X PATCH http://localhost:8000/api/jobs/69/layout_mode \
  -H "Content-Type: application/json" -d '{"layout_mode":"text"}'
echo ""

# Verify news.json
python -X utf8 -c "
import json
d = json.load(open('pipeline/2026-04-17/job_69/news.json', encoding='utf-8'))
print('after PATCH text:', d.get('layout_mode'))
"

# Toggle back to visual
curl -s --max-time 5 -X PATCH http://localhost:8000/api/jobs/69/layout_mode \
  -H "Content-Type: application/json" -d '{"layout_mode":"visual"}'
echo ""

python -X utf8 -c "
import json
d = json.load(open('pipeline/2026-04-17/job_69/news.json', encoding='utf-8'))
print('after PATCH visual:', d.get('layout_mode'))
"
```

Expected: `after PATCH text: text` then `after PATCH visual: visual`.

- [ ] **Step 3: Audio metadata round-trip**

```bash
curl -s --max-time 5 http://localhost:8000/api/jobs/69/audio_metadata | python -X utf8 -c "
import json, sys
d = json.loads(sys.stdin.read())
print('voice_strategy:', repr(d.get('voice_strategy')))
print('items count:', len(d.get('items', [])))
for it in d.get('items', []):
    print(f'  #{it[\"index\"]}: dur={it[\"duration\"]}s offset={it[\"offset\"]}s bgm={it[\"bgm\"]!r} sfx={it[\"sfx\"]!r}')
"
```

Expected: `items count: 1` (job 69 has 1 news item), with `duration` around 10.4s.

- [ ] **Step 4: Assets status**

```bash
curl -s --max-time 5 http://localhost:8000/api/assets/status | python -X utf8 -m json.tool
```

Expected: JSON with music = 6 emotions each 0, sfx_hook = 0, total_files = 0 (since user hasn't added any mp3s yet). No crashes on empty directories.

- [ ] **Step 5: UI smoke test (manual)**

Open `http://localhost:8000/ui`:

1. **Layout toggle**: Go to any job in `script_review` state → see radio `🎬 視覺優先 / ✨ 文字優先` at top of script cards. Click text → see toast "版面 → 文字優先". Refresh page, radio stays on 文字優先.

2. **Audio metadata card**: Go to job 69 detail → see collapsible `🎙️ 音訊詳情 · entertainment voice`. Click to expand → see `#1 10.4s — —` (dashes because no BGM/SFX assets).

3. **Assets status**: Go to 設定 page → see `🎵 Audio Assets 狀態` panel at top. All 6 emotions show gray with `0`. Warning banner says "尚未放入任何音樂或音效".

- [ ] **Step 6: Commit (empty — E2E marker)**

```bash
git commit --allow-empty -m "test: UI sync (layout toggle + audio metadata + assets status) E2E verified"
```

---

## Self-Review

**1. Spec coverage:**
- Visual/Text toggle in script_review → Task 1 (PATCH endpoint) + Task 2 (radio UI, 2 panels, load+save methods) ✅
- Audio metadata display → Task 3 (writer) + Task 4 (GET endpoint + collapsible card) ✅
- Assets status panel in settings → Task 5 (GET endpoint + UI panel with empty-warning banner) ✅
- Layout toggle persists (survives refresh) → Task 1 writes to news.json, Task 2 Step 3 reloads on `openJob` ✅
- Audio metadata shows `voice_strategy` / per-item BGM / SFX / offset / duration → Task 3 (written by audio_generator), Task 4 (card UI) ✅
- Assets panel warns when empty → Task 5 Step 5 (amber banner block) ✅
- All endpoints use same error convention (404 job not found, 400 bad input) → Task 1 Step 1, Task 4 Step 1 consistent ✅

**2. Placeholder scan:** All steps have concrete code. The verification greps use explicit string matching. Task 2 Step 3 has two fallback options for hooking `loadLayoutMode` into `openJob` — both work; the implementer picks the simpler second one.

**3. Type consistency:**
- `layoutMode: 'visual' | 'text'` — Alpine field matches backend PATCH body field `layout_mode` matches news.json key `layout_mode` ✅
- `audioMetadata: { voice_strategy, voice_id_used, items: [...] }` — Task 3 Step 1 writes this shape, Task 4 Step 1 returns same shape, Task 4 Step 4 reads same keys ✅
- `assetsStatus: { music: {emotion: count}, sfx_hook: number, total_files: number }` — Task 5 Step 1 returns, Task 5 Step 5 reads same keys ✅
- `MUSIC_EMOTIONS` in settings.py (Task 5) matches the 6 emotion keys from `scripts/audio_assets.py:KNOWN_EMOTIONS` ∪ `{"generic"}` → consistent ✅

**4. Scope check:** Single subsystem (UI synchronization for Steps 3-4 backend changes). 6 tasks total, all touching the same Alpine SPA + backend routes + audio_generator. No DB schema changes. Acceptable as a single plan.
