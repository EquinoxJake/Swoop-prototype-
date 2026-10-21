"""Parking photo upload + auth-gated file serving."""
from pathlib import Path
from typing import Optional
import uuid

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .core.config import APP_NAME, UPLOAD_DIR
from .core.db import db
from .core.security import get_current_user

router = APIRouter()


def _disk_path(path: str) -> Path:
    """Map a stored path to a file under UPLOAD_DIR, refusing anything that escapes it (e.g. '..')."""
    full = (UPLOAD_DIR / path).resolve()
    if not full.is_relative_to(UPLOAD_DIR):
        raise HTTPException(403, "Forbidden")
    return full


def _write_file_sync(full: Path, data: bytes) -> None:
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)


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
    await run_in_threadpool(_write_file_sync, _disk_path(path), data)

    # Cache the path on the ride doc so the receipt can read it
    await db.rides.update_one({"ride_id": ride_id}, {"$set": {"end_photo_path": path}})
    return PhotoUploadResponse(path=path, size=len(data))


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

    # Only allow the owner to fetch their own photos (admin review comes later)
    own_dir = _disk_path(f"{APP_NAME}/uploads/{user['user_id']}")
    full = _disk_path(full_path)
    if not full.is_relative_to(own_dir):
        raise HTTPException(403, "Forbidden")
    if not full.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(full)
