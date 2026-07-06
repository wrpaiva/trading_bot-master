# Stellar/Soroban Arbitrage Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and test a Soroban smart contract that executes an atomic two-leg arbitrage across Soroban AMMs and reverts unless it ends with a guaranteed minimum profit.

**Architecture:** A stateless (except `admin`) Rust contract holds a working balance of a base asset. Its `arb` entrypoint runs two cross-contract swaps (buy on AMM A, sell on AMM B) inside one atomic transaction, then asserts the closing balance grew by at least `min_profit` — panicking (reverting the whole transaction) otherwise. Swap calls go through a per-protocol dispatcher so the profit-guard core is tested against **mock routers**, independent of any live AMM.

**Tech Stack:** Rust, `soroban-sdk` (v22.x), `stellar` CLI (contract build/deploy), Soroban test framework.

## Global Constraints

- Contract language: Rust with `#![no_std]`, `soroban-sdk` — copied verbatim from spec ("The on-chain contract on Soroban is mandatorily Rust/WASM").
- Base asset flow: every arbitrage cycle **enters and exits in the same asset** (`asset` parameter). Never end holding a different token.
- Custody model: contract holds a working balance funded once; only `admin` may call `arb` or `withdraw`.
- Safety invariant: `arb` MUST revert (panic) when `final_balance < balance_before + min_profit`. This is the capital-protection guarantee — no code path may bypass it.
- No leverage, no flash loans — swaps operate only on the contract's own held balance.
- Nothing runs against mainnet or real funds in this plan. Deploy target is **testnet only**.

---

## File Structure

```
stellar-arb/
└── contracts/
    └── arbitrage/
        ├── Cargo.toml           # crate manifest, soroban-sdk dep + testutils
        ├── Makefile             # build/test shortcuts
        └── src/
            ├── lib.rs           # contract entrypoints: init, arb, withdraw
            ├── types.rs         # DataKey, Protocol, SwapLeg, ArbError
            ├── adapters.rs      # swap_on dispatcher + per-protocol router calls
            └── test.rs          # unit tests w/ mock token + mock routers
```

Responsibilities:
- `types.rs` — all `#[contracttype]` / `#[contracterror]` definitions. No logic.
- `adapters.rs` — the only place that knows AMM router call shapes. `swap_on(env, leg, token_in, amount_in) -> i128`.
- `lib.rs` — entrypoints + the profit guard. Depends on `types` and `adapters`.
- `test.rs` — mock router contracts + mock token; drives every entrypoint.

---

## Task 1: Scaffold the contract crate

**Files:**
- Create: `stellar-arb/contracts/arbitrage/Cargo.toml`
- Create: `stellar-arb/contracts/arbitrage/src/lib.rs`
- Create: `stellar-arb/contracts/arbitrage/Makefile`

**Interfaces:**
- Consumes: nothing.
- Produces: a buildable empty contract crate; `ArbContract` struct exists.

- [ ] **Step 1: Create `Cargo.toml`**

```toml
[package]
name = "arbitrage"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib", "rlib"]

[dependencies]
soroban-sdk = "22"

[dev-dependencies]
soroban-sdk = { version = "22", features = ["testutils"] }

[profile.release]
opt-level = "z"
overflow-checks = true
debug = 0
strip = "symbols"
lto = true
panic = "abort"
codegen-units = 1
```

- [ ] **Step 2: Create minimal `src/lib.rs`**

```rust
#![no_std]
use soroban_sdk::{contract, contractimpl, Env};

#[contract]
pub struct ArbContract;

#[contractimpl]
impl ArbContract {
    /// Placeholder so the crate builds; replaced in Task 3.
    pub fn version(_env: Env) -> u32 {
        1
    }
}

#[cfg(test)]
mod test;
```

Note: `mod test;` references a file created in Task 4. Until then, comment out the last two lines OR create an empty `src/test.rs`. Create an empty `src/test.rs` now to keep the crate compiling.

- [ ] **Step 3: Create empty `src/test.rs`**

```rust
// Tests added in Task 4.
```

- [ ] **Step 4: Create `Makefile`**

```makefile
build:
	stellar contract build

test:
	cargo test

fmt:
	cargo fmt --all
```

- [ ] **Step 5: Verify it builds**

Run: `cd stellar-arb/contracts/arbitrage && cargo build`
Expected: compiles with no errors.

- [ ] **Step 6: Commit**

```bash
git add stellar-arb/contracts/arbitrage
git commit -m "feat: scaffold Soroban arbitrage contract crate"
```

---

## Task 2: Types and errors

**Files:**
- Create: `stellar-arb/contracts/arbitrage/src/types.rs`
- Modify: `stellar-arb/contracts/arbitrage/src/lib.rs` (add `mod types;`)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `enum Protocol { Soroswap, Phoenix }` (`#[contracttype]`)
  - `struct SwapLeg { protocol: Protocol, router: Address, token_out: Address, amount_out_min: i128 }` (`#[contracttype]`)
  - `enum DataKey { Admin }` (`#[contracttype]`)
  - `enum ArbError { AlreadyInitialized = 1, NotInitialized = 2, NotProfitable = 3 }` (`#[contracterror]`)

- [ ] **Step 1: Write `src/types.rs`**

```rust
use soroban_sdk::{contracterror, contracttype, Address};

#[contracttype]
#[derive(Clone, PartialEq, Eq, Debug)]
pub enum Protocol {
    Soroswap,
    Phoenix,
}

/// One hop of the arbitrage cycle.
#[contracttype]
#[derive(Clone, Debug)]
pub struct SwapLeg {
    pub protocol: Protocol,
    pub router: Address,
    pub token_out: Address,
    pub amount_out_min: i128,
}

#[contracttype]
#[derive(Clone)]
pub enum DataKey {
    Admin,
}

#[contracterror]
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u32)]
pub enum ArbError {
    AlreadyInitialized = 1,
    NotInitialized = 2,
    NotProfitable = 3,
}
```

- [ ] **Step 2: Wire the module into `lib.rs`**

Add near the top of `src/lib.rs`, after the `#![no_std]` line:

```rust
mod types;
```

- [ ] **Step 3: Verify it builds**

Run: `cd stellar-arb/contracts/arbitrage && cargo build`
Expected: compiles (warnings about unused items are fine at this stage).

- [ ] **Step 4: Commit**

```bash
git add stellar-arb/contracts/arbitrage/src
git commit -m "feat: add contract types and error enum"
```

---

## Task 3: init + admin storage + withdraw (with auth)

**Files:**
- Modify: `stellar-arb/contracts/arbitrage/src/lib.rs`
- Test: `stellar-arb/contracts/arbitrage/src/test.rs` (filled in Task 4; this task ships the impl, Task 4 proves it)

**Interfaces:**
- Consumes: `types::{DataKey, ArbError}`.
- Produces:
  - `ArbContract::init(env: Env, admin: Address)` — stores admin, panics `AlreadyInitialized` if called twice.
  - `ArbContract::withdraw(env: Env, asset: Address, amount: i128, to: Address)` — requires admin auth, transfers `asset` out.
  - internal `read_admin(env: &Env) -> Address` (panics `NotInitialized` if unset).

- [ ] **Step 1: Replace `src/lib.rs` body with the entrypoints**

```rust
#![no_std]
mod types;
mod adapters; // created in Task 5; add now, create the file in Task 5's step 1

use soroban_sdk::{contract, contractimpl, panic_with_error, token, Address, Env};
use types::{ArbError, DataKey};

#[contract]
pub struct ArbContract;

#[contractimpl]
impl ArbContract {
    pub fn init(env: Env, admin: Address) {
        if env.storage().instance().has(&DataKey::Admin) {
            panic_with_error!(&env, ArbError::AlreadyInitialized);
        }
        env.storage().instance().set(&DataKey::Admin, &admin);
    }

    pub fn withdraw(env: Env, asset: Address, amount: i128, to: Address) {
        let admin = read_admin(&env);
        admin.require_auth();
        token::Client::new(&env, &asset).transfer(
            &env.current_contract_address(),
            &to,
            &amount,
        );
    }
}

fn read_admin(env: &Env) -> Address {
    env.storage()
        .instance()
        .get(&DataKey::Admin)
        .unwrap_or_else(|| panic_with_error!(env, ArbError::NotInitialized))
}

#[cfg(test)]
mod test;
```

Note: `mod adapters;` is declared here but the file is created in Task 5, Step 1. To keep this task compiling on its own, create `src/adapters.rs` now containing only `// filled in Task 5`. Do that as the next step.

- [ ] **Step 2: Create placeholder `src/adapters.rs`**

```rust
// swap_on dispatcher added in Task 5.
```

- [ ] **Step 3: Verify it builds**

Run: `cd stellar-arb/contracts/arbitrage && cargo build`
Expected: compiles.

- [ ] **Step 4: Commit**

```bash
git add stellar-arb/contracts/arbitrage/src
git commit -m "feat: add init, admin storage, and admin-gated withdraw"
```

---

## Task 4: Test harness — mock token + mock router, prove init/withdraw

**Files:**
- Modify: `stellar-arb/contracts/arbitrage/src/test.rs`

**Interfaces:**
- Consumes: `ArbContract` client, `soroban_sdk::testutils`.
- Produces:
  - `make_token(env, admin) -> (Address, StellarAssetClient)` helper (creates a test asset, returns its address + admin client for minting).
  - A registered `MockRouter` contract whose `swap_exact_tokens_for_tokens(...)` returns a configurable output. Used by Task 5.
  - Passing tests: `test_init_sets_admin`, `test_init_twice_panics`, `test_withdraw_moves_funds`, `test_withdraw_requires_auth`.

- [ ] **Step 1: Write the mock token helper + init tests (failing)**

```rust
#![cfg(test)]
use soroban_sdk::testutils::Address as _;
use soroban_sdk::{token, Address, Env};
use crate::{ArbContract, ArbContractClient};

fn make_token<'a>(env: &Env, admin: &Address) -> (Address, token::StellarAssetClient<'a>) {
    let sac = env.register_stellar_asset_contract_v2(admin.clone());
    let addr = sac.address();
    (addr.clone(), token::StellarAssetClient::new(env, &addr))
}

fn setup<'a>(env: &Env) -> (ArbContractClient<'a>, Address) {
    let admin = Address::generate(env);
    let contract_id = env.register(ArbContract, ());
    let client = ArbContractClient::new(env, &contract_id);
    (client, admin)
}

#[test]
fn test_init_sets_admin() {
    let env = Env::default();
    env.mock_all_auths();
    let (client, admin) = setup(&env);
    client.init(&admin);
    // A second init must fail (proven separately); here we just assert no panic.
}

#[test]
#[should_panic]
fn test_init_twice_panics() {
    let env = Env::default();
    env.mock_all_auths();
    let (client, admin) = setup(&env);
    client.init(&admin);
    client.init(&admin); // AlreadyInitialized
}
```

- [ ] **Step 2: Run tests to verify they fail/pass appropriately**

Run: `cd stellar-arb/contracts/arbitrage && cargo test`
Expected: `test_init_sets_admin` PASS, `test_init_twice_panics` PASS (panics as required). If a compile error about `ArbContractClient` occurs, ensure `#[contractimpl]` is present (it generates the client).

- [ ] **Step 3: Add withdraw tests**

Append to `src/test.rs`:

```rust
#[test]
fn test_withdraw_moves_funds() {
    let env = Env::default();
    env.mock_all_auths();
    let (client, admin) = setup(&env);
    client.init(&admin);

    let (asset, asset_admin) = make_token(&env, &admin);
    let contract_addr = client.address.clone();
    asset_admin.mint(&contract_addr, &1_000);

    let dest = Address::generate(&env);
    client.withdraw(&asset, &400, &dest);

    let tok = token::Client::new(&env, &asset);
    assert_eq!(tok.balance(&dest), 400);
    assert_eq!(tok.balance(&contract_addr), 600);
}

#[test]
#[should_panic]
fn test_withdraw_requires_auth() {
    let env = Env::default();
    // NOTE: no mock_all_auths() -> require_auth must fail
    let (client, admin) = setup(&env);
    env.mock_all_auths();
    client.init(&admin);
    env.set_auths(&[]); // clear mocked auths
    let (asset, _) = make_token(&env, &admin);
    client.withdraw(&asset, &1, &admin); // should panic: not authorized
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd stellar-arb/contracts/arbitrage && cargo test`
Expected: all four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add stellar-arb/contracts/arbitrage/src/test.rs
git commit -m "test: cover init and admin-gated withdraw"
```

---

## Task 5: The `arb` core + profit guard (against mock routers)

This is the safety-critical task. The profit guard is proven here.

**Files:**
- Modify: `stellar-arb/contracts/arbitrage/src/adapters.rs`
- Modify: `stellar-arb/contracts/arbitrage/src/lib.rs` (add `arb`)
- Modify: `stellar-arb/contracts/arbitrage/src/test.rs` (mock router + arb tests)

**Interfaces:**
- Consumes: `types::{SwapLeg, Protocol, ArbError}`, `token::Client`.
- Produces:
  - `adapters::swap_on(env: &Env, leg: &SwapLeg, token_in: &Address, amount_in: i128) -> i128` — invokes the leg's router and returns the received amount.
  - `ArbContract::arb(env, asset: Address, amount_in: i128, min_profit: i128, leg_a: SwapLeg, leg_b: SwapLeg)` — admin-gated, atomic, profit-guarded.

- [ ] **Step 1: Implement `swap_on` in `src/adapters.rs`**

Both target routers (Soroswap and, later, Phoenix) are invoked through a Uniswap-V2-style
`swap_exact_tokens_for_tokens`. Task 6 verifies/branches the exact per-protocol shape; here we
implement the common Soroswap shape and route both variants through it so the core is testable now.

```rust
use soroban_sdk::{vec, Address, Env, IntoVal, Symbol, Val, Vec};
use crate::types::SwapLeg;

/// Executes one swap leg and returns the amount of `leg.token_out` received.
pub fn swap_on(env: &Env, leg: &SwapLeg, token_in: &Address, amount_in: i128) -> i128 {
    let to = env.current_contract_address();
    let deadline: u64 = env.ledger().timestamp() + 300;

    let path: Vec<Address> = vec![env, token_in.clone(), leg.token_out.clone()];

    let args: Vec<Val> = vec![
        env,
        amount_in.into_val(env),
        leg.amount_out_min.into_val(env),
        path.into_val(env),
        to.into_val(env),
        deadline.into_val(env),
    ];

    // Returns Vec<i128> of amounts along the path; last element is amount_out.
    let amounts: Vec<i128> = env.invoke_contract(
        &leg.router,
        &Symbol::new(env, "swap_exact_tokens_for_tokens"),
        args,
    );
    amounts.last().unwrap()
}
```

- [ ] **Step 2: Add `arb` to `src/lib.rs`**

Add inside `impl ArbContract`, and add imports `use types::{SwapLeg};` and `use adapters::swap_on;`:

```rust
    pub fn arb(
        env: Env,
        asset: Address,
        amount_in: i128,
        min_profit: i128,
        leg_a: SwapLeg,
        leg_b: SwapLeg,
    ) {
        let admin = read_admin(&env);
        admin.require_auth();

        let token = token::Client::new(&env, &asset);
        let me = env.current_contract_address();
        let balance_before = token.balance(&me);

        // Leg A: asset -> token_out(A). Approve router to pull amount_in.
        token.approve(&me, &leg_a.router, &amount_in, &(env.ledger().sequence() + 200));
        let mid = swap_on(&env, &leg_a, &asset, amount_in);

        // Leg B: token_out(A) -> asset. Approve router to pull `mid`.
        let mid_token = leg_a.token_out.clone();
        token::Client::new(&env, &mid_token)
            .approve(&me, &leg_b.router, &mid, &(env.ledger().sequence() + 200));
        let _out = swap_on(&env, &leg_b, &mid_token, mid);

        let balance_after = token.balance(&me);
        // PROFIT GUARD — capital-protection invariant.
        if balance_after < balance_before + min_profit {
            panic_with_error!(&env, ArbError::NotProfitable);
        }
    }
```

Ensure `SwapLeg` is imported: change the `use types::...` line in `lib.rs` to
`use types::{ArbError, DataKey, SwapLeg};` and add `mod adapters;` already declared, plus
`use adapters::swap_on;`.

- [ ] **Step 3: Add a configurable mock router to `src/test.rs`**

```rust
use soroban_sdk::{contract as sdk_contract, contractimpl as sdk_contractimpl, vec, Vec};

// A mock AMM router: on swap, it pulls `amount_in` of path[0] from the caller
// and mints/sends back a fixed `rate`-scaled amount of path[last].
#[sdk_contract]
pub struct MockRouter;

#[sdk_contractimpl]
impl MockRouter {
    // rate is basis points: out = amount_in * rate / 10_000
    pub fn swap_exact_tokens_for_tokens(
        env: Env,
        amount_in: i128,
        _amount_out_min: i128,
        path: Vec<Address>,
        to: Address,
        _deadline: u64,
    ) -> Vec<i128> {
        let token_in = path.first().unwrap();
        let token_out = path.last().unwrap();
        // pull input from caller
        token::Client::new(&env, &token_in)
            .transfer(&to, &env.current_contract_address(), &amount_in);
        // rate stored in instance under symbol "rate"
        let rate: i128 = env
            .storage()
            .instance()
            .get(&soroban_sdk::symbol_short!("rate"))
            .unwrap_or(10_000);
        let out = amount_in * rate / 10_000;
        // send output to caller (mock must be pre-funded with token_out)
        token::Client::new(&env, &token_out)
            .transfer(&env.current_contract_address(), &to, &out);
        vec![&env, amount_in, out]
    }

    pub fn set_rate(env: Env, rate: i128) {
        env.storage().instance().set(&soroban_sdk::symbol_short!("rate"), &rate);
    }
}
```

- [ ] **Step 4: Write the profitable-arb test (failing first)**

```rust
#[test]
fn test_arb_profitable_succeeds() {
    let env = Env::default();
    env.mock_all_auths();
    let (client, admin) = setup(&env);
    client.init(&admin);

    let (asset, asset_admin) = make_token(&env, &admin);
    let (mid_tok, mid_admin) = make_token(&env, &admin);
    let me = client.address.clone();

    // Fund arb contract with working capital.
    asset_admin.mint(&me, &1_000);

    // Register two mock routers.
    let router_a = env.register(MockRouter, ());
    let router_b = env.register(MockRouter, ());
    let ra = MockRouterClient::new(&env, &router_a);
    let rb = MockRouterClient::new(&env, &router_b);

    // Router A gives 100 mid per 100 asset (rate 10000); pre-fund with mid.
    ra.set_rate(&10_000);
    mid_admin.mint(&router_a, &10_000);
    // Router B gives 110 asset per 100 mid (rate 11000, i.e. +10%); pre-fund with asset.
    rb.set_rate(&11_000);
    asset_admin.mint(&router_b, &10_000);

    let leg_a = SwapLeg { protocol: Protocol::Soroswap, router: router_a, token_out: mid_tok.clone(), amount_out_min: 0 };
    let leg_b = SwapLeg { protocol: Protocol::Soroswap, router: router_b, token_out: asset.clone(), amount_out_min: 0 };

    client.arb(&asset, &100, &1, &leg_a, &leg_b);

    // 100 asset -> 100 mid -> 110 asset. Net +10 on the 1000 balance = 1010.
    let tok = token::Client::new(&env, &asset);
    assert_eq!(tok.balance(&me), 1_010);
}
```

Add the required imports at the top of `test.rs`:
`use crate::types::{Protocol, SwapLeg};`

- [ ] **Step 5: Run to verify it passes**

Run: `cd stellar-arb/contracts/arbitrage && cargo test test_arb_profitable_succeeds`
Expected: PASS (balance 1010). If it fails on approvals, confirm `mock_all_auths()` is set.

- [ ] **Step 6: Write the unprofitable-arb test (must revert)**

```rust
#[test]
#[should_panic] // ArbError::NotProfitable
fn test_arb_unprofitable_reverts() {
    let env = Env::default();
    env.mock_all_auths();
    let (client, admin) = setup(&env);
    client.init(&admin);

    let (asset, asset_admin) = make_token(&env, &admin);
    let (mid_tok, mid_admin) = make_token(&env, &admin);
    let me = client.address.clone();
    asset_admin.mint(&me, &1_000);

    let router_a = env.register(MockRouter, ());
    let router_b = env.register(MockRouter, ());
    MockRouterClient::new(&env, &router_a).set_rate(&10_000);
    mid_admin.mint(&router_a, &10_000);
    // Router B gives only 95 back -> loss.
    MockRouterClient::new(&env, &router_b).set_rate(&9_500);
    asset_admin.mint(&router_b, &10_000);

    let leg_a = SwapLeg { protocol: Protocol::Soroswap, router: router_a, token_out: mid_tok.clone(), amount_out_min: 0 };
    let leg_b = SwapLeg { protocol: Protocol::Soroswap, router: router_b, token_out: asset.clone(), amount_out_min: 0 };

    // min_profit = 1 but the round trip loses 5 -> must panic and revert.
    client.arb(&asset, &100, &1, &leg_a, &leg_b);
}
```

- [ ] **Step 7: Run to verify the guard reverts**

Run: `cd stellar-arb/contracts/arbitrage && cargo test test_arb_unprofitable_reverts`
Expected: PASS (the test asserts a panic). Because the transaction panics, the mid/asset moves are rolled back — verify by adding, in a separate non-panicking variant if desired, that balance stays 1000. (Atomic revert is guaranteed by Soroban.)

- [ ] **Step 8: Write the non-admin test**

```rust
#[test]
#[should_panic]
fn test_arb_requires_admin_auth() {
    let env = Env::default();
    let (client, admin) = setup(&env);
    env.mock_all_auths();
    client.init(&admin);
    env.set_auths(&[]); // no auths -> admin.require_auth() fails

    let (asset, _) = make_token(&env, &admin);
    let (mid_tok, _) = make_token(&env, &admin);
    let router = env.register(MockRouter, ());
    let leg = SwapLeg { protocol: Protocol::Soroswap, router: router.clone(), token_out: mid_tok.clone(), amount_out_min: 0 };
    let leg2 = SwapLeg { protocol: Protocol::Soroswap, router, token_out: asset.clone(), amount_out_min: 0 };
    client.arb(&asset, &100, &1, &leg, &leg2);
}
```

- [ ] **Step 9: Run the full suite**

Run: `cd stellar-arb/contracts/arbitrage && cargo test`
Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add stellar-arb/contracts/arbitrage/src
git commit -m "feat: add atomic arb entrypoint with on-chain profit guard"
```

---

## Task 6: Verify + branch real router interfaces (Soroswap + Phoenix)

The core is proven. Now make `swap_on` call the **real** routers. Their signatures must be verified against current docs/contracts before coding — do not assume.

**Files:**
- Modify: `stellar-arb/contracts/arbitrage/src/adapters.rs`

**Interfaces:**
- Consumes: `types::{SwapLeg, Protocol}`.
- Produces: `swap_on` branches on `leg.protocol` and builds the correct call per AMM.

- [ ] **Step 1: Fetch the Soroswap router interface**

Run (WebFetch): `https://docs.soroswap.finance/` — router / SoroswapRouter contract reference.
Record the exact function name and argument order for the swap entrypoint. Expected (verify):
`swap_exact_tokens_for_tokens(amount_in: i128, amount_out_min: i128, path: Vec<Address>, to: Address, deadline: u64) -> Vec<i128>`.

- [ ] **Step 2: Fetch the Phoenix router/multihop interface**

Run (WebFetch): Phoenix protocol docs (search "Phoenix Stellar multihop swap contract interface").
Record the exact swap entrypoint name and args. Phoenix commonly uses a `swap` on a multihop
contract taking an `operations`/`swaps` vector rather than a Uniswap-style path — capture the
real shape.

- [ ] **Step 3: Branch `swap_on` by protocol**

Rewrite `swap_on` to `match leg.protocol`: keep the Soroswap branch from Task 5, and add a
Phoenix branch that builds Phoenix's verified argument shape. Use the exact names/types recorded
in Steps 1–2. Return the received `amount_out` in both branches.

(Code is written against the Step 1–2 findings; if Phoenix's interface differs from a simple
path call, encode its operation-vector argument here.)

- [ ] **Step 4: Update tests so both branches are exercised**

The `MockRouter` already matches the Soroswap shape. If the Phoenix branch uses a different
signature, add a `MockPhoenixRouter` in `test.rs` with the matching entrypoint, and a
`test_arb_soroswap_to_phoenix` test analogous to `test_arb_profitable_succeeds` but with
`leg_b.protocol = Protocol::Phoenix`.

- [ ] **Step 5: Run the suite**

Run: `cd stellar-arb/contracts/arbitrage && cargo test`
Expected: all tests PASS, including cross-protocol.

- [ ] **Step 6: Commit**

```bash
git add stellar-arb/contracts/arbitrage/src
git commit -m "feat: wire real Soroswap and Phoenix router adapters"
```

---

## Task 7: Build WASM + deploy to testnet + smoke docs

**Files:**
- Create: `stellar-arb/contracts/arbitrage/DEPLOY.md`

**Interfaces:**
- Consumes: the built contract.
- Produces: deployment instructions and a recorded testnet contract id.

- [ ] **Step 1: Build the optimized WASM**

Run: `cd stellar-arb/contracts/arbitrage && stellar contract build`
Expected: a `.wasm` under `target/wasm32v1-none/release/arbitrage.wasm` (or the path the CLI prints). Record the exact path.

- [ ] **Step 2: Create a funded testnet identity**

```bash
stellar keys generate arb-bot --network testnet --fund
stellar keys address arb-bot
```

- [ ] **Step 3: Deploy to testnet**

```bash
stellar contract deploy \
  --wasm target/wasm32v1-none/release/arbitrage.wasm \
  --source arb-bot --network testnet
```
Record the printed contract id.

- [ ] **Step 4: Initialize the contract**

```bash
stellar contract invoke --id <CONTRACT_ID> --source arb-bot --network testnet \
  -- init --admin $(stellar keys address arb-bot)
```
Expected: no error.

- [ ] **Step 5: Write `DEPLOY.md`**

Capture: the exact build output path, the testnet contract id, the admin address, and the
init/withdraw/arb invoke command templates used above. This file is the handoff to Plan 2 (the
off-chain bot), which needs the contract id and interface.

- [ ] **Step 6: Commit**

```bash
git add stellar-arb/contracts/arbitrage/DEPLOY.md
git commit -m "docs: add testnet deploy guide and record contract id"
```

---

## Self-Review

**Spec coverage:**
- Custom Rust profit-guarded contract → Tasks 3, 5. ✓
- Custody model (fund once, admin-only, withdraw anytime) → Tasks 3, 4. ✓
- `swap_on` per-protocol adapter dispatcher (MVP 2 protocols) → Tasks 5, 6. ✓
- Double protection (`amount_out_min` per leg + final guard) → `SwapLeg.amount_out_min` (Task 2) passed into `swap_on` (Task 5) + guard (Task 5). ✓
- Contract tests: reverts when unprofitable, succeeds with spread, admin-only → Task 5 Steps 4/6/8. ✓
- Testnet-first, no real funds → Task 7 (testnet only); mainnet explicitly excluded by Global Constraints. ✓
- Off-chain bot (detector/sizer/simulator/executor) → **deferred to Plan 2** (out of scope here, by design).

**Placeholder scan:** The only research-first steps (Task 6 Steps 1–2) are genuine external-interface lookups, not code placeholders; the code steps that follow reference the recorded signatures. No "TODO/TBD" in code.

**Type consistency:** `SwapLeg` fields (`protocol`, `router`, `token_out`, `amount_out_min`), `Protocol::{Soroswap, Phoenix}`, `ArbError::{AlreadyInitialized, NotInitialized, NotProfitable}`, and `swap_on(env, leg, token_in, amount_in) -> i128` are used identically across Tasks 2, 5, 6. `arb` signature is stable between lib.rs (Task 5) and tests (Task 5). ✓

**Note on SDK specifics:** exact `soroban-sdk` v22 method names (`register_stellar_asset_contract_v2`, `env.register`, `set_auths`) should be confirmed against the installed SDK version during Task 1; adjust minor naming if the pinned version differs. This is the one place to reconcile at execution time.
