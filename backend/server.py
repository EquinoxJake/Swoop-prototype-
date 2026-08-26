"""
Swoop — Scooter Rental Backend
Auth (email/password + Emergent Google), scooters, rides, mocked payments.
"""
from fastapi import FastAPI, APIRouter, HTTPException, Header, Request
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
    amount_cents: int = 0
    payment_method_id: Optional[str] = None
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None
    end_lat: Optional[float] = None
    end_lng: Optional[float] = None
    route: List[List[float]] = Field(default_factory=list)  # [[lat, lng], ...]
    paused_seconds: int = 0
    created_at: datetime
    paid_at: Optional[datetime] = None


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
    kind: Literal["unlock", "mileage"]
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


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
