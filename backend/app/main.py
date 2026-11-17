"""
app/main.py — FastAPI application entry point.
"""

import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings, configure_logging
from app.database import init_db
from app.routes import router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown hooks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Skip heavy startup in test mode (TESTING=1 env var)
    if os.environ.get("TESTING") == "1":
        yield
        return

    # Configure logging on first real startup
    configure_logging()

    logger.info("=" * 60)
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    logger.info("API: http://%s:%d", settings.api_host, settings.api_port)
    logger.info("Docs: http://%s:%d/docs", settings.api_host, settings.api_port)
    logger.info("Dashboard: http://%s:%d/", settings.api_host, settings.api_port)

    init_db()

    logger.info("Application startup complete.")
    yield
    logger.info("Application shutdown.")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "SolarTwin 5G — digital twin monitoring backend for solar PV panels. "
        "Acquires environmental sensor data via USB-UART, stores it in SQLite, "
        "and exposes a REST API for the dashboard and future 5G/MEC integration."
    ),
    lifespan=lifespan,
)

# CORS — allow all origins in development; restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all routes under /api prefix
app.include_router(router, prefix="/api")


# ---------------------------------------------------------------------------
# Frontend Static Files (Anubhav 5G Dashboard)
# ---------------------------------------------------------------------------

_FRONTEND_DIST = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend"
    / "Anubhav-5G-Dashboard"
    / "dist"
)

if _FRONTEND_DIST.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )
else:
    @app.get("/", include_in_schema=False)
    def root():
        return {
            "message": f"Welcome to {settings.app_name}",
            "docs": f"http://{settings.api_host}:{settings.api_port}/docs",
            "health": f"http://{settings.api_host}:{settings.api_port}/api/health",
        }
