"""
tests/test_temperature_parser.py — Unit tests for the temperature sensor parser.

All tests use mocked serial devices. No physical hardware is required.
"""

import json
import sys
import os
from io import BytesIO
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import pytest

# Ensure backend/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_acquisition.temperature import TemperatureReader, TemperatureReading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reader_with_line(json_line: str) -> TemperatureReader:
    """
    Return a TemperatureReader whose serial port is mocked to return
    the given string as one readline() response.
    """
    reader = TemperatureReader(port="MOCK_PORT", baudrate=115200, read_timeout=1.0)
    mock_serial = MagicMock()
    mock_serial.is_open = True
    mock_serial.readline.return_value = (json_line + "\n").encode("utf-8")
    reader._serial = mock_serial
    reader._connected = True
    return reader


def _make_reader_with_bytes(raw: bytes) -> TemperatureReader:
    """Return a TemperatureReader mocked to return specific raw bytes."""
    reader = TemperatureReader(port="MOCK_PORT", baudrate=115200, read_timeout=1.0)
    mock_serial = MagicMock()
    mock_serial.is_open = True
    mock_serial.readline.return_value = raw
    reader._serial = mock_serial
    reader._connected = True
    return reader


# ---------------------------------------------------------------------------
# 1. Valid temperature JSON parsing
# ---------------------------------------------------------------------------

class TestValidTemperatureParsing:

    def test_full_valid_message(self):
        """Standard message with all fields."""
        line = '{"node": "node2", "t": 25.8, "h": 70.1, "rise_c_min": 1.33, "uptime_s": 51}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()

        assert result is not None
        assert isinstance(result, TemperatureReading)
        assert result.node == "node2"
        assert result.temperature_c == pytest.approx(25.8)
        assert result.humidity_percent == pytest.approx(70.1)
        assert result.rise_c_min == pytest.approx(1.33)
        assert result.uptime_s == 51

    def test_timestamp_is_utc(self):
        """Timestamps added by the gateway must be timezone-aware UTC."""
        line = '{"node": "n1", "t": 22.0, "h": 55.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is not None
        assert result.timestamp.tzinfo is not None
        assert result.timestamp.tzinfo == timezone.utc or \
               result.timestamp.utcoffset().total_seconds() == 0

    def test_minimum_valid_temperature(self):
        """Temperature exactly at lower bound is accepted."""
        line = '{"node": "n1", "t": -40.0, "h": 10.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is not None
        assert result.temperature_c == pytest.approx(-40.0)

    def test_maximum_valid_temperature(self):
        """Temperature exactly at upper bound is accepted."""
        line = '{"node": "n1", "t": 85.0, "h": 90.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is not None
        assert result.temperature_c == pytest.approx(85.0)

    def test_zero_humidity_is_valid(self):
        """Humidity of exactly 0 is a valid reading, not a missing value."""
        line = '{"node": "n1", "t": 20.0, "h": 0.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is not None
        assert result.humidity_percent == pytest.approx(0.0)

    def test_full_humidity_is_valid(self):
        """Humidity of 100 % is valid."""
        line = '{"node": "n1", "t": 20.0, "h": 100.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is not None
        assert result.humidity_percent == pytest.approx(100.0)

    def test_optional_fields_absent(self):
        """rise_c_min and uptime_s are optional; their absence returns None."""
        line = '{"node": "n1", "t": 20.0, "h": 50.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is not None
        assert result.rise_c_min is None
        assert result.uptime_s is None

    def test_to_dict(self):
        """to_dict() must include all fields."""
        line = '{"node": "n2", "t": 25.8, "h": 70.1, "rise_c_min": 1.33, "uptime_s": 51}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is not None
        d = result.to_dict()
        assert "node" in d
        assert "temperature_c" in d
        assert "humidity_percent" in d
        assert "rise_c_min" in d
        assert "uptime_s" in d
        assert "timestamp" in d


# ---------------------------------------------------------------------------
# 2. Invalid temperature messages
# ---------------------------------------------------------------------------

class TestInvalidTemperatureMessages:

    def test_temperature_too_high_rejected(self):
        """Temperature above 85 °C must be rejected (not silently zeroed)."""
        line = '{"node": "n1", "t": 200.0, "h": 50.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_temperature_too_low_rejected(self):
        """Temperature below −40 °C must be rejected."""
        line = '{"node": "n1", "t": -100.0, "h": 50.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_humidity_above_100_rejected(self):
        line = '{"node": "n1", "t": 25.0, "h": 150.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_humidity_below_0_rejected(self):
        line = '{"node": "n1", "t": 25.0, "h": -5.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_non_numeric_temperature_rejected(self):
        line = '{"node": "n1", "t": "hot", "h": 50.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_non_numeric_humidity_rejected(self):
        line = '{"node": "n1", "t": 25.0, "h": "wet"}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None


# ---------------------------------------------------------------------------
# 3. Missing JSON fields
# ---------------------------------------------------------------------------

class TestMissingJsonFields:

    def test_missing_node_returns_none(self):
        line = '{"t": 25.0, "h": 50.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_missing_temperature_returns_none(self):
        line = '{"node": "n1", "h": 50.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_missing_humidity_returns_none(self):
        line = '{"node": "n1", "t": 25.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_empty_dict_returns_none(self):
        line = '{}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_null_node_returns_none(self):
        line = '{"node": null, "t": 25.0, "h": 50.0}'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None


# ---------------------------------------------------------------------------
# 4. Malformed / non-JSON input
# ---------------------------------------------------------------------------

class TestMalformedInput:

    def test_pure_garbage_returns_none(self):
        line = "GARBAGE DATA @@@@"
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_truncated_json_returns_none(self):
        line = '{"node": "n1", "t": 25'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_json_array_returns_none(self):
        """A JSON array at the top level is rejected (must be an object)."""
        line = '[25.0, 50.0]'
        reader = _make_reader_with_line(line)
        result = reader.read_one()
        assert result is None

    def test_empty_line_returns_none(self):
        """Empty bytes from a timeout must return None, not raise."""
        reader = _make_reader_with_bytes(b"")
        result = reader.read_one()
        assert result is None

    def test_binary_bytes_returns_none(self):
        """Arbitrary binary data must return None, not raise."""
        reader = _make_reader_with_bytes(b"\x00\x01\xff\xfe\xab\xcd")
        result = reader.read_one()
        assert result is None


# ---------------------------------------------------------------------------
# 5. Serial disconnection handling
# ---------------------------------------------------------------------------

class TestSerialDisconnection:

    def test_serial_exception_during_read_sets_disconnected(self):
        """A SerialException during readline() must mark the reader as disconnected."""
        import serial
        reader = TemperatureReader(port="MOCK_PORT", baudrate=115200)
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial.readline.side_effect = serial.SerialException("Device disconnected")
        reader._serial = mock_serial
        reader._connected = True

        result = reader.read_one()

        assert result is None
        assert reader.is_connected is False

    def test_read_on_unconnected_reader_returns_none(self):
        """read_one() on an unconnected reader must return None without error."""
        reader = TemperatureReader(port="MOCK_PORT", baudrate=115200)
        # Do not call connect()
        result = reader.read_one()
        assert result is None

    def test_connect_failure_sets_disconnected(self):
        """connect() must return False and set is_connected=False when port is unavailable."""
        reader = TemperatureReader(port="NONEXISTENT_PORT_XYZ", baudrate=115200)
        result = reader.connect()
        assert result is False
        assert reader.is_connected is False


# ---------------------------------------------------------------------------
# 6. BH1750 Light sensor decoding tests
# ---------------------------------------------------------------------------

class TestLightDecoding:

    def test_decode_json_format(self):
        from data_acquisition.light import _decode_frame
        assert _decode_frame('{"light_lux": 540.5}') == pytest.approx(540.5)
        assert _decode_frame('{"lux": 1200}') == pytest.approx(1200.0)

    def test_decode_formatted_text(self):
        from data_acquisition.light import _decode_frame
        assert _decode_frame('Light: 450.2 lx') == pytest.approx(450.2)
        assert _decode_frame('BH1750: 980 lux') == pytest.approx(980.0)
        assert _decode_frame('lux = 312.0') == pytest.approx(312.0)
        assert _decode_frame('250.75') == pytest.approx(250.75)

    def test_decode_wifi_status_returns_none(self):
        from data_acquisition.light import _decode_frame
        assert _decode_frame('Connecting to WiFi..') is None
        assert _decode_frame('BH1750 Test begin') is None

    def test_decode_out_of_range_returns_none(self):
        from data_acquisition.light import _decode_frame
        assert _decode_frame('Light: 999999 lx') is None
        assert _decode_frame('Light: -50 lx') is None
