# AutoVideo Bug Fixes + Remotion Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two confirmed bugs (screenshot-review script editing blocked, trending mode only creates 1 job) and polish Remotion with `@remotion/transitions` slide effects, Ken Burns zoom, and a dynamic item counter.

**Architecture:**
- **Bug A** (截圖審查腳本鎖定): After news replacement the backend already returns the new script in `data.item`; the frontend just discards it. Fix: store it in `scriptOverrides`, show editable fields inline per replaced shot, persist on `continueJob()` via new `PATCH /api/jobs/{id}/items/{n}/script`.
- **Bug B** (趨勢模式只跑 1 則): `trigger_job()` returns False when another job holds the lock; `jobs.py` 409s all subsequent triggers. Fix: add a FIFO `_job_queue` deque — enqueue instead of returning False, dequeue in the `finally` block so jobs run sequentially.
- **Remotion polish**: install `@remotion/transitions`, replace manual crossfade `Sequence` overlap with `TransitionSeries` + alternating `slide()`, add Ken Burns zoom on screenshots, spring-entrance on the item counter, and fix hardcoded `/ 03`.

**Tech Stack:** Python / FastAPI, Alpine.js (vanilla HTML SPA), Remotion 4.x, TypeScript / React, `@remotion/transitions` package.

---

## File Map

| File | Change |
|------|--------|
| `web/routes/jobs.py` | Add `PATCH /api/jobs/{id}/items/{n}/script` endpoint (~after line 343) |
| `web/job_runner.py` | Add `_job_queue` deque, `_start_next_queued()`, update `trigger_job()` and both `finally` blocks |
| `web/routes/jobs.py` | Remove 409 guard after `trigger_job()` returns (lines ~80-83) |
| `web/static/index.html` | `scriptOverrides` state; `replaceNewsItem` populates it; inline editor HTML in screenshot review; `continueJob` saves overrides first |
| `remotion/package.json` | Add `@remotion/transitions: ^4.0.0` |
| `remotion/src/NewsVideo.tsx` | Full rewrite: `TransitionSeries` + `slide()`; updated `calcTotalFrames` |
| `remotion/src/NewsItem.tsx` | Add `totalItems` prop; fix `/ 03`; Ken Burns zoom; counter spring entrance |

---

## Task 1: Backend — PATCH script endpoint

**Files:**
- Modify: `web/routes/jobs.py` (after line 343, before `@router.get("/jobs/{job_id}/news")`)

After replacing a news item the frontend needs to persist any hook/script/scene_type edits without re-triggering the pipeline.

- [ ] **Step 1: Add `ScriptPatchRequest` model and endpoint**

In `web/routes/jobs.py`, after the closing `}` of the `replace_item` function (~line 343), add:

```python
class ScriptPatchRequest(BaseModel):
    hook:       str | None = None
    script:     str | None = None
    scene_type: str | None = None


@router.patch("/jobs/{job_id}/items/{n}/script")
def patch_item_script(job_id: int, n: int, body: ScriptPatchRequest):
    """Patch hook/script/scene_type for a single item in news.json.
    Called by the frontend after inline edits in the screenshot review phase."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    news_file = pipe_dir / "news.json"
    if not news_file.exists():
        raise HTTPException(404, "news.json not found")

    data  = _json.loads(news_file.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if n < 1 or n > len(items):
        raise HTTPException(400, f"Item {n} out of range (1–{len(items)})")

    item = items[n - 1]
    if body.hook       is not None: item["hook"]       = body.hook
    if body.script     is not None: item["script"]     = body.script
    if body.scene_type is not None: item["scene_type"] = body.scene_type
    data["items"] = items
    news_file.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}
```

- [ ] **Step 2: Smoke-test the endpoint**

Start the backend (`python -m uvicorn web.app:app --reload --port 8000`) and run:
```bash
curl -s -X PATCH http://localhost:8000/api/jobs/999/items/1/script \
  -H "Content-Type: application/json" \
  -d '{"hook": "test"}'
```
Expected: `{"detail":"Job not found"}` (404) — proves the endpoint is registered and routed correctly.

- [ ] **Step 3: Commit**

```bash
git add web/routes/jobs.py
git commit -m "feat: PATCH /api/jobs/{id}/items/{n}/script endpoint for inline script edits"
```

---

## Task 2: Frontend — Inline script editor in screenshot review

**Files:**
- Modify: `web/static/index.html`

Four changes to one file — do them in order.

- [ ] **Step 1: Add `scriptOverrides: {}` to Alpine data** (line 1457, after `replacePanelOpen: null,`)

Find:
```js
replacePanelOpen: null,   // shot.index of open replace panel
```
Add one line after it:
```js
scriptOverrides: {},      // shotIndex → {hook, script, scene_type} after replace
```

- [ ] **Step 2: Update `replaceNewsItem()` to populate `scriptOverrides`**

Find the existing `replaceNewsItem` method (~line 2095). After the `if (idx !== -1)` block that updates `this.screenshots[idx]`, add:

```js
if (data.item) {
  this.scriptOverrides = {
    ...this.scriptOverrides,
    [shotIndex]: {
      hook:       data.item.hook       || '',
      script:     data.item.script     || data.item.summary || '',
      scene_type: data.item.scene_type || 'default',
    },
  }
}
```

The spread ensures Alpine detects the object change reactively.

- [ ] **Step 3: Add inline editor HTML after the replace panel in each screenshot card**

In the screenshot review section, find the closing `</div>` of the replace panel block:
```html
                </div>
              </div>
            </template>
          </div>

                <!-- Replace panel -->
```

After the replace panel `</div>` (the one with `x-show="replacePanelOpen === shot.index"`), add:

```html
                <!-- Inline script editor (shown after replace) -->
                <div x-show="scriptOverrides[shot.index]"
                  class="border-t border-blue-100 bg-blue-50/40 p-4 space-y-2">
                  <p class="text-[11px] font-semibold text-blue-600 mb-2">
                    已替換 — 可修改腳本後再確認：
                  </p>
                  <template x-if="scriptOverrides[shot.index]">
                    <div class="space-y-2">
                      <div>
                        <label class="text-[10px] text-gray-400 block mb-0.5">Hook</label>
                        <input x-model="scriptOverrides[shot.index].hook" type="text"
                          class="w-full bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-300">
                      </div>
                      <div>
                        <label class="text-[10px] text-gray-400 block mb-0.5">動畫場景</label>
                        <select x-model="scriptOverrides[shot.index].scene_type"
                          class="w-full bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-300">
                          <option value="default">預設（文字卡片）</option>
                          <option value="fire">🔥 攻擊/爆炸/燃燒</option>
                          <option value="race">🏃 競賽/追趕/對決</option>
                          <option value="money">💰 融資/估值/錢</option>
                          <option value="robot">🤖 AI/機器人/科技</option>
                          <option value="warning">⚠️ 爭議/警告/風險</option>
                          <option value="trophy">🏆 突破/獲獎/創紀錄</option>
                        </select>
                      </div>
                      <div>
                        <label class="text-[10px] text-gray-400 block mb-0.5">
                          腳本 <span class="text-gray-300"
                            x-text="'(' + (scriptOverrides[shot.index]?.script||'').length + ' 字)'">
                          </span>
                        </label>
                        <textarea x-model="scriptOverrides[shot.index].script" rows="3"
                          class="w-full bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-300 resize-none">
                        </textarea>
                      </div>
                    </div>
                  </template>
                </div>
```

- [ ] **Step 4: Update `continueJob()` to save overrides before proceeding** (line 1986)

Replace the existing `continueJob` method (lines 1986–1993):
```js
async continueJob() {
  // Persist any inline script edits made after news replacement
  const overrides = Object.entries(this.scriptOverrides)
  for (const [idxStr, edits] of overrides) {
    const n = parseInt(idxStr)
    try {
      await this.api('PATCH', `/api/jobs/${this.currentJob.id}/items/${n}/script`, edits)
    } catch (e) {
      this.showToast(`腳本存檔失敗 (#${n})：${e.message}`)
    }
  }
  this.scriptOverrides = {}
  try {
    await this.api('POST', `/api/jobs/${this.currentJob.id}/continue`)
    this.currentJob.step_audio = 'running'
    this.subscribeSSE(this.currentJob.id)
    this.showToast('繼續生成語音與影片…')
  } catch (e) { this.showToast('繼續失敗：' + e.message) }
},
```

- [ ] **Step 5: Manual test**

1. Start a new job (news mode) and let it reach screenshot review (`step_audio === 'review'`)
2. Click "替換新聞" on item #1 and select a replacement — verify inline editor appears with hook/script/scene_type pre-filled
3. Edit the hook to something unique, e.g. `"EDITED"`
4. Click "確認截圖，繼續生成語音與影片 →"
5. Open `pipeline/DATE/job_N/news.json` and verify item 1's `hook` is `"EDITED"`

- [ ] **Step 6: Commit**

```bash
git add web/static/index.html
git commit -m "feat: inline script editor in screenshot review after news replacement"
```

---

## Task 3: Job queue — trending mode triggers N sequential jobs

**Files:**
- Modify: `web/job_runner.py`
- Modify: `web/routes/jobs.py`

Root cause: `trigger_job()` returns `False` when `_lock` is already held; `jobs.py` immediately marks all subsequent jobs `failed` and raises HTTP 409. Trending mode loops `trendingEnriched` and fires one trigger per item — only the first succeeds.

Fix: add a `_job_queue` deque. When the lock is held, push params onto the queue and return `True`. In both pipeline `finally` blocks, call `_start_next_queued()` to drain the queue sequentially.

- [ ] **Step 1: Add `_job_queue` deque** (after `_cancel_flags` line, ~line 18 of `job_runner.py`)

```python
import collections as _collections
_job_queue: _collections.deque = _collections.deque()  # pending job params
```

- [ ] **Step 2: Add `_start_next_queued()` helper** (after the `_broadcast` function, before `set_event_loop`)

```python
def _start_next_queued():
    """Start the next queued job if one is waiting. Called after current job finishes."""
    if not _job_queue:
        return
    params = _job_queue.popleft()
    trigger_job(**params)
```

- [ ] **Step 3: Replace `trigger_job()` body** (lines ~351–369)

```python
def trigger_job(job_id: int, date: str, topic: str | None = None,
                platforms: list[str] = None, skip_upload: bool = False,
                dry_run: bool = False,
                pre_news: list[dict] | None = None,
                account_profile: str | None = None) -> bool:
    """Returns True always — job runs immediately or is enqueued for sequential execution."""
    global _running_job_id
    if platforms is None:
        platforms = get_setting("platforms", "youtube,instagram").split(",")
    if not _lock.acquire(blocking=False):
        # Another job is running — queue this one for after it finishes
        _job_queue.append({
            "job_id": job_id, "date": date, "topic": topic,
            "platforms": platforms, "skip_upload": skip_upload,
            "dry_run": dry_run, "pre_news": pre_news,
            "account_profile": account_profile,
        })
        return True
    _running_job_id = job_id
    t = threading.Thread(
        target=_run_pipeline,
        args=(job_id, date, topic, platforms, skip_upload, dry_run, pre_news, account_profile),
        daemon=True,
    )
    t.start()
    return True
```

- [ ] **Step 4: Add `_start_next_queued()` to `_run_pipeline` finally block** (~line 346)

Find:
```python
        _cancel_flags.pop(job_id, None)
        _running_job_id = None
        _lock.release()
```
Add one line after `_lock.release()`:
```python
        _start_next_queued()
```

- [ ] **Step 5: Add `_start_next_queued()` to `resume_from_audio` finally block** (~line 172)

Same pattern — find the `_lock.release()` and add `_start_next_queued()` after it.

- [ ] **Step 6: Update `jobs.py` trigger endpoint — remove the 409 guard** (~lines 79–83)

Find:
```python
    if not started:
        update_job(job_id, status="failed", error="Lock acquire failed")
        raise HTTPException(409, "Pipeline already running")
```
Replace with nothing (delete those 3 lines). The `return` below stays:
```python
    return {"job_id": job_id, "date": run_date, "status": "queued"}
```

- [ ] **Step 7: Manual test — 3 trending items**

1. In trending mode select 3 items, click "送出產生影片"
2. Check dashboard — should see 3 jobs created, first transitions to `running`, next starts when it finishes
3. No "送出失敗" toasts should appear for items 2 and 3

- [ ] **Step 8: Commit**

```bash
git add web/job_runner.py web/routes/jobs.py
git commit -m "feat: job queue — trending mode queues N jobs for sequential execution"
```

---

## Task 4: Remotion — install @remotion/transitions

**Files:**
- Modify: `remotion/package.json`

- [ ] **Step 1: Edit package.json — add dependency**

In `remotion/package.json`, update `"dependencies"`:
```json
"dependencies": {
  "@remotion/cli": "^4.0.0",
  "remotion": "^4.0.0",
  "@remotion/transitions": "^4.0.0",
  "react": "^18.0.0",
  "react-dom": "^18.0.0"
}
```

- [ ] **Step 2: Install**

```bash
cd remotion && npm install
```
Expected: resolves `@remotion/transitions@4.x.x`, no peer-dep warnings.

- [ ] **Step 3: Verify TypeScript can import it**

```bash
cd remotion && node -e "require('@remotion/transitions')" && echo "OK"
```
Expected: `OK` (no module-not-found errors).

- [ ] **Step 4: Commit**

```bash
cd ..
git add remotion/package.json remotion/package-lock.json
git commit -m "deps: add @remotion/transitions ^4.0.0"
```

---

## Task 5: Remotion — TransitionSeries slide transitions + fix calcTotalFrames

**Files:**
- Modify: `remotion/src/NewsVideo.tsx` (full rewrite)
- Modify: `remotion/src/NewsItem.tsx` (add `totalItems` prop)

Replace the manual crossfade (Sequence from= arithmetic with 9-frame overlap) with `TransitionSeries` + `slide()`. Alternating left/right slide directions keeps multi-item videos visually varied.

`springTiming({durationInFrames: 18, config: {damping: 200}})` gives a snappy 0.6 s slide with a hint of spring overshoot — fast enough not to feel sluggish, slow enough to read.

`calcTotalFrames` must subtract transition overlap: with `n` items the total is `Σ durations − (n−1) × TRANSITION_FRAMES`.

- [ ] **Step 1: Rewrite `remotion/src/NewsVideo.tsx`**

```tsx
import React from "react";
import { AbsoluteFill } from "remotion";
import { TransitionSeries, springTiming } from "@remotion/transitions";
import { slide } from "@remotion/transitions/slide";
import { NewsVideoProps } from "./types";
import { NewsItemComponent } from "./NewsItem";

const FPS = 30;
const TRANSITION_FRAMES = 18; // 0.6 s slide

export const NewsVideo: React.FC<NewsVideoProps> = ({ items }) => {
  const segments = items.map((item) => ({
    item,
    durationFrames: Math.round((item.duration + 0.3) * FPS),
  }));

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <TransitionSeries>
        {segments.flatMap(({ item, durationFrames }, idx) => {
          const nodes: React.ReactNode[] = [
            <TransitionSeries.Sequence key={`seq-${idx}`} durationInFrames={durationFrames}>
              <NewsItemComponent
                item={item}
                index={idx}
                totalItems={items.length}
                totalFrames={durationFrames}
              />
            </TransitionSeries.Sequence>,
          ];
          if (idx < segments.length - 1) {
            nodes.push(
              <TransitionSeries.Transition
                key={`trans-${idx}`}
                timing={springTiming({
                  durationInFrames: TRANSITION_FRAMES,
                  config: { damping: 200 },
                })}
                presentation={slide({
                  direction: idx % 2 === 0 ? "from-right" : "from-left",
                })}
              />
            );
          }
          return nodes;
        })}
      </TransitionSeries>
    </AbsoluteFill>
  );
};

export function calcTotalFrames(items: NewsVideoProps["items"]): number {
  if (!items || items.length === 0) return FPS * 10;
  const segmentTotal = items.reduce(
    (sum, item) => sum + Math.round((item.duration + 0.3) * FPS),
    0
  );
  const transitionTotal = (items.length - 1) * TRANSITION_FRAMES;
  return Math.max(FPS * 3, segmentTotal - transitionTotal);
}
```

- [ ] **Step 2: Add `totalItems` prop to `NewsItem.tsx`**

Find the `NewsItemProps` interface (~line 36):
```tsx
interface NewsItemProps {
  item: NewsItemType;
  index: number;
  totalFrames: number;
}
```
Replace with:
```tsx
interface NewsItemProps {
  item: NewsItemType;
  index: number;
  totalItems: number;
  totalFrames: number;
}
```

Find the component signature:
```tsx
export const NewsItemComponent: React.FC<NewsItemProps> = ({
  item,
  index,
  totalFrames,
}) => {
```
Replace with:
```tsx
export const NewsItemComponent: React.FC<NewsItemProps> = ({
  item,
  index,
  totalItems,
  totalFrames,
}) => {
```

Find the hardcoded counter text (~line 202):
```tsx
          {String(index + 1).padStart(2, "0")} / 03
```
Replace with:
```tsx
          {String(index + 1).padStart(2, "0")} / {String(totalItems).padStart(2, "0")}
```

- [ ] **Step 3: TypeScript check**

```bash
cd remotion && npx tsc --noEmit
```
Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
cd ..
git add remotion/src/NewsVideo.tsx remotion/src/NewsItem.tsx
git commit -m "feat: TransitionSeries slide transitions + dynamic item counter"
```

---

## Task 6: Remotion — Ken Burns zoom + counter spring entrance

**Files:**
- Modify: `remotion/src/NewsItem.tsx`

Two visual upgrades, both pure `NewsItem.tsx` changes:

1. **Ken Burns**: interpolate screenshot `scale` from 1.0 → 1.06 over the full segment. The outer container has `overflow: hidden` so the zoom never bleeds outside the rounded card.
2. **Counter spring**: replace the simple `opacity: sourceProgress` fade with a spring that drops in from above (`translateY(-30 → 0)`) — feels more like a broadcast lower-third.

- [ ] **Step 1: Add `kenScale` interpolation** (inside `NewsItemComponent` body, after the existing `sourceProgress` variable ~line 109)

```tsx
  // Ken Burns: slow zoom on screenshot
  const kenScale = interpolate(localFrame, [0, totalFrames], [1.0, 1.06], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Counter spring entrance (delayed 8 frames so hook enters first)
  const counterSpring = spring({
    fps,
    frame: Math.max(0, localFrame - 8),
    config: { damping: 14, stiffness: 200, mass: 0.5 },
    durationInFrames: 20,
  });
  const counterY = interpolate(counterSpring, [0, 1], [-30, 0]);
  const counterOpacity = interpolate(counterSpring, [0, 0.4, 1], [0, 1, 1]);
```

- [ ] **Step 2: Apply Ken Burns to the `<Img>` block** (~line 277)

Find the existing screenshot `<Img>` block:
```tsx
              <Img
                src={screenshotSrc}
                style={{
                  width: "100%",
                  objectFit: "cover",
                  display: "block",
                }}
              />
```
Replace with:
```tsx
              <Img
                src={screenshotSrc}
                style={{
                  width: "100%",
                  objectFit: "cover",
                  display: "block",
                  transform: `scale(${kenScale})`,
                  transformOrigin: "center center",
                }}
              />
```

The parent div already has `overflow: "hidden"` via the existing screenshot container — no additional change needed.

- [ ] **Step 3: Apply counter spring** (~line 183)

Find the item counter container style:
```tsx
        style={{
          position: "absolute",
          top: 80,
          right: 60,
          zIndex: 20,
          opacity: sourceProgress,
        }}
```
Replace with:
```tsx
        style={{
          position: "absolute",
          top: 80,
          right: 60,
          zIndex: 20,
          opacity: counterOpacity,
          transform: `translateY(${counterY}px)`,
        }}
```

- [ ] **Step 4: TypeScript check**

```bash
cd remotion && npx tsc --noEmit
```
Expected: 0 errors.

- [ ] **Step 5: End-to-end render test**

If a completed job exists (`pipeline/2026-04-16/job_65/` from the screenshot in the conversation):
```bash
python scripts/remotion_renderer.py 2026-04-16/job_65
```
Expected: `Done: pipeline/2026-04-16/job_65/output.mp4`

Open the output in a media player and verify:
- Slide transition plays between segments (not just a fade)
- Screenshot zooms subtly over its segment
- Counter badge drops in with a spring bounce
- Counter reads `01 / 03` (or however many items there are), not hardcoded `01 / 03` if count changes

- [ ] **Step 6: Commit**

```bash
cd ..
git add remotion/src/NewsItem.tsx
git commit -m "feat: Ken Burns zoom on screenshots + spring counter entrance"
```

---

## Self-Review

**1. Spec coverage:**
- 截圖審查替換後腳本可編輯 → Task 1 (API endpoint) + Task 2 (UI inline editor + continueJob) ✅
- 趨勢模式只產生1則 → Task 3 (job queue in job_runner + remove 409 in jobs.py) ✅
- Remotion 轉場 → Task 4 (install) + Task 5 (TransitionSeries slide) ✅
- Remotion 分鏡精修 → Task 6 (Ken Burns + counter spring) ✅
- 硬碼 `/ 03` → Task 5 Step 2 ✅

**2. Placeholder scan:** All steps have exact code. No TBD.

**3. Type consistency:**
- `totalItems` added to `NewsItemProps` in Task 5 Step 2; used in counter in Task 5 Step 2; passed from `NewsVideo.tsx` in Task 5 Step 1 — consistent ✅
- `TRANSITION_FRAMES = 18` defined in `NewsVideo.tsx` Task 5 Step 1; referenced in `calcTotalFrames` same file — consistent ✅
- `ScriptPatchRequest` fields `{hook, script, scene_type}` match what `continueJob()` sends in Task 2 Step 4 — consistent ✅
- `scriptOverrides[shotIndex]` set in `replaceNewsItem` Task 2 Step 2; read in HTML `x-model` Task 2 Step 3; iterated in `continueJob` Task 2 Step 4 — consistent ✅
