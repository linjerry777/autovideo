import os
import requests as _req
from fastapi import APIRouter
from pydantic import BaseModel
from web.db import get_all_settings, set_setting
from web import scheduler_service

router = APIRouter(prefix="/api")


class SettingsUpdate(BaseModel):
    schedule_hour:   str | None = None
    schedule_minute: str | None = None
    platforms:       str | None = None
    skip_upload:     str | None = None
    dry_run:         str | None = None
    # LLM
    llm_provider:    str | None = None   # "claude" | "ollama"
    llm_model:       str | None = None
    llm_proxy_url:   str | None = None
    # API Keys
    fish_audio_key:  str | None = None
    upload_post_key: str | None = None
    unsplash_key:    str | None = None
    pexels_api_key:  str | None = None
    youtube_api_key: str | None = None
    voice_id:        str | None = None
    x_keywords:      str | None = None
    # 背景模式
    background_mode:      str | None = None   # "screenshot" | "broll" | "playwright_stealth"
    # AI 圖生影片
    ai_video_mode:        str | None = None   # "" | "kling" | "replicate"
    kling_access_key:     str | None = None
    kling_secret_key:     str | None = None
    replicate_api_token:  str | None = None
    # Telegram Bot
    telegram_bot_token:   str | None = None
    telegram_chat_ids:    str | None = None   # comma-separated chat IDs
    # 影片渲染器
    video_renderer:       str | None = None   # "ffmpeg" | "remotion"


@router.get("/settings")
def get_settings():
    s = get_all_settings()
    # Expose whether optional API keys are configured (without revealing the key)
    # DB key takes priority over .env
    s["youtube_key_set"] = bool(s.get("youtube_api_key") or os.getenv("YOUTUBE_API_KEY", ""))
    return s


@router.put("/settings")
def update_settings(body: SettingsUpdate):
    updated = body.model_dump(exclude_none=True)
    for k, v in updated.items():
        set_setting(k, str(v))

    if "schedule_hour" in updated or "schedule_minute" in updated:
        s = get_all_settings()
        scheduler_service.update_schedule(
            int(s.get("schedule_hour", 8)),
            int(s.get("schedule_minute", 0)),
        )

    return get_all_settings()


@router.get("/llm/models")
def list_llm_models(url: str = None):
    """列出 Ollama 已安裝的模型。
    url 參數可直接傳入 Ollama 位址（前端選完但尚未存檔時用）。
    """
    from web.db import get_setting

    # 優先順序：query param > DB > env default
    if url:
        ollama_url = url
    else:
        db_url = get_setting("llm_proxy_url", "")
        ollama_url = db_url or os.getenv("CLAUDE_PROXY_URL", "http://localhost:11434")

    # 若不是 Ollama（沒有 11434），直接回傳 Claude 選項
    if "11434" not in ollama_url:
        return {"provider": "claude", "models": []}

    try:
        r = _req.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        return {"provider": "ollama", "models": models}
    except Exception as e:
        return {"provider": "ollama", "models": [], "error": f"Ollama 未啟動或連線失敗：{e}"}
