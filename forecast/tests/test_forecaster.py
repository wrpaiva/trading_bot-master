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


class RelativeDoublingPredictor:
    """Returns the last input close x2 (scale-relative), so it is correct at any price scale."""

    def __init__(self):
        self.kwargs = None

    def predict(self, **kwargs):
        self.kwargs = kwargs
        n = kwargs["pred_len"]
        last = kwargs["df"]["close"].iloc[-1]
        return pd.DataFrame({
            "open": [2 * last] * n,
            "high": [2 * last * 1.02] * n,
            "low": [2 * last * 0.98] * n,
            "close": [2 * last] * n,
            "volume": [1.0] * n,
            "amount": [1.0] * n,
        }, index=kwargs["y_timestamp"])


def test_prices_are_rescaled_to_unit_scale_before_predict():
    # Kronos z-scores with an absolute 1e-5 std epsilon, so tiny prices must be rescaled.
    predictor = RelativeDoublingPredictor()
    run(make_candles(15, close=5e-6), predictor)

    df = predictor.kwargs["df"]
    assert df["close"].iloc[-1] == pytest.approx(1.0)
    assert df["high"].iloc[-1] == pytest.approx(1.005)
    assert (df["volume"] == 100.0).all()
    assert (df["amount"] == 100.0).all()


def test_prediction_is_scaled_back_and_matches_unit_price_case():
    tiny = run(make_candles(15, close=5e-6), RelativeDoublingPredictor())
    unit = run(make_candles(15, close=1.0), RelativeDoublingPredictor())

    assert tiny["last_close"] == pytest.approx(5e-6)
    assert tiny["predicted_close"] == pytest.approx(1e-5)
    assert tiny["vol_ratio"] == pytest.approx(unit["vol_ratio"])
    assert tiny["predicted_range_pct"] == pytest.approx(unit["predicted_range_pct"])


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_build_forecast_rejects_non_finite_output(bad):
    class BadPredictor(FakePredictor):
        def predict(self, **kwargs):
            df = super().predict(**kwargs)
            df["high"] = bad
            return df

    with pytest.raises(ValueError, match="non-finite"):
        run(make_candles(15), BadPredictor())


def test_series_holds_recent_history_and_prediction_in_original_units():
    candles = make_candles(150, close=5e-6)
    result = build_forecast(
        candles, FakePredictor(),
        symbol="SHIBUSDT", interval_minutes=5, lookback=120, pred_len=3,
        sample_count=2, now=NOW, model="Kronos-small",
    )
    series = result["series"]

    assert len(series["history"]) == 96
    assert len(series["predicted"]) == 3
    assert series["history"][-1] == ["2026-10-18T12:25:00Z", 5e-6, pytest.approx(5.025e-6), pytest.approx(4.975e-6), 5e-6]
    assert series["predicted"][0][0] == "2026-10-18T12:30:00Z"
    # FakePredictor returns unit-scale 2.0 for a unit-scale input, i.e. 2 × last close.
    assert series["predicted"][0][4] == pytest.approx(1e-5)


def test_series_history_is_capped_by_lookback():
    result = run(make_candles(15), FakePredictor())
    assert len(result["series"]["history"]) == 10
