# Generate Page Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 UI issues on the generate page: more news sources, state persistence across navigation, screenshot review step with news replacement (scrollable), and blocked screenshot fallback.

**Architecture:** The Next.js frontend is fully Supabase-based (serverless). News fetching is done in Next.js API routes; jobs are stored in Supabase. The Python backend at `:8000` is only used for news caching. Screenshots are either from `screenshotone.com` or `/api/card` fallback. All fixes are in `frontend/`.

**Tech Stack:** Next.js 16 App Router, TypeScript, Tailwind CSS, Supabase, Groq SDK, Fish Audio SDK

---

## Architecture Map

| Issue | Files to Modify |
|-------|----------------|
| 1. More sources (Bing + HN) | `frontend/app/api/news/sources/route.ts`, `frontend/app/api/news/fetch/route.ts` |
| 2. last30days data volume | `web/routes/news.py` line 218 |
| 3. State persistence | `frontend/app/generate/page.tsx` |
| 4+5. Screenshot review + scrollable replace | `frontend/app/generate/page.tsx` |
| 6. Blocked screenshot fallback | `frontend/app/generate/page.tsx` |

---

## Task 1: Add Bing + Hacker News as news sources

**Files:**
- Modify: `frontend/app/api/news/sources/route.ts`
- Modify: `frontend/app/api/news/fetch/route.ts`

Currently `sources/route.ts` hardcodes only Google News. `fetch/route.ts` only fetches from Google News RSS. This task adds Bing News RSS and Hacker News Algolia API.

- [ ] **Step 1: Update sources list**

Replace `frontend/app/api/news/sources/route.ts` entirely:

```typescript
import { NextResponse } from 'next/server'

const SOURCES = [
  { id: 'google',     label: 'Google News', icon: '🔍', default: true  },
  { id: 'bing',       label: 'Bing News',   icon: '🔎', default: true  },
  { id: 'hackernews', label: 'Hacker News', icon: '🦊', default: false },
  { id: 'last30days', label: 'Social (Reddit·HN)', icon: '🌐', default: false },
]

export async function GET() {
  return NextResponse.json({
    sources:  SOURCES,
    defaults: SOURCES.filter(s => s.default).map(s => s.id),
  })
}
```

- [ ] **Step 2: Add Bing + HN fetchers to news/fetch/route.ts**

In `frontend/app/api/news/fetch/route.ts`, after the `fetchRSS` function (around line 47), add:

```typescript
async function fetchBing(keyword: string, lang = 'zh-TW'): Promise<Array<{
  title: string; summary: string; url: string; source: string; source_type: string
}>> {
  const langMap: Record<string, string> = { 'zh-TW': 'zh-tw', 'zh-CN': 'zh-cn', 'en': 'en-us' }
  const setlang = langMap[lang] ?? 'zh-tw'
  try {
    const res = await fetch(
      `https://www.bing.com/news/search?q=${encodeURIComponent(keyword)}&setlang=${setlang}&format=RSS`,
      { headers: { 'User-Agent': 'Mozilla/5.0' }, next: { revalidate: 0 } }
    )
    const xml = await res.text()
    const items: Array<{ title: string; summary: string; url: string; source: string; source_type: string }> = []
    const itemMatches = xml.matchAll(/<item>([\s\S]*?)<\/item>/g)
    for (const match of itemMatches) {
      const block = match[1]
      const title  = (block.match(/<title><!\[CDATA\[(.*?)\]\]><\/title>/) ?? block.match(/<title>(.*?)<\/title>/))?.[1] ?? ''
      const link   = (block.match(/<link>(.*?)<\/link>/))?.[1] ?? ''
      const desc   = (block.match(/<description><!\[CDATA\[(.*?)\]\]><\/description>/) ?? block.match(/<description>(.*?)<\/description>/))?.[1] ?? ''
      const srcName = (block.match(/<source[^>]*>(.*?)<\/source>/))?.[1] ?? 'Bing News'
      if (title && link) {
        items.push({ title, summary: desc.replace(/<[^>]+>/g, '').slice(0, 300), url: link, source: `Bing · ${srcName}`, source_type: 'bing' })
      }
      if (items.length >= 25) break
    }
    return items
  } catch { return [] }
}

async function fetchHackerNews(keyword: string): Promise<Array<{
  title: string; summary: string; url: string; source: string; source_type: string
}>> {
  try {
    const url = keyword
      ? `https://hn.algolia.com/api/v1/search?query=${encodeURIComponent(keyword)}&tags=story&hitsPerPage=20`
      : `https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=20`
    const data = await (await fetch(url, { next: { revalidate: 0 } })).json()
    return (data.hits ?? []).filter((h: Record<string, unknown>) => h.title && h.url).map((h: Record<string, unknown>) => ({
      title:       String(h.title ?? ''),
      summary:     `🔥 ${h.points ?? 0} pts · ${h.num_comments ?? 0} 留言`,
      url:         String(h.url ?? `https://news.ycombinator.com/item?id=${h.objectID}`),
      source:      'Hacker News',
      source_type: 'hackernews',
    }))
  } catch { return [] }
}
```

- [ ] **Step 3: Update the GET handler to accept `sources` param and call all fetchers in parallel**

Replace the `GET` function in `frontend/app/api/news/fetch/route.ts`:

```typescript
export async function GET(request: NextRequest) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { searchParams } = request.nextUrl
  const topic   = searchParams.get('topic') ?? ''
  const lang    = searchParams.get('lang') ?? 'zh-TW'
  const sources = (searchParams.get('sources') ?? 'google,bing').split(',').filter(Boolean)
  const today   = new Date().toISOString().split('T')[0]
  const keyword = topic || DEFAULT_KEYWORD

  // Check today's cache (per user + topic + lang + sources combo)
  const cacheKey = `${topic}|${lang}|${sources.sort().join(',')}`
  const { data: cached } = await supabase
    .from('news_cache')
    .select('*')
    .eq('user_id', user.id)
    .eq('topic', cacheKey)
    .eq('lang', lang)
    .eq('fetch_date', today)
    .order('id', { ascending: true })

  if (cached && cached.length > 0) {
    return NextResponse.json({
      keyword, lang, from_cache: true,
      items: cached.map(r => ({
        cache_id:          r.id,
        title:             r.title,
        summary:           r.summary,
        url:               r.url,
        source:            r.source,
        source_type:       r.source_type ?? 'google',
        screenshot_blocked: r.blocked ?? false,
      })),
    })
  }

  // Fetch from selected sources in parallel
  const fetchers: Promise<Array<{ title: string; summary: string; url: string; source: string; source_type?: string }>>[] = []
  if (sources.includes('google'))     fetchers.push(fetchRSS(keyword, lang))
  if (sources.includes('bing'))       fetchers.push(fetchBing(keyword, lang))
  if (sources.includes('hackernews')) fetchers.push(fetchHackerNews(keyword))

  const results = await Promise.allSettled(fetchers)
  const seen = new Set<string>()
  const rawItems: Array<{ title: string; summary: string; url: string; source: string; source_type: string }> = []
  for (const r of results) {
    if (r.status === 'fulfilled') {
      for (const item of r.value) {
        if (item.url && !seen.has(item.url)) {
          seen.add(item.url)
          rawItems.push({ ...item, source_type: (item as { source_type?: string }).source_type ?? 'google' })
        }
      }
    }
  }

  if (rawItems.length === 0) {
    return NextResponse.json({ error: '無法取得新聞，請稍後再試' }, { status: 502 })
  }

  // Save to cache
  const rows = rawItems.map(item => ({
    user_id:    user.id,
    topic:      cacheKey,
    lang,
    fetch_date: today,
    title:      item.title,
    summary:    item.summary,
    url:        item.url,
    source:     item.source,
    source_type: item.source_type,
  }))

  const { data: inserted } = await supabase.from('news_cache').insert(rows).select('id')
  const ids = inserted?.map(r => r.id) ?? []

  return NextResponse.json({
    keyword, lang, from_cache: false,
    items: rawItems.map((item, i) => ({
      cache_id:          ids[i] ?? i,
      title:             item.title,
      summary:           item.summary,
      url:               item.url,
      source:            item.source,
      source_type:       item.source_type,
      screenshot_blocked: false,
    })),
  })
}
```

Note: The `fetchRSS` function needs a `lang` parameter. Update its signature:
```typescript
async function fetchRSS(keyword: string, lang = 'zh-TW'): Promise<Array<{...}>> {
  const langMap: Record<string, { hl: string; gl: string; ceid: string }> = {
    'zh-TW': { hl: 'zh-TW', gl: 'TW', ceid: 'TW:zh-Hant' },
    'zh-CN': { hl: 'zh-CN', gl: 'CN', ceid: 'CN:zh-Hans' },
    'en':    { hl: 'en-US', gl: 'US', ceid: 'US:en'      },
  }
  const { hl, gl, ceid } = langMap[lang] ?? langMap['zh-TW']
  for (const days of [3, 7, 30]) {
    try {
      const q = encodeURIComponent(`${keyword} when:${days}d`)
      const res = await fetch(
        `https://news.google.com/rss/search?q=${q}&hl=${hl}&gl=${gl}&ceid=${ceid}`,
        { headers: { 'User-Agent': 'Mozilla/5.0' }, next: { revalidate: 0 } }
      )
      // ... rest of existing logic unchanged
```

- [ ] **Step 4: Verify — open browser at http://localhost:3000/generate, open DevTools Network tab, click sources — confirm you see Google, Bing, Hacker News options. Fetch news with Bing selected, confirm Bing items appear.**

- [ ] **Step 5: Commit**

```bash
git add frontend/app/api/news/sources/route.ts frontend/app/api/news/fetch/route.ts
git commit -m "feat: add Bing News and Hacker News as selectable news sources"
```

---

## Task 2: Fix last30days returning too few results

**Files:**
- Modify: `web/routes/news.py` line 216–219

The `_fetch_last30days` function calls the script with `--quick` (limits results) and only searches `reddit,hackernews`. Remove `--quick` and add more social sources.

- [ ] **Step 1: Update the subprocess call in `web/routes/news.py`**

Find lines ~216–219:
```python
result = subprocess.run(
    [sys.executable, str(_LAST30DAYS_SCRIPT), keyword,
     "--emit", "json", "--quick", "--search", "reddit,hackernews"],
```

Replace with:
```python
result = subprocess.run(
    [sys.executable, str(_LAST30DAYS_SCRIPT), keyword,
     "--emit", "json", "--search", "reddit,hackernews,x,youtube"],
```

- [ ] **Step 2: Test directly**

```bash
python -c "
from web.routes.news import _fetch_last30days
items = _fetch_last30days('ai')
print(f'Got {len(items)} items')
for i in items[:3]: print(i['title'][:60], '-', i['source'])
"
```

Expected: 10+ items from reddit, hackernews, x, youtube.

- [ ] **Step 3: Commit**

```bash
git add web/routes/news.py
git commit -m "fix: remove --quick flag from last30days to get more social results"
```

---

## Task 3: Persist generate page state across navigation

**Files:**
- Modify: `frontend/app/generate/page.tsx`

When user navigates to dashboard and back, all state (newsItems, topic, selectedSources, step, checked items) is lost. Fix by saving/restoring from `sessionStorage`.

- [ ] **Step 1: Add a `STORAGE_KEY` constant and save helper at the top of `GeneratePage`**

After the existing imports and type definitions, add a storage key constant. Inside `GeneratePage`, add a `saveState` function and `useEffect` to persist state:

```typescript
const STORAGE_KEY = 'generate_page_state'

// Inside GeneratePage, after state declarations:
// Save state to sessionStorage whenever key values change
useEffect(() => {
  if (step === 'fetching' || step === 'generating') return  // don't save mid-flight states
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
      step,
      topic,
      newsLang,
      selectedSources: [...selectedSources],
      platforms,
      newsItems,
      checked: [...checked],
    }))
  } catch { /* ignore quota errors */ }
}, [step, topic, newsLang, selectedSources, platforms, newsItems, checked])
```

- [ ] **Step 2: Restore state from sessionStorage on mount**

Replace the existing `useEffect` that loads settings (around line 146) by adding a restore block BEFORE the settings load:

```typescript
// Restore persisted state
useEffect(() => {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw)
    if (saved.step && saved.step !== 'generating') setStep(saved.step)
    if (saved.topic)        setTopic(saved.topic)
    if (saved.newsLang)     setNewsLang(saved.newsLang)
    if (saved.selectedSources) setSelectedSources(new Set(saved.selectedSources))
    if (saved.platforms)    setPlatforms(saved.platforms)
    if (saved.newsItems?.length) setNewsItems(saved.newsItems)
    if (saved.checked?.length)   setChecked(new Set(saved.checked))
  } catch { /* ignore parse errors */ }
}, [])  // runs once on mount
```

- [ ] **Step 3: Clear state on successful completion**

In `handleUpload` (around the success branch), add:
```typescript
sessionStorage.removeItem(STORAGE_KEY)
```

Also in `handleSkipUpload`:
```typescript
const handleSkipUpload = () => {
  sessionStorage.removeItem(STORAGE_KEY)
  setNewsItems([]); setScriptItems([])
  refresh()
  setStep('idle')
}
```

- [ ] **Step 4: Verify**

1. Start the frontend (`cd frontend && npm run dev`)
2. Navigate to `/generate`, set topic to "AI", select news items
3. Navigate to `/` (dashboard)
4. Navigate back to `/generate`
5. Confirm: topic "AI" is still set, news items still visible, selected items still checked

- [ ] **Step 5: Commit**

```bash
git add frontend/app/generate/page.tsx
git commit -m "feat: persist generate page state in sessionStorage across navigation"
```

---

## Task 4: Add screenshot review step with news replacement

**Files:**
- Modify: `frontend/app/generate/page.tsx`
- Modify: `frontend/lib/api.ts`

Currently after `confirmScript`, the pipeline immediately calls `runTTS` without showing screenshots. This task adds:
1. A `screenshot_review` UIStep that shows og_images before TTS
2. A "換新聞" button per item that opens a candidate list
3. A "繼續生成語音與影片" button that proceeds to TTS

**Understanding the data flow:**
- `activeJob.id` is set after `triggerJob`
- `job.news_items` in Supabase contains `{ og_image, hook, title, script, source_url, source_name }`
- `scriptItems` (state) holds the confirmed news items with scripts
- Candidates come from `/api/news/candidates?job_id={id}` → calls Python backend's `/api/news/candidates`

- [ ] **Step 1: Add `screenshot_review` to UIStep type and state**

In `generate/page.tsx`, change:
```typescript
type UIStep = "idle" | "fetching" | "selecting" | "generating" | "video_review";
```
to:
```typescript
type UIStep = "idle" | "fetching" | "selecting" | "generating" | "screenshot_review" | "video_review";
```

Add state for replacement UI:
```typescript
const [replacingIndex, setReplacingIndex]   = useState<number | null>(null)
const [candidates, setCandidates]           = useState<RawNewsItem[]>([])
const [loadingCandidates, setLoadingCandidates] = useState(false)
const [screenshotItems, setScreenshotItems] = useState<NewsItem[]>([])
```

- [ ] **Step 2: Modify `handleConfirmScript` to stop at screenshot_review instead of running TTS**

Replace the `handleConfirmScript` function:

```typescript
const handleConfirmScript = async (items: NewsItem[]) => {
  if (!activeJob?.id) return
  setConfirmingScript(true)
  try {
    await apiClient.confirmScript(activeJob.id, items)
    setScriptItems([])
    setScreenshotItems(items)  // save for screenshot review
    setActiveJob(prev => prev ? { ...prev, step_screenshot: 'done' } as Job : null)
    setStep('screenshot_review')  // pause here for user to review screenshots
  } catch (e) {
    setError(e instanceof Error ? e.message : '確認腳本失敗')
  } finally {
    setConfirmingScript(false)
  }
}
```

- [ ] **Step 3: Add `handleContinueToTTS` (called when user confirms screenshots)**

Add this function after `handleConfirmScript`:

```typescript
const handleContinueToTTS = async () => {
  if (!activeJob?.id) return
  setStep('generating')
  await runPipeline(activeJob.id)
}
```

- [ ] **Step 4: Add `handleReplaceNews` function**

```typescript
const handleReplaceNews = async (index: number) => {
  if (!activeJob?.id) return
  setReplacingIndex(index)
  setLoadingCandidates(true)
  try {
    const res = await apiClient.getCandidates(activeJob.id)
    // Filter out items already in screenshotItems
    const usedUrls = new Set(screenshotItems.map(i => i.source_url))
    setCandidates(res.items.filter(c => !usedUrls.has(c.url)))
  } catch (e) {
    setError(e instanceof Error ? e.message : '載入候選新聞失敗')
  } finally {
    setLoadingCandidates(false)
  }
}
```

- [ ] **Step 5: Add `handleSelectCandidate` (replaces one item with a candidate)**

```typescript
const handleSelectCandidate = async (candidate: RawNewsItem) => {
  if (replacingIndex === null || !activeJob?.id) return
  // Regenerate script for the replacement via Groq (reuse existing confirm_script)
  // For now: create a minimal NewsItem from the raw candidate
  const newItem: NewsItem = {
    hook:        candidate.title.slice(0, 15),
    title:       candidate.title.slice(0, 30),
    summary:     candidate.summary?.slice(0, 60) ?? '',
    script:      candidate.summary ?? candidate.title,
    source_url:  candidate.url,
    source_name: candidate.source,
    og_image:    undefined,
  }
  const updated = screenshotItems.map((item, i) => i === replacingIndex ? newItem : item)
  setScreenshotItems(updated)
  // Update job in Supabase
  try {
    await apiClient.confirmScript(activeJob.id, updated)
  } catch { /* non-fatal */ }
  setReplacingIndex(null)
  setCandidates([])
}
```

- [ ] **Step 6: Add `ScreenshotReviewStep` component in `generate/page.tsx`** (above `GeneratePage`)

```typescript
function ScreenshotReviewStep({
  items,
  onContinue,
  onReplace,
  onCancel,
}: {
  items: NewsItem[]
  onContinue: () => void
  onReplace: (index: number) => void
  onCancel: () => void
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-medium text-sm text-gray-600">截圖審核</h2>
          <p className="text-xs text-gray-400 mt-0.5">確認截圖後繼續生成語音與影片</p>
        </div>
        <div className="flex gap-2">
          <button onClick={onCancel}
            className="px-3 py-1.5 rounded-lg text-xs text-red-500 border border-red-500/20 hover:bg-red-500/10 cursor-pointer transition-colors">
            取消任務
          </button>
          <button onClick={onContinue}
            className="px-4 py-1.5 rounded-lg text-xs font-medium bg-green-600 hover:bg-green-700 text-white cursor-pointer transition-colors">
            繼續生成語音與影片 →
          </button>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {items.map((item, i) => (
          <div key={i} className="rounded-xl border border-gray-200 overflow-hidden bg-gray-50">
            <ScreenshotCard item={item} index={i} onReplace={() => onReplace(i)} />
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 7: Add `ScreenshotCard` component** (above `ScreenshotReviewStep`)

```typescript
function ScreenshotCard({
  item, index, onReplace,
}: {
  item: NewsItem; index: number; onReplace: () => void
}) {
  const [imgError, setImgError] = useState(false)

  return (
    <div className="space-y-2 p-2">
      <div className="aspect-video rounded-lg overflow-hidden bg-gray-100 relative">
        {item.og_image && !imgError ? (
          <img
            src={item.og_image}
            alt={item.title}
            className="w-full h-full object-cover"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center p-3 bg-gradient-to-br from-gray-100 to-gray-200">
            <span className="text-2xl mb-1">📰</span>
            <p className="text-[10px] text-gray-500 text-center leading-tight">{item.title.slice(0, 40)}</p>
          </div>
        )}
        <span className="absolute top-1 left-1 bg-black/50 text-white text-[10px] px-1.5 py-0.5 rounded">
          #{index + 1}
        </span>
      </div>
      <p className="text-[11px] text-gray-600 leading-tight line-clamp-2">{item.hook}</p>
      <button
        onClick={onReplace}
        className="w-full py-1 rounded-lg text-[11px] text-gray-500 border border-gray-200 hover:border-green-400 hover:text-green-600 cursor-pointer transition-colors">
        換新聞
      </button>
    </div>
  )
}
```

- [ ] **Step 8: Add the candidate replacement panel** (as a slide-over inside the right panel)

In `generate/page.tsx`, inside the right panel (`lg:col-span-3`) section, add the screenshot review and candidate panel rendering:

```typescript
{/* Screenshot review */}
{step === 'screenshot_review' && replacingIndex === null && (
  <ScreenshotReviewStep
    items={screenshotItems}
    onContinue={handleContinueToTTS}
    onReplace={handleReplaceNews}
    onCancel={handleCancel}
  />
)}

{/* Candidate replacement panel */}
{step === 'screenshot_review' && replacingIndex !== null && (
  <div className="space-y-3">
    <div className="flex items-center justify-between">
      <div>
        <h2 className="font-medium text-sm text-gray-600">選擇替換新聞 #{replacingIndex + 1}</h2>
        <p className="text-xs text-gray-400 mt-0.5">點選一則新聞替換</p>
      </div>
      <button
        onClick={() => { setReplacingIndex(null); setCandidates([]) }}
        className="px-3 py-1.5 rounded-lg text-xs text-gray-400 border border-gray-200 hover:border-gray-300 cursor-pointer transition-colors">
        ← 返回
      </button>
    </div>
    {loadingCandidates ? (
      <div className="flex items-center justify-center h-32">
        <span className="w-5 h-5 border-2 border-green-500 border-t-transparent rounded-full animate-spin" />
      </div>
    ) : (
      <div className="space-y-1.5 max-h-[480px] overflow-y-auto pr-1">
        {candidates.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-8">沒有更多候選新聞，請重新搜尋</p>
        ) : candidates.map((c, i) => (
          <button key={i} onClick={() => handleSelectCandidate(c)}
            className="w-full text-left rounded-lg border border-gray-200 px-3 py-2.5 hover:border-green-300 hover:bg-green-50/30 transition-all cursor-pointer">
            <p className="text-sm text-gray-700 leading-snug">{c.title}</p>
            <p className="text-[11px] text-gray-400 mt-0.5">{c.source}</p>
          </button>
        ))}
      </div>
    )}
  </div>
)}
```

- [ ] **Step 9: Update the left panel action for `screenshot_review` step**

In the left panel action button section (after `step === 'selecting'` block), add:

```typescript
{step === 'screenshot_review' && replacingIndex === null && (
  <div className="flex items-center gap-3 py-3 px-4 rounded-xl bg-yellow-500/[0.08] border border-yellow-500/20">
    <span className="text-yellow-500 text-sm">📸</span>
    <p className="text-sm text-yellow-700 font-medium flex-1">確認截圖後繼續</p>
  </div>
)}
{step === 'screenshot_review' && replacingIndex !== null && (
  <div className="flex items-center gap-3 py-3 px-4 rounded-xl bg-blue-500/[0.08] border border-blue-500/20">
    <span className="text-blue-500 text-sm">🔄</span>
    <p className="text-sm text-blue-700 font-medium flex-1">選擇替換新聞 #{(replacingIndex ?? 0) + 1}</p>
  </div>
)}
```

- [ ] **Step 10: Also persist `screenshotItems` in sessionStorage**

In the `useEffect` that saves state (Task 3), add `screenshotItems` to the saved object:
```typescript
screenshotItems,
```

And in the restore `useEffect`:
```typescript
if (saved.screenshotItems?.length) setScreenshotItems(saved.screenshotItems)
```

- [ ] **Step 11: Verify flow**
1. Start dev server: `cd frontend && npm run dev`
2. Navigate to `/generate`
3. Set topic "AI", select 3 news items
4. Click "生成" → wait for script review
5. Confirm script → should now land on screenshot review step
6. Verify 3 screenshot cards appear (with og_image or fallback icon)
7. Click "換新聞" on one card → verify scrollable candidate list appears
8. Click a candidate → verify it replaces the item
9. Click "繼續生成語音與影片" → verify TTS starts

- [ ] **Step 12: Commit**

```bash
git add frontend/app/generate/page.tsx frontend/lib/api.ts
git commit -m "feat: add screenshot review step with news replacement before TTS"
```

---

## Task 5: Fix blocked screenshot display (fallback handled in Task 4)

The `ScreenshotCard` component added in Task 4 already handles this via `onError={() => setImgError(true)}`. This task adds one more improvement: show the source URL as a clickable link under the fallback.

**Files:**
- Modify: `frontend/app/generate/page.tsx` — `ScreenshotCard` component

- [ ] **Step 1: Update the fallback state in `ScreenshotCard` to show source URL**

In the fallback div (when `!item.og_image || imgError`), add a clickable link:

```typescript
<div className="w-full h-full flex flex-col items-center justify-center p-3 bg-gradient-to-br from-gray-100 to-gray-200">
  <span className="text-2xl mb-1">📰</span>
  <p className="text-[10px] text-gray-500 text-center leading-tight mb-2">{item.title.slice(0, 40)}</p>
  {item.source_url && (
    <a
      href={item.source_url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-[9px] text-blue-400 hover:underline truncate max-w-full px-1"
      onClick={e => e.stopPropagation()}
    >
      {new URL(item.source_url).hostname}
    </a>
  )}
</div>
```

Also, add a tooltip on the image itself to indicate it's clickable:

```typescript
{item.og_image && !imgError ? (
  <a href={item.source_url} target="_blank" rel="noopener noreferrer" className="block w-full h-full">
    <img
      src={item.og_image}
      alt={item.title}
      className="w-full h-full object-cover hover:opacity-90 transition-opacity"
      onError={() => setImgError(true)}
    />
  </a>
) : (
```

- [ ] **Step 2: Verify**

1. In DevTools, throttle network or block an image URL
2. Verify the fallback card appears with the source hostname link
3. Click the hostname link → verify it opens the article in a new tab

- [ ] **Step 3: Commit**

```bash
git add frontend/app/generate/page.tsx
git commit -m "fix: show source URL fallback when screenshot image fails to load"
```

---

## Self-Review

### Spec Coverage Check

| Issue | Task | Coverage |
|-------|------|----------|
| 來源選擇問題 | Task 1 | ✅ Adds Bing + HN sources |
| last30days 資料太少 | Task 2 | ✅ Removes --quick, adds more social sources |
| 換頁狀態消失 | Task 3 | ✅ sessionStorage persistence |
| 截圖頁沒有換新聞 | Task 4 | ✅ screenshot_review step + candidate panel |
| 換新聞沒有 Scroll Bar | Task 4 step 8 | ✅ `max-h-[480px] overflow-y-auto` |
| 截圖問題 | Task 4 step 7 + Task 5 | ✅ onError fallback + source URL link |

### Notes on `getCandidates`

`apiClient.getCandidates(jobId)` calls `/api/news/candidates?job_id={jobId}` which proxies to the Python backend at `http://localhost:8000/api/news/candidates?job_id={jobId}`. This returns news items from the same date/topic that were NOT selected. The Python backend must be running for this to work.

The `frontend/app/api/news/candidates/route.ts` file needs to proxy this correctly. Check it proxies to `:8000` not Supabase. If not, a fix may be needed (out of scope of this plan, check before executing Task 4).

### Type Consistency

- `NewsItem` (from `lib/api.ts`) is used throughout: `{ hook, title, summary, script, source_url, source_name, og_image? }`
- `RawNewsItem` (from `lib/api.ts`): `{ cache_id, title, summary, url, source, source_type?, screenshot_blocked }`
- `ScreenshotCard` uses `NewsItem` (has `og_image`, `source_url`, `hook`)
- `handleSelectCandidate` receives `RawNewsItem` and creates `NewsItem` — types are consistent
