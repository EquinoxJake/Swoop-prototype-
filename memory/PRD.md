# Swoop — PRD

## Vision
Bird/Lime-style scooter rental micromobility app launching at **Georgia Southern University** (Statesboro, GA) and expanding to **Savannah, GA**. Riders find nearby scooters on a live GPS map, scan a QR code on the handlebar, unlock via Bluetooth, ride, and pay per minute.

## Users
- College students at Georgia Southern
- Downtown Savannah residents and tourists (later)

## Core features (MVP)
1. **Authentication** — Email/password + Emergent Google Auth
2. **Live map** — react-native-maps with clustered pins showing battery %; user location + centering
3. **QR scan** — expo-camera scans handlebar QR (`SW-XXXX` format); manual code entry fallback
4. **Scooter detail** — Bottom sheet with battery, price, range, unlock CTA
5. **BLE handshake (MOCKED)** — Simulated search/connect/unlock animation with haptics; ready to swap in real `react-native-ble-plx` for the custom board later
6. **Active ride** — Live timer, distance, running cost, End ride
7. **Payment (Stripe MOCKED)** — Backend calculates cost server-side ($1 unlock + $0.35/min); mock checkout + confirmation; ready to swap to real Stripe Checkout
8. **Receipt** — Trip summary, itemized cost, mark ride paid
9. **Ride history** — Chronological list of past rides
10. **Profile** — User details, sign out, safety/support/service area sections

## Pricing (server-authoritative)
- Unlock: $1.00
- Per minute: $0.35
- Minimum: 1 minute

## Architecture
- **Backend**: FastAPI + MongoDB (motor async)
- **Frontend**: Expo Router (stack navigation), react-native-maps, @gorhom/bottom-sheet, expo-camera, expo-haptics, expo-blur
- **Auth**: Bearer session_token in expo-secure-store (mobile) / localStorage (web); 7-day TTL sessions
- **Data model**: users, user_sessions, scooters (seeded ~24 at Georgia Southern + Savannah), rides

## Ride state machine
`reserved → active → awaiting_payment → paid`

## Mocked components (to be replaced later)
- **BLE**: `/app/frontend/app/(app)/ride.tsx` — simulated searching/connecting/unlocking phases. Wire to `react-native-ble-plx` when the custom board is ready.
- **Stripe**: `/app/backend/server.py` `create_mock_checkout` + `confirm_mock_payment`. Replace with `stripe.checkout.Session.create()` + webhook per playbook.

## Next steps
- Real Stripe Checkout (backend already computes amount server-side)
- Real BLE via `react-native-ble-plx` (needs dev build, not Expo Go)
- Business dashboard for the custom board data (battery %, GPS, payment status per unit)
- Push notifications for low battery / found-my-scooter
- Referral / campus promo codes
