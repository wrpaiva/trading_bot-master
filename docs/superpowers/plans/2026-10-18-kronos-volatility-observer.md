# Kronos Volatility Observer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rodar o Kronos-small num serviço Python separado que prevê a volatilidade de curto prazo de SHIBUSDT e fazer o `bot.js` registrar essa previsão ao lado de cada spread observado — sem alterar nenhuma decisão de trade.

**Architecture:** `forecast/` é um pacote Python (`kronos_service`) com quatro módulos puros/testáveis (candles, volatility, forecaster, app) e um `main.py` que liga tudo ao Kronos real e sobe um FastAPI em `127.0.0.1:8001`. Uma thread em segundo plano refaz a previsão a cada N segundos e guarda a última em cache. No Node, `helpers/forecast-client.js` faz polling desse endpoint fora do caminho crítico e `helpers/observation.js` calcula o threshold sugerido e grava `logs/observations.jsonl`; `bot.js` só chama `logObservation()` dentro de `checkPrice()`.

**Tech Stack:** Python 3.10+ (testado em 3.12), PyTorch ≥ 2.0, pandas, FastAPI, uvicorn, requests, pytest; Kronos (`shiyu-coder/Kronos` @ `67b630e67f6a18c9e9be918d9b4337c960db1e9a`, MIT); Node.js (compatível com 16.14.2 — sem `fetch` global), `http` nativo, `assert` nativo.

**Spec:** `docs/superpowers/specs/2026-10-18-kronos-volatility-observer-design.md`

## Global Constraints

- Fase 1 é **só observação**: `determineDirection()` continua usando `PRICE_DIFFERENCE` do `.env`. Nenhuma linha de decisão de trade muda.
- O bot nunca espera o serviço dentro do handler de `Swap`: a leitura é síncrona sobre um cache (`forecastClient.latest()`).
- Código Node não pode usar `fetch` global (Node 16.14.2 é a versão recomendada no README). Use o módulo `http`.
- `FORECAST_URL` vazio ou ausente ⇒ integração desligada; o bot se comporta exatamente como hoje (só ganha a linha de log "Forecast: disabled").
- Kronos é vendorizado por clone em `forecast/vendor/Kronos` no commit `67b630e67f6a18c9e9be918d9b4337c960db1e9a`; o diretório fica no `.gitignore`.
- Modelo: `NeoQuasar/Kronos-small` + `NeoQuasar/Kronos-Tokenizer-base`, `max_context=512`. `KRONOS_LOOKBACK` ≤ 512.
- Candles: endpoint público `https://data-api.binance.vision/api/v3/klines` (sem chave), sobrescrevível por `KRONOS_CANDLES_URL`. O último candle retornado está em formação e é descartado.
- `suggested_threshold = PRICE_DIFFERENCE × clamp(vol_ratio, 0.5, 2.0)`, arredondado a 4 casas.
- Previsão com `generated_at` mais velho que `FORECAST_MAX_AGE_MIN` minutos (padrão 15) é tratada como ausente.
- Serviço escuta só em `127.0.0.1:8001` (porta 5000 é o Express, 7545 é o Ganache).

## Review Focus

1. **Serviço Kronos fora do ar quando o bot sobe ou cai no meio** — o bot deve seguir monitorando com threshold fixo, logando "unavailable", sem exceção não tratada. Teste: `test/forecast-client.test.js` (conexão recusada, 500, timeout).
2. **Previsão velha no cache** (serviço travou mas o último JSON continua lá) — `latest()` deve retornar `null`. Teste: `test/forecast-client.test.js` (stale e `generated_at` no futuro).
3. **Kronos prevendo `high < low`** (o modelo amostra cada coluna e não garante consistência OHLC) — `range_pct` usa valor absoluto e não pode gerar volatilidade negativa. Teste: `forecast/tests/test_volatility.py::test_range_pct_uses_absolute_spread`.
4. **Menos candles que o lookback** (símbolo novo, `limit` errado, API devolvendo poucos) — o refresh falha com mensagem clara e o serviço mantém a última previsão boa, expondo o erro em `/health`. Testes: `test_forecaster.py::test_rejects_short_history` e `test_app.py::test_failed_refresh_keeps_last_forecast`.
5. **`vol_ratio` nulo/zero/NaN chegando ao bot** (histórico com range 0) — `suggestThreshold` deve devolver o threshold base. Teste: `test/observation.test.js`.

---

## File Structure

```
forecast/
  requirements.txt            # deps Python (Kronos + serviço + testes)
  setup_kronos.sh             # clona Kronos no commit fixado em forecast/vendor/Kronos
  pytest.ini                  # pythonpath = .
  kronos_service/
    __init__.py
    candles.py                # parse_klines(), fetch_candles() — Binance → DataFrame
    volatility.py             # range_pct(), vol_ratio() — métricas puras
    forecaster.py             # build_forecast() (puro, predictor injetado), load_kronos_predictor()
    app.py                    # ForecastCache, create_app() — FastAPI + thread de refresh
    main.py                   # lê env, carrega Kronos, sobe uvicorn
  tests/
    test_candles.py
    test_volatility.py
    test_forecaster.py
    test_app.py
helpers/
  forecast-client.js          # fetchJson(), isFresh(), createForecastClient()
  observation.js              # suggestThreshold(), buildObservation(), appendObservation()
test/
  forecast-client.test.js
  observation.test.js
bot.js                        # + startup do client, + logObservation() em checkPrice()
package.json                  # script test roda os 3 arquivos
.env.example                  # + FORECAST_URL, FORECAST_MAX_AGE_MIN
.gitignore                    # + forecast/vendor, forecast/.venv, __pycache__, logs/
README.md                     # + seção "Kronos volatility observer"
```

---

### Task 1: Scaffold do serviço + módulo de candles

**Files:**
- Create: `forecast/requirements.txt`, `forecast/pytest.ini`, `forecast/kronos_service/__init__.py`
- Create: `forecast/kronos_service/candles.py`
- Test: `forecast/tests/test_candles.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `COLUMNS: list[str]` = `["timestamps", "open", "high", "low", "close", "volume", "amount"]`
  - `class CandleError(ValueError)`
  - `parse_klines(raw: list) -> pd.DataFrame` — colunas `COLUMNS`, `timestamps` em `datetime64[ns]` (UTC naive), ordenado crescente.
  - `fetch_candles(symbol: str, interval: str, limit: int, url: str = DEFAULT_URL, get=requests.get, timeout: float = 10) -> pd.DataFrame` — devolve `limit - 1` candles fechados.

- [ ] **Step 1: Criar scaffold e venv**

`forecast/requirements.txt`:

```
torch>=2.0.0
numpy
pandas==2.2.2
einops==0.8.1
huggingface_hub==0.33.1
safetensors==0.6.2
tqdm==4.67.1
fastapi>=0.110
uvicorn>=0.29
requests>=2.31
httpx>=0.27
pytest>=8.0
```

`forecast/pytest.ini`:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

`forecast/kronos_service/__init__.py`: arquivo vazio.

Acrescentar ao fim de `.gitignore`:

```
# kronos forecast service
/forecast/vendor
/forecast/.venv
__pycache__/
/logs
```

Run:

```bash
cd forecast && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```

Expected: instalação termina sem erro (torch é o download grande, ~700 MB CPU).

- [ ] **Step 2: Escrever o teste que falha**

`forecast/tests/test_candles.py`:

```python
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
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `cd forecast && .venv/bin/python -m pytest tests/test_candles.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'kronos_service.candles'`

- [ ] **Step 4: Implementar**

`forecast/kronos_service/candles.py`:

```python
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
```

- [ ] **Step 5: Rodar e ver passar**

Run: `cd forecast && .venv/bin/python -m pytest tests/test_candles.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add .gitignore forecast/requirements.txt forecast/pytest.ini forecast/kronos_service/__init__.py forecast/kronos_service/candles.py forecast/tests/test_candles.py
git commit -m "feat(forecast): scaffold kronos service and binance candle loader"
```

---

### Task 2: Métricas de volatilidade + forecaster

**Files:**
- Create: `forecast/kronos_service/volatility.py`
- Create: `forecast/kronos_service/forecaster.py`
- Test: `forecast/tests/test_volatility.py`, `forecast/tests/test_forecaster.py`

**Interfaces:**
- Consumes: `COLUMNS` de `kronos_service.candles` (DataFrame no formato de `parse_klines`).
- Produces:
  - `range_pct(df: pd.DataFrame) -> float` — média de `|high − low| / close × 100`; `ValueError` se vazio ou `close <= 0`.
  - `vol_ratio(predicted: float, historical: float) -> float | None` — `None` se `historical <= 0`.
  - `build_forecast(candles, predictor, *, symbol: str, interval_minutes: int, lookback: int, pred_len: int, sample_count: int, now: datetime, model: str) -> dict` — dict com as chaves do contrato HTTP do spec. `predictor` é qualquer objeto com `.predict(df=, x_timestamp=, y_timestamp=, pred_len=, T=, top_p=, sample_count=, verbose=)` igual ao `KronosPredictor`.
  - `load_kronos_predictor(vendor_path: str, model_id: str, tokenizer_id: str, device: str | None = None, max_context: int = 512)` — retorna `KronosPredictor`.

- [ ] **Step 1: Escrever os testes que falham**

`forecast/tests/test_volatility.py`:

```python
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
```

`forecast/tests/test_forecaster.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd forecast && .venv/bin/python -m pytest tests/test_volatility.py tests/test_forecaster.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'kronos_service.volatility'`

- [ ] **Step 3: Implementar**

`forecast/kronos_service/volatility.py`:

```python
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
```

`forecast/kronos_service/forecaster.py`:

```python
import sys

import pandas as pd

from kronos_service.volatility import range_pct, vol_ratio

FEATURES = ["open", "high", "low", "close", "volume", "amount"]


def build_forecast(candles, predictor, *, symbol, interval_minutes, lookback, pred_len, sample_count, now, model):
    if len(candles) < lookback:
        raise ValueError(f"need {lookback} candles, got {len(candles)}")

    history = candles.tail(lookback).reset_index(drop=True)
    x_timestamp = history["timestamps"]
    step = pd.Timedelta(minutes=interval_minutes)
    y_timestamp = pd.Series([x_timestamp.iloc[-1] + step * (i + 1) for i in range(pred_len)])

    predicted = predictor.predict(
        df=history[FEATURES],
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=pred_len,
        T=1.0,
        top_p=0.9,
        sample_count=sample_count,
        verbose=False,
    )

    historical_range = range_pct(history.tail(pred_len))
    predicted_range = range_pct(predicted)

    return {
        "symbol": symbol,
        "interval_minutes": interval_minutes,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizon_minutes": interval_minutes * pred_len,
        "predicted_range_pct": predicted_range,
        "historical_range_pct": historical_range,
        "vol_ratio": vol_ratio(predicted_range, historical_range),
        "last_close": float(history["close"].iloc[-1]),
        "predicted_close": float(predicted["close"].iloc[-1]),
        "model": model,
    }


def load_kronos_predictor(vendor_path, model_id, tokenizer_id, device=None, max_context=512):
    if vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)
    from model import Kronos, KronosPredictor, KronosTokenizer

    tokenizer = KronosTokenizer.from_pretrained(tokenizer_id)
    model = Kronos.from_pretrained(model_id)
    return KronosPredictor(model, tokenizer, device=device, max_context=max_context)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd forecast && .venv/bin/python -m pytest -v`
Expected: 12 passed (5 candles + 4 volatility + 3 forecaster)

- [ ] **Step 5: Commit**

```bash
git add forecast/kronos_service/volatility.py forecast/kronos_service/forecaster.py forecast/tests/test_volatility.py forecast/tests/test_forecaster.py
git commit -m "feat(forecast): volatility metrics and kronos forecast builder"
```

---

### Task 3: API FastAPI com cache e refresh em segundo plano

**Files:**
- Create: `forecast/kronos_service/app.py`
- Test: `forecast/tests/test_app.py`

**Interfaces:**
- Consumes: nada de tasks anteriores diretamente (recebe `refresh_fn: Callable[[], dict]`).
- Produces:
  - `class ForecastCache` com `refresh(refresh_fn) -> bool` e `snapshot() -> {"forecast": dict | None, "last_error": str | None}`.
  - `create_app(refresh_fn, interval_seconds: float, start_background: bool = True) -> FastAPI` — `app.state.cache` é o `ForecastCache`. Rotas: `GET /forecast` (200 com o dict / 503 `{"error": str}`), `GET /health` (`{"ready": bool, "last_error": str | None}`).

- [ ] **Step 1: Escrever o teste que falha**

`forecast/tests/test_app.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd forecast && .venv/bin/python -m pytest tests/test_app.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'kronos_service.app'`

- [ ] **Step 3: Implementar**

`forecast/kronos_service/app.py`:

```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd forecast && .venv/bin/python -m pytest -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add forecast/kronos_service/app.py forecast/tests/test_app.py
git commit -m "feat(forecast): fastapi app with cached background refresh"
```

---

### Task 4: Entry point real + vendorização do Kronos + smoke test

**Files:**
- Create: `forecast/setup_kronos.sh`
- Create: `forecast/kronos_service/main.py`

**Interfaces:**
- Consumes: `fetch_candles` (Task 1), `build_forecast`, `load_kronos_predictor` (Task 2), `create_app` (Task 3).
- Produces: processo `python -m kronos_service.main` servindo o contrato do spec em `127.0.0.1:${KRONOS_PORT:-8001}`.

Env vars (todas opcionais): `KRONOS_SYMBOL` (SHIBUSDT), `KRONOS_INTERVAL` (5m; aceita 1m/5m/15m/1h), `KRONOS_LOOKBACK` (400, máx 512), `KRONOS_PRED_LEN` (12), `KRONOS_SAMPLE_COUNT` (5), `KRONOS_REFRESH_SECONDS` (300), `KRONOS_PORT` (8001), `KRONOS_DEVICE` (auto), `KRONOS_CANDLES_URL`, `KRONOS_VENDOR_PATH` (`forecast/vendor/Kronos`).

- [ ] **Step 1: Script de vendorização**

`forecast/setup_kronos.sh`:

```bash
#!/usr/bin/env bash
# Clones Kronos at a pinned commit into forecast/vendor/Kronos (gitignored).
set -euo pipefail

KRONOS_COMMIT="67b630e67f6a18c9e9be918d9b4337c960db1e9a"
DEST="$(cd "$(dirname "$0")" && pwd)/vendor/Kronos"

if [ ! -d "$DEST/.git" ]; then
    git clone https://github.com/shiyu-coder/Kronos "$DEST"
fi
git -C "$DEST" fetch --quiet origin "$KRONOS_COMMIT"
git -C "$DEST" checkout --quiet "$KRONOS_COMMIT"
echo "Kronos ready at $DEST ($KRONOS_COMMIT)"
```

Run: `chmod +x forecast/setup_kronos.sh && forecast/setup_kronos.sh`
Expected: `Kronos ready at .../forecast/vendor/Kronos (67b630e...)`

- [ ] **Step 2: Entry point**

`forecast/kronos_service/main.py`:

```python
import os
from datetime import datetime, timezone

import uvicorn

from kronos_service.app import create_app
from kronos_service.candles import DEFAULT_URL, fetch_candles
from kronos_service.forecaster import build_forecast, load_kronos_predictor

INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
MAX_CONTEXT = 512


def main():
    symbol = os.environ.get("KRONOS_SYMBOL", "SHIBUSDT")
    interval = os.environ.get("KRONOS_INTERVAL", "5m")
    lookback = int(os.environ.get("KRONOS_LOOKBACK", "400"))
    pred_len = int(os.environ.get("KRONOS_PRED_LEN", "12"))
    sample_count = int(os.environ.get("KRONOS_SAMPLE_COUNT", "5"))
    refresh_seconds = int(os.environ.get("KRONOS_REFRESH_SECONDS", "300"))
    port = int(os.environ.get("KRONOS_PORT", "8001"))
    device = os.environ.get("KRONOS_DEVICE") or None
    candles_url = os.environ.get("KRONOS_CANDLES_URL", DEFAULT_URL)
    default_vendor = os.path.join(os.path.dirname(__file__), "..", "vendor", "Kronos")
    vendor_path = os.path.abspath(os.environ.get("KRONOS_VENDOR_PATH", default_vendor))

    if interval not in INTERVAL_MINUTES:
        raise SystemExit(f"KRONOS_INTERVAL must be one of {sorted(INTERVAL_MINUTES)}, got {interval!r}")
    if not 1 <= lookback <= MAX_CONTEXT:
        raise SystemExit(f"KRONOS_LOOKBACK must be between 1 and {MAX_CONTEXT}, got {lookback}")
    if not os.path.isdir(os.path.join(vendor_path, "model")):
        raise SystemExit(f"Kronos not found at {vendor_path}; run forecast/setup_kronos.sh")

    predictor = load_kronos_predictor(
        vendor_path, "NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base",
        device=device, max_context=MAX_CONTEXT,
    )

    def refresh():
        # +1 because fetch_candles drops the still-forming candle.
        candles = fetch_candles(symbol, interval, lookback + 1, url=candles_url)
        return build_forecast(
            candles, predictor,
            symbol=symbol, interval_minutes=INTERVAL_MINUTES[interval],
            lookback=lookback, pred_len=pred_len, sample_count=sample_count,
            now=datetime.now(timezone.utc), model="Kronos-small",
        )

    uvicorn.run(create_app(refresh, refresh_seconds), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke test com o modelo real**

Run (terminal 1): `cd forecast && .venv/bin/python -m kronos_service.main`
Expected: download dos pesos do Hugging Face na primeira vez, depois `Uvicorn running on http://127.0.0.1:8001`.

Run (terminal 2, após ~10–60 s em CPU):

```bash
curl -s http://127.0.0.1:8001/health
curl -s http://127.0.0.1:8001/forecast
```

Expected: `{"ready":true,"last_error":null}` e um JSON com todas as chaves do contrato, `vol_ratio` numérico positivo e `predicted_close` na mesma ordem de grandeza de `last_close` (~1e-5 para SHIB). Se `/health` mostrar `HTTPError ... 451`, defina `KRONOS_CANDLES_URL` para outro endpoint compatível. Anote o tempo de um refresh no log; se passar de `KRONOS_REFRESH_SECONDS`, reduza `KRONOS_SAMPLE_COUNT`.

- [ ] **Step 4: Rodar a suíte inteira de novo**

Run: `cd forecast && .venv/bin/python -m pytest -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add forecast/setup_kronos.sh forecast/kronos_service/main.py
git commit -m "feat(forecast): kronos-small entry point and pinned vendor setup"
```

---

### Task 5: Client Node com polling e checagem de frescor

**Files:**
- Create: `helpers/forecast-client.js`
- Test: `test/forecast-client.test.js`
- Modify: `package.json` (script `test`)

**Interfaces:**
- Consumes: contrato HTTP do spec (`GET /forecast`).
- Produces:
  - `fetchJson(url: string, timeoutMs: number) -> Promise<object>` — rejeita em status ≠ 200, JSON inválido, erro de rede ou timeout.
  - `isFresh(forecast: object | null, nowMs: number, maxAgeMs: number) -> boolean` — falso se ausente, `generated_at` inválido, mais velho que `maxAgeMs` ou mais de 60 s no futuro.
  - `createForecastClient({ url, intervalMs = 60000, maxAgeMs = 900000, timeoutMs = 2000, fetch = fetchJson }) -> { poll(): Promise<void>, start(): void, stop(): void, latest(nowMs = Date.now()): object | null, lastError(): string | null }`

- [ ] **Step 1: Escrever o teste que falha**

`test/forecast-client.test.js`:

```js
const assert = require('assert')
const http = require('http')
const { fetchJson, isFresh, createForecastClient } = require('../helpers/forecast-client')

const NOW = Date.parse('2026-10-18T12:00:00Z')
const MIN = 60 * 1000
const forecastAt = (iso) => ({ generated_at: iso, vol_ratio: 1.2 })

function listen(handler) {
    return new Promise((resolve) => {
        const server = http.createServer(handler).listen(0, '127.0.0.1', () => {
            resolve({ server, url: `http://127.0.0.1:${server.address().port}/forecast` })
        })
    })
}

async function run() {
    // Test 1: freshness window.
    assert.strictEqual(isFresh(forecastAt('2026-10-18T11:50:00Z'), NOW, 15 * MIN), true, 'fresh forecast')
    assert.strictEqual(isFresh(forecastAt('2026-10-18T11:40:00Z'), NOW, 15 * MIN), false, 'stale forecast')
    assert.strictEqual(isFresh(forecastAt('2026-10-18T12:05:00Z'), NOW, 15 * MIN), false, 'forecast from the future')
    assert.strictEqual(isFresh(forecastAt('not a date'), NOW, 15 * MIN), false, 'invalid timestamp')
    assert.strictEqual(isFresh(null, NOW, 15 * MIN), false, 'missing forecast')

    // Test 2: fetchJson happy path.
    const ok = await listen((req, res) => {
        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify(forecastAt('2026-10-18T11:59:00Z')))
    })
    assert.deepStrictEqual(await fetchJson(ok.url, 1000), forecastAt('2026-10-18T11:59:00Z'), 'fetchJson 200')

    // Test 3: client caches the last good forecast and survives a later failure.
    let calls = 0
    const flaky = createForecastClient({
        url: 'unused',
        fetch: async () => {
            calls += 1
            if (calls === 1) return forecastAt('2026-10-18T11:59:00Z')
            throw new Error('ECONNREFUSED')
        },
    })
    await flaky.poll()
    await flaky.poll()
    assert.deepStrictEqual(flaky.latest(NOW), forecastAt('2026-10-18T11:59:00Z'), 'keeps last good forecast')
    assert.strictEqual(flaky.lastError(), 'ECONNREFUSED', 'records last error')
    assert.strictEqual(flaky.latest(NOW + 30 * MIN), null, 'cached forecast expires')
    ok.server.close()

    // Test 4: non-200 rejects.
    const failing = await listen((req, res) => {
        res.writeHead(503)
        res.end('{"error":"forecast not ready"}')
    })
    await assert.rejects(fetchJson(failing.url, 1000), /HTTP 503/, 'fetchJson 503')
    failing.server.close()

    // Test 5: timeout rejects instead of hanging.
    const slow = await listen(() => { /* never responds */ })
    await assert.rejects(fetchJson(slow.url, 100), /timeout/, 'fetchJson timeout')
    slow.server.close()

    // Test 6: refused connection rejects; client with nothing cached returns null.
    await assert.rejects(fetchJson('http://127.0.0.1:1/forecast', 500), 'fetchJson refused')
    const down = createForecastClient({ url: 'http://127.0.0.1:1/forecast', timeoutMs: 500 })
    await down.poll()
    assert.strictEqual(down.latest(NOW), null, 'no forecast when service is down')

    console.log('All forecast-client tests passed')
}

run().catch((error) => {
    console.error(error)
    process.exit(1)
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `node test/forecast-client.test.js`
Expected: FAIL com `Cannot find module '../helpers/forecast-client'`

- [ ] **Step 3: Implementar**

`helpers/forecast-client.js`:

```js
const http = require('http')

const FUTURE_TOLERANCE_MS = 60 * 1000

function fetchJson(url, timeoutMs) {
    return new Promise((resolve, reject) => {
        const req = http.get(url, { timeout: timeoutMs }, (res) => {
            let body = ''
            res.setEncoding('utf8')
            res.on('data', (chunk) => { body += chunk })
            res.on('end', () => {
                if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode}`))
                try {
                    resolve(JSON.parse(body))
                } catch (error) {
                    reject(error)
                }
            })
        })
        req.on('timeout', () => req.destroy(new Error('timeout')))
        req.on('error', reject)
    })
}

function isFresh(forecast, nowMs, maxAgeMs) {
    if (!forecast || typeof forecast.generated_at !== 'string') return false
    const generatedMs = Date.parse(forecast.generated_at)
    if (Number.isNaN(generatedMs)) return false
    return nowMs - generatedMs <= maxAgeMs && generatedMs - nowMs <= FUTURE_TOLERANCE_MS
}

// Polls the Kronos service off the hot path; latest() is a synchronous cache read.
function createForecastClient({ url, intervalMs = 60000, maxAgeMs = 15 * 60000, timeoutMs = 2000, fetch = fetchJson }) {
    let last = null
    let error = null
    let timer = null

    async function poll() {
        try {
            last = await fetch(url, timeoutMs)
            error = null
        } catch (err) {
            error = err.message
        }
    }

    return {
        poll,
        start() {
            poll()
            timer = setInterval(poll, intervalMs)
            timer.unref()
        },
        stop() {
            clearInterval(timer)
        },
        latest(nowMs = Date.now()) {
            return isFresh(last, nowMs, maxAgeMs) ? last : null
        },
        lastError() {
            return error
        },
    }
}

module.exports = { fetchJson, isFresh, createForecastClient }
```

- [ ] **Step 4: Rodar e ver passar**

Run: `node test/forecast-client.test.js`
Expected: `All forecast-client tests passed`

- [ ] **Step 5: Ligar no `npm test`**

Em `package.json`, trocar o script:

```json
"test": "node test/arbitrage-math.test.js && node test/forecast-client.test.js"
```

Run: `npm test`
Expected: `All arbitrage-math tests passed` e `All forecast-client tests passed`

- [ ] **Step 6: Commit**

```bash
git add helpers/forecast-client.js test/forecast-client.test.js package.json
git commit -m "feat(bot): polling client for kronos forecast service"
```

---

### Task 6: Observação no bot.js (threshold sugerido + log JSONL)

**Files:**
- Create: `helpers/observation.js`
- Test: `test/observation.test.js`
- Modify: `bot.js` (imports no topo; `logObservation` + chamada em `checkPrice()`; `forecastClient.start()` em `main()`)
- Modify: `package.json`, `.env.example`, `README.md`

**Interfaces:**
- Consumes: `createForecastClient` (Task 5); JSON do contrato do spec.
- Produces:
  - `suggestThreshold(base: number | string, forecast: object | null) -> number`
  - `buildObservation({ nowMs, block, priceDifference, baseThreshold, forecast }) -> object` com chaves `observed_at, block, price_difference_pct, base_threshold_pct, suggested_threshold_pct, forecast_generated_at, vol_ratio, predicted_range_pct, historical_range_pct`.
  - `appendObservation(filePath: string, record: object) -> void` — cria o diretório se preciso e acrescenta uma linha JSON.

- [ ] **Step 1: Escrever o teste que falha**

`test/observation.test.js`:

```js
const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { suggestThreshold, buildObservation, appendObservation } = require('../helpers/observation')

const forecast = {
    generated_at: '2026-10-18T11:55:00Z',
    vol_ratio: 1.5,
    predicted_range_pct: 0.6,
    historical_range_pct: 0.4,
}

// Test 1: threshold scales with vol_ratio, clamped to [0.5, 2].
assert.strictEqual(suggestThreshold('0.50', forecast), 0.75, 'scaled threshold')
assert.strictEqual(suggestThreshold(0.5, { vol_ratio: 10 }), 1, 'clamped high')
assert.strictEqual(suggestThreshold(0.5, { vol_ratio: 0.1 }), 0.25, 'clamped low')

// Test 2: no usable forecast falls back to the base threshold.
assert.strictEqual(suggestThreshold('0.50', null), 0.5, 'no forecast')
assert.strictEqual(suggestThreshold(0.5, { vol_ratio: null }), 0.5, 'null ratio')
assert.strictEqual(suggestThreshold(0.5, { vol_ratio: 0 }), 0.5, 'zero ratio')
assert.strictEqual(suggestThreshold(0.5, { vol_ratio: NaN }), 0.5, 'NaN ratio')

// Test 3: observation record with and without forecast.
const nowMs = Date.parse('2026-10-18T12:00:00Z')
assert.deepStrictEqual(
    buildObservation({ nowMs, block: 123, priceDifference: '-0.62', baseThreshold: '0.50', forecast }),
    {
        observed_at: '2026-10-18T12:00:00.000Z',
        block: 123,
        price_difference_pct: -0.62,
        base_threshold_pct: 0.5,
        suggested_threshold_pct: 0.75,
        forecast_generated_at: '2026-10-18T11:55:00Z',
        vol_ratio: 1.5,
        predicted_range_pct: 0.6,
        historical_range_pct: 0.4,
    },
    'observation with forecast'
)
const bare = buildObservation({ nowMs, block: 1, priceDifference: '0.10', baseThreshold: '0.50', forecast: null })
assert.strictEqual(bare.suggested_threshold_pct, 0.5, 'bare suggested threshold')
assert.strictEqual(bare.forecast_generated_at, null, 'bare generated_at')
assert.strictEqual(bare.vol_ratio, null, 'bare vol_ratio')

// Test 4: append creates the directory and writes one JSON line per call.
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'obs-'))
const file = path.join(dir, 'nested', 'observations.jsonl')
appendObservation(file, { a: 1 })
appendObservation(file, { a: 2 })
assert.deepStrictEqual(
    fs.readFileSync(file, 'utf8').trim().split('\n').map((line) => JSON.parse(line)),
    [{ a: 1 }, { a: 2 }],
    'jsonl lines'
)
fs.rmSync(dir, { recursive: true, force: true })

console.log('All observation tests passed')
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `node test/observation.test.js`
Expected: FAIL com `Cannot find module '../helpers/observation'`

- [ ] **Step 3: Implementar**

`helpers/observation.js`:

```js
const fs = require('fs')
const path = require('path')

const MIN_FACTOR = 0.5
const MAX_FACTOR = 2

function suggestThreshold(base, forecast) {
    const baseThreshold = Number(base)
    const ratio = forecast ? forecast.vol_ratio : null
    if (typeof ratio !== 'number' || !Number.isFinite(ratio) || ratio <= 0) return baseThreshold
    const factor = Math.min(MAX_FACTOR, Math.max(MIN_FACTOR, ratio))
    return Number((baseThreshold * factor).toFixed(4))
}

function buildObservation({ nowMs, block, priceDifference, baseThreshold, forecast }) {
    return {
        observed_at: new Date(nowMs).toISOString(),
        block,
        price_difference_pct: Number(priceDifference),
        base_threshold_pct: Number(baseThreshold),
        suggested_threshold_pct: suggestThreshold(baseThreshold, forecast),
        forecast_generated_at: forecast ? forecast.generated_at : null,
        vol_ratio: forecast ? forecast.vol_ratio : null,
        predicted_range_pct: forecast ? forecast.predicted_range_pct : null,
        historical_range_pct: forecast ? forecast.historical_range_pct : null,
    }
}

function appendObservation(filePath, record) {
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    fs.appendFileSync(filePath, JSON.stringify(record) + '\n')
}

module.exports = { suggestThreshold, buildObservation, appendObservation }
```

- [ ] **Step 4: Rodar e ver passar; ligar no `npm test`**

Em `package.json`:

```json
"test": "node test/arbitrage-math.test.js && node test/forecast-client.test.js && node test/observation.test.js"
```

Run: `npm test`
Expected: as três linhas `All ... tests passed`

- [ ] **Step 5: Integrar em `bot.js`**

Logo após `const { optimalInput, estimateProfit, mapReserves } = require('./helpers/arbitrage-math')`, acrescentar:

```js
const path = require('path')
const { createForecastClient } = require('./helpers/forecast-client')
const { buildObservation, appendObservation } = require('./helpers/observation')
```

Logo após `const estimatedGasCost = process.env.GAS_PRICE ...`, acrescentar:

```js
const forecastClient = process.env.FORECAST_URL
    ? createForecastClient({
        url: process.env.FORECAST_URL,
        maxAgeMs: Number(process.env.FORECAST_MAX_AGE_MIN || 15) * 60 * 1000,
    })
    : null
const observationsPath = path.join(__dirname, 'logs', 'observations.jsonl')
```

No início de `main()`, antes de `getTokenAndContract`:

```js
    if (forecastClient) forecastClient.start()
```

Em `checkPrice()`, logo após `console.log(\`Percentage Difference: ${priceDifference}%\n\`)` e antes de `return priceDifference`:

```js
    logObservation(currentBlock, priceDifference)
```

E acrescentar a função logo após `checkPrice` (antes de `determineDirection`):

```js
// Phase 1 (observation only): the suggested threshold is logged, never applied.
const logObservation = (block, priceDifference) => {
    const forecast = forecastClient ? forecastClient.latest() : null
    const record = buildObservation({ nowMs: Date.now(), block, priceDifference, baseThreshold: difference, forecast })

    if (!forecastClient) {
        console.log(`Forecast: disabled\n`)
    } else if (!forecast) {
        console.log(`Forecast: unavailable (${forecastClient.lastError() || 'stale'}) — using fixed PRICE_DIFFERENCE\n`)
    } else {
        console.log(`Forecast: vol_ratio ${forecast.vol_ratio} → suggested threshold ${record.suggested_threshold_pct}% (not applied)\n`)
    }

    try {
        appendObservation(observationsPath, record)
    } catch (error) {
        console.log(`Could not write observation: ${error.message}\n`)
    }
}
```

- [ ] **Step 6: `.env.example` e README**

Acrescentar ao `.env.example`:

```
# Kronos volatility observer (optional; empty disables it)
FORECAST_URL="http://127.0.0.1:8001/forecast"
FORECAST_MAX_AGE_MIN=15
```

Acrescentar ao `README.md` uma seção:

````markdown
## Kronos volatility observer (optional)

Logs a Kronos-small volatility forecast next to every observed spread in `logs/observations.jsonl`. It never changes trade decisions.

```bash
cd forecast
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./setup_kronos.sh
python -m kronos_service.main        # serves http://127.0.0.1:8001/forecast
```

Then set `FORECAST_URL` in `.env` and start the bot as usual. Leave it empty to disable.
````

- [ ] **Step 7: Verificação manual ponta a ponta**

Pré-requisitos: Ganache rodando conforme o README, `truffle migrate --reset` feito.

1. **Desligado:** `.env` sem `FORECAST_URL`. `node ./bot.js`, depois em outro terminal `node ./scripts/manipulatePrice.js`. Expected: saída idêntica à de antes + linha `Forecast: disabled`; `logs/observations.jsonl` ganha uma linha com `vol_ratio: null`.
2. **Serviço fora do ar:** `FORECAST_URL="http://127.0.0.1:8001/forecast"` sem subir o serviço. Reinicie Ganache + migrate, repita. Expected: `Forecast: unavailable (connect ECONNREFUSED 127.0.0.1:8001) — using fixed PRICE_DIFFERENCE`; a decisão de trade é a mesma do passo 1.
3. **Serviço ativo:** suba `python -m kronos_service.main`, espere `/health` ficar `ready: true`, reinicie Ganache + migrate + bot, repita. Expected: `Forecast: vol_ratio <n> → suggested threshold <x>% (not applied)`; linha JSONL com todos os campos preenchidos; decisão de trade igual ao passo 1.

- [ ] **Step 8: Commit**

```bash
git add helpers/observation.js test/observation.test.js bot.js package.json .env.example README.md
git commit -m "feat(bot): log kronos volatility forecast alongside observed spreads"
```
