def range_pct(df):
    if df.empty:
        raise ValueError("cannot compute range of empty candles")
    close = df["close"].astype(float)
    if (close <= 0).any():
        raise ValueError("close must be positive")
    # abs(): Kronos samples each column, so predicted high can fall below low.
    return float(((df["high"] - df["low"]).abs() / close).mean() * 100)


def vol_ratio(predicted, historical):
    if historical <= 0:
        return None
    return predicted / historical
