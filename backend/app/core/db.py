"""Mongo client, indexes and demo seed data."""
import random
import uuid

from motor.motor_asyncio import AsyncIOMotorClient

from .config import DB_NAME, MONGO_URL, PER_MILE_CENTS, UNLOCK_CENTS, logger
from .geo import now_utc

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


async def ensure_indexes_and_seed():
    from .security import hash_password  # security imports db; import here to avoid a cycle

    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.scooters.create_index("scooter_id", unique=True)
    await db.scooters.create_index("code", unique=True)
    await db.rides.create_index("ride_id", unique=True)
    await db.rides.create_index([("user_id", 1), ("created_at", -1)])
    await db.payment_methods.create_index("payment_method_id", unique=True)
    await db.payment_methods.create_index([("user_id", 1), ("is_default", 1)])
    await db.charges.create_index("charge_id", unique=True)
    await db.charges.create_index([("user_id", 1), ("created_at", -1)])
    # BLE security
    await db.scooter_secrets.create_index("scooter_id", unique=True)
    await db.ble_tokens.create_index("token_id", unique=True)
    await db.ble_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.used_ble_nonces.create_index("nonce", unique=True)
    await db.used_ble_nonces.create_index("expires_at", expireAfterSeconds=0)

    # Migrate legacy ride statuses ('awaiting_payment' -> 'completed', 'paid' -> 'completed')
    await db.rides.update_many({"status": {"$in": ["awaiting_payment", "paid"]}}, {"$set": {"status": "completed"}})
    # Migrate legacy scooter field
    await db.scooters.update_many({"price_per_min_cents": {"$exists": True}}, {"$unset": {"price_per_min_cents": ""}})

    # Parking zones — designated bike racks + no-park zones around Georgia Southern
    await db.parking_zones.create_index("zone_id", unique=True)
    if await db.parking_zones.count_documents({}) == 0:
        seeds = [
            # Bike racks (allowed parking) — approximate GSU landmarks
            {"name": "Henderson Library bike rack", "kind": "bike_rack", "lat": 32.4176, "lng": -81.7811, "radius_m": 25},
            {"name": "Russell Union bike rack", "kind": "bike_rack", "lat": 32.4189, "lng": -81.7808, "radius_m": 25},
            {"name": "RAC bike rack", "kind": "bike_rack", "lat": 32.4144, "lng": -81.7735, "radius_m": 30},
            {"name": "Engineering Bldg bike rack", "kind": "bike_rack", "lat": 32.4165, "lng": -81.7825, "radius_m": 20},
            {"name": "Sweetheart Circle designated", "kind": "designated", "lat": 32.4197, "lng": -81.7815, "radius_m": 40},
            # No-park zones — high-traffic plazas & pathways
            {"name": "Pedestrium (main plaza)", "kind": "no_park", "lat": 32.4182, "lng": -81.7802, "radius_m": 45},
            {"name": "Rotunda no-park", "kind": "no_park", "lat": 32.4172, "lng": -81.7794, "radius_m": 25},
            {"name": "Paulson Stadium gates", "kind": "no_park", "lat": 32.4123, "lng": -81.7802, "radius_m": 40},
        ]
        docs = []
        for s in seeds:
            docs.append({
                "zone_id": f"zone_{uuid.uuid4().hex[:10]}",
                **s,
                "created_at": now_utc(),
            })
        await db.parking_zones.insert_many(docs)
        logger.info("Seeded %d parking zones", len(docs))

    # Seed scooters around Georgia Southern University (Statesboro) and a few in Savannah
    count = await db.scooters.count_documents({})
    if count == 0:
        # Georgia Southern Statesboro campus center approx
        gs_center = (32.4171, -81.7784)
        # Savannah historic district
        sav_center = (32.0809, -81.0912)
        rng = random.Random(42)
        seeds = []
        for i in range(18):
            lat = gs_center[0] + rng.uniform(-0.008, 0.008)
            lng = gs_center[1] + rng.uniform(-0.008, 0.008)
            seeds.append({
                "scooter_id": f"scoot_{uuid.uuid4().hex[:10]}",
                "code": f"SW-{1000 + i}",
                "lat": lat,
                "lng": lng,
                "battery": rng.randint(35, 100),
                "status": "available",
                "model": "Swoop One",
                "price_per_mile_cents": PER_MILE_CENTS,
                "unlock_fee_cents": UNLOCK_CENTS,
                "created_at": now_utc(),
            })
        for i in range(6):
            lat = sav_center[0] + rng.uniform(-0.006, 0.006)
            lng = sav_center[1] + rng.uniform(-0.006, 0.006)
            seeds.append({
                "scooter_id": f"scoot_{uuid.uuid4().hex[:10]}",
                "code": f"SW-{2000 + i}",
                "lat": lat,
                "lng": lng,
                "battery": rng.randint(50, 100),
                "status": "available",
                "model": "Swoop One",
                "price_per_mile_cents": PER_MILE_CENTS,
                "unlock_fee_cents": UNLOCK_CENTS,
                "created_at": now_utc(),
            })
        await db.scooters.insert_many(seeds)
        logger.info("Seeded %d scooters", len(seeds))

    # Seed demo user
    demo = await db.users.find_one({"email": "demo@swoop.app"})
    if not demo:
        await db.users.insert_one({
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": "demo@swoop.app",
            "password_hash": hash_password("swoop1234"),
            "name": "Demo Rider",
            "picture": None,
            "created_at": now_utc(),
        })
        logger.info("Seeded demo user demo@swoop.app / swoop1234")
