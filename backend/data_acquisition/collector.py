"""
data_acquisition/collector.py — Main acquisition loop.

Responsibilities
----------------
1. Own and manage one TemperatureReader and one LightReader.
2. Poll both sensors on a configurable interval.
3. Assemble a structured record from whatever readings are available.
4. POST the record to the backend API.
5. Retry the POST on transient network failures (exponential back-off).
6. Reconnect sensors automatically after disconnection.
7. Update the backend's sensor-status flags via an internal API call.
8. Never open the same serial port from two threads.

Design constraints
------------------
- The collector is the SOLE owner of both serial ports. The FastAPI process
  does not touch serial ports.
- Readings are only stored when at least one valid sensor value is present.
- light_lux is forwarded only when _decode_frame() returns a real value.
- Run this module as:   python -m data_acquisition.collector
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests
import requests.exceptions

# Ensure the backend/ directory is on sys.path so app.config resolves
import os, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import settings, configure_logging
from data_acquisition.temperature import TemperatureReader
from data_acquisition.light import LightReader

configure_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_BASE = f"http://{settings.api_host}:{settings.api_port}/api"
_DATA_URL = f"{_API_BASE}/sensors/data"
_STATUS_URL = f"{_API_BASE}/sensors/status/update"

# Back-off parameters for failed API POSTs
_BACKOFF_INITIAL = 2.0    # seconds
_BACKOFF_MAX = 60.0       # seconds
_BACKOFF_FACTOR = 2.0


# ---------------------------------------------------------------------------
# Status reporter
# ---------------------------------------------------------------------------

def _report_status(temperature_connected: bool, light_connected: bool) -> None:
    """
    Notify the backend API of current sensor connection states.
    Failures here are non-fatal and silently logged.
    """
    try:
        requests.put(
            _STATUS_URL,
            params={
                "temperature": str(temperature_connected).lower(),
                "light": str(light_connected).lower(),
            },
            timeout=3,
        )
    except Exception as exc:
        logger.debug("Could not update sensor status on backend: %s", exc)


# ---------------------------------------------------------------------------
# API POST with retry / back-off
# ---------------------------------------------------------------------------

def _post_reading(payload: dict) -> bool:
    """
    POST a sensor reading to the backend.

    Retries with exponential back-off on connection errors.
    Returns True on HTTP 2xx, False after all retries exhausted.
    """
    backoff = _BACKOFF_INITIAL
    attempts = 0

    while True:
        attempts += 1
        try:
            resp = requests.post(_DATA_URL, json=payload, timeout=10)
            if 200 <= resp.status_code < 300:
                logger.debug("Reading accepted by API (attempt %d).", attempts)
                return True
            else:
                logger.error(
                    "API rejected reading (HTTP %d): %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False   # validation error — retrying won't help
        except requests.exceptions.ConnectionError:
            if attempts == 1:
                logger.warning(
                    "Backend not reachable at %s — retrying (back-off %.1fs).",
                    _DATA_URL, backoff,
                )
            time.sleep(backoff)
            backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)
        except requests.exceptions.Timeout:
            logger.warning("API POST timed out (attempt %d).", attempts)
            time.sleep(backoff)
            backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)
        except Exception as exc:
            logger.error("Unexpected POST error: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Main acquisition loop
# ---------------------------------------------------------------------------

def run_collector() -> None:
    """
    Main entry point for the data acquisition loop.

    Runs indefinitely until SIGINT / SIGTERM.
    """
    logger.info("=" * 60)
    logger.info("SolarTwin 5G — Data Acquisition Collector")
    logger.info("Temperature port : %s @ %d baud", settings.temperature_port, settings.temperature_baudrate)
    logger.info("Light port       : %s @ %d baud (protocol unknown)", settings.light_port, settings.light_baudrate)
    logger.info("API endpoint     : %s", _DATA_URL)
    logger.info("Sampling interval: %d s", settings.collection_interval)
    logger.info("=" * 60)

    temp_reader = TemperatureReader()
    light_reader = LightReader()

    # Graceful shutdown
    _shutdown = {"requested": False}

    def _handle_signal(sig, frame):
        logger.info("Shutdown signal received (%s). Stopping collector.", sig)
        _shutdown["requested"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    temp_connected = False
    light_connected = False

    # Initial connections
    temp_connected = temp_reader.connect()
    light_connected = light_reader.connect()
    _report_status(temp_connected, light_connected)

    # Track when each sensor last failed for reconnect back-off
    temp_last_fail: float = 0.0
    light_last_fail: float = 0.0

    while not _shutdown["requested"]:
        loop_start = time.monotonic()

        # --- Reconnect temperature if disconnected -----------------------
        if not temp_reader.is_connected:
            now = time.monotonic()
            if now - temp_last_fail >= settings.temperature_reconnect_delay:
                logger.info("[temperature] Attempting reconnect to %s…", settings.temperature_port)
                temp_connected = temp_reader.connect()
                if not temp_connected:
                    temp_last_fail = now
                    logger.warning(
                        "[temperature] Reconnect failed. Next attempt in %.0fs.",
                        settings.temperature_reconnect_delay,
                    )
                else:
                    logger.info("[temperature] Reconnected successfully.")
                _report_status(temp_connected, light_connected)

        # --- Reconnect light if disconnected ----------------------------
        if not light_reader.is_connected:
            now = time.monotonic()
            if now - light_last_fail >= settings.light_reconnect_delay:
                light_connected = light_reader.connect()
                if not light_connected:
                    light_last_fail = now
                _report_status(temp_connected, light_connected)

        # --- Acquire readings -------------------------------------------
        temp_reading = None
        light_lux: Optional[float] = None

        if temp_reader.is_connected:
            temp_reading = temp_reader.read_one()
            if temp_reading is None and temp_reader.is_connected:
                # Could be a timeout; try one more time
                temp_reading = temp_reader.read_one()
            if not temp_reader.is_connected:
                # Sensor disconnected during read
                temp_connected = False
                temp_last_fail = time.monotonic()
                _report_status(temp_connected, light_connected)

        if light_reader.is_connected:
            light_lux = light_reader.read_one()
            if not light_reader.is_connected:
                light_connected = False
                light_last_fail = time.monotonic()
                _report_status(temp_connected, light_connected)

        # --- Assemble record -------------------------------------------
        # Only submit when we have at least one sensor value.
        if temp_reading is not None or light_lux is not None:
            payload: dict = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "node": temp_reading.node if temp_reading else None,
                "temperature_c": temp_reading.temperature_c if temp_reading else None,
                "humidity_percent": temp_reading.humidity_percent if temp_reading else None,
                "rise_c_min": temp_reading.rise_c_min if temp_reading else None,
                "uptime_s": temp_reading.uptime_s if temp_reading else None,
                "light_lux": light_lux,  # None when protocol is unknown
                "voltage_v": None,       # INA219 not yet available
                "current_a": None,
                "power_w": None,
                "source": "real",
            }
            _post_reading(payload)
        else:
            logger.debug("No valid readings this cycle — nothing stored.")

        # --- Wait for next cycle ----------------------------------------
        elapsed = time.monotonic() - loop_start
        sleep_time = max(0.0, settings.collection_interval - elapsed)
        if sleep_time > 0:
            # Wake up early if shutdown is requested
            deadline = time.monotonic() + sleep_time
            while time.monotonic() < deadline and not _shutdown["requested"]:
                time.sleep(0.2)

    # --- Cleanup -----------------------------------------------------------
    logger.info("Stopping readers…")
    temp_reader.close()
    light_reader.close()
    _report_status(False, False)
    logger.info("Collector stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_collector()
