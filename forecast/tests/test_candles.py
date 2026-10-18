import pandas as pd
import pytest

from kronos_service.candles import COLUMNS, CandleError, fetch_candles, parse_klines


def kline(open_ms, o, h, l, c, v, quote_v):
    # Binance kline layout: [openTime, open, high, low, close, volume, closeTime, quoteVolume, trades, ...]
    return [open_ms, str(o), str(h), str(l), str(c), str(v), open_ms + 299999, str(quote_v), 10, "0", "0", "0"]


RAW = [
    kline(1_700_000_300_000, 2, 3, 1, 2.5, 100, 250),
    kline(1_700_000_000_000, 1, 2, 0.5, 1.5, 10, 15),
]


def test_parse_klines_maps_columns_and_sorts():
    df = parse_klines(RAW)
    assert list(df.columns) == COLUMNS
    assert df["timestamps"].iloc[0] == pd.Timestamp(1_700_000_000_000, unit="ms")
    assert df["close"].tolist() == [1.5, 2.5]
    assert df["amount"].tolist() == [15.0, 250.0]


def test_parse_klines_rejects_empty():
    with pytest.raises(CandleError):
        parse_klines([])


def test_parse_klines_rejects_non_positive_close():
    with pytest.raises(CandleError):
        parse_klines([kline(1_700_000_000_000, 1, 2, 0.5, 0, 10, 15)])


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status != 200:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.payload


def test_fetch_candles_drops_in_progress_candle_and_passes_params():
    calls = {}

    def fake_get(url, params, timeout):
        calls.update(url=url, params=params, timeout=timeout)
        return FakeResponse(RAW)

    df = fetch_candles("SHIBUSDT", "5m", 2, url="http://x/klines", get=fake_get)
    assert calls["params"] == {"symbol": "SHIBUSDT", "interval": "5m", "limit": 2}
    assert len(df) == 1
    assert df["close"].iloc[0] == 1.5


def test_fetch_candles_propagates_http_error():
    with pytest.raises(RuntimeError, match="HTTP 451"):
        fetch_candles("SHIBUSDT", "5m", 2, get=lambda url, params, timeout: FakeResponse([], status=451))
