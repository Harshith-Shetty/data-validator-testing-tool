"""FastAPI application entry point."""

from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import storage
from .api.routes import router

# So a slow request shows up somewhere instead of the terminal going quiet —
# set DVT_LOG_LEVEL=DEBUG for more, or WARNING to go back to silence.
logging.basicConfig(
    level=os.environ.get("DVT_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

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


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One line per request, so a hung/slow call is visible even before it
    finishes: logged as 'started' immediately, then 'done' with the timing."""
    started = time.time()
    logger.info("--> %s %s", request.method, request.url.path)
    response = await call_next(request)
    elapsed_ms = int((time.time() - started) * 1000)
    logger.info(
        "<-- %s %s %s (%d ms)", request.method, request.url.path, response.status_code, elapsed_ms
    )
    return response


app.include_router(router)

logger.info("Data Validator Testing Tool ready. Storage: %s", storage.STORAGE_ROOT)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "data-validator-testing-tool", "docs": "/docs"}
