"""ResidueIQ API — FastAPI app exposing the detection engine, gated by App Check.

Run locally:  uvicorn api.main:app --reload
Docs:         http://localhost:8000/docs
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import config, routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("api")

app = FastAPI(
    title="ResidueIQ API",
    version="1.0.0",
    description=(
        "Contaminant detection engine. Protected routes require a valid "
        "Firebase App Check token in the X-Firebase-AppCheck header."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS or ["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(routes.public_router)
app.include_router(routes.router)


@app.get("/")
def root() -> dict:
    return {"name": "ResidueIQ API", "docs": "/docs", "health": "/api/health"}
