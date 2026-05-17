import json
import threading
from pathlib import Path
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from web import job_runner
from web.db import get_job, get_setting, list_figure_quote_segments, list_figure_source_candidates

router = APIRouter(prefix="/api/media")
BASE_DIR = Path(__file__).parent.parent.parent
PIPELINE_DIR = BASE_DIR / "pipeline"
LIBRARY_UPLOAD_PLATFORMS = ["youtube", "instagram", "facebook", "threads", "x", "linkedin"]


class LibraryMetaUpdate(BaseModel):
    key: str
    platform_meta: dict


class LibraryUploadRequest(BaseModel):
    key: str
    platforms: list[str] | None = None
    dry_run: bool | None = None


def _pipe(date: str) -> Path:
    return PIPELINE_DIR / date


def _library_video_dir(key: str) -> Path:
    clean = (key or "").replace("\\", "/").strip().lstrip("/")
    if not clean:
        raise HTTPException(400, "missing library key")
    path = (PIPELINE_DIR / clean).resolve()
    base = PIPELINE_DIR.resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise HTTPException(400, "invalid library key")
    if path.is_file():
        path = path.parent
    if not (path / "output.mp4").exists():
        raise HTTPException(404, "output.mp4 not found for library item")
    if not (path / "news.json").exists():
        raise HTTPException(404, "news.json not found for library item")
    return path


def _library_job_key(video_dir: Path) -> str:
    return "/".join(video_dir.relative_to(PIPELINE_DIR).parts)


def _read_news(video_dir: Path) -> dict:
    try:
        return json.loads((video_dir / "news.json").read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(400, f"invalid news.json: {exc}")


def _default_profile_for_news(news: dict) -> str:
    if news.get("account_profile"):
        return str(news.get("account_profile") or "")
    strategy = (news.get("strategy") or "").lower()
    if strategy == "figure_tech":
        return get_setting("autopilot_figure_tech_profile", "yt") or "yt"
    if strategy == "figure_entertainment":
        return get_setting("autopilot_figure_entertainment_profile", "pet") or "pet"
    if strategy:
        routed = get_setting(f"trending_profile_{strategy}", "")
        if routed:
            return routed
    return get_setting("upload_post_profile", "yt") or "yt"


def _read_video_meta(video_dir: Path) -> dict:
    meta = {
        "title": video_dir.name,
        "figure_name": "",
        "source_name": "",
        "source_url": "",
        "source_published_at": "",
        "content_type": "",
        "strategy": "",
        "quote_original": "",
        "quote_zh": "",
        "script_short": "",
        "script_long": "",
        "script": "",
        "transcript_window": "",
    }
    news_file = video_dir / "news.json"
    if not news_file.exists() and video_dir.parent.name.startswith("job_"):
        news_file = video_dir.parent / "news.json"
    if not news_file.exists():
        return meta
    try:
        data = json.loads(news_file.read_text(encoding="utf-8"))
    except Exception:
        return meta
    item = (data.get("items") or [{}])[0] if isinstance(data, dict) else {}
    meta.update({
        "title": item.get("title") or item.get("hook") or data.get("topic") or video_dir.name,
        "figure_name": item.get("figure_name") or "",
        "source_name": item.get("source_name") or item.get("source") or "",
        "source_url": item.get("source_url") or item.get("url") or "",
        "source_published_at": item.get("source_published_at") or "",
        "content_type": data.get("content_type") or item.get("content_type") or "",
        "strategy": data.get("strategy") or item.get("strategy") or "",
        "quote_original": item.get("quote_original") or "",
        "quote_zh": item.get("quote_zh") or "",
        "script_short": item.get("script_short") or "",
        "script_long": item.get("script_long") or "",
        "script": item.get("script") or "",
        "transcript_window": item.get("transcript_window") or "",
    })
    return meta


def _library_item(video_path: Path) -> dict | None:
    try:
        rel = video_path.relative_to(PIPELINE_DIR)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 2:
        return None
    date_part = parts[0]
    folder = parts[1] if len(parts) >= 3 else ""
    variant = parts[2] if len(parts) >= 4 else "default"
    video_dir = video_path.parent
    meta = _read_video_meta(video_dir)
    job_id = None
    if folder.startswith("job_"):
        try:
            job_id = int(folder.replace("job_", "", 1))
        except ValueError:
            job_id = None
    thumb = video_dir / "thumbnail.png"
    if not thumb.exists() and folder and video_dir.parent.name == folder:
        thumb = video_dir.parent / "thumbnail.png"
    kind = "job" if job_id else ("figure" if folder.startswith("figure_") else "preview")
    return {
        "key": "/".join(parts).replace("\\", "/"),
        "date": date_part,
        "folder": folder or date_part,
        "variant": variant,
        "job_id": job_id,
        "kind": kind,
        "title": meta["title"],
        "figure_name": meta["figure_name"],
        "source_name": meta["source_name"],
        "source_url": meta["source_url"],
        "source_published_at": meta["source_published_at"],
        "content_type": meta["content_type"],
        "strategy": meta["strategy"],
        "quote_original": meta["quote_original"],
        "quote_zh": meta["quote_zh"],
        "script_short": meta["script_short"],
        "script_long": meta["script_long"],
        "script": meta["script"],
        "transcript_window": meta["transcript_window"],
        "video_url": "/pipeline_asset/" + "/".join(parts).replace("\\", "/"),
        "thumbnail_url": (
            "/pipeline_asset/" + "/".join(thumb.relative_to(PIPELINE_DIR).parts).replace("\\", "/")
            if thumb.exists() else ""
        ),
        "size_bytes": video_path.stat().st_size,
        "mtime": video_path.stat().st_mtime,
    }


def _figure_source_summary() -> dict:
    rows = list_figure_source_candidates(None, limit=5000)
    groups: dict[str, dict] = {}
    for row in rows:
        group = row.get("group_name") or "unknown"
        item = groups.setdefault(group, {"total": 0, "available": 0, "used": 0})
        item["total"] += 1
        status = row.get("status") or ""
        if status == "used":
            item["used"] += 1
        if status == "available" and int(row.get("caption_count") or 0) >= 8:
            item["available"] += 1
    total = {
        "total": sum(item["total"] for item in groups.values()),
        "available": sum(item["available"] for item in groups.values()),
        "used": sum(item["used"] for item in groups.values()),
    }
    return {"total": total, "groups": groups}


def _figure_segment_summary() -> dict:
    rows = list_figure_quote_segments(None, limit=10000)
    groups: dict[str, dict] = {}
    for row in rows:
        group = row.get("group_name") or "unknown"
        item = groups.setdefault(group, {"total": 0, "available": 0, "used": 0})
        item["total"] += 1
        status = row.get("status") or ""
        if status == "available":
            item["available"] += 1
        if status == "used":
            item["used"] += 1
    total = {
        "total": sum(item["total"] for item in groups.values()),
        "available": sum(item["available"] for item in groups.values()),
        "used": sum(item["used"] for item in groups.values()),
    }
    return {"total": total, "groups": groups}


@router.get("/library")
def video_library(limit: int = 80):
    """List rendered short videos from pipeline, including non-DB previews."""
    if not PIPELINE_DIR.exists():
        return {
            "items": [],
            "figure_sources": _figure_source_summary(),
            "figure_segments": _figure_segment_summary(),
        }
    items = []
    seen = set()
    for video in PIPELINE_DIR.rglob("output.mp4"):
        key = str(video.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        item = _library_item(video)
        if item:
            items.append(item)
    items.sort(key=lambda x: (x.get("source_published_at") or "", x["mtime"]), reverse=True)
    return {
        "items": items[: max(1, min(limit, 500))],
        "total": len(items),
        "figure_sources": _figure_source_summary(),
        "figure_segments": _figure_segment_summary(),
    }


@router.get("/library/platform_meta")
def library_platform_meta(key: str):
    """Return upload metadata for a rendered library video, seeding it if needed."""
    video_dir = _library_video_dir(key)
    meta_file = video_dir / "platform_meta.json"
    news = _read_news(video_dir)
    if meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    else:
        from web.routes.jobs import _seed_platform_meta
        meta = _seed_platform_meta(news)
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "key": _library_job_key(video_dir),
        "profile": _default_profile_for_news(news),
        "strategy": news.get("strategy") or "",
        "platform_meta": meta,
        "default_platforms": LIBRARY_UPLOAD_PLATFORMS,
    }


@router.put("/library/platform_meta")
def put_library_platform_meta(body: LibraryMetaUpdate):
    video_dir = _library_video_dir(body.key)
    meta_file = video_dir / "platform_meta.json"
    tmp_file = meta_file.with_suffix(".json.tmp")
    tmp_file.write_text(json.dumps(body.platform_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(meta_file)
    return {"ok": True, "key": _library_job_key(video_dir)}


@router.post("/library/upload")
def upload_library_video(body: LibraryUploadRequest):
    video_dir = _library_video_dir(body.key)
    news = _read_news(video_dir)
    job_key = _library_job_key(video_dir)
    platforms = body.platforms or LIBRARY_UPLOAD_PLATFORMS
    if not platforms:
        raise HTTPException(400, "no platforms selected")

    meta_file = video_dir / "platform_meta.json"
    if not meta_file.exists():
        from web.routes.jobs import _seed_platform_meta
        meta_file.write_text(
            json.dumps(_seed_platform_meta(news), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    profile = _default_profile_for_news(news)
    plat_args = ["--platforms"] + platforms + ["--profile", profile]
    dry_run = body.dry_run if body.dry_run is not None else (get_setting("dry_run", "false") == "true")
    if dry_run:
        plat_args.append("--dry-run")

    log_path = video_dir / "upload.log"

    def _do_upload():
        ok, out = job_runner._call_script("publisher.py", job_key, plat_args, log_path)
        status_file = video_dir / "upload_status.json"
        status_file.write_text(
            json.dumps({
                "ok": ok,
                "status": "done" if ok else "failed",
                "profile": profile,
                "platforms": platforms,
                "dry_run": dry_run,
                "error": "" if ok else out[-500:],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    threading.Thread(target=_do_upload, daemon=True).start()
    return {
        "key": job_key,
        "status": "uploading",
        "profile": profile,
        "platforms": platforms,
        "dry_run": dry_run,
    }


async def _stream_video(f: Path, request: Request):
    if not f.exists():
        raise HTTPException(404, "Video not found")
    file_size = f.stat().st_size
    range_header = request.headers.get("range")
    if range_header:
        start_str, _, end_str = range_header.replace("bytes=", "").partition("-")
        start = int(start_str)
        end   = int(end_str) if end_str else file_size - 1
        length = end - start + 1
        async def iter_file():
            with open(f, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        return StreamingResponse(
            iter_file(), status_code=206, media_type="video/mp4",
            headers={"Content-Range": f"bytes {start}-{end}/{file_size}",
                     "Accept-Ranges": "bytes", "Content-Length": str(length)},
        )
    return FileResponse(str(f), media_type="video/mp4",
                        headers={"Accept-Ranges": "bytes"})


@router.get("/{date}/news")
def news_json(date: str):
    f = _pipe(date) / "news.json"
    if not f.exists():
        raise HTTPException(404, "news.json not found")
    return JSONResponse(json.loads(f.read_text(encoding="utf-8")))


@router.get("/{date}/screenshot/{n}")
def screenshot(date: str, n: int):
    f = _pipe(date) / "screenshots" / f"news_{n:02d}.png"
    if not f.exists():
        raise HTTPException(404, "Screenshot not found")
    return FileResponse(str(f), media_type="image/png")


@router.get("/{date}/video")
async def video(date: str, request: Request):
    """Stream by date (legacy). Prefer /jobs/{id}/video."""
    return await _stream_video(_pipe(date) / "output.mp4", request)


@router.get("/jobs/{job_id}/video")
async def video_by_job(job_id: int, request: Request, v: str | None = None):
    """Stream video for a specific job.

    Optional `?v=short` or `?v=long` selects the dual-version output.
    Falls back to legacy `output.mp4` at the job root if the requested
    version file doesn't exist.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job_dir = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}"
    legacy = Path(job["output_path"]) if job.get("output_path") else (job_dir / "output.mp4")

    if v in ("short", "long"):
        versioned = job_dir / v / "output.mp4"
        if versioned.exists():
            return await _stream_video(versioned, request)
    return await _stream_video(legacy, request)


@router.get("/jobs/{job_id}/thumbnail")
def thumbnail_by_job(job_id: int):
    """Serve the auto-generated 1080x1920 thumbnail PNG for a job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    f = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "thumbnail.png"
    if not f.exists():
        raise HTTPException(404, "Thumbnail not yet generated")
    return FileResponse(str(f), media_type="image/png")


@router.get("/jobs/{job_id}/screenshots/{filename}")
def job_screenshot(job_id: int, filename: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    f = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "screenshots" / filename
    if not f.exists():
        raise HTTPException(404, "Screenshot not found")
    # no-cache: user can overwrite via /upload (edited PNG replaces same filename on disk).
    # Without this header Chrome serves stale bytes even after the file changed.
    return FileResponse(str(f), media_type="image/png",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@router.get("/jobs/{job_id}/broll/{filename}")
async def job_broll(job_id: int, filename: str, request: Request):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    f = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "broll" / filename
    if not f.exists():
        raise HTTPException(404, "B-roll not found")
    return await _stream_video(f, request)


@router.get("/{date}/log/{job_id}")
def log(date: str, job_id: int):
    f = _pipe(date) / f"job_{job_id}" / "run.log"
    if not f.exists():
        return {"log": ""}
    return {"log": f.read_text(encoding="utf-8", errors="replace")}
