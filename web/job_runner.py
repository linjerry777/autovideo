"""
web/job_runner.py — Runs the pipeline as background thread, updates DB + SSE
"""
import asyncio, json as _json, queue, subprocess, sys, threading
from datetime import datetime, timezone
from pathlib import Path

from web.db import update_job, get_setting

BASE_DIR = Path(__file__).parent.parent
SCRIPTS  = BASE_DIR / "scripts"
PYTHON   = sys.executable

# ── 同時只允許一個 job 跑 ─────────────────────────────────────────────
_lock = threading.Lock()
_running_job_id: int | None = None
_pause_events:  dict[int, threading.Event] = {}  # job_id → Event (set = continue)
_cancel_flags:  dict[int, bool] = {}              # job_id → True = 取消中


def cancel_job(job_id: int):
    """標記 job 為取消，下一個步驟前會中止"""
    _cancel_flags[job_id] = True
    # 解除所有暫停事件（截圖審核 + 腳本審核）
    for key in (job_id, f"{job_id}_script"):
        ev = _pause_events.get(key)
        if ev:
            ev.set()


# ── SSE 事件廣播 ──────────────────────────────────────────────────────
# job_id → list of asyncio.Queue
_event_queues: dict[int, list] = {}
_event_queues_lock = threading.Lock()


def subscribe(job_id: int) -> asyncio.Queue:
    q = asyncio.Queue()
    with _event_queues_lock:
        _event_queues.setdefault(job_id, []).append(q)
    return q


def unsubscribe(job_id: int, q: asyncio.Queue):
    with _event_queues_lock:
        lst = _event_queues.get(job_id, [])
        if q in lst:
            lst.remove(q)


def _broadcast(job_id: int, data: dict):
    """Thread-safe: push event to all SSE queues and step hooks for this job"""
    with _event_queues_lock:
        queues = list(_event_queues.get(job_id, []))
    for q in queues:
        if _main_loop and _main_loop.is_running():
            _main_loop.call_soon_threadsafe(q.put_nowait, data)
    for hook in list(_step_hooks):
        try:
            hook(job_id, data)
        except Exception:
            pass


_main_loop: asyncio.AbstractEventLoop | None = None

def set_event_loop(loop: asyncio.AbstractEventLoop):
    global _main_loop
    _main_loop = loop


# ── Step hooks (for Telegram bot, etc.) ──────────────────────────────────────
_step_hooks: list = []

def add_step_hook(fn):
    """Register a callable(job_id, data) to be called on every broadcast."""
    if fn not in _step_hooks:
        _step_hooks.append(fn)

def remove_step_hook(fn):
    if fn in _step_hooks:
        _step_hooks.remove(fn)


def resume_job(job_id: int, key=None):
    """Resume a job paused at a review step."""
    k = key if key is not None else job_id
    ev = _pause_events.get(k)
    if ev:
        ev.set()


def is_running() -> bool:
    return _lock.locked()


def get_running_job_id() -> int | None:
    return _running_job_id


def _check_cancel(job_id: int):
    if _cancel_flags.get(job_id):
        raise RuntimeError("__CANCELLED__")


def _step_update(job_id: int, date: str, step: str, status: str, **extra):
    update_job(job_id, **{f"step_{step}": status}, **extra)
    _broadcast(job_id, {"job_id": job_id, "date": date, f"step_{step}": status, **extra})


def resume_from_audio(job_id: int, job_key: str, dry_run: bool) -> bool:
    """後端重啟後 _pause_events 遺失，重新從 audio 步驟繼續跑完流程"""
    global _running_job_id
    if not _lock.acquire(blocking=False):
        return False
    _running_job_id = job_id
    _cancel_flags[job_id] = False

    # job_key format: "{date}/job_{id}"
    date = job_key.split("/")[0]

    def _run():
        pipe_dir = BASE_DIR / "pipeline" / job_key
        pipe_dir.mkdir(parents=True, exist_ok=True)
        log_path = pipe_dir / "run.log"

        try:
            update_job(job_id, status="running")
            _broadcast(job_id, {"job_id": job_id, "status": "running"})

            _step_update(job_id, date, "audio", "running")
            extra = ["--dry-run"] if dry_run else []
            ok, out = _call_script("audio_generator.py", job_key, extra, log_path)
            if not ok:
                _step_update(job_id, date, "audio", "failed")
                update_job(job_id, status="failed", error=out[-300:])
                _broadcast(job_id, {"job_id": job_id, "status": "failed"})
                return
            _step_update(job_id, date, "audio", "done")
            _check_cancel(job_id)

            # ── Step 3.5: AI 圖生影片 B-roll (optional) ─────────────
            ai_video_mode = get_setting("ai_video_mode", "").lower()
            if ai_video_mode in ("kling", "replicate"):
                _step_update(job_id, date, "ai_video", "running")
                ok_av, out_av = _call_script("ai_video_fetcher.py", job_key, [], log_path)
                _step_update(job_id, date, "ai_video", "done" if ok_av else "skipped")
                _check_cancel(job_id)

            renderer = get_setting("video_renderer", "ffmpeg").lower()
            script_name = "remotion_renderer.py" if renderer == "remotion" else "video_composer.py"
            _step_update(job_id, date, "video", "running")
            ok, out = _call_script(script_name, job_key, [], log_path)
            if not ok:
                _step_update(job_id, date, "video", "failed")
                update_job(job_id, status="failed", error=out[-300:])
                _broadcast(job_id, {"job_id": job_id, "status": "failed"})
                return
            _step_update(job_id, date, "video", "done")

            update_job(job_id, status="done", finished_at=_now())
            _broadcast(job_id, {"job_id": job_id, "status": "done"})

        except Exception as e:
            if str(e) == "__CANCELLED__":
                update_job(job_id, status="cancelled", finished_at=_now())
                _broadcast(job_id, {"job_id": job_id, "status": "cancelled"})
            else:
                update_job(job_id, status="failed", finished_at=_now(), error=str(e))
                _broadcast(job_id, {"job_id": job_id, "status": "failed"})
        finally:
            _cancel_flags.pop(job_id, None)
            _running_job_id = None
            _lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return True


def _now():
    return datetime.now(timezone.utc).isoformat()


def _call_script(script: str, date: str, extra: list = [],
                 log_path: Path = None) -> tuple[bool, str]:
    cmd = [PYTHON, str(SCRIPTS / script), date, *extra]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1500
    )
    output = result.stdout + result.stderr
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {script} ===\n{output}\n")
    return result.returncode == 0, output


def _run_pipeline(job_id: int, date: str, topic: str | None,
                  platforms: list[str], skip_upload: bool, dry_run: bool,
                  pre_news: list[dict] | None = None,
                  account_profile: str | None = None,
                  strategy: str | None = None):
    global _running_job_id

    # 每個 job 有自己的子目錄，避免同天不同主題互相覆蓋
    job_key  = f"{date}/job_{job_id}"
    pipe_dir = BASE_DIR / "pipeline" / date / f"job_{job_id}"
    pipe_dir.mkdir(parents=True, exist_ok=True)
    log_path = pipe_dir / "run.log"

    def su(step: str, status: str, **extra):
        _step_update(job_id, date, step, status, **extra)

    update_job(job_id, status="running", started_at=_now(), log_path=str(log_path))
    _broadcast(job_id, {"job_id": job_id, "status": "running"})
    _cancel_flags[job_id] = False

    try:
        # ── Step 1: 新聞 ────────────────────────────────────────────
        su("news", "running")
        news_file = pipe_dir / "news.json"

        if pre_news:
            # 用戶已選好原始新聞，Claude 只針對這幾筆生成腳本
            from web.claude_client import enrich_news_items, _last_usage
            enriched = enrich_news_items(pre_news, topic, strategy)
            news_file.write_text(
                _json.dumps(
                    {"date": job_key,
                     "account_profile": account_profile or "",
                     "strategy": strategy or "",
                     "items": enriched},
                    ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
            # 記錄 token 用量
            total_tok = _last_usage.get("total_tokens") or (
                _last_usage.get("prompt_tokens", 0) +
                _last_usage.get("completion_tokens", 0)
            )
            if total_tok:
                update_job(job_id, tokens_used=total_tok)
        else:
            # 排程自動跑：用 news_collector.py 完整流程
            extra = []
            if topic:
                extra += ["--topic", topic]
            if dry_run:
                extra += ["--dry-run"]
            ok, out = _call_script("news_collector.py", job_key, extra, log_path)
            if not ok:
                su("news", "failed")
                raise RuntimeError(f"news_collector 失敗:\n{out[-500:]}")

        su("news", "done")
        _check_cancel(job_id)

        # ── 暫停：等用戶確認/調整腳本 ────────────────────────────
        ev_script = threading.Event()
        _pause_events[f"{job_id}_script"] = ev_script
        su("screenshot", "script_review")
        ev_script.wait()
        del _pause_events[f"{job_id}_script"]
        _check_cancel(job_id)

        # ── Step 2: 背景素材（截圖 or B-roll）──────────────────────
        bg_mode = get_setting("background_mode", "screenshot")
        su("screenshot", "running")
        if bg_mode == "broll":
            ok, out = _call_script("broll_fetcher.py", job_key, [], log_path)
            if not ok:
                # B-roll 抓取失敗不是致命錯誤：fallback 到截圖
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\n[WARN] B-roll 失敗，改用截圖模式\n")
                ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)
        elif bg_mode == "playwright_stealth":
            ok, out = _call_script("playwright_scraper.py", job_key, [], log_path)
            if not ok:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\n[WARN] Playwright stealth 失敗，改用截圖模式\n")
                ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)
        else:
            ok, out = _call_script("screenshot_collector.py", job_key, [], log_path)

        if not ok:
            su("screenshot", "failed")
            raise RuntimeError(f"背景素材抓取失敗:\n{out[-500:]}")
        su("screenshot", "done")
        _check_cancel(job_id)

        # ── 暫停：等用戶確認截圖 ──────────────────────────────────
        ev = threading.Event()
        _pause_events[job_id] = ev
        su("audio", "review")
        ev.wait()
        del _pause_events[job_id]
        _check_cancel(job_id)

        # ── Step 3: 語音生成 ────────────────────────────────────────
        su("audio", "running")
        extra = ["--dry-run"] if dry_run else []
        ok, out = _call_script("audio_generator.py", job_key, extra, log_path)
        if not ok:
            su("audio", "failed")
            raise RuntimeError(f"audio_generator 失敗:\n{out[-500:]}")
        su("audio", "done")
        _check_cancel(job_id)

        # ── Step 3.5: AI 圖生影片 B-roll (optional) ─────────────────
        ai_video_mode = get_setting("ai_video_mode", "").lower()
        if ai_video_mode in ("kling", "replicate"):
            su("ai_video", "running")
            ok_av, out_av = _call_script("ai_video_fetcher.py", job_key, [], log_path)
            su("ai_video", "done" if ok_av else "skipped")
            _check_cancel(job_id)

        # ── Step 4: 合成影片 ────────────────────────────────────────
        renderer = get_setting("video_renderer", "ffmpeg").lower()
        script_name = "remotion_renderer.py" if renderer == "remotion" else "video_composer.py"
        su("video", "running")
        ok, out = _call_script(script_name, job_key, [], log_path)
        if not ok:
            su("video", "failed")
            raise RuntimeError(f"{script_name} 失敗:\n{out[-500:]}")
        su("video", "done")

        # ── Step 5: 上傳 (需用戶手動觸發) ─────────────────────────
        output_mp4 = pipe_dir / "output.mp4"
        su("upload", "pending")

        # ── 完成 ────────────────────────────────────────────────────
        update_job(job_id, status="done", finished_at=_now(),
                   output_path=str(output_mp4))
        _broadcast(job_id, {"job_id": job_id, "status": "done",
                             "output_path": str(output_mp4)})

    except Exception as e:
        if str(e) == "__CANCELLED__":
            update_job(job_id, status="cancelled", finished_at=_now())
            _broadcast(job_id, {"job_id": job_id, "status": "cancelled"})
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n[CANCELLED]\n")
        else:
            update_job(job_id, status="failed", finished_at=_now(), error=str(e))
            _broadcast(job_id, {"job_id": job_id, "status": "failed", "error": str(e)})
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[FAILED] {e}\n")
    finally:
        _cancel_flags.pop(job_id, None)
        _running_job_id = None
        _lock.release()


def trigger_job(job_id: int, date: str, topic: str | None = None,
                platforms: list[str] = None, skip_upload: bool = False,
                dry_run: bool = False,
                pre_news: list[dict] | None = None,
                account_profile: str | None = None,
                strategy: str | None = None) -> bool:
    """Returns True if job was started, False if already running."""
    global _running_job_id
    if platforms is None:
        platforms = get_setting("platforms", "youtube,instagram").split(",")
    if not _lock.acquire(blocking=False):
        return False
    _running_job_id = job_id
    t = threading.Thread(
        target=_run_pipeline,
        args=(job_id, date, topic, platforms, skip_upload, dry_run,
              pre_news, account_profile, strategy),
        daemon=True,
    )
    t.start()
    return True
