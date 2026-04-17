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

from datetime import date
from pathlib import Path
from dotenv import load_dotenv
from upload_post import UploadPostClient

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_DIR  = Path(__file__).parent.parent
API_KEY   = os.getenv("UPLOAD_POST_KEY", "")
PROFILE   = os.getenv("UPLOAD_POST_PROFILE", "default")   # 在 .env 設定你的 profile 名稱


def build_metadata(items: list) -> dict:
    """從新聞 items 組合標題、說明、hashtag"""
    titles   = [it["title"] for it in items]
    hooks    = [it.get("hook", "") for it in items]
    title    = " | ".join(titles)
    desc     = "\n\n".join(
        f"【{it['hook']}】\n{it['summary']}" for it in items
    )
    hashtags = "#AI快訊 #人工智慧 #科技新聞 #AINews #TechNews"
    return dict(title=title, description=f"{desc}\n\n{hashtags}")


def publish(job_key: str, platforms: list[str], dry_run: bool = False):
    """job_key is either a date "2026-03-22" or "2026-03-22/job_5" """
    pipe_dir   = BASE_DIR / "pipeline" / job_key
    output_mp4 = pipe_dir / "output.mp4"
    news_file  = pipe_dir / "news.json"

    if not output_mp4.exists():
        print(f"❌ 找不到影片：{output_mp4}")
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
    schedule = pmeta.get("_schedule", {}) if pmeta else {}
    schedule_kwargs = {}
    if schedule.get("mode") == "scheduled" and schedule.get("scheduled_date"):
        schedule_kwargs["scheduled_date"] = schedule["scheduled_date"]
        if schedule.get("timezone"):
            schedule_kwargs["timezone"] = schedule["timezone"]
    items = data["items"]
    meta  = build_metadata(items)

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
    for p in ("youtube", "tiktok", "instagram", "facebook", "threads", "x", "pinterest", "reddit"):
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

    # Facebook
    if "facebook" in platforms:
        fb = _platform_meta("facebook")
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

    # Pinterest (board_id required — drop platform if empty)
    if "pinterest" in platforms:
        pn = _platform_meta("pinterest")
        if not pn.get("pinterest_board_id"):
            print("⚠️  Pinterest 未填 board_id，跳過 Pinterest 上傳", file=sys.stderr)
            platforms = [p for p in platforms if p != "pinterest"]
        else:
            kwargs["pinterest_board_id"]    = pn["pinterest_board_id"]
            kwargs["pinterest_description"] = pn.get("description") or fallback_desc
            kwargs["pinterest_alt_text"]    = pn.get("pinterest_alt_text") or fallback_title
            if pn.get("pinterest_link"):
                kwargs["pinterest_link"] = pn["pinterest_link"]

    # Reddit (subreddit required — drop platform if empty)
    if "reddit" in platforms:
        rd = _platform_meta("reddit")
        if not rd.get("subreddit"):
            print("⚠️  Reddit 未填 subreddit，跳過 Reddit 上傳", file=sys.stderr)
            platforms = [p for p in platforms if p != "reddit"]
        else:
            kwargs["subreddit"] = rd["subreddit"]
            if rd.get("flair_id"):
                kwargs["flair_id"] = rd["flair_id"]

    if not platforms:
        print("❌ 沒有可上傳的平台（必填欄位未填）", file=sys.stderr)
        sys.exit(1)

    # Group platforms by video_version; upload each group separately
    version_groups: dict[str, list[str]] = {"short": [], "long": [], "legacy": []}
    for p in platforms:
        v = _platform_meta(p).get("video_version")
        if v == "short":
            version_groups["short"].append(p)
        elif v == "long":
            version_groups["long"].append(p)
        else:
            version_groups["legacy"].append(p)

    responses = []
    for version_key, group in version_groups.items():
        if not group:
            continue
        if version_key == "legacy":
            video_path = output_mp4           # pipeline/.../output.mp4
        else:
            video_path = pipe_dir / version_key / "output.mp4"
            if not video_path.exists():
                # Graceful fallback: if expected version MP4 missing, use legacy
                print(f"⚠️  {video_path.name} 不存在，{group} 改用 legacy output.mp4", file=sys.stderr)
                video_path = output_mp4
                if not video_path.exists():
                    print(f"❌ legacy output.mp4 也不存在，跳過 {group}", file=sys.stderr)
                    continue

        print(f"📤 上傳 {version_key} ({video_path.name}) → {group}")
        resp = client.upload_video(
            video_path = str(video_path),
            title      = fallback_title,
            user       = PROFILE,
            platforms  = group,
            **kwargs,
        )
        responses.append((version_key, resp))

    # Summarize
    all_ok = all(r.get("success") for _, r in responses) if responses else False
    if responses:
        for version_key, resp in responses:
            req_id = resp.get("request_id", "")
            status = "✅" if resp.get("success") else "❌"
            print(f"  {status} {version_key}: request_id={req_id}")
    else:
        print("❌ 沒有任何上傳發生")
        sys.exit(1)
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job_key", nargs="?", default=date.today().isoformat(),
                        help="job key，例如 2026-03-20 或 2026-03-20/job_5")
    parser.add_argument("--platforms", nargs="+",
                        default=["youtube", "instagram"],
                        choices=["youtube","instagram","tiktok","facebook",
                                 "threads","linkedin","x","pinterest","bluesky","reddit"],
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
