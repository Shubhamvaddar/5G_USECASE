# SolarTwin 5G — Backend & Data Acquisition

Digital twin monitoring system for solar photovoltaic panels.  
Acquires environmental sensor data via USB-UART, stores it in SQLite, and exposes a REST API for the dashboard and future 5G / MEC integration.

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Hardware Setup](#hardware-setup)
3. [Quick Start — Windows](#quick-start--windows)
4. [Quick Start — Fedora / Linux](#quick-start--fedora--linux)
5. [Configuration (.env)](#configuration-env)
6. [API Endpoints](#api-endpoints)
7. [Running Tests](#running-tests)
8. [Architecture Notes](#architecture-notes)
9. [Future Integration](#future-integration)
10. [Troubleshooting](#troubleshooting)

---

## Project Structure

```
backend/
│
├── app/
│   ├── __init__.py
│   ├── main.py          ← FastAPI app entry point, lifespan
│   ├── config.py        ← Settings (env vars), logging setup
│   ├── database.py      ← SQLAlchemy engine, session, init_db()
│   ├── db_models.py     ← SensorReading ORM model
│   ├── schemas.py       ← Pydantic request / response models
│   └── routes.py        ← All REST endpoints
│
├── data_acquisition/
│   ├── __init__.py
│   ├── serial_config.py ← Platform-agnostic serial port factory
│   ├── temperature.py   ← CP2102 JSON temperature/humidity reader
│   ├── light.py         ← Light sensor stub (protocol unknown)
│   └── collector.py     ← Main acquisition loop, posts to API
│
├── tests/
│   ├── __init__.py
│   ├── test_temperature_parser.py  ← 27 sensor parsing tests
│   ├── test_database.py            ← 8 database layer tests
│   └── test_api.py                 ← 25 route handler tests
│
├── logs/                ← Log files (auto-created, gitignored)
├── requirements.txt
├── .env.example         ← Template — copy to .env and edit
├── .gitignore
├── pytest.ini
└── README.md
```

---

## Hardware Setup

### Currently available

| Sensor | Windows port | Linux port | Baud | Protocol |
|--------|-------------|-----------|------|----------|
| Temperature + Humidity (CP2102) | COM21 | /dev/ttyUSB1 | 115200 | UTF-8 JSON |
| Light intensity (CP2102) | COM20 | /dev/ttyUSB0 | 9600 | BH1750 (ESP32) |

**Temperature JSON example (from real sensor):**
```json
{"node": "node2", "t": 25.8, "h": 70.1, "rise_c_min": 1.33, "uptime_s": 51}
```

**Light sensor:** Currently outputs mostly zero bytes. The protocol has not been identified. `light_lux` will remain `null` in all records until the protocol is decoded. See `data_acquisition/light.py` for the stub and diagnostic logging.

### Hardware not yet available

- Arduino Uno + INA219 current sensor + solar PV panel  
  → `voltage_v`, `current_a`, `power_w` stored as `NULL` until hardware is available.

---

## Quick Start — Windows

### 1. Create virtual environment (first time only)

```powershell
cd c:\SolarTwin\backend
python -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure

```powershell
copy .env.example .env
# Edit .env to match your COM ports — TEMPERATURE_PORT=COM8, LIGHT_PORT=COM7
notepad .env
```

### 4. Start the backend API

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API: http://127.0.0.1:8000  
Swagger docs: http://127.0.0.1:8000/docs

### 5. Start the data acquisition collector (second terminal)

```powershell
cd c:\SolarTwin\backend
venv\Scripts\activate
python -m data_acquisition.collector
```

The collector connects to the temperature sensor on COM8, polls every 5 seconds, and POSTs each reading to the backend API. Readings appear in the database immediately.

---

## Quick Start — Fedora / Linux

### 1. Create virtual environment

```bash
cd ~/SolarTwin/backend
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Serial port permissions

Add your user to the `dialout` group (required for USB serial access):

```bash
sudo usermod -aG dialout $USER
# Log out and log back in for the change to take effect
```

Verify the ports are visible:

```bash
ls /dev/ttyUSB*
# Expected: /dev/ttyUSB0 (light), /dev/ttyUSB1 (temperature)
# If order differs, check: dmesg | grep ttyUSB
```

### 4. Configure

```bash
cp .env.example .env
nano .env
# Set:
#   TEMPERATURE_PORT=/dev/ttyUSB1
#   LIGHT_PORT=/dev/ttyUSB0
```

### 5. Start backend

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 6. Start collector

```bash
python -m data_acquisition.collector
```

---

## Configuration (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./solartwin.db` | SQLite path (relative to backend/) |
| `TEMPERATURE_PORT` | `COM21` | Serial port for temp sensor |
| `TEMPERATURE_BAUDRATE` | `115200` | Baud rate |
| `TEMPERATURE_READ_TIMEOUT` | `2.0` | Seconds per readline() |
| `TEMPERATURE_RECONNECT_DELAY` | `5.0` | Seconds before reconnect |
| `LIGHT_PORT` | `COM20` | Serial port for light sensor |
| `LIGHT_BAUDRATE` | `9600` | Baud rate for BH1750 ESP32 |
| `LIGHT_DIAG_SAMPLE_BYTES` | `64` | Max bytes logged per diagnostic sample |
| `COLLECTION_INTERVAL` | `5` | Seconds between acquisition cycles |
| `API_HOST` | `127.0.0.1` | Backend bind address |
| `API_PORT` | `8000` | Backend bind port |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_FILE` | `logs/solartwin.log` | Rotating log file path |

> **Never commit `.env` to version control.** It is listed in `.gitignore`.

---

## API Endpoints

Base URL: `http://127.0.0.1:8000/api`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Backend status and DB connectivity |
| `POST` | `/sensors/data` | Submit a sensor reading |
| `GET` | `/sensors/latest` | Most recent reading |
| `GET` | `/sensors/history` | Historical readings with filters |
| `GET` | `/sensors/status` | Sensor connection status |
| `GET` | `/dashboard/summary` | Latest values for all channels |
| `GET` | `/sensors/statistics` | Aggregate temperature/humidity stats |

### Query parameters for `/sensors/history`

| Param | Type | Description |
|-------|------|-------------|
| `limit` | int (1–10000) | Max records (default 100) |
| `start` | ISO 8601 datetime | Filter: earliest timestamp |
| `end` | ISO 8601 datetime | Filter: latest timestamp |
| `node` | string | Filter by node ID |

### Query parameters for `/sensors/statistics`

Same `start`, `end`, `node` filters as history.

### POST `/sensors/data` payload

```json
{
  "node": "node2",
  "temperature_c": 25.8,
  "humidity_percent": 70.1,
  "rise_c_min": 1.33,
  "uptime_s": 51,
  "light_lux": null,
  "voltage_v": null,
  "current_a": null,
  "power_w": null,
  "source": "collector"
}
```

**Validation rules:**
- `temperature_c`: must be in −40 … 85 °C (or `null`)
- `humidity_percent`: must be in 0 … 100 % (or `null`)
- `rise_c_min`: must be in −100 … 100 °C/min (or `null`)
- Hardware-unavailable fields: send `null`, never `0`

Full interactive docs: http://127.0.0.1:8000/docs

---

## Running Tests

```powershell
cd c:\SolarTwin\backend
python -m pytest tests/ -v
```

**60 tests, 0 failures.** No physical sensors required — all hardware is mocked.

| Test file | Tests | Coverage |
|-----------|-------|----------|
| `test_temperature_parser.py` | 27 | JSON parsing, validation, serial errors |
| `test_database.py` | 8 | Insertion, NULL handling, ordering |
| `test_api.py` | 25 | All 7 endpoints, schema validation |

```
============================= 60 passed in 0.92s ==============================
```

---

## Architecture Notes

### Serial port ownership

The **collector** is the sole owner of both serial ports. The FastAPI process never opens a serial port. This eliminates port conflicts when both processes run simultaneously.

### Sensor status

The collector calls the internal `PUT /api/sensors/status/update` endpoint to keep the backend aware of current connection states. The status is reflected in `/api/sensors/status` and `/api/dashboard/summary`.

### NULL vs zero

Fields for unavailable hardware are stored as SQL `NULL`. A genuine reading of `0.0` is a valid measurement (e.g., complete darkness for lux). The system never silently converts `null` to `0`.

### WAL mode

SQLite runs in Write-Ahead Logging mode (`PRAGMA journal_mode=WAL`) for better concurrent read/write performance between the API and collector processes.

### Reconnect logic

Both sensor readers reconnect automatically after disconnection. The reconnect interval is configurable (`TEMPERATURE_RECONNECT_DELAY`, `LIGHT_RECONNECT_DELAY`). The acquisition loop does not crash when a sensor is unplugged.

---

## Future Integration

### Light sensor protocol

The light sensor's binary output is captured, hex-logged at `DEBUG` level, and ignored until the protocol is identified. Steps to decode:

1. Set `LOG_LEVEL=DEBUG` in `.env`
2. Run the collector and examine the hex output for `[light]` lines
3. Cross-reference with the sensor datasheet or vendor documentation
4. Implement the decode logic in `data_acquisition/light.py` → `_decode_frame()`

### Arduino + INA219 (solar panel)

Create `data_acquisition/arduino.py` following the pattern of `temperature.py`. The database already has `voltage_v`, `current_a`, `power_w` columns ready. No schema migration required.

### Private 5G / MEC deployment

Change `API_HOST` and `API_PORT` in `.env` to point to the MEC server address. The collector will POST readings to the remote endpoint. No code changes required.

For the MEC server deployment:
1. Deploy the FastAPI backend on the MEC server.
2. Configure the laptop gateway's `.env` with the MEC server IP/port.
3. Ensure the 5G NPN (Non-Public Network) route is established before starting the collector.
4. Do not use public internet — keep all traffic on the private 5G network.

---

## Troubleshooting

### "Cannot open COM8: Access is denied"
- Another application (e.g., serial monitor) has the port open. Close it and retry.
- On Windows: Device Manager → Ports → verify the COM number.

### "Cannot open COM8: FileNotFoundError"
- Sensor USB cable is not plugged in, or driver is not installed (Silicon Labs CP2102).
- Download CP210x driver from: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers

### "Cannot open /dev/ttyUSB1: Permission denied" (Linux)
```bash
sudo usermod -aG dialout $USER
# Then log out and log back in
```

### Collector starts but no readings appear in the database
- Verify the backend API is running: `curl http://127.0.0.1:8000/api/health`
- Check the collector log output for POST errors.
- Verify `API_HOST` and `API_PORT` in `.env` match the running backend.

### Light sensor shows all zeros / no lux value
- Expected behaviour. The light sensor protocol is unknown.
- `light_lux` will remain `null`. Set `LOG_LEVEL=DEBUG` to view raw hex output.

### Temperature reads seem wrong
- Verify the correct port is set in `TEMPERATURE_PORT`.
- Use a serial terminal (e.g., PuTTY / minicom) to confirm raw JSON output.
- Example expected line: `{"node": "node2", "t": 25.8, "h": 70.1, "rise_c_min": 1.33, "uptime_s": 51}`

### Port order differs on Linux after replug
- Ports are assigned in plug order. Check with `dmesg | grep ttyUSB` after plugging sensors.
- Update `TEMPERATURE_PORT` / `LIGHT_PORT` in `.env` accordingly.
