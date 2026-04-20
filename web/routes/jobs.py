import json as _json, os, shutil, threading
import base64 as _base64
from datetime import date as date_cls
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.db import (create_job, get_job, list_jobs, get_stats,
                    get_setting, update_job, get_cache_item,
                    mark_news_blocked_by_url, mark_news_blocked)
from web import job_runner

BASE_DIR = Path(__file__).parent.parent.parent

router = APIRouter(prefix="/api")


def _take_screenshot(url: str, shot_path: Path) -> bool:
    """用 Playwright 截圖，成功回傳 True；失敗回傳 False"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                viewport={"width": 1200, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()
            page.route("**/*.{woff,woff2,ttf,otf}", lambda r: r.abort())
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2000)
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(shot_path), full_page=False)
            browser.close()
        return True
    except Exception:
        return False


class TriggerRequest(BaseModel):
    date:               str | None        = None
    topic:              str | None        = None
    lang:               str               = "zh-TW"
    platforms:          list[str]         = ["youtube", "instagram"]
    dry_run:            bool              = False
    selected_news:      list[dict] | None = None   # 前端預選的新聞，有則跳過爬蟲
    selected_cache_ids: list[int] | None  = None   # 對應快取 ID
    account_profile:    str | None        = None   # 覆蓋預設 Upload-Post profile
    strategy:           str | None        = None   # tech|entertainment|finance|pet
    autopilot:          bool              = False  # 略過 review pause + 自動發布


@router.post("/jobs/trigger")
def trigger(req: TriggerRequest):
    run_date = req.date or date_cls.today().isoformat()
    dry_run  = req.dry_run or get_setting("dry_run", "false") == "true"

    job_id = create_job(
        date               = run_date,
        triggered_by       = "manual",
        topic              = req.topic,
        lang               = req.lang,
        platforms          = ",".join(req.platforms),
        selected_cache_ids = ",".join(str(x) for x in (req.selected_cache_ids or [])),
    )

    job_runner.trigger_job(
        job_id          = job_id,
        date            = run_date,
        topic           = req.topic,
        platforms       = req.platforms,
        dry_run         = dry_run,
        pre_news        = req.selected_news,
        account_profile = req.account_profile,
        strategy        = req.strategy,
        autopilot       = req.autopilot,
    )
    return {"job_id": job_id, "date": run_date, "status": "queued"}


_STRATEGY_LABEL = {
    "tech":          "科技",
    "entertainment": "娛樂",
    "finance":       "財經",
    "pet":           "寵物",
    "generic":       "新聞",
}

_TRIGGERED_LABEL = {
    "autopilot_news":     ("📰", "新聞"),
    "autopilot_trending": ("🔥", "娛樂"),
    "schedule":           ("⏰", "排程"),
    "manual":             ("✋", "手動"),
}

def _enrich_display(job: dict) -> dict:
    """Compute display_topic = {strategy label} · {first news title}. Falls
    back to triggered_by + status hint so queued/in-flight jobs still show
    meaningful labels (avoids the dreaded "AI 科技快訊" placeholder)."""
    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job['id']}"
    news_file = pipe_dir / "news.json"
    strategy  = ""
    first_title = ""
    if news_file.exists():
        try:
            nd = _json.loads(news_file.read_text(encoding="utf-8"))
            strategy = (nd.get("strategy") or "").lower()
            items    = nd.get("items") or []
            if items:
                first_title = items[0].get("title") or items[0].get("hook") or ""
        except Exception:
            pass
    label = _STRATEGY_LABEL.get(strategy, "")
    parts = [p for p in (label, first_title) if p]
    display = " · ".join(parts) if parts else ""
    if not display:
        # No news.json yet (queued/early-stage). Use triggered_by + status hint.
        emoji, src_label = _TRIGGERED_LABEL.get(job.get("triggered_by") or "", ("⚙️", "自動"))
        status_hint = {
            "queued":  "排隊中",
            "running": "選題中",
            "failed":  "失敗",
            "cancelled": "已取消",
        }.get(job.get("status") or "", job.get("status") or "")
        display = f"{emoji} {src_label} · {status_hint}" if status_hint else f"{emoji} {src_label}"
    job["display_topic"] = display
    return job


@router.get("/jobs")
def jobs_list(limit: int = 30, status: str = None):
    return [_enrich_display(j) for j in list_jobs(limit=limit, status=status)]


class CompileRequest(BaseModel):
    src_job_ids: list[int]              # [92, 94] — order preserved in output
    version:     str | None = "long"    # "short" | "long" (default long → >60s)


@router.post("/compile")
def compile_videos_api(req: CompileRequest):
    """Concatenate 2+ finished jobs into a 合輯 video. Returns the new
    compile job's directory so the UI can open it for upload preview."""
    import subprocess, sys
    from datetime import date as _date

    if len(req.src_job_ids) < 2:
        raise HTTPException(400, "需要至少 2 個 src_job_ids")
    if req.version not in ("short", "long"):
        raise HTTPException(400, "version 必須是 short 或 long")

    src_keys: list[str] = []
    for jid in req.src_job_ids:
        j = get_job(jid)
        if not j:
            raise HTTPException(404, f"job {jid} 不存在")
        src_keys.append(f"{j['date']}/job_{jid}")

    target_date = _date.today().isoformat()
    script = BASE_DIR / "scripts" / "compile_videos.py"

    proc = subprocess.run(
        [sys.executable, str(script), target_date, *src_keys, "--version", req.version],
        capture_output=True, text=True, cwd=str(BASE_DIR),
    )
    if proc.returncode != 0:
        raise HTTPException(500, f"compile failed: {proc.stderr[-500:]}")

    # Parse the output.mp4 path from the last line of stdout
    import re as _re
    m = _re.search(r"compile done.*?(pipeline[\\/][^\s(]+output\.mp4)", proc.stdout)
    out_path = m.group(1) if m else ""

    return {
        "ok":         True,
        "output":     out_path,
        "src_keys":   src_keys,
        "stdout_tail": proc.stdout.splitlines()[-6:],
    }


@router.get("/jobs/running")
def running_job():
    return {"running": job_runner.is_running(),
            "job_id": job_runner.get_running_job_id()}


@router.get("/jobs/{job_id}")
def job_detail(job_id: int):
    job = get_job(job_id)
    if job:
        _enrich_display(job)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/stats")
def stats():
    return get_stats()



class UploadRequest(BaseModel):
    platforms: list[str] | None = None   # ["youtube","tiktok","instagram"]; None = use job's stored


@router.post("/jobs/{job_id}/upload")
def upload_job(job_id: int, req: UploadRequest | None = None):
    """手動觸發上傳 — 在用戶確認影片後呼叫"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "done":
        raise HTTPException(400, "Job not done yet")
    if job.get("step_upload") == "uploading":
        raise HTTPException(409, "Already uploading")

    job_key   = f"{job['date']}/job_{job_id}"
    req_plats = (req.platforms if req else None) or []
    platforms = req_plats or (job.get("platforms") or "youtube,instagram").split(",")
    if req_plats:
        update_job(job_id, platforms=",".join(req_plats))
    dry_run   = get_setting("dry_run", "false") == "true"

    # 讀取 news.json 的 account_profile（若有）
    news_file = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "news.json"
    profile_override = ""
    if news_file.exists():
        try:
            nd = _json.loads(news_file.read_text(encoding="utf-8"))
            profile_override = nd.get("account_profile", "")
        except Exception:
            pass

    plat_args = ["--platforms"] + platforms
    if dry_run:
        plat_args += ["--dry-run"]
    if profile_override:
        plat_args += ["--profile", profile_override]

    update_job(job_id, step_upload="uploading")
    log_path = Path(job["log_path"]) if job.get("log_path") else None

    def _do_upload():
        ok, _ = job_runner._call_script("publisher.py", job_key, plat_args, log_path)
        update_job(job_id, step_upload="done" if ok else "failed")

    threading.Thread(target=_do_upload, daemon=True).start()
    return {"job_id": job_id, "status": "uploading"}


@router.get("/jobs/{job_id}/screenshots")
def job_screenshots(job_id: int):
    """列出此 job 所有截圖（含缺圖佔位），數量以 news.json 為準"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    shots_dir = pipe_dir / "screenshots"
    news_file = pipe_dir / "news.json"

    count = 3
    if news_file.exists():
        try:
            count = len(_json.loads(news_file.read_text(encoding="utf-8")).get("items", []))
        except Exception:
            pass

    broll_dir = pipe_dir / "broll"
    result = []
    for i in range(1, count + 1):
        png   = f"news_{i:02d}.png"
        mp4   = f"broll_{i:02d}.mp4"
        if (broll_dir / mp4).exists():
            result.append({
                "index":    i,
                "filename": mp4,
                "url":      f"/api/media/jobs/{job_id}/broll/{mp4}",
                "exists":   True,
                "type":     "broll",
            })
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
        else:
            result.append({
                "index":    i,
                "filename": png,
                "url":      None,
                "exists":   False,
                "type":     "screenshot",
            })
    return result


class RetakeRequest(BaseModel):
    url: str | None = None   # 可選：覆蓋 news.json 中的 URL


@router.post("/jobs/{job_id}/screenshots/{n}/retake")
def retake_screenshot(job_id: int, n: int, body: RetakeRequest = None):
    """重新截圖第 n 張（1-based），同步執行，完成後回傳"""
    if body is None:
        body = RetakeRequest()
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    news_file = pipe_dir / "news.json"
    shots_dir = pipe_dir / "screenshots"

    if not news_file.exists():
        raise HTTPException(400, "news.json not found")

    data  = _json.loads(news_file.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if n < 1 or n > len(items):
        raise HTTPException(400, f"Item {n} out of range (1–{len(items)})")

    item = items[n - 1]
    # 若前端傳入新 URL，更新 news.json
    if body.url:
        items[n - 1]["source_url"] = body.url
        news_file.write_text(
            _json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        url = body.url
    else:
        url = item.get("source_url") or item.get("url") or ""
    if not url:
        raise HTTPException(400, "No URL for this item")

    shot_path = shots_dir / f"news_{n:02d}.png"
    shot_path.unlink(missing_ok=True)
    shots_dir.mkdir(parents=True, exist_ok=True)

    ok = _take_screenshot(url, shot_path)
    if not ok:
        raise HTTPException(500, "截圖失敗")

    return {"ok": True, "url": f"/api/media/jobs/{job_id}/screenshots/{shot_path.name}"}


class UploadScreenshotRequest(BaseModel):
    data_url: str   # "data:image/png;base64,<b64>"


@router.post("/jobs/{job_id}/screenshots/{n}/upload")
def upload_screenshot(job_id: int, n: int, body: UploadScreenshotRequest):
    """Overwrite screenshot n with client-edited PNG (base64 data URL)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    news_file = pipe_dir / "news.json"
    if not news_file.exists():
        raise HTTPException(400, "news.json not found")

    data  = _json.loads(news_file.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if n < 1 or n > len(items):
        raise HTTPException(400, f"Item {n} out of range (1–{len(items)})")

    # Strip data URL prefix and decode
    url = body.data_url
    if "," in url:
        url = url.split(",", 1)[1]
    try:
        png_bytes = _base64.b64decode(url)
    except Exception:
        raise HTTPException(400, "Invalid base64 payload")

    shots_dir = pipe_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shots_dir / f"news_{n:02d}_edited.png"   # edited variant never overwritten by retake
    shot_path.write_bytes(png_bytes)

    return {"ok": True,
            "url": f"/api/media/jobs/{job_id}/screenshots/{shot_path.name}",
            "edited": True}


PLATFORMS = ["youtube", "tiktok", "instagram", "facebook", "threads", "x", "pinterest", "reddit"]


# ══════════════════════════════════════════════════════════════════════════════
# Per-platform metadata recipes (v2 — after 2026-04-19 specialist agent audit)
# ══════════════════════════════════════════════════════════════════════════════
# Insights codified here:
#   1. TikTok: ladder (1 huge + 3 niche + 2 micro) — not generic tag spam
#   2. IG: 25-30 hashtag first_comment — current 5 tags kills discovery
#   3. YT: 8-12 tags, front-load specific IPs (algo weights first 3 heaviest)
#   4. Threads/X: keep hashtags minimal (1-3 topic tags)
#   5. FB: no hashtag spam — prose-style tags in body

# Per-platform × per-strategy hashtag strings (TikTok / IG / Threads / X / FB)
# "{topic}" placeholder gets replaced with 2-3 story-specific tags at runtime.
_HASHTAGS = {
    "tiktok": {
        "tech":          "#fyp #AI新聞 #科技新聞 #AI #AItools #Doro日報",
        "entertainment": "#TikTokTaiwan #台灣娛樂 #娛樂懶人包 #熱搜 #Doro日報 #fyp",
        "finance":       "#fyp #台股 #財經新聞 #投資 #股市 #Doro日報",
        "pet":           "#fyp #萌寵 #寵物日常 #貓狗 #療癒 #Doro日報",
        "generic":       "#fyp #每日新聞 #台灣熱搜 #懶人包 #Doro日報 #TikTokTaiwan",
    },
    "instagram": {  # expand to 25-30 for first_comment
        "tech": (
            "#Doro日報 #AI新聞 #每日AI #AI懶人包 #Claude #Anthropic #ChatGPT #LLM "
            "#AIAgent #AI代理 #生成式AI #GenAI #AI工具 #AItools #AInews "
            "#tech #techtok #科技新聞 #科技趨勢 #AI趨勢 #AI產業 #AI應用 "
            "#台灣科技 #未來科技 #科技宅 #每日科技 #AI觀察 #AI圈 #科技新知"
        ),
        "entertainment": (
            "#Doro日報 #每日娛樂 #娛樂懶人包 #YT熱門 #台灣熱門 #TWtrending "
            "#電競 #電競新聞 #esports #娛樂圈 #明星八卦 #追劇日常 #追劇推薦 "
            "#電影預告 #必看電影 #遊戲實況 #實況主 #網路熱搜 #熱搜話題 "
            "#週末追劇 #娛樂新聞 #popculture #fandom #movietok #gametok "
            "#台灣娛樂 #TWent #twtok #每日精選 #娛樂整理"
        ),
        "finance": (
            "#Doro日報 #每日財經 #台股 #美股 #財經新聞 #投資理財 #股市分析 "
            "#台灣股市 #投資 #存股 #ETF #被動收入 #理財 #股票 #投資日常 "
            "#finance #stocks #investing #台股日記 #股市觀察 #財經懶人包 "
            "#財經筆記 #投資筆記 #理財生活 #每日市場 #股市 #TWstocks "
            "#投資新手 #理財達人 #台灣投資"
        ),
        "pet": (
            "#Doro日報 #萌寵日常 #寵物日常 #貓奴 #狗奴 #貓咪 #狗狗 "
            "#柯基 #柴犬 #橘貓 #三花貓 #貓生活 #狗生活 #療癒系 #動物療癒 "
            "#可愛動物 #寵物愛好者 #pet #cats #dogs #petlover "
            "#cutepet #pettok #寵物頻道 #毛孩日常 #寵物 #萌寵動物 "
            "#動物星球 #寵物世界"
        ),
        "generic": (  # mixed news — broad but named
            "#Doro日報 #每日懶人包 #台灣新聞 #TWnews #熱搜 #trending "
            "#網路熱議 #話題焦點 #新聞整理 #懶人包 #新聞日報 "
            "#科技新聞 #娛樂新聞 #社會議題 #每日精選 #Taiwan #TaiwanNews "
            "#news #每日話題 #熱門話題 #熱門整理 #追新聞 "
            "#今日焦點 #台灣焦點 #新聞彙整 #每日焦點 #焦點新聞 "
            "#新聞懶人包 #新聞彙整 #新聞日常"
        ),
    },
    "facebook_body": {  # inline at end of description, 5-8 tags is FB norm
        "tech":          "#AI新聞 #科技新知 #AI工具 #台灣科技 #Doro日報",
        "entertainment": "#娛樂新聞 #台灣娛樂 #熱搜話題 #追劇 #Doro日報",
        "finance":       "#財經 #投資理財 #台股 #股市 #Doro日報",
        "pet":           "#萌寵 #寵物日常 #療癒 #Doro日報",
        "generic":       "#每日新聞 #台灣新聞 #熱搜 #懶人包 #Doro日報",
    },
    "threads": {  # 1-2 topic tags max
        "tech":          "#AI新聞 #Doro日報",
        "entertainment": "#娛樂懶人包 #Doro日報",
        "finance":       "#財經 #Doro日報",
        "pet":           "#萌寵 #Doro日報",
        "generic":       "#每日新聞 #Doro日報",
    },
    "x": {  # 2-3 tags, front of post style
        "tech":          "#AI #科技 #AINews",
        "entertainment": "#娛樂 #熱搜",
        "finance":       "#台股 #投資",
        "pet":           "#萌寵 #寵物",
        "generic":       "#新聞 #台灣",
    },
}

_HASHTAGS_BY_STRATEGY = _HASHTAGS["tiktok"]  # legacy alias (some callers may use)

# YouTube tags (comma-separated, no hashtag prefix) — 8-12 tags, IP-specific first
_YOUTUBE_TAGS_BY_STRATEGY = {
    "tech":          "AI新聞,ChatGPT,Claude,Anthropic,AI工具,人工智慧,科技新聞,AI代理,生成式AI,Doro日報,每日AI",
    "entertainment": "台灣娛樂,娛樂新聞,熱門話題,YT熱門,電競,電影預告,實況,娛樂懶人包,Doro日報,每日娛樂",
    "finance":       "台股,財經新聞,投資,股市,理財,美股,ETF,財經懶人包,Doro日報,每日財經",
    "pet":           "萌寵,寵物日常,貓狗,療癒,可愛動物,pet,寵物頻道,Doro日報",
    "generic":       "台灣新聞,每日新聞,熱門話題,新聞懶人包,時事,Doro日報,每日懶人包",
}

# Per-strategy is_aigc policy.
# Rule: only set true when VIDEO CONTENT is fully synthetic. Our entertainment
# is repackaged human source (trending YT TW clips rehashed with AI narration)
# — TikTok's AI-content flag on such posts measurably suppresses reach -15-25%
# in Taiwan market per 2026 TikTok Strategist audit. Keep true for pure AI/
# tech news (no human footage).
_IS_AIGC_BY_STRATEGY = {
    "tech":          True,
    "generic":       True,
    "finance":       True,
    "entertainment": False,
    "pet":           False,
}

# Strategy-specific title hook formulas. {hook} = first item's hook, {n} = item count.
_TITLE_FORMULA = {
    "tech":          "{hook}｜{n} 則 AI 大事一次看完",
    "entertainment": "{hook}｜今天台灣 {n} 件熱搜一次看",
    "finance":       "{hook}｜{n} 則市場焦點",
    "pet":           "{hook}｜{n} 個萌寵時刻",
    "generic":       "{hook}｜{n} 則今日重點",
}

# Strategy-specific sign-off line at end of long descriptions
_SIGNOFF = {
    "tech":          "追蹤 @doro 每天一則 AI 懶人包 🐾",
    "entertainment": "追蹤 @doro 每天一則娛樂懶人包 🐾",
    "finance":       "追蹤 @doro 每天一則財經懶人包 🐾",
    "pet":           "追蹤 @doro 每天一則萌寵日常 🐾",
    "generic":       "追蹤 @doro 每天一則重點懶人包 🐾",
}


def _compose_title(hooks: list[str], items: list[dict], strategy: str) -> str:
    """Hook-driven single-line title (v2). Replaces old 'A | B | C' pipe dump."""
    first_hook = (hooks[0] or (items[0].get("title") if items else "") or "每日重點")[:18]
    n = len([h for h in hooks if h])
    template = _TITLE_FORMULA.get(strategy, _TITLE_FORMULA["generic"])
    return template.format(hook=first_hook, n=max(n, 1))[:100]


def _compose_description(items: list[dict], strategy: str, signoff: bool = True) -> str:
    """Numbered + save-CTA + sign-off description (v2)."""
    if not items:
        return _SIGNOFF.get(strategy, _SIGNOFF["generic"])
    lines = []
    for i, it in enumerate(items, 1):
        h = it.get("hook") or ""
        t = it.get("title") or ""
        s = (it.get("script") or it.get("summary") or "")[:80]
        lines.append(f"{'①②③④⑤'[i-1] if i<=5 else f'{i}.'} {h}：{t}")
        if s:
            lines.append(f"    {s}")
    body = "\n".join(lines)
    tail = f"\n\n你怎麼看？留言告訴 Doro 👇\n📌 收藏起來，這週再看一次" if signoff else ""
    tail += f"\n{_SIGNOFF.get(strategy, _SIGNOFF['generic'])}" if signoff else ""
    return f"🐾 Doro 日報\n\n{body}{tail}"

# Strategy → FB Page ID mapping.
# Tech goes to 雙層甜甜圈; everything else (news, entertainment, pet) defaults to Mascot page.
_FB_PAGE_BY_STRATEGY = {
    "tech":          "1100141579843223",   # 雙層甜甜圈
    "entertainment": "1012830001921459",   # Doro / Mascot
    "pet":           "1012830001921459",   # same Mascot page for now (swap if 奶烙 gets own page)
    "finance":       "1100141579843223",   # fallback to tech page (finance strategy dropped)
    "generic":       "1012830001921459",   # generic (news without specific strategy) → Mascot
}
FACEBOOK_PAGE_ID_DEFAULT = _FB_PAGE_BY_STRATEGY["generic"]


def _seed_platform_meta(news: dict) -> dict:
    """Build default per-platform meta from news.json items (option B: shared baseline)."""
    items = news.get("items", [])
    if not items:
        titles    = [""]
        hooks     = [""]
        scripts   = [""]
    else:
        titles  = [it.get("title", "")  for it in items]
        hooks   = [it.get("hook", "")   for it in items]
        scripts = [it.get("script") or it.get("summary", "") for it in items]

    # v2 (2026-04-19): hook-driven title + per-platform hashtag recipes
    # Replaces the old "A | B | C" pipe format + generic 3-tag spam.
    strategy = (news.get("strategy") or "generic").lower()

    main_title  = _compose_title(hooks, items, strategy)
    long_desc   = _compose_description(items, strategy, signoff=True)

    def _tags(platform: str) -> str:
        return _HASHTAGS[platform].get(strategy, _HASHTAGS[platform]["generic"])

    yt_tags_csv = _YOUTUBE_TAGS_BY_STRATEGY.get(strategy, _YOUTUBE_TAGS_BY_STRATEGY["generic"])
    fb_page_id  = _FB_PAGE_BY_STRATEGY.get(strategy,     FACEBOOK_PAGE_ID_DEFAULT)
    is_aigc     = _IS_AIGC_BY_STRATEGY.get(strategy,     True)

    return {
        "youtube": {
            "video_version":         "long",
            "title":                 main_title,
            "description":           long_desc,
            "tags":                  yt_tags_csv,
            "use_auto_thumbnail":    True,
            "categoryId":            "22",
            "defaultLanguage":       "zh-TW",
            "defaultAudioLanguage":  "zh-TW",
            "privacyStatus":         "public",
            "containsSyntheticMedia": True,
            "selfDeclaredMadeForKids": False,
            "embeddable":            True,
            "publicStatsViewable":   True,
            "license":               "youtube",
        },
        "tiktok": {
            "video_version":         "long",   # >60s qualifies for Creator Rewards ($0.50-1/1K views)
            # v2: ladder hashtags (1 huge + 3 niche + 2 micro), hook line on top
            "title":                 f"{main_title}\n\n{_tags('tiktok')}",
            "privacy_level":         "PUBLIC_TO_EVERYONE",
            # v2: is_aigc follows strategy (entertainment=false restores -15-25% reach)
            "is_aigc":               is_aigc,
            "cover_timestamp":       1000,
            "disable_duet":          False,
            "disable_comment":       False,
            "disable_stitch":        False,
            "brand_content_toggle":  False,
            "brand_organic_toggle":  False,
        },
        "instagram": {
            "video_version":         "short",
            "title":                 long_desc,           # v2: full IG-native caption body
            "first_comment":         _tags("instagram"),  # v2: 25-30 mixed hashtags
            "share_mode":            "REELS",
            "share_to_feed":         True,
            "collaborators":         "",
            "user_tags":             "",
        },
        "facebook": {
            "video_version":         "short",
            "title":                 main_title,
            "description":           f"{long_desc}\n\n{_tags('facebook_body')}",
            "facebook_media_type":   "REELS",
            "video_state":           "PUBLISHED",
            "facebook_page_id":      fb_page_id,
        },
        "threads": {
            "video_version":         "short",
            # v2: conversational single-post body + 1-2 topic tags only
            "title":                 f"{main_title[:400]}\n{_tags('threads')}",
            "threads_topic_tag":     "",
        },
        "x": {
            "video_version":         "long",
            # v2: tight 2-3 tags inline, under 280 chars hard cap
            "title":                 f"{main_title[:240]} {_tags('x')}"[:280],
            "poll_options":          "",
            "poll_duration":         1440,
            "reply_settings":        "everyone",
            "x_long_text_as_post":   False,
        },
        "_schedule": {
            # auto_per_platform → publisher computes each platform's next golden
            # slot (TikTok 19-23, IG 13-19, YT 07-09 / 20-22 etc) and Upload-Post
            # handles the actual queue. Avoids the "凌晨同時爆 6 平台" signal
            # that flags AI channels for YT review.
            "mode":                  "auto_per_platform",
            "scheduled_date":        "",
            "timezone":              "Asia/Taipei",
        },
    }


@router.get("/jobs/{job_id}/platform_meta")
def get_platform_meta(job_id: int):
    """Return per-platform meta (seeded from news.json if file doesn't exist yet)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir    = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    meta_file   = pipe_dir / "platform_meta.json"
    news_file   = pipe_dir / "news.json"

    if meta_file.exists():
        return _json.loads(meta_file.read_text(encoding="utf-8"))

    if not news_file.exists():
        raise HTTPException(400, "news.json not found; cannot seed platform meta")

    news = _json.loads(news_file.read_text(encoding="utf-8"))
    return _seed_platform_meta(news)


class PlatformMetaUpdate(BaseModel):
    platform_meta: dict   # full shape {youtube: {...}, tiktok: {...}, ...}


@router.put("/jobs/{job_id}/platform_meta")
def put_platform_meta(job_id: int, body: PlatformMetaUpdate):
    """Save per-platform meta (overwrites platform_meta.json)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    pipe_dir.mkdir(parents=True, exist_ok=True)
    meta_file = pipe_dir / "platform_meta.json"
    tmp_file  = meta_file.with_suffix(".json.tmp")
    tmp_file.write_text(
        _json.dumps(body.platform_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_file, meta_file)   # atomic on Windows + POSIX
    return {"ok": True}


_LAYOUT_MODES = {
    "visual", "text",
    "article_rotate", "article_magazine", "article_breaking", "article_flashcard",
}


class LayoutModeUpdate(BaseModel):
    layout_mode: str   # see _LAYOUT_MODES


@router.patch("/jobs/{job_id}/layout_mode")
def patch_layout_mode(job_id: int, body: LayoutModeUpdate):
    """Update layout_mode in news.json (atomic write)."""
    if body.layout_mode not in _LAYOUT_MODES:
        raise HTTPException(400, f"layout_mode must be one of: {sorted(_LAYOUT_MODES)}")

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    news_file = pipe_dir / "news.json"
    if not news_file.exists():
        raise HTTPException(400, "news.json not found")

    data = _json.loads(news_file.read_text(encoding="utf-8"))
    data["layout_mode"] = body.layout_mode

    tmp = news_file.with_suffix(".json.tmp")
    tmp.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, news_file)
    return {"ok": True, "layout_mode": body.layout_mode}


@router.get("/jobs/{job_id}/audio_metadata")
def get_audio_metadata(job_id: int):
    """Return audio pipeline metadata (voice, BGM/SFX pick per item, offsets)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    p = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "audio" / "audio_metadata.json"
    if not p.exists():
        return {"voice_strategy": "", "voice_id_used": "", "items": []}
    return _json.loads(p.read_text(encoding="utf-8"))


class ReplaceItemRequest(BaseModel):
    cache_id: int
    mark_old_blocked: bool = True   # 是否標記被替換的 URL 為截圖封鎖


@router.post("/jobs/{job_id}/items/{n}/replace")
def replace_item(job_id: int, n: int, body: ReplaceItemRequest):
    """
    以快取中的新聞替換第 n 篇：重新 Claude 生成腳本 + 截圖。
    同時將原本那篇的 URL 標記為 screenshot_blocked。
    """
    from web.claude_client import enrich_news_items

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    cached = get_cache_item(body.cache_id)
    if not cached:
        raise HTTPException(404, "Cache item not found")

    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    news_file = pipe_dir / "news.json"
    if not news_file.exists():
        raise HTTPException(400, "news.json not found")

    data  = _json.loads(news_file.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if n < 1 or n > len(items):
        raise HTTPException(400, f"Item {n} out of range (1–{len(items)})")

    # 標記舊文章為截圖被擋
    if body.mark_old_blocked:
        old_url = items[n - 1].get("source_url") or items[n - 1].get("url", "")
        if old_url:
            mark_news_blocked_by_url(old_url)

    # Load strategy from news.json if present
    strategy = data.get("strategy") or None

    # Claude 重新生成腳本（單篇）
    raw = [{
        "title":   cached["title"],
        "summary": cached["summary"],
        "url":     cached["url"],
        "source":  cached["source"],
    }]
    try:
        enriched = enrich_news_items(raw, job.get("topic"), strategy)
    except Exception as e:
        raise HTTPException(500, f"Claude 生成失敗: {e}")

    if not enriched:
        raise HTTPException(500, "Claude 回傳空結果")

    new_item = enriched[0]
    new_item["source_url"]  = cached["url"]
    new_item["source_name"] = cached["source"]

    # 更新 news.json
    items[n - 1] = new_item
    data["items"] = items
    news_file.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 更新 job 的 selected_cache_ids（加入新的，可選）
    cur_ids = set(
        int(x) for x in (job.get("selected_cache_ids") or "").split(",") if x.strip()
    )
    cur_ids.add(body.cache_id)
    update_job(job_id, selected_cache_ids=",".join(str(x) for x in cur_ids))

    # 截圖
    shots_dir = pipe_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shots_dir / f"news_{n:02d}.png"
    shot_path.unlink(missing_ok=True)

    screenshot_ok = _take_screenshot(cached["url"], shot_path)
    if not screenshot_ok:
        mark_news_blocked(body.cache_id)

    return {
        "ok":               True,
        "item":             new_item,
        "url":              f"/api/media/jobs/{job_id}/screenshots/{shot_path.name}" if screenshot_ok else None,
        "screenshot_ok":    screenshot_ok,
    }


@router.get("/jobs/{job_id}/news")
def get_job_news(job_id: int):
    """讀取 job 的 news.json（供腳本編輯 UI 用）"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    news_file = pipe_dir / "news.json"
    if not news_file.exists():
        raise HTTPException(404, "news.json not found")
    return _json.loads(news_file.read_text(encoding="utf-8"))


class ScriptEditRequest(BaseModel):
    items: list[dict]   # [{hook, title, summary, script, source_url, source_name}, ...]


@router.post("/jobs/{job_id}/confirm_script")
def confirm_script(job_id: int, req: ScriptEditRequest):
    """用戶確認/調整腳本後繼續，更新 news.json 並釋放暫停"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    ev = job_runner._pause_events.get(f"{job_id}_script")
    if not ev:
        raise HTTPException(400, "Job not waiting for script review")

    # 更新 news.json
    pipe_dir  = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    news_file = pipe_dir / "news.json"
    if news_file.exists():
        data = _json.loads(news_file.read_text(encoding="utf-8"))
        data["items"] = req.items
        news_file.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    update_job(job_id, step_screenshot="pending")
    ev.set()
    return {"ok": True}


@router.post("/jobs/{job_id}/continue")
def continue_job(job_id: int):
    """截圖審核完成，繼續執行語音/影片"""
    ev = job_runner._pause_events.get(job_id)
    if ev:
        # 正常流程：解除暫停事件
        update_job(job_id, step_audio="pending")
        ev.set()
        return {"ok": True}

    # Fallback：後端曾重啟，_pause_events 已遺失
    # 檢查 DB 確認 job 確實在等審核
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.get("step_audio") != "review":
        raise HTTPException(400, "Job not waiting for review")
    if job_runner.is_running():
        raise HTTPException(409, "Pipeline already running")

    job_key = f"{job['date']}/job_{job_id}"
    dry_run = get_setting("dry_run", "false") == "true"
    started = job_runner.resume_from_audio(job_id, job_key, dry_run)
    if not started:
        raise HTTPException(409, "Pipeline already running")
    return {"ok": True, "resumed": True}


@router.post("/jobs/{job_id}/retry/{step}")
def retry_step(job_id: int, step: str):
    """從指定步驟重新跑（audio / video / upload）"""
    RETRYABLE = {"audio", "video", "upload"}
    if step not in RETRYABLE:
        raise HTTPException(400, f"只能重跑 {RETRYABLE} 其中一個步驟")
    if job_runner.is_running():
        raise HTTPException(409, "Pipeline already running")

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    job_key = f"{job['date']}/job_{job_id}"
    dry_run = get_setting("dry_run", "false") == "true"
    renderer = get_setting("video_renderer", "ffmpeg").lower()
    video_script = "remotion_renderer.py" if renderer == "remotion" else "video_composer.py"
    script_map = {
        "audio":  ("audio_generator.py",  []),
        "video":  (video_script,           []),
    }

    if step == "upload":
        return upload_job(job_id)

    script, extra = script_map[step]
    if dry_run:
        extra = extra + ["--dry-run"]

    update_job(job_id, status="running", **{f"step_{step}": "running"})

    def _run():
        log_path = Path(job["log_path"]) if job.get("log_path") else None
        ok, out = job_runner._call_script(script, job_key, extra, log_path)
        if ok:
            update_job(job_id, status="done", **{f"step_{step}": "done"})
        else:
            update_job(job_id, status="failed", **{f"step_{step}": "failed"}, error=out[-300:])

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "job_id": job_id, "step": step}


@router.delete("/jobs/{job_id}/files")
def cleanup_job_files(job_id: int):
    """刪除 job 的 pipeline 工作檔案（保留 output.mp4），釋放磁碟空間"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] == "running":
        raise HTTPException(400, "Job is still running")

    pipe_dir = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    freed_mb = 0
    for subdir in ["audio", "screenshots", "segments"]:
        d = pipe_dir / subdir
        if d.exists():
            freed_mb += sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) // (1024*1024)
            shutil.rmtree(d)

    return {"ok": True, "freed_mb": freed_mb}


@router.get("/storage/stats")
def storage_stats():
    """統計 pipeline 資料夾佔用空間"""
    pipe_root = BASE_DIR / "pipeline"
    if not pipe_root.exists():
        return {"total_mb": 0, "jobs": []}
    total = 0
    jobs_info = []
    for job_dir in sorted(pipe_root.rglob("job_*")):
        if job_dir.is_dir():
            size = sum(f.stat().st_size for f in job_dir.rglob("*") if f.is_file())
            total += size
            jobs_info.append({"path": str(job_dir.relative_to(pipe_root)), "mb": size // (1024*1024)})
    return {"total_mb": total // (1024*1024), "jobs": jobs_info}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    """取消正在執行的 job"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] not in ("running", "queued"):
        raise HTTPException(400, "Job is not running")
    # 立刻更新 DB，避免頁面刷新後仍顯示 running
    update_job(job_id, status="cancelled")
    job_runner.cancel_job(job_id)
    return {"ok": True, "job_id": job_id}


@router.post("/jobs/{job_id}/regenerate")
def regenerate_job(job_id: int):
    """用相同主題重新生成影片"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    run_date  = date_cls.today().isoformat()
    platforms = (job.get("platforms") or "youtube,instagram").split(",")
    dry_run   = get_setting("dry_run", "false") == "true"

    new_id = create_job(
        date         = run_date,
        triggered_by = "manual",
        topic        = job.get("topic"),
        platforms    = ",".join(platforms),
    )
    job_runner.trigger_job(
        job_id  = new_id,
        date    = run_date,
        topic   = job.get("topic"),
        platforms = platforms,
        dry_run = dry_run,
    )

    return {"job_id": new_id, "date": run_date, "status": "queued"}
