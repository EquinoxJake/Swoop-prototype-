# Swoop — PRD

## Vision
Bird/Lime-style scooter rental micromobility app launching at **Georgia Southern University** (Statesboro, GA) and expanding to **Savannah, GA**. Riders find nearby scooters on a live GPS map, scan a QR code on the handlebar, unlock via Bluetooth, ride, and are billed per real GPS mile.

## Core features (MVP)
1. **Auth** — Email/password + Emergent Google Auth
2. **Live map** — full-bleed react-native-maps with pins showing battery %
3. **Persistent swipe-up scooter list** — peek/mid/full sheet; sorted by distance; search by code
4. **Dummy scooters spawn around user's GPS location** (idempotent seed via `/api/scooters/seed-near`)
5. **QR scan** — expo-camera scans SW-XXXX codes; manual entry fallback
6. **Scooter detail** — bottom sheet with battery, range, price, unlock CTA
7. **Card-on-file required** — Reserving requires a saved card (`POST /api/rides/reserve` returns 402 if none). If missing, user is auto-routed to `/(app)/payment-method` and returned to the ride when saved.
8. **BLE handshake (MOCKED)** — Simulated search/connect/unlock with haptics
9. **$1.00 unlock fee charged upfront** when the ride is reserved (mocked Stripe → `charges` table)
10. **GPS mileage tracking** — `expo-location.watchPositionAsync` with high accuracy + 3m/1s interval; distance accumulated via haversine, ignoring <2m jitter and >300m jumps
11. **$0.20/mile billed on ride end (auto-charged)** — `POST /api/rides/end` computes `mileage_cents = ceil(miles × 20)` and charges the default card. Ride jumps straight to `completed`; no separate Pay button.
12. **Receipt** — Trip summary + itemized charges + card that was billed
13. **Ride history + Profile** with dark mode toggle and Payment methods manager

## Pricing (server-authoritative)
- Unlock: **$1.00** (charged on reserve)
- Per mile: **$0.20** (charged on end)
- Min mileage: none — if GPS reports 0m the mileage is $0

## Data model
- `users`, `user_sessions`
- `scooters` (seeded 24 baseline + auto-seeded near each user)
- `rides` — status: `reserved → active → completed | cancelled`
- `payment_methods` — mocked card (brand, last4, exp)
- `charges` — one row per mock Stripe charge (`unlock` or `mileage`)

## Theming
- Brand: `#2E7BFF` (blue) light, `#4C93FF` dark
- Light/Dark/System toggle in Profile → Appearance, persisted via `@/src/utils/storage`

## Mocked components (to be replaced later)
- **BLE** in `ride.tsx` — swap to `react-native-ble-plx` for the custom board
- **Stripe** in `server.py` (`mock_charge`) — swap to `stripe.PaymentIntent.create()` with a saved `payment_method` and `off_session=true` for auto-charges. Use Stripe SetupIntents to save cards to `payment_methods` instead of storing digits in DB.

## Backend endpoints
```
POST   /api/auth/signup           { email, password, name? }
POST   /api/auth/login            { email, password }
POST   /api/auth/session          { session_id }               # Emergent Google
GET    /api/auth/me
POST   /api/auth/logout

GET    /api/scooters
GET    /api/scooters/{code}
POST   /api/scooters/seed-near    { lat, lng, radius_m, count }

GET    /api/payment-methods
POST   /api/payment-methods       { number, exp_month, exp_year, cvc }
DELETE /api/payment-methods/{id}
POST   /api/payment-methods/{id}/default

POST   /api/rides/reserve         { scooter_code }             # 402 if no card
POST   /api/rides/start           { ride_id }
POST   /api/rides/end             { ride_id, distance_m, end_lat?, end_lng? }
GET    /api/rides
GET    /api/rides/active
GET    /api/rides/{ride_id}
```

## Test coverage
- `/app/backend/tests/test_swoop_backend.py` — 15/15 passing (card guard, unlock charge, mileage charge, delete/default, invalid card 400, etc.)
