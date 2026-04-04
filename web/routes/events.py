import asyncio, json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from web import job_runner

router = APIRouter(prefix="/api")


@router.get("/events/{job_id}")
async def sse(job_id: int):
    q = job_runner.subscribe(job_id)

    async def stream():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get("status") in ("done", "failed"):
                        break
                except asyncio.TimeoutError:
                    yield ": ping\n\n"   # keep-alive
        finally:
            job_runner.unsubscribe(job_id, q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
