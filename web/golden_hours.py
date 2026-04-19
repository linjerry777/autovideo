"""
web/golden_hours.py — shared golden-hour first-slot table + next-slot helper.

Previously only publisher.py knew these; UI needed to predict slots ahead of
publish for the schedule preview page, so the logic lives here and both
publisher.py + web routes import it.
"""
from datetime import datetime, timedelta

# Hour:minute of the first golden-hour slot per platform, local time.
# MUST stay in sync with scripts/publisher.py GOLDEN_HOUR_FIRST.
# (Based on 2026 Buffer / Socialync aggregate data — weekday peak windows.)
GOLDEN_HOUR_FIRST: dict[str, str] = {
    "youtube":   "14:00",
    "tiktok":    "07:00",
    "instagram": "13:00",
    "facebook":  "13:00",
    "threads":   "12:00",
    "x":         "09:00",
}


def next_golden_slot(platform: str, tz: str | None = "Asia/Taipei",
                     now: datetime | None = None) -> str | None:
    """Return ISO datetime string for the next golden-hour slot of this
    platform. If today's slot is already in the past, roll to tomorrow.

    `now` can be injected for deterministic tests; defaults to real clock.
    """
    hh_mm = GOLDEN_HOUR_FIRST.get(platform)
    if not hh_mm:
        return None
    try:
        from zoneinfo import ZoneInfo
        tzinfo = ZoneInfo(tz or "Asia/Taipei")
    except Exception:
        tzinfo = None
    current = now or datetime.now(tz=tzinfo)
    hh, mm = hh_mm.split(":")
    target = current.replace(hour=int(hh), minute=int(mm),
                             second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target.strftime("%Y-%m-%dT%H:%M:%S")
