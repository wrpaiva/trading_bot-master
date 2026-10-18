import os
from datetime import datetime, timezone

import uvicorn

from kronos_service.app import create_app
from kronos_service.candles import DEFAULT_URL, fetch_candles
from kronos_service.forecaster import build_forecast, load_kronos_predictor

INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
MAX_CONTEXT = 512


def _env_int(name, default, minimum, maximum=None):
    raw = os.environ.get(name, str(default))
    bound = f"at least {minimum}" if maximum is None else f"between {minimum} and {maximum}"
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"{name} must be an integer {bound}, got {raw!r}") from None
    if value < minimum or (maximum is not None and value > maximum):
        raise SystemExit(f"{name} must be an integer {bound}, got {raw!r}")
    return value


def main():
    symbol = os.environ.get("KRONOS_SYMBOL", "SHIBUSDT")
    interval = os.environ.get("KRONOS_INTERVAL", "5m")
    lookback = _env_int("KRONOS_LOOKBACK", 400, 1, MAX_CONTEXT)
    pred_len = _env_int("KRONOS_PRED_LEN", 12, 1, lookback)
    sample_count = _env_int("KRONOS_SAMPLE_COUNT", 5, 1)
    refresh_seconds = _env_int("KRONOS_REFRESH_SECONDS", 300, 1)
    port = _env_int("KRONOS_PORT", 8001, 1, 65535)
    device = os.environ.get("KRONOS_DEVICE") or None
    candles_url = os.environ.get("KRONOS_CANDLES_URL", DEFAULT_URL)
    default_vendor = os.path.join(os.path.dirname(__file__), "..", "vendor", "Kronos")
    vendor_path = os.path.abspath(os.environ.get("KRONOS_VENDOR_PATH", default_vendor))

    if interval not in INTERVAL_MINUTES:
        raise SystemExit(f"KRONOS_INTERVAL must be one of {sorted(INTERVAL_MINUTES)}, got {interval!r}")
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
