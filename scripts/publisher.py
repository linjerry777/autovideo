#!/usr/bin/env python3
"""
Publisher — 上傳影片到 YouTube / Instagram
使用 Upload-Post.com API

用法：
    python scripts/publisher.py 2026-03-20
    python scripts/publisher.py 2026-03-20 --platforms youtube instagram
    python scripts/publisher.py 2026-03-20 --dry-run
"""
import io, json, os, re, sys, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from datetime import date, datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from upload_post import UploadPostClient

# Golden-hour first-slot per platform (local time). Mirrors UI _GOLDEN_HOURS.
GOLDEN_HOUR_FIRST = {
    "youtube":   "14:00",
    "tiktok":    "07:00",
    "instagram": "13:00",
    "facebook":  "13:00",
    "threads":   "12:00",
    "x":         "09:00",
}


def _next_golden_slot(platform: str, tz: str | None) -> str | None:
    """Return ISO datetime for the next golden-hour slot of this platform.

    If today's slot has passed, returns tomorrow's. Emits local datetime in
    ISO format (Upload-Post parses this + timezone kwarg).
    """
    hh_mm = GOLDEN_HOUR_FIRST.get(platform)
    if not hh_mm:
        return None
    try:
        from zoneinfo import ZoneInfo
        tzinfo = ZoneInfo(tz or "Asia/Taipei")
    except Exception:
        tzinfo = None
    now = datetime.now(tz=tzinfo)
    hh, mm = hh_mm.split(":")
    target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.strftime("%Y-%m-%dT%H:%M:%S")

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_DIR  = Path(__file__).parent.parent
API_KEY   = os.getenv("UPLOAD_POST_KEY", "")
PROFILE   = os.getenv("UPLOAD_POST_PROFILE", "default")   # 在 .env 設定你的 profile 名稱


_HASHTAGS_BY_STRATEGY = {
    "tech":          "#AI快訊 #人工智慧 #科技新聞 #AINews #TechNews",
    "entertainment": "#娛樂 #明星 #藝人 #熱門話題 #八卦",
    "finance":       "#股市 #投資 #財經 #台股 #理財",
    "pet":           "#萌寵 #貓狗 #寵物 #可愛動物 #療癒",
    "generic":       "#每日新聞 #熱門 #話題",
}


def build_metadata(items: list, strategy: str = "tech") -> dict:
    """從新聞 items 組合標題、說明、hashtag (hashtag 跟著 strategy 走)"""
    titles   = [it["title"] for it in items]
    title    = " | ".join(titles)
    desc     = "\n\n".join(
        f"【{it['hook']}】\n{it['summary']}" for it in items
    )
    hashtags = _HASHTAGS_BY_STRATEGY.get((strategy or "tech").lower(),
                                        _HASHTAGS_BY_STRATEGY["tech"])
    return dict(title=title, description=f"{desc}\n\n{hashtags}")


SUPPORTED_PLATFORMS = {"youtube", "instagram", "tiktok", "facebook", "threads", "x"}


def publish(job_key: str, platforms: list[str], dry_run: bool = False):
    """job_key is either a date "2026-03-22" or "2026-03-22/job_5" """
    # Silently drop removed/unsupported platforms (reddit/pinterest/linkedin left over
    # from old job DB rows). No crash; just warn.
    dropped = [p for p in platforms if p not in SUPPORTED_PLATFORMS]
    if dropped:
        print(f"⚠️  忽略不支援的平台：{dropped}（reddit/pinterest/linkedin 已於 2026-04 移除）", file=sys.stderr)
    platforms = [p for p in platforms if p in SUPPORTED_PLATFORMS]
    if not platforms:
        print("❌ 過濾後沒有任何可上傳的平台，中止", file=sys.stderr)
        sys.exit(1)

    pipe_dir   = BASE_DIR / "pipeline" / job_key
    output_mp4 = pipe_dir / "output.mp4"
    news_file  = pipe_dir / "news.json"

    # Accept legacy output.mp4 OR dual-version short/long outputs — any one is enough
    has_video = (
        output_mp4.exists()
        or (pipe_dir / "short" / "output.mp4").exists()
        or (pipe_dir / "long"  / "output.mp4").exists()
    )
    if not has_video:
        print(f"❌ 找不到影片：{output_mp4}（short/long/output.mp4 也都沒有）")
        sys.exit(1)
    if not news_file.exists():
        print(f"❌ 找不到新聞：{news_file}")
        sys.exit(1)
    if not API_KEY:
        print("❌ 請在 .env 設定 UPLOAD_POST_KEY")
        sys.exit(1)

    data  = json.loads(news_file.read_text(encoding="utf-8"))
    meta_file = pipe_dir / "platform_meta.json"
    pmeta = (
        json.loads(meta_file.read_text(encoding="utf-8"))
        if meta_file.exists() else {}
    )
    # Global schedule: if mode=scheduled, pass to Upload-Post (it handles the queue)
    # mode=auto_per_platform → compute per-platform scheduled_date later, keep this empty.
    schedule = pmeta.get("_schedule", {}) if pmeta else {}
    schedule_kwargs = {}
    if schedule.get("mode") == "scheduled" and schedule.get("scheduled_date"):
        schedule_kwargs["scheduled_date"] = schedule["scheduled_date"]
        if schedule.get("timezone"):
            schedule_kwargs["timezone"] = schedule["timezone"]
    items = data["items"]
    meta  = build_metadata(items, strategy=data.get("strategy") or "tech")

    print(f"📤 準備上傳：{output_mp4.name}")
    print(f"   平台：{', '.join(platforms)}")
    print(f"   標題：{meta['title'][:60]}...")
    print(f"   Profile：{PROFILE}")

    if dry_run:
        print("\n[DRY RUN] 不實際上傳，以上為預覽")
        return

    client = UploadPostClient(API_KEY)

    # Per-platform kwargs derived from platform_meta.json (falls back to meta if missing)
    fallback_title = meta["title"]
    fallback_desc  = meta["description"]

    def _platform_meta(platform: str) -> dict:
        """Return platform-specific meta dict (never None)."""
        return pmeta.get(platform, {})

    kwargs = dict(async_upload=True, description=fallback_desc)
    kwargs.update(schedule_kwargs)   # scheduled_date + timezone if set

    # Per-platform titles for all platforms
    for p in ("youtube", "tiktok", "instagram", "facebook", "threads", "x"):
        if p in platforms:
            title = _platform_meta(p).get("title") or fallback_title
            kwargs[f"{p}_title"] = title

    # ── YouTube
    if "youtube" in platforms:
        yt = _platform_meta("youtube")
        kwargs["youtube_description"] = yt.get("description") or fallback_desc
        if yt.get("tags"):
            kwargs["tags"] = [t.strip() for t in re.split(r"[,\uff0c\u3001\n]+", yt["tags"]) if t.strip()]
        else:
            kwargs["tags"] = ["AI", "人工智慧", "科技新聞", "AINews", "TechNews"]
        kwargs["privacyStatus"]            = yt.get("privacyStatus", "public")
        kwargs["categoryId"]               = yt.get("categoryId", "22")
        kwargs["defaultLanguage"]          = yt.get("defaultLanguage", "zh-Hant")
        kwargs["defaultAudioLanguage"]     = yt.get("defaultAudioLanguage", "zh-Hant")
        kwargs["containsSyntheticMedia"]   = yt.get("containsSyntheticMedia", True)
        kwargs["selfDeclaredMadeForKids"]  = yt.get("selfDeclaredMadeForKids", False)
        kwargs["embeddable"]               = yt.get("embeddable", True)
        kwargs["publicStatsViewable"]      = yt.get("publicStatsViewable", True)
        kwargs["license"]                  = yt.get("license", "youtube")
        thumb_path = pipe_dir / "thumbnail.png"
        if yt.get("use_auto_thumbnail", True) and thumb_path.exists():
            kwargs["thumbnail"] = str(thumb_path)

    # ── TikTok
    if "tiktok" in platforms:
        tt = _platform_meta("tiktok")
        kwargs["privacy_level"]         = tt.get("privacy_level", "PUBLIC_TO_EVERYONE")
        kwargs["is_aigc"]               = tt.get("is_aigc", True)
        kwargs["cover_timestamp"]       = int(tt.get("cover_timestamp", 1000))
        kwargs["disable_duet"]          = tt.get("disable_duet", False)
        kwargs["disable_comment"]       = tt.get("disable_comment", False)
        kwargs["disable_stitch"]        = tt.get("disable_stitch", False)
        kwargs["brand_content_toggle"]  = tt.get("brand_content_toggle", False)
        kwargs["brand_organic_toggle"]  = tt.get("brand_organic_toggle", False)

    # ── Instagram / Threads / Facebook share media_type=REELS
    if any(p in platforms for p in ("instagram", "threads", "facebook")):
        kwargs["media_type"]    = "REELS"
        kwargs["share_to_feed"] = True

    # Instagram
    if "instagram" in platforms:
        ig = _platform_meta("instagram")
        fc = ig.get("first_comment", "")
        if fc:
            kwargs["first_comment"] = fc
        if ig.get("collaborators"):
            kwargs["collaborators"] = ig["collaborators"]
        if ig.get("user_tags"):
            kwargs["user_tags"]     = ig["user_tags"]

    # Facebook (page_id required — drop platform if empty)
    if "facebook" in platforms:
        fb = _platform_meta("facebook")
        if not fb.get("facebook_page_id"):
            print("⚠️  Facebook 未填 facebook_page_id（粉絲團 ID），跳過 Facebook 上傳", file=sys.stderr)
            platforms = [p for p in platforms if p != "facebook"]
        else:
            kwargs["facebook_page_id"]     = fb["facebook_page_id"]
            kwargs["facebook_description"] = fb.get("description") or fallback_desc
            kwargs["facebook_media_type"]  = fb.get("facebook_media_type", "REELS")
            kwargs["video_state"]          = fb.get("video_state", "PUBLISHED")

    # Threads
    if "threads" in platforms:
        th = _platform_meta("threads")
        if th.get("threads_topic_tag"):
            kwargs["threads_topic_tag"] = th["threads_topic_tag"][:50]

    # X (Twitter)
    if "x" in platforms:
        xp = _platform_meta("x")
        if xp.get("poll_options"):
            opts = [o.strip() for o in xp["poll_options"].split("|") if o.strip()]
            if 2 <= len(opts) <= 4:
                kwargs["poll_options"]  = opts
                kwargs["poll_duration"] = int(xp.get("poll_duration", 1440))
        kwargs["reply_settings"]      = xp.get("reply_settings", "everyone")
        kwargs["x_long_text_as_post"] = xp.get("x_long_text_as_post", False)

    if not platforms:
        print("❌ 沒有可上傳的平台（必填欄位未填）", file=sys.stderr)
        sys.exit(1)

    # Group platforms by video_version; upload each group separately.
    # When _schedule.mode=='auto_per_platform', further split each group into
    # per-platform calls so each platform can get its own golden-hour schedule.
    version_groups: dict[str, list[str]] = {"short": [], "long": [], "legacy": []}
    for p in platforms:
        v = _platform_meta(p).get("video_version")
        if v == "short":
            version_groups["short"].append(p)
        elif v == "long":
            version_groups["long"].append(p)
        else:
            version_groups["legacy"].append(p)

    auto_per_platform = schedule.get("mode") == "auto_per_platform"
    tz = schedule.get("timezone") or "Asia/Taipei"

    # Build flat upload plan: list of (label, video_path, group, extra_kwargs)
    upload_plan: list[tuple[str, Path, list[str], dict]] = []
    for version_key, group in version_groups.items():
        if not group:
            continue
        if version_key == "legacy":
            video_path = output_mp4
        else:
            video_path = pipe_dir / version_key / "output.mp4"
            if not video_path.exists():
                print(f"⚠️  {video_path.name} 不存在，{group} 改用 legacy output.mp4", file=sys.stderr)
                video_path = output_mp4
                if not video_path.exists():
                    print(f"❌ legacy output.mp4 也不存在，跳過 {group}", file=sys.stderr)
                    continue

        if auto_per_platform:
            for p in group:
                slot = _next_golden_slot(p, tz)
                extra = {"scheduled_date": slot, "timezone": tz} if slot else {}
                label = f"{version_key}:{p}@{slot or 'now'}"
                upload_plan.append((label, video_path, [p], extra))
        else:
            upload_plan.append((version_key, video_path, group, {}))

    responses = []
    for label, video_path, group, extra in upload_plan:
        merged_kwargs = {**kwargs, **extra}
        print(f"📤 上傳 {label} ({video_path.name}) → {group}")
        resp = client.upload_video(
            video_path = str(video_path),
            title      = fallback_title,
            user       = PROFILE,
            platforms  = group,
            **merged_kwargs,
        )
        responses.append((label, resp))

    # Summarize
    all_ok = all(r.get("success") for _, r in responses) if responses else False
    if responses:
        for label, resp in responses:
            req_id = resp.get("request_id", "")
            status = "✅" if resp.get("success") else "❌"
            print(f"  {status} {label}: request_id={req_id}")
    else:
        print("❌ 沒有任何上傳發生")
        sys.exit(1)
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job_key", nargs="?", default=date.today().isoformat(),
                        help="job key，例如 2026-03-20 或 2026-03-20/job_5")
    # NOTE: no `choices=` — we accept whatever the job DB has, then filter unsupported
    # platforms silently (reddit/pinterest/linkedin were removed in Apr 2026 but old DB
    # rows still carry them). Crashing on extra platforms broke job #85 upload step.
    parser.add_argument("--platforms", nargs="+",
                        default=["youtube", "instagram"],
                        help="目標平台（預設：youtube instagram）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只顯示預覽，不實際上傳")
    parser.add_argument("--profile", default=None,
                        help="Upload-Post profile 名稱（覆蓋 UPLOAD_POST_PROFILE env var）")
    args = parser.parse_args()
    if args.profile:
        import sys as _sys
        _sys.modules[__name__].PROFILE = args.profile
    publish(args.job_key, args.platforms, args.dry_run)
