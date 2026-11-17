"""
data_acquisition/light.py — Light sensor reader (BH1750).

Hardware
--------
- Sensor: BH1750 Ambient Light Sensor (I2C) connected to an ESP32 microcontroller
- USB-to-UART bridge: Silicon Labs CP2102
- Windows port: COM20 | Linux port: /dev/ttyUSB0
- Baud rate: 9600 (Application sketch) / 115200 (ROM bootloader)

Protocol & Behavior
-------------------
The sensor microcontroller executes an Arduino/ESP32 sketch with a BH1750 library.
Upon power-on/reset:
  1. Bootloader initializes.
  2. Sketch prints: "BH1750 Test begin"
  3. Firmware attempts to connect to WiFi ("Connecting to WiFi..").
  4. Once connected, it streams ambient light readings in lux (either as JSON or formatted text).

This module handles:
  - Serial connection at configured baud rate (9600).
  - Decoding both JSON lines and formatted text strings (e.g. "Light: 450.00 lx", "lux: 450").
  - Clear, throttled diagnostic logging when the microcontroller is connecting to WiFi.
  - Range validation (0.0 lx to 120,000.0 lx).
  - Clean error and disconnection handling.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

import serial
import serial.serialutil

from app.config import settings
from data_acquisition.serial_config import open_serial_port

logger = logging.getLogger(__name__)

# BH1750 measurement range: 0.11 to 100,000 lx (extended up to 120,000 lx in direct sunlight)
LUX_MIN = 0.0
LUX_MAX = 120000.0

# Regex patterns for common BH1750 text formats
_LUX_PATTERNS = [
    # "Light: 123.45 lx" or "BH1750: 123.45 lux" or "Ambient Light: 123.45 lx"
    re.compile(r"(?:light|lux|bh1750|ambient)\s*(?:intensity|level)?\s*[:=]?\s*(-?[0-9]+(?:\.[0-9]+)?)\s*(?:lx|lux)?", re.IGNORECASE),
    # "123.45 lx" or "123.45 lux"
    re.compile(r"(-?[0-9]+(?:\.[0-9]+)?)\s*(?:lx|lux)", re.IGNORECASE),
    # Raw numeric value on its own line: "123.45"
    re.compile(r"^(-?[0-9]+(?:\.[0-9]+)?)$"),
]


class LightReader:
    """
    Manages the serial connection to the BH1750 light sensor.

    Usage
    -----
    reader = LightReader()
    reader.connect()
    lux = reader.read_one()   # returns float or None
    reader.close()
    """

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: Optional[int] = None,
        read_timeout: Optional[float] = None,
        diag_sample_bytes: Optional[int] = None,
    ):
        self._port = port or settings.light_port
        self._baudrate = baudrate or settings.light_baudrate
        self._timeout = read_timeout or settings.light_read_timeout
        self._diag_bytes = diag_sample_bytes or settings.light_diag_sample_bytes
        self._serial: Optional[serial.Serial] = None
        self._connected: bool = False
        self._last_wifi_log: float = 0.0
        self._wifi_connecting_count: int = 0

    def connect(self) -> bool:
        """Attempt to open the light sensor serial port."""
        try:
            self._serial = open_serial_port(
                port=self._port,
                baudrate=self._baudrate,
                read_timeout=self._timeout,
                description="light",
            )
            # Ensure DTR and RTS are de-asserted so the ESP32 is not held in reset
            self._serial.dtr = False
            self._serial.rts = False
            self._serial.reset_input_buffer()
            self._connected = True
            logger.info(
                "[light] BH1750 light sensor port %s opened @ %d baud.",
                self._port,
                self._baudrate,
            )
            return True
        except serial.SerialException as exc:
            logger.warning("[light] Cannot open %s: %s", self._port, exc)
            self._connected = False
            return False

    def close(self) -> None:
        """Close the serial port."""
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
        self._connected = False
        logger.info("[light] Serial port %s closed.", self._port)

    @property
    def is_connected(self) -> bool:
        return self._connected and self._serial is not None and self._serial.is_open

    def read_one(self) -> Optional[float]:
        """
        Read one line or frame from the light sensor and return the illuminance in lux.

        Returns:
            float value in lux if a valid reading is decoded,
            or None if no measurement is available or the device is still connecting.
        """
        if not self.is_connected:
            return None

        try:
            raw = self._serial.readline()
        except serial.SerialException as exc:
            logger.warning("[light] Serial read error on %s: %s", self._port, exc)
            self._connected = False
            return None

        if not raw:
            return None

        try:
            # Strip non-ASCII or unprintable control characters to prevent encoding errors
            raw_text = raw.decode("latin1", errors="replace").strip()
            text = re.sub(r"[^\x20-\x7E]", "", raw_text).strip()
        except Exception:
            return None

        if not text:
            return None

        # Check for ESP32 firmware status messages
        if "Connecting to WiFi" in text:
            self._wifi_connecting_count += 1
            now = time.monotonic()
            if now - self._last_wifi_log > 15.0:  # Throttled notice every 15s
                logger.warning(
                    "[light] BH1750 sensor node is waiting for WiFi connection ('%s'). "
                    "Make sure the 5G lab/router WiFi hotspot is powered on. Lux readings will stream once connected.",
                    text[:40],
                )
                self._last_wifi_log = now
            return None

        if "BH1750 Test begin" in text:
            logger.info("[light] BH1750 sensor node initialized (%s).", text)
            return None

        # Attempt to decode lux from text or JSON
        lux = _decode_frame(text)
        if lux is not None:
            logger.info("[light] Decoded lux value: %.2f lx", lux)
            return lux

        return None


# ---------------------------------------------------------------------------
# Frame / text decoder
# ---------------------------------------------------------------------------

def _decode_frame(data: str | bytes) -> Optional[float]:
    """
    Attempt to decode a raw string or byte frame into a valid lux measurement.
    Supports JSON objects and standard formatted text from Arduino BH1750 sketches.
    """
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8", errors="replace").strip()
        except Exception:
            return None
    else:
        text = data.strip()

    if not text:
        return None

    # 1. Try parsing as JSON object
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                for key in ["light_lux", "lux", "lightLux", "light", "illumination"]:
                    if key in obj and obj[key] is not None:
                        try:
                            val = float(obj[key])
                            if LUX_MIN <= val <= LUX_MAX:
                                return val
                        except (ValueError, TypeError):
                            pass
        except json.JSONDecodeError:
            pass

    # 2. Try parsing formatted text with regexes
    for pattern in _LUX_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                val = float(match.group(1))
                if LUX_MIN <= val <= LUX_MAX:
                    return val
            except (ValueError, TypeError):
                continue

    return None
