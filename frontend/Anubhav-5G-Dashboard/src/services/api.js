import { makeTwinRecord, mockRealRecords } from './mockData.js';

const DEFAULTS = {
  real: '/api/panels/real/readings',
  simulated: '/api/panels/simulated/readings',
  health: '/api/health',
  network: '/api/network/status',
};
const env = import.meta.env || {};
const trimSlash = (value = '') => value.replace(/\/+$/, '');
export const getInitialApiBase = () => trimSlash(env.VITE_API_BASE_URL || '');
export const pollIntervalMs = Number(env.VITE_POLL_INTERVAL_MS || 10000);
export const staleAfterMs = Number(env.VITE_STALE_AFTER_MS || 60000);
export function isRecordStale(record, thresholdMs = staleAfterMs, now = Date.now()) {
  const ts = record?.timestamp;
  if (!ts) return false;
  const parsed = (typeof ts === 'string' && !ts.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(ts)) ? Date.parse(ts + 'Z') : Date.parse(ts);
  if (!Number.isFinite(parsed)) return false;
  return now - parsed > thresholdMs;
}

const fieldAliases = {
  lightLux: ['lightLux', 'light_lux', 'lightIntensity', 'light_intensity', 'lux'],
  temperatureC: ['temperatureC', 'temperature_c', 'tempC', 'temp_c', 'temperature'],
  voltageV: ['voltageV', 'voltage_v', 'voltage'],
  currentA: ['currentA', 'current_a', 'current'],
  powerW: ['powerW', 'power_w', 'power'],
};
const pick = (object, keys) => {
  for (const key of keys) if (object?.[key] !== undefined && object?.[key] !== null && object?.[key] !== '') return object[key];
  return null;
};
const numberOrNull = value => value === null ? null : (Number.isFinite(Number(value)) ? Number(value) : null);

export function normalizeRecord(record) {
  const raw = record?.measurements || record?.values || record?.data || record || {};
  const measurements = {};
  for (const [key, aliases] of Object.entries(fieldAliases)) measurements[key] = numberOrNull(pick(raw, aliases));
  if (measurements.powerW === null && measurements.voltageV !== null && measurements.currentA !== null) {
    measurements.powerW = Number((measurements.voltageV * measurements.currentA).toFixed(3));
  }
  const source = String(record?.source || record?.panelSource || '').toLowerCase();
  return {
    id: String(record?.id ?? record?.recordId ?? `${source}-${record?.timestamp || record?.time || Math.random()}`),
    timestamp: record?.timestamp || record?.time || record?.createdAt || null,
    source,
    origin: record?.origin || (record?.demo ? 'demo' : 'api'),
    deviceId: record?.deviceId || record?.device_id || record?.panelId || 'Panel',
    measurements,
  };
}

export function extractRecords(payload, fallbackSource) {
  const rows = Array.isArray(payload) ? payload : payload?.records ?? payload?.data ?? payload?.readings ?? [];
  if (!Array.isArray(rows)) return [];
  return rows.map(normalizeRecord).filter(record => record.source === fallbackSource);
}

async function fetchJSON(url, timeoutMs = 7000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error([`HTTP ${response.status}`, response.statusText].filter(Boolean).join(' '));
    return await response.json();
  } finally { clearTimeout(timer); }
}
function endpoint(base, envKey, fallback) {
  const path = env[envKey] || fallback;
  return `${trimSlash(base)}/${path.replace(/^\/+/, '')}`;
}

export async function fetchDashboardData(base = getInitialApiBase()) {
  if (!base) {
    const real = mockRealRecords;
    return {
      demo: true,
      real,
      simulated: real.map(makeTwinRecord),
      errors: {},
      health: null,
      network: null,
      reachability: 'demo',
    };
  }

  const requests = {
    real: fetchJSON(endpoint(base, 'VITE_API_REAL_ENDPOINT', DEFAULTS.real)).then(data => extractRecords(data, 'real')),
    simulated: fetchJSON(endpoint(base, 'VITE_API_SIM_ENDPOINT', DEFAULTS.simulated)).then(data => extractRecords(data, 'simulated')),
    health: fetchJSON(endpoint(base, 'VITE_API_HEALTH_ENDPOINT', DEFAULTS.health)),
    network: fetchJSON(endpoint(base, 'VITE_API_NETWORK_ENDPOINT', DEFAULTS.network)),
  };
  const entries = await Promise.all(Object.entries(requests).map(async ([key, promise]) => {
    try { return [key, { value: await promise, error: null }]; }
    catch (error) { return [key, { value: null, error: error.name === 'AbortError' ? 'Request timed out' : error.message }]; }
  }));
  const result = Object.fromEntries(entries);
  const real = result.real.value || [];
  const apiSimulated = result.simulated.value || [];
  const simulated = apiSimulated.length ? apiSimulated : real.map(makeTwinRecord);
  return {
    demo: false,
    real,
    simulated,
    errors: Object.fromEntries(entries.filter(([, item]) => item.error).map(([key, item]) => [key, item.error])),
    health: result.health.value,
    network: result.network.value,
    reachability: result.health.error ? 'unreachable' : 'reachable',
  };
}
