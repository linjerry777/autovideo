# Step 1 Optimization — Virality Score + Multi-Hook + Freshness Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Step 1 (news collection + Claude enrichment) so every news item comes back with a virality score + reason + emotion + 3 hook variants + freshness tier. Script review UI shows color-coded badges and lets the user pick which of the 3 hooks to use.

**Architecture:**
- **Backend (Python)** — Parse `pubDate` from feedparser entries, compute `freshness_hours`, pass to Claude. Upgrade 3 Claude prompts (`scripts/news_collector.py:select_news_with_claude`, `web/claude_client.py:enrich_news_items`, `web/claude_client.py:enrich_trending_items`) to produce the 4 new fields per item. Backward-compatible: old shape still works if Claude omits fields.
- **Frontend (Alpine.js)** — Script review shows virality score badge (green ≥8 / yellow 6-7 / red <6) with reason, emotion chip (😲驚/😡怒/😂笑/🤔好奇/😨驚恐), freshness badge (🟢<12h / 🟡12-24h / 🔴>24h). A 3-chip hook picker below the title — clicking a variant replaces `item.hook`. Manual textarea still works.

**Tech Stack:** Python (`feedparser`, `requests`), Claude Proxy (`localhost:3456`), Alpine.js, FastAPI.

---

## Research-Driven Field Schema

Based on earlier 2026 short-video research (Buffer, TikTok policy, YT algorithm):

```jsonc
{
  // Existing fields (unchanged)
  "hook":        "破千萬的秘密",
  "title":       "TXT 新 MV 爆紅",
  "script":      "...",
  "scene_type":  "trophy",
  "source_url":  "...",
  "source_name": "...",

  // NEW fields
  "virality_score":   8,                                          // 1-10, Claude's viral potential estimate
  "virality_reason":  "1188 萬觀看 + K-pop 全球受眾 + 反差感",      // 1 short sentence explaining score
  "emotion":          "surprise",                                  // surprise | anger | joy | curiosity | fear
  "hook_variants":    ["破千萬的秘密", "1188萬人搞錯了", "為什麼全網都看"], // exactly 3
  "freshness_hours":  4,                                           // computed by Python (not Claude), from RSS pubDate
  "freshness_level":  "fresh"                                      // fresh | stale | old | unknown
}
```

- `virality_score / virality_reason / emotion / hook_variants` — from Claude
- `freshness_hours / freshness_level` — computed by Python before saving (news_collector.py) OR missing (trending / pre-selected paths)

Thresholds (hardcoded in Python — keep in ONE place):
- `< 12h` → `"fresh"`
- `12-24h` → `"stale"`
- `> 24h` → `"old"`
- `None` → `"unknown"`

---

## File Map

| File | Change |
|------|--------|
| `scripts/news_collector.py` | Parse `entry.published_parsed`, compute freshness, update Claude prompt for `select_news_with_claude` |
| `web/claude_client.py` | Update `enrich_news_items` prompt (user-preselected path); update `enrich_trending_items` prompt |
| `web/static/index.html` | Script review UI — badges (score/emotion/freshness) + 3-chip hook picker |

Scope: NO DB schema changes, NO new endpoints. All new fields flow through existing `news.json` and the existing `confirm_script` PUT.

---

## Task 1: news_collector.py — freshness computation

**Files:**
- Modify: `scripts/news_collector.py` (~lines 60-82, 140-175)

Extract `published_parsed` from feedparser entries, convert to hours-since, classify into fresh/stale/old, attach to each item before Claude sees them.

- [ ] **Step 1: Add freshness helpers + extend `fetch_rss_items`**

Find `fetch_rss_items()` in `scripts/news_collector.py` (~line 60). Before it, add:

```python
import time as _time
from datetime import datetime, timezone


def _hours_since(struct_time) -> float | None:
    """Convert feedparser's published_parsed struct_time → hours since now (UTC)."""
    if not struct_time:
        return None
    try:
        ts = _time.mktime(struct_time)   # local-epoch interpretation; RSS is usually UTC-ish
        return (datetime.now(timezone.utc).timestamp() - ts) / 3600.0
    except Exception:
        return None


def _freshness_level(hours: float | None) -> str:
    if hours is None:
        return "unknown"
    if hours < 12:
        return "fresh"
    if hours < 24:
        return "stale"
    return "old"
```

Then inside `fetch_rss_items`, in the `for entry in feed.entries[:limit]:` loop, extend the dict built per entry to include freshness. Find:

```python
            for entry in feed.entries[:limit]:
                items.append({
                    "title":   entry.get("title", ""),
                    "summary": entry.get("summary", "")[:400],
                    "url":     entry.get("link", ""),
                    "source":  entry.get("source", {}).get("title", "") or feed.feed.get("title", "Google News"),
                })
```

Replace with:

```python
            for entry in feed.entries[:limit]:
                hours = _hours_since(entry.get("published_parsed"))
                items.append({
                    "title":           entry.get("title", ""),
                    "summary":         entry.get("summary", "")[:400],
                    "url":             entry.get("link", ""),
                    "source":          entry.get("source", {}).get("title", "") or feed.feed.get("title", "Google News"),
                    "freshness_hours": round(hours, 1) if hours is not None else None,
                    "freshness_level": _freshness_level(hours),
                })
```

- [ ] **Step 2: Pass freshness into Claude prompt**

Find `select_news_with_claude()` (~line 85). The current `headlines` builder is:

```python
    headlines = "\n".join([
        f"{i+1}. [{item['source']}] {item['title']}\n   URL: {item['url']}\n   {item['summary'][:120]}"
        for i, item in enumerate(raw_items[:40])
    ])
```

Replace with:

```python
    def _fresh_tag(it):
        h = it.get("freshness_hours")
        if h is None: return "[時效未知]"
        return f"[{h:.0f}h前]" if h < 48 else f"[{h/24:.0f}d前]"

    headlines = "\n".join([
        f"{i+1}. {_fresh_tag(item)} [{item['source']}] {item['title']}\n   URL: {item['url']}\n   {item['summary'][:120]}"
        for i, item in enumerate(raw_items[:40])
    ])
```

- [ ] **Step 3: Thread freshness through to output items**

Still in `select_news_with_claude`, Claude returns picked items but without the freshness fields (Claude doesn't know those). We must copy them from the matched `raw_items`. After `return json.loads(raw)` parses Claude's output, before returning, **backfill freshness** by matching URLs:

Find the current return:

```python
    raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw.strip())

    return json.loads(raw)
```

Replace the `return json.loads(raw)` line with:

```python
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        raw = match.group(0)
    picked = json.loads(raw)
    # Backfill freshness from matched raw items by URL
    raw_by_url = {it.get("url", ""): it for it in raw_items}
    for item in picked:
        src = raw_by_url.get(item.get("source_url", ""), {})
        item["freshness_hours"] = src.get("freshness_hours")
        item["freshness_level"] = src.get("freshness_level", "unknown")
    return picked
```

Note: the existing `re.sub` markdown cleanup stays above this block. We ADD the JSON-array extraction via `re.search` (more robust than just strip).

- [ ] **Step 4: Syntax check + dry fetch**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/news_collector.py').read()); print('OK')"
```
Expected: `OK`

```bash
python -X utf8 -c "
from scripts.news_collector import fetch_rss_items
items = fetch_rss_items('Taiwan AI', limit=5)
for it in items[:3]:
    print(f\"  {it.get('freshness_level','?'):<8} {it.get('freshness_hours','?'):>5}h  {it['title'][:50]}\")
"
```
Expected: 3 lines, each with a freshness_level label (fresh/stale/old/unknown) and an hours number. Most items should be `fresh` or `stale`.

- [ ] **Step 5: Commit**

```bash
git add scripts/news_collector.py
git commit -m "feat: compute freshness_hours from RSS pubDate; pass to Claude"
```

---

## Task 2: Claude prompt upgrade — `select_news_with_claude`

**Files:**
- Modify: `scripts/news_collector.py` — `select_news_with_claude` prompt (~lines 92-111)

Request 4 new fields per item: `virality_score`, `virality_reason`, `emotion`, `hook_variants[]`.

- [ ] **Step 1: Upgrade prompt JSON schema**

Find the current prompt in `select_news_with_claude`:

```python
    prompt = f"""以下是搜尋「{_kw}」得到的新聞列表。請挑出 3 則最具爆點、最能引起共鳴的新聞，適合在短影音（Shorts/Reels/TikTok）分享。

{topic_line}優先選：有數字衝擊感、意外反轉、重大突破、爭議話題的新聞。

每則新聞請用以下 JSON 格式，source_url 必須從列表中完整複製：
{{
  "hook": "開場鉤子（5-8字，製造懸念或衝擊，例如：「這個 AI 嚇到所有人」）",
  "title": "標題（15字以內，中文）",
  "summary": "摘要（40字以內，中文，口語化）",
  "script": "旁白腳本（60字以內，像在跟朋友說話的語氣，第一人稱）",
  "scene_type": "動畫場景類型（從以下擇一）：fire（攻擊/爆炸/燃燒）, race（競賽/追趕/對決）, money（融資/估值/賺錢）, robot（AI/機器人/科技突破）, warning（爭議/警告/風險）, trophy（創紀錄/得獎/突破）, default（其他）",
  "source_url": "完整的新聞原始 URL",
  "source_name": "媒體名稱"
}}

新聞列表：
{headlines}

請直接回傳只有 3 則的 JSON 陣列，不要加任何其他文字或 markdown。"""
```

Replace the `{{ ... }}` JSON schema block + closing instructions with:

```python
    prompt = f"""以下是搜尋「{_kw}」得到的新聞列表（標頭含時效標籤，例如 [4h前]）。請挑出 3 則最具爆點、最能引起共鳴的新聞，適合在短影音（Shorts/Reels/TikTok）分享。

{topic_line}優先選：
1. 時效 ≤ 12h 的新聞（Shorts 演算法偏好新鮮內容）
2. 有數字衝擊、意外反轉、重大突破、爭議話題
3. 情緒張力強（驚訝/憤怒/好笑/好奇/驚恐）

每則請用以下 JSON 格式，source_url 必須從列表中完整複製：
{{
  "hook": "主要開場鉤子（5-8字，從 hook_variants 中選最強的那個）",
  "hook_variants": ["懸念式 hook", "打臉式 hook", "提問式 hook"],
  "title": "標題（15字以內，中文）",
  "summary": "摘要（40字以內，中文，口語化）",
  "script": "旁白腳本（60字以內，像在跟朋友說話的語氣，第一人稱）",
  "scene_type": "動畫場景（擇一）：fire, race, money, robot, warning, trophy, default",
  "virality_score": 1-10 的整數，預測這則在 Shorts/TikTok 爆的潛力,
  "virality_reason": "一句話說明為什麼給這個分數（例如：『數字衝擊+反差感+時效新鮮』）",
  "emotion": "主導情緒：surprise | anger | joy | curiosity | fear 擇一",
  "source_url": "完整的新聞原始 URL",
  "source_name": "媒體名稱"
}}

hook_variants 必須生成恰好 3 個不同風格：
- 風格 A：懸念式（「破千萬的秘密」「沒人告訴你的」）
- 風格 B：打臉式（「1188 萬人搞錯了」「你以為 X 是 Y 其實...」）
- 風格 C：提問式（「為什麼全網都...？」「這事怎麼發生的？」）

新聞列表：
{headlines}

請直接回傳只有 3 則的 JSON 陣列，不要加任何其他文字或 markdown。"""
```

- [ ] **Step 2: Verify syntax**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/news_collector.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Live dry run through the upgraded prompt**

```bash
python -X utf8 -c "
from scripts.news_collector import fetch_rss_items, select_news_with_claude
raw = fetch_rss_items('AI 人工智慧', limit=10)
print(f'fetched {len(raw)} items')
picked = select_news_with_claude(raw)
for i, it in enumerate(picked, 1):
    print(f'--- {i} ---')
    print(f'  score:   {it.get(\"virality_score\")}  reason: {it.get(\"virality_reason\",\"\")[:50]}')
    print(f'  emotion: {it.get(\"emotion\")}')
    print(f'  hook:    {it.get(\"hook\")}')
    variants = it.get('hook_variants', [])
    print(f'  variants ({len(variants)}): {variants}')
    print(f'  freshness: {it.get(\"freshness_level\")} ({it.get(\"freshness_hours\")}h)')
"
```
Expected:
- 3 items returned
- Each has `virality_score` (int 1-10), `virality_reason` (string), `emotion` (one of 5 values)
- Each has exactly 3 `hook_variants`
- `freshness_level` is non-empty (set by Task 1)

- [ ] **Step 4: Commit**

```bash
git add scripts/news_collector.py
git commit -m "feat: Claude news-picker now returns virality score + 3 hook variants + emotion"
```

---

## Task 3: Prompt upgrade for user-preselected + trending paths

**Files:**
- Modify: `web/claude_client.py` — `enrich_news_items` (~lines 66-113), `enrich_trending_items` (~lines 132-193)

Same schema upgrade for the two other Claude entry points so the UI gets consistent fields regardless of which mode fed the news.

- [ ] **Step 1: Update `enrich_news_items` prompt**

Find `enrich_news_items` in `web/claude_client.py` (~line 66). The existing prompt's JSON schema block (inside the `prompt = f"""..."""` triple-quoted string) has:

```python
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

請直接回傳 JSON 陣列，不要加任何其他文字或 markdown。
```

Replace with:

```python
每則請用以下 JSON 格式（照順序）：
{{
  "hook": "主要開場鉤子（5-8字，從 hook_variants 中選最強的）",
  "hook_variants": ["懸念式", "打臉式", "提問式"],
  "title": "標題（15字以內，中文）",
  "summary": "摘要（40字以內，中文，口語化）",
  "script": "旁白腳本（依上述腳本長度，像在跟朋友說話）",
  "scene_type": "動畫場景（擇一）：fire, race, money, robot, warning, trophy, default",
  "virality_score": 1-10 整數，預測這則在短影音爆的潛力,
  "virality_reason": "一句話說明分數理由",
  "emotion": "主導情緒：surprise | anger | joy | curiosity | fear 擇一",
  "source_url": "原始 URL（從列表複製）",
  "source_name": "媒體名稱"
}}

hook_variants 必須恰好 3 個不同風格：
- 風格 A：懸念式（「破千萬的秘密」）
- 風格 B：打臉式（「1188 萬人搞錯了」）
- 風格 C：提問式（「為什麼全網都...？」）

請直接回傳 JSON 陣列，不要加任何其他文字或 markdown。
```

- [ ] **Step 2: Update `enrich_trending_items` prompt**

Find `enrich_trending_items` (~line 132). Its schema block is:

```python
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

請直接回傳 JSON 陣列，不要加任何其他文字或 markdown。
```

Replace with:

```python
每則請用以下 JSON 格式（照順序）：
{{
  "format": "top5 | explainer | reaction | story 擇一",
  "category": "tech | entertainment | finance 擇一",
  "hook": "主要開場鉤子（5-8字，從 hook_variants 選最強的）",
  "hook_variants": ["懸念式", "打臉式", "提問式"],
  "title": "標題（15字以內，中文）",
  "script": "旁白腳本（80字以內，依格式結構生成，像在跟朋友說話）",
  "scene_type": "動畫場景：fire/race/money/robot/warning/trophy/default 擇一",
  "virality_score": 1-10 整數,
  "virality_reason": "一句話說明分數理由",
  "emotion": "surprise | anger | joy | curiosity | fear 擇一",
  "account_suggestion": "科技帳號 | 娛樂帳號 | 財經帳號 擇一",
  "source_url": "原始 URL",
  "source_name": "來源名稱"
}}

hook_variants 必須恰好 3 個不同風格：懸念式 / 打臉式 / 提問式。

請直接回傳 JSON 陣列，不要加任何其他文字或 markdown。
```

- [ ] **Step 3: Verify syntax**

```bash
python -X utf8 -c "import ast; ast.parse(open('web/claude_client.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Live test both functions**

```bash
python -X utf8 -c "
from web.claude_client import enrich_news_items, enrich_trending_items
test = [{'title':'AI 突破再下一城','summary':'OpenAI 發表新模型...','url':'https://example.com/1','source':'TechCrunch'}]
print('=== enrich_news_items ===')
r = enrich_news_items(test, topic='AI', strategy='tech')[0]
print('  score:', r.get('virality_score'), '/ reason:', r.get('virality_reason',''))
print('  emotion:', r.get('emotion'))
print('  variants:', r.get('hook_variants'))

print('\\n=== enrich_trending_items ===')
test2 = [{'title':'TXT 新歌破千萬','summary':'...','url':'https://example.com/2','source':'Reddit','source_type':'reddit'}]
r2 = enrich_trending_items(test2)[0]
print('  score:', r2.get('virality_score'))
print('  format:', r2.get('format'), '/ emotion:', r2.get('emotion'))
print('  variants:', r2.get('hook_variants'))
"
```
Expected: each block prints non-None score, emotion, 3-element hook_variants array.

- [ ] **Step 5: Commit**

```bash
git add web/claude_client.py
git commit -m "feat: enrich_news_items + enrich_trending_items return score/emotion/3-hook-variants"
```

---

## Task 4: Frontend — Virality / Emotion / Freshness badges

**Files:**
- Modify: `web/static/index.html` — script review section (search for `step_screenshot === 'script_review'`)

Each news item card in the script-review panel gets 3 new badges above the existing hook/script inputs: virality score, emotion, freshness.

- [ ] **Step 1: Add Alpine helpers**

Find the Alpine methods block (where `_PLATFORM_STYLE`, `_GOLDEN_HOURS`, etc. live). Add a sibling property:

```js
_EMOTION_CHIP: {
  surprise:  { icon: '😲', label: '驚訝',  cls: 'bg-purple-50 text-purple-700 border-purple-200' },
  anger:     { icon: '😡', label: '憤怒',  cls: 'bg-red-50 text-red-700 border-red-200' },
  joy:       { icon: '😂', label: '好笑',  cls: 'bg-yellow-50 text-yellow-700 border-yellow-200' },
  curiosity: { icon: '🤔', label: '好奇',  cls: 'bg-blue-50 text-blue-700 border-blue-200' },
  fear:      { icon: '😨', label: '驚恐',  cls: 'bg-gray-50 text-gray-700 border-gray-200' },
},

_FRESHNESS_CHIP: {
  fresh:   { icon: '🟢', label: '新鮮 <12h',  cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  stale:   { icon: '🟡', label: '過時 12-24h', cls: 'bg-yellow-50 text-yellow-700 border-yellow-200' },
  old:     { icon: '🔴', label: '老舊 >24h',   cls: 'bg-red-50 text-red-700 border-red-200' },
  unknown: { icon: '⚪', label: '時效未知',    cls: 'bg-gray-50 text-gray-500 border-gray-200' },
},

_scoreColor(score) {
  if (score == null) return 'bg-gray-50 text-gray-500 border-gray-200'
  if (score >= 8)    return 'bg-emerald-50 text-emerald-700 border-emerald-300'
  if (score >= 6)    return 'bg-yellow-50 text-yellow-700 border-yellow-300'
  return 'bg-red-50 text-red-700 border-red-300'
},
```

- [ ] **Step 2: Add badge row to script review card**

Find the script review section. Use Grep to locate — search for `x-show="currentJob?.step_screenshot === 'script_review'"`. Inside its `<template x-for="(item, i) in scriptItems">` block, there's a `<div class="glass rounded-2xl p-5 space-y-3">` card. Inside that card, right AFTER the existing `<div class="flex items-center gap-2 text-sm font-semibold text-gray-700">...</div>` (the header with `#1` badge + title), add:

```html
              <!-- Virality / emotion / freshness badges -->
              <div class="flex items-center gap-2 flex-wrap">
                <span x-show="item.virality_score != null"
                  class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-xs font-semibold"
                  :class="_scoreColor(item.virality_score)">
                  🔥 <span x-text="item.virality_score"></span>/10
                </span>

                <span x-show="item.emotion && _EMOTION_CHIP[item.emotion]"
                  class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-xs font-medium"
                  :class="_EMOTION_CHIP[item.emotion]?.cls"
                  x-text="_EMOTION_CHIP[item.emotion]?.icon + ' ' + _EMOTION_CHIP[item.emotion]?.label">
                </span>

                <span x-show="item.freshness_level && _FRESHNESS_CHIP[item.freshness_level]"
                  class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-xs font-medium"
                  :class="_FRESHNESS_CHIP[item.freshness_level]?.cls"
                  x-text="_FRESHNESS_CHIP[item.freshness_level]?.icon + ' ' + _FRESHNESS_CHIP[item.freshness_level]?.label">
                </span>
              </div>

              <!-- Virality reason -->
              <p x-show="item.virality_reason"
                class="text-[11px] text-gray-500 italic leading-snug"
                x-text="'💡 ' + item.virality_reason"></p>
```

- [ ] **Step 3: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('emotion_chip:', '_EMOTION_CHIP' in s); print('freshness_chip:', '_FRESHNESS_CHIP' in s); print('score_color:', '_scoreColor' in s); print('score_badge:', 'virality_score != null' in s); print('reason_line:', 'virality_reason' in s)"
```
Expected: all 5 True.

- [ ] **Step 4: Commit**

```bash
git add web/static/index.html
git commit -m "feat: script review shows virality score + emotion + freshness badges"
```

---

## Task 5: Frontend — 3-hook picker

**Files:**
- Modify: `web/static/index.html` — script review hook input (inside the same card as Task 4)

Display `hook_variants` as 3 clickable chips. Clicking replaces `item.hook`. Currently-selected variant gets a highlighted border. Existing `<input x-model="item.hook">` still works for manual edits.

- [ ] **Step 1: Insert the picker above the existing Hook input**

Find the Hook input inside the script review card — it looks like:
```html
              <div>
                <label class="text-xs font-medium text-gray-400 block mb-1">Hook</label>
                <input x-model="item.hook" type="text" ...>
              </div>
```

Just BEFORE that `<div>` (so the picker sits above the Hook label), insert:

```html
              <div x-show="item.hook_variants && item.hook_variants.length > 0">
                <label class="text-xs font-medium text-gray-400 block mb-1">選擇 Hook 風格（AI 生成 3 個版本）</label>
                <div class="flex flex-wrap gap-2">
                  <template x-for="(variant, vi) in item.hook_variants" :key="vi">
                    <button type="button"
                      @click="item.hook = variant"
                      :class="item.hook === variant
                        ? 'bg-emerald-50 border-emerald-400 text-emerald-700 ring-1 ring-emerald-200'
                        : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'"
                      class="text-sm px-3 py-1.5 rounded-lg border transition-all text-left flex items-start gap-2">
                      <span class="text-[10px] text-gray-400 mt-0.5"
                        x-text="['A懸念','B打臉','C提問'][vi] || '#' + (vi+1)"></span>
                      <span x-text="variant"></span>
                    </button>
                  </template>
                </div>
              </div>
```

Change the existing `<label>Hook</label>` to `<label>Hook（手動覆寫上方選擇）</label>` so the user understands the relationship:

```html
                <label class="text-xs font-medium text-gray-400 block mb-1">Hook（手動覆寫上方選擇）</label>
```

- [ ] **Step 2: Verify**

```bash
python -X utf8 -c "s=open('web/static/index.html',encoding='utf-8').read(); print('picker:', 'hook_variants && item.hook_variants.length' in s); print('click_sets_hook:', 'item.hook = variant' in s); print('style_hint:', \"'A懸念','B打臉','C提問'\" in s); print('label_updated:', '手動覆寫上方選擇' in s)"
```
Expected: all 4 True.

- [ ] **Step 3: Commit**

```bash
git add web/static/index.html
git commit -m "feat: 3-hook variant picker in script review (A懸念/B打臉/C提問)"
```

---

## Task 6: E2E test

**Files:**
- None modified — just runs an end-to-end smoke test.

- [ ] **Step 1: Trigger a real job via API with a small topic**

```bash
python -X utf8 << 'EOF'
import urllib.request, json
body = json.dumps({
    'date': '2026-04-17',
    'topic': 'AI 人工智慧',
    'lang': 'zh-TW',
    'platforms': ['youtube'],
    'dry_run': True,
}).encode()
req = urllib.request.Request('http://localhost:8000/api/jobs/trigger',
    data=body, method='POST', headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=30) as r:
    print(json.loads(r.read()))
EOF
```

Expected: `{"job_id": N, "date": "2026-04-17", "status": "queued"}`

Note the job_id — call it `$JID`.

- [ ] **Step 2: Wait for the job to reach script_review, then inspect news.json**

```bash
# Replace 73 with the actual job_id from Step 1
JID=73

# Poll every 5s up to 3 min
for i in $(seq 1 36); do
  s=$(curl -s --max-time 5 http://localhost:8000/api/jobs/$JID | python -X utf8 -c "import sys,json; print(json.loads(sys.stdin.read()).get('step_screenshot'))")
  echo "t+${i}0s step_screenshot=$s"
  if [ "$s" = "script_review" ]; then break; fi
  sleep 5
done
```

Expected: `step_screenshot=script_review` within ~2 min (news_collector runs + Claude enrichment).

- [ ] **Step 3: Verify new fields in news.json**

```bash
python -X utf8 -c "
import json
from pathlib import Path
# JID from Step 1; adjust as needed
for d in Path('pipeline/2026-04-17').iterdir():
    if d.is_dir() and d.name.startswith('job_'):
        nj = d / 'news.json'
        if nj.exists():
            data = json.loads(nj.read_text(encoding='utf-8'))
            items = data.get('items', [])
            if items and 'virality_score' in items[0]:
                print(f'--- {d.name} (newest) ---')
                for i, it in enumerate(items, 1):
                    print(f'  #{i} score={it.get(\"virality_score\"):>2}/10 | emotion={it.get(\"emotion\"):<10} | freshness={it.get(\"freshness_level\"):<8} | variants={len(it.get(\"hook_variants\",[]))} | hook={it.get(\"hook\",\"\")[:20]}')
                    print(f'       reason: {it.get(\"virality_reason\",\"\")[:80]}')
                break
"
```

Expected per item:
- `score=` 1-10 integer
- `emotion=` one of `surprise/anger/joy/curiosity/fear`
- `freshness=` one of `fresh/stale/old/unknown`
- `variants=3`
- `reason=` non-empty explanation

- [ ] **Step 4: Open UI and verify badges + hook picker visible**

Open `http://localhost:8000/ui` → navigate to the running job → script review page. Confirm:
- Each news item shows 🔥 score / 😲 emotion / 🟢 freshness badges
- `💡 reason` line appears below title
- 3-chip hook picker shows above Hook input
- Clicking a chip replaces the hook value in the textarea below
- Manual typing in the textarea still works

Cancel the test job after visual confirmation:

```bash
# Replace with your JID
curl -s -X POST http://localhost:8000/api/jobs/73/cancel
```

- [ ] **Step 5: Commit (empty — just a marker that E2E passed)**

No file changes here — the commit captures that the plan's end-to-end flow was verified manually.

```bash
git commit --allow-empty -m "test: Step 1 optimization (score/emotion/freshness/variants) verified E2E"
```

---

## Self-Review

**1. Spec coverage:**
- Virality score + reason → Task 2 (news_collector prompt), Task 3 (claude_client prompts), Task 4 (UI badge) ✅
- Emotion (5 values) → Task 2, Task 3, Task 4 (emotion chip) ✅
- 3 hook variants → Task 2, Task 3 (prompts), Task 5 (picker UI) ✅
- Freshness (hours + level) → Task 1 (Python compute from RSS), Task 4 (badge) ✅
- Backward compat (old Claude responses without new fields) → All UI badges guarded by `x-show="item.X != null"` ✅
- Trending path also upgraded → Task 3 updates `enrich_trending_items` ✅

**2. Placeholder scan:**
- All prompts have concrete JSON schema with examples
- Task 1 freshness function shows exact struct_time → hours conversion
- Task 6 wait-loop has concrete polling interval and exit condition
- No TBD/TODO

**3. Type consistency:**
- `virality_score: int (1-10)` used in Claude prompts (Tasks 2, 3) + `_scoreColor(score)` threshold check in Task 4 — consistent ✅
- `emotion: "surprise"|"anger"|"joy"|"curiosity"|"fear"` — prompt vocabulary (Tasks 2, 3) matches `_EMOTION_CHIP` keys in Task 4 ✅
- `hook_variants: string[]` exactly 3 — prompt specifies 3, UI picker `x-for` iterates variable length (safe if Claude returns fewer, picker just shows what it got) ✅
- `freshness_level: "fresh"|"stale"|"old"|"unknown"` — computed in Task 1 `_freshness_level()`, consumed in Task 4 `_FRESHNESS_CHIP` keys ✅
- `freshness_hours: float | None` — Task 1 returns `round(hours, 1)` or `None`, Task 4 UI doesn't read this directly (only `freshness_level`), but it's in news.json for debugging ✅

**4. Scope check:**
Single subsystem (Step 1 — news collection + enrichment + script review UI). No DB schema change, no new endpoints, no new files. 6 tasks. Acceptable as single plan.
