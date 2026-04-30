"""
web/scheduler_service.py — APScheduler (BackgroundScheduler)

Daily autopilot (opt-in via `autopilot_enabled` setting):
  fires at (schedule_hour, schedule_minute), runs two back-to-back jobs:
    1. News autopilot (strategy=generic)
    2. Trending autopilot (strategy=entertainment, single YT TW top trend)

Both go through job_runner.trigger_job(autopilot=True). The queue inside
trigger_job sequences them so only one runs at a time.

Safety: `autopilot_dry_run` defaults to true — publisher prints preview only.
Flip to false once you trust the pipeline.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date as date_cls

from web.db import get_setting, create_job
from web import job_runner

log = logging.getLogger("scheduler_service")

_scheduler = BackgroundScheduler()

# Defaults applied when autopilot settings are missing. Keep aligned with the
# settings row documented in web/db.py.
_DEFAULT_PLATFORMS = "youtube,instagram,facebook,threads,x,tiktok"


def _bool_setting(key: str, default: bool) -> bool:
    return str(get_setting(key, str(default).lower())).lower() == "true"


def _pick_news_items(n: int = 3) -> list[dict]:
    """Multi-source news fetch + AI keyword filter + dedup.

    Pulls from the sources listed in `autopilot_news_sources` setting (default
    google/bing/hackernews/ithome/last30days/youtube_us — everything except
    youtube_tw which is reserved for trending autopilot, plus dcard/x which
    the user flagged as useless for this use case).

    Keeps only items whose title/summary contains at least one AI-related
    keyword, and excludes URLs already used in past jobs. Returns `n` items
    in the same shape enrich_news_items expects.
    """
    try:
        from web.routes.news import _fetch_all, _load_used_urls
    except Exception as e:
        log.warning("[autopilot] news fetch import failed: %s", e)
        return []

    sources_csv = get_setting("autopilot_news_sources",
                              "google,bing,hackernews,ithome,last30days")
    sources = [s.strip() for s in sources_csv.split(",") if s.strip()]
    keywords_csv = get_setting("autopilot_news_keywords",
                               "AI,人工智慧,ChatGPT,Claude,Gemini,LLM,機器學習,生成式,大型語言模型,深度學習,神經網路,科技,半導體,晶片,GPU,輝達,Nvidia,OpenAI,Anthropic,Meta,Google,Microsoft")
    keywords = [k.strip() for k in keywords_csv.split(",") if k.strip()]
    # Send the broadest keyword to RSS-style sources so we get AI-flavored hits
    kw = keywords[0] if keywords else "AI"

    try:
        raw = _fetch_all(keyword=kw, lang="zh-TW", sources=sources)
    except Exception as e:
        log.warning("[autopilot] _fetch_all failed: %s", e)
        return []
    if not raw:
        return []

    # Word-boundary matcher so short keywords like "AI" don't false-match
    # English noise words containing "ai" (TRAILER / SPAIN / RAIN / TAIL).
    # Chinese keywords don't have word boundaries — for those plain `in` is fine.
    import re as _re
    en_keywords = [k for k in keywords if _re.fullmatch(r"[A-Za-z0-9]+", k)]
    cn_keywords = [k for k in keywords if k not in en_keywords]
    en_pattern  = _re.compile(
        r"\b(" + "|".join(_re.escape(k) for k in en_keywords) + r")\b",
        _re.IGNORECASE,
    ) if en_keywords else None

    def _matches(text: str) -> bool:
        if not text:
            return False
        if any(k in text for k in cn_keywords):
            return True
        if en_pattern and en_pattern.search(text):
            return True
        return False

    used = _load_used_urls()
    matched = []
    seen_urls = set()
    for it in raw:
        url = it.get("url", "")
        if not url or url in used or url in seen_urls:
            continue
        haystack = f"{it.get('title','')} {it.get('summary','')}"
        if keywords and not _matches(haystack):
            continue
        seen_urls.add(url)
        matched.append({
            "title":       it.get("title", ""),
            "summary":     it.get("summary", "") or it.get("title", ""),
            "url":         url,
            "source":      it.get("source", ""),
            "source_type": it.get("source_type", "google"),
        })
        if len(matched) >= n:
            break
    return matched


def _fire_news_autopilot(today: str, platforms: list[str], dry_run: bool) -> None:
    strategy = get_setting("autopilot_news_strategy", "generic") or "generic"
    profile  = get_setting("autopilot_news_profile",  "pet")     or "pet"
    items    = _pick_news_items(n=3)

    job_id   = create_job(date=today, triggered_by="autopilot_news",
                          platforms=",".join(platforms))

    if items:
        log.info("[autopilot] news job %s multi-source (%d items) strategy=%s profile=%s dry_run=%s",
                 job_id, len(items), strategy, profile, dry_run)
        pre_news = items
    else:
        # Fallback to legacy Google News RSS path if multi-source yielded nothing
        log.info("[autopilot] news job %s multi-source empty — falling back to news_collector.py",
                 job_id)
        pre_news = None

    job_runner.trigger_job(
        job_id=job_id, date=today, topic=None,
        platforms=platforms, dry_run=dry_run,
        pre_news=pre_news,
        account_profile=profile,
        strategy=strategy,
        autopilot=True,
    )


def _pick_trending_items(n: int = 3) -> list[dict]:
    """Pick top N raw trending items by view_count, merged across configured
    sources (default YT TW + YT US). Skips URLs already made into videos.

    Source list tunable via the `autopilot_trending_sources` DB setting.
    Per user 2026-04-22: merge all sources into one pool and rank purely by
    view count — beat the TW-only bias that was over-indexing on esports.
    """
    try:
        from web.routes.news import _fetch_all, _load_used_urls
    except Exception as e:
        log.warning("[autopilot] trending fetch import failed: %s", e)
        return []

    sources_csv = get_setting("autopilot_trending_sources", "youtube_tw,youtube_us")
    sources = [s.strip() for s in sources_csv.split(",") if s.strip()] or ["youtube_tw"]

    used = _load_used_urls()
    merged: list[dict] = []
    seen_urls: set[str] = set()
    for src in sources:
        try:
            raw = _fetch_all(keyword="", lang="zh-TW", sources=[src])
        except Exception as e:
            log.warning("[autopilot] trending fetch %s failed: %s", src, e)
            continue
        for it in (raw or []):
            url = it.get("url", "")
            if not url or url in used or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(it)

    # Rank purely by view_count (desc). Missing view_count sinks to 0.
    merged.sort(key=lambda it: int(it.get("view_count") or 0), reverse=True)

    return [{
        "title":       it.get("title", ""),
        "summary":     it.get("summary", "") or it.get("title", ""),
        "url":         it.get("url", ""),
        "source":      it.get("source", "YouTube"),
        "source_type": it.get("source_type", "youtube"),
        "view_count":  it.get("view_count"),
    } for it in merged[:n]]


def _fire_trending_autopilot(today: str, platforms: list[str], dry_run: bool) -> None:
    # Per user preference: 娛樂 autopilot 一次只做 1 則（合輯要手動在 UI 選擇）
    items = _pick_trending_items(n=1)
    if not items:
        log.info("[autopilot] all YT TW trends already made — skipping trending job")
        return
    strategy = get_setting("autopilot_trending_strategy", "entertainment") or "entertainment"
    profile  = get_setting("autopilot_trending_profile",  "pet")           or "pet"
    job_id   = create_job(date=today, triggered_by="autopilot_trending",
                          platforms=",".join(platforms))
    log.info("[autopilot] trending job %s single item=%s strategy=%s profile=%s dry_run=%s",
             job_id, items[0]["title"][:50], strategy, profile, dry_run)
    job_runner.trigger_job(
        job_id=job_id, date=today, topic=None,
        platforms=platforms, dry_run=dry_run,
        pre_news=items,
        account_profile=profile,
        strategy=strategy,
        autopilot=True,
    )


def _read_autopilot_runtime_settings() -> tuple[str, list[str], bool]:
    """Common (date, platforms, dry_run) used by both fire functions."""
    today     = date_cls.today().isoformat()
    platforms = (get_setting("autopilot_platforms", _DEFAULT_PLATFORMS)
                 or _DEFAULT_PLATFORMS).split(",")
    platforms = [p.strip() for p in platforms if p.strip()]
    dry_run   = _bool_setting("autopilot_dry_run", True)
    return today, platforms, dry_run


def _news_cron_job() -> None:
    """Fires news autopilot at schedule_hour:schedule_minute."""
    if not _bool_setting("autopilot_enabled", False):
        _legacy_daily()
        return
    if not _bool_setting("autopilot_news_enabled", True):
        return
    today, platforms, dry_run = _read_autopilot_runtime_settings()
    _fire_news_autopilot(today, platforms, dry_run)


def _trending_cron_job() -> None:
    """Fires trending autopilot at offset hours after news.

    Reason: cross-account same-minute posting (yt + pet) tripped Meta's
    cross-account spam detector and dragged IG reach -20-40%. Stagger so
    the two pipelines hit each platform at different times of day.
    """
    if not _bool_setting("autopilot_enabled", False):
        return
    if not _bool_setting("autopilot_trending_enabled", True):
        return
    today, platforms, dry_run = _read_autopilot_runtime_settings()
    _fire_trending_autopilot(today, platforms, dry_run)


def _daily_job() -> None:
    """Manual `run_now()` and legacy callers — fires both back-to-back.

    The two cron jobs (_news_cron_job + _trending_cron_job) are what fire
    on a normal autopilot day; this combined version stays for the UI's
    「立刻跑一次 autopilot」button.
    """
    if not _bool_setting("autopilot_enabled", False):
        _legacy_daily()
        return
    today, platforms, dry_run = _read_autopilot_runtime_settings()
    if _bool_setting("autopilot_news_enabled", True):
        _fire_news_autopilot(today, platforms, dry_run)
    if _bool_setting("autopilot_trending_enabled", True):
        _fire_trending_autopilot(today, platforms, dry_run)


def _legacy_daily() -> None:
    """Pre-autopilot behavior: create 1 job and let user click through UI."""
    today     = date_cls.today().isoformat()
    platforms = get_setting("platforms", "youtube,instagram").split(",")
    dry_run   = get_setting("dry_run", "false") == "true"
    job_id    = create_job(date=today, triggered_by="schedule",
                           platforms=",".join(platforms))
    job_runner.trigger_job(job_id=job_id, date=today,
                           platforms=platforms, dry_run=dry_run)


def _trending_offset_hours() -> int:
    try:
        return max(0, min(20, int(get_setting("autopilot_trending_offset_hours", "4"))))
    except (TypeError, ValueError):
        return 4


def start(hour: int = 8, minute: int = 0) -> None:
    offset = _trending_offset_hours()
    trending_hour = (hour + offset) % 24
    # News at schedule_hour, trending offset hours later (default +4h)
    _scheduler.add_job(_news_cron_job, "cron", hour=hour, minute=minute,
                       id="autopilot_news", replace_existing=True)
    _scheduler.add_job(_trending_cron_job, "cron", hour=trending_hour, minute=minute,
                       id="autopilot_trending", replace_existing=True)
    log.info("[autopilot] schedule registered news=%02d:%02d trending=%02d:%02d (+%dh)",
             hour, minute, trending_hour, minute, offset)
    if not _scheduler.running:
        _scheduler.start()


def update_schedule(hour: int, minute: int) -> None:
    if not _scheduler.running:
        return
    offset = _trending_offset_hours()
    trending_hour = (hour + offset) % 24
    _scheduler.reschedule_job("autopilot_news", trigger="cron",
                              hour=hour, minute=minute)
    _scheduler.reschedule_job("autopilot_trending", trigger="cron",
                              hour=trending_hour, minute=minute)
    log.info("[autopilot] reschedule news=%02d:%02d trending=%02d:%02d (+%dh)",
             hour, minute, trending_hour, minute, offset)


def run_now() -> None:
    """Manual trigger — used by UI 'run autopilot now' button / API probe."""
    _daily_job()


def shutdown() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
