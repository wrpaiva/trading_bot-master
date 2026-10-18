# Kronos Volatility Observer — Design

**Data:** 2026-10-18
**Status:** proposta

## Problema

O bot faz arbitragem atômica (flash loan, compra e venda na mesma transação). O lucro é determinístico a partir das reservas, então previsão de preço direcional não ajuda o caminho crítico. A hipótese a testar é outra: **a volatilidade prevista para as próximas horas tem relação com o tamanho/frequência dos spreads Uniswap↔Sushiswap?** Se tiver, um `PRICE_DIFFERENCE` dinâmico pode filtrar ruído em regimes calmos e capturar mais em regimes agitados.

## Escopo (fase 1 — só observação)

1. Um serviço Python separado (`forecast/`) roda o Kronos-small periodicamente sobre candles de 5 min de `SHIBUSDT` (perna volátil do par) e expõe a última previsão via HTTP.
2. O `bot.js` consulta esse serviço em segundo plano (polling), **nunca** no caminho do evento `Swap`.
3. A cada `checkPrice`, o bot registra em `logs/observations.jsonl`: spread observado, threshold fixo, threshold *sugerido* e métricas da previsão.
4. O threshold sugerido **não é aplicado**. A decisão de trade continua 100% igual à atual.

Fora de escopo: aplicar o threshold dinâmico, fine-tuning, estratégia direcional, previsão do spread em si.

## Métrica

- `range_pct(candles)` = média de `|high − low| / close × 100`.
- `predicted_range_pct` = `range_pct` dos `pred_len` candles previstos pelo Kronos.
- `historical_range_pct` = `range_pct` dos últimos `pred_len` candles reais.
- `vol_ratio` = `predicted / historical` (`null` se histórico = 0).
- `suggested_threshold` = `PRICE_DIFFERENCE × clamp(vol_ratio, 0.5, 2.0)`; sem previsão válida → `PRICE_DIFFERENCE`.

## Contrato HTTP

`GET http://127.0.0.1:8001/forecast` → 200:

```json
{
  "symbol": "SHIBUSDT",
  "interval_minutes": 5,
  "generated_at": "2026-10-18T12:00:00Z",
  "horizon_minutes": 60,
  "predicted_range_pct": 0.42,
  "historical_range_pct": 0.35,
  "vol_ratio": 1.2,
  "last_close": 0.0000123,
  "predicted_close": 0.0000124,
  "model": "Kronos-small"
}
```

→ 503 `{"error": "..."}` enquanto não houver previsão. `GET /health` → `{"ready": bool, "last_error": str|null}`.

## Requisitos de robustez

- Serviço fora do ar, lento, com 5xx ou JSON inválido → bot segue com threshold fixo, sem travar nem lançar.
- Previsão mais velha que `FORECAST_MAX_AGE_MIN` (padrão 15) → tratada como ausente.
- Falha ao buscar candles ou rodar o modelo → serviço mantém a última previsão boa e expõe o erro em `/health`.
- `FORECAST_URL` vazio → integração desligada; comportamento idêntico ao atual.

## Critério de saída da fase 1

Algumas semanas de `observations.jsonl` analisadas: se `vol_ratio` correlacionar com `|price_difference_pct|`, abrir fase 2 (aplicar o threshold atrás de flag). Senão, remover.
