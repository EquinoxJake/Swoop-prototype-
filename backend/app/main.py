"""Swoop API entry point. Run: uvicorn app.main:app"""
from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from . import auth, ble, parking, payments, rides, scooters, uploads
from .core.db import client, ensure_indexes_and_seed

app = FastAPI(title="Swoop API")


@app.on_event("startup")
async def on_startup():
    await ensure_indexes_and_seed()


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
