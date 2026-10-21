"""Minimal Discord REST client: DM a user (with an image and buttons) and verify interaction signatures."""
import json
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import httpx

from .config import DISCORD_BOT_TOKEN

API = "https://discord.com/api/v10"
_http = httpx.AsyncClient(base_url=API, timeout=20)


def _headers() -> dict:
    return {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}


async def send_dm(
    user_id: str,
    content: str,
    image: Optional[tuple[str, bytes, str]] = None,
    buttons: Optional[list[dict]] = None,
) -> str:
    """DM `user_id`. `image` is (filename, bytes, content_type); `buttons` are Discord button objects.
    Returns the message id."""
    dm = await _http.post("/users/@me/channels", headers=_headers(), json={"recipient_id": user_id})
    dm.raise_for_status()
    channel_id = dm.json()["id"]

    payload: dict = {"content": content}
    if buttons:
        payload["components"] = [{"type": 1, "components": buttons}]  # one action row
    files = None
    if image:
        filename, data, ctype = image
        payload["attachments"] = [{"id": 0, "filename": filename}]
        payload["embeds"] = [{"image": {"url": f"attachment://{filename}"}}]
        files = {"files[0]": (filename, data, ctype)}

    msg = await _http.post(
        f"/channels/{channel_id}/messages",
        headers=_headers(),
        data={"payload_json": json.dumps(payload)},
        files=files,
    )
    msg.raise_for_status()
    return msg.json()["id"]


def verify_signature(public_key_hex: str, signature_hex: str, timestamp: str, body: bytes) -> bool:
    """Discord signs every interaction with Ed25519 over timestamp + raw body."""
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        key.verify(bytes.fromhex(signature_hex), timestamp.encode() + body)
        return True
    except (InvalidSignature, ValueError):
        return False
