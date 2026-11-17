"""
app/config.py — Centralised configuration via environment variables.

All settings are read from a .env file (or the process environment).
No secrets or hardware paths are hard-coded here.
"""

import os
import sys
import logging
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


# ---------------------------------------------------------------------------
# Locate .env relative to the backend/ root (two levels up from this file)
# ---------------------------------------------------------------------------
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    """Application-wide settings loaded from .env / environment."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application -------------------------------------------------------
    app_name: str = "SolarTwin 5G"
    app_version: str = "0.1.0"

    # ---- Database ----------------------------------------------------------
    database_url: str = "sqlite:///./solartwin.db"

    # ---- Temperature sensor ------------------------------------------------
    temperature_port: str = "COM21"         # Windows: COM21 | Linux: /dev/ttyUSB1
    temperature_baudrate: int = 115200
    temperature_read_timeout: float = 2.0   # seconds per readline()
    temperature_reconnect_delay: float = 5.0

    # ---- Light sensor (BH1750 on ESP32) -----------------------------------
    light_port: str = "COM20"              # Windows: COM20 | Linux: /dev/ttyUSB0
    light_baudrate: int = 9600
    light_read_timeout: float = 2.0
    light_reconnect_delay: float = 5.0
    light_diag_sample_bytes: int = 64      # max raw bytes logged per sample

    # ---- Data acquisition --------------------------------------------------
    collection_interval: int = 5           # seconds between readings

    # ---- FastAPI server ----------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # ---- Logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_file: str = "logs/solartwin.log"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return upper

    @field_validator("temperature_baudrate", "light_baudrate")
    @classmethod
    def validate_baudrate(cls, v: int) -> int:
        allowed = {300, 600, 1200, 2400, 4800, 9600, 14400, 19200,
                   38400, 57600, 115200, 230400, 460800, 921600}
        if v not in allowed:
            raise ValueError(f"Unsupported baud rate: {v}. Allowed: {allowed}")
        return v


# Singleton — imported everywhere as `from app.config import settings`
settings = Settings()


# ---------------------------------------------------------------------------
# Logging setup (call once at startup)
# ---------------------------------------------------------------------------

def configure_logging() -> None:
    """
    Configure the root logger.
    Writes to both stdout and a rotating log file.
    Call this exactly once from app/main.py and from the collector entry-point.
    """
    # Ensure Windows console handles UTF-8 safely
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    log_path = _BACKEND_ROOT / settings.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    numeric_level = getattr(logging, settings.log_level, logging.INFO)

    fmt = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%SZ"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
    ]

    # File handler with basic rotation (10 MB × 5 backups)
    try:
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        handlers.append(fh)
    except OSError as exc:
        print(f"WARNING: Cannot open log file {log_path}: {exc}", file=sys.stderr)

    logging.basicConfig(
        level=numeric_level,
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
        force=True,
    )
    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
