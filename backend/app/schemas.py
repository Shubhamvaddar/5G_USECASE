"""
app/schemas.py — Pydantic request/response models.

Validation rules:
  - Nullable fields remain None when hardware is unavailable; never coerced to 0.
  - Temperature: plausible range −40 … 85 °C (sensor datasheet range).
  - Humidity: 0 … 100 %.
  - rise_c_min: bounded to avoid pathological values.
  - Invalid / out-of-range fields are rejected with a clear error message.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional
from pydantic import BaseModel, Field, field_validator, model_validator, BeforeValidator, PlainSerializer


# ---------------------------------------------------------------------------
# UTC Datetime helper for robust JSON serialization with trailing 'Z'
# ---------------------------------------------------------------------------

def _ensure_utc(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    return v


def _serialize_utc(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo == timezone.utc or v.tzinfo is None:
            return v.strftime("%Y-%m-%dT%H:%M:%S.%fZ") if v.microsecond else v.strftime("%Y-%m-%dT%H:%M:%SZ")
        return v.isoformat()
    return str(v)


UtcDatetime = Annotated[
    datetime,
    BeforeValidator(_ensure_utc),
    PlainSerializer(_serialize_utc, return_type=str, when_used="json"),
]


# ---------------------------------------------------------------------------
# Inbound — POST /api/sensors/data
# ---------------------------------------------------------------------------

class SensorReadingCreate(BaseModel):
    """
    Payload submitted by the data-acquisition collector.
    All hardware-specific fields are Optional; truly absent readings must be
    sent as null (JSON null), not as 0.
    """

    timestamp: Optional[datetime] = Field(
        default=None,
        description="UTC acquisition timestamp. Server sets it if omitted.",
    )
    node: Optional[str] = Field(
        default=None, max_length=64, description="Sensor node identifier."
    )

    # Temperature / Humidity
    temperature_c: Optional[float] = Field(
        default=None, description="Temperature in °C."
    )
    humidity_percent: Optional[float] = Field(
        default=None, description="Relative humidity 0–100 %."
    )
    rise_c_min: Optional[float] = Field(
        default=None, description="Temperature rise rate °C/min."
    )
    uptime_s: Optional[int] = Field(
        default=None, ge=0, description="Sensor uptime in seconds."
    )

    # Light (protocol TBD — only set when a valid reading exists)
    light_lux: Optional[float] = Field(
        default=None, ge=0.0, description="Illuminance in lux."
    )

    # Solar panel / INA219 (hardware not yet available)
    voltage_v: Optional[float] = Field(
        default=None, ge=0.0, description="Panel voltage in V."
    )
    current_a: Optional[float] = Field(
        default=None, description="Panel current in A."
    )
    power_w: Optional[float] = Field(
        default=None, description="Panel power in W."
    )

    source: Optional[str] = Field(
        default="api_post", max_length=64, description="Data provenance tag."
    )

    # ---- Validators -------------------------------------------------------

    @field_validator("temperature_c")
    @classmethod
    def validate_temperature(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-40.0 <= v <= 85.0):
            raise ValueError(
                f"temperature_c {v} is outside the plausible sensor range −40…85 °C"
            )
        return v

    @field_validator("humidity_percent")
    @classmethod
    def validate_humidity(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 100.0):
            raise ValueError(
                f"humidity_percent {v} is outside the valid range 0…100 %"
            )
        return v

    @field_validator("rise_c_min")
    @classmethod
    def validate_rise(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-100.0 <= v <= 100.0):
            raise ValueError(
                f"rise_c_min {v} is implausibly large (expected −100…100 °C/min)"
            )
        return v

    @model_validator(mode="after")
    def set_utc_timestamp(self) -> SensorReadingCreate:
        """If the collector did not send a timestamp, the server supplies one."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        elif self.timestamp.tzinfo is None:
            # Treat naive datetime as UTC
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)
        return self


# ---------------------------------------------------------------------------
# Outbound — single reading response
# ---------------------------------------------------------------------------

class SensorReadingOut(BaseModel):
    id: int
    timestamp: UtcDatetime
    node: Optional[str]
    temperature_c: Optional[float]
    humidity_percent: Optional[float]
    rise_c_min: Optional[float]
    uptime_s: Optional[int]
    light_lux: Optional[float]
    voltage_v: Optional[float]
    current_a: Optional[float]
    power_w: Optional[float]
    source: Optional[str]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Outbound — history list wrapper
# ---------------------------------------------------------------------------

class SensorHistoryOut(BaseModel):
    count: int
    readings: list[SensorReadingOut]


# ---------------------------------------------------------------------------
# Outbound — health
# ---------------------------------------------------------------------------

class HealthOut(BaseModel):
    status: str
    ok: bool = True
    database: str
    app_name: str
    version: str
    timestamp: UtcDatetime


# ---------------------------------------------------------------------------
# Outbound — network status (5G Lab / MEC status)
# ---------------------------------------------------------------------------

class NetworkStatusOut(BaseModel):
    labConnected: bool
    mecConnected: bool
    lastSuccessfulUpdate: Optional[UtcDatetime] = None


# ---------------------------------------------------------------------------
# Outbound — Panel reading (used by frontend dashboard)
# ---------------------------------------------------------------------------

class PanelMeasurements(BaseModel):
    temperatureC: Optional[float] = None
    humidityPercent: Optional[float] = None
    lightLux: Optional[float] = None
    voltageV: Optional[float] = None
    currentA: Optional[float] = None
    powerW: Optional[float] = None


class PanelReadingOut(BaseModel):
    id: str
    timestamp: UtcDatetime
    source: str
    origin: str = "api"
    deviceId: str = "ANUBHAV-PANEL-01"
    measurements: PanelMeasurements
    temperature_c: Optional[float] = None
    humidity_percent: Optional[float] = None
    light_lux: Optional[float] = None
    voltage_v: Optional[float] = None
    current_a: Optional[float] = None
    power_w: Optional[float] = None


class PanelReadingsResponse(BaseModel):
    count: int
    records: list[PanelReadingOut]


# ---------------------------------------------------------------------------
# Outbound — sensor status
# ---------------------------------------------------------------------------

class SensorStatusOut(BaseModel):
    temperature_sensor_connected: bool
    light_sensor_connected: bool
    temperature_port: str
    light_port: str
    note: str


# ---------------------------------------------------------------------------
# Outbound — dashboard summary
# ---------------------------------------------------------------------------

class DashboardSummaryOut(BaseModel):
    latest_temperature_c: Optional[float]
    latest_humidity_percent: Optional[float]
    latest_light_lux: Optional[float]
    latest_voltage_v: Optional[float]
    latest_current_a: Optional[float]
    latest_power_w: Optional[float]
    last_update: Optional[UtcDatetime]
    temperature_sensor_connected: bool
    light_sensor_connected: bool
    node: Optional[str]


# ---------------------------------------------------------------------------
# Outbound — statistics
# ---------------------------------------------------------------------------

class StatisticsOut(BaseModel):
    record_count: int
    temperature_avg_c: Optional[float]
    temperature_min_c: Optional[float]
    temperature_max_c: Optional[float]
    humidity_avg_percent: Optional[float]
    period_start: Optional[UtcDatetime]
    period_end: Optional[UtcDatetime]
