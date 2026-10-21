"""Signup, login, Google sign-in, logout, me."""
from typing import Optional
import uuid

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field
import jwt

from .core.config import GOOGLE_CLIENT_IDS, logger
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


class GoogleSignInRequest(BaseModel):
    id_token: str


# Google's public signing keys; PyJWKClient caches them between requests.
_google_jwks = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")


def verify_google_id_token(id_token: str) -> dict:
    """Check the ID token was signed by Google for one of our client IDs. Returns its claims."""
    if not GOOGLE_CLIENT_IDS:
        raise HTTPException(503, "Google sign-in is not configured")
    try:
        key = _google_jwks.get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=GOOGLE_CLIENT_IDS)
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid Google token: {e}")
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(401, "Invalid Google token issuer")
    if not claims.get("email") or not claims.get("email_verified"):
        raise HTTPException(401, "Google account email is not verified")
    return claims


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


@router.post("/auth/google", response_model=AuthResponse)
async def google_sign_in(body: GoogleSignInRequest):
    """Exchange a Google ID token (from the app's Google sign-in) for our session_token."""
    # Key fetch is a blocking HTTP call on cache miss, so keep it off the event loop
    data = await run_in_threadpool(verify_google_id_token, body.id_token)
    email = data["email"].lower()
    logger.info("Google sign-in for %s", email)
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
