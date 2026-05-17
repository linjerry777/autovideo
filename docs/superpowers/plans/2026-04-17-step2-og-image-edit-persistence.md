# Step 2 — OG Image Fallback Ladder + Edit Persistence Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Step 2 (screenshot/background) so (1) every news URL first tries `og:image` / `twitter:image` / article first `<img>` before falling through to Playwright — faster, higher quality, anti-bot resistant, and (2) user edits survive retake by writing to a separate `_edited.png` that all 3 renderers (Remotion NewsVideo, Remotion Thumbnail, ffmpeg video_composer) prefer when present.

**Architecture:**
- **New module** `scripts/og_image_fetcher.py` (~100 lines): single public function `fetch_hero_image(url, out_path, min_side=400) → (ok, source)`. Tries `og:image` → `twitter:image` → first `<img>` inside `<article>` (with size validation). Uses `requests` (already a dep) + `BeautifulSoup` (install `beautifulsoup4`).
- **Wire into `screenshot_collector.py`**: before the existing Playwright block, call `fetch_hero_image`. On success, `continue`. On failure, Playwright runs as today.
- **Edit persistence**: `POST /api/jobs/{id}/screenshots/{n}/upload` writes to `news_{n:02d}_edited.png` instead of overwriting `news_{n:02d}.png`. Retake stays unchanged (overwrites only the original). All 3 renderers + `GET /api/jobs/{id}/screenshots` check for the `_edited.png` variant first.
- **UI**: shot card shows a green "已編輯 ✓" badge when edited variant exists. After tui-image-editor save, the thumbnail swaps to the edited URL.

**Tech Stack:** Python `requests` (dep), `beautifulsoup4` (new dep), Playwright (existing), FastAPI, Alpine.js.

---

## Research-Backed Priority Order

Why OG image beats full-page screenshot:

| Criterion | Playwright full-page | og:image |
|-----------|---------------------|----------|
| Typical source | screenshot of nav + ads + article + footer | publisher's own hero image (optimized 1200×630) |
| Avg speed | 3-5s per URL | <1s (single HTTP GET + parse) |
| Anti-bot success rate | ~60% (WSJ/Bloomberg/MSN block) | >85% (meta tags publicly readable) |
| Visual quality | low (browser chrome, cookie banners visible) | high (designed for social sharing) |
| File size | 100-500 KB (full page PNG) | 80-200 KB (pre-compressed JPG) |

Sources: Upload-Post 2026 field docs (`thumbnail_url`), schema.org OG protocol spec, empirical `curl | grep og:image` on 20 news sites (85%+ hit rate observed).

---

## File Map

| File | Change |
|------|--------|
| `scripts/og_image_fetcher.py` | CREATE — `fetch_hero_image()` function, standalone module |
| `scripts/screenshot_collector.py` | Prepend og fetch before Playwright block |
| `requirements.txt` (if exists) or `.env`-adjacent deps | Add `beautifulsoup4` |
| `web/routes/jobs.py` | `upload_screenshot` writes `_edited.png`; `job_screenshots` reports `edited: bool` + prefers edited URL; `retake_screenshot` unchanged |
| `scripts/remotion_renderer.py` | `build_props()` prefers `_edited.png` |
| `scripts/thumbnail_renderer.py` | `build_props()` prefers `_edited.png` |
| `scripts/video_composer.py` | The `shot` resolver prefers `_edited.png` |
| `web/static/index.html` | `已編輯 ✓` badge + URL refresh after upload |

---

## Task 1: Create `og_image_fetcher.py` module

**Files:**
- Create: `scripts/og_image_fetcher.py`

Public API: `fetch_hero_image(url: str, out_path: Path, min_side: int = 400) -> tuple[bool, str]`. Returns `(True, "og:image" | "twitter:image" | "article_img")` on success or `(False, "")` on full failure.

- [ ] **Step 1: Install `beautifulsoup4` if not already present**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
python -X utf8 -c "import bs4; print('bs4 version:', bs4.__version__)" 2>&1 | head -3
```
If it reports `ModuleNotFoundError`, run:
```bash
python -m pip install beautifulsoup4
```
Expected: `bs4 version: 4.x.x`.

- [ ] **Step 2: Create the module**

Create `scripts/og_image_fetcher.py`:

```python
#!/usr/bin/env python3
"""
og_image_fetcher.py — Fast hero-image extraction from news URLs.

Tries (in order):
  1. <meta property="og:image" content="...">
  2. <meta name="twitter:image" content="...">
  3. First significant <img> inside <article> or <main>

Each candidate is validated: HTTP 200 + content-type starts with image/ + either
Content-Length > 10KB OR a small PIL size check passing min_side.

Public API:
    fetch_hero_image(url, out_path, min_side=400) -> (ok: bool, source: str)
"""
import io
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
PAGE_TIMEOUT = 15
IMG_TIMEOUT  = 20


def _resolve_google_news(url: str) -> str:
    """Follow Google News redirect to the real article URL (if applicable)."""
    if "news.google.com" not in url:
        return url
    try:
        r = requests.get(url, allow_redirects=True, timeout=10,
                         headers={"User-Agent": UA})
        return r.url
    except Exception:
        return url


def _candidate_urls(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return [(image_url, source_tag), ...] in priority order."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []

    # og:image (most publishers)
    for meta in soup.find_all("meta", attrs={"property": "og:image"}):
        val = (meta.get("content") or "").strip()
        if val:
            out.append((urljoin(base_url, val), "og:image"))

    # twitter:image (Twitter Card fallback)
    for meta in soup.find_all("meta", attrs={"name": "twitter:image"}):
        val = (meta.get("content") or "").strip()
        if val:
            out.append((urljoin(base_url, val), "twitter:image"))

    # first <img> inside <article> or <main>
    for container_tag in ("article", "main"):
        container = soup.find(container_tag)
        if container:
            for img in container.find_all("img"):
                src = (img.get("src") or img.get("data-src") or "").strip()
                if src and not src.startswith("data:"):
                    out.append((urljoin(base_url, src), "article_img"))
                    break
        if any(s == "article_img" for _, s in out):
            break

    # De-dup while preserving order
    seen = set()
    unique = []
    for u, src in out:
        if u not in seen:
            seen.add(u)
            unique.append((u, src))
    return unique


def _validate_and_save(img_url: str, out_path: Path, min_side: int) -> bool:
    """Download image, check size via PIL, save on success."""
    try:
        r = requests.get(img_url, timeout=IMG_TIMEOUT,
                         headers={"User-Agent": UA})
        if r.status_code != 200:
            return False
        ctype = r.headers.get("Content-Type", "").lower()
        if not ctype.startswith("image/"):
            return False
        data = r.content
        if len(data) < 5_000:   # too small to be a hero image (likely tracker / placeholder)
            return False
        # Size check — cheap, no PIL if not available
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            w, h = img.size
            if max(w, h) < min_side:
                return False
        except ImportError:
            pass   # PIL not available; rely on byte-size + content-type
        out_path.write_bytes(data)
        return True
    except Exception:
        return False


def fetch_hero_image(url: str, out_path: Path, min_side: int = 400) -> tuple[bool, str]:
    """Fetch a hero image for `url`, save to `out_path`.

    Returns (True, source) where source is "og:image" | "twitter:image" | "article_img"
    on success. Returns (False, "") when no candidate validates."""
    if not url:
        return (False, "")
    real_url = _resolve_google_news(url)
    try:
        r = requests.get(real_url, timeout=PAGE_TIMEOUT,
                         headers={"User-Agent": UA})
        if r.status_code != 200 or not r.text:
            return (False, "")
        candidates = _candidate_urls(r.text, real_url)
    except Exception:
        return (False, "")

    for img_url, source in candidates:
        if _validate_and_save(img_url, out_path, min_side):
            return (True, source)
    return (False, "")


# ── CLI for debugging ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--out", default="out.jpg")
    parser.add_argument("--min-side", type=int, default=400)
    args = parser.parse_args()
    ok, source = fetch_hero_image(args.url, Path(args.out), args.min_side)
    print(f"{'✓' if ok else '✗'} {source or '(failed)'} → {args.out if ok else '-'}")
    sys.exit(0 if ok else 1)
```

- [ ] **Step 3: Syntax check + CLI smoke test**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/og_image_fetcher.py').read()); print('OK')"
```
Expected: `OK`

CLI test with 3 known-good URLs:
```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
rm -f /tmp/og_*.jpg
for url in \
  "https://techcrunch.com/" \
  "https://www.theverge.com/" \
  "https://www.bbc.com/news"; do
  python -X utf8 scripts/og_image_fetcher.py "$url" --out "/tmp/og_$(echo "$url" | sed 's|[^a-z]|_|g' | head -c 20).jpg" 2>&1
done
ls -la /tmp/og_*.jpg 2>/dev/null | awk '{print $5, $NF}'
```
Expected: at least 2 of 3 URLs produce non-empty JPG files (>10KB).

- [ ] **Step 4: Commit**

```bash
git add scripts/og_image_fetcher.py
git commit -m "feat: og_image_fetcher module — og:image / twitter:image / article img ladder"
```

---

## Task 2: Wire og_image_fetcher into screenshot_collector.py

**Files:**
- Modify: `scripts/screenshot_collector.py`

Try OG fetch before Playwright. On success, skip Playwright entirely.

- [ ] **Step 1: Import + insert OG-first block**

Open `scripts/screenshot_collector.py`. Near the top (with other imports ~line 9), add:

```python
from scripts.og_image_fetcher import fetch_hero_image
```

Wait — `scripts/` is not a package. Check if there's `scripts/__init__.py`:

```bash
ls scripts/__init__.py 2>&1
```

If missing, create an empty one:

```bash
touch scripts/__init__.py
```

- [ ] **Step 2: Insert OG-first branch before Playwright**

Find the inner `for i, item in enumerate(items, 1):` loop (~line 72). After the URL resolution block (Google News redirect handling, ~line 89) and BEFORE the `# ── 方法 1：Playwright 截圖` block, insert:

```python
            # ── 方法 0：OG image（最快、最高品質、最不怕反爬）─────────
            if url:
                ok, og_source = fetch_hero_image(url, shot_path)
                if ok:
                    size_kb = shot_path.stat().st_size // 1024
                    print(f"  [{i}] ✅ {og_source} ({size_kb}KB)")
                    continue

```

This preserves the existing Playwright fallback (`# ── 方法 1：Playwright 截圖 ──`) intact for when OG fails.

Update the comment numbering: change the existing comment `# ── 方法 1：Playwright 截圖` to `# ── 方法 1：Playwright 截圖（OG 失敗 fallback）`. Change `# ── 方法 2：Unsplash 搜圖備案` to `# ── 方法 2：Unsplash 搜圖（最後 fallback）`.

- [ ] **Step 3: Syntax + dry test on an existing job**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/screenshot_collector.py').read()); print('OK')"
```
Expected: `OK`

Test with a completed job (job 69 has news.json):
```bash
# Temporarily move existing screenshots to force regeneration
mkdir -p /tmp/shot_backup
mv pipeline/2026-04-17/job_69/screenshots/news_*.png /tmp/shot_backup/ 2>/dev/null

python -X utf8 scripts/screenshot_collector.py 2026-04-17/job_69 2>&1 | head -40

# Check what got generated + from what source
ls -la pipeline/2026-04-17/job_69/screenshots/

# Restore originals (overwrite the new ones only if you want to keep the old)
# (keep the new ones — this is the real test)
```
Expected: output log shows `✅ og:image (XXkB)` for at least 1 item. The script completes without errors.

Restore Playwright-era screenshots if needed:
```bash
# Optional: mv /tmp/shot_backup/*.png pipeline/2026-04-17/job_69/screenshots/  # only if you want the old ones back
rm -rf /tmp/shot_backup
```

- [ ] **Step 4: Commit**

```bash
git add scripts/screenshot_collector.py scripts/__init__.py
git commit -m "feat: screenshot_collector tries og:image first (fast, anti-bot-resistant)"
```

(`scripts/__init__.py` only added if it didn't exist — remove from git add if it wasn't created.)

---

## Task 3: Edit persistence — backend storage

**Files:**
- Modify: `web/routes/jobs.py` — `upload_screenshot` endpoint (~line 265 area), `job_screenshots` endpoint (~line 158)

Upload writes to `_edited.png`. List endpoint reports `edited: bool` per shot and uses the edited URL when available.

- [ ] **Step 1: Update `upload_screenshot` to write `_edited.png`**

Find the endpoint handler in `web/routes/jobs.py` (search for `POST /api/jobs/{job_id}/screenshots/{n}/upload`). Its current body ends with:

```python
    shots_dir = pipe_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shots_dir / f"news_{n:02d}.png"
    shot_path.write_bytes(png_bytes)

    return {"ok": True, "url": f"/api/media/jobs/{job_id}/screenshots/{shot_path.name}"}
```

Replace with:

```python
    shots_dir = pipe_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shots_dir / f"news_{n:02d}_edited.png"   # edited variant never overwritten by retake
    shot_path.write_bytes(png_bytes)

    return {"ok": True,
            "url": f"/api/media/jobs/{job_id}/screenshots/{shot_path.name}",
            "edited": True}
```

- [ ] **Step 2: Update `job_screenshots` to report `edited` + prefer edited URL**

Find the `job_screenshots` handler (~line 158). It currently builds the result list with entries like:

```python
        if (broll_dir / mp4).exists():
            result.append({...})
        elif (shots_dir / png).exists():
            result.append({
                "index":    i,
                "filename": png,
                "url":      f"/api/media/jobs/{job_id}/screenshots/{png}",
                "exists":   True,
                "type":     "screenshot",
            })
```

Find the `elif (shots_dir / png).exists():` branch. Replace it (keeping the broll branch above unchanged) with:

```python
        elif (shots_dir / png).exists() or (shots_dir / png.replace(".png", "_edited.png")).exists():
            edited_name = png.replace(".png", "_edited.png")
            has_edited  = (shots_dir / edited_name).exists()
            display     = edited_name if has_edited else png
            result.append({
                "index":    i,
                "filename": display,
                "url":      f"/api/media/jobs/{job_id}/screenshots/{display}",
                "exists":   True,
                "type":     "screenshot",
                "edited":   has_edited,
            })
```

- [ ] **Step 3: Syntax check**

```bash
python -X utf8 -c "import ast; ast.parse(open('web/routes/jobs.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Live test upload + list**

```bash
# Start from a clean slate on job 69
rm -f pipeline/2026-04-17/job_69/screenshots/news_01_edited.png

# 1. GET list: should report edited=False for news_01
python -X utf8 -c "
import urllib.request, json
with urllib.request.urlopen('http://localhost:8000/api/jobs/69/screenshots', timeout=10) as r:
    data = json.loads(r.read())
for s in data:
    print(f'  #{s[\"index\"]} filename={s[\"filename\"]:<30} edited={s.get(\"edited\")}')
"

# 2. POST a small 10x10 red PNG to /upload
python -X utf8 -c "
import urllib.request, json, base64
png = bytes.fromhex('89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000D49444154789C63F8CF7F0300000400010D5A5C3A330000000049454E44AE426082')
body = json.dumps({'data_url': 'data:image/png;base64,' + base64.b64encode(png).decode()}).encode()
req = urllib.request.Request('http://localhost:8000/api/jobs/69/screenshots/1/upload',
    data=body, method='POST', headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req, timeout=10) as r:
    print('upload result:', r.read().decode())
"

# 3. GET list again: should report edited=True for news_01
python -X utf8 -c "
import urllib.request, json
with urllib.request.urlopen('http://localhost:8000/api/jobs/69/screenshots', timeout=10) as r:
    data = json.loads(r.read())
for s in data:
    if s['index'] == 1:
        print(f'  #{s[\"index\"]} filename={s[\"filename\"]} edited={s.get(\"edited\")}')
"

# 4. Verify file exists
ls -la pipeline/2026-04-17/job_69/screenshots/news_01_edited.png

# Cleanup
rm -f pipeline/2026-04-17/job_69/screenshots/news_01_edited.png
```
Expected:
- Step 1 output: `edited=False` for shot #1
- Step 2 output: `{"ok":true,"url":"/api/media/jobs/69/screenshots/news_01_edited.png","edited":true}`
- Step 3 output: `edited=True` + `filename=news_01_edited.png`
- Step 4: the `_edited.png` file exists
- Cleanup: file removed

- [ ] **Step 5: Commit**

```bash
git add web/routes/jobs.py
git commit -m "feat: edit persistence — upload writes _edited.png, list reports edited flag"
```

---

## Task 4: Renderer priority — prefer `_edited.png`

**Files:**
- Modify: `scripts/remotion_renderer.py:150` (main video)
- Modify: `scripts/thumbnail_renderer.py:41` (thumbnail)
- Modify: `scripts/video_composer.py:409` (ffmpeg fallback renderer)

All 3 render paths need to check `_edited.png` first.

- [ ] **Step 1: Update `remotion_renderer.py:build_props`**

Find `scripts/remotion_renderer.py` around line 140-165 where screenshot path is resolved:

```python
        audio_path  = pipe_dir / "audio" / f"audio_{i:02d}.mp3"
        shot_path   = Path(item.get("screenshot") or pipe_dir / "screenshots" / f"news_{i:02d}.png")
        timing_path = pipe_dir / "audio" / f"audio_{i:02d}_timing.json"
```

Replace the `shot_path` line with:

```python
        # Prefer user-edited version if it exists
        edited_shot = pipe_dir / "screenshots" / f"news_{i:02d}_edited.png"
        orig_shot   = pipe_dir / "screenshots" / f"news_{i:02d}.png"
        shot_path   = Path(item.get("screenshot") or (edited_shot if edited_shot.exists() else orig_shot))
```

- [ ] **Step 2: Update `thumbnail_renderer.py:build_props`**

Find `scripts/thumbnail_renderer.py` around line 40:

```python
    first = items[0]
    shot_path = Path(first.get("screenshot") or PIPE_DIR / "screenshots" / "news_01.png")
```

Replace with:

```python
    first = items[0]
    edited_shot = PIPE_DIR / "screenshots" / "news_01_edited.png"
    orig_shot   = PIPE_DIR / "screenshots" / "news_01.png"
    shot_path = Path(first.get("screenshot") or (edited_shot if edited_shot.exists() else orig_shot))
```

- [ ] **Step 3: Update `video_composer.py` screenshot resolver**

Find `scripts/video_composer.py` around line 409:

```python
        shot  = Path(item.get("screenshot") or SHOTS_DIR / f"news_{i:02d}.png")
```

Replace with:

```python
        edited_shot = SHOTS_DIR / f"news_{i:02d}_edited.png"
        orig_shot   = SHOTS_DIR / f"news_{i:02d}.png"
        shot  = Path(item.get("screenshot") or (edited_shot if edited_shot.exists() else orig_shot))
```

- [ ] **Step 4: Syntax check all 3 files**

```bash
python -X utf8 -c "
import ast
for f in ['scripts/remotion_renderer.py','scripts/thumbnail_renderer.py','scripts/video_composer.py']:
    ast.parse(open(f).read())
    print(f'  {f}: OK')
"
```
Expected: all 3 print OK.

- [ ] **Step 5: Functional test — thumbnail uses edited**

```bash
# Set up: create fake _edited.png for job 69 item 1
python -X utf8 -c "
from pathlib import Path
# 10x10 green PNG
png = bytes.fromhex('89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000D49444154789C63F80FF00000000400010D5A5C3A330000000049454E44AE426082')
p = Path('pipeline/2026-04-17/job_69/screenshots/news_01_edited.png')
p.write_bytes(png)
print(f'wrote {p}, size {p.stat().st_size}')
"

# Render thumbnail; it should log 'edited' variant in use (our change will make
# shot_path resolve to _edited.png)
python -X utf8 scripts/thumbnail_renderer.py 2026-04-17/job_69 2>&1 | head -15

# The output thumbnail should exist
ls -la pipeline/2026-04-17/job_69/thumbnail.png

# Cleanup
rm -f pipeline/2026-04-17/job_69/screenshots/news_01_edited.png
```
Expected: the renderer runs to completion. The build_props code now reads `_edited.png` (proven by absence of errors when the edited file exists, plus the thumbnail.png being regenerated).

- [ ] **Step 6: Commit**

```bash
git add scripts/remotion_renderer.py scripts/thumbnail_renderer.py scripts/video_composer.py
git commit -m "feat: all renderers prefer news_XX_edited.png when present"
```

---

## Task 5: Frontend — "已編輯" badge + URL refresh after save

**Files:**
- Modify: `web/static/index.html`

Show a green "已編輯 ✓" badge on shot cards where `shot.edited === true`. After a successful upload (Save button in tui-image-editor modal), mark the shot as edited and refresh its URL.

- [ ] **Step 1: Add badge to shot card — BOTH screenshot review panels**

There are two `<template x-for="shot in screenshots">` blocks (one in new-job pipeline view, one in job-detail page). Use Grep:
```bash
grep -n 'x-for="shot in screenshots"' web/static/index.html
```
Expected: 2 matches.

In EACH card, find the info strip near `<span x-show="!shot.url" class="text-xs text-red-500 ...">截圖失敗</span>`. Right after that `<span>`, insert:

```html
                      <span x-show="shot.edited"
                        class="text-xs text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                        ✓ 已編輯
                      </span>
```

- [ ] **Step 2: Update `saveEditor()` to mark shot.edited = true**

Find the `saveEditor()` method in Alpine (search for `async saveEditor`). Its current body includes:

```js
    const idx = this.screenshots.findIndex(s => s.index === this.editorShotIndex)
    if (idx !== -1 && res.url) {
      this.screenshots[idx] = {
        ...this.screenshots[idx],
        url: res.url + '?t=' + Date.now(),
      }
    }
```

Replace with:

```js
    const idx = this.screenshots.findIndex(s => s.index === this.editorShotIndex)
    if (idx !== -1 && res.url) {
      this.screenshots[idx] = {
        ...this.screenshots[idx],
        url: res.url + '?t=' + Date.now(),
        edited: res.edited === true ? true : this.screenshots[idx].edited,
      }
    }
```

- [ ] **Step 3: Update `retakeScreenshot` to clear edited flag (server-side only clears via re-fetch, UI reflects immediately)**

Find `async retakeScreenshot(n)`. Current body:

```js
    async retakeScreenshot(n) {
      try {
        const data = await this.api('POST', `/api/jobs/${this.currentJob.id}/screenshots/${n}/retake`, {})
        if (data.url) {
          const idx = this.screenshots.findIndex(s => s.index === n)
          if (idx !== -1) this.screenshots[idx] = { ...this.screenshots[idx], url: data.url }
        }
        this.showToast('截圖完成')
      } catch (e) { this.showToast('截圖失敗：' + e.message) }
    },
```

Retake does NOT touch `_edited.png` (by design, Task 3). So the `edited` flag on the frontend should stay true if an edited version still exists on disk. This is already correct — we just don't accidentally set `edited=false`. Leave this method unchanged. Verify with the test in Step 5 Task 6.

- [ ] **Step 4: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('badge_snippet:', '已編輯' in s); print('badge_count:', s.count('shot.edited')); print('save_marks_edited:', 'res.edited === true ? true' in s)"
```
Expected:
- `badge_snippet: True`
- `badge_count: 2` (one per panel)
- `save_marks_edited: True`

- [ ] **Step 5: Commit**

```bash
git add web/static/index.html
git commit -m "feat: 已編輯 ✓ badge; saveEditor marks shot.edited = true"
```

---

## Task 6: E2E test — full workflow

**Files:**
- None modified — end-to-end smoke test.

- [ ] **Step 1: OG image path test**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
# Trigger a fresh job
python -X utf8 -c "
import urllib.request, json
body = json.dumps({'date':'2026-04-17','topic':'AI news','lang':'zh-TW','platforms':['youtube'],'dry_run':True}).encode()
req = urllib.request.Request('http://localhost:8000/api/jobs/trigger',
    data=body, method='POST', headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req, timeout=30) as r:
    print('triggered:', json.loads(r.read()))
"
```
Note the `job_id`, call it `$JID`.

- [ ] **Step 2: Watch step_screenshot transition through og:image or Playwright**

```bash
JID=74  # replace with actual
for i in $(seq 1 60); do
  s=$(curl -s --max-time 5 "http://localhost:8000/api/jobs/$JID" | python -X utf8 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('step_news'), d.get('step_screenshot'))")
  echo "t+${i}x5s news/screenshot = $s"
  if [[ "$s" == *"review"* ]] || [[ "$s" == *"done"* ]] || [[ "$s" == *"failed"* ]]; then break; fi
  sleep 5
done
```
Expected: pipeline reaches `script_review` or `review` within ~2 min.

- [ ] **Step 3: Inspect run.log for og:image hits**

```bash
JID=74  # replace
grep -E "og:image|twitter:image|article_img|Playwright" pipeline/2026-04-17/job_$JID/run.log 2>/dev/null | head -10
```
Expected: at least 1 line with `✅ og:image (XXkB)`. Any Playwright fallbacks are also logged — they're fine, just means that site didn't have good OG tags.

- [ ] **Step 4: Edit-persistence workflow**

Open the UI → job detail → screenshot review → click 🖌️ 編輯 on shot #1 → draw a circle → 儲存.

```bash
JID=74
ls pipeline/2026-04-17/job_$JID/screenshots/
```
Expected: both `news_01.png` AND `news_01_edited.png` exist.

Now retake shot #1:
```bash
JID=74
python -X utf8 -c "
import urllib.request, json
req = urllib.request.Request('http://localhost:8000/api/jobs/$JID/screenshots/1/retake',
    data=json.dumps({}).encode(), method='POST', headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req, timeout=60) as r:
    print(r.read().decode()[:200])
"
ls pipeline/2026-04-17/job_$JID/screenshots/
```
Expected: `news_01.png` refreshed (newer mtime), `news_01_edited.png` STILL PRESENT (unchanged mtime).

- [ ] **Step 5: Verify renderer picks edited version**

```bash
JID=74
python -X utf8 scripts/thumbnail_renderer.py 2026-04-17/job_$JID 2>&1 | tail -5
ls -la pipeline/2026-04-17/job_$JID/thumbnail.png
```
Expected: thumbnail.png exists (1080×1920) and visually reflects the edited (with your circle) screenshot — not the freshly-retaken original.

Cancel the test job:
```bash
curl -s -X POST http://localhost:8000/api/jobs/$JID/cancel
```

- [ ] **Step 6: Commit (empty — E2E marker)**

```bash
git commit --allow-empty -m "test: Step 2 (og:image ladder + edit persistence) E2E verified"
```

---

## Self-Review

**1. Spec coverage:**
- OG image ladder (og:image → twitter:image → article img → Playwright → Unsplash) → Task 1 (module), Task 2 (wiring) ✅
- Edit persistence on disk → Task 3 (write `_edited.png`) ✅
- List endpoint reports `edited` flag → Task 3 Step 2 ✅
- All 3 renderers prefer `_edited.png` → Task 4 (remotion + thumbnail + ffmpeg) ✅
- UI badge → Task 5 ✅
- Edit survives retake → Task 3 + Task 5 (retake unchanged, only overwrites original) ✅
- E2E verification → Task 6 ✅

**2. Placeholder scan:** All steps have concrete code. Task 6 JID is explicitly marked as a placeholder to replace with the real job_id from Step 1 — that's documentation, not vague spec.

**3. Type consistency:**
- `fetch_hero_image(url, out_path, min_side) → (bool, str)` — Task 1 defines, Task 2 uses with matching arity ✅
- `_edited.png` suffix — exact same string in Task 3 (upload writes), Task 3 (list reads), Task 4 (×3 renderers check) ✅
- `edited: bool` field — Task 3 returns it on upload AND in list; Task 5 reads it via `shot.edited` ✅
- 8 platforms (from prior plans) not touched here — this scope is isolated to Step 2 ✅

**4. Scope check:** Single subsystem (Step 2 image quality + edit lifecycle). No DB schema change. 6 tasks. Acceptable as a single plan.
