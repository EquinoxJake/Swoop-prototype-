"""Swoop backend integration tests — auth, scooters, ride lifecycle, mock payments."""
import os
import uuid
import time
import requests
import pytest

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://scoot-pay-go.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

DEMO_EMAIL = "demo@swoop.app"
DEMO_PASSWORD = "swoop1234"


@pytest.fixture(scope="session")
def demo_token():
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"demo login failed: {r.status_code} {r.text}"
    return r.json()["session_token"]


@pytest.fixture(scope="session")
def new_user():
    email = f"TEST_{uuid.uuid4().hex[:10]}@example.com"
    pw = "swooptest123"
    r = requests.post(f"{API}/auth/signup", json={"email": email, "password": pw, "name": "TEST User"}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    return {"email": email, "password": pw, "token": data["session_token"], "user": data["user"]}


# ============ AUTH ============
class TestAuth:
    def test_root(self):
        r = requests.get(f"{API}/", timeout=10)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_signup_and_login(self, new_user):
        # login again to confirm password stored
        r = requests.post(f"{API}/auth/login", json={"email": new_user["email"], "password": new_user["password"]})
        assert r.status_code == 200
        assert "session_token" in r.json()

    def test_signup_duplicate(self, new_user):
        r = requests.post(f"{API}/auth/signup", json={"email": new_user["email"], "password": "x123456"})
        assert r.status_code == 409

    def test_login_wrong_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_me_requires_token(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401
        r2 = requests.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage"})
        assert r2.status_code == 401

    def test_me_ok(self, demo_token):
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {demo_token}"})
        assert r.status_code == 200
        assert r.json()["email"] == DEMO_EMAIL

    def test_logout_invalidates(self):
        # login fresh, then logout, then me should fail
        r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        tok = r.json()["session_token"]
        h = {"Authorization": f"Bearer {tok}"}
        assert requests.get(f"{API}/auth/me", headers=h).status_code == 200
        assert requests.post(f"{API}/auth/logout", headers=h).status_code == 200
        assert requests.get(f"{API}/auth/me", headers=h).status_code == 401


# ============ SCOOTERS ============
class TestScooters:
    def test_list(self, demo_token):
        r = requests.get(f"{API}/scooters", headers={"Authorization": f"Bearer {demo_token}"})
        assert r.status_code == 200
        scooters = r.json()
        assert len(scooters) >= 24, f"expected >=24 scooters, got {len(scooters)}"
        codes = {s["code"] for s in scooters}
        assert "SW-1000" in codes
        assert "SW-2000" in codes

    def test_get_by_code(self):
        r = requests.get(f"{API}/scooters/SW-1000")
        assert r.status_code == 200
        d = r.json()
        assert d["code"] == "SW-1000"
        assert 0 <= d["battery"] <= 100
        assert d["price_per_min_cents"] == 35
        assert d["unlock_fee_cents"] == 100

    def test_get_not_found(self):
        r = requests.get(f"{API}/scooters/SW-9999")
        assert r.status_code == 404

    def test_radius_filter(self):
        r = requests.get(f"{API}/scooters", params={"lat": 32.4171, "lng": -81.7784, "radius_m": 2000})
        assert r.status_code == 200
        # all returned should be Georgia Southern side (SW-10xx)
        for s in r.json():
            assert s["code"].startswith("SW-1")


# ============ RIDE LIFECYCLE ============
class TestRideLifecycle:
    """Uses a fresh user so we don't collide with demo state."""

    @pytest.fixture(scope="class")
    def user(self):
        email = f"TEST_ride_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/signup", json={"email": email, "password": "swoop1234"})
        assert r.status_code == 200
        return r.json()

    @pytest.fixture(scope="class")
    def scooter_code(self):
        # find an available scooter (avoid ones held by other test runs)
        r = requests.get(f"{API}/scooters")
        for s in r.json():
            if s["status"] == "available":
                return s["code"]
        pytest.skip("no available scooter")

    def test_full_flow(self, user, scooter_code):
        h = {"Authorization": f"Bearer {user['session_token']}"}

        # Reserve
        r = requests.post(f"{API}/rides/reserve", json={"scooter_code": scooter_code}, headers=h)
        assert r.status_code == 200, r.text
        ride = r.json()
        ride_id = ride["ride_id"]
        assert ride["status"] == "reserved"

        # Prevent concurrent
        r2 = requests.post(f"{API}/rides/reserve", json={"scooter_code": scooter_code}, headers=h)
        assert r2.status_code == 409

        # Start
        r = requests.post(f"{API}/rides/start", json={"ride_id": ride_id}, headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "active"

        # cannot start again
        r = requests.post(f"{API}/rides/start", json={"ride_id": ride_id}, headers=h)
        assert r.status_code == 409

        # active endpoint returns the ride
        r = requests.get(f"{API}/rides/active", headers=h)
        assert r.status_code == 200
        assert r.json()["ride_id"] == ride_id

        # give it a moment so minutes >= 1 (server always min 1)
        time.sleep(1)

        # End
        r = requests.post(f"{API}/rides/end", json={"ride_id": ride_id, "end_lat": 32.417, "end_lng": -81.778}, headers=h)
        assert r.status_code == 200
        ended = r.json()
        assert ended["status"] == "awaiting_payment"
        assert ended["minutes"] >= 1
        expected = 100 + ended["minutes"] * 35
        assert ended["amount_cents"] == expected

        # mock checkout
        r = requests.post(f"{API}/payments/mock-checkout", json={"ride_id": ride_id}, headers=h)
        assert r.status_code == 200
        co = r.json()
        assert co["amount_cents"] == expected
        assert co["session_id"].startswith("mock_sess_")

        # mock confirm
        r = requests.post(f"{API}/payments/mock-confirm", json={"ride_id": ride_id}, headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "paid"

        # history
        r = requests.get(f"{API}/rides", headers=h)
        assert r.status_code == 200
        rides = r.json()
        assert any(x["ride_id"] == ride_id and x["status"] == "paid" for x in rides)

        # active is now none
        r = requests.get(f"{API}/rides/active", headers=h)
        assert r.status_code == 200
        assert r.json() in (None, {})

    def test_start_without_reserve(self, user):
        h = {"Authorization": f"Bearer {user['session_token']}"}
        r = requests.post(f"{API}/rides/start", json={"ride_id": "ride_doesnotexist"}, headers=h)
        assert r.status_code == 404

    def test_unauth_reserve(self):
        r = requests.post(f"{API}/rides/reserve", json={"scooter_code": "SW-1000"})
        assert r.status_code == 401
