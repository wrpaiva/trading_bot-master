# Optimal Input Sizing & Fee-Aware Profitability Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the arbitrary "clear out reserves" trade sizing and the 0.5% price threshold with a closed-form optimal input amount whose positivity is itself the net-of-fees profitability gate.

**Architecture:** Extract the arbitrage math into a pure, RPC-free module (`helpers/arbitrage-math.js`) covered by unit tests. Refactor `bot.js`'s `determineProfitability()` to map pool reserves to WETH/SHIB roles by token address, compute the optimal input `x*`, reject when `x* <= 0` (fee-aware gate) or when gross profit doesn't beat the gas estimate, and pass `x*` as the flash-loan amount. The Solidity contract is untouched.

**Tech Stack:** Node.js, `big.js` (arbitrary-precision arithmetic), `web3`, Node's built-in `assert` for tests.

## Global Constraints

- Fee factor is `997/1000` for both pools (Uniswap V2 + Sushiswap are both 0.3% pools).
- The arbitrage math module MUST be pure: no `web3`, no RPC, no `require` of network code. Only `big.js`.
- All monetary math uses `big.js` (`Big`), never JS floats. Reserves are wei-scale (~1e24); the product under the square root reaches ~1e96.
- The flash-loan amount passed on-chain MUST be an integer wei string (`Big.toFixed(0)`).
- Profitability gate subtracts pool fees (via the formula) + the existing static gas estimate (`GAS_PRICE` from `.env`, in ether). Dynamic gas, MEV/minAmountOut, and contract changes are out of scope.

---

### Task 1: Pure arbitrage math module + unit tests

**Files:**
- Create: `helpers/arbitrage-math.js`
- Create: `test/arbitrage-math.test.js`
- Modify: `package.json` (the `test` script)

**Interfaces:**
- Consumes: `big.js` only.
- Produces:
  - `optimalInput(reserves, fee?) -> Big` where `reserves = { a, b, aPrime, bPrime }` (WETH/SHIB reserves as `Big`/string/number). Returns `x*` as `Big`, or `Big(0)` when not profitable. `fee` defaults to `997/1000`.
  - `estimateProfit(reserves, x, fee?) -> { amountIn: Big, amountOut: Big, grossProfit: Big }`.
  - `mapReserves({ buyReserve0, buyReserve1, buyToken0IsWeth, sellReserve0, sellReserve1, sellToken0IsWeth }) -> { a, b, aPrime, bPrime }`.
  - `DEFAULT_FEE: Big` (the `997/1000` fee factor).

- [ ] **Step 1: Install dependencies (needed to run any test)**

Run: `npm install`
Expected: `node_modules/` is created; `node_modules/big.js` exists. (Deps are currently not installed.)

- [ ] **Step 2: Write the failing test**

Create `test/arbitrage-math.test.js`:

```js
const assert = require('assert')
const Big = require('big.js')
const { optimalInput, estimateProfit, mapReserves, DEFAULT_FEE } = require('../helpers/arbitrage-math')

function approx(actual, expected, tol, msg) {
    const diff = Big(actual).minus(expected).abs()
    assert.ok(diff.lte(tol), `${msg}: expected ~${expected}, got ${actual.toString()} (diff ${diff.toString()})`)
}

// Buy pool: 100 WETH / 100000 SHIB (1 WETH = 1000 SHIB, SHIB cheap here).
// Sell pool: 100 WETH / 90000 SHIB (1 WETH = 900 SHIB, SHIB dearer here).
// Profitable direction: buy SHIB on buy pool, sell on sell pool.
const profitable = { a: 100, b: 100000, aPrime: 100, bPrime: 90000 }

// Test 1: optimal input matches the closed-form value.
const x = optimalInput(profitable)
approx(x, '2.4236', '0.01', 'optimalInput profitable scenario')

// Test 2: estimated gross profit is positive and matches hand calculation.
const { amountIn, amountOut, grossProfit } = estimateProfit(profitable, x)
assert.ok(amountOut.gt(amountIn), 'amountOut should exceed amountIn')
approx(grossProfit, '0.1235', '0.01', 'grossProfit profitable scenario')

// Test 3: spread below the ~0.6% fee hurdle => no trade.
const belowCost = { a: 100, b: 100000, aPrime: 100, bPrime: 99900 }
assert.ok(optimalInput(belowCost).eq(0), 'optimalInput should be 0 below fee hurdle')

// Test 4: wrong direction (buy where SHIB is dear) => no trade.
const wrongDirection = { a: 100, b: 90000, aPrime: 100, bPrime: 100000 }
assert.ok(optimalInput(wrongDirection).eq(0), 'optimalInput should be 0 in the unprofitable direction')

// Test 5: mapReserves assigns WETH/SHIB by token0 flag, both orderings.
const mappedWethIsToken0 = mapReserves({
    buyReserve0: 100, buyReserve1: 100000, buyToken0IsWeth: true,
    sellReserve0: 100, sellReserve1: 90000, sellToken0IsWeth: true,
})
assert.deepStrictEqual(
    { a: mappedWethIsToken0.a, b: mappedWethIsToken0.b, aPrime: mappedWethIsToken0.aPrime, bPrime: mappedWethIsToken0.bPrime },
    { a: 100, b: 100000, aPrime: 100, bPrime: 90000 },
    'mapReserves (WETH is token0)'
)
const mappedShibIsToken0 = mapReserves({
    buyReserve0: 100000, buyReserve1: 100, buyToken0IsWeth: false,
    sellReserve0: 90000, sellReserve1: 100, sellToken0IsWeth: false,
})
assert.deepStrictEqual(
    { a: mappedShibIsToken0.a, b: mappedShibIsToken0.b, aPrime: mappedShibIsToken0.aPrime, bPrime: mappedShibIsToken0.bPrime },
    { a: 100, b: 100000, aPrime: 100, bPrime: 90000 },
    'mapReserves (SHIB is token0)'
)

// Test 6: both mappings yield the same optimal input.
approx(optimalInput(mappedShibIsToken0), optimalInput(mappedWethIsToken0), '0.0001', 'ordering invariance')

assert.ok(DEFAULT_FEE.eq(Big(997).div(1000)), 'DEFAULT_FEE is 997/1000')

console.log('All arbitrage-math tests passed')
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `npm test`
Expected: FAIL — `Cannot find module '../helpers/arbitrage-math'`.

- [ ] **Step 4: Wire the test script**

In `package.json`, replace the `test` script:

```json
  "scripts": {
    "test": "node test/arbitrage-math.test.js"
  },
```

- [ ] **Step 5: Implement the module**

Create `helpers/arbitrage-math.js`:

```js
const Big = require('big.js')

// Fee factor gamma = 1 - 0.003 = 0.997 for Uniswap-V2-style pools.
const DEFAULT_FEE = Big(997).div(1000)

// reserves = { a, b, aPrime, bPrime } where, for a trade that buys SHIB with
// WETH on the BUY pool and sells SHIB for WETH on the SELL pool:
//   a      = WETH reserve in the BUY pool
//   b      = SHIB reserve in the BUY pool
//   aPrime = WETH reserve in the SELL pool
//   bPrime = SHIB reserve in the SELL pool
// Returns the profit-maximizing WETH input x* as Big, or Big(0) if x* <= 0
// (i.e. no arbitrage after fees).
//   x* = ( g*sqrt(a*aPrime*b*bPrime) - a*bPrime ) / ( g*(bPrime + g*b) )
function optimalInput(reserves, fee = DEFAULT_FEE) {
    const a = Big(reserves.a)
    const b = Big(reserves.b)
    const aPrime = Big(reserves.aPrime)
    const bPrime = Big(reserves.bPrime)
    const g = Big(fee)

    const root = a.times(aPrime).times(b).times(bPrime).sqrt()
    const numerator = g.times(root).minus(a.times(bPrime))

    if (numerator.lte(0)) {
        return Big(0)
    }

    const denominator = g.times(bPrime.plus(g.times(b)))
    return numerator.div(denominator)
}

// Estimated WETH output z and gross profit for a given WETH input x, through
// the same two pools:
//   z = g^2 * aPrime * b * x / ( a*bPrime + g*(bPrime + g*b)*x )
function estimateProfit(reserves, x, fee = DEFAULT_FEE) {
    const a = Big(reserves.a)
    const b = Big(reserves.b)
    const aPrime = Big(reserves.aPrime)
    const bPrime = Big(reserves.bPrime)
    const g = Big(fee)
    const amountIn = Big(x)

    const numerator = g.times(g).times(aPrime).times(b).times(amountIn)
    const denominator = a.times(bPrime).plus(g.times(bPrime.plus(g.times(b))).times(amountIn))
    const amountOut = denominator.eq(0) ? Big(0) : numerator.div(denominator)
    const grossProfit = amountOut.minus(amountIn)

    return { amountIn, amountOut, grossProfit }
}

// Maps raw pool reserves (reserve0/reserve1 as returned by getReserves) to
// WETH/SHIB roles using each pool's token0 identity.
function mapReserves({
    buyReserve0, buyReserve1, buyToken0IsWeth,
    sellReserve0, sellReserve1, sellToken0IsWeth,
}) {
    return {
        a: buyToken0IsWeth ? buyReserve0 : buyReserve1,
        b: buyToken0IsWeth ? buyReserve1 : buyReserve0,
        aPrime: sellToken0IsWeth ? sellReserve0 : sellReserve1,
        bPrime: sellToken0IsWeth ? sellReserve1 : sellReserve0,
    }
}

module.exports = { optimalInput, estimateProfit, mapReserves, DEFAULT_FEE }
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `npm test`
Expected: PASS — prints `All arbitrage-math tests passed`, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add helpers/arbitrage-math.js test/arbitrage-math.test.js package.json
git commit -m "feat: add closed-form optimal input arbitrage math with tests"
```

---

### Task 2: Wire optimal sizing into bot.js's profitability gate

**Files:**
- Modify: `bot.js` (imports near top; `determineProfitability` at `bot.js:137`)

**Interfaces:**
- Consumes: `optimalInput`, `estimateProfit`, `mapReserves` from `./helpers/arbitrage-math`; `getReserves` (already imported from `./helpers/helpers`); module-level `uPair`, `sPair`, `uRouter`, `web3`, `estimatedGasCost`, `amount`.
- Produces: sets module-level `amount` (integer wei string) and returns a boolean, exactly as before, so `main()` and `executeTrade()` are unchanged.

- [ ] **Step 1: Add imports near the top of `bot.js`**

After the existing `const { uFactory, uRouter, ... } = require('./helpers/initialization')` line, add:

```js
const Big = require('big.js')
const { optimalInput, estimateProfit, mapReserves } = require('./helpers/arbitrage-math')
```

- [ ] **Step 2: Replace the body of `determineProfitability`**

Replace the entire `determineProfitability` function (from `const determineProfitability = async (...) => {` through its closing `}`) with:

```js
const determineProfitability = async (_routerPath, _token0Contract, _token0, _token1) => {
    console.log(`Determining Profitability...\n`)

    // _token0 is arbFor (WETH); routerPath[0] is where we buy, routerPath[1] where we sell.
    let buyPair, sellPair, exchangeToBuy, exchangeToSell
    if (_routerPath[0]._address == uRouter._address) {
        buyPair = uPair
        sellPair = sPair
        exchangeToBuy = 'Uniswap'
        exchangeToSell = 'Sushiswap'
    } else {
        buyPair = sPair
        sellPair = uPair
        exchangeToBuy = 'Sushiswap'
        exchangeToSell = 'Uniswap'
    }

    try {
        const buyReserves = await getReserves(buyPair)
        const sellReserves = await getReserves(sellPair)
        const buyToken0 = await buyPair.methods.token0().call()
        const sellToken0 = await sellPair.methods.token0().call()

        const wethAddress = _token0.address.toLowerCase()

        const reserves = mapReserves({
            buyReserve0: buyReserves[0],
            buyReserve1: buyReserves[1],
            buyToken0IsWeth: buyToken0.toLowerCase() === wethAddress,
            sellReserve0: sellReserves[0],
            sellReserve1: sellReserves[1],
            sellToken0IsWeth: sellToken0.toLowerCase() === wethAddress,
        })

        const x = optimalInput(reserves)

        if (x.lte(0)) {
            console.log(`No profitable trade size — spread below fee hurdle.\n`)
            return false
        }

        const { amountIn, amountOut, grossProfit } = estimateProfit(reserves, x)

        // Gas estimate from .env is in ether; convert to wei to compare with profit.
        const gasWei = Big(web3.utils.toWei(estimatedGasCost.toString(), 'ether'))
        const netProfit = grossProfit.minus(gasWei)

        const data = {
            'Optimal WETH In': web3.utils.fromWei(amountIn.toFixed(0), 'ether'),
            'Estimated WETH Out': web3.utils.fromWei(amountOut.toFixed(0), 'ether'),
            'Buy On': exchangeToBuy,
            'Sell On': exchangeToSell,
            'Gross Profit (WETH)': web3.utils.fromWei(grossProfit.toFixed(0), 'ether'),
            'Est. Gas Cost (ETH)': estimatedGasCost,
            'Net Profit (WETH)': web3.utils.fromWei(netProfit.toFixed(0), 'ether'),
        }
        console.table(data)
        console.log()

        if (netProfit.lte(0)) {
            console.log(`Trade not profitable after gas.\n`)
            return false
        }

        amount = x.toFixed(0) // integer wei for the flash-loan amount
        return true

    } catch (error) {
        console.log(error)
        console.log(`\nError occured while trying to determine profitability...\n`)
        console.log(`This can typically happen because an issue with reserves, see README for more information.\n`)
        return false
    }
}
```

- [ ] **Step 3: Syntax-check the file**

Run: `node --check bot.js`
Expected: no output, exit code 0 (parses cleanly). Full behavioral verification requires a running Ganache mainnet fork + Alchemy key + migrated contract (see README); that is a manual step, not part of the automated gate.

- [ ] **Step 4: Re-run the unit tests to confirm nothing regressed**

Run: `npm test`
Expected: PASS — `All arbitrage-math tests passed`.

- [ ] **Step 5: Commit**

```bash
git add bot.js
git commit -m "feat: use optimal input sizing and fee-aware gate in determineProfitability"
```

---

## Manual Verification (post-implementation, optional)

Requires the README setup (Ganache fork, `.env`, `truffle migrate --reset`):

1. Start Ganache forking mainnet with the SHIB-holding account unlocked.
2. `truffle migrate --reset`, then `node ./bot.js`.
3. In another terminal: `node ./scripts/manipulatePrice.js` to open a spread.
4. Confirm the bot logs an "Optimal WETH In" that is a sane fraction of pool liquidity (not the whole reserve) and a positive "Net Profit (WETH)" before executing.

---

## Self-Review Notes

- **Spec coverage:** #1 optimal sizing → `optimalInput` + Task 2 wiring. #2 fee-aware gate → `x <= 0` rejection + net-profit-after-gas check. Token-ordering bug fix → `mapReserves` (Task 1) + address-based flags (Task 2). Tests → Task 1 Step 2. `npm test` wiring → Task 1 Step 4. All spec "Files Touched" are covered.
- **Out of scope confirmed untouched:** `Arbitrage.sol`, dynamic gas, minAmountOut/MEV.
- **Type consistency:** `optimalInput`/`estimateProfit`/`mapReserves`/`DEFAULT_FEE` names identical across module, tests, and bot.js. `estimateProfit` returns `{ amountIn, amountOut, grossProfit }` (all `Big`) — consumed with `.toFixed(0)` / `.lte` / `.gt` accordingly.
```
