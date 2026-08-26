"""
Swoop backend tests — new pricing flow.
- Card required on file before reserve
- $1.00 unlock charged on reserve
- $0.20/mile GPS-based mileage auto-charged on ride end (no separate Pay)
- No 'awaiting_payment' status

NOTE: pytest is configured with `-n 2 --dist loadscope` (see /app/backend/pytest.ini),
which pins one test class per worker. All flow tests live in a SINGLE class
so they share a single fresh user + preview backend state.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL", "https://scoot-pay-go.preview.emergentagent.com")).rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def fresh_user(api_client):
    ts = int(time.time() * 1000)
    email = f"ridertest+{ts}_{uuid.uuid4().hex[:8]}@example.com"
    password = "testpass1"
    r = api_client.post(f"{API}/auth/signup", json={"email": email, "password": password, "name": "Rider Test"})
    assert r.status_code == 200, f"signup failed: {r.status_code} {r.text}"
    data = r.json()
    return {"email": email, "password": password, "token": data["session_token"], "user": data["user"]}


@pytest.fixture(scope="module")
def auth_headers(fresh_user):
    return {"Authorization": f"Bearer {fresh_user['token']}", "Content-Type": "application/json"}


def _pick_available_scooter(api_client):
    r = api_client.get(f"{API}/scooters")
    assert r.status_code == 200
    for s in r.json():
        if s["status"] == "available":
            return s
    pytest.skip("No available scooter to test with")


class TestSwoopFullFlow:
    """End-to-end flow in one class so xdist loadscope keeps state on a single worker."""

    ride_id = None
    pm_id = None

    # ---- health ----
    def test_00_root(self, api_client):
        r = api_client.get(f"{API}/")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    # ---- payment methods (no card yet) ----
    def test_01_payment_methods_empty_for_fresh_user(self, api_client, auth_headers):
        r = api_client.get(f"{API}/payment-methods", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json() == []

    def test_02_reserve_without_card_returns_402(self, api_client, auth_headers):
        scooter = _pick_available_scooter(api_client)
        r = api_client.post(f"{API}/rides/reserve", headers=auth_headers, json={"scooter_code": scooter["code"]})
        assert r.status_code == 402, f"expected 402, got {r.status_code} {r.text}"
        assert "payment method" in r.json().get("detail", "").lower()

    def test_03_invalid_card_letters_rejected(self, api_client, auth_headers):
        r = api_client.post(f"{API}/payment-methods", headers=auth_headers,
                            json={"number": "4242abcd4242", "exp_month": 5, "exp_year": 2030, "cvc": "123"})
        assert r.status_code == 400, r.text

    def test_04_invalid_card_short_rejected(self, api_client, auth_headers):
        r = api_client.post(f"{API}/payment-methods", headers=auth_headers,
                            json={"number": "4242", "exp_month": 5, "exp_year": 2030, "cvc": "123"})
        assert r.status_code == 400, r.text

    def test_05_add_first_card_is_default(self, api_client, auth_headers):
        payload = {"number": "4242424242424242", "exp_month": 12, "exp_year": 2030, "cvc": "123"}
        r = api_client.post(f"{API}/payment-methods", headers=auth_headers, json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["brand"] == "Visa"
        assert d["last4"] == "4242"
        assert d["is_default"] is True
        assert d["exp_month"] == 12 and d["exp_year"] == 2030
        TestSwoopFullFlow.pm_id = d["payment_method_id"]
        # GET verifies persistence
        cards = api_client.get(f"{API}/payment-methods", headers=auth_headers).json()
        assert len(cards) == 1 and cards[0]["payment_method_id"] == d["payment_method_id"]

    # ---- ride lifecycle ----
    def test_06_no_active_ride_initially(self, api_client, auth_headers):
        r = api_client.get(f"{API}/rides/active", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() is None

    def test_07_reserve_returns_ride_with_unlock_fee(self, api_client, auth_headers):
        scooter = _pick_available_scooter(api_client)
        r = api_client.post(f"{API}/rides/reserve", headers=auth_headers, json={"scooter_code": scooter["code"]})
        assert r.status_code == 200, r.text
        ride = r.json()
        TestSwoopFullFlow.ride_id = ride["ride_id"]
        assert ride["status"] == "reserved"
        assert ride["unlock_charged_cents"] == 100
        assert ride["amount_cents"] == 100
        assert ride["payment_method_id"] == TestSwoopFullFlow.pm_id

    def test_08_start_ride(self, api_client, auth_headers):
        assert TestSwoopFullFlow.ride_id
        r = api_client.post(f"{API}/rides/start", headers=auth_headers, json={"ride_id": TestSwoopFullFlow.ride_id})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"

    def test_09_end_ride_auto_charges_mileage(self, api_client, auth_headers):
        assert TestSwoopFullFlow.ride_id
        r = api_client.post(
            f"{API}/rides/end",
            headers=auth_headers,
            json={"ride_id": TestSwoopFullFlow.ride_id, "distance_m": 1610, "end_lat": 32.42, "end_lng": -81.78},
        )
        assert r.status_code == 200, r.text
        ride = r.json()
        assert ride["status"] == "completed"
        # 1610m -> ~1.0004 miles; ceil(1.0004*20) = 21, or 20 if computed slightly different
        assert ride["mileage_charged_cents"] in (20, 21), f"unexpected: {ride['mileage_charged_cents']}"
        assert ride["amount_cents"] in (120, 121)
        assert ride["paid_at"] is not None
        assert abs(ride["miles"] - 1.0) < 0.01
        assert ride["unlock_charged_cents"] == 100

    def test_10_active_ride_null_after_completion(self, api_client, auth_headers):
        r = api_client.get(f"{API}/rides/active", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() is None

    def test_11_ride_statuses_have_no_awaiting_payment(self, api_client, auth_headers):
        r = api_client.get(f"{API}/rides", headers=auth_headers)
        assert r.status_code == 200
        allowed = {"reserved", "active", "completed", "cancelled"}
        for ride in r.json():
            assert ride["status"] in allowed, f"bad status {ride['status']}"

    def test_12_completed_ride_totals(self, api_client, auth_headers):
        r = api_client.get(f"{API}/rides/{TestSwoopFullFlow.ride_id}", headers=auth_headers)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["status"] == "completed"
        assert c["unlock_charged_cents"] == 100
        assert c["mileage_charged_cents"] in (20, 21)
        assert c["amount_cents"] == c["unlock_charged_cents"] + c["mileage_charged_cents"]
        assert c["payment_method_id"] is not None

    # ---- payment method management ----
    def test_13_add_second_card_default_swap_and_delete_promotes(self, api_client, auth_headers):
        add = api_client.post(f"{API}/payment-methods", headers=auth_headers,
                              json={"number": "5555555555554444", "exp_month": 6, "exp_year": 2031, "cvc": "321"})
        assert add.status_code == 200, add.text
        second = add.json()
        assert second["brand"] == "Mastercard"
        assert second["last4"] == "4444"
        assert second["is_default"] is False

        cards = api_client.get(f"{API}/payment-methods", headers=auth_headers).json()
        assert len(cards) == 2
        first = next(c for c in cards if c["last4"] == "4242")
        assert first["is_default"] is True

        # Set Mastercard as default
        sd = api_client.post(f"{API}/payment-methods/{second['payment_method_id']}/default", headers=auth_headers)
        assert sd.status_code == 200, sd.text
        assert sd.json()["is_default"] is True

        cards = api_client.get(f"{API}/payment-methods", headers=auth_headers).json()
        defaults = [c for c in cards if c["is_default"]]
        assert len(defaults) == 1 and defaults[0]["last4"] == "4444"

        # Delete the current default (Mastercard) -> Visa should be promoted
        de = api_client.delete(f"{API}/payment-methods/{second['payment_method_id']}", headers=auth_headers)
        assert de.status_code == 200, de.text
        cards = api_client.get(f"{API}/payment-methods", headers=auth_headers).json()
        assert len(cards) == 1
        assert cards[0]["last4"] == "4242"
        assert cards[0]["is_default"] is True
        TestSwoopFullFlow.pm_id = cards[0]["payment_method_id"]

    def test_14_delete_last_card_then_reserve_402_again(self, api_client, auth_headers):
        cards = api_client.get(f"{API}/payment-methods", headers=auth_headers).json()
        for c in cards:
            r = api_client.delete(f"{API}/payment-methods/{c['payment_method_id']}", headers=auth_headers)
            assert r.status_code == 200
        cards = api_client.get(f"{API}/payment-methods", headers=auth_headers).json()
        assert cards == []
        scooter = _pick_available_scooter(api_client)
        r = api_client.post(f"{API}/rides/reserve", headers=auth_headers, json={"scooter_code": scooter["code"]})
        assert r.status_code == 402
