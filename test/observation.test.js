const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { suggestThreshold, buildObservation, appendObservation } = require('../helpers/observation')

const forecast = {
    generated_at: '2026-10-18T11:55:00Z',
    vol_ratio: 1.5,
    predicted_range_pct: 0.6,
    historical_range_pct: 0.4,
}

// Test 1: threshold scales with vol_ratio, clamped to [0.5, 2].
assert.strictEqual(suggestThreshold('0.50', forecast), 0.75, 'scaled threshold')
assert.strictEqual(suggestThreshold(0.5, { vol_ratio: 10 }), 1, 'clamped high')
assert.strictEqual(suggestThreshold(0.5, { vol_ratio: 0.1 }), 0.25, 'clamped low')

// Test 2: no usable forecast falls back to the base threshold.
assert.strictEqual(suggestThreshold('0.50', null), 0.5, 'no forecast')
assert.strictEqual(suggestThreshold(0.5, { vol_ratio: null }), 0.5, 'null ratio')
assert.strictEqual(suggestThreshold(0.5, { vol_ratio: 0 }), 0.5, 'zero ratio')
assert.strictEqual(suggestThreshold(0.5, { vol_ratio: NaN }), 0.5, 'NaN ratio')

// Test 3: observation record with and without forecast.
const nowMs = Date.parse('2026-10-18T12:00:00Z')
assert.deepStrictEqual(
    buildObservation({ nowMs, block: 123, priceDifference: '-0.62', baseThreshold: '0.50', forecast, forecastStatus: 'ok' }),
    {
        observed_at: '2026-10-18T12:00:00.000Z',
        block: 123,
        price_difference_pct: -0.62,
        base_threshold_pct: 0.5,
        suggested_threshold_pct: 0.75,
        forecast_generated_at: '2026-10-18T11:55:00Z',
        vol_ratio: 1.5,
        predicted_range_pct: 0.6,
        historical_range_pct: 0.4,
        forecast_status: 'ok',
    },
    'observation with forecast'
)
const bare = buildObservation({ nowMs, block: 1, priceDifference: '0.10', baseThreshold: '0.50', forecast: null, forecastStatus: 'stale' })
assert.strictEqual(bare.suggested_threshold_pct, 0.5, 'bare suggested threshold')
assert.strictEqual(bare.forecast_generated_at, null, 'bare generated_at')
assert.strictEqual(bare.vol_ratio, null, 'bare vol_ratio')
assert.strictEqual(bare.forecast_status, 'stale', 'bare status')

// Test 4: append creates the directory and writes one JSON line per call.
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'obs-'))
const file = path.join(dir, 'nested', 'observations.jsonl')
appendObservation(file, { a: 1 })
appendObservation(file, { a: 2 })
assert.deepStrictEqual(
    fs.readFileSync(file, 'utf8').trim().split('\n').map((line) => JSON.parse(line)),
    [{ a: 1 }, { a: 2 }],
    'jsonl lines'
)
fs.rmSync(dir, { recursive: true, force: true })

console.log('All observation tests passed')
