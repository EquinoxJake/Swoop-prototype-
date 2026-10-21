"""
Parking-photo review: AI verdict handling, Discord DM payload, and the Discord button endpoint.

Unit tests run in-process with fakes (no real Claude or Discord calls).
The endpoint tests hit the running server, which must be started with:
    DISCORD_PUBLIC_KEY=03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8
    DISCORD_ADMIN_USER_IDS=111111
(the public half of TEST_SIGNING_KEY below) and without DISCORD_BOT_TOKEN / ANTHROPIC_API_KEY.
"""
import asyncio
import json
import os
import time
import uuid
from types import SimpleNamespace

import anthropic
import httpx
import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import review
from app.core import discord

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TEST_SIGNING_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
TEST_PUBLIC_HEX = "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"
ADMIN_DISCORD_ID = "111111"
JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")


# ---------- unit: signature ----------
def _sign(body: bytes, ts: str = "1700000000") -> dict:
    return {"X-Signature-Ed25519": TEST_SIGNING_KEY.sign(ts.encode() + body).hex(), "X-Signature-Timestamp": ts}


def test_signature_accepts_discord_signed_body():
    h = _sign(b'{"type":1}')
    assert discord.verify_signature(TEST_PUBLIC_HEX, h["X-Signature-Ed25519"], h["X-Signature-Timestamp"], b'{"type":1}')


def test_signature_rejects_tampered_body_and_garbage():
    h = _sign(b'{"type":1}')
    assert not discord.verify_signature(TEST_PUBLIC_HEX, h["X-Signature-Ed25519"], h["X-Signature-Timestamp"], b'{"type":2}')
    assert not discord.verify_signature(TEST_PUBLIC_HEX, "zz", "1", b"{}")


# ---------- unit: when a human must look ----------
@pytest.mark.parametrize("placement,parking_ok,expected", [
    ("bike_rack", True, False),
    ("sidewalk_out_of_way", None, False),
    ("bike_rack", False, True),            # AI happy but GPS says no-park zone
    ("sidewalk_blocking", True, True),
    ("road", True, True),
    ("no_scooter_visible", True, True),
    ("unclear", True, True),
])
def test_needs_human_check(placement, parking_ok, expected):
    verdict = review.ParkingVerdict(placement=placement, reason="x")
    assert review.needs_human_check(verdict, parking_ok) is expected


def test_no_ai_verdict_always_needs_check():
    assert review.needs_human_check(None, True) is True


# ---------- unit: the Claude call ----------
def _fake_ai(monkeypatch, response=None, error=None):
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        return response

    monkeypatch.setattr(review, "_ai", SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse))))
    return calls


def test_ai_verdict_is_returned_and_photo_is_sent(monkeypatch):
    verdict = review.ParkingVerdict(placement="road", reason="Scooter is in the bike lane.")
    calls = _fake_ai(monkeypatch, SimpleNamespace(stop_reason="end_turn", parsed_output=verdict))
    assert asyncio.run(review.check_photo_with_ai(JPEG, "image/jpeg")) == verdict
    image = calls[0]["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    assert calls[0]["output_format"] is review.ParkingVerdict


def test_ai_refusal_falls_back_to_human(monkeypatch):
    _fake_ai(monkeypatch, SimpleNamespace(stop_reason="refusal", parsed_output=None))
    assert asyncio.run(review.check_photo_with_ai(JPEG, "image/jpeg")) is None


def test_ai_outage_falls_back_to_human(monkeypatch):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    _fake_ai(monkeypatch, error=anthropic.APIConnectionError(request=req))
    assert asyncio.run(review.check_photo_with_ai(JPEG, "image/jpeg")) is None


def test_ai_off_without_key(monkeypatch):
    monkeypatch.setattr(review, "_ai", None)
    assert asyncio.run(review.check_photo_with_ai(JPEG, "image/jpeg")) is None


# ---------- unit: the Discord DM ----------
def test_send_dm_posts_photo_and_buttons(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path.endswith("/users/@me/channels"):
            return httpx.Response(200, json={"id": "dm1"})
        return httpx.Response(200, json={"id": "msg1"})

    monkeypatch.setattr(discord, "_http", httpx.AsyncClient(base_url=discord.API, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(discord, "DISCORD_BOT_TOKEN", "tok")
    msg_id = asyncio.run(discord.send_dm("42", "hello", ("p.jpg", JPEG, "image/jpeg"), review._buttons("ride_1")))

    assert msg_id == "msg1"
    open_dm, post = seen
    assert json.loads(open_dm.content) == {"recipient_id": "42"}
    assert post.url.path.endswith("/channels/dm1/messages")
    assert post.headers["Authorization"] == "Bot tok"
    body = post.content.decode("latin-1")
    assert 'name="files[0]"; filename="p.jpg"' in body
    assert "attachment://p.jpg" in body and "flag:ride_1" in body and "approve:ride_1" in body


def test_dm_text_marks_checks():
    ride = {"ride_id": "r1", "scooter_code": "SW-1", "miles": 1.234, "parking_ok": False, "end_lat": 1.0, "end_lng": 2.0}
    text = review._dm_text(ride, review.ParkingVerdict(placement="road", reason="In the street."), True)
    assert text.startswith("⚠️ **CHECK NEEDED**")
    assert "SW-1" in text and "1.23 mi" in text and "road" in text and "no-park zone" in text
    assert "maps.google.com/?q=1.0,2.0" in text


# ---------- endpoint: Discord buttons on a real completed ride ----------
def _signup(email):
    r = requests.post(f"{API}/auth/signup", json={"email": email, "password": "testpass1", "name": "T"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['session_token']}"}


def _completed_ride() -> tuple[str, dict]:
    h = _signup(f"review+{uuid.uuid4().hex[:10]}@ex.com")
    assert requests.post(f"{API}/payment-methods", headers=h,
                         json={"number": "4242424242424242", "exp_month": 12, "exp_year": 2030, "cvc": "123"}).status_code == 200
    # Own scooter at a random spot so parallel tests never reserve the same one
    lat, lng = 40 + uuid.uuid4().int % 1000 / 100, -100 - uuid.uuid4().int % 1000 / 100
    scooter = requests.post(f"{API}/scooters/seed-near", json={"lat": lat, "lng": lng, "radius_m": 50, "count": 1}).json()[0]
    rid = requests.post(f"{API}/rides/reserve", headers=h, json={"scooter_code": scooter["code"]}).json()["ride_id"]
    assert requests.post(f"{API}/rides/start", headers=h, json={"ride_id": rid}).status_code == 200
    photo = requests.post(f"{API}/uploads/parking-photo", params={"ride_id": rid}, headers=h,
                          files={"file": ("p.jpg", JPEG, "image/jpeg")}).json()["path"]
    r = requests.post(f"{API}/rides/end", headers=h, json={
        "ride_id": rid, "distance_m": 800, "end_lat": 32.4176, "end_lng": -81.7811, "end_photo_path": photo})
    assert r.status_code == 200, r.text
    # Review runs in the background; with no AI key it must land on needs_check
    for _ in range(20):
        if requests.get(f"{API}/rides/{rid}", headers=h).json().get("review_status"):
            break
        time.sleep(0.1)
    assert requests.get(f"{API}/rides/{rid}", headers=h).json()["review_status"] == "needs_check"
    return rid, h


def _press(custom_id: str, user_id: str = ADMIN_DISCORD_ID):
    body = json.dumps({"type": 3, "data": {"custom_id": custom_id}, "user": {"id": user_id, "username": "jake"},
                       "message": {"content": "⚠️ **CHECK NEEDED**"}}).encode()
    return requests.post(f"{API}/discord/interactions", data=body, headers={**_sign(body), "Content-Type": "application/json"})


def test_endpoint_answers_discord_ping():
    body = b'{"type":1}'
    r = requests.post(f"{API}/discord/interactions", data=body, headers=_sign(body))
    assert r.status_code == 200 and r.json() == {"type": 1}


def test_endpoint_rejects_unsigned_requests():
    r = requests.post(f"{API}/discord/interactions", data=b'{"type":1}',
                      headers={"X-Signature-Ed25519": "00" * 64, "X-Signature-Timestamp": "1"})
    assert r.status_code == 401


def test_non_admin_cannot_press_buttons():
    rid, _ = _completed_ride()
    r = _press(f"flag:{rid}", user_id="999")
    assert r.json()["data"]["flags"] == 64  # private "not an admin" reply
    assert "not a Swoop admin" in r.json()["data"]["content"]


def test_approve_button():
    rid, h = _completed_ride()
    r = _press(f"approve:{rid}")
    assert r.json()["type"] == 7 and r.json()["data"]["components"] == []
    assert "Approved by jake" in r.json()["data"]["content"]
    ride = requests.get(f"{API}/rides/{rid}", headers=h).json()
    assert ride["review_status"] == "approved" and ride["fee_charged_cents"] == 0


def test_flag_button_charges_once():
    rid, h = _completed_ride()
    before = requests.get(f"{API}/rides/{rid}", headers=h).json()["amount_cents"]
    r = _press(f"flag:{rid}")
    assert r.json()["type"] == 7 and "Flagged by jake" in r.json()["data"]["content"]
    _press(f"flag:{rid}")  # double tap
    ride = requests.get(f"{API}/rides/{rid}", headers=h).json()
    assert ride["review_status"] == "flagged" and ride["parking_flagged"] is True
    assert ride["fee_charged_cents"] == 1500 and ride["amount_cents"] == before + 1500

    # Another admin pressing "Looks good" afterwards must not undo the flag
    late = _press(f"approve:{rid}")
    assert "already flagged" in late.json()["data"]["content"]
    assert requests.get(f"{API}/rides/{rid}", headers=h).json()["review_status"] == "flagged"
