"""Ride lifecycle: reserve → start → end, history, improper-parking fee."""
from datetime import datetime
from typing import List, Literal, Optional
import math
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .core.config import IMPROPER_PARKING_FEE_CENTS, METERS_PER_MILE, PER_MILE_CENTS, UNLOCK_CENTS
from .core.db import db
from .core.geo import ensure_aware, now_utc
from .core.security import get_current_user
from .parking import evaluate_parking
from .payments import get_default_payment_method, mock_charge

router = APIRouter()


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


class FlagImproperRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


def sanitize_ride(doc: dict) -> Ride:
    doc = {k: v for k, v in doc.items() if k != "_id"}
    for k in ("started_at", "ended_at", "created_at", "paid_at"):
        if doc.get(k) is not None:
            doc[k] = ensure_aware(doc[k])
    return Ride(**doc)


@router.post("/rides/reserve", response_model=Ride)
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


@router.post("/rides/start", response_model=Ride)
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


@router.post("/rides/end", response_model=Ride)
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
        parking = await evaluate_parking(body.end_lat, body.end_lng)
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


@router.get("/rides/active", response_model=Optional[Ride])
async def get_active_ride(authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    ride = await db.rides.find_one(
        {"user_id": user["user_id"], "status": {"$in": ["reserved", "active"]}},
        {"_id": 0},
    )
    if not ride:
        return None
    return sanitize_ride(ride)


@router.get("/rides", response_model=List[Ride])
async def list_rides(authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    docs = await db.rides.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [sanitize_ride(d) for d in docs]


@router.get("/rides/{ride_id}", response_model=Ride)
async def get_ride(ride_id: str, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    doc = await db.rides.find_one({"ride_id": ride_id, "user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Ride not found")
    return sanitize_ride(doc)


@router.post("/rides/{ride_id}/flag-improper-parking", response_model=Ride)
async def flag_improper_parking(ride_id: str, body: FlagImproperRequest, authorization: Optional[str] = Header(None)):
    # For MVP the ride owner OR any authenticated admin can call this.
    await get_current_user(authorization)
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
