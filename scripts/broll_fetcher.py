#!/usr/bin/env python3
"""
B-roll Fetcher
根據新聞標題從 Pexels 搜尋免版稅影片，作為影片背景素材
Pexels License: 免費商用，無需標註來源
https://www.pexels.com/license/
"""
import io, json, os, re, sys, requests
from pathlib import Path
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

TODAY     = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
BASE_DIR  = Path(__file__).parent.parent
PIPE_DIR  = BASE_DIR / "pipeline" / TODAY
NEWS_FILE = PIPE_DIR / "news.json"
BROLL_DIR = PIPE_DIR / "broll"

PEXELS_KEY      = os.getenv("PEXELS_API_KEY", "")
PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"


# ── 關鍵字提取：中文新聞 → 英文 Pexels 搜尋詞 ─────────────────────────────

# 常見主題關鍵字對照
_TOPIC_MAP = [
    (["AI", "人工智慧", "GPT", "Claude", "大模型", "機器學習", "深度學習"],
     "artificial intelligence technology"),
    (["機器人", "Robot"],                       "robot technology"),
    (["科技", "軟體", "程式", "Tech"],          "technology digital"),
    (["台灣", "Taiwan"],                        "Taiwan cityscape"),
    (["中國", "中共"],                           "China city"),
    (["美國", "USA", "美聯儲"],                  "United States city"),
    (["股市", "股票", "市場", "投資"],            "stock market finance"),
    (["加密貨幣", "比特幣", "Bitcoin", "區塊鏈"], "cryptocurrency bitcoin"),
    (["太空", "NASA", "SpaceX", "火箭"],         "space rocket launch"),
    (["氣候", "環境", "地球", "碳"],             "climate nature environment"),
    (["健康", "醫療", "病毒", "疫情"],           "healthcare medical hospital"),
    (["政治", "選舉", "政府"],                   "government politics"),
    (["電動車", "Tesla", "EV"],                  "electric vehicle car"),
    (["手機", "iPhone", "Android", "5G"],        "smartphone mobile technology"),
    (["元宇宙", "VR", "AR", "虛擬"],             "virtual reality metaverse"),
    (["晶片", "半導體", "輝達", "NVIDIA"],        "semiconductor chip technology"),
    (["社群媒體", "TikTok", "YouTube"],          "social media internet"),
    (["戰爭", "軍事", "衝突"],                   "military defense"),
    (["企業", "公司", "CEO"],                    "business corporate office"),
    (["能源", "石油", "電力"],                   "energy power electricity"),
]


def to_english_query(title: str, hook: str) -> str:
    text = f"{title} {hook}"
    for keywords, english in _TOPIC_MAP:
        if any(kw.lower() in text.lower() for kw in keywords):
            return english
    # 嘗試抽出現有英文單字
    eng = re.findall(r'[A-Za-z]{3,}', text)
    if eng:
        return ' '.join(eng[:3])
    return "technology news"


# ── Pexels API ────────────────────────────────────────────────────────────────

def search_pexels(query: str, prefer_portrait: bool = True) -> dict | None:
    headers = {"Authorization": PEXELS_KEY}

    def _search(orientation: str | None) -> list[dict]:
        params = {"query": query, "per_page": 15, "size": "medium"}
        if orientation:
            params["orientation"] = orientation
        try:
            r = requests.get(PEXELS_VIDEO_URL, headers=headers,
                             params=params, timeout=15)
            r.raise_for_status()
            return r.json().get("videos", [])
        except Exception as e:
            print(f"  ⚠️  Pexels 搜尋失敗：{e}")
            return []

    videos = _search("portrait") if prefer_portrait else []
    if not videos:
        videos = _search(None)   # 不限方向
    if not videos:
        return None

    # 挑 4–20 秒的片段，越短越好控制
    best = next(
        (v for v in videos if 4 <= v.get("duration", 0) <= 20),
        videos[0]
    )

    # 挑最佳畫質檔案：portrait > landscape，解析度越高越好
    files = best.get("video_files", [])
    portrait = [f for f in files if f.get("width", 1) < f.get("height", 0)]
    hd       = [f for f in files if f.get("width", 0) >= 1080]
    pool     = portrait or hd or files
    if not pool:
        return None

    pool.sort(key=lambda f: f.get("width", 0) * f.get("height", 0), reverse=True)
    chosen = pool[0]
    return {
        "video_id":  best["id"],
        "pexels_url": best.get("url", ""),
        "download_url": chosen["link"],
        "width":     chosen.get("width"),
        "height":    chosen.get("height"),
        "duration":  best.get("duration"),
        "query":     query,
    }


def download_clip(url: str, out_path: Path) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=120)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return out_path.stat().st_size > 10_000
    except Exception as e:
        print(f"  ⚠️  下載失敗：{e}")
        return False


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    if not NEWS_FILE.exists():
        print(f"❌ 找不到新聞檔：{NEWS_FILE}", file=sys.stderr)
        sys.exit(1)
    if not PEXELS_KEY:
        print("❌ 請在 .env 設定 PEXELS_API_KEY（免費申請：https://www.pexels.com/api/）",
              file=sys.stderr)
        sys.exit(1)

    BROLL_DIR.mkdir(parents=True, exist_ok=True)
    data  = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data["items"]
    failed = 0

    print(f"🎬 抓取 {len(items)} 則 B-roll（Pexels）...")
    for i, item in enumerate(items, 1):
        out  = BROLL_DIR / f"broll_{i:02d}.mp4"
        meta_f = BROLL_DIR / f"broll_{i:02d}.json"

        if out.exists() and meta_f.exists():
            print(f"  [{i}] 已存在，跳過")
            continue

        query = to_english_query(item.get("title", ""), item.get("hook", ""))
        print(f"  [{i}] 搜尋：「{query}」（來自：{item.get('title','')[:30]}）")

        meta = search_pexels(query)
        if not meta:
            print(f"      ↳ 找不到，嘗試通用備案 'technology background'...")
            meta = search_pexels("technology background", prefer_portrait=False)

        if not meta:
            print(f"  [{i}] ❌ 無法取得 B-roll → 將 fallback 到截圖模式")
            failed += 1
            continue

        w, h = meta.get("width", 0), meta.get("height", 0)
        dur  = meta.get("duration", 0)
        print(f"      ↳ {w}x{h} {dur}s，下載中...")

        ok = download_clip(meta["download_url"], out)
        if ok:
            meta_f.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  [{i}] ✅ {out.name} ({out.stat().st_size // 1024}KB)")
        else:
            failed += 1
            print(f"  [{i}] ❌ 下載失敗 → fallback 到截圖")

    if failed:
        print(f"\n⚠️  {failed} 則無法取得 B-roll，video_composer 將自動 fallback 到截圖/佔位圖")
    print(f"✅ B-roll 步驟完成")


if __name__ == "__main__":
    main()
