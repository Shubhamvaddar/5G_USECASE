"""
tests/test_database.py — Tests for database models and persistence layer.

Uses an in-memory SQLite database — never touches solartwin.db.
"""

import sys
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base
from app.db_models import SensorReading


# ---------------------------------------------------------------------------
# In-memory database fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """Provide a fresh in-memory SQLite session for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# 4. Database record insertion
# ---------------------------------------------------------------------------

class TestDatabaseInsertion:

    def test_insert_full_reading(self, db_session):
        """A complete reading with all fields is stored and retrieved correctly."""
        now = datetime.now(timezone.utc)
        record = SensorReading(
            timestamp=now,
            node="node2",
            temperature_c=25.8,
            humidity_percent=70.1,
            rise_c_min=1.33,
            uptime_s=51,
            light_lux=None,
            voltage_v=None,
            current_a=None,
            power_w=None,
            source="test",
        )
        db_session.add(record)
        db_session.commit()

        retrieved = db_session.query(SensorReading).filter_by(node="node2").first()
        assert retrieved is not None
        assert retrieved.temperature_c == pytest.approx(25.8)
        assert retrieved.humidity_percent == pytest.approx(70.1)
        assert retrieved.rise_c_min == pytest.approx(1.33)
        assert retrieved.uptime_s == 51
        assert retrieved.source == "test"

    def test_insert_minimal_reading(self, db_session):
        """A reading with only temperature/humidity (all else NULL) is valid."""
        record = SensorReading(
            timestamp=datetime.now(timezone.utc),
            node="n1",
            temperature_c=22.0,
            humidity_percent=45.0,
        )
        db_session.add(record)
        db_session.commit()

        retrieved = db_session.query(SensorReading).first()
        assert retrieved is not None
        assert retrieved.light_lux is None
        assert retrieved.voltage_v is None
        assert retrieved.current_a is None
        assert retrieved.power_w is None

    def test_null_readings_are_null_not_zero(self, db_session):
        """Fields that have no hardware must be stored as NULL, not 0."""
        record = SensorReading(
            timestamp=datetime.now(timezone.utc),
            node="n1",
            temperature_c=20.0,
            humidity_percent=50.0,
        )
        db_session.add(record)
        db_session.commit()

        retrieved = db_session.query(SensorReading).first()
        assert retrieved.light_lux is None
        assert retrieved.voltage_v is None
        assert retrieved.power_w is None

    def test_multiple_readings_ordered_by_timestamp(self, db_session):
        """Multiple readings are retrieved in the expected order."""
        for i in range(3):
            record = SensorReading(
                timestamp=datetime(2025, 1, 1, i, 0, 0, tzinfo=timezone.utc),
                node="n1",
                temperature_c=20.0 + i,
                humidity_percent=50.0,
                source="test",
            )
            db_session.add(record)
        db_session.commit()

        records = (
            db_session.query(SensorReading)
            .order_by(SensorReading.timestamp.desc())
            .all()
        )
        assert len(records) == 3
        assert records[0].temperature_c == pytest.approx(22.0)
        assert records[2].temperature_c == pytest.approx(20.0)

    def test_auto_increment_id(self, db_session):
        """Each inserted record gets a unique auto-incremented ID."""
        for _ in range(3):
            db_session.add(
                SensorReading(
                    timestamp=datetime.now(timezone.utc),
                    temperature_c=20.0,
                    humidity_percent=50.0,
                )
            )
        db_session.commit()

        ids = [r.id for r in db_session.query(SensorReading).all()]
        assert len(set(ids)) == 3  # all unique

    def test_repr_contains_node_and_temperature(self, db_session):
        """__repr__ should include node and temperature for debugging."""
        record = SensorReading(
            timestamp=datetime.now(timezone.utc),
            node="node_repr",
            temperature_c=30.0,
            humidity_percent=60.0,
        )
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)
        repr_str = repr(record)
        assert "node_repr" in repr_str
        assert "30.0" in repr_str


# ---------------------------------------------------------------------------
# 9. Missing light measurements (database perspective)
# ---------------------------------------------------------------------------

class TestMissingLightMeasurements:

    def test_light_lux_stored_as_null(self, db_session):
        """When no valid light reading is available, light_lux is NULL."""
        record = SensorReading(
            timestamp=datetime.now(timezone.utc),
            node="n1",
            temperature_c=25.0,
            humidity_percent=60.0,
            light_lux=None,  # explicitly None
        )
        db_session.add(record)
        db_session.commit()

        r = db_session.query(SensorReading).first()
        assert r.light_lux is None

    def test_light_lux_zero_is_different_from_null(self, db_session):
        """
        A genuine zero-lux reading (e.g., complete darkness) is distinguishable
        from a missing reading (NULL).
        """
        db_session.add(SensorReading(
            timestamp=datetime.now(timezone.utc),
            node="n1",
            temperature_c=25.0,
            humidity_percent=60.0,
            light_lux=0.0,     # real zero reading
        ))
        db_session.add(SensorReading(
            timestamp=datetime.now(timezone.utc),
            node="n2",
            temperature_c=25.0,
            humidity_percent=60.0,
            light_lux=None,    # sensor unavailable
        ))
        db_session.commit()

        zero_r = db_session.query(SensorReading).filter_by(node="n1").first()
        null_r = db_session.query(SensorReading).filter_by(node="n2").first()

        assert zero_r.light_lux == pytest.approx(0.0)
        assert null_r.light_lux is None
        assert zero_r.light_lux != null_r.light_lux or null_r.light_lux is None
