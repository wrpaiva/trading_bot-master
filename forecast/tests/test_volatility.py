import pandas as pd
import pytest

from kronos_service.volatility import range_pct, vol_ratio


def test_range_pct_mean_of_relative_ranges():
    df = pd.DataFrame({"high": [102.0, 11.0], "low": [98.0, 9.0], "close": [100.0, 10.0]})
    # (4/100 + 2/10) / 2 * 100 = 12.0
    assert range_pct(df) == pytest.approx(12.0)


def test_range_pct_uses_absolute_spread():
    # Kronos samples OHLC independently and can emit high < low.
    df = pd.DataFrame({"high": [98.0], "low": [102.0], "close": [100.0]})
    assert range_pct(df) == pytest.approx(4.0)


def test_range_pct_rejects_empty_and_non_positive_close():
    with pytest.raises(ValueError):
        range_pct(pd.DataFrame({"high": [], "low": [], "close": []}))
    with pytest.raises(ValueError):
        range_pct(pd.DataFrame({"high": [1.0], "low": [1.0], "close": [-1.0]}))


def test_vol_ratio():
    assert vol_ratio(2.0, 1.0) == pytest.approx(2.0)
    assert vol_ratio(2.0, 0.0) is None
