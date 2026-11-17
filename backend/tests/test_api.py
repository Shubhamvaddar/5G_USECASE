"""
tests/test_api.py — Tests for the FastAPI route handlers.

The tests call route handler functions directly with a real in-memory SQLite
session instead of making HTTP requests through an ASGI transport. This avoids
the anyio/threading overhead that hangs in constrained sandbox environments,
while still exercising all business logic, database operations, and Pydantic
validation.

All tests use an isolated in-memory SQLite database — the production
solartwin.db is never touched.
"""

import sys
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base
from app.db_models import SensorReading
from app.schemas import SensorReadingCreate
from app import routes as route_module

# ---------------------------------------------------------------------------
# In-memory test database
# ---------------------------------------------------------------------------

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def reset_test_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    yield session
    session.close()


def _seed_reading(db, **kwargs) -> SensorReading:
    defaults = {
        "timestamp": datetime.now(timezone.utc),
        "node": "test_node",
        "temperature_c": 25.0,
        "humidity_percent": 60.0,
        "rise_c_min": 0.5,
        "uptime_s": 100,
        "source": "test",
    }
    defaults.update(kwargs)
    record = SensorReading(**defaults)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# ---------------------------------------------------------------------------
# 5. Health endpoint — test the response object directly
# ---------------------------------------------------------------------------

class TestHealthEndpoint:

    def test_health_returns_ok_when_db_healthy(self):
        with patch("app.routes.check_db_health", return_value=True):
            result = route_module.health_check()
        assert result.status == "ok"
        assert result.database == "connected"

    def test_health_response_has_all_fields(self):
        with patch("app.routes.check_db_health", return_value=True):
            result = route_module.health_check()
        assert result.app_name is not None
        assert result.version is not None
        assert result.timestamp is not None

    def test_health_returns_degraded_when_db_down(self):
        with patch("app.routes.check_db_health", return_value=False):
            result = route_module.health_check()
        assert result.status == "degraded"
        assert result.database == "unreachable"


# ---------------------------------------------------------------------------
# 6. Latest reading endpoint
# ---------------------------------------------------------------------------

class TestLatestEndpoint:

    def test_latest_raises_404_when_no_data(self, db):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            route_module.get_latest(db=db)
        assert exc_info.value.status_code == 404

    def test_latest_returns_most_recent(self, db):
        _seed_reading(db, temperature_c=20.0,
                      timestamp=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc))
        _seed_reading(db, temperature_c=30.0,
                      timestamp=datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc))
        result = route_module.get_latest(db=db)
        assert result.temperature_c == pytest.approx(30.0)

    def test_latest_includes_null_light(self, db):
        _seed_reading(db, light_lux=None)
        result = route_module.get_latest(db=db)
        assert result.light_lux is None


# ---------------------------------------------------------------------------
# 7. Historical readings endpoint
# ---------------------------------------------------------------------------

class TestHistoryEndpoint:

    def test_history_empty_returns_zero_count(self, db):
        result = route_module.get_history(
            limit=100, start=None, end=None, node=None, db=db
        )
        assert result.count == 0
        assert result.readings == []

    def test_history_returns_seeded_records(self, db):
        for i in range(3):
            _seed_reading(db, temperature_c=20.0 + i)
        result = route_module.get_history(
            limit=100, start=None, end=None, node=None, db=db
        )
        assert result.count == 3

    def test_history_limit_parameter(self, db):
        for i in range(10):
            _seed_reading(db)
        result = route_module.get_history(
            limit=3, start=None, end=None, node=None, db=db
        )
        assert result.count == 3

    def test_history_node_filter(self, db):
        _seed_reading(db, node="alpha")
        _seed_reading(db, node="beta")
        _seed_reading(db, node="alpha")
        result = route_module.get_history(
            limit=100, start=None, end=None, node="alpha", db=db
        )
        assert result.count == 2

    def test_history_start_filter(self, db):
        _seed_reading(db, timestamp=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc))
        _seed_reading(db, timestamp=datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc))
        result = route_module.get_history(
            limit=100,
            start=datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc),
            end=None,
            node=None,
            db=db,
        )
        assert result.count == 1

    def test_history_end_filter(self, db):
        _seed_reading(db, timestamp=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc))
        _seed_reading(db, timestamp=datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc))
        result = route_module.get_history(
            limit=100,
            start=None,
            end=datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc),
            node=None,
            db=db,
        )
        assert result.count == 1


# ---------------------------------------------------------------------------
# 8. Invalid API payloads — Pydantic validation
# ---------------------------------------------------------------------------

class TestSubmitReadingValidation:

    def test_valid_payload_accepted(self, db):
        payload = SensorReadingCreate(
            node="node2",
            temperature_c=25.8,
            humidity_percent=70.1,
            rise_c_min=1.33,
            uptime_s=51,
        )
        result = route_module.submit_reading(payload=payload, db=db)
        assert result.id is not None
        assert result.temperature_c == pytest.approx(25.8)

    def test_valid_post_with_null_light(self, db):
        payload = SensorReadingCreate(
            node="n1", temperature_c=22.0, humidity_percent=55.0, light_lux=None
        )
        result = route_module.submit_reading(payload=payload, db=db)
        assert result.light_lux is None

    def test_temperature_above_range_rejected(self):
        with pytest.raises(Exception) as exc_info:
            SensorReadingCreate(temperature_c=200.0, humidity_percent=50.0)
        assert "temperature_c" in str(exc_info.value).lower() or "value_error" in str(exc_info.value).lower()

    def test_temperature_below_range_rejected(self):
        with pytest.raises(Exception):
            SensorReadingCreate(temperature_c=-99.0, humidity_percent=50.0)

    def test_humidity_above_100_rejected(self):
        with pytest.raises(Exception):
            SensorReadingCreate(temperature_c=25.0, humidity_percent=150.0)

    def test_humidity_below_0_rejected(self):
        with pytest.raises(Exception):
            SensorReadingCreate(temperature_c=25.0, humidity_percent=-1.0)

    def test_empty_payload_accepted(self, db):
        """All fields optional — empty payload is valid."""
        payload = SensorReadingCreate()
        result = route_module.submit_reading(payload=payload, db=db)
        assert result.id is not None

    def test_stored_null_fields_are_null(self, db):
        """Explicitly null hardware fields stored as NULL, not 0."""
        payload = SensorReadingCreate(
            node="nulltest",
            temperature_c=25.0,
            humidity_percent=50.0,
            voltage_v=None,
            current_a=None,
            power_w=None,
            light_lux=None,
        )
        result = route_module.submit_reading(payload=payload, db=db)
        assert result.voltage_v is None
        assert result.light_lux is None

        stored = db.query(SensorReading).filter_by(node="nulltest").first()
        assert stored.voltage_v is None
        assert stored.light_lux is None


# ---------------------------------------------------------------------------
# Dashboard and statistics
# ---------------------------------------------------------------------------

class TestDashboardEndpoint:

    def test_dashboard_no_data(self, db):
        result = route_module.dashboard_summary(db=db)
        assert result.latest_temperature_c is None
        assert result.latest_light_lux is None

    def test_dashboard_with_data(self, db):
        _seed_reading(db, temperature_c=28.0, humidity_percent=65.0)
        result = route_module.dashboard_summary(db=db)
        assert result.latest_temperature_c == pytest.approx(28.0)
        assert result.latest_humidity_percent == pytest.approx(65.0)
        assert result.latest_light_lux is None


class TestStatisticsEndpoint:

    def test_statistics_empty_db(self, db):
        result = route_module.sensor_statistics(
            start=None, end=None, node=None, db=db
        )
        assert result.record_count == 0
        assert result.temperature_avg_c is None

    def test_statistics_with_data(self, db):
        _seed_reading(db, temperature_c=20.0, humidity_percent=50.0)
        _seed_reading(db, temperature_c=30.0, humidity_percent=70.0)
        result = route_module.sensor_statistics(
            start=None, end=None, node=None, db=db
        )
        assert result.record_count == 2
        assert result.temperature_avg_c == pytest.approx(25.0)
        assert result.temperature_min_c == pytest.approx(20.0)
        assert result.temperature_max_c == pytest.approx(30.0)
        assert result.humidity_avg_percent == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Sensor status
# ---------------------------------------------------------------------------

class TestSensorStatus:

    def test_sensor_status_structure(self):
        result = route_module.sensor_status()
        assert hasattr(result, "temperature_sensor_connected")
        assert hasattr(result, "light_sensor_connected")
        assert hasattr(result, "temperature_port")
        assert hasattr(result, "light_port")
        assert hasattr(result, "note")
        assert "unknown" in result.note.lower()


# ---------------------------------------------------------------------------
# Frontend integration endpoints
# ---------------------------------------------------------------------------

class TestFrontendEndpoints:

    def test_network_status_empty_db(self, db):
        result = route_module.network_status(db=db)
        assert result.labConnected is True
        assert result.mecConnected is True
        assert result.lastSuccessfulUpdate is None

    def test_network_status_with_data(self, db):
        r = _seed_reading(db)
        result = route_module.network_status(db=db)
        assert result.labConnected is True
        assert result.mecConnected is True
        assert result.lastSuccessfulUpdate is not None

    def test_real_panel_readings_empty(self, db):
        result = route_module.get_real_panel_readings(limit=48, db=db)
        assert result.count == 0
        assert result.records == []

    def test_real_panel_readings_formatted(self, db):
        _seed_reading(db, temperature_c=26.4, humidity_percent=65.2, light_lux=1200.0)
        result = route_module.get_real_panel_readings(limit=48, db=db)
        assert result.count == 1
        record = result.records[0]
        assert record.source == "real"
        assert record.measurements.temperatureC == pytest.approx(26.4)
        assert record.measurements.humidityPercent == pytest.approx(65.2)
        assert record.measurements.lightLux == pytest.approx(1200.0)

    def test_simulated_twin_readings(self, db):
        _seed_reading(db, temperature_c=25.0, light_lux=95000.0)
        result = route_module.get_simulated_panel_readings(limit=48, db=db)
        assert result.count == 1
        record = result.records[0]
        assert record.source == "simulated"
        assert record.origin == "model"
        assert record.deviceId == "ANUBHAV-TWIN-01"
        assert record.measurements.powerW is not None
        assert record.measurements.powerW > 0
