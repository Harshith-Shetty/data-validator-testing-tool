"""FastAPI application entry point."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router

app = FastAPI(
    title="Data Validator Testing Tool",
    description="Validation APIs behind the data capture validation dashboard.",
    version="0.1.0",
)

origins = os.environ.get("DVT_CORS_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "data-validator-testing-tool", "docs": "/docs"}
