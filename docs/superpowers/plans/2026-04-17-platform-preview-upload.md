# Per-Platform Upload Preview + Trending Queue Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Fix the trending-mode bug where selecting 3 items only produces 1 job (job queue). (2) Add a per-platform upload preview: six cards styled as the actual platforms (YouTube / TikTok / IG / FB / Threads / X), each editable with its own title/description/hashtags, plus automatic YouTube thumbnail injection.

**Architecture:**
- **Queue fix**: add a FIFO `_job_queue` deque in `job_runner.py`; enqueue instead of returning False when the pipeline lock is held; drain in the `finally` block. Remove the HTTP 409 in `jobs.py`.
- **Per-platform meta**: one `platform_meta.json` file per job dir. Shared baseline (option B) — seeded from `news.json` when first read, then user edits override per platform. Six-platform fixed schema (`youtube / tiktok / instagram / facebook / threads / x`) with fields matching Upload-Post's per-platform API.
- **Preview UI**: new Alpine page `page='upload'` reachable from the "done" view. Grid of 6 platform-branded cards with authentic colors/logos/typography ("recognizable at a glance" fidelity, not pixel-perfect). Click a card → edit modal → save → platform_meta PUT. "🚀 全部上傳" calls existing upload endpoint after confirming platforms.
- **Publisher**: `scripts/publisher.py` reads `platform_meta.json` and maps each platform's fields to Upload-Post's `{platform}_title` / `{platform}_description` / `tags[]` / `first_comment`. YouTube gets `thumbnail` wired to `pipeline/.../thumbnail.png`.

**Tech Stack:** FastAPI, Alpine.js, Upload-Post SDK, Remotion (existing thumbnail), tui-image-editor (existing).

---

## File Map

| File | Change |
|------|--------|
| `web/job_runner.py` | Add `_job_queue` deque + `_start_next_queued()`; update `trigger_job()`; add `_start_next_queued()` calls in both `finally` blocks |
| `web/routes/jobs.py` | Remove 409 on queue; add `GET/PUT /api/jobs/{id}/platform_meta` endpoints; extend `upload_job` to respect platform_meta |
| `scripts/publisher.py` | Read `platform_meta.json` if present; map to per-platform Upload-Post fields; wire YouTube thumbnail |
| `web/static/index.html` | New `page='upload'` page; 6 platform-styled cards; edit modal; state loading; navigation |

---

## Task 1: Trending job queue fix

**Files:**
- Modify: `web/job_runner.py`
- Modify: `web/routes/jobs.py`

Root cause: `trigger_job()` returns `False` when `_lock` is held; `jobs.py` marks subsequent trending jobs as failed with HTTP 409. The trending "send 3 videos" loop only succeeds for item 1.

Fix: FIFO deque, enqueue instead of failing, drain in the `finally`.

- [ ] **Step 1: Add `_job_queue` deque in `job_runner.py`**

Near the top of `web/job_runner.py`, after `_cancel_flags: dict[int, bool] = {}` (~line 18), add:

```python
import collections as _collections
_job_queue: _collections.deque = _collections.deque()   # pending job params (dicts)
```

- [ ] **Step 2: Add `_start_next_queued()` helper**

Place it after `_broadcast()` and before `set_event_loop()`:

```python
def _start_next_queued():
    """Start the next queued job if one is waiting. Called after current job finishes."""
    if not _job_queue:
        return
    params = _job_queue.popleft()
    trigger_job(**params)
```

- [ ] **Step 3: Replace `trigger_job()` body to enqueue instead of returning False**

Find the existing `trigger_job()` (~line 351 — has signature ending with `strategy: str | None = None`). Replace its body (keeping the existing signature intact) with:

```python
def trigger_job(job_id: int, date: str, topic: str | None = None,
                platforms: list[str] = None, skip_upload: bool = False,
                dry_run: bool = False,
                pre_news: list[dict] | None = None,
                account_profile: str | None = None,
                strategy: str | None = None) -> bool:
    """Returns True always — job runs immediately or is enqueued for sequential execution."""
    global _running_job_id
    if platforms is None:
        platforms = get_setting("platforms", "youtube,instagram").split(",")
    if not _lock.acquire(blocking=False):
        _job_queue.append({
            "job_id": job_id, "date": date, "topic": topic,
            "platforms": platforms, "skip_upload": skip_upload,
            "dry_run": dry_run, "pre_news": pre_news,
            "account_profile": account_profile,
            "strategy": strategy,
        })
        return True
    _running_job_id = job_id
    t = threading.Thread(
        target=_run_pipeline,
        args=(job_id, date, topic, platforms, skip_upload, dry_run,
              pre_news, account_profile, strategy),
        daemon=True,
    )
    t.start()
    return True
```

- [ ] **Step 4: Drain queue in both `finally` blocks**

In `_run_pipeline()` `finally` (end of function ~line 346), find:
```python
        _cancel_flags.pop(job_id, None)
        _running_job_id = None
        _lock.release()
```
Add after `_lock.release()`:
```python
        _start_next_queued()
```

Repeat in `resume_from_audio()` `finally` (~line 172) — same `_start_next_queued()` line after `_lock.release()`.

- [ ] **Step 5: Remove 409 guard in `jobs.py` trigger endpoint**

Find in `web/routes/jobs.py` (~lines 80–83):
```python
    if not started:
        update_job(job_id, status="failed", error="Lock acquire failed")
        raise HTTPException(409, "Pipeline already running")
```
Delete those 3 lines (`trigger_job` now always returns True). The `return {"job_id": job_id, "date": run_date, "status": "queued"}` line below stays.

- [ ] **Step 6: Verify syntax**

```bash
python -c "import ast; [ast.parse(open(f).read()) for f in ['web/job_runner.py','web/routes/jobs.py']]; print('OK')"
```
Expected: `OK`.

```bash
python -c "from web.job_runner import trigger_job, _job_queue, _start_next_queued; print('imports ok, queue empty:', len(_job_queue))"
```
Expected: `imports ok, queue empty: 0`

- [ ] **Step 7: Commit**

```bash
git add web/job_runner.py web/routes/jobs.py
git commit -m "fix: FIFO job queue so trending mode can dispatch N jobs sequentially"
```

---

## Task 2: Backend — platform_meta.json data model + endpoints

**Files:**
- Modify: `web/routes/jobs.py`

Add two endpoints: `GET /api/jobs/{id}/platform_meta` (reads the file or seeds from news.json) and `PUT /api/jobs/{id}/platform_meta` (saves edits).

**Schema** — fixed 6 platforms, each with platform-specific fields matching Upload-Post's API:

```json
{
  "youtube":   {"title": "...", "description": "...", "tags": "AI,科技", "use_auto_thumbnail": true},
  "tiktok":    {"title": "..."},
  "instagram": {"title": "...", "first_comment": "..."},
  "facebook":  {"title": "...", "description": "..."},
  "threads":   {"title": "..."},
  "x":         {"title": "..."}
}
```

`title` is the platform's caption / post body. `description` (YouTube/Facebook) is the longer body. `tags` (YouTube only) is a comma-separated string. `first_comment` (Instagram) holds hashtag spam separate from the caption. `use_auto_thumbnail` (YouTube only) controls whether the Remotion-rendered thumbnail is uploaded as the custom cover.

- [ ] **Step 1: Add seeding helper + GET endpoint**

In `web/routes/jobs.py`, after the existing `patch_item_script` function (if present) or after `upload_screenshot` (from Task 1 of the previous plan — look for `@router.post("/jobs/{job_id}/screenshots/{n}/upload")`), add:

```python
PLATFORMS = ["youtube", "tiktok", "instagram", "facebook", "threads", "x"]


def _seed_platform_meta(news: dict) -> dict:
    """Build default per-platform meta from news.json items (option B: shared baseline)."""
    items = news.get("items", [])
    if not items:
        titles    = [""]
        hooks     = [""]
        scripts   = [""]
    else:
        titles  = [it.get("title", "")  for it in items]
        hooks   = [it.get("hook", "")   for it in items]
        scripts = [it.get("script") or it.get("summary", "") for it in items]

    main_title = " | ".join(t for t in titles if t)[:100]
    long_desc  = "\n\n".join(f"【{h}】{s}" for h, s in zip(hooks, scripts) if s)
    hashtags   = "#AI快訊 #人工智慧 #科技新聞"

    return {
        "youtube": {
            "title":             main_title,
            "description":       f"{long_desc}\n\n{hashtags}",
            "tags":              "AI,人工智慧,科技新聞,AINews,TechNews",
            "use_auto_thumbnail": True,
        },
        "tiktok":    {"title": f"{main_title}\n\n{hashtags}"},
        "instagram": {"title": main_title,
                      "first_comment": hashtags},
        "facebook":  {"title": main_title,
                      "description": f"{long_desc}\n\n{hashtags}"},
        "threads":   {"title": f"{main_title[:450]}\n\n{hashtags}"},
        "x":         {"title": f"{main_title[:240]} {hashtags}"[:280]},
    }


@router.get("/jobs/{job_id}/platform_meta")
def get_platform_meta(job_id: int):
    """Return per-platform meta (seeded from news.json if file doesn't exist yet)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir    = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    meta_file   = pipe_dir / "platform_meta.json"
    news_file   = pipe_dir / "news.json"

    if meta_file.exists():
        return _json.loads(meta_file.read_text(encoding="utf-8"))

    if not news_file.exists():
        raise HTTPException(400, "news.json not found; cannot seed platform meta")

    news = _json.loads(news_file.read_text(encoding="utf-8"))
    return _seed_platform_meta(news)


class PlatformMetaUpdate(BaseModel):
    platform_meta: dict   # full shape {youtube: {...}, tiktok: {...}, ...}


@router.put("/jobs/{job_id}/platform_meta")
def put_platform_meta(job_id: int, body: PlatformMetaUpdate):
    """Save per-platform meta (overwrites platform_meta.json)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    pipe_dir.mkdir(parents=True, exist_ok=True)
    meta_file = pipe_dir / "platform_meta.json"
    meta_file.write_text(
        _json.dumps(body.platform_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"ok": True}
```

- [ ] **Step 2: Smoke-test endpoints**

```bash
curl -s http://localhost:8000/api/jobs/65/platform_meta | python -m json.tool | head -20
```
Expected: JSON with keys `youtube`, `tiktok`, `instagram`, `facebook`, `threads`, `x`. Since job 65 has news.json but no platform_meta.json yet, this will be the seeded default.

```bash
curl -s -X PUT http://localhost:8000/api/jobs/999/platform_meta \
  -H "Content-Type: application/json" \
  -d '{"platform_meta":{"youtube":{"title":"test"}}}'
```
Expected: `{"detail":"Job not found"}` (proves endpoint is routed; 999 doesn't exist).

- [ ] **Step 3: Commit**

```bash
git add web/routes/jobs.py
git commit -m "feat: GET/PUT /api/jobs/{id}/platform_meta with news.json seeding"
```

---

## Task 3: Publisher.py per-platform field mapping + thumbnail

**Files:**
- Modify: `scripts/publisher.py`

Read `platform_meta.json` if present and map each platform's fields to Upload-Post's per-platform API. Wire YouTube's custom thumbnail from `pipeline/.../thumbnail.png`.

- [ ] **Step 1: Load platform meta in `publish()`**

Find `publish()` function (~line 39). After the existing `data = json.loads(news_file.read_text(...))` line, add:

```python
    meta_file = pipe_dir / "platform_meta.json"
    pmeta = (
        json.loads(meta_file.read_text(encoding="utf-8"))
        if meta_file.exists() else {}
    )
```

- [ ] **Step 2: Build per-platform kwargs instead of shared kwargs**

Replace the current per-platform logic (the `yt_platforms`/`ig_platforms`/`tt_platforms`/`other_platforms` block and the single `client.upload_video(**kwargs)` call, lines ~70-104) with per-platform kwarg building:

```python
    # Per-platform kwargs derived from platform_meta.json (falls back to meta if missing)
    fallback_title = meta["title"]
    fallback_desc  = meta["description"]

    def _p(platform: str) -> dict:
        """Return platform-specific meta dict (never None)."""
        return (pmeta or {}).get(platform, {})

    # Build upload kwargs — platform-specific fields merged
    kwargs = dict(async_upload=True, description=fallback_desc)

    # Per-platform titles (override default)
    for p in ("youtube", "tiktok", "instagram", "facebook", "threads", "x"):
        if p in platforms:
            title = _p(p).get("title") or fallback_title
            kwargs[f"{p}_title"] = title

    # YouTube-specific
    if "youtube" in platforms:
        yt = _p("youtube")
        kwargs["youtube_description"] = yt.get("description") or fallback_desc
        if yt.get("tags"):
            # tags in UP is array; accept comma-separated string → list
            kwargs["tags"] = [t.strip() for t in yt["tags"].split(",") if t.strip()]
        else:
            kwargs["tags"] = ["AI", "人工智慧", "科技新聞", "AINews", "TechNews"]
        kwargs["privacyStatus"]          = "public"
        kwargs["containsSyntheticMedia"] = True
        kwargs["defaultAudioLanguage"]   = "zh-TW"
        # Wire auto-thumbnail if requested and file exists
        thumb_path = pipe_dir / "thumbnail.png"
        if yt.get("use_auto_thumbnail", True) and thumb_path.exists():
            kwargs["thumbnail"] = str(thumb_path)

    # Instagram / Threads / Facebook share Upload-Post media_type
    if any(p in platforms for p in ("instagram", "threads", "facebook")):
        kwargs["media_type"]    = "REELS"
        kwargs["share_to_feed"] = True

    # Facebook extra description
    if "facebook" in platforms:
        kwargs["facebook_description"] = _p("facebook").get("description") or fallback_desc

    # Instagram first_comment (hashtag spam)
    if "instagram" in platforms:
        fc = _p("instagram").get("first_comment", "")
        if fc:
            kwargs["first_comment"] = fc

    # TikTok
    if "tiktok" in platforms:
        kwargs["privacy_level"] = "PUBLIC_TO_EVERYONE"

    resp = client.upload_video(
        video_path = str(output_mp4),
        title      = fallback_title,   # default for any platform without override
        user       = PROFILE,
        platforms  = platforms,
        **kwargs,
    )
```

- [ ] **Step 3: Syntax check**

```bash
python -c "import ast; ast.parse(open('scripts/publisher.py').read()); print('OK')"
```
Expected: `OK`.

- [ ] **Step 4: Dry-run test with platform_meta**

Create a test platform_meta for an existing job (e.g., job 65):
```bash
python -c "
from pathlib import Path
import json
p = Path('pipeline/2026-04-16/job_65/platform_meta.json')
p.write_text(json.dumps({
  'youtube': {'title': 'YT Test', 'description': 'YT desc', 'tags': 'a,b,c', 'use_auto_thumbnail': True},
  'tiktok': {'title': 'TT Test #ai'},
  'instagram': {'title': 'IG Test', 'first_comment': '#ai #tech'},
  'facebook': {'title': 'FB Test', 'description': 'FB desc'},
  'threads': {'title': 'TH Test #ai'},
  'x': {'title': 'X Test #ai'}
}, ensure_ascii=False, indent=2), encoding='utf-8')
print('wrote', p)
"

python scripts/publisher.py 2026-04-16/job_65 --platforms youtube tiktok --dry-run
```
Expected: no errors, preview shows the test titles.

Cleanup: `rm pipeline/2026-04-16/job_65/platform_meta.json`

- [ ] **Step 5: Commit**

```bash
git add scripts/publisher.py
git commit -m "feat: publisher maps platform_meta.json to Upload-Post per-platform fields"
```

---

## Task 4: Frontend — preview page skeleton + navigation

**Files:**
- Modify: `web/static/index.html`

Add a new Alpine page `page='upload'` that loads `platform_meta` for the current job. Empty grid placeholder for now — Task 5 fills in the cards. Add a "前往上傳預覽" button on the "done" view that switches to this page.

- [ ] **Step 1: Add Alpine data fields**

In the Alpine `data` block, near `scriptOverrides: {},` (from previous plan's Task 2) or near `uploadPlatforms: ...`, add:

```js
// Upload preview page state
platformMeta: null,          // {youtube:{...}, tiktok:{...}, ...}
platformMetaLoading: false,
editingPlatform: null,       // 'youtube' | 'tiktok' | ... | null (modal open for this platform)
```

- [ ] **Step 2: Add `loadPlatformMeta()` method**

In the Alpine methods section, near `continueJob()`:

```js
async loadPlatformMeta(jobId) {
  this.platformMetaLoading = true
  try {
    this.platformMeta = await this.api('GET', `/api/jobs/${jobId}/platform_meta`)
  } catch (e) {
    this.showToast('載入平台設定失敗：' + e.message)
    this.platformMeta = null
  } finally {
    this.platformMetaLoading = false
  }
},

async savePlatformMeta() {
  if (!this.platformMeta || !this.currentJob) return
  try {
    await this.api('PUT', `/api/jobs/${this.currentJob.id}/platform_meta`,
                   { platform_meta: this.platformMeta })
    this.showToast('已儲存')
  } catch (e) {
    this.showToast('儲存失敗：' + e.message)
  }
},

openUploadPreview() {
  if (!this.currentJob) return
  this.page = 'upload'
  this.loadPlatformMeta(this.currentJob.id)
},
```

- [ ] **Step 3: Add "前往上傳預覽" button on done views**

In `web/static/index.html`, find BOTH done-view sections (there are two: one in the new-job pipeline view around line ~740, one in the job-detail view around line ~1100). Each has the existing `<button ... @click="uploadJob()">` with text "上傳到平台" or similar. Replace that button with a "前往上傳預覽" button:

```html
<button x-show="currentJob?.step_upload !== 'done' && currentJob?.step_upload !== 'uploading'"
  @click="openUploadPreview()"
  class="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-green-600 hover:bg-green-700 text-white transition-all glow-sm">
  🎬 前往上傳預覽
</button>
```

(Keep the other surrounding buttons like 上傳中/已完成 indicators and 重新生成影片.)

- [ ] **Step 4: Add `page='upload'` page container (skeleton)**

After the existing `page='job'` Job Detail page's closing `</div>`, and before `page='accounts'` starts, add:

```html
<!-- ── Upload Preview ─────────────────────────────────────────── -->
<div x-show="page==='upload'" class="p-8 max-w-6xl mx-auto space-y-6">
  <div class="flex items-center gap-3">
    <button @click="page='job'" class="text-sm text-gray-400 hover:text-gray-600 transition-colors flex items-center gap-1">
      ← 返回
    </button>
    <div class="h-4 w-px bg-gray-200"></div>
    <h1 class="text-xl font-bold text-gray-900">
      📤 上傳預覽 — Job #<span x-text="currentJob?.id ?? '...'"></span>
    </h1>
  </div>

  <!-- Loading state -->
  <div x-show="platformMetaLoading" class="glass rounded-2xl p-12 text-center">
    <div class="w-10 h-10 rounded-full border-2 border-green-500 border-t-transparent animate-spin mx-auto mb-4"></div>
    <p class="text-sm text-gray-500">載入中…</p>
  </div>

  <!-- Platform cards grid (filled in Task 5) -->
  <div x-show="!platformMetaLoading && platformMeta" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
       id="platform-cards">
    <!-- Cards will render here (Task 5) -->
  </div>

  <!-- Action bar -->
  <div x-show="!platformMetaLoading && platformMeta" class="glass rounded-2xl p-5 flex items-center justify-between sticky bottom-4">
    <div class="text-xs text-gray-500">
      將上傳到 <span x-text="uploadPlatforms.size"></span> 個平台
    </div>
    <div class="flex gap-3">
      <button @click="savePlatformMeta()"
        class="px-4 py-2 rounded-xl text-sm font-medium bg-gray-100 hover:bg-gray-200 text-gray-700 transition-all">
        💾 儲存草稿
      </button>
      <button @click="savePlatformMeta().then(() => uploadJob())"
        :disabled="uploadPlatforms.size === 0 || !uploadKeySet"
        :class="(uploadPlatforms.size === 0 || !uploadKeySet) ? 'opacity-40 cursor-not-allowed' : 'hover:bg-green-700'"
        class="px-5 py-2 rounded-xl text-sm font-semibold bg-green-600 text-white transition-all glow-sm">
        🚀 全部上傳
      </button>
    </div>
  </div>
</div>
```

- [ ] **Step 5: Verify navigation works**

Start backend (if not running). Open `http://localhost:8000/ui` → go to an existing done job (e.g., `#/?page=job&id=65` or navigate via dashboard) → click "前往上傳預覽" → should land on the upload preview page with the loading spinner then an empty grid + action bar.

```bash
python -c "s=open('web/static/index.html',encoding='utf-8').read(); print('has_upload_page:', \"page==='upload'\" in s); print('has_load:', 'loadPlatformMeta' in s); print('has_save:', 'savePlatformMeta' in s); print('has_open:', 'openUploadPreview' in s)"
```
Expected: all 4 True.

- [ ] **Step 6: Commit**

```bash
git add web/static/index.html
git commit -m "feat: upload preview page skeleton + platform_meta loading"
```

---

## Task 5: Frontend — 6 platform cards with authentic styling

**Files:**
- Modify: `web/static/index.html`

Replace the empty `<!-- Cards will render here (Task 5) -->` placeholder with 6 cards. Each card uses the platform's actual brand colors + inline SVG logo + typography. Click the card body to open the edit modal.

Each card shows: platform logo (top), simulated content preview (video thumbnail + title + description excerpt + hashtags), and an "編輯" button. The existing screenshot preview (thumbnail.png via `/api/media/jobs/{id}/thumbnail`) is the video poster.

- [ ] **Step 1: Add platform style constants to Alpine data**

In the Alpine data block, near `_STRATEGY_PLATFORMS`, add:

```js
_PLATFORM_STYLE: {
  youtube:   { bg: 'bg-white',               text: 'text-gray-900', accent: '#FF0000', name: 'YouTube Shorts', logo: 'yt' },
  tiktok:    { bg: 'bg-black',               text: 'text-white',    accent: '#FE2C55', name: 'TikTok',         logo: 'tt' },
  instagram: { bg: 'bg-gradient-to-br from-[#833AB4] via-[#FD1D1D] to-[#FCAF45]',
               text: 'text-white',    accent: '#ffffff', name: 'Instagram Reels', logo: 'ig' },
  facebook:  { bg: 'bg-[#18191A]',           text: 'text-white',    accent: '#1877F2', name: 'Facebook Reels', logo: 'fb' },
  threads:   { bg: 'bg-black',               text: 'text-white',    accent: '#ffffff', name: 'Threads',        logo: 'th' },
  x:         { bg: 'bg-black',               text: 'text-white',    accent: '#1D9BF0', name: 'X (Twitter)',    logo: 'x'  },
},
```

- [ ] **Step 2: Replace the grid placeholder with the 6 cards template**

Find the placeholder `<!-- Cards will render here (Task 5) -->` from Task 4 Step 4. Replace the surrounding `<div class="grid...">` block with:

```html
<div x-show="!platformMetaLoading && platformMeta"
     class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">

  <template x-for="pid in ['youtube','tiktok','instagram','facebook','threads','x']" :key="pid">
    <div class="relative rounded-2xl overflow-hidden shadow-lg border border-gray-200"
         :class="_PLATFORM_STYLE[pid].bg + ' ' + _PLATFORM_STYLE[pid].text">

      <!-- Header: platform logo + enable toggle -->
      <div class="flex items-center justify-between p-3 border-b border-white/10">
        <div class="flex items-center gap-2">
          <!-- Logo SVG (switch by pid) -->
          <span x-html="_platformSvg(pid)"></span>
          <span class="text-xs font-semibold" x-text="_PLATFORM_STYLE[pid].name"></span>
        </div>
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" class="accent-green-500"
            :checked="uploadPlatforms.has(pid)"
            @change="togglePlatform(pid)">
          <span class="text-[10px] opacity-70">啟用</span>
        </label>
      </div>

      <!-- Video thumbnail (shared across all cards) -->
      <div class="relative aspect-[9/16] bg-black mx-auto" style="max-width:280px">
        <img x-show="currentJob"
             :src="'http://localhost:8000/api/media/jobs/' + currentJob?.id + '/thumbnail?t=' + encodeURIComponent(currentJob?.finished_at || currentJob?.id)"
             class="w-full h-full object-cover"
             @error="$event.target.style.display='none'"
             alt="thumbnail">
        <!-- Play button overlay -->
        <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div class="w-14 h-14 rounded-full bg-black/40 flex items-center justify-center backdrop-blur-sm">
            <svg class="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
          </div>
        </div>
      </div>

      <!-- Content preview (platform-style typography) -->
      <div class="p-3 space-y-1.5 text-[12px]">
        <!-- Title -->
        <p class="font-semibold line-clamp-2 leading-snug"
           x-text="platformMeta[pid]?.title || '(未設定標題)'"></p>

        <!-- Description excerpt (YouTube/Facebook) -->
        <p x-show="['youtube','facebook'].includes(pid) && platformMeta[pid]?.description"
           class="opacity-60 text-[11px] line-clamp-2"
           x-text="platformMeta[pid]?.description"></p>

        <!-- Hashtags (Instagram first_comment, YouTube tags) -->
        <div x-show="pid==='youtube' && platformMeta[pid]?.tags"
             class="flex flex-wrap gap-1 mt-1">
          <template x-for="tag in (platformMeta[pid]?.tags || '').split(',').filter(t => t.trim())" :key="tag">
            <span class="text-[10px] px-1.5 py-0.5 rounded border border-white/20" x-text="'#' + tag.trim()"></span>
          </template>
        </div>
        <p x-show="pid==='instagram' && platformMeta[pid]?.first_comment"
           class="text-[10px] opacity-70 italic line-clamp-1"
           x-text="'💬 ' + platformMeta[pid]?.first_comment"></p>
      </div>

      <!-- Edit button -->
      <button @click="editingPlatform = pid"
        class="absolute top-2 right-2 text-[11px] px-2.5 py-1 rounded-lg bg-white/20 hover:bg-white/30 backdrop-blur-sm font-medium">
        🖌️ 編輯
      </button>
    </div>
  </template>
</div>
```

- [ ] **Step 3: Add `togglePlatform` and `_platformSvg` methods**

In the Alpine methods section:

```js
togglePlatform(pid) {
  const s = new Set(this.uploadPlatforms)
  if (s.has(pid)) s.delete(pid); else s.add(pid)
  this.uploadPlatforms = s
},

_platformSvg(pid) {
  // Inline SVG logos (simpleicons.org path data, white fill, 16x16)
  const paths = {
    yt: '<svg class="w-4 h-4" fill="#FF0000" viewBox="0 0 24 24"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>',
    tt: '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z"/></svg>',
    ig: '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 1 0 0 12.324 6.162 6.162 0 0 0 0-12.324zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.406-11.845a1.44 1.44 0 1 0 0 2.881 1.44 1.44 0 0 0 0-2.881z"/></svg>',
    fb: '<svg class="w-4 h-4" fill="#1877F2" viewBox="0 0 24 24"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>',
    th: '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M12.186 24h-.007c-3.581-.024-6.334-1.205-8.184-3.509C2.35 18.44 1.5 15.586 1.472 12.01v-.017c.03-3.579.879-6.43 2.525-8.482C5.845 1.205 8.6.024 12.18 0h.014c2.746.02 5.043.725 6.826 2.098 1.677 1.29 2.858 3.13 3.509 5.467l-2.04.569c-1.104-3.96-3.898-5.984-8.304-6.015-2.91.022-5.11.936-6.54 2.717C4.307 6.504 3.616 8.914 3.589 12c.027 3.086.718 5.496 2.057 7.164 1.43 1.783 3.631 2.698 6.54 2.717 2.623-.02 4.358-.631 5.8-2.045 1.647-1.613 1.618-3.593 1.09-4.798-.31-.71-.873-1.3-1.634-1.75-.192 1.352-.622 2.446-1.284 3.272-.886 1.102-2.14 1.704-3.73 1.79-1.202.065-2.361-.218-3.259-.801-1.063-.689-1.685-1.74-1.752-2.964-.065-1.19.408-2.285 1.33-3.082.88-.76 2.119-1.207 3.583-1.291a13.853 13.853 0 0 1 3.02.142c-.126-.742-.375-1.332-.75-1.757-.513-.586-1.308-.883-2.359-.89h-.029c-.844 0-1.992.232-2.721 1.32L7.734 7.847c.98-1.454 2.568-2.256 4.478-2.256h.044c3.194.02 5.097 1.975 5.287 5.388.108.046.216.094.321.142 1.49.7 2.58 1.761 3.154 3.07.797 1.82.871 4.79-1.548 7.158-1.848 1.81-4.091 2.628-7.277 2.65Zm1.003-11.69c-.242 0-.487.007-.739.021-1.836.103-2.98.946-2.916 2.143.067 1.256 1.452 1.839 2.784 1.767 1.224-.065 2.818-.543 3.086-3.71a10.5 10.5 0 0 0-2.215-.221z"/></svg>',
    x:  '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>',
  }
  return paths[pid] || ''
},
```

- [ ] **Step 4: Verify grid renders**

Restart backend if needed. Open browser → job 65 → "前往上傳預覽" → should see 6 colored cards: YouTube white/red, TikTok black/pink, Instagram pink gradient, Facebook dark-blue, Threads black, X black/blue. Each card shows the thumbnail in a 9:16 preview with play button overlay.

```bash
python -c "s=open('web/static/index.html',encoding='utf-8').read(); print('_PLATFORM_STYLE:', '_PLATFORM_STYLE' in s); print('togglePlatform:', 'togglePlatform' in s); print('platformSvg:', '_platformSvg' in s); print('six_cards template:', \"'youtube','tiktok','instagram','facebook','threads','x'\" in s)"
```
Expected: all 4 True.

- [ ] **Step 5: Commit**

```bash
git add web/static/index.html
git commit -m "feat: 6 platform-styled cards with inline SVG logos in upload preview"
```

---

## Task 6: Frontend — edit modal + save + upload wiring

**Files:**
- Modify: `web/static/index.html`

A single modal that renders the right fields based on `editingPlatform`. Clicking "🖌️ 編輯" on any card sets `editingPlatform = pid` and opens the modal. Save writes to `platformMeta[pid]` and PUTs to backend.

- [ ] **Step 1: Add edit-modal HTML at the end of the upload preview page**

Inside the `<div x-show="page==='upload'">` container (after the action bar), add:

```html
<!-- Edit modal -->
<div x-show="editingPlatform" x-cloak
     class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6"
     @click.self="editingPlatform = null">
  <div class="bg-white rounded-2xl w-[95vw] max-w-2xl max-h-[90vh] flex flex-col overflow-hidden shadow-2xl">
    <div class="flex items-center justify-between px-5 py-3 border-b border-gray-100">
      <p class="text-sm font-semibold text-gray-700">
        🖌️ 編輯 <span x-text="_PLATFORM_STYLE[editingPlatform]?.name"></span>
      </p>
      <button @click="editingPlatform = null"
        class="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5">
        完成
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-5 space-y-4" x-show="editingPlatform && platformMeta">
      <!-- Title (all platforms) -->
      <div>
        <label class="text-xs font-medium text-gray-500 block mb-1">
          標題 / 文案 <span class="text-gray-400"
            x-text="'(' + (platformMeta[editingPlatform]?.title || '').length + ' 字)'"></span>
        </label>
        <textarea x-model="platformMeta[editingPlatform].title" rows="3"
          class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500/30 focus:border-green-500"></textarea>
        <p x-show="editingPlatform==='x'" class="text-[10px] text-gray-400 mt-1">X 單則貼文最多 280 字</p>
        <p x-show="editingPlatform==='tiktok'" class="text-[10px] text-gray-400 mt-1">TikTok caption 含 #hashtag 最多 2200 字</p>
      </div>

      <!-- YouTube/Facebook: description -->
      <div x-show="['youtube','facebook'].includes(editingPlatform)">
        <label class="text-xs font-medium text-gray-500 block mb-1">影片描述</label>
        <textarea x-model="platformMeta[editingPlatform].description" rows="5"
          class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500/30 focus:border-green-500"></textarea>
      </div>

      <!-- YouTube: tags -->
      <div x-show="editingPlatform==='youtube'">
        <label class="text-xs font-medium text-gray-500 block mb-1">標籤（逗號分隔）</label>
        <input x-model="platformMeta[editingPlatform].tags" type="text"
          placeholder="AI,人工智慧,科技"
          class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500/30 focus:border-green-500">
      </div>

      <!-- YouTube: auto thumbnail toggle -->
      <div x-show="editingPlatform==='youtube'" class="flex items-center gap-2">
        <input type="checkbox" id="yt-thumb"
          :checked="platformMeta[editingPlatform].use_auto_thumbnail"
          @change="platformMeta[editingPlatform].use_auto_thumbnail = $event.target.checked"
          class="accent-green-500">
        <label for="yt-thumb" class="text-xs text-gray-700">
          使用自動生成的封面縮圖（1080×1920）
        </label>
      </div>

      <!-- Instagram: first_comment -->
      <div x-show="editingPlatform==='instagram'">
        <label class="text-xs font-medium text-gray-500 block mb-1">
          首條留言（自動發布 hashtag，避免洗版 caption）
        </label>
        <textarea x-model="platformMeta[editingPlatform].first_comment" rows="2"
          placeholder="#AI #人工智慧 #科技新聞"
          class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500/30 focus:border-green-500"></textarea>
      </div>
    </div>

    <div class="border-t border-gray-100 p-4 flex justify-end gap-2">
      <button @click="editingPlatform = null"
        class="px-4 py-2 rounded-xl text-sm font-medium bg-gray-100 hover:bg-gray-200 text-gray-700">
        取消
      </button>
      <button @click="savePlatformMeta().then(() => editingPlatform = null)"
        class="px-5 py-2 rounded-xl text-sm font-semibold bg-green-600 hover:bg-green-700 text-white">
        儲存
      </button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Wire "全部上傳" to respect platform_meta**

Find the `uploadJob()` method in Alpine (search for `async uploadJob`). Currently it calls `POST /api/jobs/{id}/upload` with just platforms. Update it to first PUT platform_meta (so publisher reads the latest), then trigger upload:

```js
async uploadJob() {
  if (!this.currentJob) return
  const platforms = [...this.uploadPlatforms]
  if (platforms.length === 0) {
    this.showToast('沒有選擇任何平台')
    return
  }
  // Save platform_meta first if we have one loaded (from upload preview page)
  if (this.platformMeta) {
    try {
      await this.api('PUT', `/api/jobs/${this.currentJob.id}/platform_meta`,
                     { platform_meta: this.platformMeta })
    } catch (e) {
      this.showToast('儲存草稿失敗：' + e.message)
      return
    }
  }
  try {
    await this.api('POST', `/api/jobs/${this.currentJob.id}/upload`, { platforms })
    this.currentJob.step_upload = 'uploading'
    this.subscribeSSE(this.currentJob.id)
    this.showToast(`開始上傳到 ${platforms.length} 個平台…`)
  } catch (e) { this.showToast('上傳失敗：' + e.message) }
},
```

(Replace the existing `uploadJob` entirely — match its original signature / Alpine placement.)

- [ ] **Step 3: Manual E2E test**

1. Start backend (restart if needed).
2. Open `http://localhost:8000/ui`, pick job 65.
3. Click "前往上傳預覽" → see 6 cards.
4. Click 編輯 on TikTok card → modal opens with title textarea pre-filled.
5. Edit the title to add "🔥 TEST" at the end → click 儲存 → toast "已儲存".
6. Reload the page. Go back to upload preview. TikTok card should still show the edited title.
7. Check `pipeline/2026-04-16/job_65/platform_meta.json` — has the edit.
8. Delete the test file when done.

- [ ] **Step 4: Verify modal works via grep**

```bash
python -c "s=open('web/static/index.html',encoding='utf-8').read(); print('modal:', \"editingPlatform\" in s and 'x-show=\"editingPlatform\"' in s); print('save_close:', 'savePlatformMeta().then' in s); print('use_auto_thumbnail:', 'use_auto_thumbnail' in s)"
```
Expected: all 3 True.

- [ ] **Step 5: Commit**

```bash
git add web/static/index.html
git commit -m "feat: platform edit modal + upload wiring with platform_meta PUT"
```

---

## Self-Review

**1. Spec coverage:**
- Trending 3→1 bug → Task 1 (queue) ✅
- 6 platform preview frames → Task 5 (6 cards with per-platform styling) ✅
- Per-platform title/description/hashtag editing → Task 6 (edit modal) ✅
- Upload-Post per-platform API usage → Task 3 (publisher maps each field) ✅
- Auto-thumbnail wired to YouTube → Task 3 + Task 6 (toggle in modal) ✅
- Option B (shared baseline, edit per platform) → Task 2 (`_seed_platform_meta` builds same base, user overrides) ✅
- Option A (authentic styling) → Task 5 (brand colors, inline SVG logos, platform typography hints) ✅

**2. Placeholder scan:** All steps have concrete code. No TBD/TODO. The SVG strings in Task 5 Step 3 are the full paths.

**3. Type consistency:**
- `platformMeta` is a dict with 6 fixed keys in Task 2 (`_seed_platform_meta`), Task 4 (loadPlatformMeta reads same), Task 5 (template iterates `['youtube','tiktok','instagram','facebook','threads','x']`), Task 6 (modal keys off `editingPlatform`) ✅
- Per-platform fields: `youtube.{title,description,tags,use_auto_thumbnail}`, `instagram.{title,first_comment}`, `facebook.{title,description}`, `tiktok.{title}`, `threads.{title}`, `x.{title}` — same keys across Task 2 seed, Task 3 publisher map, Task 5 card render, Task 6 modal ✅
- `_PLATFORM_STYLE` keys match Task 5 template platform IDs ✅
- `uploadPlatforms` is a `Set<string>` across original codebase + Task 5 `togglePlatform` (creates new Set) ✅

**4. Scope check:** Two loosely related scopes (Task 1 is independent trending fix; Tasks 2-6 are the preview feature). Acceptable as a single plan because: (a) trending fix is trivial (1 task), (b) both affect the same `upload` flow conceptually, (c) user requested both "按順序" together. Total: 6 tasks ≈ 1 day of work.
