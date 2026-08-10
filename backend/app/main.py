"""FastAPI application entry point.

In development the Angular dev server proxies `/api` here. In a container the
built Angular bundle is served by this same app, so the whole tool lives behind
one port and one URL.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .api.routes import router

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATIC_DIR = REPO_ROOT / "frontend" / "dist" / "frontend" / "browser"

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

static_dir = Path(os.environ.get("DVT_STATIC_DIR", DEFAULT_STATIC_DIR))


if static_dir.is_dir():
    index_file = static_dir / "index.html"
    static_root = static_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_dashboard(full_path: str) -> FileResponse:
        """Serve the built dashboard, falling back to index.html for client routes.

        Registered after the API router, so `/api/*`, `/docs` and `/openapi.json`
        still win.
        """
        if full_path:
            candidate = (static_dir / full_path).resolve()
            # Never serve anything outside the build output.
            if candidate.is_file() and candidate.is_relative_to(static_root):
                return FileResponse(candidate)
        return FileResponse(index_file)

else:

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "service": "data-validator-testing-tool",
            "docs": "/docs",
            "dashboard": "not built — run 'npm run build' in frontend/, or use the dev server",
        }
