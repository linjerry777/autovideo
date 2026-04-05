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
from dotenv import load_dotenv
from groq import Groq

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

# ── Groq 客戶端 ──────────────────────────────────────────────────────
_groq_client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def _google_news_url(keyword: str, days: int = 3) -> str:
    from urllib.parse import quote_plus
    q = quote_plus(f"{keyword} when:{days}d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

# ── 工具 ────────────────────────────────────────────────────────────

def call_groq(prompt: str) -> str:
    """呼叫 Groq API，回傳純文字"""
    resp = _groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=2048,
    )
    return resp.choices[0].message.content.strip()


def fetch_rss_items(keyword: str = DEFAULT_KEYWORD, limit: int = 30) -> list[dict]:
    print(f"  Google News 搜尋：{keyword}")
    for days in [3, 7, 30]:
        url = _google_news_url(keyword, days)
        try:
            feed = feedparser.parse(url)
            items = []
            for entry in feed.entries[:limit]:
                items.append({
                    "title":   entry.get("title", ""),
                    "summary": entry.get("summary", "")[:400],
                    "url":     entry.get("link", ""),
                    "source":  entry.get("source", {}).get("title", "") or feed.feed.get("title", "Google News"),
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
    headlines = "\n".join([
        f"{i+1}. [{item['source']}] {item['title']}\n   URL: {item['url']}\n   {item['summary'][:120]}"
        for i, item in enumerate(raw_items[:40])
    ])

    topic_line = f"主題：{TOPIC}（只選跟這個主題直接相關的新聞）\n\n" if TOPIC else ""
    _kw = TOPIC or DEFAULT_KEYWORD
    prompt = f"""以下是搜尋「{_kw}」得到的新聞列表。請挑出 3 則最具爆點、最能引起共鳴的新聞，適合在短影音（Shorts/Reels/TikTok）分享。

{topic_line}優先選：有數字衝擊感、意外反轉、重大突破、爭議話題的新聞。

每則新聞請用以下 JSON 格式，source_url 必須從列表中完整複製：
{{
  "hook": "開場鉤子（5-8字，製造懸念或衝擊，例如：「這個 AI 嚇到所有人」）",
  "title": "標題（15字以內，中文）",
  "summary": "摘要（40字以內，中文，口語化）",
  "script": "旁白腳本（60字以內，像在跟朋友說話的語氣，第一人稱）",
  "source_url": "完整的新聞原始 URL",
  "source_name": "媒體名稱"
}}

新聞列表：
{headlines}

請直接回傳只有 3 則的 JSON 陣列，不要加任何其他文字或 markdown。"""

    print(f"  呼叫 Groq ({GROQ_MODEL}) 整理新聞...")
    raw = call_groq(prompt)

    # 清除可能的 markdown 包裹
    raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw.strip())

    return json.loads(raw)


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
