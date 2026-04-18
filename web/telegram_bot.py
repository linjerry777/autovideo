"""
web/telegram_bot.py — Telegram Bot for AutoVideo remote control

Commands (from phone):
  /run [topic]  — trigger pipeline
  /status       — current job status
  /cancel       — cancel running job
  /jobs         — last 5 jobs
  /help         — show commands

Review pauses send inline buttons so you can approve from phone.
Final MP4 is sent directly to Telegram when done.

Setup:
  1. Message @BotFather → /newbot → copy TOKEN
  2. Message @userinfobot → copy your Chat ID
  3. Add both in Settings page → Restart server
"""
import json, sys, threading, time, urllib.error, urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


# ── Low-level Telegram API helpers ───────────────────────────────────────────

def _api(token: str, method: str, **kwargs) -> dict:
    url  = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(kwargs).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "description": e.read().decode("utf-8", errors="replace")}
    except Exception as e:
        return {"ok": False, "description": str(e)}


def _send(token: str, chat_id: str, text: str,
          reply_markup: dict = None, parse_mode: str = "HTML") -> dict:
    kwargs = dict(chat_id=chat_id, text=text[:4096], parse_mode=parse_mode)
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    return _api(token, "sendMessage", **kwargs)


def _answer_callback(token: str, callback_id: str, text: str = ""):
    _api(token, "answerCallbackQuery", callback_query_id=callback_id, text=text)


def _send_file(token: str, chat_id: str, path: Path, caption: str = "") -> dict:
    """Send a file via multipart/form-data (works for video and document)."""
    boundary = "TGBotBoundary42"
    mime = "video/mp4" if path.suffix.lower() == ".mp4" else "application/octet-stream"
    field  = "video" if mime == "video/mp4" else "document"

    header_str = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        + (f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n' if caption else "")
        + f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    )
    body = header_str.encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")

    url = f"https://api.telegram.org/bot{token}/send{'Video' if field=='video' else 'Document'}"
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "description": str(e)}


# ── Inline keyboard helpers ───────────────────────────────────────────────────

def _inline_kb(*rows: list[tuple[str, str]]) -> dict:
    """rows: list of [(label, callback_data), ...]"""
    return {"inline_keyboard": [[{"text": l, "callback_data": d} for l, d in row] for row in rows]}


# ── Bot class ─────────────────────────────────────────────────────────────────

class TelegramBot:
    def __init__(self, token: str, allowed_chat_ids: set[str]):
        self.token = token
        self.allowed_chat_ids = allowed_chat_ids
        self._offset = 0
        self._running = False
        self._thread: threading.Thread | None = None
        # Track which chat triggered the active job
        self._job_chat: str | None = None
        self._active_job_id: int | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="tg-bot")
        self._thread.start()
        print("[TG Bot] Started", flush=True)

    def stop(self):
        self._running = False
        print("[TG Bot] Stopped", flush=True)

    # ── Job event hook (called by job_runner._broadcast) ─────────────────────

    def on_event(self, job_id: int, data: dict):
        # Pick recipient:
        #   - Bot-triggered job → the chat that ran /run (1:1 feedback)
        #   - Anything else (UI click, scheduler cron) → broadcast to all allowed_chat_ids
        #     so the user gets pings even for jobs they started at the computer and then
        #     walked away from.
        if self._job_chat and job_id == self._active_job_id:
            targets = [self._job_chat]
        elif self.allowed_chat_ids:
            targets = sorted(self.allowed_chat_ids)
        else:
            return
        for chat in targets:
            self._dispatch_event(chat, job_id, data)

    def _dispatch_event(self, chat: str, job_id: int, data: dict):

        STEP_LABELS = {
            "step_news":       "📰 新聞收集",
            "step_screenshot": "📸 截圖/素材",
            "step_audio":      "🔊 語音生成",
            "step_ai_video":   "🎬 AI 圖生影片",
            "step_video":      "🎞️ 影片合成",
            "step_upload":     "📤 上傳發布",
        }

        for key, label in STEP_LABELS.items():
            val = data.get(key)
            if val == "running":
                _send(self.token, chat, f"⏳ {label} 進行中…")
            elif val == "done":
                _send(self.token, chat, f"✅ {label} 完成")
            elif val == "failed":
                _send(self.token, chat, f"❌ {label} 失敗")
            elif val == "skipped":
                _send(self.token, chat, f"⏭️ {label} 跳過")
            elif val == "script_review":
                # 讀取腳本內容傳到 Telegram
                self._send_script_preview(chat, job_id)
                kb = _inline_kb(
                    [("✅ 確認腳本，繼續", f"resume_script:{job_id}"),
                     ("❌ 取消 Job",      f"cancel:{job_id}")]
                )
                _send(self.token, chat,
                      "確認後開始截圖，或至 Web UI 調整內容。",
                      reply_markup=kb)
            elif val == "review":
                kb = _inline_kb(
                    [("✅ 確認截圖，繼續", f"resume_shot:{job_id}"),
                     ("❌ 取消 Job",       f"cancel:{job_id}")]
                )
                _send(self.token, chat,
                      "🖼️ <b>截圖已收集，請確認後繼續</b>",
                      reply_markup=kb)
            elif val == "pending" and key == "step_upload":
                _send(self.token, chat, "⏸️ 影片完成，等待手動上傳（可至 Web UI 發布）")

        status = data.get("status")
        if status == "done":
            self._deliver_video(chat, job_id)
            self._job_chat = None
            self._active_job_id = None
        elif status == "failed":
            err = data.get("error", "未知錯誤")
            _send(self.token, chat, f"💥 Pipeline 失敗：{err[:300]}")
            self._job_chat = None
            self._active_job_id = None
        elif status == "cancelled":
            _send(self.token, chat, "🚫 Job 已取消")
            self._job_chat = None
            self._active_job_id = None

    def _send_script_preview(self, chat: str, job_id: int):
        """Read news.json and send each item's script to Telegram."""
        try:
            from web.db import get_job
            import json as _json
            job = get_job(job_id)
            if not job:
                return
            news_file = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "news.json"
            if not news_file.exists():
                _send(self.token, chat, "📝 <b>腳本已生成</b>（找不到 news.json）")
                return
            data  = _json.loads(news_file.read_text(encoding="utf-8"))
            items = data.get("items", [])
            if not items:
                _send(self.token, chat, "📝 <b>腳本已生成</b>（無內容）")
                return

            SCENE_EMOJI = {
                "fire": "🔥", "race": "🏃", "money": "💰",
                "robot": "🤖", "warning": "⚠️", "trophy": "🏆", "default": "📄",
            }
            lines = [f"📝 <b>腳本預覽（共 {len(items)} 則）</b>\n"]
            for i, item in enumerate(items, 1):
                hook    = item.get("hook", "")
                title   = item.get("title", "")
                script  = item.get("script", "")
                scene   = item.get("scene_type", "default")
                emoji   = SCENE_EMOJI.get(scene, "📄")
                lines.append(
                    f"<b>【{i}】{hook}</b> {emoji}\n"
                    f"{title}\n"
                    f"<i>{script[:120]}</i>\n"
                )
            _send(self.token, chat, "\n".join(lines))
        except Exception as e:
            _send(self.token, chat, f"📝 <b>腳本已生成</b>（讀取失敗：{e}）")

    def _deliver_video(self, chat: str, job_id: int):
        from web.db import get_job
        job = get_job(job_id)
        if not job:
            _send(self.token, chat, "🎉 完成！（找不到輸出路徑）")
            return
        mp4 = Path(job.get("output_path") or "")
        if not mp4.exists():
            _send(self.token, chat, f"🎉 Pipeline 完成！\n找不到 MP4，請至 Web UI 下載。")
            return
        size_mb = mp4.stat().st_size / 1024 / 1024
        if size_mb > 50:
            _send(self.token, chat,
                  f"🎉 影片完成！檔案 {size_mb:.1f} MB 超過 Telegram 限制，請至 Web UI 下載。\n"
                  f"路徑：<code>{mp4}</code>")
            return
        _send(self.token, chat, f"🎉 影片完成！({size_mb:.1f} MB) 傳送中…")
        result = _send_file(self.token, chat, mp4, caption=f"AutoVideo #{job_id}")
        if not result.get("ok"):
            _send(self.token, chat,
                  f"⚠️ 傳送失敗：{result.get('description','')}\n請至 Web UI 下載。")

    # ── Command handlers ──────────────────────────────────────────────────────

    def _cmd_help(self, chat: str):
        _send(self.token, chat,
              "🎬 <b>AutoVideo Bot</b>\n\n"
              "<b>新聞模式</b>\n"
              "/run — 觸發新聞影片（預設主題）\n"
              "/run AI科技 — 指定主題\n\n"
              "<b>趨勢模式</b>（YouTube TW 熱門第 1 則）\n"
              "/trending — 預設娛樂策略\n"
              "/trending tech — 指定策略 (tech|entertainment|finance|pet)\n\n"
              "<b>管理</b>\n"
              "/status — 查看目前狀態\n"
              "/cancel — 取消執行中的 job\n"
              "/jobs — 最近 5 筆記錄\n"
              "/help — 顯示此說明")

    def _cmd_run(self, chat: str, topic: str | None):
        from web import job_runner
        from web.db import create_job, get_setting
        from datetime import date

        if job_runner.is_running():
            _send(self.token, chat, "⚠️ 已有 job 在執行，請先等待或 /cancel")
            return

        today    = date.today().isoformat()
        platforms = get_setting("platforms", "youtube,instagram").split(",")
        dry_run  = get_setting("dry_run", "false").lower() == "true"

        job_id = create_job(today, triggered_by="telegram", topic=topic)
        self._job_chat      = chat
        self._active_job_id = job_id

        ok = job_runner.trigger_job(job_id, today, topic=topic,
                                    platforms=platforms, dry_run=dry_run)
        if ok:
            label = f"「{topic}」" if topic else "（預設主題）"
            _send(self.token, chat, f"🚀 Job #{job_id} 啟動 {label}\n進度更新稍後自動傳送…")
        else:
            _send(self.token, chat, "❌ 啟動失敗（鎖定中）")
            self._job_chat      = None
            self._active_job_id = None

    def _cmd_trending(self, chat: str, strategy: str | None):
        """Fetch top YouTube TW trending item → enrich → trigger job with strategy."""
        from web import job_runner
        from web.db import create_job, get_setting
        from web.routes.news import _fetch_youtube_trending
        from datetime import date

        if job_runner.is_running():
            _send(self.token, chat, "⚠️ 已有 job 在執行，請先等待或 /cancel")
            return

        strategy = (strategy or "entertainment").lower()
        if strategy not in ("tech", "entertainment", "finance", "pet"):
            _send(self.token, chat, f"❌ 策略必須是 tech/entertainment/finance/pet 之一（你給的：{strategy}）")
            return

        _send(self.token, chat, f"📡 抓 YouTube TW 熱門 #1…")
        try:
            raw_items = _fetch_youtube_trending(region="TW", limit=5)
        except Exception as e:
            _send(self.token, chat, f"❌ 抓熱門失敗：{e}")
            return
        if not raw_items:
            _send(self.token, chat, "❌ 沒抓到熱門影片（API key 可能沒設）")
            return

        first = raw_items[0]
        # Raw YouTube-trending item has 'source'/'title'/'summary'/'url' — pipeline's
        # enrich_news_items(strategy=...) consumes it directly. Do NOT pre-enrich via
        # enrich_trending_items here: pipeline would then re-enrich and KeyError on 'source'.
        today     = date.today().isoformat()
        platforms = get_setting("platforms", "youtube,instagram").split(",")
        dry_run   = get_setting("dry_run", "false").lower() == "true"

        job_id = create_job(today, triggered_by="telegram", topic=first["title"][:40])
        self._job_chat      = chat
        self._active_job_id = job_id

        ok = job_runner.trigger_job(
            job_id, today,
            topic=None,
            platforms=platforms,
            dry_run=dry_run,
            pre_news=[first],       # raw YouTube item; pipeline's Claude enrich handles rest
            strategy=strategy,
        )
        if ok:
            _send(self.token, chat,
                  f"🎯 選到：{first['title'][:60]}\n"
                  f"🚀 Job #{job_id} 啟動，策略 {strategy}\n"
                  f"🤖 Claude 生腳本 + 截圖 + 語音 + 影片合成中…\n"
                  f"進度 / 審核暫停點都會自動推播")
        else:
            _send(self.token, chat, "❌ 啟動失敗")
            self._job_chat = None
            self._active_job_id = None

    def _cmd_status(self, chat: str):
        from web import job_runner
        from web.db import get_job, list_jobs

        running_id = job_runner.get_running_job_id()
        if running_id:
            job = get_job(running_id)
            if job:
                STEPS = [
                    ("step_news",       "新聞"),
                    ("step_screenshot", "截圖"),
                    ("step_audio",      "語音"),
                    ("step_ai_video",   "AI影片"),
                    ("step_video",      "合成"),
                    ("step_upload",     "上傳"),
                ]
                ICONS = {"done":"✅","running":"⏳","failed":"❌",
                         "pending":"⬜","skipped":"⏭️","review":"⏸️",
                         "script_review":"⏸️"}
                lines = [f"🔄 <b>Job #{running_id} 執行中</b>"]
                for key, label in STEPS:
                    val = job.get(key, "pending")
                    lines.append(f"  {ICONS.get(val,'❓')} {label}: {val}")
                _send(self.token, chat, "\n".join(lines))
                return
        jobs = list_jobs(limit=1)
        if jobs:
            j = jobs[0]
            _send(self.token, chat,
                  f"最後一筆：Job #{j['id']} · {j['date']} · <b>{j['status']}</b>")
        else:
            _send(self.token, chat, "目前沒有 job 記錄")

    def _cmd_cancel(self, chat: str):
        from web import job_runner
        job_id = job_runner.get_running_job_id()
        if not job_id:
            _send(self.token, chat, "目前沒有執行中的 job")
            return
        job_runner.cancel_job(job_id)
        _send(self.token, chat, f"🚫 取消指令已送出（Job #{job_id}）")

    def _cmd_jobs(self, chat: str):
        from web.db import list_jobs
        jobs = list_jobs(limit=5)
        if not jobs:
            _send(self.token, chat, "尚無記錄")
            return
        ICONS = {"done":"✅","failed":"❌","running":"🔄",
                 "cancelled":"🚫","queued":"⬜"}
        lines = ["📋 <b>最近 5 筆 job</b>"]
        for j in jobs:
            icon  = ICONS.get(j["status"], "❓")
            topic = f" 「{j['topic']}」" if j.get("topic") else ""
            lines.append(f"{icon} #{j['id']} {j['date']}{topic} [{j['status']}]")
        _send(self.token, chat, "\n".join(lines))

    # ── Callback query handler (inline buttons) ───────────────────────────────

    def _handle_callback(self, cb: dict):
        chat      = str(cb.get("message", {}).get("chat", {}).get("id", ""))
        cb_id     = cb.get("id", "")
        data      = cb.get("data", "")

        if self.allowed_chat_ids and chat not in self.allowed_chat_ids:
            _answer_callback(self.token, cb_id, "⛔ 未授權")
            return

        if data.startswith("resume_script:"):
            job_id = int(data.split(":")[1])
            from web import job_runner
            job_runner.resume_job(job_id, key=f"{job_id}_script")
            _answer_callback(self.token, cb_id, "✅ 腳本確認，繼續")

        elif data.startswith("resume_shot:"):
            job_id = int(data.split(":")[1])
            from web import job_runner
            job_runner.resume_job(job_id)
            _answer_callback(self.token, cb_id, "✅ 截圖確認，繼續")

        elif data.startswith("cancel:"):
            job_id = int(data.split(":")[1])
            from web import job_runner
            job_runner.cancel_job(job_id)
            _answer_callback(self.token, cb_id, "🚫 取消中…")

    # ── Message handler ───────────────────────────────────────────────────────

    def _handle_message(self, msg: dict):
        chat = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        if self.allowed_chat_ids and chat not in self.allowed_chat_ids:
            _send(self.token, chat, "⛔ 未授權")
            return

        parts = text.split(maxsplit=1)
        cmd   = parts[0].split("@")[0].lower()
        arg   = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/start", "/help"):
            self._cmd_help(chat)
        elif cmd == "/run":
            self._cmd_run(chat, arg or None)
        elif cmd == "/trending":
            self._cmd_trending(chat, arg or None)
        elif cmd == "/status":
            self._cmd_status(chat)
        elif cmd == "/cancel":
            self._cmd_cancel(chat)
        elif cmd == "/jobs":
            self._cmd_jobs(chat)

    # ── Long-polling loop ─────────────────────────────────────────────────────

    def _poll_loop(self):
        while self._running:
            try:
                url = (f"https://api.telegram.org/bot{self.token}/getUpdates"
                       f"?offset={self._offset}&timeout=20")
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())

                if not data.get("ok"):
                    time.sleep(5)
                    continue

                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    try:
                        if msg := (update.get("message") or update.get("edited_message")):
                            self._handle_message(msg)
                        elif cb := update.get("callback_query"):
                            self._handle_callback(cb)
                    except Exception as e:
                        print(f"[TG Bot] Handler error: {e}", file=sys.stderr)

            except Exception as e:
                if self._running:
                    print(f"[TG Bot] Poll error: {e}", file=sys.stderr)
                    time.sleep(5)


# ── Module-level singleton ────────────────────────────────────────────────────

_bot: TelegramBot | None = None


def start_bot(token: str, chat_ids: set[str]) -> TelegramBot:
    global _bot
    stop_bot()
    from web import job_runner
    _bot = TelegramBot(token, chat_ids)
    job_runner.add_step_hook(_bot.on_event)
    _bot.start()
    return _bot


def stop_bot():
    global _bot
    if _bot:
        from web import job_runner
        job_runner.remove_step_hook(_bot.on_event)
        _bot.stop()
        _bot = None
