"""
app/db_models.py — SQLAlchemy ORM models.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, Float, String, DateTime, Index, TypeDecorator
)
from app.database import Base


class UTCDateTime(TypeDecorator):
    """
    Ensures that datetimes stored and retrieved from SQLite (which strips timezone offsets)
    are always returned as timezone-aware UTC datetime objects.
    """
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value


class SensorReading(Base):
    """
    One timestamped row of sensor data from any combination of attached sensors.

    Columns that have no corresponding hardware yet are nullable and stored as
    NULL (never as zero or a fabricated value).
    """

    __tablename__ = "sensor_readings"

    # Primary key
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Gateway-stamped UTC acquisition time (not the sensor's own uptime clock)
    timestamp = Column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Sensor identity
    node = Column(String(64), nullable=True, index=True)

    # --- Temperature / Humidity sensor (CP2102 JSON) ----------------------
    temperature_c = Column(Float, nullable=True)
    humidity_percent = Column(Float, nullable=True)
    rise_c_min = Column(Float, nullable=True)      # °C per minute rise rate
    uptime_s = Column(Integer, nullable=True)       # sensor's own uptime counter

    # --- Light sensor (protocol TBD) -------------------------------------
    light_lux = Column(Float, nullable=True)        # NULL until protocol known

    # --- Solar panel / INA219 (hardware not yet available) ---------------
    voltage_v = Column(Float, nullable=True)
    current_a = Column(Float, nullable=True)
    power_w = Column(Float, nullable=True)

    # Data provenance: 'collector', 'api_post', 'test', etc.
    source = Column(String(64), nullable=True, default="collector")

    # Composite indexes for the most common query patterns
    __table_args__ = (
        Index("ix_readings_timestamp", "timestamp"),
        Index("ix_readings_node_timestamp", "node", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<SensorReading id={self.id} node={self.node!r} "
            f"ts={self.timestamp} t={self.temperature_c}°C h={self.humidity_percent}%>"
        )
