#!/usr/bin/env python3
"""
AI Video Fetcher — generates animated B-roll clips from news screenshots
using AI image-to-video APIs.

Priority order:
  1. Kling AI  (KLING_ACCESS_KEY + KLING_SECRET_KEY)
  2. Replicate  (REPLICATE_API_TOKEN)
  3. Graceful skip — exit 0, video_composer will fall back to Ken Burns

Output: pipeline/DATE/broll/broll_NN.mp4  (same path video_composer checks)

Usage:
    python scripts/ai_video_fetcher.py 2026-04-14
    python scripts/ai_video_fetcher.py 2026-04-14/job_3
"""
import io, json, os, sys, time, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from datetime import date
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────
TODAY    = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
BASE_DIR = Path(__file__).parent.parent
PIPE_DIR = BASE_DIR / "pipeline" / TODAY
NEWS_FILE = PIPE_DIR / "news.json"
SHOTS_DIR = PIPE_DIR / "screenshots"
BROLL_DIR = PIPE_DIR / "broll"

# ── Env / DB settings ────────────────────────────────────────────────
# Values come from environment variables first, then fall back to the
# SQLite settings table (written by the frontend settings page).

def _db_setting(key: str, default: str = "") -> str:
    """Read a value from data/dashboard.db settings table."""
    try:
        import sqlite3
        db_path = BASE_DIR / "data" / "dashboard.db"
        if not db_path.exists():
            return default
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


KLING_ACCESS_KEY    = os.getenv("KLING_ACCESS_KEY")    or _db_setting("kling_access_key")
KLING_SECRET_KEY    = os.getenv("KLING_SECRET_KEY")    or _db_setting("kling_secret_key")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN") or _db_setting("replicate_api_token")

# Kling API config
KLING_BASE_URL   = "https://api.klingai.com"
KLING_MODEL      = "kling-v1"
KLING_DURATION   = 5      # seconds; free tier: 5s costs ~10 credits
KLING_CFG        = 0.5    # guidance scale

# Poll config
MAX_POLL_ATTEMPTS = 60    # 60 × 5s = 5 min max wait per clip
POLL_INTERVAL     = 5     # seconds between polls
MAX_RETRIES       = 3     # retries on transient errors


# ── JWT helper for Kling ──────────────────────────────────────────────

def _gen_kling_token(access_key: str, secret_key: str) -> str:
    """Generate a short-lived JWT for Kling API authentication."""
    try:
        import jwt as pyjwt
    except ImportError:
        print("⚠️  PyJWT not installed — run: pip install PyJWT", file=sys.stderr)
        raise
    payload = {
        "iss": access_key,
        "exp": int(time.time()) + 1800,
        "nbf": int(time.time()) - 5,
    }
    return pyjwt.encode(payload, secret_key, algorithm="HS256")


# ── Low-level HTTP helpers ────────────────────────────────────────────

def _http_get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _http_post(url: str, headers: dict, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _download(url: str, dest: Path):
    """Download binary from url to dest."""
    req = urllib.request.Request(url, headers={"User-Agent": "AutoVideo/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())


# ── Upload screenshot to a temporary public URL ──────────────────────
# Kling requires an HTTP/HTTPS image URL; we use the Kling upload endpoint
# if available, otherwise fall back to a base64 data URI approach via
# the Replicate pathway.

def _upload_image_kling(image_path: Path, token: str) -> str:
    """Upload a local image via Kling's file upload endpoint and return its URL."""
    upload_url = f"{KLING_BASE_URL}/v1/images/upload"
    boundary = "AutoVideoBoundary"
    img_data = image_path.read_bytes()
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"

    # Multipart form-data body
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{image_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + img_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    req = urllib.request.Request(upload_url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result["data"]["url"]
    except Exception:
        # Fall back: use a public imgur-style upload or return None to trigger
        # the data-uri path if Kling supports it.
        return None


def _image_to_data_uri(image_path: Path) -> str:
    """Convert local image to base64 data URI (fallback for APIs that accept it)."""
    import base64
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


# ── Kling AI backend ──────────────────────────────────────────────────

def _kling_image2video(image_path: Path, item_index: int, prompt: str = "") -> Path | None:
    """
    Submit image-to-video task to Kling AI and poll until complete.
    Returns local MP4 path on success, None on failure.
    """
    print(f"  [Kling] Generating video for item {item_index}...")
    token = _gen_kling_token(KLING_ACCESS_KEY, KLING_SECRET_KEY)
    headers = {"Authorization": f"Bearer {token}"}

    # Try to upload image to get a URL Kling can fetch
    image_url = _upload_image_kling(image_path, token)
    if not image_url:
        # Some Kling versions accept base64 via image_base64 field
        import base64
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model_name": KLING_MODEL,
            "image_base64": image_b64,
            "duration": str(KLING_DURATION),
            "cfg_scale": KLING_CFG,
        }
    else:
        payload = {
            "model_name": KLING_MODEL,
            "image_url": image_url,
            "duration": str(KLING_DURATION),
            "cfg_scale": KLING_CFG,
        }

    if prompt:
        payload["prompt"] = prompt

    # Submit task
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = _http_post(
                f"{KLING_BASE_URL}/v1/videos/image2video",
                headers, payload
            )
            break
        except Exception as e:
            print(f"  [Kling] Submit attempt {attempt} failed: {e}", file=sys.stderr)
            if attempt == MAX_RETRIES:
                return None
            time.sleep(5)

    # Extract task_id (Kling wraps in data.task_id)
    task_id = (
        resp.get("data", {}).get("task_id")
        or resp.get("task_id")
    )
    if not task_id:
        print(f"  [Kling] No task_id in response: {resp}", file=sys.stderr)
        return None

    print(f"  [Kling] Task submitted: {task_id} — polling...")

    # Poll for completion
    poll_url = f"{KLING_BASE_URL}/v1/videos/image2video/{task_id}"
    for poll in range(MAX_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL)
        # Refresh token every 10 polls to avoid expiry
        if poll % 10 == 0:
            token = _gen_kling_token(KLING_ACCESS_KEY, KLING_SECRET_KEY)
            headers = {"Authorization": f"Bearer {token}"}

        try:
            status_resp = _http_get(poll_url, headers)
        except Exception as e:
            print(f"  [Kling] Poll error: {e}", file=sys.stderr)
            continue

        task_status = (
            status_resp.get("data", {}).get("task_status")
            or status_resp.get("task_status", "")
        )

        if task_status in ("succeed", "completed", "done"):
            # Extract video URL from various response shapes
            data = status_resp.get("data", status_resp)
            video_url = (
                data.get("task_result", {}).get("videos", [{}])[0].get("url")
                or data.get("video_url")
                or data.get("output_url")
            )
            if not video_url:
                print(f"  [Kling] Succeeded but no video URL in response: {status_resp}", file=sys.stderr)
                return None
            out_path = BROLL_DIR / f"broll_{item_index:02d}.mp4"
            print(f"  [Kling] Downloading video → {out_path.name}...")
            _download(video_url, out_path)
            print(f"  [Kling] Done: {out_path}")
            return out_path

        elif task_status in ("failed", "error"):
            err = status_resp.get("data", {}).get("task_status_msg", "unknown error")
            print(f"  [Kling] Task failed: {err}", file=sys.stderr)
            return None

        else:
            # still processing
            elapsed = (poll + 1) * POLL_INTERVAL
            print(f"  [Kling] Status: {task_status or 'processing'} ({elapsed}s elapsed)")

    print(f"  [Kling] Timed out after {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s", file=sys.stderr)
    return None


# ── Replicate backend ─────────────────────────────────────────────────

def _replicate_image2video(image_path: Path, item_index: int) -> Path | None:
    """
    Use Replicate's stable-video-diffusion to animate a screenshot.
    Returns local MP4 path on success, None on failure.
    """
    print(f"  [Replicate] Generating video for item {item_index}...")
    try:
        import replicate
    except ImportError:
        print("⚠️  replicate package not installed — run: pip install replicate", file=sys.stderr)
        return None

    try:
        output = replicate.run(
            "stability-ai/stable-video-diffusion:3f0457e4619daac51203dedb472816fd4af51f3149fa7a9e0b5ffcf1b8172438",
            input={
                "input_image": open(image_path, "rb"),
                "video_length": "25_frames_with_svd_xt",
                "sizing_strategy": "maintain_aspect_ratio",
                "frames_per_second": 6,
                "motion_bucket_id": 40,
                "cond_aug": 0.02,
                "decoding_t": 7,
            }
        )
        # output is a URL string or file-like object
        video_url = str(output) if not hasattr(output, "read") else None
        out_path = BROLL_DIR / f"broll_{item_index:02d}.mp4"
        if video_url:
            print(f"  [Replicate] Downloading video → {out_path.name}...")
            _download(video_url, out_path)
        else:
            out_path.write_bytes(output.read())
        print(f"  [Replicate] Done: {out_path}")
        return out_path
    except Exception as e:
        print(f"  [Replicate] Error: {e}", file=sys.stderr)
        return None


# ── Main ──────────────────────────────────────────────────────────────

def main():
    # Determine which backend to use.
    # Priority: explicit AI_VIDEO_MODE env var > DB setting > auto-detect from keys
    ai_video_mode = (
        os.getenv("AI_VIDEO_MODE", "").lower()
        or _db_setting("ai_video_mode").lower()
    )

    use_kling = bool(
        KLING_ACCESS_KEY and KLING_SECRET_KEY
        and (not ai_video_mode or ai_video_mode == "kling")
    )
    use_replicate = bool(
        REPLICATE_API_TOKEN
        and (not ai_video_mode or ai_video_mode == "replicate")
    )

    if not use_kling and not use_replicate:
        print("⚠️  No AI video API keys found (KLING_ACCESS_KEY/KLING_SECRET_KEY or "
              "REPLICATE_API_TOKEN). Skipping AI video generation — video_composer will "
              "use Ken Burns effect on screenshots.")
        sys.exit(0)

    if not NEWS_FILE.exists():
        print(f"❌ 找不到新聞檔：{NEWS_FILE}", file=sys.stderr)
        sys.exit(1)

    data  = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if not items:
        print("⚠️  No news items found, skipping AI video generation.")
        sys.exit(0)

    BROLL_DIR.mkdir(parents=True, exist_ok=True)

    print(f"🎬 AI Video Fetcher — {len(items)} items, backend: "
          f"{'Kling' if use_kling else 'Replicate'}")

    generated = 0
    skipped   = 0

    for i, item in enumerate(items, 1):
        broll_out = BROLL_DIR / f"broll_{i:02d}.mp4"
        if broll_out.exists():
            print(f"  [{i}] Already exists, skipping: {broll_out.name}")
            generated += 1
            continue

        # Find corresponding screenshot
        shot = Path(item.get("screenshot") or SHOTS_DIR / f"news_{i:02d}.png")
        if not shot.exists():
            print(f"  [{i}] Screenshot not found ({shot}), skipping B-roll for this item.")
            skipped += 1
            continue

        # Build a short motion prompt from the news title
        title = item.get("hook") or item.get("title", "")
        prompt = f"Slow cinematic camera pan across: {title[:80]}" if title else ""

        result = None
        if use_kling:
            result = _kling_image2video(shot, i, prompt=prompt)
            if result is None:
                print(f"  [{i}] Kling failed", file=sys.stderr)

        if result is None and use_replicate:
            print(f"  [{i}] Trying Replicate fallback...")
            result = _replicate_image2video(shot, i)

        if result is not None:
            generated += 1
        else:
            print(f"  [{i}] All backends failed — video_composer will use Ken Burns fallback.")
            skipped += 1

    print(f"\n✅ AI B-roll: {generated} generated, {skipped} skipped/failed")
    # Always exit 0 — failures are non-fatal; video_composer handles missing broll gracefully
    sys.exit(0)


if __name__ == "__main__":
    main()
