# Upload-Post Advanced Features + Scheduled Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade our Upload-Post integration from basic title/description to 90%+ feature parity — including legally-required AIGC disclosure, scheduled publishing, YouTube SEO fields, TikTok interaction controls, X polls, Pinterest boards, and Reddit subreddits. Add a "best time to post" advisor that suggests the golden-hour for each active platform.

**Architecture:**
- **Backend**: Extend `_seed_platform_meta` in `web/routes/jobs.py` to seed compliance defaults (`is_aigc=true`, `containsSyntheticMedia=true`) and new platform-specific fields. Extend `scripts/publisher.py` to map every new field to Upload-Post's kwargs. Add a global `schedule` section to `platform_meta.json` (scheduled_date + timezone) — Upload-Post does the actual scheduling; we just pass through.
- **Frontend**: Each card gets a "進階" (Advanced) collapsible that exposes platform-specific fields. New global `<ScheduleBar>` strip above the action bar with "立刻發布 / 排程" radio + datetime picker + "🕐 建議時間" auto-fill based on 2026 golden-hour data per platform.
- **Compliance**: AIGC flags default to `true` (we generate AI content — this is non-negotiable per EU AI Act / TikTok policy); user can uncheck in the modal if editing a hand-made video.
- **No new backend scheduler**: Upload-Post has its own queue + `scheduled_date` field. We pass ISO-8601 strings; Upload-Post fires at the right moment.

**Tech Stack:** FastAPI, Alpine.js, Upload-Post SDK, `<input type="datetime-local">` (no extra libs), existing Remotion thumbnail.

---

## Research-Driven Design Decisions

| Decision | Source | Rationale |
|----------|--------|-----------|
| Default `is_aigc=true` / `containsSyntheticMedia=true` | [TikTok 2026 AI disclosure](https://www.auditsocials.com/blog/tiktok-ai-content-disclosure-rules-2026), [EU AI Act Art.50](https://virvid.ai/blog/ai-video-ad-disclosure-requirements-2026-meta-youtube-tiktok) | Non-compliance = auto-removal; EU fine up to €15M |
| Golden-hour data baked in | [Buffer 2026](https://buffer.com/resources/best-time-to-post-social-media/), [Moonb data](https://www.moonb.io/blog/best-times-to-post-video) | Avoid external API — data changes yearly, edit in one place |
| X polls as text input → parsed | [Statweestics polls 2026](https://statweestics.com/blog/x-twitter-polls-guide-2026/) | 1.5-3% engagement, 150× value of replies |
| Upload-Post handles scheduling | Upload-Post OpenAPI `scheduled_date` | Avoid reinventing a scheduler |
| Pinterest `board_id` is REQUIRED | Upload-Post docs | Must prompt user to fill; default empty = omit platform from upload |
| Reddit `subreddit` is REQUIRED | Upload-Post docs | Same as Pinterest board |

---

## File Map

| File | Change |
|------|--------|
| `web/routes/jobs.py` | Extend `_seed_platform_meta()` with compliance + platform defaults; `PLATFORMS` stays 6 |
| `scripts/publisher.py` | Map ~30 new fields to Upload-Post kwargs; handle schedule dict at the top of `publish()` |
| `web/static/index.html` | Add schedule bar; per-card advanced collapsible; X poll / Pinterest / Reddit editors; "建議時間" helper; extend modal fields |

---

## Task 1: Backend seed defaults for compliance + advanced fields

**Files:**
- Modify: `web/routes/jobs.py` — `_seed_platform_meta()` function (~line 297)

Expand the default seeding so every new job's `platform_meta.json` already has compliance flags pre-set. User can still change them in the UI.

- [ ] **Step 1: Replace `_seed_platform_meta()` body**

Find the function at `web/routes/jobs.py:297` (body ends with the `return {...}` block). Replace the `return` dict with:

```python
    return {
        "youtube": {
            "title":                 main_title,
            "description":           f"{long_desc}\n\n{hashtags}",
            "tags":                  "AI,人工智慧,科技新聞,AINews,TechNews",
            "use_auto_thumbnail":    True,
            # Compliance & SEO (new)
            "categoryId":            "22",             # People & Blogs; 25=News, 28=Science/Tech
            "defaultLanguage":       "zh-Hant",
            "defaultAudioLanguage":  "zh-Hant",
            "privacyStatus":         "public",          # public | unlisted | private
            "containsSyntheticMedia": True,             # AI-generated — required disclosure
            "selfDeclaredMadeForKids": False,           # COPPA
            "embeddable":            True,
            "publicStatsViewable":   True,
            "license":               "youtube",         # or "creativeCommon"
        },
        "tiktok": {
            "title":                 f"{main_title}\n\n{hashtags}",
            # Compliance & control (new)
            "privacy_level":         "PUBLIC_TO_EVERYONE",
            "is_aigc":               True,              # AI-generated flag (required)
            "cover_timestamp":       1000,               # ms into video for cover (default 1s)
            "disable_duet":          False,
            "disable_comment":       False,
            "disable_stitch":        False,
            "brand_content_toggle":  False,
            "brand_organic_toggle":  False,
        },
        "instagram": {
            "title":                 main_title,
            "first_comment":         hashtags,
            # Optional (new)
            "share_mode":            "REELS",            # FEED | STORY | REELS
            "share_to_feed":         True,
            "collaborators":         "",                # comma-separated usernames
            "user_tags":             "",                # @mentions
        },
        "facebook": {
            "title":                 main_title,
            "description":           f"{long_desc}\n\n{hashtags}",
            "facebook_media_type":   "REELS",            # POST | STORIES | REELS
            "video_state":           "PUBLISHED",        # PUBLISHED | DRAFT
        },
        "threads": {
            "title":                 f"{main_title[:450]}\n\n{hashtags}",
            "threads_topic_tag":     "",                # single tag, 1-50 chars
        },
        "x": {
            "title":                 f"{main_title[:240]} {hashtags}"[:280],
            # Optional poll (new)
            "poll_options":          "",                 # "opt1|opt2|opt3" (2-4 allowed)
            "poll_duration":         1440,               # minutes, default 1 day
            "reply_settings":        "everyone",         # everyone | mentioned | following
            "x_long_text_as_post":   False,
        },
        "pinterest": {
            "title":                 main_title,
            "description":           f"{long_desc}\n\n{hashtags}",
            "pinterest_board_id":    "",                # REQUIRED — user must fill
            "pinterest_link":        "",                # optional outbound URL
            "pinterest_alt_text":    main_title,
        },
        "reddit": {
            "title":                 main_title,
            "subreddit":             "",                 # REQUIRED — user must fill
            "flair_id":              "",                 # optional subreddit flair
        },
        # Global schedule (applies to all platforms unless per-platform override set)
        "_schedule": {
            "mode":                  "now",              # "now" | "scheduled"
            "scheduled_date":        "",                 # ISO-8601, empty if mode=now
            "timezone":              "Asia/Taipei",
        },
    }
```

Also update `PLATFORMS` at `web/routes/jobs.py:294` to include the new platforms:
```python
PLATFORMS = ["youtube", "tiktok", "instagram", "facebook", "threads", "x", "pinterest", "reddit"]
```

- [ ] **Step 2: Verify syntax + route**

```bash
python -c "import ast; ast.parse(open('web/routes/jobs.py').read()); print('OK')"
```
Expected: `OK`.

Live-check the seeded shape (needs backend running — will auto-reload):
```bash
curl -s --max-time 10 http://localhost:8000/api/jobs/999/platform_meta
# (should 404; if backend reloads + responds, schema is registered)

curl -s --max-time 10 http://localhost:8000/api/jobs/65/platform_meta | python -c "
import sys, json
d = json.loads(sys.stdin.read())
print('keys:', sorted(d.keys()))
print('youtube fields:', sorted(d.get('youtube',{}).keys()))
print('tiktok is_aigc:', d.get('tiktok',{}).get('is_aigc'))
print('schedule mode:', d.get('_schedule',{}).get('mode'))
"
```
Expected:
- `keys:` includes `pinterest, reddit, _schedule` plus the 6 existing
- `youtube fields:` includes `categoryId, defaultLanguage, containsSyntheticMedia, selfDeclaredMadeForKids, embeddable, license, privacyStatus, publicStatsViewable`
- `tiktok is_aigc: True`
- `schedule mode: now`

⚠️ **Important: Re-seeding vs migration**: Jobs that already have a `platform_meta.json` from the previous plan will NOT auto-upgrade to the new schema — the file exists, so `get_platform_meta` returns the old shape. This is acceptable: (a) users re-seed by deleting the file, (b) publisher.py's `.get(field, default)` handles missing new fields gracefully (see Task 2).

- [ ] **Step 3: Commit**

```bash
git add web/routes/jobs.py
git commit -m "feat: seed platform_meta with AIGC compliance + 8-platform advanced fields"
```

---

## Task 2: Publisher — map all new fields to Upload-Post kwargs

**Files:**
- Modify: `scripts/publisher.py` — the per-platform kwargs block (~lines 75-140)

Extend the existing per-platform mapping so every new field we seeded is passed through to Upload-Post. Handle `_schedule` at the top.

- [ ] **Step 1: Add schedule handling near the top of `publish()`**

After loading `pmeta` (the existing `meta_file = pipe_dir / "platform_meta.json"` block), add:

```python
    # Global schedule: if mode=scheduled, pass to Upload-Post (it handles the queue)
    schedule = pmeta.get("_schedule", {}) if pmeta else {}
    schedule_kwargs = {}
    if schedule.get("mode") == "scheduled" and schedule.get("scheduled_date"):
        schedule_kwargs["scheduled_date"] = schedule["scheduled_date"]
        if schedule.get("timezone"):
            schedule_kwargs["timezone"] = schedule["timezone"]
```

- [ ] **Step 2: Replace the per-platform kwargs block**

Find the existing per-platform mapping (starts with `# Per-platform kwargs derived from platform_meta.json`). Replace the ENTIRE block from that comment down through the `resp = client.upload_video(...)` call with:

```python
    # Per-platform kwargs derived from platform_meta.json (falls back to meta if missing)
    fallback_title = meta["title"]
    fallback_desc  = meta["description"]

    def _platform_meta(platform: str) -> dict:
        """Return platform-specific meta dict (never None)."""
        return pmeta.get(platform, {})

    kwargs = dict(async_upload=True, description=fallback_desc)
    kwargs.update(schedule_kwargs)   # scheduled_date + timezone if set

    # Per-platform titles for all platforms
    for p in ("youtube", "tiktok", "instagram", "facebook", "threads", "x", "pinterest", "reddit"):
        if p in platforms:
            title = _platform_meta(p).get("title") or fallback_title
            kwargs[f"{p}_title"] = title

    # ── YouTube
    if "youtube" in platforms:
        yt = _platform_meta("youtube")
        kwargs["youtube_description"] = yt.get("description") or fallback_desc
        if yt.get("tags"):
            kwargs["tags"] = [t.strip() for t in re.split(r"[,\uff0c\u3001\n]+", yt["tags"]) if t.strip()]
        else:
            kwargs["tags"] = ["AI", "人工智慧", "科技新聞", "AINews", "TechNews"]
        kwargs["privacyStatus"]            = yt.get("privacyStatus", "public")
        kwargs["categoryId"]               = yt.get("categoryId", "22")
        kwargs["defaultLanguage"]          = yt.get("defaultLanguage", "zh-Hant")
        kwargs["defaultAudioLanguage"]     = yt.get("defaultAudioLanguage", "zh-Hant")
        kwargs["containsSyntheticMedia"]   = yt.get("containsSyntheticMedia", True)
        kwargs["selfDeclaredMadeForKids"]  = yt.get("selfDeclaredMadeForKids", False)
        kwargs["embeddable"]               = yt.get("embeddable", True)
        kwargs["publicStatsViewable"]      = yt.get("publicStatsViewable", True)
        kwargs["license"]                  = yt.get("license", "youtube")
        thumb_path = pipe_dir / "thumbnail.png"
        if yt.get("use_auto_thumbnail", True) and thumb_path.exists():
            kwargs["thumbnail"] = str(thumb_path)

    # ── TikTok
    if "tiktok" in platforms:
        tt = _platform_meta("tiktok")
        kwargs["privacy_level"]         = tt.get("privacy_level", "PUBLIC_TO_EVERYONE")
        kwargs["is_aigc"]               = tt.get("is_aigc", True)
        kwargs["cover_timestamp"]       = int(tt.get("cover_timestamp", 1000))
        kwargs["disable_duet"]          = tt.get("disable_duet", False)
        kwargs["disable_comment"]       = tt.get("disable_comment", False)
        kwargs["disable_stitch"]        = tt.get("disable_stitch", False)
        kwargs["brand_content_toggle"]  = tt.get("brand_content_toggle", False)
        kwargs["brand_organic_toggle"]  = tt.get("brand_organic_toggle", False)

    # ── Instagram / Threads / Facebook share media_type=REELS
    if any(p in platforms for p in ("instagram", "threads", "facebook")):
        kwargs["media_type"]    = "REELS"
        kwargs["share_to_feed"] = True

    # Instagram
    if "instagram" in platforms:
        ig = _platform_meta("instagram")
        fc = ig.get("first_comment", "")
        if fc:
            kwargs["first_comment"] = fc
        if ig.get("collaborators"):
            kwargs["collaborators"] = ig["collaborators"]
        if ig.get("user_tags"):
            kwargs["user_tags"]     = ig["user_tags"]

    # Facebook
    if "facebook" in platforms:
        fb = _platform_meta("facebook")
        kwargs["facebook_description"] = fb.get("description") or fallback_desc
        kwargs["facebook_media_type"]  = fb.get("facebook_media_type", "REELS")
        kwargs["video_state"]          = fb.get("video_state", "PUBLISHED")

    # Threads
    if "threads" in platforms:
        th = _platform_meta("threads")
        if th.get("threads_topic_tag"):
            kwargs["threads_topic_tag"] = th["threads_topic_tag"][:50]

    # X (Twitter)
    if "x" in platforms:
        xp = _platform_meta("x")
        if xp.get("poll_options"):
            opts = [o.strip() for o in xp["poll_options"].split("|") if o.strip()]
            if 2 <= len(opts) <= 4:
                kwargs["poll_options"]  = opts
                kwargs["poll_duration"] = int(xp.get("poll_duration", 1440))
        kwargs["reply_settings"]     = xp.get("reply_settings", "everyone")
        kwargs["x_long_text_as_post"] = xp.get("x_long_text_as_post", False)

    # Pinterest (board_id required — drop platform if empty)
    if "pinterest" in platforms:
        pn = _platform_meta("pinterest")
        if not pn.get("pinterest_board_id"):
            print("⚠️  Pinterest 未填 board_id，跳過 Pinterest 上傳", file=sys.stderr)
            platforms = [p for p in platforms if p != "pinterest"]
        else:
            kwargs["pinterest_board_id"]  = pn["pinterest_board_id"]
            kwargs["pinterest_description"] = pn.get("description") or fallback_desc
            kwargs["pinterest_alt_text"]  = pn.get("pinterest_alt_text") or fallback_title
            if pn.get("pinterest_link"):
                kwargs["pinterest_link"] = pn["pinterest_link"]

    # Reddit (subreddit required — drop platform if empty)
    if "reddit" in platforms:
        rd = _platform_meta("reddit")
        if not rd.get("subreddit"):
            print("⚠️  Reddit 未填 subreddit，跳過 Reddit 上傳", file=sys.stderr)
            platforms = [p for p in platforms if p != "reddit"]
        else:
            kwargs["subreddit"] = rd["subreddit"]
            if rd.get("flair_id"):
                kwargs["flair_id"] = rd["flair_id"]

    if not platforms:
        print("❌ 沒有可上傳的平台（必填欄位未填）", file=sys.stderr)
        sys.exit(1)

    resp = client.upload_video(
        video_path = str(output_mp4),
        title      = fallback_title,
        user       = PROFILE,
        platforms  = platforms,
        **kwargs,
    )
```

- [ ] **Step 3: Update `argparse` choices**

Find the argparse section at the bottom of `scripts/publisher.py` (~line 130). Update `--platforms` choices:

```python
    parser.add_argument("--platforms", nargs="+",
                        default=["youtube", "instagram"],
                        choices=["youtube","instagram","tiktok","facebook",
                                 "threads","linkedin","x","pinterest","bluesky","reddit"],
                        help="目標平台（預設：youtube instagram）")
```

(`reddit` added to the choices list.)

- [ ] **Step 4: Verify**

```bash
python -c "import ast; ast.parse(open('scripts/publisher.py').read()); print('OK')"
```
Expected: `OK`.

```bash
python -c "
from pathlib import Path
import json
p = Path('pipeline/2026-04-16/job_65/platform_meta.json')
p.write_text(json.dumps({
  'youtube': {'title': 'yt', 'description': 'd', 'tags': 'a,b', 'use_auto_thumbnail': False,
              'categoryId': '25', 'defaultLanguage': 'zh-Hant', 'containsSyntheticMedia': True,
              'selfDeclaredMadeForKids': False, 'embeddable': True, 'publicStatsViewable': True,
              'license': 'youtube', 'privacyStatus': 'public'},
  'tiktok': {'title': 't', 'is_aigc': True, 'cover_timestamp': 2000, 'privacy_level': 'PUBLIC_TO_EVERYONE',
             'disable_duet': False, 'disable_comment': False, 'disable_stitch': True,
             'brand_content_toggle': False, 'brand_organic_toggle': False},
  'instagram': {'title': 'i', 'first_comment': '#a', 'collaborators': 'friend1', 'user_tags': '@me'},
  'facebook': {'title': 'f', 'description': 'd', 'facebook_media_type': 'REELS', 'video_state': 'PUBLISHED'},
  'threads': {'title': 'th', 'threads_topic_tag': 'AI'},
  'x': {'title': 'x', 'poll_options': 'Yes|No', 'poll_duration': 60, 'reply_settings': 'everyone', 'x_long_text_as_post': False},
  'pinterest': {'title': 'pn', 'description': 'd', 'pinterest_board_id': 'abc', 'pinterest_alt_text': 'alt'},
  'reddit': {'title': 'rd', 'subreddit': 'test'},
  '_schedule': {'mode': 'scheduled', 'scheduled_date': '2026-04-20T08:00:00Z', 'timezone': 'Asia/Taipei'}
}, ensure_ascii=False, indent=2), encoding='utf-8')
print('wrote', p)
"

python scripts/publisher.py 2026-04-16/job_65 --platforms youtube tiktok x pinterest reddit --dry-run
```
Expected: no exceptions. Output prints preview.

Cleanup:
```bash
rm pipeline/2026-04-16/job_65/platform_meta.json
```

- [ ] **Step 5: Commit**

```bash
git add scripts/publisher.py
git commit -m "feat: publisher maps 30+ advanced Upload-Post fields per platform + schedule"
```

---

## Task 3: Frontend — schedule bar + "best time" advisor

**Files:**
- Modify: `web/static/index.html`

Add a strip above the existing action bar on the upload preview page. Two modes: "🚀 立刻發布" (default) / "🕐 排程發布". When scheduled, show datetime picker + suggested-time chips.

- [ ] **Step 1: Add Alpine data for schedule state + golden-hour data**

Find the Alpine data block in `app()`. Add near `platformMeta`:

```js
// Schedule state (mirrors platformMeta._schedule but UI-reactive)
scheduleMode: 'now',            // 'now' | 'scheduled'
scheduledDatetime: '',          // "2026-04-20T08:00"
scheduleTimezone: 'Asia/Taipei',
```

Add as an Alpine property (sibling of `_PLATFORM_STYLE`):

```js
// Golden-hour windows per platform (local time, hour ranges)
// Data: Buffer/Moonb 2026 studies — keep edits in ONE place when data changes
_GOLDEN_HOURS: {
  youtube:   { weekday: ['14:00', '20:00'], note: '平日 14-16 / 20-23 最佳（前 2-4h 決定推送）' },
  tiktok:    { weekday: ['07:00', '20:00'], note: '晨間 6-10 / 晚間 19-23 最佳' },
  instagram: { weekday: ['12:00', '19:00'], note: '週二 13-19 / 週三 12-21 最佳' },
  facebook:  { weekday: ['13:00', '16:00'], note: '午後 13-16 最佳' },
  threads:   { weekday: ['12:00', '19:00'], note: '同 IG 節奏' },
  x:         { weekday: ['09:00', '17:00'], note: '早晨 9-10 / 下午 17-18 最佳' },
  pinterest: { weekday: ['20:00', '23:00'], note: '週末晚間最佳' },
  reddit:    { weekday: ['06:00', '09:00'], note: '清晨 6-9 EST 最活躍' },
},
```

- [ ] **Step 2: Add `suggestBestTime()` method**

In the Alpine methods section:

```js
// Find the earliest golden-hour window across currently enabled platforms
suggestBestTime() {
  if (this.uploadPlatforms.size === 0) {
    this.showToast('請先啟用至少一個平台')
    return
  }
  // Tomorrow at the earliest golden window of any enabled platform
  const windows = [...this.uploadPlatforms]
    .map(p => this._GOLDEN_HOURS[p]?.weekday?.[0])
    .filter(Boolean)
    .sort()
  const earliestHour = windows[0] || '10:00'
  const d = new Date()
  d.setDate(d.getDate() + 1)  // tomorrow
  const [hh, mm] = earliestHour.split(':')
  d.setHours(parseInt(hh), parseInt(mm), 0, 0)
  // Format for <input type=datetime-local>: YYYY-MM-DDTHH:MM
  const pad = n => String(n).padStart(2, '0')
  this.scheduledDatetime =
    `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
  this.scheduleMode = 'scheduled'
  this.syncScheduleToMeta()
  this.showToast(`已填入 ${earliestHour} — 覆蓋最多啟用平台的黃金時段`)
},

// Push UI state back into platformMeta._schedule
syncScheduleToMeta() {
  if (!this.platformMeta) return
  if (!this.platformMeta._schedule) this.platformMeta._schedule = {}
  this.platformMeta._schedule.mode           = this.scheduleMode
  this.platformMeta._schedule.scheduled_date =
    this.scheduleMode === 'scheduled' && this.scheduledDatetime
      ? new Date(this.scheduledDatetime).toISOString()
      : ''
  this.platformMeta._schedule.timezone       = this.scheduleTimezone
},
```

- [ ] **Step 3: Hook schedule load into `loadPlatformMeta`**

Find `loadPlatformMeta(jobId)`. After the defensive init loop (from Task 6 of previous plan), add:

```js
    // Restore schedule UI state from meta
    const sched = pm._schedule || {}
    this.scheduleMode       = sched.mode || 'now'
    this.scheduleTimezone   = sched.timezone || 'Asia/Taipei'
    // Convert ISO back to datetime-local format for the <input>
    if (sched.scheduled_date) {
      const d = new Date(sched.scheduled_date)
      const pad = n => String(n).padStart(2, '0')
      this.scheduledDatetime =
        `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
    } else {
      this.scheduledDatetime = ''
    }
```

Place this block INSIDE the `try` block, after `this.platformMeta = pm`.

- [ ] **Step 4: Add the schedule bar UI above the existing action bar**

Find the existing action bar (search for `儲存草稿`). Immediately BEFORE that `<div class="glass rounded-2xl p-5 flex items-center justify-between sticky bottom-4">` block, insert:

```html
<!-- Schedule bar -->
<div x-show="!platformMetaLoading && platformMeta" class="glass rounded-2xl p-5 space-y-3">
  <div class="flex items-center gap-4 flex-wrap">
    <p class="text-xs font-semibold text-gray-500">發布時機</p>
    <label class="flex items-center gap-2 text-sm cursor-pointer">
      <input type="radio" x-model="scheduleMode" value="now" @change="syncScheduleToMeta()" class="accent-green-500">
      <span>🚀 立刻發布</span>
    </label>
    <label class="flex items-center gap-2 text-sm cursor-pointer">
      <input type="radio" x-model="scheduleMode" value="scheduled" @change="syncScheduleToMeta()" class="accent-green-500">
      <span>🕐 排程發布</span>
    </label>

    <div x-show="scheduleMode === 'scheduled'" class="flex items-center gap-2 flex-wrap">
      <input type="datetime-local" x-model="scheduledDatetime" @change="syncScheduleToMeta()"
        class="bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-green-500/30">
      <select x-model="scheduleTimezone" @change="syncScheduleToMeta()"
        class="bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-sm">
        <option value="Asia/Taipei">Asia/Taipei (UTC+8)</option>
        <option value="Asia/Tokyo">Asia/Tokyo (UTC+9)</option>
        <option value="America/Los_Angeles">US/Pacific</option>
        <option value="America/New_York">US/Eastern</option>
        <option value="UTC">UTC</option>
      </select>
      <button @click="suggestBestTime()"
        class="text-xs text-orange-600 border border-orange-200 bg-orange-50 hover:bg-orange-100 rounded-lg px-3 py-1.5 font-medium">
        ✨ 建議時間
      </button>
    </div>
  </div>

  <!-- Per-platform golden-hour hints -->
  <div x-show="scheduleMode === 'scheduled'" class="flex flex-wrap gap-2 pt-2 border-t border-gray-100">
    <template x-for="pid in [...uploadPlatforms]" :key="pid">
      <span class="text-[10px] px-2 py-1 rounded-full bg-gray-100 text-gray-600"
        x-text="(_PLATFORM_STYLE[pid]?.name || pid) + ': ' + (_GOLDEN_HOURS[pid]?.note || '')"></span>
    </template>
  </div>
</div>
```

- [ ] **Step 5: Verify**

```bash
python -c "s=open('web/static/index.html',encoding='utf-8').read(); print('sched_mode:', 'scheduleMode' in s); print('golden_hours:', '_GOLDEN_HOURS' in s); print('suggest:', 'suggestBestTime' in s); print('sync:', 'syncScheduleToMeta' in s); print('datetime_input:', 'type=\"datetime-local\"' in s)"
```
Expected: all 5 True.

- [ ] **Step 6: Commit**

```bash
git add web/static/index.html
git commit -m "feat: schedule bar + golden-hour advisor for multi-platform publish"
```

---

## Task 4: Frontend — per-card advanced fields (YouTube / TikTok / Instagram)

**Files:**
- Modify: `web/static/index.html` — the edit modal (added in previous plan's Task 6)

Extend the edit modal to show platform-specific advanced fields via a collapsible "進階設定" section.

- [ ] **Step 1: Add `showAdvanced` Alpine state**

Add to the Alpine data block near `editingPlatform`:

```js
showAdvanced: false,    // toggle for modal's advanced fields section
```

Reset it when modal closes. Find the `editingPlatform = null` handlers in the modal (there are ~3 sites: backdrop click, 完成 button, 取消 button, save promise). Change each to `editingPlatform = null; showAdvanced = false`.

You can use replace-all for this pattern specifically within the upload page. Be careful: the string `editingPlatform = null` may appear in the save button's `.then(() => editingPlatform = null)` — that one should also get the reset.

Concrete: find this modal's save button (from previous plan):
```html
<button @click="savePlatformMeta().then(() => editingPlatform = null).catch(...)">
```
Change to:
```html
<button @click="savePlatformMeta().then(() => { editingPlatform = null; showAdvanced = false }).catch(err => console.error('savePlatformMeta:', err))">
```

And the 完成 / 取消 / backdrop handlers from `editingPlatform = null` to `editingPlatform = null; showAdvanced = false`.

- [ ] **Step 2: Add advanced toggle + sections to the modal**

Find the modal body (`<div class="flex-1 overflow-y-auto p-5 space-y-4" x-show="editingPlatform && platformMeta">`). Just BEFORE its closing `</div>` (the one that closes the body div, not the fields inside), add:

```html
      <!-- Advanced fields toggle -->
      <button @click="showAdvanced = !showAdvanced"
        class="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5 flex items-center gap-1">
        <span x-text="showAdvanced ? '▼' : '▶'"></span>
        <span>進階設定</span>
      </button>

      <div x-show="showAdvanced" class="space-y-3 pt-3 border-t border-gray-100">

        <!-- ═══ YouTube advanced ═══ -->
        <template x-if="editingPlatform === 'youtube'">
          <div class="space-y-3">
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="text-xs font-medium text-gray-500 block mb-1">類別</label>
                <select x-model="platformMeta.youtube.categoryId"
                  class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
                  <option value="22">人物與網誌 (22)</option>
                  <option value="25">新聞與政治 (25)</option>
                  <option value="28">科學與科技 (28)</option>
                  <option value="24">娛樂 (24)</option>
                  <option value="26">教育 (26)</option>
                  <option value="27">How-to (27)</option>
                  <option value="10">音樂 (10)</option>
                  <option value="20">遊戲 (20)</option>
                </select>
              </div>
              <div>
                <label class="text-xs font-medium text-gray-500 block mb-1">隱私</label>
                <select x-model="platformMeta.youtube.privacyStatus"
                  class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
                  <option value="public">公開</option>
                  <option value="unlisted">不公開（有連結才能看）</option>
                  <option value="private">私人</option>
                </select>
              </div>
              <div>
                <label class="text-xs font-medium text-gray-500 block mb-1">主要語言</label>
                <select x-model="platformMeta.youtube.defaultLanguage"
                  class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
                  <option value="zh-Hant">繁體中文</option>
                  <option value="zh-Hans">簡體中文</option>
                  <option value="en">English</option>
                  <option value="ja">日本語</option>
                  <option value="ko">한국어</option>
                </select>
              </div>
              <div>
                <label class="text-xs font-medium text-gray-500 block mb-1">License</label>
                <select x-model="platformMeta.youtube.license"
                  class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
                  <option value="youtube">標準 YouTube License</option>
                  <option value="creativeCommon">Creative Commons</option>
                </select>
              </div>
            </div>
            <div class="space-y-2">
              <label class="flex items-center gap-2 text-xs"><input type="checkbox" class="accent-green-500"
                  :checked="platformMeta.youtube.containsSyntheticMedia"
                  @change="platformMeta.youtube.containsSyntheticMedia = $event.target.checked">
                <span>🤖 包含 AI 生成內容（合規必填）</span>
              </label>
              <label class="flex items-center gap-2 text-xs"><input type="checkbox" class="accent-green-500"
                  :checked="platformMeta.youtube.selfDeclaredMadeForKids"
                  @change="platformMeta.youtube.selfDeclaredMadeForKids = $event.target.checked">
                <span>👶 兒童向內容（COPPA 合規）</span>
              </label>
              <label class="flex items-center gap-2 text-xs"><input type="checkbox" class="accent-green-500"
                  :checked="platformMeta.youtube.embeddable"
                  @change="platformMeta.youtube.embeddable = $event.target.checked">
                <span>允許嵌入到其他網站</span>
              </label>
              <label class="flex items-center gap-2 text-xs"><input type="checkbox" class="accent-green-500"
                  :checked="platformMeta.youtube.publicStatsViewable"
                  @change="platformMeta.youtube.publicStatsViewable = $event.target.checked">
                <span>公開觀看數與評分</span>
              </label>
            </div>
          </div>
        </template>

        <!-- ═══ TikTok advanced ═══ -->
        <template x-if="editingPlatform === 'tiktok'">
          <div class="space-y-3">
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="text-xs font-medium text-gray-500 block mb-1">隱私</label>
                <select x-model="platformMeta.tiktok.privacy_level"
                  class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
                  <option value="PUBLIC_TO_EVERYONE">公開（所有人）</option>
                  <option value="MUTUAL_FOLLOW_FRIENDS">相互追蹤好友</option>
                  <option value="SELF_ONLY">僅自己可見</option>
                </select>
              </div>
              <div>
                <label class="text-xs font-medium text-gray-500 block mb-1">封面時間點（ms）</label>
                <input type="number" min="0" step="100" x-model.number="platformMeta.tiktok.cover_timestamp"
                  class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
              </div>
            </div>
            <div class="space-y-2">
              <label class="flex items-center gap-2 text-xs"><input type="checkbox" class="accent-green-500"
                  :checked="platformMeta.tiktok.is_aigc"
                  @change="platformMeta.tiktok.is_aigc = $event.target.checked">
                <span>🤖 AI 生成聲明（TikTok 2026 合規必填）</span>
              </label>
              <label class="flex items-center gap-2 text-xs"><input type="checkbox" class="accent-green-500"
                  :checked="platformMeta.tiktok.disable_duet"
                  @change="platformMeta.tiktok.disable_duet = $event.target.checked">
                <span>禁止 Duet（合拍）</span>
              </label>
              <label class="flex items-center gap-2 text-xs"><input type="checkbox" class="accent-green-500"
                  :checked="platformMeta.tiktok.disable_stitch"
                  @change="platformMeta.tiktok.disable_stitch = $event.target.checked">
                <span>禁止 Stitch（剪接）</span>
              </label>
              <label class="flex items-center gap-2 text-xs"><input type="checkbox" class="accent-green-500"
                  :checked="platformMeta.tiktok.disable_comment"
                  @change="platformMeta.tiktok.disable_comment = $event.target.checked">
                <span>關閉留言</span>
              </label>
              <label class="flex items-center gap-2 text-xs"><input type="checkbox" class="accent-green-500"
                  :checked="platformMeta.tiktok.brand_content_toggle"
                  @change="platformMeta.tiktok.brand_content_toggle = $event.target.checked">
                <span>業配聲明（付費合作）</span>
              </label>
            </div>
          </div>
        </template>

        <!-- ═══ Instagram advanced ═══ -->
        <template x-if="editingPlatform === 'instagram'">
          <div class="space-y-3">
            <div>
              <label class="text-xs font-medium text-gray-500 block mb-1">共同製作者（逗號分隔 username）</label>
              <input type="text" x-model="platformMeta.instagram.collaborators"
                placeholder="friend_handle1, friend_handle2"
                class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
            </div>
            <div>
              <label class="text-xs font-medium text-gray-500 block mb-1">@標記使用者</label>
              <input type="text" x-model="platformMeta.instagram.user_tags"
                placeholder="@user1, @user2"
                class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
            </div>
          </div>
        </template>

      </div>
```

- [ ] **Step 3: Verify**

```bash
python -c "s=open('web/static/index.html',encoding='utf-8').read(); print('showAdvanced:', 'showAdvanced' in s); print('categoryId:', 'categoryId' in s); print('is_aigc:', 'is_aigc' in s); print('cover_timestamp:', 'cover_timestamp' in s); print('collaborators:', 'collaborators' in s); print('containsSynthetic:', 'containsSyntheticMedia' in s); print('selfDeclaredMadeForKids:', 'selfDeclaredMadeForKids' in s)"
```
Expected: all 7 True.

- [ ] **Step 4: Commit**

```bash
git add web/static/index.html
git commit -m "feat: YouTube/TikTok/Instagram advanced fields in edit modal"
```

---

## Task 5: Frontend — platform-specific UI for X / Pinterest / Reddit / Facebook / Threads

**Files:**
- Modify: `web/static/index.html`

Extend the advanced section for the remaining 5 platforms. X gets a poll editor; Pinterest gets board_id / link / alt_text; Reddit gets subreddit / flair_id; Facebook gets draft toggle; Threads gets topic_tag. Also add these 3 new platforms (pinterest, reddit) to the card grid.

- [ ] **Step 1: Update `_PLATFORM_STYLE` to include pinterest + reddit**

Find `_PLATFORM_STYLE` (from previous plan). Replace with:

```js
_PLATFORM_STYLE: {
  youtube:   { bg: 'bg-white',               text: 'text-gray-900', accent: '#FF0000', name: 'YouTube Shorts', logo: 'yt' },
  tiktok:    { bg: 'bg-black',               text: 'text-white',    accent: '#FE2C55', name: 'TikTok',         logo: 'tt' },
  instagram: { bg: 'bg-gradient-to-br from-[#833AB4] via-[#FD1D1D] to-[#FCAF45]',
               text: 'text-white',    accent: '#ffffff', name: 'Instagram Reels', logo: 'ig' },
  facebook:  { bg: 'bg-[#18191A]',           text: 'text-white',    accent: '#1877F2', name: 'Facebook Reels', logo: 'fb' },
  threads:   { bg: 'bg-black',               text: 'text-white',    accent: '#ffffff', name: 'Threads',        logo: 'th' },
  x:         { bg: 'bg-black',               text: 'text-white',    accent: '#1D9BF0', name: 'X (Twitter)',    logo: 'x'  },
  pinterest: { bg: 'bg-white',               text: 'text-gray-900', accent: '#E60023', name: 'Pinterest',      logo: 'pn' },
  reddit:    { bg: 'bg-[#FF4500]',           text: 'text-white',    accent: '#ffffff', name: 'Reddit',         logo: 'rd' },
},
```

- [ ] **Step 2: Add pinterest + reddit logos to `_platformSvg()`**

In the `_platformSvg(pid)` method, extend the `paths` object with two new entries:

```js
    pn: '<svg class="w-4 h-4" fill="#E60023" viewBox="0 0 24 24"><path d="M12.017 0C5.396 0 .029 5.367.029 11.987c0 5.079 3.158 9.417 7.618 11.162-.105-.949-.199-2.403.041-3.439.219-.937 1.406-5.957 1.406-5.957s-.359-.72-.359-1.781c0-1.663.967-2.911 2.168-2.911 1.024 0 1.518.769 1.518 1.688 0 1.029-.653 2.567-.992 3.992-.285 1.193.6 2.165 1.775 2.165 2.128 0 3.768-2.245 3.768-5.487 0-2.861-2.063-4.869-5.008-4.869-3.41 0-5.409 2.562-5.409 5.199 0 1.033.394 2.143.889 2.741.099.12.112.225.085.345-.09.375-.293 1.199-.334 1.363-.053.225-.172.271-.402.165-1.495-.69-2.433-2.878-2.433-4.646 0-3.776 2.748-7.252 7.92-7.252 4.158 0 7.392 2.967 7.392 6.923 0 4.135-2.607 7.462-6.233 7.462-1.214 0-2.357-.629-2.758-1.378l-.749 2.853c-.269 1.045-1.004 2.352-1.498 3.146 1.123.345 2.306.535 3.55.535 6.607 0 11.985-5.365 11.985-11.987C23.97 5.39 18.592.026 11.985.026L12.017 0z"/></svg>',
    rd: '<svg class="w-4 h-4" fill="#FF4500" viewBox="0 0 24 24"><path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 0 0 .029-.463.33.33 0 0 0-.464 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z"/></svg>',
```

Add them inside the existing `paths = {` object.

- [ ] **Step 3: Update the card grid x-for to iterate 8 platforms**

Find the grid template `<template x-for="pid in ['youtube','tiktok','instagram','facebook','threads','x']"`. Change the array to include the 2 new platforms:

```html
<template x-for="pid in ['youtube','tiktok','instagram','facebook','threads','x','pinterest','reddit']" :key="pid">
```

- [ ] **Step 4: Add the 5 platform-specific advanced sections**

In the advanced-fields block from Task 4 Step 2 (just after the Instagram `<template x-if>` block), add:

```html
        <!-- ═══ X (Twitter) advanced — poll editor ═══ -->
        <template x-if="editingPlatform === 'x'">
          <div class="space-y-3">
            <div>
              <label class="text-xs font-medium text-gray-500 block mb-1">
                投票選項（用 | 分隔，2-4 項）
              </label>
              <input type="text" x-model="platformMeta.x.poll_options"
                placeholder="選項A|選項B|選項C"
                class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
              <p class="text-[10px] text-gray-400 mt-1">X 投票互動率 1.5-3%，留白不啟用</p>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="text-xs font-medium text-gray-500 block mb-1">投票時長（分）</label>
                <input type="number" min="5" max="10080" x-model.number="platformMeta.x.poll_duration"
                  class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
              </div>
              <div>
                <label class="text-xs font-medium text-gray-500 block mb-1">回覆限制</label>
                <select x-model="platformMeta.x.reply_settings"
                  class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
                  <option value="everyone">所有人</option>
                  <option value="mentioned">僅提及者</option>
                  <option value="following">僅追蹤者</option>
                </select>
              </div>
            </div>
            <label class="flex items-center gap-2 text-xs">
              <input type="checkbox" class="accent-green-500"
                :checked="platformMeta.x.x_long_text_as_post"
                @change="platformMeta.x.x_long_text_as_post = $event.target.checked">
              <span>長推以「單一貼文」發布（預設關閉 = 串 Thread）</span>
            </label>
          </div>
        </template>

        <!-- ═══ Facebook advanced ═══ -->
        <template x-if="editingPlatform === 'facebook'">
          <div class="space-y-3">
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="text-xs font-medium text-gray-500 block mb-1">媒體類型</label>
                <select x-model="platformMeta.facebook.facebook_media_type"
                  class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
                  <option value="REELS">Reels</option>
                  <option value="POST">一般貼文</option>
                  <option value="STORIES">Stories</option>
                </select>
              </div>
              <div>
                <label class="text-xs font-medium text-gray-500 block mb-1">發布狀態</label>
                <select x-model="platformMeta.facebook.video_state"
                  class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
                  <option value="PUBLISHED">立即發布</option>
                  <option value="DRAFT">儲存草稿（不公開）</option>
                </select>
              </div>
            </div>
          </div>
        </template>

        <!-- ═══ Threads advanced ═══ -->
        <template x-if="editingPlatform === 'threads'">
          <div class="space-y-3">
            <div>
              <label class="text-xs font-medium text-gray-500 block mb-1">主題標籤（單一，1-50 字，不含 . &amp; 符號）</label>
              <input type="text" x-model="platformMeta.threads.threads_topic_tag"
                placeholder="AI"
                class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
            </div>
          </div>
        </template>

        <!-- ═══ Pinterest advanced — board_id REQUIRED ═══ -->
        <template x-if="editingPlatform === 'pinterest'">
          <div class="space-y-3">
            <div>
              <label class="text-xs font-medium text-gray-500 block mb-1">
                Board ID <span class="text-red-500">*必填</span>
              </label>
              <input type="text" x-model="platformMeta.pinterest.pinterest_board_id"
                placeholder="e.g. 1234567890123456789"
                class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
              <p class="text-[10px] text-gray-400 mt-1">Pinterest 規定必須指定 board — 從你的 Pinterest 網址取得</p>
            </div>
            <div>
              <label class="text-xs font-medium text-gray-500 block mb-1">導流連結（選填）</label>
              <input type="url" x-model="platformMeta.pinterest.pinterest_link"
                placeholder="https://your-site.com/article"
                class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
            </div>
            <div>
              <label class="text-xs font-medium text-gray-500 block mb-1">Alt 文字（無障礙）</label>
              <input type="text" x-model="platformMeta.pinterest.pinterest_alt_text"
                class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
            </div>
          </div>
        </template>

        <!-- ═══ Reddit advanced — subreddit REQUIRED ═══ -->
        <template x-if="editingPlatform === 'reddit'">
          <div class="space-y-3">
            <div>
              <label class="text-xs font-medium text-gray-500 block mb-1">
                Subreddit <span class="text-red-500">*必填</span>
              </label>
              <input type="text" x-model="platformMeta.reddit.subreddit"
                placeholder="r/ 後面的部分，例如 technology"
                class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
              <p class="text-[10px] text-gray-400 mt-1">必須指定發文版，且你必須符合該版規則（9:1 比例不違規）</p>
            </div>
            <div>
              <label class="text-xs font-medium text-gray-500 block mb-1">Flair ID（選填）</label>
              <input type="text" x-model="platformMeta.reddit.flair_id"
                placeholder="從該版取得"
                class="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-sm">
            </div>
          </div>
        </template>
```

- [ ] **Step 5: Update defensive init in `loadPlatformMeta`**

Find the defensive init loop (from previous plan's Task 6 polish):
```js
    for (const p of ['youtube','tiktok','instagram','facebook','threads','x']) {
      if (!pm[p]) pm[p] = { title: '' }
    }
```
Replace with:
```js
    for (const p of ['youtube','tiktok','instagram','facebook','threads','x','pinterest','reddit']) {
      if (!pm[p]) pm[p] = { title: '' }
    }
    if (!pm._schedule) pm._schedule = { mode: 'now', scheduled_date: '', timezone: 'Asia/Taipei' }
```

- [ ] **Step 6: Verify**

```bash
python -c "s=open('web/static/index.html',encoding='utf-8').read(); print('eight_platforms:', \"'youtube','tiktok','instagram','facebook','threads','x','pinterest','reddit'\" in s); print('poll_editor:', 'poll_options' in s); print('pinterest_board:', 'pinterest_board_id' in s); print('subreddit_required:', 'subreddit' in s and '*必填' in s); print('video_state_draft:', 'video_state' in s and 'DRAFT' in s); print('threads_topic:', 'threads_topic_tag' in s)"
```
Expected: all 6 True.

- [ ] **Step 7: Commit**

```bash
git add web/static/index.html
git commit -m "feat: add Pinterest + Reddit cards; X poll / FB draft / Threads topic advanced UI"
```

---

## Task 6: End-to-end test + README update

**Files:**
- Modify: `CLAUDE.md` or create `docs/upload-features.md`

Document the newly-supported Upload-Post fields and platforms so future sessions know what's wired.

- [ ] **Step 1: Dry-run E2E on job 65 with advanced fields**

Seed a fresh platform_meta with advanced values and dry-run publisher:

```bash
rm -f pipeline/2026-04-16/job_65/platform_meta.json

# Fetch via backend so it seeds with our new defaults
curl -s http://localhost:8000/api/jobs/65/platform_meta > /tmp/meta.json

# Save via PUT (now includes all new defaults)
curl -s -X PUT http://localhost:8000/api/jobs/65/platform_meta \
  -H "Content-Type: application/json" \
  -d "$(python -c "
import json
d = json.load(open('/tmp/meta.json'))
print(json.dumps({'platform_meta': d}, ensure_ascii=False))
")"

# Dry-run all 8 platforms
python scripts/publisher.py 2026-04-16/job_65 --platforms youtube tiktok instagram facebook threads x --dry-run
```

Expected: preview prints cleanly, no exceptions. (Pinterest + Reddit will be skipped automatically because board_id / subreddit are empty by default — confirm `⚠️ 未填...跳過` messages appear as expected if included.)

- [ ] **Step 2: Add documentation section to CLAUDE.md**

Find CLAUDE.md at the root (`C:\Users\User\Documents\GitHub\AutoVideo\CLAUDE.md`). In the "Key Environment Variables" section or near it, add a new block:

```markdown
## Upload-Post Feature Coverage

We use Upload-Post's per-platform API extensively. Coverage per platform:

**YouTube** — `youtube_title`, `youtube_description`, `tags[]`, `categoryId`, `defaultLanguage`, `defaultAudioLanguage`, `privacyStatus`, `containsSyntheticMedia`, `selfDeclaredMadeForKids`, `embeddable`, `publicStatsViewable`, `license`, `thumbnail` (auto from `pipeline/.../thumbnail.png`)

**TikTok** — `tiktok_title`, `privacy_level`, `is_aigc` (2026 compliance), `cover_timestamp`, `disable_duet/comment/stitch`, `brand_content_toggle`, `brand_organic_toggle`

**Instagram Reels** — `instagram_title`, `first_comment` (hashtag spam), `collaborators`, `user_tags`, `media_type=REELS`

**Facebook Reels** — `facebook_title`, `facebook_description`, `facebook_media_type`, `video_state` (PUBLISHED/DRAFT)

**Threads** — `threads_title`, `threads_topic_tag`

**X (Twitter)** — `x_title`, `poll_options`, `poll_duration`, `reply_settings`, `x_long_text_as_post`

**Pinterest** — `pinterest_title`, `pinterest_description`, `pinterest_board_id` (REQUIRED), `pinterest_link`, `pinterest_alt_text`

**Reddit** — `reddit_title`, `subreddit` (REQUIRED), `flair_id`

**Scheduling** — `scheduled_date` + `timezone` (pass-through to Upload-Post's queue; no local scheduler)

Per-platform customization lives in `pipeline/{date}/job_{id}/platform_meta.json`. UI edits via Alpine modal. Compliance defaults (`is_aigc=true`, `containsSyntheticMedia=true`) are seeded — users can uncheck for non-AI content.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: upload-post feature coverage per platform"
```

---

## Self-Review

**1. Spec coverage:**
- AIGC compliance (TikTok + YouTube) → Task 1 seeds defaults, Task 2 publisher forwards, Task 4 UI toggles ✅
- Scheduled publishing (scheduled_date + timezone) → Task 1 schema, Task 2 publisher kwargs, Task 3 UI ✅
- YouTube SEO (categoryId, language, license, etc.) → Tasks 1, 2, 4 ✅
- TikTok controls (cover_timestamp, disable_*, brand) → Tasks 1, 2, 4 ✅
- X polls → Tasks 1, 2, 5 ✅
- Pinterest (board, link, alt) → Tasks 1, 2, 5 ✅
- Reddit (subreddit, flair) → Tasks 1, 2, 5 ✅
- Instagram (collaborators, user_tags) → Tasks 1, 2, 4 ✅
- Facebook (media_type, video_state DRAFT) → Tasks 1, 2, 5 ✅
- Threads (topic_tag) → Tasks 1, 2, 5 ✅
- "建議發布時間" advisor → Task 3 `suggestBestTime()` + `_GOLDEN_HOURS` data ✅

**2. Placeholder scan:** All tasks have exact code. One area worth double-checking: Task 4 Step 1 asks the implementer to update multiple `editingPlatform = null` sites — if any are missed, `showAdvanced` won't reset. Called out explicitly.

**3. Type consistency:**
- 8-platform list `[youtube, tiktok, instagram, facebook, threads, x, pinterest, reddit]` appears identically in: Task 1 `PLATFORMS` constant + `_seed_platform_meta` return dict, Task 2 publisher loop, Task 5 Step 3 frontend grid x-for, Task 5 Step 5 defensive init ✅
- `_schedule` nested object with `{mode, scheduled_date, timezone}` used consistently across Task 1 seed, Task 2 publisher parse, Task 3 frontend state + sync ✅
- Required fields (`pinterest_board_id`, `subreddit`) — publisher checks for empty and drops the platform (Task 2); UI marks with `*必填` label (Task 5) — consistent ✅
- `is_aigc` / `containsSyntheticMedia` default to True in seed (Task 1) + publisher default (Task 2) + UI checkbox states (Task 4) ✅

**4. Scope check:** This plan is focused on one subsystem: Upload-Post feature expansion + scheduling. All 6 tasks ship working software at each commit. Acceptable as a single plan.
