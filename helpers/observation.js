const fs = require('fs')
const path = require('path')

const MIN_FACTOR = 0.5
const MAX_FACTOR = 2

function suggestThreshold(base, forecast) {
    const baseThreshold = Number(base)
    const ratio = forecast ? forecast.vol_ratio : null
    if (typeof ratio !== 'number' || !Number.isFinite(ratio) || ratio <= 0) return baseThreshold
    const factor = Math.min(MAX_FACTOR, Math.max(MIN_FACTOR, ratio))
    return Number((baseThreshold * factor).toFixed(4))
}

function buildObservation({ nowMs, block, priceDifference, baseThreshold, forecast }) {
    return {
        observed_at: new Date(nowMs).toISOString(),
        block,
        price_difference_pct: Number(priceDifference),
        base_threshold_pct: Number(baseThreshold),
        suggested_threshold_pct: suggestThreshold(baseThreshold, forecast),
        forecast_generated_at: forecast ? forecast.generated_at : null,
        vol_ratio: forecast ? forecast.vol_ratio : null,
        predicted_range_pct: forecast ? forecast.predicted_range_pct : null,
        historical_range_pct: forecast ? forecast.historical_range_pct : null,
    }
}

function appendObservation(filePath, record) {
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    fs.appendFileSync(filePath, JSON.stringify(record) + '\n')
}

module.exports = { suggestThreshold, buildObservation, appendObservation }
