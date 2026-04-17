import json as _json, shutil, threading
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


@router.post("/jobs/trigger")
def trigger(req: TriggerRequest):
    if job_runner.is_running():
        raise HTTPException(409, "Pipeline already running")

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

    started = job_runner.trigger_job(
        job_id          = job_id,
        date            = run_date,
        topic           = req.topic,
        platforms       = req.platforms,
        dry_run         = dry_run,
        pre_news        = req.selected_news,
        account_profile = req.account_profile,
        strategy        = req.strategy,
    )
    if not started:
        update_job(job_id, status="failed", error="Lock acquire failed")
        raise HTTPException(409, "Pipeline already running")

    return {"job_id": job_id, "date": run_date, "status": "queued"}


@router.get("/jobs")
def jobs_list(limit: int = 30, status: str = None):
    return list_jobs(limit=limit, status=status)


@router.get("/jobs/running")
def running_job():
    return {"running": job_runner.is_running(),
            "job_id": job_runner.get_running_job_id()}


@router.get("/jobs/{job_id}")
def job_detail(job_id: int):
    job = get_job(job_id)
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
        elif (shots_dir / png).exists():
            result.append({
                "index":    i,
                "filename": png,
                "url":      f"/api/media/jobs/{job_id}/screenshots/{png}",
                "exists":   True,
                "type":     "screenshot",
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
    shot_path = shots_dir / f"news_{n:02d}.png"
    shot_path.write_bytes(png_bytes)

    return {"ok": True, "url": f"/api/media/jobs/{job_id}/screenshots/{shot_path.name}"}


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
    if job_runner.is_running():
        raise HTTPException(409, "Pipeline already running")

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
    started = job_runner.trigger_job(
        job_id  = new_id,
        date    = run_date,
        topic   = job.get("topic"),
        platforms = platforms,
        dry_run = dry_run,
    )
    if not started:
        update_job(new_id, status="failed", error="Lock acquire failed")
        raise HTTPException(409, "Pipeline already running")

    return {"job_id": new_id, "date": run_date, "status": "queued"}
