#!/usr/bin/env python3
"""
Upload bandwidth diagnostic — figure out if it's Upload-Post, the route to
Europe, ISP throttling, or bandwidth cap.

Tests upload throughput to multiple destinations + path/latency probes.

Usage:
    python scripts/_upload_diag.py
"""
import io
import os
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Test targets — POST 1 MB random body, measure wall-clock time
# Each entry: (label, url, prepare_kwargs_func)
SIZE = 1024 * 1024  # 1 MB
PAYLOAD = os.urandom(SIZE)


def post_form(url, files, data=None, headers=None, timeout=120):
    t0 = time.perf_counter()
    try:
        r = requests.post(url, files=files, data=data, headers=headers, timeout=timeout)
        dt = time.perf_counter() - t0
        return r.status_code, dt, len(r.content), None
    except Exception as e:
        return None, time.perf_counter() - t0, 0, f"{type(e).__name__}: {str(e)[:120]}"


def test_uploadpost():
    """Real production target — Frankfurt CDN."""
    key = os.getenv("UPLOAD_POST_KEY", "")
    if not key:
        return ("Upload-Post (Frankfurt)", None, "no UPLOAD_POST_KEY")
    files = {"video": ("test.bin", io.BytesIO(PAYLOAD), "application/octet-stream")}
    headers = {"Authorization": f"ApiKey {key}"}
    data = {"user": "yt", "platform[]": "instagram"}
    status, dt, _, err = post_form("https://api.upload-post.com/api/upload",
                                    files=files, data=data, headers=headers)
    if err:
        return ("Upload-Post (Frankfurt)", None, err)
    return ("Upload-Post (Frankfurt)", SIZE / dt, f"HTTP {status} in {dt:.1f}s")


def test_imgbb():
    """imgbb — used by thumbnail uploader. CDN often US-based."""
    key = os.getenv("IMGBB_API_KEY", "")
    if not key:
        return ("imgbb", None, "no IMGBB_API_KEY")
    import base64
    b64 = base64.b64encode(PAYLOAD[:512*1024]).decode()  # imgbb max 32MB but use 512KB
    t0 = time.perf_counter()
    try:
        r = requests.post("https://api.imgbb.com/1/upload",
                         data={"key": key, "image": b64, "name": "diag"},
                         timeout=120)
        dt = time.perf_counter() - t0
        ok = r.json().get("success", False)
        return ("imgbb", (512*1024) / dt, f"success={ok} in {dt:.1f}s")
    except Exception as e:
        return ("imgbb", None, f"{type(e).__name__}: {e}")


def test_cloudflare():
    """Cloudflare's speed test endpoint — Anycast, should hit nearest edge."""
    files = {"file": ("test.bin", io.BytesIO(PAYLOAD), "application/octet-stream")}
    status, dt, _, err = post_form("https://speed.cloudflare.com/__up",
                                    files=files, timeout=120)
    if err:
        return ("Cloudflare (Anycast)", None, err)
    return ("Cloudflare (Anycast)", SIZE / dt, f"HTTP {status} in {dt:.1f}s")


def test_httpbin_aws():
    """httpbin.org — hosted on AWS, location varies but often US."""
    status, dt, _, err = post_form("https://httpbin.org/post",
                                    files={"file": ("test.bin", io.BytesIO(PAYLOAD))},
                                    timeout=120)
    if err:
        return ("httpbin (AWS US)", None, err)
    return ("httpbin (AWS US)", SIZE / dt, f"HTTP {status} in {dt:.1f}s")


def ping_target(host, count=4):
    """Cross-platform ping — average ms + loss%."""
    flag = "-n" if sys.platform == "win32" else "-c"
    try:
        out = subprocess.run(["ping", flag, str(count), host],
                             capture_output=True, text=True, timeout=15,
                             encoding="utf-8", errors="replace")
        return out.stdout
    except Exception as e:
        return f"ping err: {e}"


def resolve_ip(host):
    try:
        return socket.gethostbyname(host)
    except Exception as e:
        return f"DNS err: {e}"


def main():
    print("=" * 70)
    print("Upload bandwidth diagnostic — 1 MB POST to multiple endpoints")
    print(f"Local time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # --- DNS + ping probes
    targets = [
        ("api.upload-post.com",         "Upload-Post API"),
        ("speed.cloudflare.com",        "Cloudflare Speed"),
        ("api.imgbb.com",               "imgbb API"),
        ("httpbin.org",                 "httpbin"),
    ]
    print("\n[1] DNS + latency:")
    for host, label in targets:
        ip = resolve_ip(host)
        print(f"  {label:24} {host:30} → {ip}")
    print()
    print(f"  ping api.upload-post.com (4 packets):")
    raw = ping_target("api.upload-post.com")
    # Show only summary lines (last 4 lines on Windows)
    print("  " + "\n  ".join(raw.strip().splitlines()[-4:]))

    # --- Upload throughput
    print("\n[2] Upload throughput (3 runs each):")
    tests = [
        ("Upload-Post", test_uploadpost),
        ("Cloudflare",  test_cloudflare),
        ("imgbb",       test_imgbb),
        ("httpbin",     test_httpbin_aws),
    ]
    print(f"  {'target':22} {'run 1':>15} {'run 2':>15} {'run 3':>15} {'avg KB/s':>12}")
    for name, fn in tests:
        speeds = []
        run_strs = []
        for i in range(3):
            label, kbps, info = fn()
            if kbps:
                speeds.append(kbps / 1024)
                run_strs.append(f"{kbps/1024:>10.1f} KB/s")
            else:
                run_strs.append(f"{'FAIL':>15}")
        avg = statistics.mean(speeds) if speeds else 0
        print(f"  {name:22} " + " ".join(f"{s:>15}" for s in run_strs)
              + f" {avg:>10.1f}")

    print("\n" + "=" * 70)
    print("解讀指南：")
    print("  - 全部都慢 (<50 KB/s) → ISP 上傳頻寬本身就爛")
    print("  - 只 Upload-Post 慢 → Frankfurt 路由問題或他們伺服器限速")
    print("  - imgbb / Cloudflare 快但 Upload-Post 慢 → 國際路由特定問題")
    print("  - 全部都快 → 之前的 19 KB/s 是該時段網路抖動")
    print("=" * 70)


if __name__ == "__main__":
    main()
