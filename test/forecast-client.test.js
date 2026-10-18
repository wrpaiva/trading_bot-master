const assert = require('assert')
const http = require('http')
const { fetchJson, isFresh, createForecastClient } = require('../helpers/forecast-client')

const NOW = Date.parse('2026-10-18T12:00:00Z')
const MIN = 60 * 1000
const forecastAt = (iso) => ({ generated_at: iso, vol_ratio: 1.2 })

function listen(handler) {
    return new Promise((resolve) => {
        const server = http.createServer(handler).listen(0, '127.0.0.1', () => {
            resolve({ server, url: `http://127.0.0.1:${server.address().port}/forecast` })
        })
    })
}

async function run() {
    // Test 1: freshness window.
    assert.strictEqual(isFresh(forecastAt('2026-10-18T11:50:00Z'), NOW, 15 * MIN), true, 'fresh forecast')
    assert.strictEqual(isFresh(forecastAt('2026-10-18T11:40:00Z'), NOW, 15 * MIN), false, 'stale forecast')
    assert.strictEqual(isFresh(forecastAt('2026-10-18T12:05:00Z'), NOW, 15 * MIN), false, 'forecast from the future')
    assert.strictEqual(isFresh(forecastAt('not a date'), NOW, 15 * MIN), false, 'invalid timestamp')
    assert.strictEqual(isFresh(null, NOW, 15 * MIN), false, 'missing forecast')

    // Test 2: fetchJson happy path.
    const ok = await listen((req, res) => {
        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify(forecastAt('2026-10-18T11:59:00Z')))
    })
    assert.deepStrictEqual(await fetchJson(ok.url, 1000), forecastAt('2026-10-18T11:59:00Z'), 'fetchJson 200')

    // Test 3: client caches the last good forecast and survives a later failure.
    let calls = 0
    const flaky = createForecastClient({
        url: 'unused',
        fetch: async () => {
            calls += 1
            if (calls === 1) return forecastAt('2026-10-18T11:59:00Z')
            throw new Error('ECONNREFUSED')
        },
    })
    await flaky.poll()
    await flaky.poll()
    assert.deepStrictEqual(flaky.latest(NOW), forecastAt('2026-10-18T11:59:00Z'), 'keeps last good forecast')
    assert.strictEqual(flaky.lastError(), 'ECONNREFUSED', 'records last error')
    assert.strictEqual(flaky.latest(NOW + 30 * MIN), null, 'cached forecast expires')
    ok.server.close()

    // Test 4: non-200 rejects.
    const failing = await listen((req, res) => {
        res.writeHead(503)
        res.end('{"error":"forecast not ready"}')
    })
    await assert.rejects(fetchJson(failing.url, 1000), /HTTP 503/, 'fetchJson 503')
    failing.server.close()

    // Test 5: timeout rejects instead of hanging.
    const slow = await listen(() => { /* never responds */ })
    await assert.rejects(fetchJson(slow.url, 100), /timeout/, 'fetchJson timeout')
    slow.server.close()

    // Test 6: refused connection rejects; client with nothing cached returns null.
    await assert.rejects(fetchJson('http://127.0.0.1:1/forecast', 500), 'fetchJson refused')
    const down = createForecastClient({ url: 'http://127.0.0.1:1/forecast', timeoutMs: 500 })
    await down.poll()
    assert.strictEqual(down.latest(NOW), null, 'no forecast when service is down')

    console.log('All forecast-client tests passed')
}

run().catch((error) => {
    console.error(error)
    process.exit(1)
})
