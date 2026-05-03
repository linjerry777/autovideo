#!/usr/bin/env python3
"""
Cloudflare R2 uploader — pre-upload mp4 (or any blob) before handing the URL
to a downstream API (e.g. Upload-Post).

Why this exists
---------------
Direct upload from Taiwan to upload-post.com (Frankfurt) caps around
~180 KB/s due to long-haul international routing — diagnosed by
`scripts/_upload_diag.py`. Cloudflare R2 sits behind Anycast edge so the
local upload sustains 2-3 MB/s; the R2 → Upload-Post hop is server-to-
server and effectively instant. Net effect: ~10x faster publish loop.

Cost
----
R2 free tier covers our actual usage by 100x:
  - 10 GB storage / month — we keep <300 MB
  - 1M Class A ops / month — we do <1k
  - Egress: free forever

Usage
-----
    from r2_uploader import upload_to_r2
    public_url = upload_to_r2(Path("pipeline/2026-05-02/output.mp4"))
    # → "https://pub-xxxx.r2.dev/<key>"

The returned URL can be passed to `UploadPostClient.upload_video(video_path=url, ...)`
because the Upload-Post SDK auto-detects http(s) prefixes and sends the URL
as form-data instead of streaming the file body.

Lifecycle
---------
Uploaded objects accumulate in the bucket. There's a `prune_old(...)` helper
that deletes objects older than `max_age_days`. Wire it into your daily cron
or call it manually if you start nearing the 10 GB ceiling.
"""
from __future__ import annotations

import io
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# NOTE: do NOT replace sys.stdout/sys.stderr at module top-level. publisher.py
# (and other callers) already wrap stdout once; doing it a second time here
# leaves the original wrapper as garbage, GC closes its underlying buffer, and
# the next print() in the caller raises "I/O operation on closed file." This
# was the cause of jobs 133-136 silently failing every upload after the R2
# patch landed (commit 424c56f). Keep CJK-safe encoding via reconfigure() and
# only when run as a CLI — never on import.
if __name__ == "__main__" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import boto3  # type: ignore
from botocore.client import Config  # type: ignore
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Required env vars ────────────────────────────────────────────────────
_REQUIRED = (
    "R2_ACCOUNT_ID",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_PUBLIC_URL_BASE",
)


class R2ConfigError(RuntimeError):
    """Raised when R2 env vars are missing — caller may fall back to local upload."""


def _config() -> dict:
    missing = [k for k in _REQUIRED if not os.getenv(k)]
    if missing:
        raise R2ConfigError(
            f"R2 not configured — missing env vars: {', '.join(missing)}. "
            f"See .env.example for the full list."
        )
    return {
        "account_id":  os.environ["R2_ACCOUNT_ID"],
        "bucket":      os.environ["R2_BUCKET"],
        "access_key":  os.environ["R2_ACCESS_KEY_ID"],
        "secret_key":  os.environ["R2_SECRET_ACCESS_KEY"],
        "public_base": os.environ["R2_PUBLIC_URL_BASE"].rstrip("/"),
        "endpoint":    os.environ.get(
            "R2_ENDPOINT",
            f'https://{os.environ["R2_ACCOUNT_ID"]}.r2.cloudflarestorage.com',
        ),
    }


_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    cfg = _config()
    _client = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        # R2 ignores region but boto3 wants something; "auto" is the convention.
        region_name="auto",
        # SigV4 is the only signature R2 supports.
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )
    return _client


# ── Content type guessing ────────────────────────────────────────────────
_CONTENT_TYPES = {
    ".mp4":  "video/mp4",
    ".mov":  "video/quicktime",
    ".webm": "video/webm",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".pdf":  "application/pdf",
}


def _guess_content_type(suffix: str) -> str:
    return _CONTENT_TYPES.get(suffix.lower(), "application/octet-stream")


# ── Public API ───────────────────────────────────────────────────────────
def upload_to_r2(
    local_path: str | Path,
    *,
    key: Optional[str] = None,
    prefix: str = "uploads",
    content_type: Optional[str] = None,
    cache_control: str = "public, max-age=86400",
) -> str:
    """
    Upload a local file to R2 and return its public URL.

    Args:
        local_path: Path on disk to upload.
        key:        Object key inside the bucket. Defaults to
                    `{prefix}/{epoch}-{stem}{suffix}` so re-uploads don't clobber.
        prefix:     Subfolder used when `key` is not given. Default 'uploads'.
        content_type: Override Content-Type. Auto-guessed by extension otherwise.
        cache_control: Cache-Control header on the object. 1 day default — long
                       enough for downstream services to fetch repeatedly,
                       short enough that prune_old() takes effect quickly.

    Returns:
        Public URL on r2.dev (or your custom domain if R2_PUBLIC_URL_BASE was
        set to one).

    Raises:
        R2ConfigError: env vars missing.
        ClientError: any S3 protocol failure.
    """
    cfg = _config()
    client = _get_client()
    p = Path(local_path)
    if not p.exists():
        raise FileNotFoundError(p)

    if key is None:
        key = f"{prefix.strip('/')}/{int(time.time())}-{p.stem}{p.suffix}"

    ctype = content_type or _guess_content_type(p.suffix)

    extra = {
        "ContentType":  ctype,
        "CacheControl": cache_control,
    }

    client.upload_file(str(p), cfg["bucket"], key, ExtraArgs=extra)
    return f'{cfg["public_base"]}/{key}'


def prune_old(max_age_days: int = 7, prefix: str = "uploads") -> int:
    """
    Delete objects under `prefix/` older than `max_age_days`. Returns count
    deleted. Call from cron or after a successful publish run to keep the
    bucket lean (we never need long-term storage for these files).
    """
    cfg = _config()
    client = _get_client()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    paginator = client.get_paginator("list_objects_v2")
    keys_to_delete: list[dict] = []
    for page in paginator.paginate(Bucket=cfg["bucket"], Prefix=f'{prefix.strip("/")}/'):
        for obj in page.get("Contents", []):
            if obj["LastModified"] < cutoff:
                keys_to_delete.append({"Key": obj["Key"]})
    deleted = 0
    # delete_objects supports max 1000 keys per call
    while keys_to_delete:
        chunk = keys_to_delete[:1000]
        keys_to_delete = keys_to_delete[1000:]
        client.delete_objects(Bucket=cfg["bucket"], Delete={"Objects": chunk})
        deleted += len(chunk)
    return deleted


# ── CLI entry: useful for ad-hoc uploads ─────────────────────────────────
def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Upload a file to Cloudflare R2.")
    parser.add_argument("path", help="Local file path")
    parser.add_argument("--key", help="Object key (default: uploads/<epoch>-<name>)")
    parser.add_argument("--prefix", default="uploads", help="Default prefix")
    parser.add_argument("--prune", type=int, metavar="DAYS",
                        help="After upload, delete objects older than DAYS")
    args = parser.parse_args()

    t0 = time.perf_counter()
    url = upload_to_r2(args.path, key=args.key, prefix=args.prefix)
    dt = time.perf_counter() - t0
    size = Path(args.path).stat().st_size
    print(f"OK  {size:,} bytes in {dt:.1f}s  ({size / max(dt, 0.001) / 1024:.0f} KB/s)")
    print(url)

    if args.prune is not None:
        n = prune_old(max_age_days=args.prune, prefix=args.prefix)
        print(f"pruned {n} object(s) older than {args.prune}d")

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
