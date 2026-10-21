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
    # Seed a scooter at a random spot so parallel test workers never reserve the same one
    lat, lng = 40 + uuid.uuid4().int % 1000 / 100, -100 - uuid.uuid4().int % 1000 / 100
    r = api_client.post(f"{API}/scooters/seed-near", json={"lat": lat, "lng": lng, "radius_m": 50, "count": 1})
    assert r.status_code == 200, r.text
    return r.json()[0]


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

    def test_09_end_ride_auto_charges_mileage(self, api_client, auth_headers, fresh_user):
        assert TestSwoopFullFlow.ride_id
        dummy_photo = f"swoop/uploads/{fresh_user['user']['user_id']}/dummy.jpg"
        r = api_client.post(
            f"{API}/rides/end",
            headers=auth_headers,
            json={"ride_id": TestSwoopFullFlow.ride_id, "distance_m": 1610, "end_lat": 32.42, "end_lng": -81.78,
                  "end_photo_path": dummy_photo},
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

    # ---- NEW: route playback + paused_seconds ----
    def _do_full_ride(self, api_client, auth_headers, fresh_user, end_body_extra: dict):
        """Reserve → start → end with extra body fields. Returns final ride dict."""
        scooter = _pick_available_scooter(api_client)
        rv = api_client.post(f"{API}/rides/reserve", headers=auth_headers, json={"scooter_code": scooter["code"]})
        assert rv.status_code == 200, rv.text
        rid = rv.json()["ride_id"]
        st = api_client.post(f"{API}/rides/start", headers=auth_headers, json={"ride_id": rid})
        assert st.status_code == 200, st.text
        dummy_photo = f"swoop/uploads/{fresh_user['user']['user_id']}/dummy.jpg"
        body = {"ride_id": rid, "distance_m": 500, "end_lat": 32.4201, "end_lng": -81.7801,
                "end_photo_path": dummy_photo}
        body.update(end_body_extra)
        en = api_client.post(f"{API}/rides/end", headers=auth_headers, json=body)
        assert en.status_code == 200, en.text
        return en.json()

    def test_14_end_ride_stores_route_and_paused_seconds(self, api_client, auth_headers, fresh_user):
        # Small route (5 points), positive paused_seconds
        route = [
            [32.4171000001, -81.7784000001],
            [32.4172, -81.7785],
            [32.4173, -81.7786],
            [32.4174, -81.7787],
            [32.4175, -81.7788],
        ]
        ride = self._do_full_ride(api_client, auth_headers, fresh_user, {"route": route, "paused_seconds": 42})
        assert ride["status"] == "completed"
        assert "route" in ride and isinstance(ride["route"], list)
        assert len(ride["route"]) == 5
        # Coords rounded to 6 decimals
        for orig, echoed in zip(route, ride["route"]):
            assert echoed == [round(orig[0], 6), round(orig[1], 6)]
        assert ride["paused_seconds"] == 42
        # Verify via GET (persistence)
        got = api_client.get(f"{API}/rides/{ride['ride_id']}", headers=auth_headers).json()
        assert got["route"] == ride["route"]
        assert got["paused_seconds"] == 42

    def test_15_end_ride_thins_large_route_to_at_most_200_points(self, api_client, auth_headers, fresh_user):
        # 300 points along a small path
        route = [[32.4171 + i * 0.00001, -81.7784 + i * 0.00001] for i in range(300)]
        ride = self._do_full_ride(api_client, auth_headers, fresh_user, {"route": route, "paused_seconds": 0})
        assert ride["status"] == "completed"
        assert 1 <= len(ride["route"]) <= 200, f"route not thinned: {len(ride['route'])}"
        # All points must be 6-decimal rounded lists of len 2
        for p in ride["route"]:
            assert isinstance(p, list) and len(p) == 2
            assert p == [round(p[0], 6), round(p[1], 6)]
        assert ride["paused_seconds"] == 0

    def test_16_end_ride_filters_malformed_route_elements(self, api_client, auth_headers, fresh_user):
        # Mix of valid pairs, empty inner lists, and single-element lists — invalid must be dropped
        route = [
            [32.4171, -81.7784],
            [],                        # dropped (len<2)
            [32.4172, -81.7785],
            [32.4173],                 # dropped (len<2)
            [32.4174, -81.7786, 99.0], # kept (len>=2, extra ignored)
        ]
        ride = self._do_full_ride(api_client, auth_headers, fresh_user, {"route": route})
        # Only elements with len>=2 kept; each kept element must be [lat, lng] (2 floats, 6dp)
        assert len(ride["route"]) == 3
        assert ride["route"][0] == [32.4171, -81.7784]
        assert ride["route"][1] == [32.4172, -81.7785]
        assert ride["route"][2][:2] == [32.4174, -81.7786]
        # Each stored entry must be exactly 2 floats
        for p in ride["route"]:
            assert len(p) == 2

    def test_17_end_ride_clamps_negative_paused_seconds_to_zero(self, api_client, auth_headers, fresh_user):
        ride = self._do_full_ride(api_client, auth_headers, fresh_user, {"paused_seconds": -50})
        assert ride["paused_seconds"] == 0
        # Verify via GET
        got = api_client.get(f"{API}/rides/{ride['ride_id']}", headers=auth_headers).json()
        assert got["paused_seconds"] == 0

    def test_18_end_ride_without_route_or_paused_defaults(self, api_client, auth_headers, fresh_user):
        # Backwards compatibility: no route/paused_seconds sent → defaults preserved
        ride = self._do_full_ride(api_client, auth_headers, fresh_user, {})
        assert ride["route"] == []
        assert ride["paused_seconds"] == 0

    # ---- NEW: parking + flag improper parking (must run before delete-last-card) ----
    def test_19_end_ride_missing_photo_returns_422(self, api_client, auth_headers):
        scooter = _pick_available_scooter(api_client)
        rv = api_client.post(f"{API}/rides/reserve", headers=auth_headers, json={"scooter_code": scooter["code"]})
        assert rv.status_code == 200, rv.text
        rid = rv.json()["ride_id"]
        st = api_client.post(f"{API}/rides/start", headers=auth_headers, json={"ride_id": rid})
        assert st.status_code == 200
        r = api_client.post(f"{API}/rides/end", headers=auth_headers,
                            json={"ride_id": rid, "distance_m": 100, "end_lat": 32.4176, "end_lng": -81.7811})
        assert r.status_code == 422, r.text
        assert "parking photo is required" in r.json()["detail"].lower()
        # cleanup: end properly at a bike rack
        dummy = f"swoop/uploads/{TestSwoopFullFlow.__name__}/dummy.jpg"
        r2 = api_client.post(f"{API}/rides/end", headers=auth_headers,
                             json={"ride_id": rid, "distance_m": 100, "end_lat": 32.4176, "end_lng": -81.7811,
                                   "end_photo_path": dummy})
        assert r2.status_code == 200, r2.text

    def test_20_end_ride_in_no_park_returns_409(self, api_client, auth_headers, fresh_user):
        scooter = _pick_available_scooter(api_client)
        rv = api_client.post(f"{API}/rides/reserve", headers=auth_headers, json={"scooter_code": scooter["code"]})
        assert rv.status_code == 200
        rid = rv.json()["ride_id"]
        api_client.post(f"{API}/rides/start", headers=auth_headers, json={"ride_id": rid})
        photo = f"swoop/uploads/{fresh_user['user']['user_id']}/dummy.jpg"
        # Rotunda no-park center
        r = api_client.post(f"{API}/rides/end", headers=auth_headers,
                            json={"ride_id": rid, "distance_m": 100, "end_lat": 32.4172, "end_lng": -81.7794,
                                  "end_photo_path": photo, "parking_override": False})
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail.get("code") == "bad_parking"
        assert detail.get("zone", {}).get("kind") == "no_park"
        # Ride should still be active
        act = api_client.get(f"{API}/rides/active", headers=auth_headers).json()
        assert act is not None and act["ride_id"] == rid and act["status"] == "active"

        # Now override to complete
        r2 = api_client.post(f"{API}/rides/end", headers=auth_headers,
                             json={"ride_id": rid, "distance_m": 100, "end_lat": 32.4172, "end_lng": -81.7794,
                                   "end_photo_path": photo, "parking_override": True})
        assert r2.status_code == 200, r2.text
        ride = r2.json()
        assert ride["status"] == "completed"
        assert ride["parking_ok"] is False
        assert ride["parking_zone_id"]
        TestSwoopFullFlow.no_park_ride_id = ride["ride_id"]

    def test_21_end_ride_at_bike_rack_ok(self, api_client, auth_headers, fresh_user):
        scooter = _pick_available_scooter(api_client)
        rv = api_client.post(f"{API}/rides/reserve", headers=auth_headers, json={"scooter_code": scooter["code"]})
        assert rv.status_code == 200
        rid = rv.json()["ride_id"]
        api_client.post(f"{API}/rides/start", headers=auth_headers, json={"ride_id": rid})
        photo = f"swoop/uploads/{fresh_user['user']['user_id']}/dummy.jpg"
        # Henderson Library bike rack center
        r = api_client.post(f"{API}/rides/end", headers=auth_headers,
                            json={"ride_id": rid, "distance_m": 100, "end_lat": 32.4176, "end_lng": -81.7811,
                                  "end_photo_path": photo})
        assert r.status_code == 200, r.text
        ride = r.json()
        assert ride["parking_ok"] is True
        assert ride["parking_zone_id"]
        # zone_id must point to a bike_rack zone
        zones = api_client.get(f"{API}/parking-zones").json()
        zid_to_kind = {z["zone_id"]: z["kind"] for z in zones}
        assert zid_to_kind.get(ride["parking_zone_id"]) == "bike_rack"

    def test_22_flag_improper_parking_charges_15_and_idempotent(self, api_client, auth_headers):
        rid = TestSwoopFullFlow.ride_id  # completed in test_09
        assert rid
        # get ride's current amount
        before = api_client.get(f"{API}/rides/{rid}", headers=auth_headers).json()
        base_amount = before["amount_cents"]
        base_fee = before.get("fee_charged_cents", 0)

        # Riders can't charge the fee; only admins (ADMIN_EMAILS must include admin@swoop-test.com)
        r = api_client.post(f"{API}/rides/{rid}/flag-improper-parking", headers=auth_headers,
                            json={"reason": "Parked in walkway blocking pedestrians"})
        assert r.status_code == 403, r.text
        creds = {"email": "admin@swoop-test.com", "password": "adminpass1"}
        r = api_client.post(f"{API}/auth/signup", json=creds)
        if r.status_code == 409:
            r = api_client.post(f"{API}/auth/login", json=creds)
        admin_headers = {"Authorization": f"Bearer {r.json()['session_token']}", "Content-Type": "application/json"}

        r = api_client.post(f"{API}/rides/{rid}/flag-improper-parking", headers=admin_headers,
                            json={"reason": "Parked in walkway blocking pedestrians"})
        assert r.status_code == 200, r.text
        ride = r.json()
        assert ride["parking_flagged"] is True
        assert ride["parking_flag_reason"] == "Parked in walkway blocking pedestrians"
        assert ride["fee_charged_cents"] == base_fee + 1500
        assert ride["amount_cents"] == base_amount + 1500

        # Idempotent: second call must NOT double-charge
        r2 = api_client.post(f"{API}/rides/{rid}/flag-improper-parking", headers=admin_headers,
                             json={"reason": "second call"})
        assert r2.status_code == 200, r2.text
        ride2 = r2.json()
        assert ride2["fee_charged_cents"] == ride["fee_charged_cents"]
        assert ride2["amount_cents"] == ride["amount_cents"]

    # ---- delete-last-card guard (kept last since it removes all cards) ----
    def test_99_delete_last_card_then_reserve_402_again(self, api_client, auth_headers):
        cards = api_client.get(f"{API}/payment-methods", headers=auth_headers).json()
        for c in cards:
            r = api_client.delete(f"{API}/payment-methods/{c['payment_method_id']}", headers=auth_headers)
            assert r.status_code == 200
        cards = api_client.get(f"{API}/payment-methods", headers=auth_headers).json()
        assert cards == []
        scooter = _pick_available_scooter(api_client)
        r = api_client.post(f"{API}/rides/reserve", headers=auth_headers, json={"scooter_code": scooter["code"]})
        assert r.status_code == 402


# ============ NEW: PARKING ZONES + PHOTO UPLOAD TESTS ============
@pytest.fixture(scope="module")
def parking_user(api_client):
    ts = int(time.time() * 1000)
    email = f"parktest+{ts}_{uuid.uuid4().hex[:8]}@example.com"
    r = api_client.post(f"{API}/auth/signup", json={"email": email, "password": "testpass1", "name": "Park Test"})
    assert r.status_code == 200, r.text
    d = r.json()
    return {"email": email, "token": d["session_token"], "user": d["user"]}


@pytest.fixture(scope="module")
def parking_headers(parking_user):
    return {"Authorization": f"Bearer {parking_user['token']}", "Content-Type": "application/json"}


class TestParkingZonesAndCheck:
    """Tests for /parking-zones and /parking/check — auth only, no card needed."""

    def test_zones_list_returns_at_least_8(self, api_client):
        r = api_client.get(f"{API}/parking-zones")
        assert r.status_code == 200, r.text
        zones = r.json()
        assert isinstance(zones, list)
        assert len(zones) >= 8, f"expected >=8 zones, got {len(zones)}"
        kinds = {z["kind"] for z in zones}
        assert "bike_rack" in kinds and "no_park" in kinds
        for z in zones:
            for k in ("zone_id", "name", "kind", "lat", "lng", "radius_m"):
                assert k in z

    def test_zones_filter_by_lat_lng_radius(self, api_client):
        # Tight radius around Henderson bike rack should return few zones
        r = api_client.get(f"{API}/parking-zones", params={"lat": 32.4176, "lng": -81.7811, "radius_m": 50})
        assert r.status_code == 200
        filt = r.json()
        # Full list larger
        full = api_client.get(f"{API}/parking-zones").json()
        assert len(filt) < len(full)
        assert len(filt) >= 1
        # Every returned zone must have Henderson name OR be within 50m
        names = [z["name"] for z in filt]
        assert any("Henderson" in n for n in names)

    def test_check_inside_no_park_rotunda(self, api_client, parking_headers):
        r = api_client.post(f"{API}/parking/check", headers=parking_headers,
                            json={"lat": 32.4172, "lng": -81.7794})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is False
        assert d["zone"] is not None
        assert d["zone"]["kind"] == "no_park"
        assert d["reason"] and d["zone"]["name"] in d["reason"]
        assert d["nearest_allowed"] is not None
        assert d["nearest_allowed"]["kind"] in ("bike_rack", "designated")

    def test_check_inside_henderson_bike_rack(self, api_client, parking_headers):
        r = api_client.post(f"{API}/parking/check", headers=parking_headers,
                            json={"lat": 32.4176, "lng": -81.7811})
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert d["zone"] is not None
        assert d["zone"]["kind"] == "bike_rack"

    def test_check_out_in_field_soft_ok(self, api_client, parking_headers):
        r = api_client.post(f"{API}/parking/check", headers=parking_headers,
                            json={"lat": 32.5, "lng": -82.0})
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert d["reason"]
        assert d["nearest_allowed"] is not None
        assert d["nearest_allowed"]["kind"] in ("bike_rack", "designated")
        assert d["nearest_allowed_distance_m"] is not None and d["nearest_allowed_distance_m"] > 0

    def test_check_requires_auth(self, api_client):
        r = api_client.post(f"{API}/parking/check", json={"lat": 32.4172, "lng": -81.7794})
        assert r.status_code == 401


class TestUploadAndFilesServe:
    """Tests for POST /uploads/parking-photo and GET /files/{path} auth/authorization."""

    def _new_active_ride(self, api_client, headers):
        # Add card first
        cr = api_client.post(f"{API}/payment-methods", headers=headers,
                             json={"number": "4242424242424242", "exp_month": 12, "exp_year": 2030, "cvc": "123"})
        assert cr.status_code == 200, cr.text
        # Reserve + start
        scooter = _pick_available_scooter(api_client)
        rv = api_client.post(f"{API}/rides/reserve", headers=headers, json={"scooter_code": scooter["code"]})
        assert rv.status_code == 200, rv.text
        rid = rv.json()["ride_id"]
        st = api_client.post(f"{API}/rides/start", headers=headers, json={"ride_id": rid})
        assert st.status_code == 200
        return rid

    def test_upload_rejects_non_image(self, api_client):
        # Fresh user for isolation
        ts = int(time.time() * 1000)
        email = f"upload1+{ts}@ex.com"
        s = requests.Session()
        r = s.post(f"{API}/auth/signup", json={"email": email, "password": "testpass1", "name": "U"})
        assert r.status_code == 200
        token = r.json()["session_token"]
        headers_json = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        rid = self._new_active_ride(s, headers_json)
        # Upload text file → 400
        files = {"file": ("junk.txt", b"hello world", "text/plain")}
        r2 = s.post(f"{API}/uploads/parking-photo", params={"ride_id": rid},
                    headers={"Authorization": f"Bearer {token}"}, files=files)
        assert r2.status_code == 400, r2.text

    def test_upload_valid_jpeg_and_serve(self, api_client):
        ts = int(time.time() * 1000)
        email = f"upload2+{ts}@ex.com"
        s = requests.Session()
        r = s.post(f"{API}/auth/signup", json={"email": email, "password": "testpass1", "name": "U"})
        assert r.status_code == 200
        token = r.json()["session_token"]
        user_id = r.json()["user"]["user_id"]
        headers_json = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        rid = self._new_active_ride(s, headers_json)

        # Minimal valid JPEG (10x10 white)
        jpeg_bytes = bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a"
            "1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffdb0043010909090c0b0c180d0d1832"
            "1c1c1c32323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232"
            "32ffc00011080001000103012200021101031101ffc4001f0000010501010101010100000000000000000102030405060708090a"
            "0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552"
            "d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a73"
            "7475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2"
            "d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f0100030101010101010101010000000000000102"
            "030405060708090a0bffc400b51100020102040403040705040400010277000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a262728292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda000c03010002110311003f00fbfc28a28a03ffd9"
        )
        files = {"file": ("park.jpg", jpeg_bytes, "image/jpeg")}
        r2 = s.post(f"{API}/uploads/parking-photo", params={"ride_id": rid},
                    headers={"Authorization": f"Bearer {token}"}, files=files)
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert "path" in body and "size" in body
        assert body["size"] == len(jpeg_bytes)
        path = body["path"]
        assert path.startswith(f"swoop/uploads/{user_id}/")

        # Ride should now have end_photo_path set
        got = s.get(f"{API}/rides/{rid}", headers=headers_json).json()
        assert got["end_photo_path"] == path

        # Serve requires auth
        no_auth = requests.get(f"{API}/files/{path}")
        assert no_auth.status_code == 401

        # Cross-user fetch → 403
        ts2 = int(time.time() * 1000) + 1
        email2 = f"other+{ts2}@ex.com"
        r3 = requests.post(f"{API}/auth/signup", json={"email": email2, "password": "testpass1", "name": "O"})
        assert r3.status_code == 200
        token2 = r3.json()["session_token"]
        cross = requests.get(f"{API}/files/{path}", headers={"Authorization": f"Bearer {token2}"})
        assert cross.status_code == 403, cross.text

        # Own fetch returns the exact bytes
        own = requests.get(f"{API}/files/{path}", headers={"Authorization": f"Bearer {token}"})
        assert own.status_code == 200, f"own fetch failed: {own.status_code} {own.text}"
        assert own.content == jpeg_bytes

        # Path traversal out of the user's folder → 403
        sneaky = f"swoop/uploads/{user_id}/..%2F..%2F..%2F..%2Fapp%2Fcore%2Fconfig.py"
        trav = requests.get(f"{API}/files/{sneaky}", headers={"Authorization": f"Bearer {token}"})
        assert trav.status_code == 403, trav.text

    def test_files_forbidden_for_other_user_path(self, api_client):
        ts = int(time.time() * 1000)
        email = f"filesA+{ts}@ex.com"
        r = requests.post(f"{API}/auth/signup", json={"email": email, "password": "testpass1", "name": "A"})
        assert r.status_code == 200
        token = r.json()["session_token"]
        # Try to fetch under a different user's namespace
        fake_path = "swoop/uploads/user_someoneelse/file.jpg"
        r2 = requests.get(f"{API}/files/{fake_path}", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 403
