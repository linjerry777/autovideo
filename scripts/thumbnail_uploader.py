#!/usr/bin/env python3
"""
Thumbnail Uploader — host the local 1080×1920 thumbnail.png on a public URL
so Upload-Post / Meta Graph / YouTube can fetch it as a custom cover.

Providers (env-driven, first match wins):
  1. Supabase Storage
     SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_THUMBNAIL_BUCKET (default "thumbnails")
  2. imgbb (fallback, free, just an API key)
     IMGBB_API_KEY

Caches the returned URL to `<pipe_dir>/thumbnail_url.txt` so subsequent
re-runs (e.g. upload retries) don't re-upload the same file.

Usage:
    python scripts/thumbnail_uploader.py 2026-04-24/job_5
    # Or from Python:
    from thumbnail_uploader import upload_thumbnail
    url = upload_thumbnail(Path("pipeline/2026-04-24/job_5/thumbnail.png"))
"""
import base64
import io
import mimetypes
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


class ThumbnailUploadError(RuntimeError):
    pass


def _upload_supabase(path: Path) -> str | None:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    bucket = os.getenv("SUPABASE_THUMBNAIL_BUCKET", "thumbnails")
    if not url or not key:
        return None
    object_name = f"{path.parent.parent.name}/{path.parent.name}/{path.name}"
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    endpoint = f"{url}/storage/v1/object/{bucket}/{object_name}"
    with path.open("rb") as f:
        r = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": mime,
                "x-upsert": "true",
            },
            data=f.read(),
            timeout=60,
        )
    if r.status_code >= 400:
        raise ThumbnailUploadError(f"Supabase upload {r.status_code}: {r.text[:200]}")
    return f"{url}/storage/v1/object/public/{bucket}/{object_name}"


def _upload_imgbb(path: Path) -> str | None:
    key = os.getenv("IMGBB_API_KEY", "")
    if not key:
        return None
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    r = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": key, "image": b64, "name": path.stem},
        timeout=60,
    )
    if r.status_code >= 400:
        raise ThumbnailUploadError(f"imgbb upload {r.status_code}: {r.text[:200]}")
    body = r.json()
    if not body.get("success"):
        raise ThumbnailUploadError(f"imgbb response: {body}")
    return body["data"]["url"]


def upload_thumbnail(path: Path, use_cache: bool = True) -> str:
    """Upload `path` to the first configured provider. Returns the public URL.

    Cached to `<path.parent>/thumbnail_url.txt` on success.
    Raises ThumbnailUploadError if every provider is unconfigured or fails.
    """
    if not path.exists():
        raise ThumbnailUploadError(f"thumbnail not found: {path}")

    cache = path.parent / "thumbnail_url.txt"
    if use_cache and cache.exists():
        cached = cache.read_text(encoding="utf-8").strip()
        if cached.startswith("http"):
            return cached

    for fn in (_upload_supabase, _upload_imgbb):
        url = fn(path)
        if url:
            try:
                cache.write_text(url, encoding="utf-8")
            except Exception:
                pass
            return url

    raise ThumbnailUploadError(
        "No thumbnail host configured. Set SUPABASE_URL+SUPABASE_SERVICE_KEY, "
        "or IMGBB_API_KEY in .env"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python thumbnail_uploader.py <job_key>", file=sys.stderr)
        sys.exit(2)
    job_key = sys.argv[1]
    base = Path(__file__).parent.parent
    thumb = base / "pipeline" / job_key / "thumbnail.png"
    print(upload_thumbnail(thumb))
