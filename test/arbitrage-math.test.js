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
