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
