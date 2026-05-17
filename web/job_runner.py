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


def _default_layout_for_strategy(strategy: str | None) -> str:
    """Default layout for all strategies → article_rotate.

    User preference: every strategy (news + trending, tech / entertainment /
    finance / pet / generic) uses the 3-variant rotation. Individual jobs
    can still override via news.json's `layout_mode` field.
    """
    return "article_rotate"


def _figure_group_for_strategy(strategy: str | None) -> str | None:
    strat = (strategy or "").lower()
    if strat == "figure_tech":
        return "tech"
    if strat == "figure_entertainment":
        return "entertainment"
    return None


def _detect_versions(job_key: str) -> list[str | None]:
    """Return list of versions to render.

    If news.json has script_short + script_long fields on items → ['short', 'long']
    Else → [None] (legacy single-render)
    """
    news_file = BASE_DIR / "pipeline" / job_key / "news.json"
    if not news_file.exists():
        return [None]
    try:
        data = _json.loads(news_file.read_text(encoding="utf-8"))
        items = data.get("items", [])
        if items and all(it.get("script_short") and it.get("script_long") for it in items):
            return ["short", "long"]
    except Exception:
        pass
    return [None]


# ── 同時只允許一個 job 跑 ─────────────────────────────────────────────
_lock = threading.Lock()
_running_job_id: int | None = None
_pause_events:  dict[int, threading.Event] = {}  # job_id → Event (set = continue)
_cancel_flags:  dict[int, bool] = {}              # job_id → True = 取消中

import collections as _collections
_job_queue: _collections.deque = _collections.deque()   # pending job params (dicts)


def cancel_job(job_id: int):
    """標記 job 為取消，下一個步驟前會中止"""
    _cancel_flags[job_id] = True
    # 解除所有暫停事件（截圖審核 + 腳本審核）
    for key in (job_id, f"{job_id}_script"):
        ev = _pause_events.get(key)
        if ev:
            ev.set()
    # If the job is still queued (not yet running), mark it cancelled immediately
    # so the UI reflects the state without waiting for queue drain.
    for entry in list(_job_queue):
        if entry.get("job_id") == job_id:
            _job_queue.remove(entry)
            _cancel_flags.pop(job_id, None)
            update_job(job_id, status="cancelled",
                       finished_at=datetime.now(timezone.utc).isoformat())
            _broadcast(job_id, {"job_id": job_id, "status": "cancelled"})
            break


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


def _start_next_queued():
    """Start the next non-cancelled queued job. Cancelled queue entries are marked
    cancelled in DB and skipped."""
    while _job_queue:
        params = _job_queue.popleft()
        jid = params.get("job_id")
        if jid is not None and _cancel_flags.get(jid):
            # Job was cancelled while queued — update DB and skip
            _cancel_flags.pop(jid, None)
            update_job(jid, status="cancelled", finished_at=datetime.now(timezone.utc).isoformat())
            _broadcast(jid, {"job_id": jid, "status": "cancelled"})
            continue
        trigger_job(**params)
        return


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

            versions = _detect_versions(job_key)
            _step_update(job_id, date, "audio", "running")
            for v in versions:
                extra_audio = ["--dry-run"] if dry_run else []
                if v:
                    extra_audio = ["--version", v] + extra_audio
                ok, out = _call_script("audio_generator.py", job_key, extra_audio, log_path)
                if not ok:
                    _step_update(job_id, date, "audio", "failed")
                    update_job(job_id, status="failed", error=out[-300:])
                    _broadcast(job_id, {"job_id": job_id, "status": "failed"})
                    return
                _check_cancel(job_id)
            _step_update(job_id, date, "audio", "done")

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
            for v in versions:
                extra_video = ["--version", v] if v else []
                ok, out = _call_script(script_name, job_key, extra_video, log_path)
                if not ok:
                    _step_update(job_id, date, "video", "failed")
                    update_job(job_id, status="failed", error=out[-300:])
                    _broadcast(job_id, {"job_id": job_id, "status": "failed"})
                    return
                _check_cancel(job_id)
            _step_update(job_id, date, "video", "done")

            # ── Step 4.5: Thumbnail (best-effort) ────────────────────────
            try:
                ok_th, _ = _call_script("thumbnail_renderer.py", job_key, [], log_path)
                if not ok_th:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write("\n[WARN] thumbnail render failed (non-fatal)\n")
            except Exception as _e:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[WARN] thumbnail render exception: {_e}\n")

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
            _start_next_queued()

    threading.Thread(target=_run, daemon=True).start()
    return True


def _now():
    return datetime.now(timezone.utc).isoformat()


def _notify_obstruction(job_id: int, bad_items: list[dict],
                         kinds: list[str], news_file: Path) -> None:
    """Send Telegram alert when the obstruction gate trips.

    Best-effort: pulls TG token + chat_id from settings. If neither is
    configured the function returns silently so the gate still works.
    """
    token = get_setting("telegram_bot_token", "")
    chat_csv = get_setting("telegram_chat_ids", "")
    if not token or not chat_csv:
        return
    chat_ids = [c.strip() for c in chat_csv.split(",") if c.strip()]
    if not chat_ids:
        return

    # Build a short message
    kinds_label = "/".join(kinds) if kinds else "unknown"
    lines = [
        f"⚠️ <b>AutoVideo Job #{job_id} 截圖被擋</b>",
        f"已暫停發布等手動 review",
        f"原因：<b>{kinds_label}</b>",
    ]
    # Include affected URLs from news.json so Jerry can recognise the source
    try:
        if news_file.exists():
            data = _json.loads(news_file.read_text(encoding="utf-8"))
            news_items = data.get("items", [])
            for r in bad_items[:3]:
                idx = r.get("idx", 0)
                if 1 <= idx <= len(news_items):
                    it = news_items[idx - 1]
                    title = (it.get("title") or "")[:60]
                    url = it.get("resolved_url") or it.get("source_url") or ""
                    lines.append(f"\n<b>#{idx}</b> {title}")
                    if url:
                        lines.append(f"URL: <code>{url[:120]}</code>")
                    lines.append(
                        f"  → {r.get('kind')} (conf {r.get('confidence')}): "
                        f"{(r.get('why') or '')[:140]}"
                    )
    except Exception:
        pass

    text = "\n".join(lines)
    import urllib.request
    for chat in chat_ids:
        try:
            payload = _json.dumps({
                "chat_id": chat,
                "text": text[:4096],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            # Best-effort; the broadcast hook will already have notified
            # the bot via on_event if running.
            pass


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
                  strategy: str | None = None,
                  autopilot: bool = False):
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
        figure_group = _figure_group_for_strategy(strategy)

        if figure_group:
            extra = ["--group", figure_group, "--strategy", strategy or ""]
            if account_profile:
                extra += ["--profile", account_profile]
            ok, out = _call_script("figure_quote_collector.py", job_key, extra, log_path)
            if not ok:
                su("news", "failed")
                raise RuntimeError(f"figure_quote_collector 失敗:\n{out[-800:]}")
        elif pre_news:
            # 用戶已選好原始新聞，Claude 只針對這幾筆生成腳本
            from web.claude_client import enrich_news_items, _last_usage
            enriched = enrich_news_items(pre_news, topic, strategy)
            # Default layout_mode by strategy: entertainment/generic → rotate
            # through 3 article-card variants; tech/finance/pet keep "visual".
            default_layout = _default_layout_for_strategy(strategy)
            news_file.write_text(
                _json.dumps(
                    {"date": job_key,
                     "account_profile": account_profile or "",
                     "strategy": strategy or "",
                     "layout_mode": default_layout,
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
            # Seed layout_mode based on strategy — news_collector.py writes
            # a minimal news.json so we patch it in place.
            try:
                if news_file.exists():
                    data = _json.loads(news_file.read_text(encoding="utf-8"))
                    if not data.get("layout_mode"):
                        data["layout_mode"] = _default_layout_for_strategy(strategy)
                        news_file.write_text(
                            _json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
            except Exception as _e:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[WARN] layout_mode seed failed: {_e}\n")

        su("news", "done")
        _check_cancel(job_id)

        # ── 暫停：等用戶確認/調整腳本 (autopilot 跳過) ────────────
        if not autopilot:
            ev_script = threading.Event()
            _pause_events[f"{job_id}_script"] = ev_script
            su("screenshot", "script_review")
            ev_script.wait()
            del _pause_events[f"{job_id}_script"]
            _check_cancel(job_id)
        else:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n[autopilot] 略過腳本 review pause\n")

        # ── Step 2: 背景素材（截圖 or B-roll）──────────────────────
        bg_mode = get_setting("background_mode", "screenshot")
        su("screenshot", "running")
        if figure_group:
            broll_file = pipe_dir / "broll" / "broll_01.mp4"
            if not broll_file.exists():
                su("screenshot", "failed")
                raise RuntimeError(f"名人原片片段不存在: {broll_file}")
            ok, out = True, "[figure_quote] using downloaded source clip as broll"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n[figure_quote] 使用原始影片片段 broll_01.mp4，略過新聞截圖\n")
        elif bg_mode == "broll":
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

        # ── Step 2.5: 文章資料擷取 (hero image + body) ─────────────
        # Best-effort: populates news.json items with hero_image_b64 / body_text
        # / byline for article_rotate / article_* layout modes. Failure is
        # non-fatal — ArticleLayer falls back to the existing screenshot.
        try:
            if figure_group:
                ok_ae, _out_ae = True, ""
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\n[figure_quote] 略過 article_extractor\n")
            else:
                ok_ae, _out_ae = _call_script("article_extractor.py", job_key, [], log_path)
            if not ok_ae:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\n[WARN] article_extractor failed (non-fatal)\n")
        except Exception as _e:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[WARN] article_extractor exception: {_e}\n")

        su("screenshot", "done")
        _check_cancel(job_id)

        # ── Step 2.6: 截圖遮擋偵測 (Obstruction Gate) ──────────────
        # screenshot_collector writes screenshots/quality.json with a per-item
        # verdict from scripts/screenshot_quality.py (Pillow heuristic + Groq
        # vision LLM). If any item is obstructed (paywall/popup/ad/cookie/
        # signup/login wall) we abort the autopilot publish path, mark the
        # job as needing manual_review, and ping Telegram so Jerry can
        # approve / replace the bad item from the UI before publish.
        screenshot_obstructed = False
        obstructed_kinds: list[str] = []
        try:
            quality_file = pipe_dir / "screenshots" / "quality.json"
            if quality_file.exists():
                qd = _json.loads(quality_file.read_text(encoding="utf-8"))
                if qd.get("any_obstructed"):
                    bad_items = [r for r in qd.get("items", [])
                                  if r.get("obstructed")]
                    obstructed_kinds = qd.get("obstructed_kinds") or sorted({
                        r.get("kind", "other") for r in bad_items
                    })
                    screenshot_obstructed = True
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write("\n[OBSTRUCTION_GATE] 截圖偵測到遮擋；將進入 manual_review\n")
                        for r in bad_items:
                            f.write(f"  - item {r.get('idx')} ({r.get('image')}): "
                                    f"kind={r.get('kind')} "
                                    f"conf={r.get('confidence')} "
                                    f"why={r.get('why', '')[:200]}\n")
                    # Mark the bad URLs as screenshot_blocked in news_cache so
                    # they get pushed to the bottom of future news pickers.
                    try:
                        from web.db import mark_news_blocked_by_url
                        if news_file.exists():
                            news_data = _json.loads(
                                news_file.read_text(encoding="utf-8")
                            )
                            news_items = news_data.get("items", [])
                            for r in bad_items:
                                idx = r.get("idx", 0)
                                if 1 <= idx <= len(news_items):
                                    it = news_items[idx - 1]
                                    bad_url = (it.get("source_url") or
                                                it.get("url") or "")
                                    if bad_url:
                                        mark_news_blocked_by_url(bad_url)
                    except Exception as _e:
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"  [WARN] mark_news_blocked failed: {_e}\n")
                    # Notify TG (best effort).
                    try:
                        _notify_obstruction(job_id, bad_items, obstructed_kinds,
                                             news_file)
                    except Exception as _e:
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"  [WARN] TG notify failed: {_e}\n")
                    # Force the run out of autopilot publish: video will still
                    # render so the operator can preview, but upload is gated
                    # behind a manual confirm in the UI.
                    if autopilot:
                        autopilot = False
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write("[OBSTRUCTION_GATE] autopilot disabled, "
                                    "upload requires manual approval.\n")
        except Exception as _e:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[WARN] obstruction gate exception (non-fatal): {_e}\n")

        # ── 暫停：等用戶確認截圖 (autopilot 跳過) ─────────────────
        if not autopilot:
            ev = threading.Event()
            _pause_events[job_id] = ev
            su("audio", "review")
            ev.wait()
            del _pause_events[job_id]
            _check_cancel(job_id)
        else:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n[autopilot] 略過截圖 review pause\n")

        # ── Step 3: 語音生成 (dual-version or legacy) ───────────────
        versions = _detect_versions(job_key)
        su("audio", "running")
        for v in versions:
            extra_audio = ["--dry-run"] if dry_run else []
            if v:
                extra_audio = ["--version", v] + extra_audio
            ok, out = _call_script("audio_generator.py", job_key, extra_audio, log_path)
            if not ok:
                su("audio", "failed")
                raise RuntimeError(f"audio_generator({v or 'legacy'}) 失敗:\n{out[-500:]}")
            _check_cancel(job_id)
        su("audio", "done")

        # ── Step 3.5: AI 圖生影片 B-roll (optional) ─────────────────
        ai_video_mode = get_setting("ai_video_mode", "").lower()
        if ai_video_mode in ("kling", "replicate"):
            su("ai_video", "running")
            ok_av, out_av = _call_script("ai_video_fetcher.py", job_key, [], log_path)
            su("ai_video", "done" if ok_av else "skipped")
            _check_cancel(job_id)

        # ── Step 4: 合成影片 (dual-version or legacy) ────────────────
        renderer = get_setting("video_renderer", "ffmpeg").lower()
        if figure_group:
            script_name = "insight_quote_composer.py"
        else:
            script_name = "remotion_renderer.py" if renderer == "remotion" else "video_composer.py"
        su("video", "running")
        for v in versions:
            extra_video = ["--version", v] if v else []
            ok, out = _call_script(script_name, job_key, extra_video, log_path)
            if not ok:
                su("video", "failed")
                raise RuntimeError(f"{script_name}({v or 'legacy'}) 失敗:\n{out[-500:]}")
            _check_cancel(job_id)
        su("video", "done")

        # ── Step 4.5: Thumbnail (best-effort) ────────────────────────
        try:
            ok_th, _ = _call_script("thumbnail_renderer.py", job_key, [], log_path)
            if not ok_th:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\n[WARN] thumbnail render failed (non-fatal)\n")
        except Exception as _e:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[WARN] thumbnail render exception: {_e}\n")

        # ── Step 5: 上傳 ──────────────────────────────────────────
        # Resolve output_mp4 — dual-version jobs write to short/output.mp4
        # (or long/output.mp4); legacy jobs write to pipe_dir/output.mp4.
        # UI reads this path to render the video preview.
        candidates = [
            pipe_dir / "output.mp4",
            pipe_dir / "short" / "output.mp4",
            pipe_dir / "long"  / "output.mp4",
        ]
        output_mp4 = next((p for p in candidates if p.exists()), candidates[0])

        # Seed platform_meta.json on disk if missing — publisher reads this to
        # route per-platform video_version (short vs long) and FB page_id. UI
        # normally seeds via GET /api/jobs/{id}/platform_meta, but autopilot
        # bypasses the UI entirely.
        meta_file = pipe_dir / "platform_meta.json"
        if not meta_file.exists() and news_file.exists():
            try:
                from web.routes.jobs import _seed_platform_meta
                news_data = _json.loads(news_file.read_text(encoding="utf-8"))
                seed = _seed_platform_meta(news_data)
                meta_file.write_text(
                    _json.dumps(seed, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as _e:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[WARN] platform_meta seed failed: {_e}\n")

        if autopilot and not skip_upload:
            # Autopilot 直接發布，不等 UI 點擊
            update_job(job_id, step_upload="uploading")
            plat_args = ["--platforms"] + platforms
            if dry_run:
                plat_args += ["--dry-run"]
            if account_profile:
                plat_args += ["--profile", account_profile]
            ok_pub, out_pub = _call_script("publisher.py", job_key, plat_args, log_path)
            # Distinguish dry-run preview from real upload in the UI so users
            # don't think an un-published job was pushed to the platforms.
            if not ok_pub:
                final_state = "failed"
            elif dry_run:
                final_state = "dry_run"
            else:
                final_state = "done"
            update_job(job_id, step_upload=final_state)
            if not ok_pub:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[autopilot] publisher 失敗:\n{out_pub[-500:]}\n")
        elif screenshot_obstructed:
            # Render finished but upload is gated behind manual review.
            su("upload", "manual_review")
        else:
            su("upload", "pending")

        # ── 完成 ────────────────────────────────────────────────────
        if screenshot_obstructed:
            update_job(job_id, status="manual_review", finished_at=_now(),
                       output_path=str(output_mp4))
            _broadcast(job_id, {"job_id": job_id, "status": "manual_review",
                                  "output_path": str(output_mp4),
                                  "screenshot_obstructed": True,
                                  "obstructed_kinds": obstructed_kinds})
        else:
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
        _start_next_queued()


def trigger_job(job_id: int, date: str, topic: str | None = None,
                platforms: list[str] = None, skip_upload: bool = False,
                dry_run: bool = False,
                pre_news: list[dict] | None = None,
                account_profile: str | None = None,
                strategy: str | None = None,
                autopilot: bool = False) -> bool:
    """Returns True always — job runs immediately or is enqueued for sequential execution."""
    global _running_job_id
    if platforms is None:
        platforms = get_setting("platforms", "youtube,instagram").split(",")
    if not _lock.acquire(blocking=False):
        _job_queue.append({
            "job_id": job_id, "date": date, "topic": topic,
            "platforms": platforms, "skip_upload": skip_upload,
            "dry_run": dry_run, "pre_news": pre_news,
            "account_profile": account_profile,
            "strategy": strategy,
            "autopilot": autopilot,
        })
        return True
    _running_job_id = job_id
    t = threading.Thread(
        target=_run_pipeline,
        args=(job_id, date, topic, platforms, skip_upload, dry_run,
              pre_news, account_profile, strategy, autopilot),
        daemon=True,
    )
    t.start()
    return True
