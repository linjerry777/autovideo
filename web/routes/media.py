import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from web.db import get_job

router = APIRouter(prefix="/api/media")
BASE_DIR = Path(__file__).parent.parent.parent


def _pipe(date: str) -> Path:
    return BASE_DIR / "pipeline" / date


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
async def video_by_job(job_id: int, request: Request):
    """Stream video for a specific job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    # output_path stored in DB; fallback to derived path
    if job.get("output_path"):
        f = Path(job["output_path"])
    else:
        f = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "output.mp4"
    return await _stream_video(f, request)


@router.get("/jobs/{job_id}/screenshots/{filename}")
def job_screenshot(job_id: int, filename: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    f = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "screenshots" / filename
    if not f.exists():
        raise HTTPException(404, "Screenshot not found")
    return FileResponse(str(f), media_type="image/png")


@router.get("/{date}/log/{job_id}")
def log(date: str, job_id: int):
    f = _pipe(date) / f"job_{job_id}" / "run.log"
    if not f.exists():
        return {"log": ""}
    return {"log": f.read_text(encoding="utf-8", errors="replace")}
