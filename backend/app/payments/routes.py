"""Card-on-file endpoints (MOCKED: only brand + last4 are stored)."""
from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..core.db import db
from ..core.geo import ensure_aware, now_utc
from ..core.security import get_current_user

router = APIRouter()


class PaymentMethod(BaseModel):
    payment_method_id: str
    user_id: str
    brand: str
    last4: str
    exp_month: int
    exp_year: int
    is_default: bool
    created_at: datetime


class AddPaymentMethodRequest(BaseModel):
    number: str  # full card number (we only keep last4)
    exp_month: int
    exp_year: int
    cvc: str  # never stored


def detect_brand(number: str) -> str:
    n = number.replace(" ", "")
    if n.startswith("4"): return "Visa"
    if n.startswith(("51", "52", "53", "54", "55", "22", "23", "24", "25", "26", "27")): return "Mastercard"
    if n.startswith(("34", "37")): return "Amex"
    if n.startswith("6"): return "Discover"
    return "Card"


async def get_default_payment_method(user_id: str) -> Optional[dict]:
    pm = await db.payment_methods.find_one({"user_id": user_id, "is_default": True}, {"_id": 0})
    if pm:
        return pm
    return await db.payment_methods.find_one({"user_id": user_id}, {"_id": 0}, sort=[("created_at", -1)])


@router.get("/payment-methods", response_model=List[PaymentMethod])
async def list_payment_methods(authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    docs = await db.payment_methods.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(20)
    return [PaymentMethod(**{**d, "created_at": ensure_aware(d["created_at"])}) for d in docs]


@router.post("/payment-methods", response_model=PaymentMethod)
async def add_payment_method(body: AddPaymentMethodRequest, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    number = body.number.replace(" ", "").replace("-", "")
    if len(number) < 13 or not number.isdigit():
        raise HTTPException(400, "Invalid card number")
    if body.exp_month < 1 or body.exp_month > 12:
        raise HTTPException(400, "Invalid expiration month")
    if len(body.cvc) < 3:
        raise HTTPException(400, "Invalid CVC")
    # If this is user's first card, make it default
    existing_count = await db.payment_methods.count_documents({"user_id": user["user_id"]})
    pm = {
        "payment_method_id": f"pm_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "brand": detect_brand(number),
        "last4": number[-4:],
        "exp_month": body.exp_month,
        "exp_year": body.exp_year,
        "is_default": existing_count == 0,
        "created_at": now_utc(),
    }
    await db.payment_methods.insert_one(pm)
    return PaymentMethod(**pm)


@router.delete("/payment-methods/{payment_method_id}")
async def delete_payment_method(payment_method_id: str, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    pm = await db.payment_methods.find_one({"payment_method_id": payment_method_id, "user_id": user["user_id"]}, {"_id": 0})
    if not pm:
        raise HTTPException(404, "Not found")
    await db.payment_methods.delete_one({"payment_method_id": payment_method_id})
    # If deleted default, promote the newest remaining card
    if pm.get("is_default"):
        remaining = await db.payment_methods.find_one({"user_id": user["user_id"]}, {"_id": 0}, sort=[("created_at", -1)])
        if remaining:
            await db.payment_methods.update_one({"payment_method_id": remaining["payment_method_id"]}, {"$set": {"is_default": True}})
    return {"ok": True}


@router.post("/payment-methods/{payment_method_id}/default", response_model=PaymentMethod)
async def set_default_payment_method(payment_method_id: str, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    pm = await db.payment_methods.find_one({"payment_method_id": payment_method_id, "user_id": user["user_id"]}, {"_id": 0})
    if not pm:
        raise HTTPException(404, "Not found")
    await db.payment_methods.update_many({"user_id": user["user_id"]}, {"$set": {"is_default": False}})
    await db.payment_methods.update_one({"payment_method_id": payment_method_id}, {"$set": {"is_default": True}})
    pm["is_default"] = True
    return PaymentMethod(**{**pm, "created_at": ensure_aware(pm["created_at"])})
