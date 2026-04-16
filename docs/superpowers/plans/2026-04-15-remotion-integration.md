# Remotion Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing Remotion project into the AutoVideo pipeline as an alternative video renderer with a UI toggle, end-to-end tested with a real job.

**Architecture:** A `video_renderer` setting (`"ffmpeg"` | `"remotion"`) controls which compositor `job_runner.py` invokes at Step 4. The Remotion project lives at `remotion/` and is invoked by `scripts/remotion_renderer.py`, which builds props from `pipeline/DATE/job_ID/news.json` and shells out to `npx remotion render`. Output filename matches the FFmpeg compositor (`output.mp4` in the same job dir) so downstream code (publisher, UI preview) needs zero changes.

**Tech Stack:** Remotion 4.x (React + TypeScript), Node.js, Python subprocess bridge, FastAPI settings.

**Pre-flight context:**
- `remotion/` dir exists with `package.json`, `remotion.config.ts`, `tsconfig.json`, `src/{index.tsx,NewsVideo.tsx,NewsItem.tsx,Subtitle.tsx,types.ts}` — but `node_modules` is gitignored and may not be installed
- `scripts/remotion_renderer.py` exists but has two bugs: (1) only handles `DATE` not `DATE/job_ID`, (2) writes to `output_remotion.mp4` instead of `output.mp4`
- `web/job_runner.py` Step 4 currently always calls `video_composer.py` (FFmpeg) — needs renderer selection
- The pipeline writes audio to `pipeline/DATE/job_ID/audio/audio_NN.mp3` and screenshots to `pipeline/DATE/job_ID/screenshots/news_NN.png`
- Default settings inserted in `web/db.py:init_db()` already include `background_mode`, `ai_video_mode` etc — add `video_renderer` similarly

---

### Task 1: Verify Remotion project boots and renders default props

**Files:**
- Modify: `remotion/package.json` (only if `npm install` reveals missing peer deps)

- [ ] **Step 1: Install Remotion dependencies**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo/remotion && npm install
```

Expected: completes without errors, creates `node_modules/` and `package-lock.json`. May print peer-dep warnings (ignore unless an error).

- [ ] **Step 2: Render the default placeholder composition to verify the toolchain works**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo/remotion && npx remotion render src/index.tsx NewsVideo out/smoketest.mp4 --overwrite
```

Expected: writes `remotion/out/smoketest.mp4`, exit code 0, log shows `Rendered ... frames`. The default composition has empty audio/screenshot strings, so expect a black screen with "AI 快訊" hook text — that's success for this step.

- [ ] **Step 3: Confirm the output file exists and has size > 10KB**

```bash
ls -la C:/Users/User/Documents/GitHub/AutoVideo/remotion/out/smoketest.mp4
```

Expected: file exists, size > 10000 bytes. If render succeeded but the file is missing, the working directory was wrong.

- [ ] **Step 4: Clean up smoketest output**

```bash
rm -rf C:/Users/User/Documents/GitHub/AutoVideo/remotion/out/
```

- [ ] **Step 5: Commit the verified setup (only `package-lock.json` is new)**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
git add remotion/package-lock.json
git commit -m "chore: lock Remotion dependencies after smoke-test render"
```

If `package-lock.json` was already tracked or unchanged, skip the commit.

---

### Task 2: Fix `scripts/remotion_renderer.py` to handle job sub-directories and write `output.mp4`

**Files:**
- Modify: `scripts/remotion_renderer.py` — fix `TODAY` parsing, output filename, and path resolution to mirror how `video_composer.py` behaves when invoked with `DATE/job_ID`

The current bugs:
- `TODAY = sys.argv[1]` — when called as `python remotion_renderer.py 2026-04-15/job_53`, this becomes `"2026-04-15/job_53"` and `Path("pipeline") / TODAY` does resolve to the right dir, BUT `OUTPUT = PIPE_DIR / "output_remotion.mp4"` should be `output.mp4` so downstream code finds it
- The file name needs to match what `web/job_runner.py` line 281 expects (`output.mp4`)

- [ ] **Step 1: Read the current renderer to confirm what needs changing**

```bash
cat C:/Users/User/Documents/GitHub/AutoVideo/scripts/remotion_renderer.py | head -50
```

- [ ] **Step 2: Change the OUTPUT filename from `output_remotion.mp4` to `output.mp4`**

In `scripts/remotion_renderer.py`, replace the line:

```python
OUTPUT      = PIPE_DIR / "output_remotion.mp4"
```

with:

```python
OUTPUT      = PIPE_DIR / "output.mp4"
```

- [ ] **Step 3: Run the renderer against an existing finished job to test path handling**

Find the most recent successful job's directory:

```bash
ls -1t C:/Users/User/Documents/GitHub/AutoVideo/pipeline/*/job_*/news.json 2>/dev/null | head -3
```

Pick one (e.g., `pipeline/2026-04-14/job_52/news.json`) and run:

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo && python scripts/remotion_renderer.py 2026-04-14/job_52
```

Expected: prints `Building props from ...`, lists items with durations, runs `npx remotion render`, ends with `Done: ...output.mp4`. If audio files are missing for that old job, it raises `FileNotFoundError` — that's a valid signal; pick a job that has audio.

- [ ] **Step 4: Verify the rendered MP4 plays**

```bash
ls -la C:/Users/User/Documents/GitHub/AutoVideo/pipeline/2026-04-14/job_52/output.mp4
```

Expected: file exists, size > 100KB (because real audio is embedded). Open it manually to confirm it plays — but a non-zero size is enough for the automated check.

⚠️ Caution: if there was already an `output.mp4` from FFmpeg in that dir, this overwrites it. That's fine for the test, but warn the user before re-running on production-finished jobs.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
git add scripts/remotion_renderer.py
git commit -m "fix: write Remotion output as output.mp4 to match FFmpeg compositor"
```

---

### Task 3: Add `video_renderer` setting to the database and settings API

**Files:**
- Modify: `web/db.py:73-80` (default settings INSERT) and `web/db.py:83-89` (column migrations — none needed, settings is key/value)
- Modify: `web/routes/settings.py:11-32` (Pydantic model)

- [ ] **Step 1: Add `video_renderer` default to `init_db()`**

In `web/db.py`, find the block:

```python
            INSERT OR IGNORE INTO settings (key, value) VALUES
                ('schedule_hour',    '8'),
                ('schedule_minute',  '0'),
                ('platforms',        'youtube,instagram'),
                ('skip_upload',      'false'),
                ('dry_run',          'false'),
                ('background_mode',  'screenshot'),
                ('ai_video_mode',         ''),
                ('telegram_bot_token',    ''),
                ('telegram_chat_ids',     '');
```

Replace the trailing `'')` line with two lines so it ends:

```python
                ('telegram_chat_ids',     ''),
                ('video_renderer',        'ffmpeg');
```

- [ ] **Step 2: Add `video_renderer` to the `SettingsUpdate` Pydantic model**

In `web/routes/settings.py`, find the AI-video block and append a new field below the Telegram block. The field declaration:

```python
    # 影片渲染器
    video_renderer:       str | None = None   # "ffmpeg" | "remotion"
```

The full updated `SettingsUpdate` should now contain (in order, keep the existing fields above untouched):

```python
    # Telegram Bot
    telegram_bot_token:   str | None = None
    telegram_chat_ids:    str | None = None
    # 影片渲染器
    video_renderer:       str | None = None
```

- [ ] **Step 3: Apply the migration by re-initialising the DB (idempotent)**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo && python -c "from web.db import init_db; init_db(); from web.db import get_setting; print('video_renderer =', repr(get_setting('video_renderer')))"
```

Expected output: `video_renderer = 'ffmpeg'`

- [ ] **Step 4: Verify the API exposes the new field**

Restart the server (or rely on `--reload`), then:

```bash
curl -s http://localhost:8000/api/settings | python -c "import sys,json; d=json.load(sys.stdin); print('video_renderer:', d.get('video_renderer'))"
```

Expected: `video_renderer: ffmpeg`

- [ ] **Step 5: Verify a PUT updates the field**

```bash
curl -s -X PUT http://localhost:8000/api/settings -H "Content-Type: application/json" -d '{"video_renderer":"remotion"}' | python -c "import sys,json; d=json.load(sys.stdin); print('video_renderer:', d.get('video_renderer'))"
```

Expected: `video_renderer: remotion`. Set it back to `ffmpeg` afterward:

```bash
curl -s -X PUT http://localhost:8000/api/settings -H "Content-Type: application/json" -d '{"video_renderer":"ffmpeg"}' >/dev/null
```

- [ ] **Step 6: Commit**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
git add web/db.py web/routes/settings.py
git commit -m "feat: add video_renderer setting (ffmpeg|remotion)"
```

---

### Task 4: Wire renderer selection into `web/job_runner.py` Step 4

**Files:**
- Modify: `web/job_runner.py` — the Step 4 video composition block in `_run_pipeline()` (around the line `# ── Step 4: 合成影片`) and the equivalent block in `resume_from_audio()`

- [ ] **Step 1: Locate the Step 4 block in `_run_pipeline()`**

```bash
grep -n "Step 4: 合成影片\|video_composer.py" C:/Users/User/Documents/GitHub/AutoVideo/web/job_runner.py
```

Expected: two locations — one in `resume_from_audio()` near line 116, one in `_run_pipeline()` near line 280.

- [ ] **Step 2: Replace the Step 4 block in `_run_pipeline()` to dispatch on `video_renderer`**

In `web/job_runner.py`, find:

```python
        # ── Step 4: 合成影片 ────────────────────────────────────────
        su("video", "running")
        ok, out = _call_script("video_composer.py", job_key, [], log_path)
        if not ok:
            su("video", "failed")
            raise RuntimeError(f"video_composer 失敗:\n{out[-500:]}")
        su("video", "done")
```

Replace with:

```python
        # ── Step 4: 合成影片 ────────────────────────────────────────
        renderer = get_setting("video_renderer", "ffmpeg").lower()
        script_name = "remotion_renderer.py" if renderer == "remotion" else "video_composer.py"
        su("video", "running")
        ok, out = _call_script(script_name, job_key, [], log_path)
        if not ok:
            su("video", "failed")
            raise RuntimeError(f"{script_name} 失敗:\n{out[-500:]}")
        su("video", "done")
```

- [ ] **Step 3: Apply the same change in `resume_from_audio()`**

In the same file, find:

```python
            _step_update(job_id, date, "video", "running")
            ok, out = _call_script("video_composer.py", job_key, [], log_path)
            if not ok:
                _step_update(job_id, date, "video", "failed")
                update_job(job_id, status="failed", error=out[-300:])
                _broadcast(job_id, {"job_id": job_id, "status": "failed"})
                return
            _step_update(job_id, date, "video", "done")
```

Replace with:

```python
            renderer = get_setting("video_renderer", "ffmpeg").lower()
            script_name = "remotion_renderer.py" if renderer == "remotion" else "video_composer.py"
            _step_update(job_id, date, "video", "running")
            ok, out = _call_script(script_name, job_key, [], log_path)
            if not ok:
                _step_update(job_id, date, "video", "failed")
                update_job(job_id, status="failed", error=out[-300:])
                _broadcast(job_id, {"job_id": job_id, "status": "failed"})
                return
            _step_update(job_id, date, "video", "done")
```

- [ ] **Step 4: Increase subprocess timeout for Remotion renders**

`web/job_runner.py:_call_script()` has `timeout=600` (10 min). Remotion renders can take 5–8 min for a 90s video on a typical laptop. Bump to 1500s (25 min). Find this line:

```python
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600
    )
```

Replace `timeout=600` with `timeout=1500`.

- [ ] **Step 5: Smoke-test the dispatch logic without actually running a job**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo && python -c "
from web.db import set_setting, get_setting
for r in ('remotion', 'ffmpeg', 'unknown', ''):
    set_setting('video_renderer', r)
    val = get_setting('video_renderer', 'ffmpeg').lower()
    script = 'remotion_renderer.py' if val == 'remotion' else 'video_composer.py'
    print(f'  setting={r!r:12s} → resolved={val!r:12s} → script={script}')
set_setting('video_renderer', 'ffmpeg')
"
```

Expected output:

```
  setting='remotion'   → resolved='remotion'   → script=remotion_renderer.py
  setting='ffmpeg'     → resolved='ffmpeg'     → script=video_composer.py
  setting='unknown'    → resolved='unknown'    → script=video_composer.py
  setting=''           → resolved=''           → script=video_composer.py
```

The third and fourth rows confirm that anything other than `"remotion"` falls back to FFmpeg — that's the safety property we want.

- [ ] **Step 6: Commit**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
git add web/job_runner.py
git commit -m "feat: dispatch Step 4 to remotion or ffmpeg renderer per setting"
```

---

### Task 5: Add a renderer toggle to the settings UI

**Files:**
- Modify: `web/static/index.html` — add a card next to the existing "AI 圖生影片" / "Telegram" cards in the settings page

- [ ] **Step 1: Find the insertion point — right after the AI video card, before the Telegram card**

```bash
grep -n "Telegram 手機遙控\|AI 圖生影片" C:/Users/User/Documents/GitHub/AutoVideo/web/static/index.html
```

Expected: a line for `🎬 AI 圖生影片 B-roll` and a line for `📱 Telegram 手機遙控`. The new card goes between them.

- [ ] **Step 2: Insert the new card before the Telegram card**

In `web/static/index.html`, find the closing of the AI video card immediately before the Telegram card:

```html
          </template>
        </div>

        <!-- Telegram Bot 設定 -->
```

Insert this block between the `</div>` and the `<!-- Telegram Bot 設定 -->` comment:

```html
        <!-- 影片渲染器 -->
        <div class="glass rounded-2xl p-5 space-y-3">
          <h3 class="text-sm font-semibold text-gray-700">🎞️ 影片渲染器</h3>
          <p class="text-xs text-gray-400">Remotion 提供 React 動畫（彈跳、漸入、Ken Burns）；FFmpeg 較快但僅靜態合成</p>
          <select x-model="settings.video_renderer"
            class="w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
            <option value="ffmpeg">FFmpeg（快速、穩定，預設）</option>
            <option value="remotion">Remotion（React 動畫，較慢）</option>
          </select>
          <p x-show="settings.video_renderer === 'remotion'" class="text-xs text-amber-600">
            ⚠️ 首次使用需在 <span class="font-mono bg-gray-100 px-1 rounded">remotion/</span> 執行 <span class="font-mono bg-gray-100 px-1 rounded">npm install</span>，渲染時間約 5–10 分鐘
          </p>
        </div>
```

- [ ] **Step 3: Reload the UI in the browser and verify the new card appears**

Open `http://localhost:8000/ui` → 設定. Expected: a new card titled "🎞️ 影片渲染器" with a dropdown showing FFmpeg/Remotion options. The current value should reflect what's in the DB.

- [ ] **Step 4: Switch the dropdown to Remotion, click 儲存設定, then verify persistence**

```bash
curl -s http://localhost:8000/api/settings | python -c "import sys,json; print(json.load(sys.stdin).get('video_renderer'))"
```

Expected: `remotion`

Switch back to FFmpeg in the UI before continuing.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
git add web/static/index.html
git commit -m "feat: add renderer toggle to settings UI"
```

---

### Task 6: End-to-end test with a real Telegram-triggered job

This task validates the full flow: Telegram `/run` → news → screenshot review → audio → Remotion render → MP4 delivered to Telegram.

- [ ] **Step 1: Set the renderer to Remotion via API**

```bash
curl -s -X PUT http://localhost:8000/api/settings -H "Content-Type: application/json" -d '{"video_renderer":"remotion"}' >/dev/null
```

- [ ] **Step 2: Trigger a job from Telegram**

On phone: send `/run` to `@Autovideo0108_bot`. Then approve the script-review and screenshot-review buttons as they arrive.

- [ ] **Step 3: Watch the server log for the renderer dispatch**

```bash
tail -f C:/Users/User/AppData/Local/Temp/claude/.../tasks/<latest>.output | grep -i "remotion\|video_composer"
```

Expected: at Step 4 you should see `Running Remotion render` (from `remotion_renderer.py` stderr), not any `ffmpeg` activity.

- [ ] **Step 4: When the job finishes, verify the MP4 is from Remotion**

```bash
JOB_ID=$(python -c "from web.db import list_jobs; print(list_jobs(limit=1)[0]['id'])")
DATE=$(python -c "from web.db import list_jobs; print(list_jobs(limit=1)[0]['date'])")
ls -la "C:/Users/User/Documents/GitHub/AutoVideo/pipeline/${DATE}/job_${JOB_ID}/output.mp4"
```

Expected: file exists, recent timestamp, size > 1MB. Confirm visually by playing it — Remotion output has spring slide-in hook text, smooth Ken Burns, fade subtitle transitions; FFmpeg output is more static.

- [ ] **Step 5: Verify the bot delivered the MP4 to Telegram**

Check phone — should have received the video file with caption `AutoVideo #<job_id>`.

- [ ] **Step 6: Switch the renderer back to FFmpeg as the default**

```bash
curl -s -X PUT http://localhost:8000/api/settings -H "Content-Type: application/json" -d '{"video_renderer":"ffmpeg"}' >/dev/null
```

Rationale: FFmpeg renders ~5× faster and Remotion is the opt-in path for users who want the animations. Default to the fast path.

- [ ] **Step 7: Final commit (only if any small fixes were needed during testing)**

If the e2e test surfaced a bug (e.g., a Remotion crash on an edge case), fix it and commit. Otherwise no commit needed for this task.

---

## Self-Review

**Spec coverage:**
- Toolchain works → Task 1 ✅
- Path/filename bugs in renderer → Task 2 ✅
- Setting + API → Task 3 ✅
- Job runner dispatch → Task 4 ✅
- UI toggle → Task 5 ✅
- End-to-end validation → Task 6 ✅

**Placeholder scan:** No TBDs, no "implement later", no "similar to Task N", no "add appropriate error handling". Each step has the actual command or code change.

**Type / name consistency:** The setting key is `video_renderer` and values are `"ffmpeg"` / `"remotion"` everywhere (db default, Pydantic model, job_runner dispatch, UI dropdown). Renderer script names are `video_composer.py` and `remotion_renderer.py` everywhere. Output filename is `output.mp4` everywhere.

**Risks called out inline:** Task 2 Step 4 warns about overwriting an existing `output.mp4`; Task 4 Step 4 explains the timeout bump; Task 5 Step 2 references the existing AI video card by anchor text.
