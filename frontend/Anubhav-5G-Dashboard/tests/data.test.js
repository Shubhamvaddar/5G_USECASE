import test from 'node:test';
import assert from 'node:assert/strict';
import { extractRecords, fetchDashboardData, isRecordStale } from '../src/services/api.js';
import { makeTwinRecord } from '../src/services/mockData.js';

const sampleTimestamp = '2026-11-06T08:15:30.000Z';
const apiRecord = {
  id: 'panel-1', timestamp: sampleTimestamp, source: 'real', deviceId: 'PANEL-01',
  measurements: { voltageV: 12.4, currentA: 2.1 },
};

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
}

test('normalizes partial sensor records, calculates power, and filters by explicit source', () => {
  const records = extractRecords({ records: [apiRecord, { ...apiRecord, id: 'unlabeled', source: undefined }] }, 'real');
  assert.equal(records.length, 1);
  assert.equal(records[0].measurements.lightLux, null);
  assert.equal(records[0].measurements.temperatureC, null);
  assert.equal(records[0].measurements.powerW, 26.04);
});

test('marks records stale by timestamp and treats missing timestamps as non-records', () => {
  const now = Date.parse(sampleTimestamp);
  assert.equal(isRecordStale({ timestamp: new Date(now - 61000).toISOString() }, 60000, now), true);
  assert.equal(isRecordStale({ timestamp: new Date(now - 59000).toISOString() }, 60000, now), false);
  assert.equal(isRecordStale({ timestamp: null }, 60000, now), false);
});

test('digital twin outputs explicitly simulated values from real inputs', () => {
  const record = { ...apiRecord, measurements: { lightLux: 95000, temperatureC: 25 } };
  const twin = makeTwinRecord(record);
  assert.equal(twin.source, 'simulated');
  assert.equal(twin.measurements.powerW, 100);
  assert.ok(Math.abs(twin.measurements.voltageV * twin.measurements.currentA - twin.measurements.powerW) < 0.1);
});

test('reports API errors and recovers when the endpoint returns', async () => {
  const previousFetch = globalThis.fetch;
  let unavailable = true;
  globalThis.fetch = async url => {
    const endpoint = String(url);
    if (endpoint.endsWith('/api/panels/real/readings')) {
      return unavailable ? jsonResponse({ error: 'offline' }, 503) : jsonResponse({ records: [apiRecord] });
    }
    if (endpoint.endsWith('/api/panels/simulated/readings')) return jsonResponse({ records: [] });
    if (endpoint.endsWith('/api/health')) return jsonResponse({ status: 'ok' });
    if (endpoint.endsWith('/api/network/status')) return jsonResponse({ labConnected: true, mecConnected: true });
    return jsonResponse({ error: 'not found' }, 404);
  };
  try {
    const failed = await fetchDashboardData('http://api.example.test');
    assert.equal(failed.errors.real, 'HTTP 503');
    assert.equal(failed.reachability, 'reachable');
    unavailable = false;
    const recovered = await fetchDashboardData('http://api.example.test');
    assert.equal(recovered.errors.real, undefined);
    assert.equal(recovered.real[0].source, 'real');
    assert.equal(recovered.simulated[0].source, 'simulated');
  } finally {
    globalThis.fetch = previousFetch;
  }
});
