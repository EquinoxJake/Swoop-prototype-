"""Scooter list, lookup by code, demo seeding near the rider."""
from typing import List, Literal, Optional
import math
import random
import re
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .core.config import PER_MILE_CENTS, UNLOCK_CENTS
from .core.db import db
from .core.geo import haversine_m, now_utc

router = APIRouter()


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


class SeedNearRequest(BaseModel):
    lat: float
    lng: float
    radius_m: float = 500.0
    count: int = 12


@router.get("/scooters", response_model=List[Scooter])
async def list_scooters(lat: Optional[float] = None, lng: Optional[float] = None, radius_m: Optional[float] = None):
    query = {}
    docs = await db.scooters.find(query, {"_id": 0}).to_list(500)
    if lat is not None and lng is not None and radius_m:
        docs = [d for d in docs if haversine_m(lat, lng, d["lat"], d["lng"]) <= radius_m]
    return [Scooter(**d) for d in docs]


@router.get("/scooters/{code}", response_model=Scooter)
async def get_scooter(code: str):
    doc = await db.scooters.find_one({"code": code.upper()}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scooter not found")
    return Scooter(**doc)


@router.post("/scooters/seed-near", response_model=List[Scooter])
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
