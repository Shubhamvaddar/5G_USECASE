"""
data_acquisition/temperature.py — Temperature & Humidity sensor reader.

Sensor hardware
---------------
- CP2102 USB-to-UART bridge
- Windows: COM8   |   Linux: /dev/ttyUSB1
- Baud rate: 115200
- Output: UTF-8 JSON lines, one reading per line

Example JSON from the sensor
-----------------------------
{"node": "node2", "t": 25.8, "h": 70.1, "rise_c_min": 1.33, "uptime_s": 51}

Design
------
- TemperatureReader owns the serial connection exclusively.
- read_one() does a single readline(), decodes and validates JSON.
- Returns a TemperatureReading dataclass or None on any error.
- Never raises; all exceptions are caught, logged, and surfaced via the
  return value so the caller can decide whether to reconnect or skip.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import serial
import serial.serialutil

from app.config import settings
from data_acquisition.serial_config import open_serial_port

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation constants (matches sensor datasheet limits)
# ---------------------------------------------------------------------------
TEMP_MIN = -40.0   # °C
TEMP_MAX = 85.0    # °C
HUM_MIN = 0.0      # %
HUM_MAX = 100.0    # %
RISE_MIN = -100.0  # °C/min
RISE_MAX = 100.0   # °C/min


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class TemperatureReading:
    """One validated temperature/humidity reading."""
    node: str
    temperature_c: float
    humidity_percent: float
    rise_c_min: Optional[float]
    uptime_s: Optional[int]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "node": self.node,
            "temperature_c": self.temperature_c,
            "humidity_percent": self.humidity_percent,
            "rise_c_min": self.rise_c_min,
            "uptime_s": self.uptime_s,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Reader class
# ---------------------------------------------------------------------------

class TemperatureReader:
    """
    Manages the serial connection to the temperature/humidity sensor.

    Usage
    -----
    reader = TemperatureReader()
    reader.connect()
    reading = reader.read_one()   # returns TemperatureReading or None
    reader.close()

    The caller is responsible for reconnect logic (see collector.py).
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: Optional[int] = None,
        read_timeout: Optional[float] = None,
    ):
        self._port = port or settings.temperature_port
        self._baudrate = baudrate or settings.temperature_baudrate
        self._timeout = read_timeout or settings.temperature_read_timeout
        self._serial: Optional[serial.Serial] = None
        self._connected: bool = False

    # ---- Connection management -------------------------------------------

    def connect(self) -> bool:
        """
        Attempt to open the serial port.

        Returns True on success, False on failure (non-fatal).
        """
        try:
            self._serial = open_serial_port(
                port=self._port,
                baudrate=self._baudrate,
                read_timeout=self._timeout,
                description="temperature",
            )
            # Flush any stale buffered data from before we opened the port
            self._serial.reset_input_buffer()
            self._connected = True
            return True
        except serial.SerialException as exc:
            logger.warning("[temperature] Cannot open %s: %s", self._port, exc)
            self._connected = False
            return False

    def close(self) -> None:
        """Close the serial port if open."""
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
        self._connected = False
        logger.info("[temperature] Serial port %s closed.", self._port)

    @property
    def is_connected(self) -> bool:
        return self._connected and self._serial is not None and self._serial.is_open

    # ---- Reading -----------------------------------------------------------

    def read_one(self) -> Optional[TemperatureReading]:
        """
        Read one line from the sensor and return a validated TemperatureReading.

        Returns None if:
        - The port is not open.
        - The read timed out (no data within timeout window).
        - The line is not valid JSON.
        - Required fields are missing.
        - Values are out of range.
        - A serial error occurred (sets connected=False).
        """
        if not self.is_connected:
            return None

        # --- Raw read -------------------------------------------------------
        try:
            raw = self._serial.readline()
        except serial.SerialException as exc:
            logger.warning("[temperature] Serial read error on %s: %s", self._port, exc)
            self._connected = False
            return None

        if not raw:
            # Timeout — no data within the read window; not an error
            logger.debug("[temperature] Read timeout — no data received.")
            return None

        # --- Decode ---------------------------------------------------------
        try:
            line = raw.decode("utf-8", errors="replace").strip()
        except Exception as exc:
            logger.warning("[temperature] Cannot decode bytes: %s", exc)
            return None

        if not line:
            return None

        # --- Parse JSON -----------------------------------------------------
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning(
                "[temperature] Invalid JSON (skipped): %s — raw: %r", exc, line[:120]
            )
            return None

        if not isinstance(data, dict):
            logger.warning("[temperature] JSON is not an object: %r", line[:120])
            return None

        # --- Extract required fields ----------------------------------------
        node = data.get("node")
        raw_t = data.get("t")
        raw_h = data.get("h")

        if node is None or raw_t is None or raw_h is None:
            logger.warning(
                "[temperature] Missing required fields (node/t/h) in: %r", data
            )
            return None

        # --- Type coercion --------------------------------------------------
        try:
            temperature_c = float(raw_t)
            humidity_percent = float(raw_h)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "[temperature] Non-numeric t/h values in %r: %s", data, exc
            )
            return None

        # --- Range validation -----------------------------------------------
        if not (TEMP_MIN <= temperature_c <= TEMP_MAX):
            logger.warning(
                "[temperature] Temperature %.2f°C out of range [%s, %s] — discarded.",
                temperature_c, TEMP_MIN, TEMP_MAX,
            )
            return None

        if not (HUM_MIN <= humidity_percent <= HUM_MAX):
            logger.warning(
                "[temperature] Humidity %.1f%% out of range [%s, %s] — discarded.",
                humidity_percent, HUM_MIN, HUM_MAX,
            )
            return None

        # --- Optional fields ------------------------------------------------
        rise_c_min: Optional[float] = None
        raw_rise = data.get("rise_c_min")
        if raw_rise is not None:
            try:
                rise_c_min = float(raw_rise)
                if not (RISE_MIN <= rise_c_min <= RISE_MAX):
                    logger.debug(
                        "[temperature] rise_c_min %.2f out of range — set to None.",
                        rise_c_min,
                    )
                    rise_c_min = None
            except (TypeError, ValueError):
                pass

        uptime_s: Optional[int] = None
        raw_uptime = data.get("uptime_s")
        if raw_uptime is not None:
            try:
                uptime_s = int(raw_uptime)
                if uptime_s < 0:
                    uptime_s = None
            except (TypeError, ValueError):
                pass

        reading = TemperatureReading(
            node=str(node),
            temperature_c=temperature_c,
            humidity_percent=humidity_percent,
            rise_c_min=rise_c_min,
            uptime_s=uptime_s,
        )
        logger.info(
            "[temperature] node=%s  t=%.2f°C  h=%.1f%%  rise=%.2f°C/min  uptime=%ds",
            reading.node,
            reading.temperature_c,
            reading.humidity_percent,
            reading.rise_c_min or 0.0,
            reading.uptime_s or 0,
        )
        return reading


# ---------------------------------------------------------------------------
# Convenience: single-shot read with auto-connect (used in tests)
# ---------------------------------------------------------------------------

def read_temperature_once(
    port: Optional[str] = None,
    baudrate: Optional[int] = None,
) -> Optional[TemperatureReading]:
    """
    Open, read one value, close. Useful for ad-hoc debugging.
    Not intended for the main acquisition loop.
    """
    reader = TemperatureReader(port=port, baudrate=baudrate)
    if not reader.connect():
        return None
    time.sleep(0.1)  # let the sensor send its next line
    reading = reader.read_one()
    reader.close()
    return reading
