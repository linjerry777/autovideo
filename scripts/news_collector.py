#!/usr/bin/env python3
"""
News Collector (Windows版)
流程：RSS抓新聞 → Groq LLM整理3則 → Playwright截圖 → 存news.json
"""
import io, json, os, re, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from datetime import date
from pathlib import Path
import feedparser
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import argparse as _ap
_parser = _ap.ArgumentParser()
_parser.add_argument("job_key", nargs="?", default=date.today().isoformat())
_parser.add_argument("--topic", default=None)
_parser.add_argument("--dry-run", action="store_true")
_args, _ = _parser.parse_known_args()

_job_key = _args.job_key
TOPIC    = _args.topic   # 使用者指定主題，None 表示 AI 科技
BASE_DIR  = Path(__file__).parent.parent
PIPE_DIR  = BASE_DIR / "pipeline" / _job_key
SHOTS_DIR = PIPE_DIR / "screenshots"
NEWS_FILE = PIPE_DIR / "news.json"

DEFAULT_KEYWORD = "AI artificial intelligence technology"

# ── Claude Proxy 設定 ────────────────────────────────────────────────
_PROXY_URL = os.getenv("CLAUDE_PROXY_URL", "http://localhost:3456")
_LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-6")


def _google_news_url(keyword: str, days: int = 3) -> str:
    from urllib.parse import quote_plus
    q = quote_plus(f"{keyword} when:{days}d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

# ── 工具 ────────────────────────────────────────────────────────────

def call_llm(prompt: str) -> str:
    """呼叫 Claude proxy（OpenAI-compatible），回傳純文字"""
    r = requests.post(
        f"{_PROXY_URL}/v1/chat/completions",
        json={
            "model": _LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
        },
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


import time as _time
from datetime import datetime, timezone


def _hours_since(struct_time) -> float | None:
    """Convert feedparser's published_parsed struct_time → hours since now (UTC)."""
    if not struct_time:
        return None
    try:
        ts = _time.mktime(struct_time)
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


def _load_used_urls() -> set[str]:
    """Scan pipeline/*/job_*/news.json for URLs already turned into videos.

    Returns a set of source_url strings that should be skipped on auto-selection.
    """
    used: set[str] = set()
    pipeline_root = BASE_DIR / "pipeline"
    if not pipeline_root.exists():
        return used
    for job_dir in pipeline_root.glob("*/job_*"):
        news_file = job_dir / "news.json"
        if not news_file.exists():
            continue
        try:
            data = json.loads(news_file.read_text(encoding="utf-8"))
            for item in data.get("items", []):
                for key in ("source_url", "url", "resolved_url"):
                    u = item.get(key)
                    if u:
                        used.add(u)
        except Exception:
            continue
    return used


def fetch_rss_items(keyword: str = DEFAULT_KEYWORD, limit: int = 30) -> list[dict]:
    print(f"  Google News 搜尋：{keyword}")
    for days in [3, 7, 30]:
        url = _google_news_url(keyword, days)
        try:
            feed = feedparser.parse(url)
            items = []
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
            if items:
                if days > 3:
                    print(f"  ⚠️  3天內無結果，改用 {days} 天範圍")
                print(f"  共取得 {len(items)} 則原始新聞")
                return items
        except Exception as e:
            print(f"⚠️  Google News 抓取失敗：{e}")
            return []
    return []


def select_news_with_claude(raw_items: list[dict]) -> list[dict]:
    def _fresh_tag(it):
        h = it.get("freshness_hours")
        if h is None: return "[時效未知]"
        return f"[{h:.0f}h前]" if h < 48 else f"[{h/24:.0f}d前]"

    headlines = "\n".join([
        f"{i+1}. {_fresh_tag(item)} [{item['source']}] {item['title']}\n   URL: {item['url']}\n   {item['summary'][:120]}"
        for i, item in enumerate(raw_items[:40])
    ])

    topic_line = f"主題：{TOPIC}（只選跟這個主題直接相關的新聞）\n\n" if TOPIC else ""
    _kw = TOPIC or DEFAULT_KEYWORD
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
  "bullets": ["金句1（≤15字）", "金句2（≤15字）", "金句3（≤15字）"],
  "script_short": "短版旁白（30-40 字，獨立重寫 — 不是 long 的截斷版，一句話講完核心）",
  "script_long":  "長版旁白（60-80 字，獨立重寫 — 含鋪陳+結論，為長平台而寫）",
  "script":       "= script_long (legacy field, backward compat)",
  "scene_type": "動畫場景（擇一）：fire, race, money, robot, warning, trophy, default",
  "virality_score": 1-10 的整數，預測這則在 Shorts/TikTok 爆的潛力,
  "virality_reason": "一句話說明為什麼給這個分數（例如：『數字衝擊+反差感+時效新鮮』）",
  "emotion": "主導情緒：surprise | anger | joy | curiosity | fear 擇一",
  "source_url": "完整的新聞原始 URL",
  "source_name": "媒體名稱"
}}

hook 必須是 **curiosity-gap 格式**（2026 短影音前 3 秒留存關鍵）：
  1. 疑問式「你知道...嗎？」「為什麼...？」
  2. 反轉式「沒人告訴你...」「原來不是...」
  3. 數字懸念「3 件事改變了...」
  4. 強烈主張「我預測...」「別再做...了」
**禁止直述陳述句**（例：「Token 稅爭議爆發」是標題不是鉤子）。
hook_variants 一樣恰好 3 個，各取不同模板。

bullets 是 3 條**新聞卡片重點**（≤15字/條），放在影片裡當 overlay。
- 每條獨立金句、非半句話
- 延伸 / 數據 / 結論 三個不同面向
- 範例：["營收年增 300%", "三大車廠同步跟進", "2026 全面商用"]

**腳本 TTS 優化（關鍵）**：
- 每 8-15 字加「，」或「…」製造換氣
- 關鍵詞前加「欸」「等等」「真的」語氣詞
- 避免無標點長句（TTS 會念得像機器人）
- 範例（壞）：「Anthropic 推 MCP 想一統 AI 代理生態 Perplexity 卻嗆 Token 稅太貴」
- 範例（好）：「欸，你聽好…Anthropic 想一統 AI 代理，但 Perplexity 直接嗆：Token 稅太貴了！」

新聞列表：
{headlines}

script_short 和 script_long 必須是**獨立重寫**的兩份腳本，不是 Long 的截斷版。
Short 適合 TikTok/IG/FB/Threads（節奏快、1 句關鍵）；
Long 適合 YouTube/X/Pinterest/LinkedIn（有鋪陳、有論點）。

請直接回傳只有 3 則的 JSON 陣列，不要加任何其他文字或 markdown。"""

    print(f"  呼叫 Claude proxy ({_LLM_MODEL}) 整理新聞...")
    raw = call_llm(prompt)

    # 清除可能的 markdown 包裹
    raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw.strip())
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        raw = match.group(0)

    picked = json.loads(raw)
    # Backfill freshness from matched raw items by URL (Claude doesn't know pubDate)
    raw_by_url = {it.get("url", ""): it for it in raw_items}
    for item in picked:
        src = raw_by_url.get(item.get("source_url", ""), {})
        item["freshness_hours"] = src.get("freshness_hours")
        item["freshness_level"] = src.get("freshness_level", "unknown")
    return picked


def screenshot_url(url: str, out_path: Path) -> bool:
    """用 Playwright 截圖新聞來源頁面（桌機寬幅）"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)          # 等 JS 渲染
            page.screenshot(path=str(out_path), full_page=False)
            browser.close()
        return True
    except Exception as e:
        print(f"  ⚠️  截圖失敗 ({url}): {e}")
        return False


# ── 主程式 ───────────────────────────────────────────────────────────

def main():
    PIPE_DIR.mkdir(parents=True, exist_ok=True)
    SHOTS_DIR.mkdir(exist_ok=True)

    keyword = TOPIC or DEFAULT_KEYWORD
    print(f"📡 Google News 搜尋：{keyword}")
    raw_items = fetch_rss_items(keyword)
    if not raw_items:
        print("❌ RSS 抓取全部失敗", file=sys.stderr)
        sys.exit(1)

    # Exclude URLs already made into videos in earlier jobs
    used = _load_used_urls()
    if used:
        before = len(raw_items)
        raw_items = [it for it in raw_items if it.get("url") not in used]
        skipped = before - len(raw_items)
        if skipped:
            print(f"  ⏭️  跳過 {skipped} 則曾經做過的新聞，剩 {len(raw_items)} 則候選")
    if not raw_items:
        print("❌ 過濾後沒有新鮮新聞可選（全部都已做過）", file=sys.stderr)
        sys.exit(1)

    print("🤖 Groq 整理 3 則精選新聞...")
    news_items = select_news_with_claude(raw_items)

    print("📸 Playwright 截圖新聞來源頁面...")
    for i, item in enumerate(news_items, 1):
        url = item.get("source_url", "")
        shot_path = SHOTS_DIR / f"news_{i:02d}.png"
        if url:
            print(f"  [{i}] {url[:60]}...")
            ok = screenshot_url(url, shot_path)
            item["screenshot"] = str(shot_path) if ok else ""
        else:
            item["screenshot"] = ""

    result = {"date": _job_key, "items": news_items}
    NEWS_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✅ 儲存 {len(news_items)} 則新聞 → {NEWS_FILE}")
    for i, item in enumerate(news_items, 1):
        print(f"  {i}. {item['hook']} — {item['title']}")
        print(f"     📸 {item.get('screenshot','（無截圖）')}")


if __name__ == "__main__":
    main()
