# Swoop

Scooter rental app: Expo (React Native) phone/web app in `frontend/`, FastAPI + MongoDB server in `backend/`.

## Run it on your computer

### 1. Install once

- **Python 3.12+**: https://www.python.org/downloads/ (Windows: tick "Add python.exe to PATH")
- **Node.js 22 LTS**: https://nodejs.org, then run `npm install -g yarn`
- **MongoDB Community Server**: https://www.mongodb.com/try/download/community
  (Windows: keep "Install as a Service" ticked. Mac: `brew tap mongodb/brew && brew install mongodb-community && brew services start mongodb-community`)
- **Git**, then: `git clone https://github.com/EquinoxJake/Swoop-prototype-.git`

### 2. Start the server (terminal 1)

```bash
cd Swoop-prototype-/backend
python -m venv .venv
# Mac/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Open http://localhost:8001/api/ in a browser; it should say `"status":"ok"`.
Optional keys (Google, Claude, Discord) go in `backend/.env`; the app runs without them.

### 3. Start the app (terminal 2)

```bash
cd Swoop-prototype-/frontend
yarn install
```

Create `frontend/.env` with one line:

```
EXPO_PUBLIC_BACKEND_URL=http://YOUR-COMPUTER-IP:8001
```

Use `http://localhost:8001` if you only test in the browser. For your phone, use your computer's
Wi-Fi address (Mac: System Settings → Wi-Fi → Details; Windows: `ipconfig` → IPv4 Address).

```bash
yarn web      # opens the app in your browser
yarn start    # shows a QR code: scan it with the Expo Go app on your phone (same Wi-Fi)
```

Log in with the demo account **demo@swoop.app / swoop1234**, or create one.
Bluetooth unlock needs a development build; Expo Go and the browser use the simulated unlock.

### Run the backend tests

With the server running and `ADMIN_EMAILS=admin@swoop-test.com`,
`DISCORD_PUBLIC_KEY=03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8` and
`DISCORD_ADMIN_USER_IDS=111111` in `backend/.env`:

```bash
cd backend
pytest
```
