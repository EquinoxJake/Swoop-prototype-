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

APP_NAME = "swoop"
# Parking photos are saved here. Back this folder up; it is the only copy.
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR") or BACKEND_DIR / "uploads").resolve()
