"""
Swoop — Scooter Rental Backend
Auth (email/password + Emergent Google), scooters, rides, mocked payments.
"""
from fastapi import FastAPI, APIRouter, HTTPException, Header, Request, UploadFile, File, Query
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os
import re
import uuid
import math
import random
import logging
import bcrypt
import jwt
import httpx
import requests

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("swoop")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ.get("JWT_SECRET", "swoop-dev-secret-change-me")
JWT_ALG = "HS256"

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="Swoop API")
api = APIRouter(prefix="/api")

# Pricing (cents)
UNLOCK_CENTS = 100
PER_MILE_CENTS = 20
METERS_PER_MILE = 1609.344
IMPROPER_PARKING_FEE_CENTS = 1500  # $15.00

# Object storage config
STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "swoop"
storage_key: Optional[str] = None


def _init_storage_sync() -> Optional[str]:
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
    key = _init_storage_sync()
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
            key = _init_storage_sync()
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
    key = _init_storage_sync()
    if not key:
        raise RuntimeError("Storage unavailable")
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if resp.status_code == 503:
        storage_key = None
        key = _init_storage_sync()
        resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ============ MODELS ============
class UserPublic(BaseModel):
    user_id: str
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    created_at: datetime


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


class Scooter(BaseModel):
    scooter_id: str
    code: str
    lat: float
    lng: float
    battery: int
    status: Literal["available", "reserved", "in_use", "offline"]
    model: str
    price_per_mile_cents: int = PER_MILE_CENTS
    unlock_fee_cents: int = UNLOCK_CENTS


class Ride(BaseModel):
    ride_id: str
    user_id: str
    scooter_id: str
    scooter_code: str
    status: Literal["reserved", "active", "completed", "cancelled"]
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    minutes: int = 0
    distance_m: int = 0
    miles: float = 0.0
    unlock_charged_cents: int = 0
    mileage_charged_cents: int = 0
    fee_charged_cents: int = 0
    amount_cents: int = 0
    payment_method_id: Optional[str] = None
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None
    end_lat: Optional[float] = None
    end_lng: Optional[float] = None
    route: List[List[float]] = Field(default_factory=list)
    paused_seconds: int = 0
    end_photo_path: Optional[str] = None
    parking_zone_id: Optional[str] = None
    parking_ok: Optional[bool] = None
    parking_flagged: bool = False
    parking_flag_reason: Optional[str] = None
    created_at: datetime
    paid_at: Optional[datetime] = None


class ParkingZone(BaseModel):
    zone_id: str
    name: str
    kind: Literal["bike_rack", "designated", "no_park"]
    lat: float
    lng: float
    radius_m: float
    created_at: datetime


class ParkingCheckRequest(BaseModel):
    lat: float
    lng: float


class ParkingCheckResponse(BaseModel):
    ok: bool
    reason: Optional[str] = None
    zone: Optional[ParkingZone] = None
    nearest_allowed: Optional[ParkingZone] = None
    nearest_allowed_distance_m: Optional[float] = None


class PaymentMethod(BaseModel):
    payment_method_id: str
    user_id: str
    brand: str
    last4: str
    exp_month: int
    exp_year: int
    is_default: bool
    created_at: datetime


class AddPaymentMethodRequest(BaseModel):
    number: str  # full card number (we only keep last4)
    exp_month: int
    exp_year: int
    cvc: str  # never stored


class ChargeRecord(BaseModel):
    charge_id: str
    user_id: str
    ride_id: Optional[str] = None
    amount_cents: int
    kind: Literal["unlock", "mileage", "improper_parking_fee"]
    payment_method_id: str
    created_at: datetime


# ============ AUTH HELPERS ============
async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    if ensure_aware(session["expires_at"]) < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")
    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def new_session_token(user_id: str) -> str:
    payload = {
        "user_id": user_id,
        "iat": int(now_utc().timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


async def create_session_for_user(user_id: str) -> str:
    token = new_session_token(user_id)
    await db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": now_utc() + timedelta(days=7),
        "created_at": now_utc(),
    })
    return token


def user_public(u: dict) -> UserPublic:
    return UserPublic(
        user_id=u["user_id"],
        email=u["email"],
        name=u.get("name"),
        picture=u.get("picture"),
        created_at=ensure_aware(u["created_at"]),
    )


# ============ SEEDING ============
async def ensure_indexes_and_seed():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.scooters.create_index("scooter_id", unique=True)
    await db.scooters.create_index("code", unique=True)
    await db.rides.create_index("ride_id", unique=True)
    await db.rides.create_index([("user_id", 1), ("created_at", -1)])
    await db.payment_methods.create_index("payment_method_id", unique=True)
    await db.payment_methods.create_index([("user_id", 1), ("is_default", 1)])
    await db.charges.create_index("charge_id", unique=True)
    await db.charges.create_index([("user_id", 1), ("created_at", -1)])

    # Migrate legacy ride statuses ('awaiting_payment' -> 'completed', 'paid' -> 'completed')
    await db.rides.update_many({"status": {"$in": ["awaiting_payment", "paid"]}}, {"$set": {"status": "completed"}})
    # Migrate legacy scooter field
    await db.scooters.update_many({"price_per_min_cents": {"$exists": True}}, {"$unset": {"price_per_min_cents": ""}})

    # Parking zones — designated bike racks + no-park zones around Georgia Southern
    await db.parking_zones.create_index("zone_id", unique=True)
    if await db.parking_zones.count_documents({}) == 0:
        seeds = [
            # Bike racks (allowed parking) — approximate GSU landmarks
            {"name": "Henderson Library bike rack", "kind": "bike_rack", "lat": 32.4176, "lng": -81.7811, "radius_m": 25},
            {"name": "Russell Union bike rack", "kind": "bike_rack", "lat": 32.4189, "lng": -81.7808, "radius_m": 25},
            {"name": "RAC bike rack", "kind": "bike_rack", "lat": 32.4144, "lng": -81.7735, "radius_m": 30},
            {"name": "Engineering Bldg bike rack", "kind": "bike_rack", "lat": 32.4165, "lng": -81.7825, "radius_m": 20},
            {"name": "Sweetheart Circle designated", "kind": "designated", "lat": 32.4197, "lng": -81.7815, "radius_m": 40},
            # No-park zones — high-traffic plazas & pathways
            {"name": "Pedestrium (main plaza)", "kind": "no_park", "lat": 32.4182, "lng": -81.7802, "radius_m": 45},
            {"name": "Rotunda no-park", "kind": "no_park", "lat": 32.4172, "lng": -81.7794, "radius_m": 25},
            {"name": "Paulson Stadium gates", "kind": "no_park", "lat": 32.4123, "lng": -81.7802, "radius_m": 40},
        ]
        docs = []
        for s in seeds:
            docs.append({
                "zone_id": f"zone_{uuid.uuid4().hex[:10]}",
                **s,
                "created_at": now_utc(),
            })
        await db.parking_zones.insert_many(docs)
        logger.info("Seeded %d parking zones", len(docs))

    # Seed scooters around Georgia Southern University (Statesboro) and a few in Savannah
    count = await db.scooters.count_documents({})
    if count == 0:
        # Georgia Southern Statesboro campus center approx
        gs_center = (32.4171, -81.7784)
        # Savannah historic district
        sav_center = (32.0809, -81.0912)
        rng = random.Random(42)
        seeds = []
        for i in range(18):
            lat = gs_center[0] + rng.uniform(-0.008, 0.008)
            lng = gs_center[1] + rng.uniform(-0.008, 0.008)
            seeds.append({
                "scooter_id": f"scoot_{uuid.uuid4().hex[:10]}",
                "code": f"SW-{1000 + i}",
                "lat": lat,
                "lng": lng,
                "battery": rng.randint(35, 100),
                "status": "available",
                "model": "Swoop One",
                "price_per_mile_cents": PER_MILE_CENTS,
                "unlock_fee_cents": UNLOCK_CENTS,
                "created_at": now_utc(),
            })
        for i in range(6):
            lat = sav_center[0] + rng.uniform(-0.006, 0.006)
            lng = sav_center[1] + rng.uniform(-0.006, 0.006)
            seeds.append({
                "scooter_id": f"scoot_{uuid.uuid4().hex[:10]}",
                "code": f"SW-{2000 + i}",
                "lat": lat,
                "lng": lng,
                "battery": rng.randint(50, 100),
                "status": "available",
                "model": "Swoop One",
                "price_per_mile_cents": PER_MILE_CENTS,
                "unlock_fee_cents": UNLOCK_CENTS,
                "created_at": now_utc(),
            })
        await db.scooters.insert_many(seeds)
        logger.info("Seeded %d scooters", len(seeds))

    # Seed demo user
    demo = await db.users.find_one({"email": "demo@swoop.app"})
    if not demo:
        await db.users.insert_one({
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": "demo@swoop.app",
            "password_hash": hash_password("swoop1234"),
            "name": "Demo Rider",
            "picture": None,
            "created_at": now_utc(),
        })
        logger.info("Seeded demo user demo@swoop.app / swoop1234")


@app.on_event("startup")
async def on_startup():
    await ensure_indexes_and_seed()
    # Warm storage key (non-blocking best-effort)
    try:
        await run_in_threadpool(_init_storage_sync)
    except Exception as e:
        logger.warning("Storage warm failed: %s", e)


@app.on_event("shutdown")
async def on_shutdown():
    client.close()


# ============ AUTH ROUTES ============
@api.get("/")
async def root():
    return {"message": "Swoop API", "status": "ok"}


@api.post("/auth/signup", response_model=AuthResponse)
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


@api.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not user.get("password_hash") or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = await create_session_for_user(user["user_id"])
    return AuthResponse(session_token=token, user=user_public(user))


@api.post("/auth/session", response_model=AuthResponse)
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


@api.get("/auth/me", response_model=UserPublic)
async def me(authorization: Optional[str] = Header(None)):
    u = await get_current_user(authorization)
    return user_public(u)


@api.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


# ============ SCOOTERS ============
@api.get("/scooters", response_model=List[Scooter])
async def list_scooters(lat: Optional[float] = None, lng: Optional[float] = None, radius_m: Optional[float] = None):
    query = {}
    docs = await db.scooters.find(query, {"_id": 0}).to_list(500)
    if lat is not None and lng is not None and radius_m:
        docs = [d for d in docs if haversine_m(lat, lng, d["lat"], d["lng"]) <= radius_m]
    return [Scooter(**d) for d in docs]


@api.get("/scooters/{code}", response_model=Scooter)
async def get_scooter(code: str):
    doc = await db.scooters.find_one({"code": code.upper()}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scooter not found")
    return Scooter(**doc)


class SeedNearRequest(BaseModel):
    lat: float
    lng: float
    radius_m: float = 500.0
    count: int = 12


@api.post("/scooters/seed-near", response_model=List[Scooter])
async def seed_scooters_near(body: SeedNearRequest):
    """
    Ensure at least `count` demo scooters exist within `radius_m` of the given point.
    Idempotent-ish: if already enough nearby, returns the existing set.
    """
    existing = await db.scooters.find({}, {"_id": 0}).to_list(2000)
    nearby = [d for d in existing if haversine_m(body.lat, body.lng, d["lat"], d["lng"]) <= body.radius_m]
    if len(nearby) >= body.count:
        return [Scooter(**d) for d in nearby]

    key = f"{round(body.lat, 3)},{round(body.lng, 3)}"
    rng = random.Random(hash(key) & 0xFFFFFFFF)
    need = body.count - len(nearby)
    dlat = body.radius_m / 111000.0
    dlng = body.radius_m / (111000.0 * max(0.2, math.cos(math.radians(body.lat))))
    max_code = 9000
    for d in existing:
        m = re.match(r"SW-(\d+)$", d.get("code", ""))
        if m:
            n = int(m.group(1))
            if 9000 <= n < 100000 and n >= max_code:
                max_code = n + 1
    new_docs = []
    for i in range(need):
        lat = body.lat + rng.uniform(-dlat, dlat)
        lng = body.lng + rng.uniform(-dlng, dlng)
        new_docs.append({
            "scooter_id": f"scoot_{uuid.uuid4().hex[:10]}",
            "code": f"SW-{max_code + i}",
            "lat": lat,
            "lng": lng,
            "battery": rng.randint(40, 100),
            "status": "available",
            "model": "Swoop One",
            "price_per_mile_cents": PER_MILE_CENTS,
            "unlock_fee_cents": UNLOCK_CENTS,
            "created_at": now_utc(),
        })
    if new_docs:
        await db.scooters.insert_many(new_docs)
    all_nearby = nearby + [{k: v for k, v in d.items() if k != "_id"} for d in new_docs]
    return [Scooter(**d) for d in all_nearby]


# ============ PAYMENT METHODS (MOCKED) ============
def detect_brand(number: str) -> str:
    n = number.replace(" ", "")
    if n.startswith("4"): return "Visa"
    if n.startswith(("51", "52", "53", "54", "55", "22", "23", "24", "25", "26", "27")): return "Mastercard"
    if n.startswith(("34", "37")): return "Amex"
    if n.startswith("6"): return "Discover"
    return "Card"


@api.get("/payment-methods", response_model=List[PaymentMethod])
async def list_payment_methods(authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    docs = await db.payment_methods.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(20)
    return [PaymentMethod(**{**d, "created_at": ensure_aware(d["created_at"])}) for d in docs]


@api.post("/payment-methods", response_model=PaymentMethod)
async def add_payment_method(body: AddPaymentMethodRequest, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    number = body.number.replace(" ", "").replace("-", "")
    if len(number) < 13 or not number.isdigit():
        raise HTTPException(400, "Invalid card number")
    if body.exp_month < 1 or body.exp_month > 12:
        raise HTTPException(400, "Invalid expiration month")
    if len(body.cvc) < 3:
        raise HTTPException(400, "Invalid CVC")
    # If this is user's first card, make it default
    existing_count = await db.payment_methods.count_documents({"user_id": user["user_id"]})
    pm = {
        "payment_method_id": f"pm_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "brand": detect_brand(number),
        "last4": number[-4:],
        "exp_month": body.exp_month,
        "exp_year": body.exp_year,
        "is_default": existing_count == 0,
        "created_at": now_utc(),
    }
    await db.payment_methods.insert_one(pm)
    return PaymentMethod(**pm)


@api.delete("/payment-methods/{payment_method_id}")
async def delete_payment_method(payment_method_id: str, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    pm = await db.payment_methods.find_one({"payment_method_id": payment_method_id, "user_id": user["user_id"]}, {"_id": 0})
    if not pm:
        raise HTTPException(404, "Not found")
    await db.payment_methods.delete_one({"payment_method_id": payment_method_id})
    # If deleted default, promote the newest remaining card
    if pm.get("is_default"):
        remaining = await db.payment_methods.find_one({"user_id": user["user_id"]}, {"_id": 0}, sort=[("created_at", -1)])
        if remaining:
            await db.payment_methods.update_one({"payment_method_id": remaining["payment_method_id"]}, {"$set": {"is_default": True}})
    return {"ok": True}


@api.post("/payment-methods/{payment_method_id}/default", response_model=PaymentMethod)
async def set_default_payment_method(payment_method_id: str, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    pm = await db.payment_methods.find_one({"payment_method_id": payment_method_id, "user_id": user["user_id"]}, {"_id": 0})
    if not pm:
        raise HTTPException(404, "Not found")
    await db.payment_methods.update_many({"user_id": user["user_id"]}, {"$set": {"is_default": False}})
    await db.payment_methods.update_one({"payment_method_id": payment_method_id}, {"$set": {"is_default": True}})
    pm["is_default"] = True
    return PaymentMethod(**{**pm, "created_at": ensure_aware(pm["created_at"])})


async def get_default_payment_method(user_id: str) -> Optional[dict]:
    pm = await db.payment_methods.find_one({"user_id": user_id, "is_default": True}, {"_id": 0})
    if pm:
        return pm
    return await db.payment_methods.find_one({"user_id": user_id}, {"_id": 0}, sort=[("created_at", -1)])


async def mock_charge(user_id: str, ride_id: Optional[str], amount_cents: int, kind: str, payment_method_id: str) -> str:
    """MOCKED Stripe charge. In production this would call stripe.PaymentIntent.create()."""
    charge_id = f"ch_{uuid.uuid4().hex[:14]}"
    await db.charges.insert_one({
        "charge_id": charge_id,
        "user_id": user_id,
        "ride_id": ride_id,
        "amount_cents": amount_cents,
        "kind": kind,
        "payment_method_id": payment_method_id,
        "created_at": now_utc(),
    })
    logger.info("[MOCK CHARGE] user=%s amount=%d kind=%s pm=%s", user_id, amount_cents, kind, payment_method_id)
    return charge_id


# ============ RIDES ============
class ReserveRequest(BaseModel):
    scooter_code: str


class StartRideRequest(BaseModel):
    ride_id: str


class EndRideRequest(BaseModel):
    ride_id: str
    end_lat: Optional[float] = None
    end_lng: Optional[float] = None
    distance_m: Optional[float] = None
    route: Optional[List[List[float]]] = None
    paused_seconds: Optional[int] = None
    end_photo_path: Optional[str] = None
    parking_override: bool = False  # server always re-checks anyway


def sanitize_ride(doc: dict) -> Ride:
    doc = {k: v for k, v in doc.items() if k != "_id"}
    for k in ("started_at", "ended_at", "created_at", "paid_at"):
        if doc.get(k) is not None:
            doc[k] = ensure_aware(doc[k])
    return Ride(**doc)


@api.post("/rides/reserve", response_model=Ride)
async def reserve_ride(body: ReserveRequest, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    # Enforce card-on-file
    pm = await get_default_payment_method(user["user_id"])
    if not pm:
        raise HTTPException(status_code=402, detail="Add a payment method before unlocking a scooter")
    scooter = await db.scooters.find_one({"code": body.scooter_code.upper()}, {"_id": 0})
    if not scooter:
        raise HTTPException(404, "Scooter not found")
    if scooter["status"] != "available":
        raise HTTPException(409, "Scooter not available")
    active = await db.rides.find_one({"user_id": user["user_id"], "status": {"$in": ["reserved", "active"]}}, {"_id": 0})
    if active:
        raise HTTPException(409, "You already have an active ride")

    # Charge unlock fee immediately (MOCKED)
    await mock_charge(user["user_id"], None, UNLOCK_CENTS, "unlock", pm["payment_method_id"])

    ride_id = f"ride_{uuid.uuid4().hex[:12]}"
    ride_doc = {
        "ride_id": ride_id,
        "user_id": user["user_id"],
        "scooter_id": scooter["scooter_id"],
        "scooter_code": scooter["code"],
        "status": "reserved",
        "minutes": 0,
        "distance_m": 0,
        "miles": 0.0,
        "unlock_charged_cents": UNLOCK_CENTS,
        "mileage_charged_cents": 0,
        "amount_cents": UNLOCK_CENTS,
        "payment_method_id": pm["payment_method_id"],
        "start_lat": scooter["lat"],
        "start_lng": scooter["lng"],
        "created_at": now_utc(),
    }
    await db.rides.insert_one(ride_doc)
    # Link the unlock charge to this ride
    await db.charges.update_many(
        {"user_id": user["user_id"], "kind": "unlock", "ride_id": None},
        {"$set": {"ride_id": ride_id}},
    )
    await db.scooters.update_one({"scooter_id": scooter["scooter_id"]}, {"$set": {"status": "reserved"}})
    return sanitize_ride(ride_doc)


@api.post("/rides/start", response_model=Ride)
async def start_ride(body: StartRideRequest, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    ride = await db.rides.find_one({"ride_id": body.ride_id, "user_id": user["user_id"]}, {"_id": 0})
    if not ride:
        raise HTTPException(404, "Ride not found")
    if ride["status"] not in ("reserved",):
        raise HTTPException(409, "Ride cannot be started")
    started_at = now_utc()
    await db.rides.update_one(
        {"ride_id": body.ride_id},
        {"$set": {"status": "active", "started_at": started_at}},
    )
    await db.scooters.update_one({"scooter_id": ride["scooter_id"]}, {"$set": {"status": "in_use"}})
    ride["status"] = "active"
    ride["started_at"] = started_at
    return sanitize_ride(ride)


@api.post("/rides/end", response_model=Ride)
async def end_ride(body: EndRideRequest, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    ride = await db.rides.find_one({"ride_id": body.ride_id, "user_id": user["user_id"]}, {"_id": 0})
    if not ride:
        raise HTTPException(404, "Ride not found")
    if ride["status"] != "active":
        raise HTTPException(409, "Ride not active")

    ended_at = now_utc()
    started_at = ensure_aware(ride["started_at"])
    seconds = max(0, (ended_at - started_at).total_seconds())
    minutes = max(1, math.ceil(seconds / 60))
    # GPS-tracked distance from client; fallback to zero if unavailable
    distance_m = float(body.distance_m) if body.distance_m is not None else 0.0
    miles = distance_m / METERS_PER_MILE
    # Round mileage cost UP by hundredth of a mile to be fair-ish
    mileage_cents = max(0, math.ceil(miles * PER_MILE_CENTS))
    total_cents = ride.get("unlock_charged_cents", UNLOCK_CENTS) + mileage_cents

    # Auto-charge mileage to user's default card (MOCKED)
    pm_id = ride.get("payment_method_id")
    if not pm_id:
        pm = await get_default_payment_method(user["user_id"])
        pm_id = pm["payment_method_id"] if pm else None
    if pm_id and mileage_cents > 0:
        await mock_charge(user["user_id"], ride["ride_id"], mileage_cents, "mileage", pm_id)

    update = {
        "status": "completed",
        "ended_at": ended_at,
        "paid_at": ended_at,
        "minutes": minutes,
        "distance_m": int(distance_m),
        "miles": round(miles, 3),
        "mileage_charged_cents": mileage_cents,
        "amount_cents": total_cents,
    }
    if body.end_lat is not None and body.end_lng is not None:
        update["end_lat"] = body.end_lat
        update["end_lng"] = body.end_lng
    if body.route:
        # Thin to max 200 points to keep documents small
        route = body.route
        if len(route) > 200:
            step = max(1, math.ceil(len(route) / 200))
            route = route[::step]
        update["route"] = [[round(p[0], 6), round(p[1], 6)] for p in route if len(p) >= 2]
    if body.paused_seconds is not None:
        update["paused_seconds"] = max(0, int(body.paused_seconds))

    # Enforce parking-verification photo
    if not body.end_photo_path:
        raise HTTPException(status_code=422, detail="A parking photo is required to end the ride")
    update["end_photo_path"] = body.end_photo_path

    # Parking-zone check (server-authoritative)
    if body.end_lat is not None and body.end_lng is not None:
        parking = await _evaluate_parking(body.end_lat, body.end_lng)
        update["parking_ok"] = parking["ok"]
        if parking.get("zone"):
            update["parking_zone_id"] = parking["zone"]["zone_id"]
        if not parking["ok"] and not body.parking_override:
            # Strip non-JSON-serializable fields (datetime) before returning in detail
            def _z(zd):
                if not zd: return None
                return {k: v for k, v in zd.items() if k != "created_at"}
            safe = {
                "ok": parking["ok"],
                "reason": parking.get("reason"),
                "zone": _z(parking.get("zone")),
                "nearest_allowed": _z(parking.get("nearest_allowed")),
                "nearest_allowed_distance_m": parking.get("nearest_allowed_distance_m"),
            }
            raise HTTPException(status_code=409, detail={"code": "bad_parking", **safe})

    await db.rides.update_one({"ride_id": body.ride_id}, {"$set": update})

    # Free scooter + update its position/battery
    scooter_updates = {"status": "available"}
    if body.end_lat is not None and body.end_lng is not None:
        scooter_updates["lat"] = body.end_lat
        scooter_updates["lng"] = body.end_lng
    scooter = await db.scooters.find_one({"scooter_id": ride["scooter_id"]}, {"_id": 0})
    if scooter:
        scooter_updates["battery"] = max(5, scooter["battery"] - max(1, minutes))
    await db.scooters.update_one({"scooter_id": ride["scooter_id"]}, {"$set": scooter_updates})

    ride.update(update)
    return sanitize_ride(ride)


@api.get("/rides/active", response_model=Optional[Ride])
async def get_active_ride(authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    ride = await db.rides.find_one(
        {"user_id": user["user_id"], "status": {"$in": ["reserved", "active"]}},
        {"_id": 0},
    )
    if not ride:
        return None
    return sanitize_ride(ride)


@api.get("/rides", response_model=List[Ride])
async def list_rides(authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    docs = await db.rides.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [sanitize_ride(d) for d in docs]


@api.get("/rides/{ride_id}", response_model=Ride)
async def get_ride(ride_id: str, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    doc = await db.rides.find_one({"ride_id": ride_id, "user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Ride not found")
    return sanitize_ride(doc)


# ============ PARKING ZONES + PHOTOS ============
def _zone_public(d: dict) -> ParkingZone:
    return ParkingZone(
        zone_id=d["zone_id"],
        name=d["name"],
        kind=d["kind"],
        lat=d["lat"],
        lng=d["lng"],
        radius_m=d["radius_m"],
        created_at=ensure_aware(d["created_at"]),
    )


async def _evaluate_parking(lat: float, lng: float) -> dict:
    zones = await db.parking_zones.find({}, {"_id": 0}).to_list(500)
    # 1) Inside a no-park zone? -> reject
    for z in zones:
        if z["kind"] == "no_park" and haversine_m(lat, lng, z["lat"], z["lng"]) <= z["radius_m"]:
            nearest = _nearest_allowed(zones, lat, lng)
            return {
                "ok": False,
                "reason": f"You're inside a no-parking zone: {z['name']}",
                "zone": z,
                "nearest_allowed": nearest[0],
                "nearest_allowed_distance_m": nearest[1],
            }
    # 2) Inside a designated / bike_rack zone? -> ok
    for z in zones:
        if z["kind"] in ("bike_rack", "designated") and haversine_m(lat, lng, z["lat"], z["lng"]) <= z["radius_m"]:
            return {"ok": True, "reason": f"Parked at {z['name']}", "zone": z}
    # 3) Not inside any zone — allow with softer message (per spec: sidewalk-off-to-the-side is ok)
    nearest = _nearest_allowed(zones, lat, lng)
    if nearest[0] and nearest[1] is not None and nearest[1] <= 60:
        # Very close to an allowed spot — treat as ok, point them to it
        return {"ok": True, "reason": f"Near {nearest[0]['name']}", "zone": None, "nearest_allowed": nearest[0], "nearest_allowed_distance_m": nearest[1]}
    return {
        "ok": True,  # spec says sidewalk-off-to-side is acceptable; still surface nearest rack
        "reason": "No designated rack here — please park off the sidewalk out of the way",
        "zone": None,
        "nearest_allowed": nearest[0],
        "nearest_allowed_distance_m": nearest[1],
    }


def _nearest_allowed(zones: list, lat: float, lng: float):
    best = None
    best_d = None
    for z in zones:
        if z["kind"] in ("bike_rack", "designated"):
            d = haversine_m(lat, lng, z["lat"], z["lng"])
            if best is None or d < best_d:
                best = z
                best_d = d
    return (best, best_d)


@api.get("/parking-zones", response_model=List[ParkingZone])
async def list_parking_zones(lat: Optional[float] = None, lng: Optional[float] = None, radius_m: Optional[float] = None):
    docs = await db.parking_zones.find({}, {"_id": 0}).to_list(500)
    if lat is not None and lng is not None and radius_m:
        docs = [d for d in docs if haversine_m(lat, lng, d["lat"], d["lng"]) <= radius_m]
    return [_zone_public(d) for d in docs]


@api.post("/parking/check", response_model=ParkingCheckResponse)
async def parking_check(body: ParkingCheckRequest, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    res = await _evaluate_parking(body.lat, body.lng)
    return ParkingCheckResponse(
        ok=res["ok"],
        reason=res.get("reason"),
        zone=_zone_public(res["zone"]) if res.get("zone") else None,
        nearest_allowed=_zone_public(res["nearest_allowed"]) if res.get("nearest_allowed") else None,
        nearest_allowed_distance_m=res.get("nearest_allowed_distance_m"),
    )


# ---- Photo upload / serve ----
class PhotoUploadResponse(BaseModel):
    path: str
    size: int


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_PHOTO_BYTES = 8 * 1024 * 1024  # 8MB


@api.post("/uploads/parking-photo", response_model=PhotoUploadResponse)
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


@api.get("/files/{full_path:path}")
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


# ---- Admin: flag improper parking + charge fee ----
class FlagImproperRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


@api.post("/rides/{ride_id}/flag-improper-parking", response_model=Ride)
async def flag_improper_parking(ride_id: str, body: FlagImproperRequest, authorization: Optional[str] = Header(None)):
    # For MVP the ride owner OR any authenticated admin can call this.
    user = await get_current_user(authorization)
    ride = await db.rides.find_one({"ride_id": ride_id}, {"_id": 0})
    if not ride:
        raise HTTPException(404, "Ride not found")
    if ride["status"] != "completed":
        raise HTTPException(409, "Ride is not completed")
    if ride.get("parking_flagged"):
        return sanitize_ride(ride)
    pm_id = ride.get("payment_method_id")
    if not pm_id:
        raise HTTPException(409, "Rider has no payment method on file")
    await mock_charge(ride["user_id"], ride_id, IMPROPER_PARKING_FEE_CENTS, "improper_parking_fee", pm_id)
    new_amount = ride.get("amount_cents", 0) + IMPROPER_PARKING_FEE_CENTS
    updated = {
        "parking_flagged": True,
        "parking_flag_reason": body.reason,
        "parking_ok": False,
        "fee_charged_cents": ride.get("fee_charged_cents", 0) + IMPROPER_PARKING_FEE_CENTS,
        "amount_cents": new_amount,
    }
    await db.rides.update_one({"ride_id": ride_id}, {"$set": updated})
    ride.update(updated)
    return sanitize_ride(ride)


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
