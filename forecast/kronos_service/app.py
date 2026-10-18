import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse


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

    @app.get("/forecast")
    def get_forecast():
        snap = cache.snapshot()
        if snap["forecast"] is None:
            return JSONResponse(status_code=503, content={"error": snap["last_error"] or "forecast not ready"})
        return snap["forecast"]

    @app.get("/health")
    def health():
        snap = cache.snapshot()
        return {"ready": snap["forecast"] is not None, "last_error": snap["last_error"]}

    return app
