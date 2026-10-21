"""BLE unlock tokens ("unhackable" unlock).

Per-scooter shared secret lives ONLY in Mongo — never sent to the app.
App requests a token per ride. Token = HMAC-SHA256(secret, nonce|ride_id|ts|user_id|expiry).
Scooter firmware verifies the signature and rejects tokens outside a ±30s window,
already-seen nonces, or wrong ride/scooter.
"""
from datetime import datetime, timedelta
from typing import Optional
import hashlib
import hmac
import secrets as pysecrets
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .core.db import db
from .core.geo import ensure_aware, now_utc
from .core.security import get_current_user

router = APIRouter()

BLE_TOKEN_TTL_SECONDS = 60
BLE_TOKEN_RATE_LIMIT_PER_MIN = 4  # per ride


class BleTokenResponse(BaseModel):
    token_id: str
    ride_id: str
    scooter_code: str
    nonce_hex: str
    signature_hex: str
    issued_at: datetime
    expires_at: datetime
    ttl_seconds: int
    # The exact byte payload to write to the scooter's unlock characteristic:
    payload_hex: str


class BleAckRequest(BaseModel):
    token_id: str
    success: bool
    detail: Optional[str] = None


async def _get_or_create_scooter_secret(scooter_id: str) -> bytes:
    doc = await db.scooter_secrets.find_one({"scooter_id": scooter_id}, {"_id": 0})
    if doc:
        return bytes.fromhex(doc["secret_hex"])
    secret = pysecrets.token_bytes(32)
    await db.scooter_secrets.insert_one({
        "scooter_id": scooter_id,
        "secret_hex": secret.hex(),
        "rotated_at": now_utc(),
        "created_at": now_utc(),
    })
    return secret


@router.post("/rides/{ride_id}/ble-token", response_model=BleTokenResponse)
async def mint_ble_token(ride_id: str, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    ride = await db.rides.find_one({"ride_id": ride_id, "user_id": user["user_id"]}, {"_id": 0})
    if not ride:
        raise HTTPException(404, "Ride not found")
    if ride["status"] not in ("reserved", "active"):
        raise HTTPException(409, "Ride is not active — cannot mint BLE token")

    # Rate limit: max N mints per ride per minute
    since = now_utc() - timedelta(seconds=60)
    recent = await db.ble_tokens.count_documents({"ride_id": ride_id, "issued_at": {"$gte": since}})
    if recent >= BLE_TOKEN_RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "Too many unlock attempts — wait a moment and try again")

    secret = await _get_or_create_scooter_secret(ride["scooter_id"])
    nonce = pysecrets.token_bytes(16)
    issued_at = now_utc()
    expires_at = issued_at + timedelta(seconds=BLE_TOKEN_TTL_SECONDS)
    ts = int(issued_at.timestamp())

    # Signed payload the scooter firmware will verify
    payload_parts = [
        nonce,
        ride_id.encode(),
        ride["scooter_id"].encode(),
        user["user_id"].encode(),
        ts.to_bytes(8, "big"),
        int(expires_at.timestamp()).to_bytes(8, "big"),
    ]
    payload = b"".join(payload_parts)
    signature = hmac.new(secret, payload, hashlib.sha256).digest()
    # This is exactly what the phone writes to the scooter's unlock characteristic:
    #   [ ride_id_len(1)+ride_id | nonce(16) | ts(8) | expires(8) | signature(32) ]
    # Kept short so it fits in a single BLE MTU write.
    ride_id_bytes = ride_id.encode()
    wire = bytes([len(ride_id_bytes)]) + ride_id_bytes + nonce + ts.to_bytes(8, "big") + int(expires_at.timestamp()).to_bytes(8, "big") + signature

    token_id = f"bt_{uuid.uuid4().hex[:12]}"
    await db.ble_tokens.insert_one({
        "token_id": token_id,
        "ride_id": ride_id,
        "user_id": user["user_id"],
        "scooter_id": ride["scooter_id"],
        "nonce_hex": nonce.hex(),
        "signature_hex": signature.hex(),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "consumed": False,
    })

    return BleTokenResponse(
        token_id=token_id,
        ride_id=ride_id,
        scooter_code=ride["scooter_code"],
        nonce_hex=nonce.hex(),
        signature_hex=signature.hex(),
        issued_at=issued_at,
        expires_at=expires_at,
        ttl_seconds=BLE_TOKEN_TTL_SECONDS,
        payload_hex=wire.hex(),
    )


@router.post("/rides/{ride_id}/ble-ack")
async def ble_ack(ride_id: str, body: BleAckRequest, authorization: Optional[str] = Header(None)):
    """Phone reports whether the scooter accepted the unlock. Used to burn the nonce (anti-replay)."""
    user = await get_current_user(authorization)
    tok = await db.ble_tokens.find_one({"token_id": body.token_id, "ride_id": ride_id, "user_id": user["user_id"]}, {"_id": 0})
    if not tok:
        raise HTTPException(404, "Token not found")
    if tok.get("consumed"):
        return {"ok": True, "already": True}
    if ensure_aware(tok["expires_at"]) < now_utc():
        raise HTTPException(410, "Token expired")
    # Burn the nonce so it can never be replayed even if the scooter is offline for a while
    await db.used_ble_nonces.insert_one({
        "nonce": tok["nonce_hex"],
        "ride_id": ride_id,
        "consumed_at": now_utc(),
        "expires_at": now_utc() + timedelta(hours=24),
    })
    await db.ble_tokens.update_one({"token_id": body.token_id}, {"$set": {"consumed": True, "success": body.success, "detail": body.detail}})
    return {"ok": True}
