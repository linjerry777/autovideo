#!/usr/bin/env python3
"""
截圖 ai_lesson 課程網站的三個 section，供 AutoVideo 使用
"""
from playwright.sync_api import sync_playwright
from pathlib import Path
import time

SHOTS_DIR = Path(__file__).parent / "pipeline/2026-03-28/job_course_promo/screenshots"
SHOTS_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://localhost:3001"

SHOTS = [
    # (filename, scroll_y, description)
    ("news_01.png", 0,    "Hero section"),
    ("news_02.png", 650,  "Problems section"),
    ("news_03.png", 2200, "Pricing section"),
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1200, "height": 800})

    print(f"載入 {BASE_URL}...")
    page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    for filename, scroll_y, desc in SHOTS:
        out = SHOTS_DIR / filename
        print(f"截圖：{desc} (scroll={scroll_y})")
        page.evaluate(f"window.scrollTo(0, {scroll_y})")
        time.sleep(0.8)
        page.screenshot(path=str(out), full_page=False)
        size = out.stat().st_size
        print(f"  OK {filename} ({size//1024}KB)")

    browser.close()

print(f"\nDone! {SHOTS_DIR}")
