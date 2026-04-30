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
    # Trending account profiles
    trending_profile_tech:          str | None = None
    trending_profile_entertainment: str | None = None
    trending_profile_finance:       str | None = None
    trending_profile_pet:           str | None = None
    # Autopilot (daily auto-run at schedule_hour:schedule_minute)
    autopilot_enabled:              str | None = None
    autopilot_dry_run:              str | None = None
    autopilot_news_enabled:         str | None = None
    autopilot_trending_enabled:     str | None = None
    autopilot_news_strategy:        str | None = None
    autopilot_news_profile:         str | None = None
    autopilot_trending_strategy:    str | None = None
    autopilot_trending_profile:     str | None = None
    autopilot_platforms:            str | None = None
    # ManyChat funnel — caption + first_comment 帶 keyword 引流到部落格
    cta_kw_tech:                    str | None = None
    cta_kw_entertain:               str | None = None
    cta_blog_url:                   str | None = None


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


@router.post("/autopilot/run")
def autopilot_run_now():
    """Manually trigger the autopilot daily_job — useful for testing."""
    scheduler_service.run_now()
    return {"ok": True}


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


from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MUSIC_EMOTIONS = ["surprise", "fear", "joy", "curiosity", "anger", "generic"]


@router.get("/assets/status")
def get_assets_status():
    """Count MP3 files in assets/music/* and assets/sfx/hook."""
    music_root = BASE_DIR / "assets" / "music"
    sfx_root   = BASE_DIR / "assets" / "sfx" / "hook"

    music = {}
    for emotion in MUSIC_EMOTIONS:
        folder = music_root / emotion
        if folder.exists() and folder.is_dir():
            music[emotion] = len([p for p in folder.iterdir() if p.suffix.lower() == ".mp3" and p.is_file()])
        else:
            music[emotion] = 0

    sfx_count = 0
    if sfx_root.exists() and sfx_root.is_dir():
        sfx_count = len([p for p in sfx_root.iterdir() if p.suffix.lower() == ".mp3" and p.is_file()])

    total = sum(music.values()) + sfx_count
    return {
        "music":       music,
        "sfx_hook":    sfx_count,
        "total_files": total,
    }
