import time

from fastapi.testclient import TestClient

from kronos_service.app import create_app

FORECAST = {"symbol": "SHIBUSDT", "generated_at": "2026-10-18T12:00:00Z", "vol_ratio": 1.2}


def boom():
    raise RuntimeError("binance down")


def make_client():
    app = create_app(lambda: FORECAST, interval_seconds=3600, start_background=False)
    return app, TestClient(app)


def test_forecast_is_503_before_first_refresh():
    _, client = make_client()
    response = client.get("/forecast")
    assert response.status_code == 503
    assert response.json() == {"error": "forecast not ready"}
    assert client.get("/health").json() == {"ready": False, "last_error": None}


def test_forecast_served_after_refresh():
    app, client = make_client()
    assert app.state.cache.refresh(lambda: FORECAST) is True
    response = client.get("/forecast")
    assert response.status_code == 200
    assert response.json() == FORECAST
    assert client.get("/health").json() == {"ready": True, "last_error": None}


def test_failed_refresh_keeps_last_forecast():
    app, client = make_client()
    app.state.cache.refresh(lambda: FORECAST)
    assert app.state.cache.refresh(boom) is False

    assert client.get("/forecast").json() == FORECAST
    assert client.get("/health").json() == {"ready": True, "last_error": "RuntimeError: binance down"}


def test_failed_first_refresh_reports_error_in_503():
    app, client = make_client()
    app.state.cache.refresh(boom)
    response = client.get("/forecast")
    assert response.status_code == 503
    assert response.json() == {"error": "RuntimeError: binance down"}


def test_background_thread_runs_first_refresh_on_startup():
    calls = []
    app = create_app(lambda: calls.append(1) or FORECAST, interval_seconds=3600)
    with TestClient(app) as client:
        for _ in range(50):
            if client.get("/forecast").status_code == 200:
                break
            time.sleep(0.02)
        assert client.get("/forecast").json() == FORECAST
    assert len(calls) == 1


SERIES = {"history": [["2026-10-18T11:55:00Z", 1.0, 1.1, 0.9, 1.05]], "predicted": [["2026-10-18T12:00:00Z", 1.05, 1.1, 1.0, 1.08]]}
WITH_SERIES = {**FORECAST, "interval_minutes": 5, "series": SERIES}


def test_forecast_omits_series_and_candles_serves_it():
    app, client = make_client()
    app.state.cache.refresh(lambda: WITH_SERIES)

    assert "series" not in client.get("/forecast").json()
    candles = client.get("/candles")
    assert candles.status_code == 200
    assert candles.json() == {"symbol": "SHIBUSDT", "generated_at": "2026-10-18T12:00:00Z", "interval_minutes": 5, **SERIES}


def test_candles_is_503_before_first_refresh():
    _, client = make_client()
    response = client.get("/candles")
    assert response.status_code == 503
    assert response.json() == {"error": "forecast not ready"}


def test_chart_page_is_served_as_html():
    _, client = make_client()
    response = client.get("/chart")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/candles" in response.text
