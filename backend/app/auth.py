"""Signup, login, Google sign-in, logout, me."""
from typing import Optional
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field
import httpx

from .core.config import logger
from .core.db import db
from .core.geo import now_utc
from .core.security import (
    UserPublic,
    create_session_for_user,
    get_current_user,
    hash_password,
    user_public,
    verify_password,
)

router = APIRouter()


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    session_token: str
    user: UserPublic


class GoogleSessionRequest(BaseModel):
    session_id: str


@router.get("/")
async def root():
    return {"message": "Swoop API", "status": "ok"}


@router.post("/auth/signup", response_model=AuthResponse)
async def signup(body: SignupRequest):
    existing = await db.users.find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    user_doc = {
        "user_id": user_id,
        "email": body.email.lower(),
        "password_hash": hash_password(body.password),
        "name": body.name or body.email.split("@")[0],
        "picture": None,
        "created_at": now_utc(),
    }
    await db.users.insert_one(user_doc)
    token = await create_session_for_user(user_id)
    return AuthResponse(session_token=token, user=user_public(user_doc))


@router.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not user.get("password_hash") or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = await create_session_for_user(user["user_id"])
    return AuthResponse(session_token=token, user=user_public(user))


@router.post("/auth/session", response_model=AuthResponse)
async def google_session(body: GoogleSessionRequest):
    """Exchange Emergent Google session_id for our session_token."""
    try:
        async with httpx.AsyncClient(timeout=15) as h:
            resp = await h.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": body.session_id},
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid Google session")
        data = resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Google session exchange failed: %s", e)
        raise HTTPException(status_code=401, detail="Google session exchange failed")

    email = (data.get("email") or "").lower()
    if not email:
        raise HTTPException(status_code=401, detail="No email in Google session")
    user = await db.users.find_one({"email": email})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "email": email,
            "password_hash": None,
            "name": data.get("name") or email.split("@")[0],
            "picture": data.get("picture"),
            "created_at": now_utc(),
        }
        await db.users.insert_one(user)
    token = await create_session_for_user(user["user_id"])
    return AuthResponse(session_token=token, user=user_public(user))


@router.get("/auth/me", response_model=UserPublic)
async def me(authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    return user_public(u)


@router.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}
