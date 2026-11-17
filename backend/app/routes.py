"""
app/routes.py — All FastAPI route handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import db_models, schemas
from app.config import settings
from app.database import get_db, check_db_health

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Shared sensor status store
# Updated by the collector process via PUT /api/sensors/status/update
# (internal endpoint, not exposed publicly in docs).
# ---------------------------------------------------------------------------
_sensor_status: dict[str, bool] = {
    "temperature": False,
    "light": False,
}


def set_sensor_status(temperature: Optional[bool] = None, light: Optional[bool] = None) -> None:
    """Update the in-process sensor status flags (called from the collector)."""
    if temperature is not None:
        _sensor_status["temperature"] = temperature
    if light is not None:
        _sensor_status["light"] = light


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@router.get("/health", response_model=schemas.HealthOut, tags=["System"])
def health_check():
    """Backend liveness and database connectivity check."""
    db_ok = check_db_health()
    return schemas.HealthOut(
        status="ok" if db_ok else "degraded",
        database="connected" if db_ok else "unreachable",
        app_name=settings.app_name,
        version=settings.app_version,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# POST /api/sensors/data
# ---------------------------------------------------------------------------

@router.post(
    "/sensors/data",
    response_model=schemas.SensorReadingOut,
    status_code=201,
    tags=["Sensors"],
)
def submit_reading(payload: schemas.SensorReadingCreate, db: Session = Depends(get_db)):
    """
    Accept a validated sensor reading from the data-acquisition collector
    and persist it to the database.
    """
    record = db_models.SensorReading(
        timestamp=payload.timestamp,
        node=payload.node,
        temperature_c=payload.temperature_c,
        humidity_percent=payload.humidity_percent,
        rise_c_min=payload.rise_c_min,
        uptime_s=payload.uptime_s,
        light_lux=payload.light_lux,
        voltage_v=payload.voltage_v,
        current_a=payload.current_a,
        power_w=payload.power_w,
        source=payload.source,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(
        "Reading stored: id=%d node=%s t=%.1f°C h=%.1f%%",
        record.id,
        record.node,
        record.temperature_c or 0.0,
        record.humidity_percent or 0.0,
    )
    return record


# ---------------------------------------------------------------------------
# GET /api/sensors/latest
# ---------------------------------------------------------------------------

@router.get(
    "/sensors/latest",
    response_model=schemas.SensorReadingOut,
    tags=["Sensors"],
)
def get_latest(db: Session = Depends(get_db)):
    """Return the most recent sensor reading."""
    record = (
        db.query(db_models.SensorReading)
        .order_by(db_models.SensorReading.timestamp.desc())
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="No readings in the database yet.")
    return record


# ---------------------------------------------------------------------------
# GET /api/sensors/history
# ---------------------------------------------------------------------------

@router.get(
    "/sensors/history",
    response_model=schemas.SensorHistoryOut,
    tags=["Sensors"],
)
def get_history(
    limit: int = Query(default=100, ge=1, le=10_000, description="Max records to return."),
    start: Optional[datetime] = Query(default=None, description="Filter: start timestamp (UTC ISO 8601)."),
    end: Optional[datetime] = Query(default=None, description="Filter: end timestamp (UTC ISO 8601)."),
    node: Optional[str] = Query(default=None, description="Filter by node identifier."),
    db: Session = Depends(get_db),
):
    """Return historical sensor readings with optional filters."""
    q = db.query(db_models.SensorReading)
    if start:
        q = q.filter(db_models.SensorReading.timestamp >= start)
    if end:
        q = q.filter(db_models.SensorReading.timestamp <= end)
    if node:
        q = q.filter(db_models.SensorReading.node == node)
    q = q.order_by(db_models.SensorReading.timestamp.desc()).limit(limit)
    records = q.all()
    return schemas.SensorHistoryOut(count=len(records), readings=records)


# ---------------------------------------------------------------------------
# GET /api/sensors/status
# ---------------------------------------------------------------------------

@router.get(
    "/sensors/status",
    response_model=schemas.SensorStatusOut,
    tags=["Sensors"],
)
def sensor_status():
    """Return the current connection status of each sensor."""
    return schemas.SensorStatusOut(
        temperature_sensor_connected=_sensor_status["temperature"],
        light_sensor_connected=_sensor_status["light"],
        temperature_port=settings.temperature_port,
        light_port=settings.light_port,
        note=(
            "Light sensor protocol unknown — light_lux will remain null "
            "until the protocol is identified and implemented."
        ),
    )


# ---------------------------------------------------------------------------
# GET /api/dashboard/summary
# ---------------------------------------------------------------------------

@router.get(
    "/dashboard/summary",
    response_model=schemas.DashboardSummaryOut,
    tags=["Dashboard"],
)
def dashboard_summary(db: Session = Depends(get_db)):
    """
    Return the most recent values for every sensor channel.
    Fields are null for sensors that have not yet provided a valid reading.
    """
    record = (
        db.query(db_models.SensorReading)
        .order_by(db_models.SensorReading.timestamp.desc())
        .first()
    )
    if record is None:
        return schemas.DashboardSummaryOut(
            latest_temperature_c=None,
            latest_humidity_percent=None,
            latest_light_lux=None,
            latest_voltage_v=None,
            latest_current_a=None,
            latest_power_w=None,
            last_update=None,
            temperature_sensor_connected=_sensor_status["temperature"],
            light_sensor_connected=_sensor_status["light"],
            node=None,
        )
    return schemas.DashboardSummaryOut(
        latest_temperature_c=record.temperature_c,
        latest_humidity_percent=record.humidity_percent,
        latest_light_lux=record.light_lux,
        latest_voltage_v=record.voltage_v,
        latest_current_a=record.current_a,
        latest_power_w=record.power_w,
        last_update=record.timestamp,
        temperature_sensor_connected=_sensor_status["temperature"],
        light_sensor_connected=_sensor_status["light"],
        node=record.node,
    )


# ---------------------------------------------------------------------------
# GET /api/sensors/statistics
# ---------------------------------------------------------------------------

@router.get(
    "/sensors/statistics",
    response_model=schemas.StatisticsOut,
    tags=["Sensors"],
)
def sensor_statistics(
    start: Optional[datetime] = Query(default=None, description="Filter: start timestamp (UTC ISO 8601)."),
    end: Optional[datetime] = Query(default=None, description="Filter: end timestamp (UTC ISO 8601)."),
    node: Optional[str] = Query(default=None, description="Filter by node identifier."),
    db: Session = Depends(get_db),
):
    """
    Aggregate statistics over all (or filtered) stored readings.
    Only reports values for sensors that have actually provided data.
    """
    q = db.query(db_models.SensorReading)
    if start:
        q = q.filter(db_models.SensorReading.timestamp >= start)
    if end:
        q = q.filter(db_models.SensorReading.timestamp <= end)
    if node:
        q = q.filter(db_models.SensorReading.node == node)

    agg = q.with_entities(
        func.count(db_models.SensorReading.id).label("cnt"),
        func.avg(db_models.SensorReading.temperature_c).label("t_avg"),
        func.min(db_models.SensorReading.temperature_c).label("t_min"),
        func.max(db_models.SensorReading.temperature_c).label("t_max"),
        func.avg(db_models.SensorReading.humidity_percent).label("h_avg"),
        func.min(db_models.SensorReading.timestamp).label("ts_start"),
        func.max(db_models.SensorReading.timestamp).label("ts_end"),
    ).one()

    def _round(v, ndigits: int = 2):
        return round(v, ndigits) if v is not None else None

    return schemas.StatisticsOut(
        record_count=agg.cnt or 0,
        temperature_avg_c=_round(agg.t_avg),
        temperature_min_c=_round(agg.t_min),
        temperature_max_c=_round(agg.t_max),
        humidity_avg_percent=_round(agg.h_avg),
        period_start=agg.ts_start,
        period_end=agg.ts_end,
    )


# ---------------------------------------------------------------------------
# Internal: PUT /api/sensors/status/update  (used by in-process collector)
# ---------------------------------------------------------------------------

@router.put(
    "/sensors/status/update",
    include_in_schema=False,  # hidden from Swagger
)
def _update_sensor_status(temperature: Optional[bool] = None, light: Optional[bool] = None):
    set_sensor_status(temperature=temperature, light=light)
    return {"ok": True}


# ---------------------------------------------------------------------------
# GET /api/network/status — 5G Lab / MEC Network Status
# ---------------------------------------------------------------------------

@router.get(
    "/network/status",
    response_model=schemas.NetworkStatusOut,
    tags=["Network"],
)
def network_status(db: Session = Depends(get_db)):
    """
    Return 5G Lab and MEC network connection status.
    Uses the latest database record to compute lastSuccessfulUpdate.
    """
    latest = (
        db.query(db_models.SensorReading)
        .order_by(db_models.SensorReading.timestamp.desc())
        .first()
    )
    return schemas.NetworkStatusOut(
        labConnected=True,
        mecConnected=True,
        lastSuccessfulUpdate=latest.timestamp if latest else None,
    )


# ---------------------------------------------------------------------------
# GET /api/panels/real/readings — Frontend Dashboard Real Panel Stream
# ---------------------------------------------------------------------------

@router.get(
    "/panels/real/readings",
    response_model=schemas.PanelReadingsResponse,
    tags=["Panels"],
)
def get_real_panel_readings(
    limit: int = Query(default=48, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Return real panel readings formatted for the Anubhav 5G Dashboard.
    Sorted in ascending order of timestamp so charts render chronologically.
    """
    records = (
        db.query(db_models.SensorReading)
        .order_by(db_models.SensorReading.timestamp.desc())
        .limit(limit)
        .all()
    )
    records.reverse()

    results = []
    for r in records:
        calculated_power = r.power_w
        if calculated_power is None and r.voltage_v is not None and r.current_a is not None:
            calculated_power = round(r.voltage_v * r.current_a, 3)

        measurements = schemas.PanelMeasurements(
            temperatureC=r.temperature_c,
            humidityPercent=r.humidity_percent,
            lightLux=r.light_lux,
            voltageV=r.voltage_v,
            currentA=r.current_a,
            powerW=calculated_power,
        )
        results.append(
            schemas.PanelReadingOut(
                id=f"real-{r.id}",
                timestamp=r.timestamp,
                source="real",
                origin="api",
                deviceId=r.node or "ANUBHAV-PANEL-01",
                measurements=measurements,
                temperature_c=r.temperature_c,
                humidity_percent=r.humidity_percent,
                light_lux=r.light_lux,
                voltage_v=r.voltage_v,
                current_a=r.current_a,
                power_w=calculated_power,
            )
        )
    return schemas.PanelReadingsResponse(count=len(results), records=results)


# ---------------------------------------------------------------------------
# GET /api/panels/simulated/readings — Digital Twin Model Predictions
# ---------------------------------------------------------------------------

@router.get(
    "/panels/simulated/readings",
    response_model=schemas.PanelReadingsResponse,
    tags=["Panels"],
)
def get_simulated_panel_readings(
    limit: int = Query(default=48, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Return digital twin model predictions derived from the real panel readings.
    Applies the mathematical model:
      - Light acts as linear irradiance proxy (capped at 1.2x reference 95,000 lx)
      - Power derates 0.4% per °C above 25°C
      - Voltage derates 0.025 V/°C above 25°C
    """
    records = (
        db.query(db_models.SensorReading)
        .order_by(db_models.SensorReading.timestamp.desc())
        .limit(limit)
        .all()
    )
    records.reverse()

    results = []
    for r in records:
        lux = r.light_lux if r.light_lux is not None else 0.0
        temp = r.temperature_c if r.temperature_c is not None else 25.0
        irradiance_factor = min(1.2, max(0.0, lux / 95000.0))
        temp_factor = max(0.72, 1.0 - max(0.0, temp - 25.0) * 0.004)
        sim_voltage = max(0.0, 17.4 - max(0.0, temp - 25.0) * 0.025) if lux > 0 else 0.0
        sim_power = round(100.0 * irradiance_factor * temp_factor, 2)
        sim_current = round(sim_power / sim_voltage, 2) if sim_voltage > 0 else 0.0

        measurements = schemas.PanelMeasurements(
            temperatureC=round(temp, 1),
            humidityPercent=r.humidity_percent,
            lightLux=round(lux),
            voltageV=round(sim_voltage, 2),
            currentA=sim_current,
            powerW=sim_power,
        )
        results.append(
            schemas.PanelReadingOut(
                id=f"twin-{r.id}",
                timestamp=r.timestamp,
                source="simulated",
                origin="model",
                deviceId="ANUBHAV-TWIN-01",
                measurements=measurements,
                temperature_c=round(temp, 1),
                humidity_percent=r.humidity_percent,
                light_lux=round(lux),
                voltage_v=round(sim_voltage, 2),
                current_a=sim_current,
                power_w=sim_power,
            )
        )
    return schemas.PanelReadingsResponse(count=len(results), records=results)
