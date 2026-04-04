#!/usr/bin/env python3
"""
generate_course_videos.py
一次生成 Claude Code 課程全部 7 章影片
每章：截圖 -> news.json -> audio -> video
"""
import json, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR   = Path(__file__).parent
SITE_URL   = "http://localhost:3001"
JOB_PREFIX = "2026-03-28/ch"

# ──────────────────────────────────────────────────────────────────────
# 每章的設定：3 個 item，每個 item 有 hook / script / url / scroll_y
# ──────────────────────────────────────────────────────────────────────
CHAPTERS = [
    {
        "id": "01",
        "items": [
            {
                "hook": "一句話，整個網站生出來",
                "script": "我跟Claude Code說：幫我建一個賣線上課程的網站，要有Google登入和Stripe付款。然後它就開始動了。",
                "url": SITE_URL, "scroll": 0,
            },
            {
                "hook": "Hero、Pain Points、定價，全部",
                "script": "Navbar、Hero section、痛點卡片、課程大綱、學員回饋、比較表、FAQ、頁腳，一個下午全部生完。你說這是Vibe Coding也好，反正它跑得動。",
                "url": SITE_URL, "scroll": 550,
            },
            {
                "hook": "重點是你要會描述需求",
                "script": "AI寫出什麼，取決於你說了什麼。這章教你怎麼把一個模糊的想法，拆解成Claude Code能直接動手的需求。這才是真正的技術。",
                "url": SITE_URL, "scroll": 1300,
            },
        ],
    },
    {
        "id": "02",
        "items": [
            {
                "hook": "Google登入，理論三行",
                "script": "Supabase文件說，Google OAuth三行程式就搞定。對，三行。然後我花了兩個小時在除錯。",
                "url": f"{SITE_URL}/login", "scroll": 0,
            },
            {
                "hook": "code跑到首頁不跑callback",
                "script": "登入完成，OAuth的code跑去了首頁，不是callback route。原因是Supabase的redirect URL白名單沒加對。你一定也會踩。",
                "url": f"{SITE_URL}/login", "scroll": 0,
            },
            {
                "hook": "這章把這些坑全部記錄下來",
                "script": "Site URL設定、redirect URL白名單、callback route的origin問題，全部在這章。下次你串OAuth，30分鐘搞定。",
                "url": SITE_URL, "scroll": 0,
            },
        ],
    },
    {
        "id": "03",
        "items": [
            {
                "hook": "echo傳API key給Vercel",
                "script": "我用echo把Stripe的secret key傳給vercel env add。然後Stripe回傳500，說API key無效。",
                "url": SITE_URL, "scroll": 0,
            },
            {
                "hook": "key的結尾有個\\n",
                "script": "原因是echo在Windows會在字串結尾加換行符。Stripe拿到的key是sk_test_xxx加一個看不見的換行，直接拒收。",
                "url": SITE_URL, "scroll": 550,
            },
            {
                "hook": "環境變數地獄的正確解法",
                "script": "這種問題沒有文件會教你。這章紀錄了echo vs printf的差異、.env.local的格式問題、怎麼用debug route確認env有沒有正確帶入。",
                "url": SITE_URL, "scroll": 1300,
            },
        ],
    },
    {
        "id": "04",
        "items": [
            {
                "hook": "Stripe串接，沙盒先測",
                "script": "付款功能不能直接上線測。Stripe有沙盒環境，用測試卡4242 4242 4242 4242，打多少都不會真的扣錢。",
                "url": SITE_URL, "scroll": 2200,
            },
            {
                "hook": "webhook是最容易漏的一塊",
                "script": "Stripe付款成功，但你的資料庫沒更新。原因是webhook沒設好。這章完整講webhook endpoint的建立、驗證、purchases資料表的寫入。",
                "url": SITE_URL, "scroll": 2200,
            },
            {
                "hook": "測試卡付一次，全流程跑通",
                "script": "付款完成跳success頁、webhook打進來、purchases表寫入、再次點購課自動跳dashboard。這章帶你把整個收款流程驗收完畢。",
                "url": SITE_URL, "scroll": 1800,
            },
        ],
    },
    {
        "id": "05",
        "items": [
            {
                "hook": "git push，網站自動更新",
                "script": "改完code，git add，git commit，git push。Vercel自動偵測到main branch有新commit，三十秒內重新部署，新版上線。",
                "url": SITE_URL, "scroll": 0,
            },
            {
                "hook": "但URL一直在換",
                "script": "每次部署Vercel都給一個新的URL，ailesson加一串亂碼。你要找固定的alias，讓同一個網址永遠指向最新版本。",
                "url": SITE_URL, "scroll": 0,
            },
            {
                "hook": "CI/CD：commit到上線不到一分鐘",
                "script": "git init、GitHub repo建立、Vercel連動、固定alias設定，這章完整走一遍。以後你任何專案要部署，套這個流程就對了。",
                "url": SITE_URL, "scroll": 550,
            },
        ],
    },
    {
        "id": "06",
        "items": [
            {
                "hook": "500 on /api/checkout",
                "script": "登入成功，點購課，白畫面，500 error。Vercel log什麼都沒顯示。這種debug才是真實開發的日常。",
                "url": SITE_URL, "scroll": 0,
            },
            {
                "hook": "debug route救了我",
                "script": "我建了一個/api/debug，直接回傳當前的user session、env var狀態、Supabase連線狀態。三十秒定位問題。這個習慣，每個專案都要有。",
                "url": SITE_URL, "scroll": 0,
            },
            {
                "hook": "session消失、CORS、cookie不帶",
                "script": "這章整理了這個專案踩過的所有坑：session為什麼在線上不見了、CORS怎麼設、Supabase cookie在不同domain的行為。一章全看完，下次不用再踩。",
                "url": SITE_URL, "scroll": 1300,
            },
        ],
    },
    {
        "id": "07",
        "items": [
            {
                "hook": "你學到的不只是這個網站",
                "script": "這整套流程不是只能做課程網站。SaaS工具、個人作品集、接案的產品原型，架構都是一樣的。學的是方法，不是模板。",
                "url": SITE_URL, "scroll": 0,
            },
            {
                "hook": "把你的想法填進去",
                "script": "Landing Page換文案，Supabase換資料表，Stripe換你的商品。其他不動。你下一個專案，從這個模板開始，省掉八成的架設時間。",
                "url": SITE_URL, "scroll": 2200,
            },
            {
                "hook": "NT$2,640，比他們便宜一成",
                "script": "比市面上同類課程便宜一成。因為我不需要分三堂課，觀念一堂、實作一堂、部署一堂，每堂三千。你現在看到的這個網站，就是全部的課程內容。",
                "url": SITE_URL, "scroll": 2200,
            },
        ],
    },
]

# ──────────────────────────────────────────────────────────────────────
# 截圖
# ──────────────────────────────────────────────────────────────────────
def take_screenshots(chapter: dict):
    job_dir   = BASE_DIR / "pipeline" / f"{JOB_PREFIX}{chapter['id']}"
    shots_dir = job_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    # 如果已存在就跳過
    existing = list(shots_dir.glob("news_*.png"))
    if len(existing) >= len(chapter["items"]):
        print(f"  截圖已存在，跳過")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 800})

        for i, item in enumerate(chapter["items"], 1):
            out = shots_dir / f"news_{i:02d}.png"
            if out.exists():
                continue
            page.goto(item["url"], wait_until="networkidle", timeout=30000)
            time.sleep(1.5)
            page.evaluate(f"window.scrollTo(0, {item['scroll']})")
            time.sleep(0.8)
            page.screenshot(path=str(out))
            kb = out.stat().st_size // 1024
            print(f"  news_{i:02d}.png ({kb}KB)")

        browser.close()

# ──────────────────────────────────────────────────────────────────────
# 建 news.json
# ──────────────────────────────────────────────────────────────────────
def write_news_json(chapter: dict):
    job_dir  = BASE_DIR / "pipeline" / f"{JOB_PREFIX}{chapter['id']}"
    job_dir.mkdir(parents=True, exist_ok=True)
    news_file = job_dir / "news.json"

    data = {
        "date": f"2026-03-28/ch{chapter['id']}",
        "items": [
            {
                "hook":        item["hook"],
                "title":       item["hook"],
                "summary":     item["script"],
                "script":      item["script"],
                "source_url":  "",
                "source_name": f"ch{chapter['id']}",
            }
            for item in chapter["items"]
        ],
    }
    news_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  news.json 寫入完成")

# ──────────────────────────────────────────────────────────────────────
# 跑 audio + video
# ──────────────────────────────────────────────────────────────────────
def run_pipeline(chapter_id: str):
    job_key = f"2026-03-28/ch{chapter_id}"
    scripts_dir = BASE_DIR / "scripts"

    print(f"  [audio] 生成語音...")
    r = subprocess.run(
        [sys.executable, str(scripts_dir / "audio_generator.py"), job_key],
        cwd=BASE_DIR, capture_output=False, text=True
    )
    if r.returncode != 0:
        print(f"  audio FAILED")
        return False

    print(f"  [video] 合成影片...")
    r = subprocess.run(
        [sys.executable, str(scripts_dir / "video_composer.py"), job_key],
        cwd=BASE_DIR, capture_output=False, text=True
    )
    if r.returncode != 0:
        print(f"  video FAILED")
        return False

    out = BASE_DIR / "pipeline" / job_key / "output.mp4"
    if out.exists():
        mb = out.stat().st_size / 1024 / 1024
        print(f"  output.mp4 ({mb:.1f}MB)")
        return True
    return False

# ──────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────
def main():
    # 支援指定章節：python generate_course_videos.py 01 03 07
    targets = sys.argv[1:] if len(sys.argv) > 1 else [ch["id"] for ch in CHAPTERS]

    for chapter in CHAPTERS:
        if chapter["id"] not in targets:
            continue

        print(f"\n{'='*50}")
        print(f"Chapter {chapter['id']}: {chapter['items'][0]['hook']}")
        print(f"{'='*50}")

        write_news_json(chapter)
        print("截圖...")
        take_screenshots(chapter)
        success = run_pipeline(chapter["id"])
        if success:
            print(f"Chapter {chapter['id']} DONE")
        else:
            print(f"Chapter {chapter['id']} FAILED")

    print("\n全部完成！")
    print("影片位置：")
    for chapter in CHAPTERS:
        if chapter["id"] not in targets:
            continue
        p = BASE_DIR / "pipeline" / f"2026-03-28/ch{chapter['id']}" / "output.mp4"
        status = "OK" if p.exists() else "missing"
        print(f"  ch{chapter['id']}: {p} [{status}]")

if __name__ == "__main__":
    main()
