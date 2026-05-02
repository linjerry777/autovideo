#!/usr/bin/env python3
"""
R2 upload speed diagnostic — measures real-world throughput end-to-end.

Compares:
  1. Direct POST to Upload-Post (Frankfurt) — the slow baseline
  2. boto3 PUT to Cloudflare R2 (Anycast edge) — should be 10x+ faster

Generates a 5 MB random blob (closer to a real short video than the 1 MB the
generic upload diag uses) and uploads via both paths 3 times each.

Usage:
    python scripts/_r2_diag.py
"""
import os
import statistics
import sys
import time
import io
from pathlib import Path

import requests  # type: ignore
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "scripts"))
from r2_uploader import upload_to_r2, prune_old, R2ConfigError  # noqa: E402

# Re-wrap stdout AFTER importing r2_uploader so we own the final wrapper
# (r2_uploader does the same trick; double-wrapping closes the first one).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SIZE = 5 * 1024 * 1024  # 5 MB
RUNS = 3


def make_blob() -> bytes:
    return os.urandom(SIZE)


def upload_via_uploadpost(blob: bytes) -> tuple[float, str]:
    """Direct multipart POST — the slow path we're measuring against."""
    key = os.getenv("UPLOAD_POST_KEY", "")
    if not key:
        return (-1.0, "no UPLOAD_POST_KEY")
    files = {"video": ("test.bin", io.BytesIO(blob), "application/octet-stream")}
    headers = {"Authorization": f"ApiKey {key}"}
    data = {"user": "yt", "platform[]": "instagram"}
    t0 = time.perf_counter()
    try:
        r = requests.post(
            "https://api.upload-post.com/api/upload",
            files=files, data=data, headers=headers, timeout=600,
        )
        dt = time.perf_counter() - t0
        return (dt, f"HTTP {r.status_code}")
    except Exception as e:
        return (time.perf_counter() - t0, f"{type(e).__name__}: {str(e)[:80]}")


def upload_via_r2(blob: bytes) -> tuple[float, str]:
    """boto3 PUT to R2, then return the public URL (no fetch)."""
    tmp = ROOT / "data" / "_r2_diag_blob.bin"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(blob)
    try:
        t0 = time.perf_counter()
        url = upload_to_r2(tmp, prefix="diag")
        dt = time.perf_counter() - t0
        return (dt, url)
    except R2ConfigError as e:
        return (-1.0, str(e))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def kb_per_sec(seconds: float) -> str:
    if seconds <= 0:
        return "FAIL"
    return f"{SIZE / seconds / 1024:>8.0f} KB/s"


def main() -> int:
    print("=" * 70)
    print(f"R2 vs direct upload diag — {SIZE // 1024 // 1024} MB × {RUNS} runs each")
    print(f"Local time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    blob = make_blob()
    print(f"\n[1] Direct POST → Upload-Post (Frankfurt):")
    direct_times: list[float] = []
    for i in range(RUNS):
        dt, info = upload_via_uploadpost(blob)
        if dt > 0:
            direct_times.append(dt)
            print(f"  run {i+1}: {dt:>6.1f}s  {kb_per_sec(dt)}  ({info})")
        else:
            print(f"  run {i+1}: {info}")

    print(f"\n[2] boto3 PUT → Cloudflare R2 (Anycast):")
    r2_times: list[float] = []
    for i in range(RUNS):
        dt, info = upload_via_r2(blob)
        if dt > 0:
            r2_times.append(dt)
            short = info.replace(os.getenv("R2_PUBLIC_URL_BASE", ""), "…")
            print(f"  run {i+1}: {dt:>6.1f}s  {kb_per_sec(dt)}  ({short})")
        else:
            print(f"  run {i+1}: {info}")

    if r2_times and direct_times:
        avg_r2 = statistics.mean(r2_times)
        avg_direct = statistics.mean(direct_times)
        speedup = avg_direct / avg_r2 if avg_r2 > 0 else 0
        print("\n" + "=" * 70)
        print(f"avg direct: {avg_direct:.1f}s ({kb_per_sec(avg_direct).strip()})")
        print(f"avg R2:     {avg_r2:.1f}s ({kb_per_sec(avg_r2).strip()})")
        print(f"speedup:    {speedup:.1f}x")
        print("=" * 70)

    # Tidy up: delete the diag objects
    try:
        n = prune_old(max_age_days=0, prefix="diag")
        print(f"\ncleanup: pruned {n} diag object(s)")
    except Exception as e:
        print(f"\ncleanup skipped: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
