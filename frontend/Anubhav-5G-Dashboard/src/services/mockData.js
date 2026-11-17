const now = Date.now();

// These samples exercise the UI schema only. They are not hardware readings.
export const mockRealRecords = Array.from({ length: 24 }, (_, index) => {
  const timestamp = new Date(now - (23 - index) * 60 * 60 * 1000).toISOString();
  const hour = new Date(timestamp).getHours();
  const daylight = Math.max(0, Math.sin(((hour - 6) / 12) * Math.PI));
  const lightLux = Math.round(95000 * daylight * (0.91 + Math.sin(index * 0.8) * 0.06));
  const temperatureC = Number((21 + daylight * 17 + Math.sin(index * 0.31) * 1.7).toFixed(1));
  const voltageV = Number((lightLux > 0 ? 17.4 - Math.max(0, temperatureC - 25) * 0.025 : 0).toFixed(2));
  const currentA = Number((lightLux > 0 ? (5.2 * daylight * (0.94 + Math.sin(index * 0.42) * 0.04)) : 0).toFixed(2));
  return {
    id: `demo-real-${index}`,
    timestamp,
    source: 'real',
    origin: 'demo',
    deviceId: 'ANUBHAV-PANEL-01',
    measurements: { lightLux, temperatureC, voltageV, currentA, powerW: Number((voltageV * currentA).toFixed(2)) },
  };
});

export function makeTwinRecord(record, index = 0) {
  const input = record?.measurements || {};
  const lux = Number.isFinite(input.lightLux) ? input.lightLux : 0;
  const temp = Number.isFinite(input.temperatureC) ? input.temperatureC : 25;
  const irradianceFactor = Math.min(1.2, Math.max(0, lux / 95000));
  const tempFactor = Math.max(0.72, 1 - Math.max(0, temp - 25) * 0.004);
  const voltage = lux > 0 ? Math.max(0, 17.4 - Math.max(0, temp - 25) * 0.025) : 0;
  const power = Number((100 * irradianceFactor * tempFactor).toFixed(2));
  const current = voltage > 0 ? Number((power / voltage).toFixed(2)) : 0;
  return {
    id: `twin-${record?.id || index}`,
    timestamp: record?.timestamp || new Date(now - index * 60_000).toISOString(),
    source: 'simulated',
    origin: record?.origin || 'model',
    deviceId: 'ANUBHAV-TWIN-01',
    measurements: {
      lightLux: Math.round(lux), temperatureC: Number(temp.toFixed(1)),
      voltageV: Number(voltage.toFixed(2)), currentA: current, powerW: power,
    },
  };
}
