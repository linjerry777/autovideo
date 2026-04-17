#!/usr/bin/env python3
"""
Publisher — 上傳影片到 YouTube / Instagram
使用 Upload-Post.com API

用法：
    python scripts/publisher.py 2026-03-20
    python scripts/publisher.py 2026-03-20 --platforms youtube instagram
    python scripts/publisher.py 2026-03-20 --dry-run
"""
import io, json, os, sys, argparse
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

    def _p(platform: str) -> dict:
        """Return platform-specific meta dict (never None)."""
        return (pmeta or {}).get(platform, {})

    kwargs = dict(async_upload=True, description=fallback_desc)

    # Per-platform titles (override default)
    for p in ("youtube", "tiktok", "instagram", "facebook", "threads", "x"):
        if p in platforms:
            title = _p(p).get("title") or fallback_title
            kwargs[f"{p}_title"] = title

    # YouTube-specific
    if "youtube" in platforms:
        yt = _p("youtube")
        kwargs["youtube_description"] = yt.get("description") or fallback_desc
        if yt.get("tags"):
            kwargs["tags"] = [t.strip() for t in yt["tags"].split(",") if t.strip()]
        else:
            kwargs["tags"] = ["AI", "人工智慧", "科技新聞", "AINews", "TechNews"]
        kwargs["privacyStatus"]          = "public"
        kwargs["containsSyntheticMedia"] = True
        kwargs["defaultAudioLanguage"]   = "zh-TW"
        thumb_path = pipe_dir / "thumbnail.png"
        if yt.get("use_auto_thumbnail", True) and thumb_path.exists():
            kwargs["thumbnail"] = str(thumb_path)

    # Instagram / Threads / Facebook share media_type=REELS
    if any(p in platforms for p in ("instagram", "threads", "facebook")):
        kwargs["media_type"]    = "REELS"
        kwargs["share_to_feed"] = True

    # Facebook extra description
    if "facebook" in platforms:
        kwargs["facebook_description"] = _p("facebook").get("description") or fallback_desc

    # Instagram first_comment (hashtag spam)
    if "instagram" in platforms:
        fc = _p("instagram").get("first_comment", "")
        if fc:
            kwargs["first_comment"] = fc

    # TikTok
    if "tiktok" in platforms:
        kwargs["privacy_level"] = "PUBLIC_TO_EVERYONE"

    resp = client.upload_video(
        video_path = str(output_mp4),
        title      = fallback_title,
        user       = PROFILE,
        platforms  = platforms,
        **kwargs,
    )

    if resp.get("success"):
        req_id = resp.get("request_id", "")
        print(f"\n✅ 上傳成功！request_id = {req_id}")
        print("   上傳為非同步，約 1~5 分鐘後在各平台生效")
    else:
        print(f"\n❌ 上傳失敗：{resp}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job_key", nargs="?", default=date.today().isoformat(),
                        help="job key，例如 2026-03-20 或 2026-03-20/job_5")
    parser.add_argument("--platforms", nargs="+",
                        default=["youtube", "instagram"],
                        choices=["youtube","instagram","tiktok","facebook",
                                 "threads","linkedin","x","pinterest","bluesky"],
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
