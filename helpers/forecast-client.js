const http = require('http')

const FUTURE_TOLERANCE_MS = 60 * 1000

function fetchJson(url, timeoutMs) {
    return new Promise((resolve, reject) => {
        const req = http.get(url, { timeout: timeoutMs }, (res) => {
            let body = ''
            res.setEncoding('utf8')
            res.on('data', (chunk) => { body += chunk })
            res.on('end', () => {
                if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode}`))
                try {
                    resolve(JSON.parse(body))
                } catch (error) {
                    reject(error)
                }
            })
        })
        req.on('timeout', () => req.destroy(new Error('timeout')))
        req.on('error', reject)
    })
}

function isFresh(forecast, nowMs, maxAgeMs) {
    if (!forecast || typeof forecast.generated_at !== 'string') return false
    const generatedMs = Date.parse(forecast.generated_at)
    if (Number.isNaN(generatedMs)) return false
    return nowMs - generatedMs <= maxAgeMs && generatedMs - nowMs <= FUTURE_TOLERANCE_MS
}

// Polls the Kronos service off the hot path; latest() is a synchronous cache read.
function createForecastClient({ url, intervalMs = 60000, maxAgeMs = 15 * 60000, timeoutMs = 2000, fetch = fetchJson }) {
    let last = null
    let error = null
    let timer = null

    async function poll() {
        try {
            last = await fetch(url, timeoutMs)
            error = null
        } catch (err) {
            error = err.message
        }
    }

    return {
        poll,
        start() {
            poll()
            timer = setInterval(poll, intervalMs)
            timer.unref()
        },
        stop() {
            clearInterval(timer)
        },
        latest(nowMs = Date.now()) {
            return isFresh(last, nowMs, maxAgeMs) ? last : null
        },
        lastError() {
            return error
        },
    }
}

module.exports = { fetchJson, isFresh, createForecastClient }
