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
import mimetypes
import os
import sys
from pathlib import Path

# NOTE: do NOT wrap sys.stdout/stderr here — this module is IMPORTED by
# publisher.py which has already wrapped them. Re-wrapping detaches the parent
# wrapper and closes the underlying buffer on GC, breaking all subsequent
# prints with "I/O operation on closed file" (regression introduced 2026-04-24).
# Standalone CLI mode only prints an ASCII URL, no UTF-8 wrapping needed.

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


class ThumbnailUploadError(RuntimeError):
    pass


def _ensure_jpeg(src: Path) -> Path:
    """Return a JPEG version of `src`. IG Reels rejects PNG cover_url ("Cover
    image must be JPEG"). Other platforms accept JPEG fine, so we standardize.

    If `src` is already .jpg/.jpeg, returns it unchanged. Otherwise creates
    `<src.stem>.jpg` next to it (idempotent — re-uses existing JPEG).
    """
    if src.suffix.lower() in (".jpg", ".jpeg"):
        return src
    jpg = src.with_suffix(".jpg")
    if jpg.exists() and jpg.stat().st_mtime >= src.stat().st_mtime:
        return jpg
    try:
        from PIL import Image
    except ImportError as e:
        raise ThumbnailUploadError(f"Pillow required for PNG→JPEG conversion: {e}")
    with Image.open(src) as im:
        # Flatten alpha onto white — JPEG has no alpha channel.
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        im.save(jpg, "JPEG", quality=92, optimize=True, progressive=True)
    return jpg


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

    PNG inputs are auto-converted to JPEG (IG Reels requires JPEG covers).
    Cached to `<path.parent>/thumbnail_url.txt` on success.
    Raises ThumbnailUploadError if every provider is unconfigured or fails.
    """
    if not path.exists():
        raise ThumbnailUploadError(f"thumbnail not found: {path}")

    # Cache key tracks JPEG URL specifically — earlier PNG uploads are
    # invalidated automatically because IG rejected them.
    cache = path.parent / "thumbnail_url.txt"
    if use_cache and cache.exists():
        cached = cache.read_text(encoding="utf-8").strip()
        # Old caches may point at .png — those failed on IG, force re-upload.
        if cached.startswith("http") and not cached.lower().endswith(".png"):
            return cached

    jpg_path = _ensure_jpeg(path)

    for fn in (_upload_supabase, _upload_imgbb):
        url = fn(jpg_path)
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
