"""
web/routes/accounts.py — Upload-Post 帳號管理 API
"""
import os
import requests as _req
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api")

UP_BASE = "https://api.upload-post.com/api"


def _headers():
    from web.db import get_setting
    key = get_setting("upload_post_key") or os.getenv("UPLOAD_POST_KEY", "")
    if not key:
        raise HTTPException(400, "Upload-Post API Key 未設定，請先到設定頁填入")
    return {"Authorization": f"Apikey {key}", "Content-Type": "application/json"}


# ── 驗證 API Key ───────────────────────────────────────────────────────────────

@router.get("/accounts/me")
def verify_api_key():
    try:
        r = _req.get(f"{UP_BASE}/uploadposts/me", headers=_headers(), timeout=5)
        r.raise_for_status()
        return r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Upload-Post API 錯誤: {e}")


# ── Profile 列表 ───────────────────────────────────────────────────────────────

@router.get("/accounts")
def list_accounts():
    try:
        r = _req.get(f"{UP_BASE}/uploadposts/users", headers=_headers(), timeout=10)
        r.raise_for_status()
        raw = r.json()

        # Upload-Post 可能用不同 key 回傳清單，統一轉成 {users: [...]}
        import logging
        logging.getLogger("accounts").info(f"[UP users raw] keys={list(raw.keys()) if isinstance(raw, dict) else type(raw)}")

        if isinstance(raw, list):
            return {"users": raw}
        for key in ("users", "profiles", "data", "items", "results"):
            if key in raw:
                return {"users": raw[key]}
        return {"users": []}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Upload-Post API 錯誤: {e}")


# ── Resolve which profile + accounts a given job will publish to ──────────────

@router.get("/accounts/resolve/{job_id}")
def resolve_for_job(job_id: int):
    """For an upload preview: return the Upload-Post profile name that this job
    will publish under + the list of social accounts already bound to it.

    Routing logic mirrors publisher.py + job_runner.py:
      1. Read news.json for this job to get `strategy`.
      2. Look up setting `trending_profile_{strategy}` → Upload-Post profile name.
      3. Fall back to setting `upload_post_profile` (global default).
      4. Fetch /uploadposts/users and cherry-pick that one profile's social_accounts.
    """
    import json as _json
    from pathlib import Path
    from web.db import get_job, get_setting

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # Read strategy from news.json if present
    BASE_DIR  = Path(__file__).parent.parent.parent
    news_file = BASE_DIR / "pipeline" / job["date"] / f"job_{job_id}" / "news.json"
    strategy  = ""
    if news_file.exists():
        try:
            strategy = _json.loads(news_file.read_text(encoding="utf-8")).get("strategy", "") or ""
        except Exception:
            pass

    # Resolve profile name via strategy → trending_profile_<strategy> setting
    profile_name = ""
    if strategy:
        profile_name = get_setting(f"trending_profile_{strategy.lower()}", "")
    if not profile_name:
        profile_name = get_setting("upload_post_profile", "") or "default"

    # Fetch accounts list + pick matching profile
    try:
        r = _req.get(f"{UP_BASE}/uploadposts/users", headers=_headers(), timeout=10)
        r.raise_for_status()
        raw = r.json()
        users = raw.get("profiles") or raw.get("users") or raw.get("data") or raw if isinstance(raw, list) else []
        if isinstance(raw, dict) and not users:
            for k in ("profiles", "users", "data", "items", "results"):
                if k in raw and isinstance(raw[k], list):
                    users = raw[k]
                    break
    except Exception as e:
        raise HTTPException(502, f"Upload-Post API 錯誤: {e}")

    matched = next((u for u in users if u.get("username") == profile_name), None)
    social  = matched.get("social_accounts") if matched else None

    bound = []
    if social and isinstance(social, dict):
        for platform, info in social.items():
            if isinstance(info, dict) and info:
                handle = info.get("username") or info.get("name") or info.get("handle") or ""
                bound.append({"platform": platform, "handle": handle})

    return {
        "job_id":       job_id,
        "strategy":     strategy,
        "profile":      profile_name,
        "profile_found": matched is not None,
        "accounts":     bound,
    }


# ── 建立 Profile ──────────────────────────────────────────────────────────────

class CreateAccountBody(BaseModel):
    email: str
    name: str


@router.post("/accounts")
def create_account(body: CreateAccountBody):
    try:
        r = _req.post(
            f"{UP_BASE}/uploadposts/users",
            headers=_headers(),
            json={"email": body.email, "name": body.name},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except HTTPException:
        raise
    except _req.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json()
        except Exception:
            detail = str(e)
        raise HTTPException(e.response.status_code, str(detail))
    except Exception as e:
        raise HTTPException(502, f"Upload-Post API 錯誤: {e}")


# ── 刪除 Profile ──────────────────────────────────────────────────────────────

@router.delete("/accounts/{username}")
def delete_account(username: str):
    try:
        r = _req.delete(
            f"{UP_BASE}/uploadposts/users",
            headers=_headers(),
            json={"username": username},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except HTTPException:
        raise
    except _req.HTTPError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(502, f"Upload-Post API 錯誤: {e}")


# ── 產生社群帳號綁定連結 (JWT) ─────────────────────────────────────────────────

class LinkBody(BaseModel):
    connect_title: str | None = None
    connect_description: str | None = None
    logo_image: str | None = None
    redirect_url: str | None = None


@router.post("/accounts/{username}/link")
def generate_link(username: str, body: LinkBody = LinkBody()):
    """產生 Upload-Post 托管的 OAuth 授權頁面連結"""
    payload: dict = {"username": username}
    if body.connect_title:        payload["connect_title"] = body.connect_title
    if body.connect_description:  payload["connect_description"] = body.connect_description
    if body.logo_image:           payload["logo_image"] = body.logo_image
    if body.redirect_url:         payload["redirect_url"] = body.redirect_url

    try:
        r = _req.post(
            f"{UP_BASE}/uploadposts/users/generate-jwt",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        # 正確欄位是 access_url
        access_url = data.get("access_url") or data.get("url") or data.get("token", "")
        return {
            "success": True,
            "url": access_url,
            "duration": data.get("duration"),
        }
    except HTTPException:
        raise
    except _req.HTTPError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(502, f"Upload-Post API 錯誤: {e}")


# ── 查詢上傳狀態 ──────────────────────────────────────────────────────────────

@router.get("/accounts/upload-status/{request_id}")
def get_upload_status(request_id: str):
    try:
        r = _req.get(
            f"{UP_BASE}/uploadposts/status",
            headers=_headers(),
            params={"request_id": request_id},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Upload-Post API 錯誤: {e}")
