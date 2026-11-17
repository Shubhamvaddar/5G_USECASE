"""
data_acquisition/serial_config.py — Serial port helpers.

Provides a factory function that creates a configured serial.Serial object
using settings from the .env file. No port names are hard-coded.
"""

import logging
import platform
import serial

logger = logging.getLogger(__name__)


def open_serial_port(
    port: str,
    baudrate: int,
    read_timeout: float,
    description: str = "sensor",
) -> serial.Serial:
    """
    Open and return a configured serial port.

    Parameters
    ----------
    port        : Platform-specific port name (e.g. 'COM8' or '/dev/ttyUSB1').
    baudrate    : Communication baud rate.
    read_timeout: Seconds to wait for each readline() call.
    description : Human-readable label used in log messages.

    Returns
    -------
    An open serial.Serial instance.

    Raises
    ------
    serial.SerialException if the port cannot be opened.
    """
    ser = serial.Serial(
        port=port,
        baudrate=baudrate,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=read_timeout,  # read timeout, not connection timeout
    )
    logger.info(
        "[%s] Serial port opened: %s @ %d baud (OS: %s)",
        description,
        port,
        baudrate,
        platform.system(),
    )
    return ser


def default_temperature_port() -> str:
    """Return the platform-appropriate default temperature port."""
    return "COM8" if platform.system() == "Windows" else "/dev/ttyUSB1"


def default_light_port() -> str:
    """Return the platform-appropriate default light port."""
    return "COM20" if platform.system() == "Windows" else "/dev/ttyUSB0"
