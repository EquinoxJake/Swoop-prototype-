"""Parking-photo review.

After a ride ends: Claude looks at the parking photo, the result is saved on the ride,
and every admin gets a Discord DM with the photo. Photos that need a human get
"Looks good" / "Bad parking · $15" buttons. Only an admin's button press charges the fee.
"""
import base64
import json
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
import anthropic

from .core import discord
from .core.config import (
    DISCORD_ADMIN_USER_IDS,
    DISCORD_BOT_TOKEN,
    DISCORD_PUBLIC_KEY,
    IMPROPER_PARKING_FEE_CENTS,
    PARKING_AI_ENABLED,
    PARKING_AI_MODEL,
    logger,
)
from .core.db import db
from .core.geo import now_utc
from .payments import mock_charge
from .uploads import disk_path

router = APIRouter()

Placement = Literal["bike_rack", "sidewalk_out_of_way", "sidewalk_blocking", "road", "no_scooter_visible", "unclear"]
GOOD_PLACEMENTS = {"bike_rack", "sidewalk_out_of_way"}


class ParkingVerdict(BaseModel):
    placement: Placement
    reason: str


AI_PROMPT = """This photo was taken by a rider ending a rental e-scooter ride. Classify where the scooter is parked.

- bike_rack: at or locked to a bike rack or a marked scooter parking spot.
- sidewalk_out_of_way: on the sidewalk, upright, pushed to the edge (by the curb, wall or grass) so people can still walk past.
- sidewalk_blocking: on the sidewalk but in the middle of the walking path, lying down, or blocking a ramp, door, stairs or crosswalk.
- road: in the street, bike lane, or parking lane where cars or bikes drive.
- no_scooter_visible: no scooter can be seen in the photo.
- unclear: too dark, blurry or close up to tell.

Give the placement and one short sentence a human reviewer can read in a notification."""

_ai = anthropic.AsyncAnthropic() if PARKING_AI_ENABLED else None


async def check_photo_with_ai(image: bytes, media_type: str) -> Optional[ParkingVerdict]:
    """Ask Claude where the scooter is parked. Returns None when the AI is off or fails,
    so the photo falls back to a human check."""
    if _ai is None:
        return None
    try:
        response = await _ai.beta.messages.parse(
            model=PARKING_AI_MODEL,
            max_tokens=16000,
            output_config={"effort": "low"},
            # On a safety decline, retry on Anthropic's recommended fallback model
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_format=ParkingVerdict,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.standard_b64encode(image).decode(),
                    }},
                    {"type": "text", "text": AI_PROMPT},
                ],
            }],
        )
    except anthropic.APIStatusError as e:
        logger.warning("Parking AI request failed (%s): %s", e.status_code, e.message)
        return None
    except anthropic.APIConnectionError as e:
        logger.warning("Parking AI unreachable: %s", e)
        return None
    if response.stop_reason == "refusal" or response.parsed_output is None:
        logger.warning("Parking AI gave no verdict (stop_reason=%s)", response.stop_reason)
        return None
    return response.parsed_output


def needs_human_check(verdict: Optional[ParkingVerdict], parking_ok: Optional[bool]) -> bool:
    return verdict is None or verdict.placement not in GOOD_PLACEMENTS or parking_ok is False


def _dm_text(ride: dict, verdict: Optional[ParkingVerdict], needs_check: bool) -> str:
    ai = f"🤖 AI: **{verdict.placement.replace('_', ' ')}**: {verdict.reason}" if verdict else "🤖 AI: no verdict"
    zone = {True: "inside an allowed spot", False: "⛔ in a no-park zone", None: "no GPS"}[ride.get("parking_ok")]
    lines = [
        ("⚠️ **CHECK NEEDED**" if needs_check else "✅ Parked fine"),
        f"🛴 {ride['scooter_code']} · {ride.get('miles', 0):.2f} mi · ride `{ride['ride_id']}`",
        ai,
        f"📍 GPS: {zone}",
    ]
    if ride.get("end_lat") is not None:
        lines.append(f"🗺️ https://maps.google.com/?q={ride['end_lat']},{ride['end_lng']}")
    return "\n".join(lines)


def _buttons(ride_id: str) -> list[dict]:
    return [
        {"type": 2, "style": 3, "label": "Looks good", "custom_id": f"approve:{ride_id}"},
        {"type": 2, "style": 4, "label": "Bad parking · charge $15", "custom_id": f"flag:{ride_id}"},
    ]


async def send_for_review(ride_id: str) -> None:
    """Run after a ride ends (background task). Never raises: a review problem must not affect the rider."""
    try:
        ride = await db.rides.find_one({"ride_id": ride_id}, {"_id": 0})
        if not ride or not ride.get("end_photo_path"):
            return
        path = disk_path(ride["end_photo_path"])
        image = await run_in_threadpool(path.read_bytes) if path.is_file() else None
        media_type = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(path.suffix.lstrip("."), "image/jpeg")

        verdict = await check_photo_with_ai(image, media_type) if image else None
        needs_check = needs_human_check(verdict, ride.get("parking_ok"))
        await db.rides.update_one({"ride_id": ride_id}, {"$set": {
            "ai_parking": verdict.model_dump() if verdict else None,
            "review_status": "needs_check" if needs_check else "ai_ok",
        }})

        if not DISCORD_BOT_TOKEN:
            return
        text = _dm_text(ride, verdict, needs_check)
        attachment = (path.name, image, media_type) if image else None
        for admin_id in DISCORD_ADMIN_USER_IDS:
            await discord.send_dm(admin_id, text, attachment, _buttons(ride_id) if needs_check else None)
    except Exception:
        logger.exception("Parking review failed for ride %s", ride_id)


async def flag_ride(ride_id: str, reason: str) -> dict:
    """Charge the improper-parking fee once. Returns the updated ride document."""
    ride = await db.rides.find_one({"ride_id": ride_id}, {"_id": 0})
    if not ride:
        raise HTTPException(404, "Ride not found")
    if ride["status"] != "completed":
        raise HTTPException(409, "Ride is not completed")
    if ride.get("parking_flagged"):
        return ride
    pm_id = ride.get("payment_method_id")
    if not pm_id:
        raise HTTPException(409, "Rider has no payment method on file")
    # Claim the flag atomically first so two clicks can never charge twice
    claimed = await db.rides.update_one(
        {"ride_id": ride_id, "parking_flagged": {"$ne": True}},
        {"$set": {"parking_flagged": True}},
    )
    if claimed.modified_count == 0:
        return await db.rides.find_one({"ride_id": ride_id}, {"_id": 0})
    await mock_charge(ride["user_id"], ride_id, IMPROPER_PARKING_FEE_CENTS, "improper_parking_fee", pm_id)
    updated = {
        "parking_flagged": True,
        "parking_flag_reason": reason,
        "parking_ok": False,
        "fee_charged_cents": ride.get("fee_charged_cents", 0) + IMPROPER_PARKING_FEE_CENTS,
        "amount_cents": ride.get("amount_cents", 0) + IMPROPER_PARKING_FEE_CENTS,
        "review_status": "flagged",
    }
    await db.rides.update_one({"ride_id": ride_id}, {"$set": updated})
    ride.update(updated)
    return ride


def _reply(content: str, ephemeral: bool = False) -> dict:
    return {"type": 4, "data": {"content": content, **({"flags": 64} if ephemeral else {})}}


@router.post("/discord/interactions")
async def discord_interactions(request: Request):
    """Discord calls this when an admin presses a button. Set it as the app's Interactions Endpoint URL."""
    body = await request.body()
    if not DISCORD_PUBLIC_KEY or not discord.verify_signature(
        DISCORD_PUBLIC_KEY,
        request.headers.get("X-Signature-Ed25519", ""),
        request.headers.get("X-Signature-Timestamp", ""),
        body,
    ):
        raise HTTPException(401, "Invalid request signature")
    interaction = json.loads(body)

    if interaction["type"] == 1:  # PING, sent when you save the endpoint URL
        return {"type": 1}
    if interaction["type"] != 3:  # only button presses
        return _reply("Unsupported interaction", ephemeral=True)

    user = (interaction.get("member") or {}).get("user") or interaction.get("user") or {}
    if user.get("id") not in DISCORD_ADMIN_USER_IDS:
        return _reply("You're not a Swoop admin.", ephemeral=True)

    action, _, ride_id = interaction["data"]["custom_id"].partition(":")
    who = user.get("username", "admin")
    original = interaction.get("message", {}).get("content", "")
    if action == "approve":
        result = await db.rides.update_one(
            {"ride_id": ride_id, "parking_flagged": {"$ne": True}},
            {"$set": {"review_status": "approved", "reviewed_by": who, "reviewed_at": now_utc()}},
        )
        if result.matched_count == 0:
            return _reply("Ride not found or already flagged", ephemeral=True)
        outcome = f"✅ Approved by {who}"
    elif action == "flag":
        try:
            ride = await flag_ride(ride_id, f"Flagged in Discord by {who}")
        except HTTPException as e:
            return _reply(f"Couldn't flag: {e.detail}", ephemeral=True)
        await db.rides.update_one({"ride_id": ride_id}, {"$set": {"reviewed_by": who, "reviewed_at": now_utc()}})
        outcome = f"🚩 Flagged by {who} · ${IMPROPER_PARKING_FEE_CENTS / 100:.2f} charged (ride total ${ride['amount_cents'] / 100:.2f})"
    else:
        return _reply("Unknown button", ephemeral=True)

    # UPDATE_MESSAGE: keep the photo, append the outcome, remove the buttons
    return {"type": 7, "data": {"content": f"{original}\n\n{outcome}", "components": []}}
