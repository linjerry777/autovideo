"""APScheduler wiring for AutoVideo autopilot.

The active daily flow is intentionally small:
1. news autopilot
2. entertainment/trending autopilot
3. tech figure source-video analysis

Older strategy metadata such as ``figure_entertainment`` remains available in
routes and publisher metadata for historical jobs, but the scheduler no longer
creates entertainment figure jobs automatically.
"""

from __future__ import annotations

import logging
import re
from datetime import date as date_cls

from apscheduler.schedulers.background import BackgroundScheduler

from web import job_runner
from web.db import create_job, get_setting

log = logging.getLogger("scheduler_service")

_scheduler = BackgroundScheduler()

_DEFAULT_PLATFORMS = "youtube,instagram,facebook,threads,x,linkedin"
_DEFAULT_NEWS_SOURCES = "google,bing,hackernews,ithome,last30days"
_DEFAULT_NEWS_KEYWORDS = (
    "AI,ChatGPT,Claude,Gemini,LLM,agent,agents,GPU,Nvidia,OpenAI,"
    "Anthropic,Meta,Google,Microsoft"
)


def _bool_setting(key: str, default: bool) -> bool:
    return str(get_setting(key, str(default).lower())).lower() == "true"


def _csv_setting(key: str, default: str) -> list[str]:
    raw = get_setting(key, default) or default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _keyword_matcher(keywords: list[str]):
    english = [k for k in keywords if re.fullmatch(r"[A-Za-z0-9]+", k)]
    non_english = [k for k in keywords if k not in english]
    pattern = (
        re.compile(r"\b(" + "|".join(re.escape(k) for k in english) + r")\b", re.IGNORECASE)
        if english
        else None
    )

    def _matches(text: str) -> bool:
        if not text:
            return False
        if any(k in text for k in non_english):
            return True
        return bool(pattern and pattern.search(text))

    return _matches


def _pick_news_items(n: int = 3) -> list[dict]:
    """Fetch multi-source AI news, filter weak matches, and skip used URLs."""
    try:
        from web.routes.news import _fetch_all, _load_used_urls
    except Exception as exc:
        log.warning("[autopilot] news fetch import failed: %s", exc)
        return []

    sources = _csv_setting("autopilot_news_sources", _DEFAULT_NEWS_SOURCES)
    keywords = _csv_setting("autopilot_news_keywords", _DEFAULT_NEWS_KEYWORDS)
    keyword = keywords[0] if keywords else "AI"

    try:
        raw = _fetch_all(keyword=keyword, lang="zh-TW", sources=sources)
    except Exception as exc:
        log.warning("[autopilot] _fetch_all failed: %s", exc)
        return []
    if not raw:
        return []

    matches = _keyword_matcher(keywords)
    used_urls = _load_used_urls()
    seen_urls: set[str] = set()
    picked: list[dict] = []

    for item in raw:
        url = item.get("url", "")
        if not url or url in used_urls or url in seen_urls:
            continue
        haystack = f"{item.get('title', '')} {item.get('summary', '')}"
        if keywords and not matches(haystack):
            continue
        seen_urls.add(url)
        picked.append(
            {
                "title": item.get("title", ""),
                "summary": item.get("summary", "") or item.get("title", ""),
                "url": url,
                "source": item.get("source", ""),
                "source_type": item.get("source_type", "google"),
            }
        )
        if len(picked) >= n:
            break

    return picked


def _fire_news_autopilot(today: str, platforms: list[str], dry_run: bool) -> None:
    strategy = get_setting("autopilot_news_strategy", "generic") or "generic"
    profile = get_setting("autopilot_news_profile", "pet") or "pet"
    items = _pick_news_items(n=3)

    job_id = create_job(date=today, triggered_by="autopilot_news", platforms=",".join(platforms))
    if items:
        log.info(
            "[autopilot] news job %s multi-source (%d items) strategy=%s profile=%s dry_run=%s",
            job_id,
            len(items),
            strategy,
            profile,
            dry_run,
        )
        pre_news = items
    else:
        log.info("[autopilot] news job %s multi-source empty; falling back to news_collector.py", job_id)
        pre_news = None

    job_runner.trigger_job(
        job_id=job_id,
        date=today,
        topic=None,
        platforms=platforms,
        dry_run=dry_run,
        pre_news=pre_news,
        account_profile=profile,
        strategy=strategy,
        autopilot=True,
    )


def _pick_trending_items(n: int = 1) -> list[dict]:
    """Pick top trending items by view count across configured sources."""
    try:
        from web.routes.news import _fetch_all, _load_used_urls
    except Exception as exc:
        log.warning("[autopilot] trending fetch import failed: %s", exc)
        return []

    sources = _csv_setting("autopilot_trending_sources", "youtube_tw,youtube_us") or ["youtube_tw"]
    used_urls = _load_used_urls()
    seen_urls: set[str] = set()
    merged: list[dict] = []

    for source in sources:
        try:
            raw = _fetch_all(keyword="", lang="zh-TW", sources=[source])
        except Exception as exc:
            log.warning("[autopilot] trending fetch %s failed: %s", source, exc)
            continue
        for item in raw or []:
            url = item.get("url", "")
            if not url or url in used_urls or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(item)

    merged.sort(key=lambda item: int(item.get("view_count") or 0), reverse=True)
    return [
        {
            "title": item.get("title", ""),
            "summary": item.get("summary", "") or item.get("title", ""),
            "url": item.get("url", ""),
            "source": item.get("source", "YouTube"),
            "source_type": item.get("source_type", "youtube"),
            "view_count": item.get("view_count"),
        }
        for item in merged[:n]
    ]


def _fire_trending_autopilot(today: str, platforms: list[str], dry_run: bool) -> None:
    items = _pick_trending_items(n=1)
    if not items:
        log.info("[autopilot] all configured trends already used; skipping trending job")
        return

    strategy = get_setting("autopilot_trending_strategy", "entertainment") or "entertainment"
    profile = get_setting("autopilot_trending_profile", "pet") or "pet"
    job_id = create_job(date=today, triggered_by="autopilot_trending", platforms=",".join(platforms))
    log.info(
        "[autopilot] trending job %s item=%s strategy=%s profile=%s dry_run=%s",
        job_id,
        items[0]["title"][:50],
        strategy,
        profile,
        dry_run,
    )
    job_runner.trigger_job(
        job_id=job_id,
        date=today,
        topic=None,
        platforms=platforms,
        dry_run=dry_run,
        pre_news=items,
        account_profile=profile,
        strategy=strategy,
        autopilot=True,
    )


def _fire_figure_autopilot(today: str, platforms: list[str], dry_run: bool) -> None:
    """Create one tech figure source-video quote-analysis job."""
    strategy = "figure_tech"
    profile = get_setting("autopilot_figure_tech_profile", "yt") or "yt"
    topic = "科技大咖"
    job_id = create_job(
        date=today,
        triggered_by="autopilot_figure_tech",
        topic=topic,
        platforms=",".join(platforms),
    )
    log.info(
        "[autopilot] figure job %s strategy=%s profile=%s dry_run=%s",
        job_id,
        strategy,
        profile,
        dry_run,
    )
    job_runner.trigger_job(
        job_id=job_id,
        date=today,
        topic=topic,
        platforms=platforms,
        dry_run=dry_run,
        pre_news=None,
        account_profile=profile,
        strategy=strategy,
        autopilot=True,
    )


def _read_autopilot_runtime_settings() -> tuple[str, list[str], bool]:
    today = date_cls.today().isoformat()
    platforms = _csv_setting("autopilot_platforms", _DEFAULT_PLATFORMS)
    dry_run = _bool_setting("autopilot_dry_run", True)
    return today, platforms, dry_run


def _news_cron_job() -> None:
    if not _bool_setting("autopilot_enabled", False):
        _legacy_daily()
        return
    if not _bool_setting("autopilot_news_enabled", True):
        return
    today, platforms, dry_run = _read_autopilot_runtime_settings()
    _fire_news_autopilot(today, platforms, dry_run)


def _trending_cron_job() -> None:
    if not _bool_setting("autopilot_enabled", False):
        return
    if not _bool_setting("autopilot_trending_enabled", True):
        return
    today, platforms, dry_run = _read_autopilot_runtime_settings()
    _fire_trending_autopilot(today, platforms, dry_run)


def _figure_tech_cron_job() -> None:
    if not _bool_setting("autopilot_enabled", False):
        return
    if not _bool_setting("autopilot_figure_enabled", True):
        return
    today, platforms, dry_run = _read_autopilot_runtime_settings()
    _fire_figure_autopilot(today, platforms, dry_run)


def _daily_job() -> None:
    """Manual "run autopilot now" path used by the UI."""
    if not _bool_setting("autopilot_enabled", False):
        _legacy_daily()
        return

    today, platforms, dry_run = _read_autopilot_runtime_settings()
    if _bool_setting("autopilot_news_enabled", True):
        _fire_news_autopilot(today, platforms, dry_run)
    if _bool_setting("autopilot_trending_enabled", True):
        _fire_trending_autopilot(today, platforms, dry_run)
    if _bool_setting("autopilot_figure_enabled", True):
        _fire_figure_autopilot(today, platforms, dry_run)


def _legacy_daily() -> None:
    """Pre-autopilot behavior: create one job and let the normal pipeline run."""
    today = date_cls.today().isoformat()
    platforms = _csv_setting("platforms", "youtube,instagram")
    dry_run = get_setting("dry_run", "false") == "true"
    job_id = create_job(date=today, triggered_by="schedule", platforms=",".join(platforms))
    job_runner.trigger_job(job_id=job_id, date=today, platforms=platforms, dry_run=dry_run)


def _offset_hours_setting(key: str, default: int) -> int:
    try:
        return max(0, min(23, int(get_setting(key, str(default)))))
    except (TypeError, ValueError):
        return default


def _trending_offset_hours() -> int:
    return _offset_hours_setting("autopilot_trending_offset_hours", 4)


def _figure_tech_offset_hours() -> int:
    return _offset_hours_setting("autopilot_figure_tech_offset_hours", 8)


def _remove_disabled_jobs() -> None:
    for job_id in ("autopilot_figure_entertainment",):
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)


def start(hour: int = 8, minute: int = 0) -> None:
    trending_offset = _trending_offset_hours()
    figure_tech_offset = _figure_tech_offset_hours()
    trending_hour = (hour + trending_offset) % 24
    figure_tech_hour = (hour + figure_tech_offset) % 24

    _scheduler.add_job(_news_cron_job, "cron", hour=hour, minute=minute, id="autopilot_news", replace_existing=True)
    _scheduler.add_job(
        _trending_cron_job,
        "cron",
        hour=trending_hour,
        minute=minute,
        id="autopilot_trending",
        replace_existing=True,
    )
    _scheduler.add_job(
        _figure_tech_cron_job,
        "cron",
        hour=figure_tech_hour,
        minute=minute,
        id="autopilot_figure_tech",
        replace_existing=True,
    )
    _remove_disabled_jobs()
    log.info(
        "[autopilot] schedule registered news=%02d:%02d trending=%02d:%02d (+%dh) "
        "figure_tech=%02d:%02d (+%dh)",
        hour,
        minute,
        trending_hour,
        minute,
        trending_offset,
        figure_tech_hour,
        minute,
        figure_tech_offset,
    )
    if not _scheduler.running:
        _scheduler.start()


def update_schedule(hour: int, minute: int) -> None:
    if not _scheduler.running:
        return
    trending_offset = _trending_offset_hours()
    figure_tech_offset = _figure_tech_offset_hours()
    trending_hour = (hour + trending_offset) % 24
    figure_tech_hour = (hour + figure_tech_offset) % 24

    _scheduler.add_job(_news_cron_job, "cron", hour=hour, minute=minute, id="autopilot_news", replace_existing=True)
    _scheduler.add_job(
        _trending_cron_job,
        "cron",
        hour=trending_hour,
        minute=minute,
        id="autopilot_trending",
        replace_existing=True,
    )
    _scheduler.add_job(
        _figure_tech_cron_job,
        "cron",
        hour=figure_tech_hour,
        minute=minute,
        id="autopilot_figure_tech",
        replace_existing=True,
    )
    _remove_disabled_jobs()
    log.info(
        "[autopilot] reschedule news=%02d:%02d trending=%02d:%02d (+%dh) "
        "figure_tech=%02d:%02d (+%dh)",
        hour,
        minute,
        trending_hour,
        minute,
        trending_offset,
        figure_tech_hour,
        minute,
        figure_tech_offset,
    )


def run_now() -> None:
    _daily_job()


def shutdown() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
