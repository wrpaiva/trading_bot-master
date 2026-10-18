import pandas as pd
import requests

DEFAULT_URL = "https://data-api.binance.vision/api/v3/klines"
COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]


class CandleError(ValueError):
    pass


def parse_klines(raw):
    if not isinstance(raw, list) or not raw:
        raise CandleError("empty kline response")

    rows = [
        {
            "timestamps": pd.Timestamp(int(k[0]), unit="ms"),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "amount": float(k[7]),
        }
        for k in raw
    ]
    df = pd.DataFrame(rows, columns=COLUMNS).sort_values("timestamps").reset_index(drop=True)

    if df[COLUMNS[1:]].isnull().values.any() or (df["close"] <= 0).any():
        raise CandleError("kline response contains missing or non-positive prices")
    return df


def fetch_candles(symbol, interval, limit, url=DEFAULT_URL, get=requests.get, timeout=10):
    response = get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=timeout)
    response.raise_for_status()
    df = parse_klines(response.json())
    # Binance's last kline is still forming; only closed candles go to the model.
    return df.iloc[:-1].reset_index(drop=True)
