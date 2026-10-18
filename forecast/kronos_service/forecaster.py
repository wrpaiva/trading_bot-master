import math
import sys

import pandas as pd

from kronos_service.volatility import range_pct, vol_ratio

FEATURES = ["open", "high", "low", "close", "volume", "amount"]
PRICE_COLUMNS = ["open", "high", "low", "close"]


def build_forecast(candles, predictor, *, symbol, interval_minutes, lookback, pred_len, sample_count, now, model):
    if len(candles) < lookback:
        raise ValueError(f"need {lookback} candles, got {len(candles)}")

    history = candles.tail(lookback).reset_index(drop=True)
    x_timestamp = history["timestamps"]
    step = pd.Timedelta(minutes=interval_minutes)
    y_timestamp = pd.Series([x_timestamp.iloc[-1] + step * (i + 1) for i in range(pred_len)])

    # Kronos z-scores each column with an absolute epsilon (x_std + 1e-5). For sub-cent
    # prices (SHIB ~5e-6) that epsilon swamps the real std, so feed unit-scale prices
    # (divided by the last close) and scale the prediction back afterwards.
    last_close = float(history["close"].iloc[-1])
    scaled = history[FEATURES].copy()
    scaled[PRICE_COLUMNS] = scaled[PRICE_COLUMNS] / last_close

    predicted = predictor.predict(
        df=scaled,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=pred_len,
        T=1.0,
        top_p=0.9,
        sample_count=sample_count,
        verbose=False,
    )

    predicted = predicted.copy()
    predicted[PRICE_COLUMNS] = predicted[PRICE_COLUMNS] * last_close

    historical_range = range_pct(history.tail(pred_len))
    predicted_range = range_pct(predicted)

    result = {
        "symbol": symbol,
        "interval_minutes": interval_minutes,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizon_minutes": interval_minutes * pred_len,
        "predicted_range_pct": predicted_range,
        "historical_range_pct": historical_range,
        "vol_ratio": vol_ratio(predicted_range, historical_range),
        "last_close": last_close,
        "predicted_close": float(predicted["close"].iloc[-1]),
        "model": model,
    }

    # NaN/inf cannot be serialized as JSON; reject so the cache keeps the last good forecast.
    # vol_ratio may legitimately be None (no historical range).
    for key, value in result.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"non-finite forecast value for {key}: {value}")
    return result


def load_kronos_predictor(vendor_path, model_id, tokenizer_id, device=None, max_context=512):
    if vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)
    from model import Kronos, KronosPredictor, KronosTokenizer

    tokenizer = KronosTokenizer.from_pretrained(tokenizer_id)
    model = Kronos.from_pretrained(model_id)
    return KronosPredictor(model, tokenizer, device=device, max_context=max_context)
