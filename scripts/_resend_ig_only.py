"""One-shot — resend IG only for a job, preserving the schedule_log entries
of platforms that already succeeded (FB/Threads/etc).

Used when Upload-Post returned the upload OK but the platform itself rejected
later (e.g. IG rate-limit "Instagram had a temporary issue. Retried 4 times").

Usage:
    python scripts/_resend_ig_only.py 2026-04-28/job_126
"""
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from upload_post import UploadPostClient

sys.path.insert(0, str(Path(__file__).parent))
from thumbnail_uploader import upload_thumbnail  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

job_key = sys.argv[1]
base = Path(__file__).parent.parent
pipe_dir = base / "pipeline" / job_key
pmeta = json.loads((pipe_dir / "platform_meta.json").read_text(encoding="utf-8"))
news = json.loads((pipe_dir / "news.json").read_text(encoding="utf-8"))

ig = pmeta.get("instagram", {})
version = ig.get("video_version", "short")
video = pipe_dir / version / "output.mp4"
if not video.exists():
    video = pipe_dir / "output.mp4"

cover_url = upload_thumbnail(pipe_dir / "thumbnail.png")
print(f"cover_url: {cover_url}")
assert cover_url.lower().endswith(".jpg"), f"expected .jpg, got {cover_url}"

# Read profile from existing FB row (FB worked; same profile)
sched_path = pipe_dir / "schedule_log.json"
schedule_log = json.loads(sched_path.read_text(encoding="utf-8"))
fb_row = next((r for r in schedule_log if r["platform"] == "facebook"), None)
profile = (fb_row or {}).get("profile") or os.getenv("UPLOAD_POST_PROFILE", "default")
print(f"profile: {profile}")

title = ig.get("title") or news.get("items", [{}])[0].get("title", "")
desc = ig.get("description") or ""
fc = ig.get("first_comment", "")

api_key = os.getenv("UPLOAD_POST_KEY", "")
client = UploadPostClient(api_key)

# Match retry/timeout protection from publisher.py
_orig = client.session.request
def _t(method, url, **kw):
    kw.setdefault("timeout", (30, 180))
    return _orig(method, url, **kw)
client.session.request = _t

kwargs = dict(
    async_upload=True,
    description=desc,
    instagram_title=title,
    media_type="REELS",
    share_to_feed=True,
    cover_url=cover_url,
)
if fc:
    kwargs["first_comment"] = fc
if ig.get("collaborators"):
    kwargs["collaborators"] = ig["collaborators"]
if ig.get("user_tags"):
    kwargs["user_tags"] = ig["user_tags"]

print(f"📤 IG resend: {video.name} → profile={profile}")
# Pre-upload to R2 (Anycast 2-3 MB/s vs ~180 KB/s direct to Frankfurt).
# Falls back to local path if R2 isn't configured / errors.
video_arg: str = str(video)
try:
    from r2_uploader import upload_to_r2, R2ConfigError  # type: ignore
    try:
        video_arg = upload_to_r2(video, prefix=f"publish/{profile}")
        print(f"☁️  R2 → {video_arg[-60:]}")
    except R2ConfigError as _e:
        print(f"ℹ️  R2 skip (not configured): {_e}")
    except Exception as _e:
        print(f"⚠️  R2 upload failed ({type(_e).__name__}): {str(_e)[:120]}; using direct upload")
except ImportError:
    pass

resp = client.upload_video(
    video_path=video_arg,
    title=title,
    user=profile,
    platforms=["instagram"],
    **kwargs,
)
print(json.dumps(resp, ensure_ascii=False, indent=2))

# Merge back into schedule_log.json
new_req = resp.get("request_id", "")
new_status = "uploaded" if resp.get("success") else "failed"
for ent in schedule_log:
    if ent["platform"] == "instagram":
        ent["request_id"] = new_req
        ent["status"] = new_status
        break
sched_path.write_text(json.dumps(schedule_log, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✓ updated schedule_log.json (IG → {new_status} req={new_req[:16]}...)")
