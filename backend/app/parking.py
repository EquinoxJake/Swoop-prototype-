"""Parking zones + server-side geofence check."""
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel

from .core.db import db
from .core.geo import ensure_aware, haversine_m
from .core.security import get_current_user

router = APIRouter()


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


async def evaluate_parking(lat: float, lng: float) -> dict:
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


@router.get("/parking-zones", response_model=List[ParkingZone])
async def list_parking_zones(lat: Optional[float] = None, lng: Optional[float] = None, radius_m: Optional[float] = None):
    docs = await db.parking_zones.find({}, {"_id": 0}).to_list(500)
    if lat is not None and lng is not None and radius_m:
        docs = [d for d in docs if haversine_m(lat, lng, d["lat"], d["lng"]) <= radius_m]
    return [_zone_public(d) for d in docs]


@router.post("/parking/check", response_model=ParkingCheckResponse)
async def parking_check(body: ParkingCheckRequest, authorization: Optional[str] = Header(None)):
    await get_current_user(authorization)
    res = await evaluate_parking(body.lat, body.lng)
    return ParkingCheckResponse(
        ok=res["ok"],
        reason=res.get("reason"),
        zone=_zone_public(res["zone"]) if res.get("zone") else None,
        nearest_allowed=_zone_public(res["nearest_allowed"]) if res.get("nearest_allowed") else None,
        nearest_allowed_distance_m=res.get("nearest_allowed_distance_m"),
    )
