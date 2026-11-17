# Coral Anubhav 5G Dashboard

A React + Vite demo dashboard for the solar-panel live-monitoring and digital-twin use case. The zip includes the source project and a production build. With no API configured it runs on clearly labeled demo data, so it can be previewed without the board or backend.

## Quick run on Windows (built demo, easiest)

1. Extract the zip.
2. Double-click `run-built-windows.bat`.
3. It opens the dashboard in your browser at `http://127.0.0.1:8000`.

This quick run needs Python 3. The built dashboard is in `dist/`.

## Quick run on macOS or Linux (built demo)

Open Terminal in the extracted folder and run:

```sh
./run-built.sh
```

The script serves `dist/` locally and opens the browser. Press Ctrl+C in the terminal to stop it.

## Run or modify the React source

Requires Node.js 20+ and npm. On Windows, double-click `run-dashboard.bat`. On macOS/Linux:

```sh
npm install
npm run dev
```

Vite prints the local address. The app starts in Demo Data mode until a backend URL is configured.

## Backend setup

Set `VITE_API_BASE_URL` and optional endpoint paths in `.env` (copy `.env.example` to `.env`), or enter the API base URL on the Network Status page. The expected API paths and JSON record format are documented below. Real records must have `source: "real"`; simulated records must have `source: "simulated"`.

Default endpoints:

- `/api/panels/real/readings`
- `/api/panels/simulated/readings` (optional; the client twin model is the fallback)
- `/api/health`
- `/api/network/status`

Read the source project notes and simulation assumptions in the rest of this README or inspect `.env.example` and `src/services/api.js`.

## Build for deployment

```sh
npm install
npm run build
```

Deploy the contents of `dist/` to a static web host. This bundle is prepared for Member 3; it has not been deployed to MEC.

## Demo-data and twin labels

The bundled sample records are for UI demonstration only and are marked **Demo Data · No hardware measurements**. The digital twin outputs are always marked **Simulated / Predicted**. They are not physical measurements.

The illustrative v1 twin model reads light intensity and temperature from its input record:

- 95,000 lx is treated as the reference light level and maps to 100 W at 25 °C.
- Predicted power scales linearly with lux, capped at 1.2 times the reference.
- Above 25 °C, power is reduced by 0.4% per °C and voltage by 0.025 V per °C.
- Predicted current is power divided by voltage.
- Lux is not calibrated irradiance; the model is not calibrated to the physical panel.

## Data shape

The API may return a bare array or `{ "records": [...] }`, `{ "data": [...] }`, or `{ "readings": [...] }`. Example:

```json
{
  "records": [
    {
      "id": "panel-001",
      "timestamp": "2026-11-06T08:15:30Z",
      "source": "real",
      "deviceId": "PANEL-01",
      "measurements": {
        "lightLux": 73500,
        "temperatureC": 33.2,
        "voltageV": 17.1,
        "currentA": 4.2,
        "powerW": 71.82
      }
    }
  ]
}
```

Sensor fields can be missing or null. Missing values appear blank; if power is absent and voltage/current exist, the dashboard calculates voltage × current. Historical charts use timestamped records.

## UI states and checks

The dashboard separates demo, loading, empty, stale, API-error, and live states. Missing sensor fields are kept as chart gaps. Lab/MEC state is only shown from backend network-check fields; it is never inferred from the browser's network status.

Run the adapter checks with `npm test`. The tests cover missing values, source filtering, stale timestamps, twin labeling, API errors, and recovery.
