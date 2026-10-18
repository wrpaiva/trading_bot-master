import sys

import pandas as pd

from kronos_service.volatility import range_pct, vol_ratio

FEATURES = ["open", "high", "low", "close", "volume", "amount"]


def build_forecast(candles, predictor, *, symbol, interval_minutes, lookback, pred_len, sample_count, now, model):
    if len(candles) < lookback:
        raise ValueError(f"need {lookback} candles, got {len(candles)}")

    history = candles.tail(lookback).reset_index(drop=True)
    x_timestamp = history["timestamps"]
    step = pd.Timedelta(minutes=interval_minutes)
    y_timestamp = pd.Series([x_timestamp.iloc[-1] + step * (i + 1) for i in range(pred_len)])

    predicted = predictor.predict(
        df=history[FEATURES],
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=pred_len,
        T=1.0,
        top_p=0.9,
        sample_count=sample_count,
        verbose=False,
    )

    historical_range = range_pct(history.tail(pred_len))
    predicted_range = range_pct(predicted)

    return {
        "symbol": symbol,
        "interval_minutes": interval_minutes,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizon_minutes": interval_minutes * pred_len,
        "predicted_range_pct": predicted_range,
        "historical_range_pct": historical_range,
        "vol_ratio": vol_ratio(predicted_range, historical_range),
        "last_close": float(history["close"].iloc[-1]),
        "predicted_close": float(predicted["close"].iloc[-1]),
        "model": model,
    }


def load_kronos_predictor(vendor_path, model_id, tokenizer_id, device=None, max_context=512):
    if vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)
    from model import Kronos, KronosPredictor, KronosTokenizer

    tokenizer = KronosTokenizer.from_pretrained(tokenizer_id)
    model = Kronos.from_pretrained(model_id)
    return KronosPredictor(model, tokenizer, device=device, max_context=max_context)
