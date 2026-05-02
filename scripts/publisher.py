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

sys.path.insert(0, str(Path(__file__).parent))
from thumbnail_uploader import upload_thumbnail, ThumbnailUploadError

# Cloudflare R2 pre-upload — sidesteps slow 跨國 routing (Taiwan→Frankfurt
# direct ~180 KB/s; Taiwan→R2 Anycast ~5 MB/s, then R2→Upload-Post is
# server-to-server). 6-10x faster publishes when configured.
# Falls back to direct file upload if R2 env vars are missing or R2 is down.
try:
    from r2_uploader import upload_to_r2, R2ConfigError  # type: ignore
    _R2_AVAILABLE = True
except Exception as _r2_imp_err:
    _R2_AVAILABLE = False
    R2ConfigError = Exception  # type: ignore

# Golden-hour first-slot per platform (local time). Mirrors UI _GOLDEN_HOURS.
GOLDEN_HOUR_FIRST = {
    "youtube":   "14:00",
    "tiktok":    "07:00",
    "instagram": "13:00",
    "facebook":  "13:00",
    "threads":   "12:00",
    "x":         "09:00",
}

# Strategy → golden-hour offset (hours). News (tech/finance) uses the base
# slot; trending (entertainment/pet/generic) shifts +4h so yt + pet posts
# don't land on the same minute on Meta and trip cross-account spam detection.
_STRATEGY_GOLDEN_OFFSET = {
    "tech":          0,
    "tech_tutorial": 0,
    "finance":       0,
    "entertainment": 4,
    "pet":           4,
    "generic":       4,
}


def _next_golden_slot(platform: str, tz: str | None, offset_hours: int = 0) -> str | None:
    """Return ISO datetime for the next golden-hour slot of this platform.

    `offset_hours` shifts the base time forward (e.g. trending → +4h).
    If the resulting slot has already passed today, returns tomorrow's.
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
    if offset_hours:
        target += timedelta(hours=int(offset_hours))
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


SUPPORTED_PLATFORMS = {"youtube", "instagram", "tiktok", "facebook", "threads", "x", "linkedin"}

# Per-profile platform allowlist. Profiles not listed here may use any
# SUPPORTED platform. Profiles listed here can ONLY upload to listed platforms
# — anything else is silently dropped before the Upload-Post call.
#
# Why: pet profile (娛樂線, _doro1998) has no LinkedIn account configured on
# Upload-Post, so attempting to publish there crashes with
# `UploadPostError: Profile pet has no Linkedin account configured` and tanks
# the rest of the run. yt profile (科技線, _doro1998ai) DOES have LinkedIn —
# only it should fan out to LinkedIn. Keep this dict in sync with whatever
# accounts each Upload-Post profile actually has connected.
_PROFILE_PLATFORM_ALLOWLIST = {
    # 娛樂線：no LinkedIn account configured on Upload-Post for this profile
    "pet": {"youtube", "instagram", "tiktok", "facebook", "threads", "x"},
}


def publish(job_key: str, platforms: list[str], dry_run: bool = False):
    """job_key is either a date "2026-03-22" or "2026-03-22/job_5" """
    # Silently drop removed/unsupported platforms (reddit/pinterest/linkedin left over
    # from old job DB rows). No crash; just warn.
    dropped = [p for p in platforms if p not in SUPPORTED_PLATFORMS]
    if dropped:
        print(f"⚠️  忽略不支援的平台：{dropped}（reddit/pinterest 已於 2026-04 移除）", file=sys.stderr)
    platforms = [p for p in platforms if p in SUPPORTED_PLATFORMS]

    # Profile-level allowlist: pet profile has no LinkedIn account on Upload-Post,
    # so dropping linkedin here prevents `Profile pet has no Linkedin account
    # configured` from bubbling up and failing the run. yt profile is unrestricted
    # so 科技線 still fans out to all 6 platforms (incl. LinkedIn) unchanged.
    profile_allow = _PROFILE_PLATFORM_ALLOWLIST.get((PROFILE or "").lower())
    if profile_allow is not None:
        before  = list(platforms)
        platforms = [p for p in platforms if p in profile_allow]
        skipped  = [p for p in before if p not in profile_allow]
        if skipped:
            print(f"⚠️  Profile={PROFILE} 沒有設定這些平台帳號，跳過：{skipped}",
                  file=sys.stderr)

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
    strategy = (data.get("strategy") or "tech").lower()
    meta  = build_metadata(items, strategy=strategy)
    # Trending pipelines (entertainment/pet/generic) shift +N hours so news
    # (yt) and trending (pet) don't post the exact same minute and trip
    # cross-account spam detection on Meta. News strategies use offset 0.
    strategy_offset = _STRATEGY_GOLDEN_OFFSET.get(strategy, 0)

    print(f"📤 準備上傳：{output_mp4.name}")
    print(f"   平台：{', '.join(platforms)}")
    print(f"   標題：{meta['title'][:60]}...")
    print(f"   Profile：{PROFILE}")
    if strategy_offset:
        print(f"   Strategy={strategy} → golden-hour offset +{strategy_offset}h")

    if dry_run:
        # Still write schedule_log.json so the UI 📅 排程 page shows what WOULD
        # be scheduled — just with status="dry_run" so user can tell apart from
        # real uploads. Inline pmeta lookups since the downstream
        # _platform_meta / auto_per_platform aren't defined yet at this point.
        _schedule     = pmeta.get("_schedule", {}) if pmeta else {}
        _auto_per     = _schedule.get("mode") == "auto_per_platform"
        _tz           = _schedule.get("timezone") or "Asia/Taipei"
        preview_entries = []
        for p in platforms:
            p_meta = pmeta.get(p, {}) if pmeta else {}
            version_key = p_meta.get("video_version", "legacy")
            slot = _next_golden_slot(p, _tz, offset_hours=strategy_offset) if _auto_per else ""
            preview_entries.append({
                "platform":       p,
                "scheduled_date": slot or "",
                "timezone":       _tz,
                "video_version":  version_key,
                "profile":        PROFILE,
                "status":         "dry_run",
                "request_id":     "",
            })
        try:
            (pipe_dir / "schedule_log.json").write_text(
                json.dumps(preview_entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as _e:
            print(f"⚠️  schedule_log 寫入失敗：{_e}", file=sys.stderr)
        print("\n[DRY RUN] 不實際上傳，以上為預覽（排程已寫入 schedule_log.json）")
        return

    client = UploadPostClient(API_KEY)

    # Upload-Post SDK has no timeout — a stalled CDN can hang the upload call
    # forever (job #118 was stuck 9 min on a single request). Monkey-patch the
    # underlying session to enforce (connect, read) defaults so retries are
    # actually reachable.
    _orig_session_request = client.session.request
    def _session_request_with_timeout(method, url, **kw):
        kw.setdefault("timeout", (30, 180))   # 30s connect, 180s read
        return _orig_session_request(method, url, **kw)
    client.session.request = _session_request_with_timeout

    # Custom cover — host thumbnail.png on a public URL so IG/YT can fetch it.
    # Platforms that support URL-based covers (IG cover_url, YT thumbnail_url)
    # share this URL. Silently skipped if no host is configured OR render missing.
    thumb_path = pipe_dir / "thumbnail.png"
    thumbnail_public_url: str | None = None
    if thumb_path.exists():
        try:
            thumbnail_public_url = upload_thumbnail(thumb_path)
            print(f"🖼️  封面 URL：{thumbnail_public_url}")
        except ThumbnailUploadError as _e:
            print(f"⚠️  封面 host 失敗（fallback 到平台自動取幀）：{_e}", file=sys.stderr)

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
        # Upload-Post's YT adapter accepts thumbnail_url (public URL, not a local path).
        if yt.get("use_auto_thumbnail", True) and thumbnail_public_url:
            kwargs["thumbnail_url"] = thumbnail_public_url

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
        # Custom cover — the hand-rendered 1080×1920 thumbnail.png (hook + title +
        # hero image). Meta Graph expects a public URL. If unhosted, fall back to
        # thumb_offset=2s to at least skip the pattern-interrupt black flash.
        if thumbnail_public_url and ig.get("use_auto_thumbnail", True):
            kwargs["cover_url"] = thumbnail_public_url
        else:
            kwargs["thumb_offset"] = int(ig.get("thumb_offset", 2))

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

    # LinkedIn (personal account; for org pages set target_linkedin_page_id)
    if "linkedin" in platforms:
        li = _platform_meta("linkedin")
        kwargs["linkedin_description"] = li.get("description") or fallback_desc
        kwargs["visibility"]           = li.get("visibility", "PUBLIC")
        if li.get("target_linkedin_page_id"):
            kwargs["target_linkedin_page_id"] = li["target_linkedin_page_id"]

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
                slot = _next_golden_slot(p, tz, offset_hours=strategy_offset)
                extra = {"scheduled_date": slot, "timezone": tz} if slot else {}
                label = f"{version_key}:{p}@{slot or 'now'}"
                upload_plan.append((label, video_path, [p], extra))
        else:
            upload_plan.append((version_key, video_path, group, {}))

    # Write schedule_log.json so the UI's 📅 排程 page can show what's queued.
    # Writes per-platform scheduled_date + account + video_version. Appended
    # with request_id + status after each upload below.
    schedule_entries: list[dict] = []
    for label, _vp, group, extra in upload_plan:
        for p in group:
            schedule_entries.append({
                "platform":       p,
                "scheduled_date": extra.get("scheduled_date") or "",
                "timezone":       tz,
                "video_version":  label.split(":")[0] if ":" in label else "legacy",
                "profile":        PROFILE,
                "status":         "pending",
                "request_id":     "",
            })

    responses = []
    # Transient-error markers — Upload-Post occasionally returns 502/504 from
    # their gateway; retrying after a short backoff usually succeeds. Without
    # this guard a single 504 used to crash the script and skip every other
    # platform (job #118: IG 504 → FB/Threads/TikTok/YT/X never attempted).
    import time as _time
    TRANSIENT_MARKERS = ("502", "503", "504", "Gateway", "Timeout", "Connection", "timed out")

    def _is_transient(exc: Exception) -> bool:
        msg = str(exc)
        return any(m in msg for m in TRANSIENT_MARKERS)

    def _resolve_video_arg(video_path: Path) -> str:
        """Pre-upload to R2 if configured; return URL. Otherwise local path str.
        URL path makes Upload-Post server-fetch (fast); local path streams
        the file body through our slow 跨國 link.
        """
        if not _R2_AVAILABLE:
            return str(video_path)
        try:
            url = upload_to_r2(video_path, prefix=f"publish/{PROFILE}")
            print(f"  ☁️  R2 pre-uploaded → {url[-60:]}")
            return url
        except R2ConfigError as e:
            # R2 not configured — silently fall back; this is the original
            # codepath. Log only at first job to avoid noise.
            print(f"  ℹ️  R2 skip (not configured): {e}", file=sys.stderr)
            return str(video_path)
        except Exception as e:
            print(f"  ⚠️  R2 upload failed ({type(e).__name__}: {str(e)[:120]}); "
                  f"falling back to direct upload", file=sys.stderr)
            return str(video_path)

    def _upload_with_retry(label, video_path, group, merged_kwargs, max_attempts=3):
        last_exc = None
        # Resolve to URL once per platform group; the URL is cheap to reuse.
        video_arg = _resolve_video_arg(video_path)
        for attempt in range(1, max_attempts + 1):
            try:
                return client.upload_video(
                    video_path = video_arg,
                    title      = fallback_title,
                    user       = PROFILE,
                    platforms  = group,
                    **merged_kwargs,
                )
            except Exception as e:
                last_exc = e
                if attempt < max_attempts and _is_transient(e):
                    backoff = 5 * (3 ** (attempt - 1))   # 5s, 15s, 45s
                    print(f"  ⚠️  {label} attempt {attempt}/{max_attempts} transient ({type(e).__name__}); retry in {backoff}s",
                          file=sys.stderr)
                    _time.sleep(backoff)
                    continue
                raise
        raise last_exc

    for label, video_path, group, extra in upload_plan:
        merged_kwargs = {**kwargs, **extra}
        print(f"📤 上傳 {label} ({video_path.name}) → {group}")
        try:
            resp = _upload_with_retry(label, video_path, group, merged_kwargs)
        except Exception as _e:
            # Mark this group failed; continue to next platform group so a
            # single platform's 504 doesn't tank the entire publish run.
            print(f"  ❌ {label} 放棄：{type(_e).__name__}: {str(_e)[:200]}", file=sys.stderr)
            resp = {"success": False, "request_id": "", "error": str(_e)[:300]}
        responses.append((label, resp))
        # Backfill status + request_id into schedule_entries for the UI
        for ent in schedule_entries:
            if ent["platform"] in group and ent.get("status") == "pending":
                ent["status"]     = "uploaded" if resp.get("success") else "failed"
                ent["request_id"] = resp.get("request_id", "")

    # Persist schedule log — MERGE with any existing log so a partial-platform
    # retry (e.g. retry/upload/failed for just YT+TT) doesn't wipe out the IG/
    # FB/Threads/X rows that succeeded earlier. Replace by platform key.
    log_path = pipe_dir / "schedule_log.json"
    merged = list(schedule_entries)
    new_platforms = {e["platform"] for e in schedule_entries}
    if log_path.exists():
        try:
            old = json.loads(log_path.read_text(encoding="utf-8"))
            for old_e in old:
                if old_e.get("platform") not in new_platforms:
                    merged.append(old_e)
        except Exception as _e:
            print(f"⚠️  讀舊 schedule_log 失敗（覆寫處理）：{_e}", file=sys.stderr)
    try:
        log_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as _e:
        print(f"⚠️  schedule_log 寫入失敗：{_e}", file=sys.stderr)

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
