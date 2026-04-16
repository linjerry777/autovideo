"""
web/routes/trending.py — Trending content enrichment endpoint
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/trending")


class EnrichRequest(BaseModel):
    items: list[dict]   # [{title, summary, url, source, source_type}, ...]


@router.post("/enrich")
def enrich_trending(req: EnrichRequest):
    """
    Call Claude to analyze trending items and assign format + account category.
    Input:  [{title, summary, url, source, source_type}, ...]
    Output: [{format, category, hook, title, script, scene_type,
              account_suggestion, source_url, source_name}, ...]
    """
    if not req.items:
        raise HTTPException(400, "items 不能為空")
    if len(req.items) > 5:
        raise HTTPException(400, "最多 5 則")

    from web.claude_client import enrich_trending_items
    try:
        enriched = enrich_trending_items(req.items)
    except Exception as e:
        raise HTTPException(500, f"Claude 分析失敗: {e}")

    return {"items": enriched}
