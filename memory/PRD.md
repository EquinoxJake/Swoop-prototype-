# Swoop — PRD

## Vision
Bird/Lime-style scooter rental micromobility app launching at **Georgia Southern University** (Statesboro, GA) and expanding to **Savannah, GA**. Riders find nearby scooters on a live GPS map, scan a QR code on the handlebar, unlock via Bluetooth, ride, and are billed per real GPS mile. Ends with a parking-verification photo.

## Core features
1. **Auth** — Email/password + Emergent Google Auth
2. **Live map** — full-bleed `react-native-maps` with pins showing battery %
3. **Persistent swipe-up scooter list** — sorted by distance, search by code
4. **Dummy scooters auto-seed around user's GPS** (idempotent)
5. **QR scan** — `expo-camera`, manual code entry fallback
6. **Card-on-file required** — 402 blocks reserve until a card is added
7. **BLE unlock (mocked timeline today, real path ready)** — see BLE Security section
8. **$1.00 unlock fee** charged upfront when reserving
9. **GPS mileage tracking** via `expo-location.watchPositionAsync`, jitter-filtered
10. **Auto-Pause on Idle** — no movement 60s → paused, no mileage charged, banner shown
11. **$0.20/mile** auto-charged on ride end to card on file
12. **Trip Route Playback** — GPS path saved (thinned to ≤200 pts) + drawn as polyline on receipt
13. **Parking verification** — server-side geofence check + mandatory in-app camera photo before ride can complete
14. **Improper-parking fee** — admin can flag → $15 auto-charged to card
15. **Dark mode** — Light / Dark / System toggle in Profile → Appearance
16. **Developer BLE scanner** — hidden behind long-press on Profile version footer

## Pricing (server-authoritative)
- Unlock: **$1.00** (charged on reserve)
- Per mile: **$0.20** (charged on end)
- Improper-parking fee: **$15.00** (admin-triggered)

## BLE Security Architecture ("unhackable" unlock)
- **Per-scooter 32-byte secret** stored in Mongo (`scooter_secrets`), never sent to the app.
- App requests an unlock token per ride via `POST /api/rides/{ride_id}/ble-token`.
- Token payload = HMAC-SHA256(secret, `nonce | ride_id | scooter_id | user_id | issued_ts | expires_ts`).
- Wire format: `[ride_id_len(1) + ride_id | nonce(16) | issued_ts(8) | expires_ts(8) | signature(32)]` — fits a single BLE MTU write.
- 60-second TTL, rate-limited to 4 tokens/min per ride.
- Scooter firmware verifies signature, time window (±30s), and that nonce isn't in its used-nonce cache.
- `POST /api/rides/{ride_id}/ble-ack` burns the nonce server-side on success → replay-proof even if the scooter is offline for a day.

## Backend endpoints (summary)
```
POST /api/auth/signup | /login | /session | /logout
GET  /api/auth/me

GET  /api/scooters
GET  /api/scooters/{code}
POST /api/scooters/seed-near

GET  /api/payment-methods
POST /api/payment-methods
DELETE /api/payment-methods/{id}
POST /api/payment-methods/{id}/default

POST /api/rides/reserve                  # 402 if no card, charges $1 unlock
POST /api/rides/start
POST /api/rides/end                      # requires end_photo_path + parking check
GET  /api/rides | /active | /{id}
POST /api/rides/{id}/flag-improper-parking

POST /api/rides/{id}/ble-token           # NEW — mints HMAC unlock token
POST /api/rides/{id}/ble-ack             # NEW — burns nonce, anti-replay

GET  /api/parking-zones
POST /api/parking/check

POST /api/uploads/parking-photo          # multipart → Emergent Object Storage
GET  /api/files/{path}                   # auth-gated serve
```

## Data model additions
- `scooter_secrets` — per-scooter HMAC key (server-only)
- `ble_tokens` — issued tokens (TTL-indexed)
- `used_ble_nonces` — burned nonces (24h TTL)
- `payment_methods` — mocked cards (brand + last4)
- `charges` — mock Stripe log (unlock / mileage / improper_parking_fee)
- `parking_zones` — bike_rack / designated / no_park
- `rides` — status: `reserved → active → completed | cancelled`; carries route, paused_seconds, end_photo_path, parking_ok, parking_flagged, fee_charged_cents

## Mocked components (swap for prod)
- **BLE handshake** in `ride.tsx` — currently simulated timeline. Real integration path built in `src/lib/ble.ts` (uses `react-native-ble-plx`, requires dev build). Swap the mock timeline for: `mintBleToken → connect → writeHex(payload) → subscribe(status) → bleAck`.
- **Stripe** — `mock_charge` writes to `db.charges`. Replace with real `stripe.PaymentIntent.create()` + SetupIntent for card save + Off-Session for automatic mileage billing.

## Test coverage
- `/app/backend/tests/test_swoop_backend.py` — 33/33 passing across: auth, cards, ride lifecycle, mileage math, route thinning, pause clamping, parking zones, parking-check, photo upload, files auth, improper-parking fee idempotency.

## Dev tools
- Hidden **Developer BLE Scanner** (`/(app)/dev-ble`): long-press "Swoop v1.0" on the Profile screen. Scan / connect / list services / write hex / subscribe notify. Requires a native dev build — not available in Expo Go.
