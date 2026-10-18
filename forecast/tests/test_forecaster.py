from datetime import datetime, timezone

import pandas as pd
import pytest

from kronos_service.forecaster import build_forecast


def make_candles(n, close=1.0):
    ts = pd.date_range("2026-10-18 00:00", periods=n, freq="5min")
    return pd.DataFrame({
        "timestamps": ts,
        "open": close,
        "high": close * 1.005,
        "low": close * 0.995,
        "close": close,
        "volume": 100.0,
        "amount": 100.0,
    })


class FakePredictor:
    def __init__(self):
        self.kwargs = None

    def predict(self, **kwargs):
        self.kwargs = kwargs
        n = kwargs["pred_len"]
        return pd.DataFrame({
            "open": [2.0] * n,
            "high": [2.04] * n,
            "low": [1.96] * n,
            "close": [2.0] * n,
            "volume": [1.0] * n,
            "amount": [1.0] * n,
        }, index=kwargs["y_timestamp"])


NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def run(candles, predictor, lookback=10, pred_len=3):
    return build_forecast(
        candles, predictor,
        symbol="SHIBUSDT", interval_minutes=5, lookback=lookback, pred_len=pred_len,
        sample_count=2, now=NOW, model="Kronos-small",
    )


def test_build_forecast_computes_ratio_and_contract_fields():
    predictor = FakePredictor()
    result = run(make_candles(15), predictor)

    assert result["symbol"] == "SHIBUSDT"
    assert result["interval_minutes"] == 5
    assert result["horizon_minutes"] == 15
    assert result["generated_at"] == "2026-10-18T12:00:00Z"
    assert result["historical_range_pct"] == pytest.approx(1.0)
    assert result["predicted_range_pct"] == pytest.approx(4.0)
    assert result["vol_ratio"] == pytest.approx(4.0)
    assert result["last_close"] == pytest.approx(1.0)
    assert result["predicted_close"] == pytest.approx(2.0)
    assert result["model"] == "Kronos-small"


def test_build_forecast_feeds_last_lookback_candles_and_future_timestamps():
    predictor = FakePredictor()
    candles = make_candles(15)
    run(candles, predictor)

    kw = predictor.kwargs
    assert len(kw["df"]) == 10
    assert list(kw["df"].columns) == ["open", "high", "low", "close", "volume", "amount"]
    assert kw["x_timestamp"].iloc[-1] == candles["timestamps"].iloc[-1]
    assert kw["y_timestamp"].iloc[0] == candles["timestamps"].iloc[-1] + pd.Timedelta(minutes=5)
    assert len(kw["y_timestamp"]) == 3
    assert kw["sample_count"] == 2
    assert kw["verbose"] is False


def test_rejects_short_history():
    with pytest.raises(ValueError, match="need 10 candles, got 4"):
        run(make_candles(4), FakePredictor())
