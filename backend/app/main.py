"""Swoop API entry point. Run: uvicorn app.main:app"""
from fastapi import APIRouter, FastAPI
from fastapi.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

from . import auth, ble, parking, payments, rides, scooters, uploads
from .core.config import logger
from .core.db import client, ensure_indexes_and_seed

app = FastAPI(title="Swoop API")


@app.on_event("startup")
async def on_startup():
    await ensure_indexes_and_seed()
    # Warm storage key (non-blocking best-effort)
    try:
        await run_in_threadpool(uploads.init_storage_sync)
    except Exception as e:
        logger.warning("Storage warm failed: %s", e)


@app.on_event("shutdown")
async def on_shutdown():
    client.close()


api = APIRouter(prefix="/api")
for module in (auth, scooters, payments, rides, parking, uploads, ble):
    api.include_router(module.router)
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
