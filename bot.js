// -- HANDLE INITIAL SETUP -- //

require('./helpers/server')
require("dotenv").config();

const config = require('./config.json')
const { getTokenAndContract, getPairContract, calculatePrice, getEstimatedReturn, getReserves } = require('./helpers/helpers')
const { uFactory, uRouter, sFactory, sRouter, web3, arbitrage } = require('./helpers/initialization')
const Big = require('big.js')
const { optimalInput, estimateProfit, mapReserves } = require('./helpers/arbitrage-math')

// -- .ENV VALUES HERE -- //

const arbFor = process.env.ARB_FOR // This is the address of token we are attempting to arbitrage (WETH)
const arbAgainst = process.env.ARB_AGAINST // SHIB
const account = process.env.ACCOUNT // Account to recieve profit
const units = process.env.UNITS // Used for price display/reporting
const difference = process.env.PRICE_DIFFERENCE
const gas = process.env.GAS_LIMIT
const estimatedGasCost = process.env.GAS_PRICE // Estimated Gas: 0.008453220000006144 ETH + ~10%

let uPair, sPair, amount
let isExecuting = false

const main = async () => {
    const { token0Contract, token1Contract, token0, token1 } = await getTokenAndContract(arbFor, arbAgainst)
    uPair = await getPairContract(uFactory, token0.address, token1.address)
    sPair = await getPairContract(sFactory, token0.address, token1.address)

    console.log(`uPair Address: ${uPair._address}`)
    console.log(`sPair Address: ${sPair._address}\n`)

    uPair.events.Swap({}, async () => {
        if (!isExecuting) {
            isExecuting = true

            const priceDifference = await checkPrice('Uniswap', token0, token1)
            const routerPath = await determineDirection(priceDifference)

            if (!routerPath) {
                console.log(`No Arbitrage Currently Available\n`)
                console.log(`-----------------------------------------\n`)
                isExecuting = false
                return
            }

            const isProfitable = await determineProfitability(routerPath, token0Contract, token0, token1)

            if (!isProfitable) {
                console.log(`No Arbitrage Currently Available\n`)
                console.log(`-----------------------------------------\n`)
                isExecuting = false
                return
            }

            const receipt = await executeTrade(routerPath, token0Contract, token1Contract)

            isExecuting = false
        }
    })

    sPair.events.Swap({}, async () => {
        if (!isExecuting) {
            isExecuting = true

            const priceDifference = await checkPrice('Sushiswap', token0, token1)
            const routerPath = await determineDirection(priceDifference)

            if (!routerPath) {
                console.log(`No Arbitrage Currently Available\n`)
                console.log(`-----------------------------------------\n`)
                isExecuting = false
                return
            }

            const isProfitable = await determineProfitability(routerPath, token0Contract, token0, token1)

            if (!isProfitable) {
                console.log(`No Arbitrage Currently Available\n`)
                console.log(`-----------------------------------------\n`)
                isExecuting = false
                return
            }

            const receipt = await executeTrade(routerPath, token0Contract, token1Contract)

            isExecuting = false
        }
    })

    console.log("Waiting for swap event...")
}

const checkPrice = async (exchange, token0, token1) => {
    isExecuting = true

    console.log(`Swap Initiated on ${exchange}, Checking Price...\n`)

    const currentBlock = await web3.eth.getBlockNumber()

    const uPrice = await calculatePrice(uPair)
    const sPrice = await calculatePrice(sPair)

    const uFPrice = Number(uPrice).toFixed(units)
    const sFPrice = Number(sPrice).toFixed(units)
    const priceDifference = (((uFPrice - sFPrice) / sFPrice) * 100).toFixed(2)

    console.log(`Current Block: ${currentBlock}`)
    console.log(`-----------------------------------------`)
    console.log(`UNISWAP   | ${token1.symbol}/${token0.symbol}\t | ${uFPrice}`)
    console.log(`SUSHISWAP | ${token1.symbol}/${token0.symbol}\t | ${sFPrice}\n`)
    console.log(`Percentage Difference: ${priceDifference}%\n`)

    return priceDifference
}

const determineDirection = async (priceDifference) => {
    console.log(`Determining Direction...\n`)

    if (priceDifference >= difference) {

        console.log(`Potential Arbitrage Direction:\n`)
        console.log(`Buy\t -->\t Uniswap`)
        console.log(`Sell\t -->\t Sushiswap\n`)
        return [uRouter, sRouter]

    } else if (priceDifference <= -(difference)) {

        console.log(`Potential Arbitrage Direction:\n`)
        console.log(`Buy\t -->\t Sushiswap`)
        console.log(`Sell\t -->\t Uniswap\n`)
        return [sRouter, uRouter]

    } else {
        return null
    }
}

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

const executeTrade = async (_routerPath, _token0Contract, _token1Contract) => {
    console.log(`Attempting Arbitrage...\n`)

    let startOnUniswap

    if (_routerPath[0]._address == uRouter._address) {
        startOnUniswap = true
    } else {
        startOnUniswap = false
    }

    // Fetch token balance before
    const balanceBefore = await _token0Contract.methods.balanceOf(account).call()
    const ethBalanceBefore = await web3.eth.getBalance(account)

    if (config.PROJECT_SETTINGS.isDeployed) {
        await arbitrage.methods.executeTrade(startOnUniswap, _token0Contract._address, _token1Contract._address, amount).send({ from: account, gas: gas })
    }

    console.log(`Trade Complete:\n`)

    // Fetch token balance after
    const balanceAfter = await _token0Contract.methods.balanceOf(account).call()
    const ethBalanceAfter = await web3.eth.getBalance(account)

    const balanceDifference = balanceAfter - balanceBefore
    const totalSpent = ethBalanceBefore - ethBalanceAfter

    const data = {
        'ETH Balance Before': web3.utils.fromWei(ethBalanceBefore, 'ether'),
        'ETH Balance After': web3.utils.fromWei(ethBalanceAfter, 'ether'),
        'ETH Spent (gas)': web3.utils.fromWei((ethBalanceBefore - ethBalanceAfter).toString(), 'ether'),
        '-': {},
        'WETH Balance BEFORE': web3.utils.fromWei(balanceBefore.toString(), 'ether'),
        'WETH Balance AFTER': web3.utils.fromWei(balanceAfter.toString(), 'ether'),
        'WETH Gained/Lost': web3.utils.fromWei(balanceDifference.toString(), 'ether'),
        '-': {},
        'Total Gained/Lost': `${web3.utils.fromWei((balanceDifference - totalSpent).toString(), 'ether')} ETH`
    }

    console.table(data)
}

main()
