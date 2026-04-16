"""
web/routes/news.py — 多來源新聞/內容聚合 + 快取
"""
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Query

from web.db import (save_news_cache, get_cached_news, get_job_candidates,
                    get_cache_item, mark_news_blocked)

router = APIRouter(prefix="/api/news")
log = logging.getLogger("news")

DEFAULT_KEYWORD = "AI 人工智慧 科技"

LANG_CONFIG = {
    "zh-TW": {"hl": "zh-TW", "gl": "TW",  "ceid": "TW:zh-Hant"},
    "zh-CN": {"hl": "zh-CN", "gl": "CN",  "ceid": "CN:zh-Hans"},
    "en":    {"hl": "en-US", "gl": "US",  "ceid": "US:en"},
}

_LAST30DAYS_SCRIPT = (
    Path.home() / ".claude/plugins/cache/last30days-skill/last30days/3.0.0/scripts/last30days.py"
)
_SOCIAL_LABELS = {
    "reddit":     "Reddit",
    "hackernews": "Hacker News",
    "youtube":    "YouTube",
    "tiktok":     "TikTok",
    "instagram":  "Instagram",
    "x":          "X / Twitter",
    "bluesky":    "Bluesky",
    "threads":    "Threads",
}

# 所有支援的來源定義
ALL_SOURCES = {
    "google":       {"label": "Google News",        "icon": "🔍", "default": True,  "group": "news"},
    "bing":         {"label": "Bing News",          "icon": "🔎", "default": True,  "group": "news"},
    "bilibili":     {"label": "Bilibili 熱榜",      "icon": "📺", "default": True,  "group": "zh"},
    "zhihu":        {"label": "知乎熱搜",            "icon": "💬", "default": True,  "group": "zh"},
    "ptt":          {"label": "PTT 八卦/熱門",       "icon": "🏛️", "default": False, "group": "zh"},
    "dcard":        {"label": "Dcard 熱門",          "icon": "🃏", "default": False, "group": "zh"},
    "reddit":       {"label": "Reddit 熱門",         "icon": "🤖", "default": False, "group": "en"},
    "youtube_tw":   {"label": "YouTube 熱門 TW",     "icon": "▶️", "default": False, "group": "en"},
    "youtube_us":   {"label": "YouTube Trending US", "icon": "▶️", "default": False, "group": "en"},
    "hackernews":   {"label": "Hacker News",         "icon": "🦊", "default": False, "group": "en"},
    "last30days":   {"label": "Social (Reddit·HN)",  "icon": "🌐", "default": False, "group": "en"},
    "v2ex":         {"label": "V2EX",               "icon": "💻", "default": False, "group": "zh"},
    "36kr":         {"label": "36氪",               "icon": "📰", "default": False, "group": "zh"},
    "sspai":        {"label": "少數派",             "icon": "✏️", "default": False, "group": "zh"},
    "ithome":       {"label": "IT之家",             "icon": "🏠", "default": False, "group": "zh"},
    "huxiu":        {"label": "虎嗅",               "icon": "🐯", "default": False, "group": "zh"},
}

DEFAULT_SOURCES = [k for k, v in ALL_SOURCES.items() if v["default"]]

# ── 各來源 Fetcher ─────────────────────────────────────────────────────────────

def _fetch_google(keyword: str, lang: str = "zh-TW", limit: int = 25) -> list[dict]:
    import feedparser
    cfg = LANG_CONFIG.get(lang, LANG_CONFIG["zh-TW"])
    for days in [3, 7, 30]:
        url = (f"https://news.google.com/rss/search?q={quote_plus(keyword + f' when:{days}d')}"
               f"&hl={cfg['hl']}&gl={cfg['gl']}&ceid={cfg['ceid']}")
        try:
            feed = feedparser.parse(url)
            items = [
                {
                    "title":       e.get("title", ""),
                    "summary":     e.get("summary", "")[:300],
                    "url":         e.get("link", ""),
                    "source":      e.get("source", {}).get("title", "") or feed.feed.get("title", "Google News"),
                    "source_type": "google",
                }
                for e in feed.entries[:limit] if e.get("title")
            ]
            if items:
                return items
        except Exception as e:
            log.warning(f"Google News 失敗: {e}")
    return []


def _fetch_bing(keyword: str, lang: str = "zh-TW", limit: int = 20) -> list[dict]:
    import feedparser
    lang_map = {"zh-TW": "zh-tw", "zh-CN": "zh-cn", "en": "en-us"}
    setlang = lang_map.get(lang, "zh-tw")
    url = f"https://www.bing.com/news/search?q={quote_plus(keyword)}&setlang={setlang}&format=RSS"
    try:
        feed = feedparser.parse(url)
        return [
            {
                "title":       e.get("title", ""),
                "summary":     e.get("summary", "")[:300],
                "url":         e.get("link", ""),
                "source":      f"Bing · {e.get('source', {}).get('title', '')}",
                "source_type": "bing",
            }
            for e in feed.entries[:limit] if e.get("title")
        ]
    except Exception as e:
        log.warning(f"Bing News 失敗: {e}")
        return []


def _fetch_bilibili(keyword: str = None, limit: int = 20) -> list[dict]:
    import requests
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
        }
        r = requests.get(
            "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all",
            headers=headers, timeout=10
        )
        videos = r.json().get("data", {}).get("list", [])
        items = []
        for v in videos[:limit * 2]:
            title = v.get("title", "")
            if keyword:
                kws = keyword.lower().split()
                if not any(kw in title.lower() for kw in kws):
                    continue
            items.append({
                "title":       title,
                "summary":     (v.get("desc") or "")[:300] or f"▶ {v.get('stat', {}).get('view', 0):,} 次觀看",
                "url":         f"https://www.bilibili.com/video/{v.get('bvid', '')}",
                "source":      f"Bilibili · {v.get('owner', {}).get('name', '')}",
                "source_type": "bilibili",
            })
            if len(items) >= limit:
                break
        # 若 keyword 過濾後太少，不過濾
        if len(items) < 5 and keyword:
            return _fetch_bilibili(None, limit)
        return items
    except Exception as e:
        log.warning(f"Bilibili 失敗: {e}")
        return []


def _fetch_zhihu(keyword: str = None, limit: int = 20) -> list[dict]:
    import requests
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "x-api-version": "3.0.91",
            "x-app-za": "OS=Web",
        }
        r = requests.get(
            "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50",
            headers=headers, timeout=10
        )
        items = []
        for item in r.json().get("data", [])[:limit * 2]:
            target = item.get("target", {})
            title = (target.get("title") or
                     target.get("question", {}).get("name") or
                     target.get("phrase", ""))
            if not title:
                continue
            if keyword:
                kws = keyword.lower().split()
                if not any(kw in title.lower() for kw in kws):
                    continue
            qid = target.get("id") or target.get("question", {}).get("id", "")
            items.append({
                "title":       title,
                "summary":     (target.get("excerpt") or "")[:300],
                "url":         f"https://www.zhihu.com/question/{qid}" if qid else "https://www.zhihu.com/hot",
                "source":      "知乎熱搜",
                "source_type": "zhihu",
            })
            if len(items) >= limit:
                break
        if len(items) < 5 and keyword:
            return _fetch_zhihu(None, limit)
        return items
    except Exception as e:
        log.warning(f"知乎失敗: {e}")
        return []


def _fetch_hackernews(keyword: str = None, limit: int = 20) -> list[dict]:
    import requests
    try:
        if keyword:
            url = f"https://hn.algolia.com/api/v1/search?query={quote_plus(keyword)}&tags=story&hitsPerPage={limit}"
        else:
            url = f"https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}"
        hits = requests.get(url, timeout=10).json().get("hits", [])
        return [
            {
                "title":       h.get("title", ""),
                "summary":     f"🔥 {h.get('points', 0)} pts · {h.get('num_comments', 0)} 留言",
                "url":         h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "source":      "Hacker News",
                "source_type": "hackernews",
            }
            for h in hits if h.get("title")
        ]
    except Exception as e:
        log.warning(f"HN 失敗: {e}")
        return []


def _fetch_reddit_trending(keyword: str = None, limit: int = 25) -> list[dict]:
    """Fetch Reddit r/popular/hot — no API key needed."""
    import requests
    try:
        headers = {"User-Agent": "AutoVideo/1.0 news-aggregator"}
        r = requests.get(
            "https://www.reddit.com/r/popular/hot.json?limit=50",
            headers=headers, timeout=12,
        )
        r.raise_for_status()
        posts = r.json().get("data", {}).get("children", [])
        items = []
        for p in posts:
            d = p.get("data", {})
            title = d.get("title", "")
            if not title:
                continue
            if keyword:
                kws = keyword.lower().split()
                if not any(kw in title.lower() for kw in kws):
                    continue
            score    = d.get("score", 0)
            comments = d.get("num_comments", 0)
            sub      = d.get("subreddit", "")
            link     = d.get("url") or f"https://www.reddit.com{d.get('permalink','')}"
            items.append({
                "title":       title,
                "summary":     f"🔥 {score:,} upvotes · {comments:,} comments · r/{sub}",
                "url":         link,
                "source":      f"Reddit · r/{sub}",
                "source_type": "reddit",
            })
            if len(items) >= limit:
                break
        # 若 keyword 過濾後太少，直接回傳全部熱門
        if len(items) < 5 and keyword:
            return _fetch_reddit_trending(None, limit)
        return items
    except Exception as e:
        log.warning(f"Reddit trending 失敗: {e}")
        return []


def _fetch_youtube_trending(keyword: str = None, region: str = "TW", limit: int = 25) -> list[dict]:
    """Fetch YouTube trending via Data API v3. Requires YOUTUBE_API_KEY env var or DB setting."""
    import os, requests
    # DB setting takes priority over .env
    try:
        from web.db import get_setting as _gs
        api_key = _gs("youtube_api_key", "") or os.getenv("YOUTUBE_API_KEY", "")
    except Exception:
        api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        log.info(f"YouTube trending ({region}): YOUTUBE_API_KEY not set, skipping")
        return []
    try:
        params = {
            "part":       "snippet,statistics",
            "chart":      "mostPopular",
            "regionCode": region,
            "maxResults": limit,
            "key":        api_key,
        }
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params=params, timeout=12,
        )
        r.raise_for_status()
        items = []
        for v in r.json().get("items", []):
            snippet = v.get("snippet", {})
            stats   = v.get("statistics", {})
            title   = snippet.get("title", "")
            if not title:
                continue
            if keyword:
                kws = keyword.lower().split()
                if not any(kw in title.lower() for kw in kws):
                    continue
            vid      = v.get("id", "")
            views    = int(stats.get("viewCount",   0))
            comments = int(stats.get("commentCount", 0))
            channel  = snippet.get("channelTitle", "")
            items.append({
                "title":       title,
                "summary":     f"▶ {views:,} views · {comments:,} comments · {channel}",
                "url":         f"https://www.youtube.com/watch?v={vid}",
                "source":      f"YouTube Trending · {region}",
                "source_type": f"youtube_{region.lower()}",
            })
        if len(items) < 5 and keyword:
            return _fetch_youtube_trending(None, region, limit)
        return items
    except Exception as e:
        log.warning(f"YouTube trending ({region}) 失敗: {e}")
        return []


def _fetch_ptt(keyword: str = None, limit: int = 25) -> list[dict]:
    """Fetch PTT 八卦板 hot posts via web scraping."""
    import requests
    from html.parser import HTMLParser

    class _PttParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.items = []
            self._in_title = False
            self._cur = {}

        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            cls = d.get("class", "")
            if tag == "div" and "r-ent" in cls:
                self._cur = {}
            if tag == "div" and cls == "title":
                self._in_title = True
            if tag == "a" and self._in_title and d.get("href", "").startswith("/bbs/"):
                self._cur["href"] = d["href"]
            if tag == "div" and cls == "nrec":
                self._in_nrec = True

        def handle_data(self, data):
            if self._in_title and data.strip():
                self._cur.setdefault("title", data.strip())

        def handle_endtag(self, tag):
            if tag == "div" and self._in_title:
                self._in_title = False
                if self._cur.get("href") and self._cur.get("title"):
                    self.items.append(dict(self._cur))

    try:
        session = requests.Session()
        session.cookies.set("over18", "1", domain="www.ptt.cc")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Referer": "https://www.ptt.cc/bbs/Gossiping/index.html",
        }
        r = session.get("https://www.ptt.cc/bbs/Gossiping/index.html",
                        headers=headers, timeout=12)
        r.raise_for_status()
        parser = _PttParser()
        parser.feed(r.text)
        raw = parser.items
        items = []
        for p in raw:
            title = p.get("title", "")
            if not title or title.startswith("[公告]"):
                continue
            if keyword:
                kws = keyword.lower().split()
                if not any(kw in title for kw in kws):
                    continue
            items.append({
                "title":       title,
                "summary":     "PTT 八卦板熱門文章",
                "url":         f"https://www.ptt.cc{p.get('href','')}",
                "source":      "PTT 八卦板",
                "source_type": "ptt",
            })
            if len(items) >= limit:
                break
        if len(items) < 3 and keyword:
            return _fetch_ptt(None, limit)
        return items
    except Exception as e:
        log.warning(f"PTT 失敗: {e}")
        return []


def _fetch_dcard(keyword: str = None, limit: int = 25) -> list[dict]:
    """Fetch Dcard popular posts via RSS."""
    import feedparser
    try:
        # Dcard RSS: all forums popular feed
        feed = feedparser.parse("https://www.dcard.tw/f.rss")
        items = []
        for e in feed.entries:
            title = e.get("title", "")
            if not title:
                continue
            if keyword:
                kws = keyword.lower().split()
                if not any(kw in title.lower() for kw in kws):
                    continue
            link  = e.get("link", "")
            items.append({
                "title":       title,
                "summary":     e.get("summary", "")[:200],
                "url":         link,
                "source":      "Dcard",
                "source_type": "dcard",
            })
            if len(items) >= limit:
                break
        if len(items) < 3 and keyword:
            return _fetch_dcard(None, limit)
        return items
    except Exception as e:
        log.warning(f"Dcard 失敗: {e}")
        return []


def _fetch_last30days(keyword: str, limit: int = 20) -> list[dict]:
    if not _LAST30DAYS_SCRIPT.exists():
        log.warning("last30days: script not found, skipping")
        return []
    try:
        import json as _json
        result = subprocess.run(
            [sys.executable, str(_LAST30DAYS_SCRIPT), keyword,
             "--emit", "json", "--search", "reddit,hackernews,x,youtube"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", timeout=25,
        )
        if result.returncode != 0:
            log.warning("last30days: non-zero exit")
            return []
        data = _json.loads(result.stdout)
        items = []
        for c in data.get("ranked_candidates", [])[:limit]:
            src = c.get("source", "")
            url = c.get("url", "") or next(iter(c.get("candidate_ids", [])), "")
            title = c.get("title", "")
            if not title or not url:
                continue
            items.append({
                "title":       title,
                "summary":     c.get("snippet", "")[:300],
                "url":         url,
                "source":      _SOCIAL_LABELS.get(src, src.capitalize()),
                "source_type": src,
            })
        log.info(f"last30days: {len(items)} items for '{keyword}'")
        return items
    except subprocess.TimeoutExpired:
        log.warning("last30days: timeout")
        return []
    except Exception as e:
        log.warning(f"last30days: {e}")
        return []


def _fetch_rss_source(source_id: str, rss_url: str, keyword: str = None, limit: int = 15) -> list[dict]:
    import feedparser
    try:
        feed = feedparser.parse(rss_url)
        source_name = ALL_SOURCES.get(source_id, {}).get("label", source_id)
        items = []
        for e in feed.entries[:limit * 2]:
            title = e.get("title", "")
            if not title:
                continue
            if keyword:
                kws = keyword.lower().split()
                if not any(kw in title.lower() for kw in kws):
                    continue
            items.append({
                "title":       title,
                "summary":     e.get("summary", "")[:300],
                "url":         e.get("link", ""),
                "source":      source_name,
                "source_type": source_id,
            })
            if len(items) >= limit:
                break
        if len(items) < 3 and keyword:
            return _fetch_rss_source(source_id, rss_url, None, limit)
        return items
    except Exception as e:
        log.warning(f"{source_id} RSS 失敗: {e}")
        return []


CURATED_RSS = {
    "v2ex":  "https://www.v2ex.com/index.xml",
    "36kr":  "https://36kr.com/feed",
    "sspai": "https://sspai.com/feed",
    "ithome":"https://www.ithome.com/rss/",
    "huxiu": "https://www.huxiu.com/rss/",
}

# ── 主要聚合函數 ───────────────────────────────────────────────────────────────

def _fetch_all(keyword: str, lang: str, sources: list[str], limit_per: int = 20) -> list[dict]:
    """並行抓取所有選定來源，合併去重"""
    tasks = {}

    def add(name, fn):
        if name in sources:
            tasks[name] = fn

    add("google",      lambda: _fetch_google(keyword, lang, limit_per))
    add("bing",        lambda: _fetch_bing(keyword, lang, limit_per))
    add("bilibili",    lambda: _fetch_bilibili(keyword, limit_per))
    add("zhihu",       lambda: _fetch_zhihu(keyword, limit_per))
    add("hackernews",  lambda: _fetch_hackernews(keyword, limit_per))
    add("last30days",  lambda: _fetch_last30days(keyword, limit_per))
    add("reddit",      lambda: _fetch_reddit_trending(keyword, limit_per))
    add("youtube_tw",  lambda: _fetch_youtube_trending(keyword, "TW", limit_per))
    add("youtube_us",  lambda: _fetch_youtube_trending(keyword, "US", limit_per))
    add("ptt",         lambda: _fetch_ptt(keyword, limit_per))
    add("dcard",       lambda: _fetch_dcard(keyword, limit_per))
    for sid, rss_url in CURATED_RSS.items():
        add(sid, lambda u=rss_url, s=sid: _fetch_rss_source(s, u, keyword, limit_per))

    results = []
    seen_urls = set()

    with ThreadPoolExecutor(max_workers=6) as ex:
        future_map = {ex.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                items = future.result()
                for item in items:
                    url = item.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        results.append(item)
            except Exception as e:
                log.warning(f"來源 {name} 失敗: {e}")

    return results


# ── API Endpoints ──────────────────────────────────────────────────────────────

@router.get("/sources")
def list_sources():
    """回傳所有支援的來源清單"""
    return {
        "sources": [
            {"id": k, **v}
            for k, v in ALL_SOURCES.items()
        ],
        "defaults": DEFAULT_SOURCES,
    }


@router.get("/fetch")
def fetch_news(
    topic: str = Query(None),
    lang: str = Query("zh-TW"),
    sources: str = Query(None),  # 逗號分隔，e.g. "google,bilibili,zhihu"
    force: bool = Query(False),  # True = skip cache
):
    if lang not in LANG_CONFIG:
        lang = "zh-TW"

    selected_sources = sources.split(",") if sources else DEFAULT_SOURCES
    selected_sources = [s.strip() for s in selected_sources if s.strip() in ALL_SOURCES]
    if not selected_sources:
        selected_sources = DEFAULT_SOURCES

    # Trending-only sources (reddit/youtube/ptt) don't need a keyword —
    # use empty string so fetchers return full hot feed without filtering.
    TRENDING_SOURCES = {"reddit", "youtube_tw", "youtube_us", "ptt", "dcard",
                        "bilibili", "zhihu"}
    all_trending = all(s in TRENDING_SOURCES for s in selected_sources)
    keyword = topic or ("" if all_trending else DEFAULT_KEYWORD)

    today = datetime.now(timezone.utc).date().isoformat()
    cache_key = f"{keyword}|{'|'.join(sorted(selected_sources))}"

    # 檢查今日快取（同 keyword + 相同來源組合）；force=true 跳過
    cached = None if force else get_cached_news(cache_key, lang, today)
    if cached:
        return {
            "keyword":    keyword,
            "lang":       lang,
            "sources":    selected_sources,
            "from_cache": True,
            "items": [
                {
                    "cache_id":           r["id"],
                    "title":              r["title"],
                    "summary":            r["summary"],
                    "url":                r["url"],
                    "source":             r["source"],
                    "source_type":        r["source_type"] if "source_type" in r.keys() else "google",
                    "screenshot_blocked": bool(r["screenshot_blocked"]),
                }
                for r in cached
            ],
        }

    # 並行抓取
    raw = _fetch_all(keyword, lang, selected_sources)
    if not raw:
        raise HTTPException(500, "所有來源均未找到相關內容，請嘗試其他關鍵字")

    ids = save_news_cache(cache_key, lang, raw)

    return {
        "keyword":    keyword,
        "lang":       lang,
        "sources":    selected_sources,
        "from_cache": False,
        "items": [
            {
                "cache_id":           cid,
                "title":              item["title"],
                "summary":            item["summary"],
                "url":                item["url"],
                "source":             item["source"],
                "source_type":        item.get("source_type", "google"),
                "screenshot_blocked": False,
            }
            for cid, item in zip(ids, raw)
        ],
    }


@router.get("/candidates")
def news_candidates(job_id: int = Query(...)):
    candidates = get_job_candidates(job_id)
    return {
        "items": [
            {
                "cache_id":           r["id"],
                "title":              r["title"],
                "summary":            r["summary"],
                "url":                r["url"],
                "source":             r["source"],
                "source_type":        r["source_type"] if "source_type" in r.keys() else "google",
                "screenshot_blocked": bool(r["screenshot_blocked"]),
            }
            for r in candidates
        ]
    }


@router.post("/cache/{cache_id}/block")
def block_cache_item(cache_id: int):
    item = get_cache_item(cache_id)
    if not item:
        raise HTTPException(404, "Cache item not found")
    mark_news_blocked(cache_id)
    return {"ok": True}
