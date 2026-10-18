import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

CHART_HTML = (Path(__file__).parent / "chart.html").read_text(encoding="utf-8")


class ForecastCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._forecast = None
        self._last_error = None

    def refresh(self, refresh_fn):
        try:
            result = refresh_fn()
        except Exception as error:  # keep serving the last good forecast
            with self._lock:
                self._last_error = f"{type(error).__name__}: {error}"
            return False
        with self._lock:
            self._forecast = result
            self._last_error = None
        return True

    def snapshot(self):
        with self._lock:
            return {"forecast": self._forecast, "last_error": self._last_error}


def create_app(refresh_fn, interval_seconds, start_background=True):
    cache = ForecastCache()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            cache.refresh(refresh_fn)
            stop.wait(interval_seconds)

    @asynccontextmanager
    async def lifespan(_app):
        if start_background:
            threading.Thread(target=loop, name="kronos-refresh", daemon=True).start()
        yield
        stop.set()

    app = FastAPI(title="kronos-forecast", lifespan=lifespan)
    app.state.cache = cache

    def not_ready(snap):
        return JSONResponse(status_code=503, content={"error": snap["last_error"] or "forecast not ready"})

    @app.get("/forecast")
    def get_forecast():
        snap = cache.snapshot()
        if snap["forecast"] is None:
            return not_ready(snap)
        # The candle series is only for /candles; keep the bot's payload small.
        return {key: value for key, value in snap["forecast"].items() if key != "series"}

    @app.get("/candles")
    def get_candles():
        snap = cache.snapshot()
        forecast = snap["forecast"]
        if forecast is None:
            return not_ready(snap)
        return {
            "symbol": forecast["symbol"],
            "generated_at": forecast["generated_at"],
            "interval_minutes": forecast["interval_minutes"],
            **forecast.get("series", {"history": [], "predicted": []}),
        }

    @app.get("/chart", response_class=HTMLResponse)
    def chart():
        return CHART_HTML

    @app.get("/health")
    def health():
        snap = cache.snapshot()
        return {"ready": snap["forecast"] is not None, "last_error": snap["last_error"]}

    return app
