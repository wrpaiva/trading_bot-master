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
