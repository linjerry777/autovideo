# Dual-Version (Short + Long) Video Generation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every new job produces TWO final videos — `short/output.mp4` (10-12s/item, 30-40 字) and `long/output.mp4` (20-25s/item, 60-80 字) — so each platform can use the version best matching its algorithm. Platform-to-version mapping is automatic (Short→TT/IG/FB/Threads, Long→YT/X/Pinterest/LinkedIn/Reddit) but user-overridable in the upload preview UI.

**Architecture:**
- **Script generation** (`claude_client.py` + `news_collector.py`): every Claude enrichment call now returns `script_short` (30-40 chars) AND `script_long` (60-80 chars) per item. Legacy `script` field kept = copy of `script_long` for backward compat with existing jobs.
- **Pipeline branching**: `audio_generator.py` / `remotion_renderer.py` / `thumbnail_renderer.py` each accept `--version short|long` CLI arg; output goes to `pipeline/{date}/job_{id}/{version}/*`. Thumbnail stays shared at job root (single image works for both).
- **Job runner**: `_run_pipeline` detects presence of `script_short` + `script_long` in news.json → loops `[short, long]` and runs audio + video twice. Old jobs without new fields use legacy single-render path.
- **Publisher mapping**: `platform_meta.json` gets new `video_version: "short" | "long"` field per platform. Publisher reads it and uploads the matching `{version}/output.mp4`.
- **UI**: each platform card in upload preview gets a 📱 Short / 💻 Long toggle. Defaults seeded per platform's natural fit; user can flip.

**Tech Stack:** Python (Claude Proxy, Fish Audio SDK, ffmpeg subprocess), Remotion 4.x, FastAPI routes, Alpine.js (no new deps).

---

## Platform → Version Default Mapping

```
Short (~10-12s per item)   →   TikTok, Instagram Reels, Facebook Reels, Threads
Long  (~20-25s per item)   →   YouTube Shorts, X, Pinterest, LinkedIn, Reddit
```

Rationale: TT/IG/FB/Threads algorithms favor 10-30s completion-rate; YT Shorts / X / Pinterest / LinkedIn / Reddit tolerate and prefer 30-60s for depth.

---

## File Map

| File | Change |
|------|--------|
| `web/claude_client.py` | `enrich_news_items` + `enrich_trending_items` prompts return both scripts |
| `scripts/news_collector.py` | `select_news_with_claude` prompt returns both scripts |
| `scripts/audio_generator.py` | Accept `--version short\|long`; write to `{version}/audio/*`; pick script field based on flag |
| `scripts/remotion_renderer.py` | Accept `--version`; read from `{version}/audio/`; write to `{version}/output.mp4` |
| `scripts/thumbnail_renderer.py` | No version arg (thumbnail shared); stays at job root |
| `web/job_runner.py` | If new schema detected → run both versions; else legacy single-render |
| `web/routes/jobs.py` | `_seed_platform_meta` adds `video_version` per platform |
| `scripts/publisher.py` | Read `video_version` per platform; use `{version}/output.mp4` |
| `web/static/index.html` | 📱/💻 toggle on each platform card; persists via existing platform_meta PUT |
| `web/routes/media.py` | `GET /api/media/jobs/{id}/video` accepts optional `?v=short\|long` param |

---

## Task 1: Claude prompts produce `script_short` + `script_long`

**Files:**
- Modify: `web/claude_client.py` — `enrich_news_items` prompt (~line 66) + `enrich_trending_items` prompt (~line 132)
- Modify: `scripts/news_collector.py` — `select_news_with_claude` prompt (~line 85)

All 3 Claude entry points must now return both script versions as independent rewrites (not truncation).

- [ ] **Step 1: Update `enrich_news_items` prompt in `claude_client.py`**

Find the JSON schema block inside the `enrich_news_items` prompt. It currently asks for a `script` field. Replace the `script` line with:

```text
  "script_short": "短版旁白（30-40 字，獨立重寫 — 不是 long 的截斷版，一句話講完核心）",
  "script_long":  "長版旁白（60-80 字，獨立重寫 — 含鋪陳+結論，為長平台而寫）",
  "script":       "= script_long (legacy field, backward compat)",
```

The updated prompt tail should end with this reminder above the existing 「請直接回傳 JSON 陣列」:

```text
script_short 和 script_long 必須是**獨立重寫**的兩份腳本，不是 Long 的截斷版。
Short 適合 TikTok/IG/FB/Threads（節奏快、1 句關鍵）；
Long 適合 YouTube/X/Pinterest/LinkedIn（有鋪陳、有論點）。
```

- [ ] **Step 2: Update `enrich_trending_items` prompt in `claude_client.py`**

Same schema edit: replace `script` line with `script_short` + `script_long` + legacy `script` alias. Same reminder paragraph.

For trending mode, character counts adjust down since N=1:
- `script_short`: 40-50 字（~12s）
- `script_long`: 100-130 字（~30s）

Use these numbers in the `enrich_trending_items` prompt specifically.

- [ ] **Step 3: Update `select_news_with_claude` prompt in `news_collector.py`**

Same edit pattern as Step 1 (news mode, N=3 typical, use 30-40 字 / 60-80 字). The prompt is structured similarly to `enrich_news_items`.

- [ ] **Step 4: Syntax + live Claude call smoke test**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
python -X utf8 -c "
import ast
for f in ['web/claude_client.py', 'scripts/news_collector.py']:
    ast.parse(open(f).read())
    print(f'{f}: OK')
"
```
Expected: both `OK`.

Live Claude call to verify schema:
```bash
python -X utf8 -c "
import sys; sys.path.insert(0, '.')
from web.claude_client import enrich_news_items
raw = [{'title':'AI 突破','summary':'OpenAI 新模型','url':'https://example.com/1','source':'TechCrunch'}]
items = enrich_news_items(raw, topic='AI', strategy='tech')
it = items[0]
print('script_short:', repr(it.get('script_short', '')[:50]))
print(f'  len={len(it.get(\"script_short\", \"\"))}')
print('script_long: ', repr(it.get('script_long', '')[:50]))
print(f'  len={len(it.get(\"script_long\", \"\"))}')
print('legacy script:', repr(it.get('script', '')[:50]))
"
```

Expected:
- `script_short` length roughly 30-50 chars
- `script_long` length roughly 60-90 chars
- `script` exists (legacy) and equals or resembles script_long

- [ ] **Step 5: Commit**

```bash
git add web/claude_client.py scripts/news_collector.py
git commit -m "feat: Claude returns script_short + script_long (independent rewrites)"
```

---

## Task 2: Pipeline scripts accept `--version` flag

**Files:**
- Modify: `scripts/audio_generator.py` — add argparse, write to `{version}/audio/`
- Modify: `scripts/remotion_renderer.py` — add argparse, read from `{version}/audio/`, write to `{version}/output.mp4`

### 2A: `audio_generator.py`

- [ ] **Step 1: Add version arg + path routing**

Near the top of `scripts/audio_generator.py`, find the existing argv-based job_key parsing:

```python
TODAY     = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
```

Replace with argparse-based parsing that accepts `--version`:

```python
import argparse as _ap
_parser = _ap.ArgumentParser()
_parser.add_argument("job_key", nargs="?", default=date.today().isoformat())
_parser.add_argument("--version", choices=["short", "long"], default=None,
                     help="Pick script_short / script_long for dual-version output (default: legacy script)")
_args, _ = _parser.parse_known_args()

TODAY   = _args.job_key
VERSION = _args.version
```

Find where `AUDIO_DIR` is defined:

```python
AUDIO_DIR = PIPE_DIR / "audio"
```

Replace with:

```python
AUDIO_DIR = PIPE_DIR / VERSION / "audio" if VERSION else PIPE_DIR / "audio"
```

- [ ] **Step 2: Pick correct script field in per-item loop**

Inside `main()` per-item loop, find:

```python
        script    = item.get("script") or item.get("summary", "")
```

Replace with:

```python
        # Pick script per version; legacy jobs use 'script'; dual-version uses script_short/long
        if VERSION == "short":
            script = item.get("script_short") or item.get("script") or item.get("summary", "")
        elif VERSION == "long":
            script = item.get("script_long")  or item.get("script") or item.get("summary", "")
        else:
            script = item.get("script") or item.get("summary", "")
```

- [ ] **Step 3: Syntax + live test**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/audio_generator.py').read()); print('OK')"
```
Expected: `OK`

Test legacy path (no --version flag):
```bash
python -X utf8 -c "
import subprocess
r = subprocess.run(['python','-X','utf8','scripts/audio_generator.py','--help'],
                   capture_output=True, text=True)
print(r.stdout)
"
```
Expected: help output shows `--version {short,long}` flag.

### 2B: `remotion_renderer.py`

- [ ] **Step 4: Add version arg + path routing**

Find the top of `scripts/remotion_renderer.py`:

```python
TODAY = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
```

Replace with argparse:

```python
import argparse as _ap
_parser = _ap.ArgumentParser()
_parser.add_argument("job_key", nargs="?", default=date.today().isoformat())
_parser.add_argument("--version", choices=["short", "long"], default=None)
_args, _ = _parser.parse_known_args()

TODAY   = _args.job_key
VERSION = _args.version
```

Find where `AUDIO_DIR`, `OUTPUT` are defined:

```python
AUDIO_DIR = PIPE_DIR / "audio"
OUTPUT    = PIPE_DIR / "output.mp4"
```

Replace with:

```python
if VERSION:
    AUDIO_DIR = PIPE_DIR / VERSION / "audio"
    OUTPUT    = PIPE_DIR / VERSION / "output.mp4"
else:
    AUDIO_DIR = PIPE_DIR / "audio"
    OUTPUT    = PIPE_DIR / "output.mp4"
```

- [ ] **Step 5: Pick script per version in `build_props()`**

Find `build_props()` in `remotion_renderer.py`. Inside the per-item loop, there's a line building the script:

```python
            "script":       item.get("script") or item.get("summary", ""),
```

Replace with:

```python
            "script":       (
                item.get("script_short") if VERSION == "short"
                else item.get("script_long") if VERSION == "long"
                else item.get("script")
            ) or item.get("summary", ""),
```

- [ ] **Step 6: Syntax check**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/remotion_renderer.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add scripts/audio_generator.py scripts/remotion_renderer.py
git commit -m "feat: audio_generator + remotion_renderer accept --version short|long"
```

---

## Task 3: job_runner runs both versions when new schema detected

**Files:**
- Modify: `web/job_runner.py` — `_run_pipeline()` audio + video step

Detect `script_short` + `script_long` in news.json → loop `[short, long]`. Otherwise legacy single-render.

- [ ] **Step 1: Replace audio + video steps with version-aware loop**

In `web/job_runner.py`, find the audio step in `_run_pipeline`. Currently (around line 298-304):

```python
        # ── Step 3: 語音生成 ────────────────────────────────────────
        su("audio", "running")
        extra = ["--dry-run"] if dry_run else []
        ok, out = _call_script("audio_generator.py", job_key, extra, log_path)
        if not ok:
            su("audio", "failed")
            raise RuntimeError(f"audio_generator 失敗:\n{out[-500:]}")
        su("audio", "done")
        _check_cancel(job_id)
```

And the video step (around line 315-322):

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

Replace BOTH blocks (preserve the ai_video step between them untouched) with a version-aware block. Insert this helper function at the TOP of `web/job_runner.py` (after the existing imports):

```python
def _detect_versions(job_key: str) -> list[str | None]:
    """Return list of versions to render.

    If news.json has script_short + script_long fields on items → ['short', 'long']
    Else → [None] (legacy single-render)
    """
    import json as _j
    news_file = BASE_DIR / "pipeline" / job_key / "news.json"
    if not news_file.exists():
        return [None]
    try:
        data = _j.loads(news_file.read_text(encoding="utf-8"))
        items = data.get("items", [])
        if items and all(it.get("script_short") and it.get("script_long") for it in items):
            return ["short", "long"]
    except Exception:
        pass
    return [None]
```

Then replace the audio + video step blocks with:

```python
        # ── Step 3+4: 語音 + 影片 (dual-version or legacy) ────────────
        versions = _detect_versions(job_key)
        su("audio", "running")
        for v in versions:
            extra_audio = ["--dry-run"] if dry_run else []
            if v:
                extra_audio = ["--version", v] + extra_audio
            ok, out = _call_script("audio_generator.py", job_key, extra_audio, log_path)
            if not ok:
                su("audio", "failed")
                raise RuntimeError(f"audio_generator({v or 'legacy'}) 失敗:\n{out[-500:]}")
        su("audio", "done")
        _check_cancel(job_id)

        # ── Step 3.5: AI 圖生影片 B-roll (optional) ─────────────
        ai_video_mode = get_setting("ai_video_mode", "").lower()
        if ai_video_mode in ("kling", "replicate"):
            su("ai_video", "running")
            ok_av, out_av = _call_script("ai_video_fetcher.py", job_key, [], log_path)
            su("ai_video", "done" if ok_av else "skipped")
            _check_cancel(job_id)

        # ── Step 4: 合成影片 ────────────────────────────────────────
        renderer = get_setting("video_renderer", "ffmpeg").lower()
        script_name = "remotion_renderer.py" if renderer == "remotion" else "video_composer.py"
        su("video", "running")
        for v in versions:
            extra_video = ["--version", v] if v else []
            ok, out = _call_script(script_name, job_key, extra_video, log_path)
            if not ok:
                su("video", "failed")
                raise RuntimeError(f"{script_name}({v or 'legacy'}) 失敗:\n{out[-500:]}")
        su("video", "done")
```

Note: this moves the existing `ai_video` step between the audio loop and the video loop (which matches the original order). Verify that's correct by comparing with the unchanged code.

- [ ] **Step 2: Update `resume_from_audio` the same way**

Find `resume_from_audio` function in `web/job_runner.py` (~line 111). It has a simpler audio + video flow without the pause points. Apply the same `_detect_versions` + version loop pattern to both its audio step and video step.

The resume function's current audio step:
```python
            _step_update(job_id, date, "audio", "running")
            extra = ["--dry-run"] if dry_run else []
            ok, out = _call_script("audio_generator.py", job_key, extra, log_path)
            if not ok:
                _step_update(job_id, date, "audio", "failed")
                update_job(job_id, status="failed", error=out[-300:])
                _broadcast(job_id, {"job_id": job_id, "status": "failed"})
                return
            _step_update(job_id, date, "audio", "done")
```

Replace with:
```python
            versions = _detect_versions(job_key)
            _step_update(job_id, date, "audio", "running")
            for v in versions:
                extra_audio = ["--dry-run"] if dry_run else []
                if v:
                    extra_audio = ["--version", v] + extra_audio
                ok, out = _call_script("audio_generator.py", job_key, extra_audio, log_path)
                if not ok:
                    _step_update(job_id, date, "audio", "failed")
                    update_job(job_id, status="failed", error=out[-300:])
                    _broadcast(job_id, {"job_id": job_id, "status": "failed"})
                    return
            _step_update(job_id, date, "audio", "done")
```

And the video step in resume_from_audio:
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

Replace with:
```python
            renderer = get_setting("video_renderer", "ffmpeg").lower()
            script_name = "remotion_renderer.py" if renderer == "remotion" else "video_composer.py"
            _step_update(job_id, date, "video", "running")
            for v in versions:
                extra_video = ["--version", v] if v else []
                ok, out = _call_script(script_name, job_key, extra_video, log_path)
                if not ok:
                    _step_update(job_id, date, "video", "failed")
                    update_job(job_id, status="failed", error=out[-300:])
                    _broadcast(job_id, {"job_id": job_id, "status": "failed"})
                    return
            _step_update(job_id, date, "video", "done")
```

(Reuses the `versions` variable computed just before the audio step.)

- [ ] **Step 3: Syntax check**

```bash
python -X utf8 -c "import ast; ast.parse(open('web/job_runner.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add web/job_runner.py
git commit -m "feat: job_runner detects dual-version news.json and renders Short+Long"
```

---

## Task 4: platform_meta seeds `video_version` per platform

**Files:**
- Modify: `web/routes/jobs.py` — `_seed_platform_meta` function

Each platform entry in the seed gets a `video_version` field with a sensible default.

- [ ] **Step 1: Update `_seed_platform_meta`**

Find `_seed_platform_meta` function in `web/routes/jobs.py`. It returns a dict like:

```python
    return {
        "youtube": {
            "title":                 main_title,
            "description":           f"{long_desc}\n\n{hashtags}",
            ...
        },
        "tiktok": {
            "title":                 f"{main_title}\n\n{hashtags}",
            ...
        },
        ...
    }
```

Add `"video_version"` field to each platform's dict with the correct default:

```python
    return {
        "youtube": {
            "title":                 main_title,
            "description":           f"{long_desc}\n\n{hashtags}",
            "tags":                  "AI,人工智慧,科技新聞,AINews,TechNews",
            "use_auto_thumbnail":    True,
            "categoryId":            "22",
            "defaultLanguage":       "zh-Hant",
            "defaultAudioLanguage":  "zh-Hant",
            "privacyStatus":         "public",
            "containsSyntheticMedia": True,
            "selfDeclaredMadeForKids": False,
            "embeddable":            True,
            "publicStatsViewable":   True,
            "license":               "youtube",
            "video_version":         "long",
        },
        "tiktok": {
            "title":                 f"{main_title}\n\n{hashtags}",
            "privacy_level":         "PUBLIC_TO_EVERYONE",
            "is_aigc":               True,
            "cover_timestamp":       1000,
            "disable_duet":          False,
            "disable_comment":       False,
            "disable_stitch":        False,
            "brand_content_toggle":  False,
            "brand_organic_toggle":  False,
            "video_version":         "short",
        },
        "instagram": {
            "title":                 main_title,
            "first_comment":         hashtags,
            "share_mode":            "REELS",
            "share_to_feed":         True,
            "collaborators":         "",
            "user_tags":             "",
            "video_version":         "short",
        },
        "facebook": {
            "title":                 main_title,
            "description":           f"{long_desc}\n\n{hashtags}",
            "facebook_media_type":   "REELS",
            "video_state":           "PUBLISHED",
            "video_version":         "short",
        },
        "threads": {
            "title":                 f"{main_title[:450]}\n\n{hashtags}",
            "threads_topic_tag":     "",
            "video_version":         "short",
        },
        "x": {
            "title":                 f"{main_title[:240]} {hashtags}"[:280],
            "poll_options":          "",
            "poll_duration":         1440,
            "reply_settings":        "everyone",
            "x_long_text_as_post":   False,
            "video_version":         "long",
        },
        "pinterest": {
            "title":                 main_title,
            "description":           f"{long_desc}\n\n{hashtags}",
            "pinterest_board_id":    "",
            "pinterest_link":        "",
            "pinterest_alt_text":    main_title,
            "video_version":         "long",
        },
        "reddit": {
            "title":                 main_title,
            "subreddit":             "",
            "flair_id":              "",
            "video_version":         "long",
        },
        "_schedule": {
            "mode":                  "now",
            "scheduled_date":        "",
            "timezone":              "Asia/Taipei",
        },
    }
```

Note: the existing `_seed_platform_meta` already has most of these fields; you're only ADDING `"video_version"` to each platform dict. Copy-paste entire updated dict to avoid field-name typos.

- [ ] **Step 2: Syntax + live seed test**

```bash
python -X utf8 -c "import ast; ast.parse(open('web/routes/jobs.py').read()); print('OK')"
```
Expected: `OK`

Backend auto-reloads. Re-fetch a seeded meta (delete old file so seed runs):
```bash
rm -f pipeline/2026-04-17/job_69/platform_meta.json
python -X utf8 -c "
import urllib.request, json
with urllib.request.urlopen('http://localhost:8000/api/jobs/69/platform_meta', timeout=10) as r:
    d = json.loads(r.read())
for p in ['youtube','tiktok','instagram','facebook','threads','x','pinterest','reddit']:
    v = d.get(p, {}).get('video_version')
    print(f'  {p:<12} → {v}')
"
```
Expected:
- youtube, x, pinterest, reddit → `long`
- tiktok, instagram, facebook, threads → `short`

- [ ] **Step 3: Commit**

```bash
git add web/routes/jobs.py
git commit -m "feat: platform_meta seeds video_version (short/long) per platform"
```

---

## Task 5: publisher.py picks correct video based on `video_version`

**Files:**
- Modify: `scripts/publisher.py` — `publish()` function

Read `video_version` from each platform's meta; upload `pipeline/.../{version}/output.mp4` instead of legacy `pipeline/.../output.mp4`.

Since Upload-Post uploads ONE video file per call but we want different platforms to get different videos, this requires splitting the upload into 2 calls (one for Short platforms, one for Long platforms).

- [ ] **Step 1: Refactor `publish()` to group platforms by version**

In `scripts/publisher.py`, find `publish()`. After the section where `pmeta` and kwargs are built (after the per-platform mapping block, before `resp = client.upload_video(...)`), REPLACE the single upload call with version-grouped uploads.

Find (existing):

```python
    resp = client.upload_video(
        video_path = str(output_mp4),
        title      = fallback_title,
        user       = PROFILE,
        platforms  = platforms,
        **kwargs,
    )
```

Replace with:

```python
    # Group platforms by video_version; upload each group separately
    version_groups: dict[str, list[str]] = {"short": [], "long": [], "legacy": []}
    for p in platforms:
        v = _platform_meta(p).get("video_version")
        if v == "short":
            version_groups["short"].append(p)
        elif v == "long":
            version_groups["long"].append(p)
        else:
            version_groups["legacy"].append(p)

    responses = []
    for version_key, group in version_groups.items():
        if not group:
            continue
        if version_key == "legacy":
            video_path = output_mp4           # pipeline/.../output.mp4
        else:
            video_path = pipe_dir / version_key / "output.mp4"
            if not video_path.exists():
                # Graceful fallback: if expected version MP4 missing, use legacy
                print(f"⚠️  {video_path.name} 不存在，{group} 改用 legacy output.mp4", file=sys.stderr)
                video_path = output_mp4
                if not video_path.exists():
                    print(f"❌ legacy output.mp4 也不存在，跳過 {group}", file=sys.stderr)
                    continue

        print(f"📤 上傳 {version_key} ({video_path.name}) → {group}")
        resp = client.upload_video(
            video_path = str(video_path),
            title      = fallback_title,
            user       = PROFILE,
            platforms  = group,
            **kwargs,
        )
        responses.append((version_key, resp))

    # Summarize
    all_ok = all(r.get("success") for _, r in responses) if responses else False
    if responses:
        for version_key, resp in responses:
            req_id = resp.get("request_id", "")
            status = "✅" if resp.get("success") else "❌"
            print(f"  {status} {version_key}: request_id={req_id}")
    else:
        print("❌ 沒有任何上傳發生")
        sys.exit(1)
    if not all_ok:
        sys.exit(1)
```

Also: the `output_mp4` variable at the top of `publish()` currently points to `pipe_dir / "output.mp4"`. Keep that line — it's used as fallback for legacy jobs.

- [ ] **Step 2: Syntax check**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/publisher.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Dry-run test with mock version grouping**

```bash
# Set up a platform_meta with mixed versions
python -X utf8 -c "
from pathlib import Path
import json
p = Path('pipeline/2026-04-17/job_69/platform_meta.json')
p.write_text(json.dumps({
  'youtube':   {'title': 'yt', 'description': 'd', 'video_version': 'long', 'use_auto_thumbnail': False, 'tags': 'a', 'privacyStatus':'public', 'containsSyntheticMedia':True, 'selfDeclaredMadeForKids':False, 'embeddable':True, 'publicStatsViewable':True, 'license':'youtube', 'categoryId':'22', 'defaultLanguage':'zh-Hant', 'defaultAudioLanguage':'zh-Hant'},
  'tiktok':    {'title': 'tt', 'video_version': 'short', 'privacy_level':'PUBLIC_TO_EVERYONE', 'is_aigc':True, 'cover_timestamp':1000, 'disable_duet':False, 'disable_comment':False, 'disable_stitch':False, 'brand_content_toggle':False, 'brand_organic_toggle':False},
  'instagram': {'title': 'ig', 'video_version': 'short', 'first_comment':'#a', 'collaborators':'', 'user_tags':''},
  'x':         {'title': 'x',  'video_version': 'long',  'poll_options':'', 'poll_duration':1440, 'reply_settings':'everyone', 'x_long_text_as_post':False},
}, ensure_ascii=False, indent=2), encoding='utf-8')
print('wrote test platform_meta')
"

python -X utf8 scripts/publisher.py 2026-04-17/job_69 --platforms youtube tiktok instagram x --dry-run 2>&1 | tail -20

# Cleanup
rm pipeline/2026-04-17/job_69/platform_meta.json
```

Expected: dry-run preview shows version grouping logic activated (prints may include `📤 上傳 short` + `📤 上傳 long` grouping lines). Depending on where the existing `--dry-run` check short-circuits, the new grouping might not actually print — if so, that's fine (the code is validated by later E2E).

- [ ] **Step 4: Commit**

```bash
git add scripts/publisher.py
git commit -m "feat: publisher groups platforms by video_version and uploads each group separately"
```

---

## Task 6: UI 📱 Short / 💻 Long toggle per platform card

**Files:**
- Modify: `web/static/index.html` — upload preview page, platform cards

Each platform card shows a radio toggle `📱 Short | 💻 Long`. Toggling updates `platformMeta[platform].video_version`. Save happens via the existing "儲存草稿" / "全部上傳" buttons (which already PUT `platform_meta`).

- [ ] **Step 1: Add toggle inside each platform card**

Find the platform card template (iterates `['youtube','tiktok',...,'reddit']`). Inside each card, there's a body containing the thumbnail + title + description preview. Near the top of the card body (just after the header with platform logo + enable toggle), insert:

```html
        <!-- Video version toggle (Short vs Long) -->
        <div class="flex items-center justify-center gap-1 px-3 py-1.5 bg-black/20 text-xs" x-show="platformMeta[pid]">
          <button type="button"
            @click="platformMeta[pid].video_version = 'short'"
            :class="platformMeta[pid]?.video_version === 'short'
              ? 'bg-white/90 text-gray-900 font-semibold'
              : 'text-white/60 hover:text-white'"
            class="px-3 py-1 rounded-full transition-all">
            📱 Short
          </button>
          <button type="button"
            @click="platformMeta[pid].video_version = 'long'"
            :class="platformMeta[pid]?.video_version === 'long'
              ? 'bg-white/90 text-gray-900 font-semibold'
              : 'text-white/60 hover:text-white'"
            class="px-3 py-1 rounded-full transition-all">
            💻 Long
          </button>
        </div>
```

(Style uses `bg-black/20` because most platform card backgrounds are dark — the toggle reads as an overlay pill on top.)

- [ ] **Step 2: Defensive init in `loadPlatformMeta`**

Find `loadPlatformMeta(jobId)` in Alpine methods. Inside the defensive-init loop for the 8 platform keys (from previous plan), each platform object should have `video_version` defaulted if absent. Add after the existing loop that ensures each platform key has `{title:''}` fallback:

Current defensive block:
```js
    for (const p of ['youtube','tiktok','instagram','facebook','threads','x','pinterest','reddit']) {
      if (!pm[p]) pm[p] = { title: '' }
    }
```

Append to the loop body (inside the same `for` iteration):
```js
    const DEFAULT_VERSION = {
      youtube: 'long', x: 'long', pinterest: 'long', linkedin: 'long', reddit: 'long',
      tiktok: 'short', instagram: 'short', facebook: 'short', threads: 'short',
    }
    for (const p of ['youtube','tiktok','instagram','facebook','threads','x','pinterest','reddit']) {
      if (!pm[p]) pm[p] = { title: '' }
      if (!pm[p].video_version) pm[p].video_version = DEFAULT_VERSION[p] || 'long'
    }
```

- [ ] **Step 3: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('toggle_short:', '📱 Short' in s); print('toggle_long:', '💻 Long' in s); print('default_version:', 'DEFAULT_VERSION' in s); print('version_update:', \"video_version = 'short'\" in s)"
```
Expected: all 4 True.

- [ ] **Step 4: Commit**

```bash
git add web/static/index.html
git commit -m "feat: 📱 Short / 💻 Long toggle per platform card in upload preview"
```

---

## Task 7: E2E validation (full dual-version pipeline)

**Files:**
- None modified — full pipeline run.

- [ ] **Step 1: Trigger a fresh job (dry_run=true so no upload fires)**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
python -X utf8 -c "
import urllib.request, json
body = json.dumps({
    'date': '2026-04-17',
    'topic': 'AI news',
    'lang': 'zh-TW',
    'platforms': ['youtube','tiktok'],
    'dry_run': True,
}).encode()
req = urllib.request.Request('http://localhost:8000/api/jobs/trigger',
    data=body, method='POST', headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req, timeout=30) as r:
    print(json.loads(r.read()))
"
```
Note the returned `job_id` — call it `$JID` for the next steps.

- [ ] **Step 2: Wait for pipeline to reach script_review**

```bash
JID=75  # replace with actual
for i in $(seq 1 60); do
  s=$(curl -s --max-time 5 "http://localhost:8000/api/jobs/$JID" | python -X utf8 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('step_news'),'/',d.get('step_screenshot'))" 2>/dev/null)
  echo "t+${i}x5s news/screenshot = $s"
  if [[ "$s" == *"review"* ]] || [[ "$s" == *"failed"* ]]; then break; fi
  sleep 5
done
```

If backend Claude proxy times out occasionally (as happened earlier), re-trigger.

- [ ] **Step 3: Verify news.json has both script versions**

```bash
JID=75
python -X utf8 -c "
import json
d = json.load(open(f'pipeline/2026-04-17/job_{$JID}/news.json', encoding='utf-8'))
for i, it in enumerate(d.get('items', []), 1):
    print(f'=== Item #{i} ===')
    print(f'  script_short ({len(it.get(\"script_short\",\"\"))} chars): {it.get(\"script_short\",\"\")[:60]}')
    print(f'  script_long  ({len(it.get(\"script_long\",\"\"))} chars): {it.get(\"script_long\",\"\")[:60]}')
    print(f'  legacy script ({len(it.get(\"script\",\"\"))} chars): {it.get(\"script\",\"\")[:60]}')
"
```
Expected:
- Every item has `script_short` (30-50 chars), `script_long` (60-100 chars), and legacy `script` (= script_long).

- [ ] **Step 4: Continue pipeline manually (simulate script_review confirm)**

In the UI, click "確認腳本" to advance past the pause. Or use the API directly:

```bash
JID=75
curl -s --max-time 5 -X POST "http://localhost:8000/api/jobs/$JID/confirm_script" \
  -H "Content-Type: application/json" \
  -d "$(python -X utf8 -c "
import json
d = json.load(open(f'pipeline/2026-04-17/job_{$JID}/news.json', encoding='utf-8'))
print(json.dumps({'items': d['items']}))
")"
```

Wait for pipeline to reach screenshot_review. Click "確認截圖" similarly to continue audio+video.

- [ ] **Step 5: Verify both versions rendered**

```bash
JID=75
ls -la pipeline/2026-04-17/job_$JID/short/audio/ pipeline/2026-04-17/job_$JID/short/output.mp4 2>/dev/null
echo "---"
ls -la pipeline/2026-04-17/job_$JID/long/audio/ pipeline/2026-04-17/job_$JID/long/output.mp4 2>/dev/null
```
Expected:
- `short/audio/audio_01.mp3` + `short/output.mp4` both exist
- `long/audio/audio_01.mp3` + `long/output.mp4` both exist

- [ ] **Step 6: Verify platform_meta has `video_version` per platform**

```bash
curl -s --max-time 5 http://localhost:8000/api/jobs/$JID/platform_meta | python -X utf8 -c "
import sys, json
d = json.loads(sys.stdin.read())
for p in ['youtube','tiktok','instagram','facebook','threads','x','pinterest','reddit']:
    v = d.get(p, {}).get('video_version')
    print(f'  {p:<12} → {v}')
"
```
Expected matches the default mapping (youtube/x/pinterest/reddit=long; tiktok/instagram/facebook/threads=short).

- [ ] **Step 7: Test UI toggle (manual)**

Open `http://localhost:8000/ui` → navigate to job 75 → click "🎬 前往上傳預覽" → each platform card shows 📱 Short / 💻 Long toggle with correct default selected. Click to flip (e.g., flip TikTok to Long); click "💾 儲存草稿"; refresh page; toggle state persists.

- [ ] **Step 8: Commit (empty E2E marker)**

```bash
git commit --allow-empty -m "test: dual-version (Short + Long) pipeline E2E verified

Verified:
✓ Claude produces script_short + script_long per item
✓ audio_generator + remotion_renderer run twice (once per version)
✓ pipeline/.../{short,long}/{audio,output.mp4} created
✓ platform_meta seeds video_version per platform with correct defaults
✓ UI toggle updates platformMeta and persists via PUT"
```

- [ ] **Step 9: Clean up test job**

```bash
curl -s -X POST http://localhost:8000/api/jobs/$JID/cancel 2>/dev/null
```

---

## Self-Review

**1. Spec coverage:**
- Both scripts (Short + Long) generated by Claude → Task 1 ✅
- Independent rewrites (not truncation) → Task 1 prompts explicitly require this ✅
- Legacy `script` field for backward compat → Task 1 keeps `script` = `script_long` ✅
- Pipeline scripts accept `--version` → Task 2 ✅
- Per-version output directories `pipeline/.../{short,long}/*` → Task 2 ✅
- job_runner detects dual-version and runs both → Task 3 ✅
- Legacy jobs still work (single render) → Task 3 `_detect_versions` returns `[None]` ✅
- platform_meta has `video_version` per platform → Task 4 ✅
- Default mapping (YT/X/Pinterest/LinkedIn/Reddit=long; TT/IG/FB/Threads=short) → Task 4 + Task 6 defensive init ✅
- publisher uses correct video per group → Task 5 ✅
- UI per-platform toggle → Task 6 ✅
- E2E verification → Task 7 ✅

**2. Placeholder scan:**
- Task 7 uses `$JID` as a shell placeholder; it's explicitly called out that the real number replaces it
- No TBD/TODO/unfilled sections

**3. Type consistency:**
- `video_version: "short" | "long"` — same string values across Task 1 (script_short/script_long in prompt), Task 2 (CLI arg choices), Task 3 (`_detect_versions` returns ["short","long"]), Task 4 (seed values), Task 5 (version_key grouping), Task 6 (button @click values + defensive init) ✅
- `script_short` / `script_long` key names consistent across Task 1 (prompt return) + Task 2 (read in audio_generator + remotion_renderer) + Task 3 (detect logic) ✅
- `pipeline/.../{version}/` directory structure consistent: Task 2 (writers), Task 5 (reader), Task 7 (validation) ✅

**4. Scope check:** Dual-version pipeline is one subsystem touching Claude, audio, video, publisher, and UI. 7 tasks, ~8-12 commits expected. Fits as one plan.
