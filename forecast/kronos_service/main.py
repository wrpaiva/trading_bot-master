import os
from datetime import datetime, timezone

import uvicorn

from kronos_service.app import create_app
from kronos_service.candles import DEFAULT_URL, fetch_candles
from kronos_service.forecaster import build_forecast, load_kronos_predictor

INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
MAX_CONTEXT = 512


def main():
    symbol = os.environ.get("KRONOS_SYMBOL", "SHIBUSDT")
    interval = os.environ.get("KRONOS_INTERVAL", "5m")
    lookback = int(os.environ.get("KRONOS_LOOKBACK", "400"))
    pred_len = int(os.environ.get("KRONOS_PRED_LEN", "12"))
    sample_count = int(os.environ.get("KRONOS_SAMPLE_COUNT", "5"))
    refresh_seconds = int(os.environ.get("KRONOS_REFRESH_SECONDS", "300"))
    port = int(os.environ.get("KRONOS_PORT", "8001"))
    device = os.environ.get("KRONOS_DEVICE") or None
    candles_url = os.environ.get("KRONOS_CANDLES_URL", DEFAULT_URL)
    default_vendor = os.path.join(os.path.dirname(__file__), "..", "vendor", "Kronos")
    vendor_path = os.path.abspath(os.environ.get("KRONOS_VENDOR_PATH", default_vendor))

    if interval not in INTERVAL_MINUTES:
        raise SystemExit(f"KRONOS_INTERVAL must be one of {sorted(INTERVAL_MINUTES)}, got {interval!r}")
    if not 1 <= lookback <= MAX_CONTEXT:
        raise SystemExit(f"KRONOS_LOOKBACK must be between 1 and {MAX_CONTEXT}, got {lookback}")
    if not os.path.isdir(os.path.join(vendor_path, "model")):
        raise SystemExit(f"Kronos not found at {vendor_path}; run forecast/setup_kronos.sh")

    predictor = load_kronos_predictor(
        vendor_path, "NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base",
        device=device, max_context=MAX_CONTEXT,
    )

    def refresh():
        # +1 because fetch_candles drops the still-forming candle.
        candles = fetch_candles(symbol, interval, lookback + 1, url=candles_url)
        return build_forecast(
            candles, predictor,
            symbol=symbol, interval_minutes=INTERVAL_MINUTES[interval],
            lookback=lookback, pred_len=pred_len, sample_count=sample_count,
            now=datetime.now(timezone.utc), model="Kronos-small",
        )

    uvicorn.run(create_app(refresh, refresh_seconds), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
