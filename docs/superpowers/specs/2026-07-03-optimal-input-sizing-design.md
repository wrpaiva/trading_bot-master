# Optimal Input Sizing & Fee-Aware Profitability Gate

**Date:** 2026-07-03
**Status:** Approved
**Scope:** Strategy improvements #1 (optimal trade sizing) and #2 (net-of-fees profitability threshold)

## Problem

The bot's `determineProfitability()` (`bot.js:137`) has two flaws that make it unprofitable in real conditions:

1. **Arbitrary trade sizing.** It calls `getAmountsIn(reserves[0], ...)` to size the trade at "the entire token reserve of the sell pool" (the README's "clear out reserves" heuristic). There is no mathematical reason this size maximizes profit; it over- or under-sizes depending on relative liquidity.

2. **No fee-aware gate.** The go/no-go is `PRICE_DIFFERENCE=0.50` (%) plus a bare `if (amountOut < amountIn) return false`. A round-trip through two Uniswap-V2-style pools costs ~0.6% in pool fees (0.3% each), so a 0.5% trigger approves trades that lose money.

## Key Insight

For two constant-product pools with equal fee factor γ (= 0.997), the profit-maximizing input has a closed form, and its positivity **is** the net-of-fees profitability condition. One computation solves both #1 and #2.

Buying token0 (WETH) in the **buy** pool then selling token1 (SHIB) in the **sell** pool:

```
x* = ( γ·√(a·a'·b·b') − a·b' ) / ( γ·(b' + γ·b) )
```

Where:
- `a`  = WETH reserve in the **buy** pool
- `b`  = SHIB reserve in the **buy** pool
- `a'` = WETH reserve in the **sell** pool
- `b'` = SHIB reserve in the **sell** pool
- `γ`  = fee factor = 997/1000

Derivation: composing the two constant-product swaps gives output `z(x) = k·x / (c + m·x)` with `k = γ²·a'·b`, `c = a·b'`, `m = γ·(b' + γ·b)`. Setting `dz/dx = 1` (marginal output equals marginal input at the profit max) yields `x* = (√(k·c) − c) / m`, which simplifies to the formula above.

**Profitability gate:** `x* > 0` ⇔ `γ·√(a·a'·b·b') > a·b'` ⇔ the cross-pool price ratio exceeds the fee hurdle. So `x* ≤ 0` replaces the arbitrary 0.5% threshold as the fee-aware "no arbitrage" signal.

Gross profit estimate at `x*`:
```
z  = γ²·a'·b·x* / ( a·b' + γ·(b' + γ·b)·x* )
grossProfit = z − x*
```

## Approach

**Chosen: closed-form formula in a pure module.** Rejected alternatives: numerical golden-section search (approximate, slower, unnecessary for two equal-fee pools) and iterative on-chain `getAmountsIn/Out` probing (many RPC calls per event, still approximate).

## Design

### New module: `helpers/arbitrage-math.js`

Pure functions, no web3/RPC, `Big.js` for arbitrary-precision arithmetic (reserves are ~1e24 wei; the product under the root reaches ~1e96).

- `optimalInput(reserves, fee)` → `Big`
  - `reserves = { a, b, aPrime, bPrime }` (all `Big` or string wei amounts, mapped as WETH/SHIB per the definitions above).
  - `fee` defaults to `997/1000`.
  - Returns `x*` as `Big`, or `Big(0)` when `x* ≤ 0` (not profitable).
- `estimateProfit(reserves, x, fee)` → `{ amountIn, amountOut, grossProfit }`
  - Computes `z` and `grossProfit = z − x` using the same reserves and fee.
  - All values `Big`.

### Refactor `determineProfitability()` in `bot.js`

1. **Map reserves by token address, not position.** Read `getReserves()` for both pairs and assign `a/b/a'/b'` by checking which token is `arbFor` (WETH) vs `arbAgainst` (SHIB) via the pair's `token0()` address. This fixes a latent bug: the current code assumes `reserves[0]=SHIB, reserves[1]=WETH`, which is only true for one address ordering.
2. Determine buy/sell pool from `_routerPath` (unchanged direction logic).
3. Call `optimalInput(...)`. If result ≤ 0 → log "no arbitrage" and return `false` (this is the #2 gate).
4. Call `estimateProfit(...)`. Subtract the existing gas estimate: if `grossProfit − estimatedGasCost ≤ 0` → return `false`.
5. Otherwise set `amount = x*` (the flash-loan amount) and return `true`.

Keep the existing `console.table` reporting, fed from the new estimates.

### `determineDirection()`

Unchanged for choosing direction by the sign of the spread. The quantitative veto now comes from `optimalInput` returning 0 — `PRICE_DIFFERENCE` is no longer the arbiter of profitability. (It may remain as a cheap pre-filter to avoid computing `x*` on tiny spreads, but is not the profit gate.)

### On-chain contract

Untouched. `Arbitrage.executeTrade(...)` already accepts `_flashAmount`; we pass `x*`. MEV protection and `minAmountOut` (items #6/#7) are out of scope.

## Profitability criterion (confirmed assumption)

The gate subtracts **pool fees (via the formula) + the existing static gas estimate** (`GAS_PRICE`/`GAS_LIMIT` from `.env`). Dynamic gas from `baseFee` is item #5 and out of scope. Flash-loan fee (DyDx, ~1 wei) is negligible and ignored.

## Testing

No test framework exists (`test/` is empty, `npm test` is a stub). Add `test/arbitrage-math.test.js` runnable with plain `node` + the built-in `assert` module, and wire `npm test` to run it.

Cases:
1. **Below cost:** spread smaller than the ~0.6% fee hurdle → `optimalInput` returns 0.
2. **Known profitable scenario:** hand-computed reserves → `x*` and `grossProfit` match expected values within a tolerance.
3. **Direction symmetry:** swapping buy/sell pools yields the correct `x*` for the reverse direction.
4. **Token ordering:** reserves where WETH is `token0` vs `token1` both map correctly and give identical results.
5. **Boundary:** exactly break-even reserves → `x*` at/near 0, gate rejects.

## Out of Scope

- Solidity contract changes.
- Dynamic gas pricing (#5).
- `minAmountOut` / MEV protection / private mempool (#6, #7).
- Switching flash-loan provider (#8).
- Multi-pair / multi-DEX / triangular arbitrage (#9).

## Files Touched

- `helpers/arbitrage-math.js` (new)
- `bot.js` (`determineProfitability`, minor `determineDirection`)
- `test/arbitrage-math.test.js` (new)
- `package.json` (`test` script)
