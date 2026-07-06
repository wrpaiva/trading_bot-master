# Design: Atomic Multi-AMM Arbitrage Bot on Stellar/Soroban

**Date:** 2026-07-04
**Status:** Approved design — pending implementation plan
**Author:** Washington (with Claude)

## Context and Motivation

The user wants to experiment with real-money arbitrage using ~$100 of capital.
The existing repo (Ethereum/Solidity/web3.js, Uniswap↔Sushiswap, DyDx flash loans)
is **not reusable** for this goal:

- On Ethereum mainnet, per-transaction gas ($20–100+) would consume the entire
  $100 in a handful of failed attempts.
- Uniswap/Sushiswap arbitrage is dominated by professional MEV bots on private
  mempools; a public bot cannot compete.
- DyDx Solo Margin (the flash-loan provider in the current contract) is
  effectively deprecated.

**Stellar changes the economics decisively for a small-capital experiment:**

- Fee per operation ≈ 0.00001 XLM (a fraction of a cent), so "gas eats the
  capital" is not a concern.
- Arbitrage can be made **atomic**: if a cycle is not profitable, the whole
  transaction reverts and the only cost is the tiny fee.
- No flash loans needed — the bot trades with its own capital.

This is explicitly a **learning + small-consistent-profit** experiment with
near-zero downside, **not** a guaranteed money-maker. Opportunities are thin,
irregular, and contested by other bots. The value is real algorithmic-execution
experience with minimal financial risk.

## Goal

Small, consistent profit via **market-neutral arbitrage** — never a directional
bet. Each cycle starts and ends in the same base asset (USDC); it either closes
with profit atomically or reverts.

## Key Constraint Discovered

**Atomic SDEX ↔ Soroban arbitrage is impossible at the protocol level:**

1. A Stellar transaction may contain **either** classic operations **or** a
   single Soroban `InvokeHostFunction` operation — never both.
   (https://developers.stellar.org/docs/learn/fundamentals/transactions/operations-and-transactions)
2. The Soroswap Aggregator executes only across Soroban-based protocols; the
   classic SDEX is excluded from on-chain execution.
   (https://docs.soroswap.finance/01-concepts/aggregator)

Crossing SDEX↔Soroban would require **two separate transactions** → non-atomic →
"stuck-leg" risk, which violates the minimal-risk requirement.

**Decision:** Arbitrage **only among Soroban AMMs** (Soroswap ↔ Phoenix ↔ Aqua)
within a **single atomic contract call**.

## Decisions Summary

| Area | Decision |
|---|---|
| Strategy | Atomic arbitrage among Soroban AMMs (Soroswap/Phoenix/Aqua) |
| Execution | Custom Soroban arbitrage contract (Rust) with on-chain profit guard |
| Off-chain bot | TypeScript/Node |
| Base asset | USDC (native, Circle) |
| Capital | ~$100: ~$88 USDC working capital, ~$10 XLM fees/reserves, ~$2 buffer |
| Custody | Fund the contract once; bot only triggers `arb`; withdraw anytime |
| Rollout | Testnet-first, then mainnet with real $100 |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  OFF-CHAIN BOT (TypeScript/Node)                            │
│  1. Detector  → Soroswap API: quote same pair on            │
│                 Soroswap / Phoenix / Aqua → find divergence │
│  2. Sizer     → optimal trade size (both pools' reserves ∩  │
│                 working capital)                            │
│  3. Simulator → build arb() tx, run simulateTransaction     │
│                 (real result + Soroban resource fees)       │
│  4. Executor  → sign with admin key, submit, await result   │
│  5. Logger    → record every attempt (size, profit, fee)    │
└───────────────────────────┬─────────────────────────────────┘
                            │ invokes arb(...)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  ARBITRAGE CONTRACT (Rust/Soroban) — 1 atomic call          │
│  arb(asset, amount_in, min_profit, leg_a, leg_b):           │
│    swap asset→X on AMM A                                     │
│    swap X→asset on AMM B                                     │
│    require(final_balance >= amount_in + min_profit) // panic│
└───────────────────────────┬─────────────────────────────────┘
                            ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ Soroswap │   │ Phoenix  │   │   Aqua   │
        └──────────┘   └──────────┘   └──────────┘
```

### Boundary principles

- **Detection and execution are separated.** The bot only *decides*; the
  profit guarantee lives on-chain. A bug in the bot's math cannot cause a loss
  beyond the tiny fee — the on-chain `require` protects the capital.
- **The contract is "dumb and safe":** no speculative state, no custody trust —
  it receives parameters, runs the round-trip, reverts if not profitable.
- **The Soroswap API is used only for detection** (aggregated quotes). Execution
  calls the AMM routers directly, because the aggregator does not perform the
  arbitrage cycle by itself.

### Out of scope (YAGNI)

Classic SDEX, flash loans (do not exist here — own capital only), and many
simultaneous pairs in the MVP.

## Component: Soroban Contract (Rust)

### Custody model

Deposit working capital (e.g., 90 USDC) into the contract **once**. The bot never
holds funds — it only triggers `arb`. Profit accumulates in the contract;
withdraw anytime. The user's key is the `admin` — only it can trigger `arb` or
`withdraw`. This avoids per-transaction auth complexity and follows the standard
arbitrage-contract pattern (idle working balance + bot that only triggers).

### Interface (sketch)

```rust
#[contract]
pub struct ArbContract;

#[contractimpl]
impl ArbContract {
    // one-time: sets who is in control
    pub fn init(env: Env, admin: Address);

    // the core — atomic. Reverts if not profitable.
    pub fn arb(
        env: Env,
        asset: Address,       // base asset (e.g., USDC) — enters and exits in it
        amount_in: i128,      // how much of the working fund to use this cycle
        min_profit: i128,     // minimum acceptable profit (in asset units)
        leg_a: SwapLeg,       // {protocol, router, token_out} — first leg
        leg_b: SwapLeg,       // second leg, back to asset
    ) {
        admin.require_auth();                                  // only owner triggers
        let bal_before = token(&env, &asset).balance(&contract);

        let mid = swap_on(&env, &leg_a, asset, amount_in);     // asset -> X (AMM A)
        let _   = swap_on(&env, &leg_b, leg_a.token_out, mid); // X -> asset (AMM B)

        let bal_after = token(&env, &asset).balance(&contract);
        // PROFIT GUARD — on failure, panic => whole tx reverts (cost ≈ fee)
        if bal_after < bal_before + min_profit {
            panic_with_error!(&env, Error::NotProfitable);
        }
    }

    pub fn withdraw(env: Env, asset: Address, amount: i128, to: Address); // admin.require_auth()
}
```

### Design points

- **`swap_on` is an adapter dispatcher:** each AMM (Soroswap/Phoenix/Aqua) has a
  different router interface, so a small per-protocol `match` calls the correct
  router. The **MVP implements 2 adapters** (Soroswap + Phoenix); Aqua is added
  later — keeps the contract small and auditable.
- **Double protection:** each leg carries an `amount_out_min` (bounds mid-cycle
  slippage) **and** the final profit guard.
- **No state beyond `admin`:** nothing to corrupt; reentrancy is not a vector
  (single call, closed round-trip).
- **`min_profit` covers the fee:** the bot passes a `min_profit` already
  including network + resource fee plus a margin, so contract-level "profit" =
  real profit.
- Deployed and hardened on **testnet** before any real USDC.

## Component: Off-chain Bot (TypeScript/Node)

```
src/
├── config.ts       # network, RPC, contractId, pairs, thresholds, poll interval
├── detector.ts     # quote pair on each AMM via Soroswap API → find divergence
├── sizer.ts        # optimal trade size (both pools' reserves ∩ working capital)
├── simulator.ts    # build arb() tx, run simulateTransaction (RPC)
├── executor.ts     # sign with admin key, submit; await result
├── logger.ts       # record each attempt: pair, size, profit, fee, status
└── index.ts        # the orchestration loop
```

### Loop per cycle

1. **Detector** — for each target pair (e.g., USDC/XLM), fetch quotes on Soroswap,
   Phoenix, and Aqua via the **Soroswap API**; compute price divergence.
2. **Fast gate** — if divergence does not cover `fee + minimum margin`, discard
   immediately (cheap, no network call).
3. **Sizer** — compute the `amount_in` that **maximizes profit** given both pools'
   reserves, bounded by the working capital in the contract.
4. **Simulator** — build the `arb(...)` call and run `simulateTransaction`. Returns
   the **real result + Soroban resource fees** (compute/storage) without sending.
5. **Decision** — recompute `min_profit = base_fee + resource_fee + margin`. If the
   simulation shows net profit > 0, proceed; otherwise discard.
6. **Executor** — sign with the `admin` key (from `.env`, never committed) and
   submit. Await confirmation.
7. **Logger** — record everything to measure real profitability over time.

### Design decisions

- **Two filters before spending network:** the mathematical gate (step 2) and the
  simulation (step 4). Only transactions the network itself confirms as profitable
  get signed.
- **`min_profit` is dynamic:** computed each cycle from the real fee returned by
  simulation — never a fixed guess.
- **The `admin` key lives in `.env`** (gitignored); MVP runs locally or on a cheap
  VPS; starting on **testnet** with test key and funds.
- **Declarative config:** change pairs, thresholds, and interval without touching
  code.

## Assets and Capital ($100)

Base asset = **USDC** (native, Circle) so P&L is measured in a stable dollar unit.

| Slice | Amount | Purpose |
|---|---|---|
| Working capital (USDC) | ~$88 | deposited in the contract; runs the cycles |
| XLM for fees + reserves | ~$10 | Stellar minimum reserve (~0.5 XLM per trustline/entry) + fees |
| Buffer | ~$2 | margin for surprises |

- **MVP pairs: 1–2** — starting with **USDC/XLM** (most liquid), optionally
  **USDC/AQUA**.
- **XLM reserves are not spent** — recoverable on closing trustlines/account; only
  locked while running.

## Security, Risk, and Rollout

- **Dedicated wallet:** a keypair used **only** for this bot, holding only the
  ~$100. Never the main wallet. A leak limits damage to the experiment capital.
- **Secret key:** only in `.env` (gitignored), never logged, never committed.
- **Exit button:** the `withdraw` (admin) function lets you pull everything at any
  time.
- **No leverage, no flash loans, no credit.** Own capital only. Max real downside:
  attempt fees + contract-bug risk (mitigated by heavy testing + the profit guard).
- **Non-negotiable deploy order:** testnet (free funds via friendbot) → validate
  end-to-end → only then mainnet with the $100.
- **Operational resilience:** RPC downtime, API rate limits, contention with other
  bots — the loop handles the error and resumes monitoring (no crash, no blind
  retry).

## Testing

- **Contract (Rust):** unit tests in the Soroban test environment with **mocked
  routers/AMMs** — prove that (a) it reverts when
  `final_balance < amount_in + min_profit`, (b) it closes with profit when a spread
  exists, (c) only `admin` can trigger `arb`/`withdraw`.
- **Bot (TS):** unit tests for the **detector** and **sizer** math (given reserves,
  the optimal size and estimated profit match), and an integration test for the
  **simulator**.
- **Testnet integration:** deploy the contract, force a price divergence between
  two test pools, and observe **both paths**: profitable arb closes; unprofitable
  arb reverts for free.
- **No real USDC** until everything is green on testnet.

## Open Questions / Deferred

- Exact router interfaces for Soroswap / Phoenix / Aqua (to be confirmed against
  current on-chain contracts during implementation).
- Whether to run the loop locally or on a VPS for the mainnet phase (operational,
  not architectural).
- Adding the Aqua adapter and additional pairs after the MVP proves out.
