"""Card processor. MOCKED: writes to db.charges. Swap these functions for Stripe calls later."""
from typing import Optional
import uuid

from ..core.config import logger
from ..core.db import db
from ..core.geo import now_utc


async def mock_charge(user_id: str, ride_id: Optional[str], amount_cents: int, kind: str, payment_method_id: str) -> str:
    """MOCKED Stripe charge. In production this would call stripe.PaymentIntent.create()."""
    charge_id = f"ch_{uuid.uuid4().hex[:14]}"
    await db.charges.insert_one({
        "charge_id": charge_id,
        "user_id": user_id,
        "ride_id": ride_id,
        "amount_cents": amount_cents,
        "kind": kind,
        "payment_method_id": payment_method_id,
        "created_at": now_utc(),
    })
    logger.info("[MOCK CHARGE] user=%s amount=%d kind=%s pm=%s", user_id, amount_cents, kind, payment_method_id)
    return charge_id
