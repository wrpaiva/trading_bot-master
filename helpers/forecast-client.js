const http = require('http')

const FUTURE_TOLERANCE_MS = 60 * 1000

function fetchJson(url, timeoutMs) {
    return new Promise((resolve, reject) => {
        let settled = false
        const done = (fn, value) => {
            if (settled) return
            settled = true
            clearTimeout(deadline)
            fn(value)
        }
        const deadline = setTimeout(() => req.destroy(new Error('timeout')), timeoutMs)

        const req = http.get(url, { timeout: timeoutMs }, (res) => {
            let body = ''
            res.setEncoding('utf8')
            res.on('data', (chunk) => { body += chunk })
            res.on('error', (err) => done(reject, err))
            res.on('aborted', () => done(reject, new Error('response aborted')))
            res.on('close', () => {
                if (!settled) done(reject, new Error('response closed before end'))
            })
            res.on('end', () => {
                if (settled) return
                if (res.statusCode !== 200) return done(reject, new Error(`HTTP ${res.statusCode}`))
                try {
                    done(resolve, JSON.parse(body))
                } catch (error) {
                    done(reject, error)
                }
            })
        })
        req.on('timeout', () => req.destroy(new Error('timeout')))
        req.on('error', (err) => done(reject, err))
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
    let inFlight = false

    async function poll() {
        if (inFlight) return
        inFlight = true
        try {
            last = await fetch(url, timeoutMs)
            error = null
        } catch (err) {
            error = (err && err.message) || String(err)
        } finally {
            inFlight = false
        }
    }

    return {
        poll,
        start() {
            if (timer) return
            poll()
            timer = setInterval(poll, intervalMs)
            timer.unref()
        },
        stop() {
            clearInterval(timer)
            timer = null
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
