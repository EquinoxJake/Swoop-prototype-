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
PER_MINUTE_CENTS = 35


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
    price_per_min_cents: int = PER_MINUTE_CENTS
    unlock_fee_cents: int = UNLOCK_CENTS


class Ride(BaseModel):
    ride_id: str
    user_id: str
    scooter_id: str
    scooter_code: str
    status: Literal["reserved", "active", "awaiting_payment", "paid", "cancelled"]
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    minutes: int = 0
    distance_m: int = 0
    amount_cents: int = 0
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None
    end_lat: Optional[float] = None
    end_lng: Optional[float] = None
    created_at: datetime
    stripe_session_id: Optional[str] = None
    paid_at: Optional[datetime] = None


class MockCheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str
    amount_cents: int
    minutes: int


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
                "price_per_min_cents": PER_MINUTE_CENTS,
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
                "price_per_min_cents": PER_MINUTE_CENTS,
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
            "price_per_min_cents": PER_MINUTE_CENTS,
            "unlock_fee_cents": UNLOCK_CENTS,
            "created_at": now_utc(),
        })
    if new_docs:
        await db.scooters.insert_many(new_docs)
    all_nearby = nearby + [{k: v for k, v in d.items() if k != "_id"} for d in new_docs]
    return [Scooter(**d) for d in all_nearby]


# ============ RIDES ============
class ReserveRequest(BaseModel):
    scooter_code: str


class StartRideRequest(BaseModel):
    ride_id: str


class EndRideRequest(BaseModel):
    ride_id: str
    end_lat: Optional[float] = None
    end_lng: Optional[float] = None
    distance_m: Optional[int] = None


def sanitize_ride(doc: dict) -> Ride:
    doc = {k: v for k, v in doc.items() if k != "_id"}
    for k in ("started_at", "ended_at", "created_at", "paid_at"):
        if doc.get(k) is not None:
            doc[k] = ensure_aware(doc[k])
    return Ride(**doc)


@api.post("/rides/reserve", response_model=Ride)
async def reserve_ride(body: ReserveRequest, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    scooter = await db.scooters.find_one({"code": body.scooter_code.upper()}, {"_id": 0})
    if not scooter:
        raise HTTPException(404, "Scooter not found")
    if scooter["status"] != "available":
        raise HTTPException(409, "Scooter not available")
    active = await db.rides.find_one({"user_id": user["user_id"], "status": {"$in": ["reserved", "active", "awaiting_payment"]}}, {"_id": 0})
    if active:
        raise HTTPException(409, "You already have an active ride")

    ride_id = f"ride_{uuid.uuid4().hex[:12]}"
    ride_doc = {
        "ride_id": ride_id,
        "user_id": user["user_id"],
        "scooter_id": scooter["scooter_id"],
        "scooter_code": scooter["code"],
        "status": "reserved",
        "minutes": 0,
        "distance_m": 0,
        "amount_cents": 0,
        "start_lat": scooter["lat"],
        "start_lng": scooter["lng"],
        "created_at": now_utc(),
    }
    await db.rides.insert_one(ride_doc)
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
    amount = UNLOCK_CENTS + minutes * PER_MINUTE_CENTS
    distance_m = int(body.distance_m or (minutes * 220))  # rough default

    update = {
        "status": "awaiting_payment",
        "ended_at": ended_at,
        "minutes": minutes,
        "amount_cents": amount,
        "distance_m": distance_m,
    }
    if body.end_lat is not None and body.end_lng is not None:
        update["end_lat"] = body.end_lat
        update["end_lng"] = body.end_lng

    await db.rides.update_one({"ride_id": body.ride_id}, {"$set": update})
    ride.update(update)
    return sanitize_ride(ride)


@api.get("/rides/active", response_model=Optional[Ride])
async def get_active_ride(authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    ride = await db.rides.find_one(
        {"user_id": user["user_id"], "status": {"$in": ["reserved", "active", "awaiting_payment"]}},
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


# ============ PAYMENTS (MOCKED) ============
class MockCheckoutRequest(BaseModel):
    ride_id: str


@api.post("/payments/mock-checkout", response_model=MockCheckoutResponse)
async def create_mock_checkout(body: MockCheckoutRequest, authorization: Optional[str] = Header(None)):
    """
    MOCKED payment session. In production this would call
    stripe.checkout.Session.create() and return the real hosted URL.
    """
    user = await get_current_user(authorization)
    ride = await db.rides.find_one({"ride_id": body.ride_id, "user_id": user["user_id"]}, {"_id": 0})
    if not ride:
        raise HTTPException(404, "Ride not found")
    if ride["status"] != "awaiting_payment":
        raise HTTPException(409, "Ride not awaiting payment")
    session_id = f"mock_sess_{uuid.uuid4().hex[:16]}"
    await db.rides.update_one({"ride_id": body.ride_id}, {"$set": {"stripe_session_id": session_id}})
    return MockCheckoutResponse(
        checkout_url=f"swoop://mock-checkout/{session_id}",  # in real Stripe this would be checkout.stripe.com/...
        session_id=session_id,
        amount_cents=ride["amount_cents"],
        minutes=ride["minutes"],
    )


@api.post("/payments/mock-confirm", response_model=Ride)
async def confirm_mock_payment(body: MockCheckoutRequest, authorization: Optional[str] = Header(None)):
    """MOCKED payment confirmation — simulates a successful Stripe webhook."""
    user = await get_current_user(authorization)
    ride = await db.rides.find_one({"ride_id": body.ride_id, "user_id": user["user_id"]}, {"_id": 0})
    if not ride:
        raise HTTPException(404, "Ride not found")
    if ride["status"] == "paid":
        return sanitize_ride(ride)
    if ride["status"] != "awaiting_payment":
        raise HTTPException(409, "Ride not awaiting payment")

    paid_at = now_utc()
    await db.rides.update_one(
        {"ride_id": body.ride_id},
        {"$set": {"status": "paid", "paid_at": paid_at}},
    )
    # Free scooter and update its battery/position
    updates = {"status": "available"}
    if ride.get("end_lat") is not None and ride.get("end_lng") is not None:
        updates["lat"] = ride["end_lat"]
        updates["lng"] = ride["end_lng"]
    # drain battery a bit
    scooter = await db.scooters.find_one({"scooter_id": ride["scooter_id"]}, {"_id": 0})
    if scooter:
        updates["battery"] = max(5, scooter["battery"] - max(1, ride.get("minutes", 1)))
    await db.scooters.update_one({"scooter_id": ride["scooter_id"]}, {"$set": updates})

    ride["status"] = "paid"
    ride["paid_at"] = paid_at
    return sanitize_ride(ride)


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
