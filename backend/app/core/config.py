"""Environment + pricing. Every other module reads settings from here."""
from pathlib import Path
import logging
import os

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("swoop")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ.get("JWT_SECRET", "swoop-dev-secret-change-me")
JWT_ALG = "HS256"

# Pricing (cents)
UNLOCK_CENTS = 100
PER_MILE_CENTS = 20
METERS_PER_MILE = 1609.344
IMPROPER_PARKING_FEE_CENTS = 1500  # $15.00


def _csv(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


# OAuth client IDs from Google Cloud Console (web, iOS, Android)
GOOGLE_CLIENT_IDS = _csv("GOOGLE_CLIENT_IDS")

# Accounts allowed to charge the improper-parking fee over HTTP
ADMIN_EMAILS = [e.lower() for e in _csv("ADMIN_EMAILS")]

# Parking-photo review: Claude checks the photo, the Discord bot DMs the admins
PARKING_AI_MODEL = os.environ.get("PARKING_AI_MODEL", "claude-opus-5-5")
PARKING_AI_ENABLED = bool(os.environ.get("ANTHROPIC_API_KEY"))
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY", "")
DISCORD_ADMIN_USER_IDS = _csv("DISCORD_ADMIN_USER_IDS")

APP_NAME = "swoop"
# Parking photos are saved here. Back this folder up; it is the only copy.
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR") or BACKEND_DIR / "uploads").resolve()
