"""Parking photo upload + auth-gated file serving."""
from typing import Optional
import os
import uuid

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
import requests

from .core.config import APP_NAME, logger
from .core.db import db
from .core.security import get_current_user

router = APIRouter()

# Object storage config
STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
storage_key: Optional[str] = None


def init_storage_sync() -> Optional[str]:
    global storage_key
    if storage_key:
        return storage_key
    if not EMERGENT_KEY:
        return None
    try:
        resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
        resp.raise_for_status()
        storage_key = resp.json()["storage_key"]
        return storage_key
    except Exception as e:
        logger.warning("Storage init failed: %s", e)
        return None


def _put_object_sync(path: str, data: bytes, content_type: str) -> dict:
    global storage_key
    key = init_storage_sync()
    if not key:
        raise RuntimeError("Storage unavailable")
    try:
        resp = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data,
            timeout=120,
        )
        if resp.status_code == 503:
            # stale key
            storage_key = None
            key = init_storage_sync()
            resp = requests.put(
                f"{STORAGE_URL}/objects/{path}",
                headers={"X-Storage-Key": key, "Content-Type": content_type},
                data=data,
                timeout=120,
            )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        raise RuntimeError(f"Upload failed: {e.response.status_code}") from e


def _get_object_sync(path: str) -> tuple:
    global storage_key
    key = init_storage_sync()
    if not key:
        raise RuntimeError("Storage unavailable")
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if resp.status_code == 503:
        storage_key = None
        key = init_storage_sync()
        resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


class PhotoUploadResponse(BaseModel):
    path: str
    size: int


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_PHOTO_BYTES = 8 * 1024 * 1024  # 8MB


@router.post("/uploads/parking-photo", response_model=PhotoUploadResponse)
async def upload_parking_photo(
    ride_id: str = Query(...),
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None),
):
    user = await get_current_user(authorization)
    ride = await db.rides.find_one({"ride_id": ride_id, "user_id": user["user_id"]}, {"_id": 0})
    if not ride:
        raise HTTPException(404, "Ride not found")
    if ride["status"] not in ("active", "reserved"):
        raise HTTPException(409, "Ride is not active")
    ctype = (file.content_type or "").lower()
    if ctype not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Only JPEG/PNG/WebP images are allowed")
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo too large (max 8MB)")

    ext = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}[ctype]
    path = f"{APP_NAME}/uploads/{user['user_id']}/{ride_id}_{uuid.uuid4().hex[:10]}.{ext}"
    try:
        result = await run_in_threadpool(_put_object_sync, path, data, ctype)
    except RuntimeError as e:
        raise HTTPException(502, f"Upload failed: {e}")

    # Cache the path on the ride doc so the receipt can read it
    await db.rides.update_one({"ride_id": ride_id}, {"$set": {"end_photo_path": path}})
    return PhotoUploadResponse(path=result.get("path", path), size=len(data))


@router.get("/files/{full_path:path}")
async def serve_file(full_path: str, authorization: Optional[str] = Header(None), token: Optional[str] = Query(None)):
    # Support both header auth and token query (for <img> tags on web)
    user = None
    if authorization and authorization.startswith("Bearer "):
        try: user = await get_current_user(authorization)
        except HTTPException: pass
    if not user and token:
        try: user = await get_current_user(f"Bearer {token}")
        except HTTPException: pass
    if not user:
        raise HTTPException(401, "Unauthorized")

    # Only allow the owner to fetch (or any ride photo the user owns)
    if not full_path.startswith(f"{APP_NAME}/uploads/{user['user_id']}/"):
        # Also allow admin-flagged reviews — for now, deny cross-user
        raise HTTPException(403, "Forbidden")
    try:
        content, ctype = await run_in_threadpool(_get_object_sync, full_path)
    except Exception:
        raise HTTPException(404, "Not found")
    return Response(content=content, media_type=ctype)
