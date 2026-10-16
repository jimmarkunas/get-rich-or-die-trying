# Automated Alpha v0.1 — READ ONLY

Three scanner modules sharing a local observation ledger:

1. **Kalshi**: reads public market/order-book REST endpoints. Calculates implied asks from opposing bids and depth-aware basket costs; flags a *candidate* only when you have independently verified every leg's settlement-equivalence/partition assumption. Special fee schedules and non-atomic execution remain unverified. Merely comparing similar-looking markets is unsafe.
2. **Aave V3**: reads on-chain `getUserAccountData(address)` for explicitly watched wallets. Flags health-factor conditions; it cannot calculate profit until per-reserve debts, collateral, close-factor, bonus, swaps and inclusion costs are known. NOT an automated borrower discovery engine.
3. **Flash AMM**: reads reserves and token addresses from two manually configured, Uniswap-V2-compatible pools at a *single block number*. Estimates round-trip token0 profit after pool fees, assumed flash fee and assumed gas. No executor, MEV inclusion, aggregator routing, historical simulation or atomic transaction simulation. Positive indications are NOT executable opportunities.

## Safety and security

- Read-only by construction: Kalshi **GET** requests only; Ethereum JSON-RPC allows only `eth_call`, `eth_chainId`, `eth_blockNumber`.
- NO wallet keys, deposits, order submission, transactions, flash-loan contracts, market maker automation, account scraping, production deployment or spending.
- No arbitrary token lookup: manually verify pool deployments and asset decimals before assessing base units.
- RPC URLs can contain tokens: keep config in `config.json`, which is gitignored. Operational logs omit URL query strings, but avoid provider secrets in URL paths.
- Market-specific fees vary. `0.07 * count * price * (1-price)` rounded up to cents is an *assumption* for baseline Kalshi prediction contracts, not the final exchange charge.
- Market quotes are **not atomic**; both sides cannot necessarily be filled at the observed price.
- Kalshi one-market complementary-side scan is a structural diagnostic (normally no positive edge). Multi-market baskets must be externally verified as exactly exhaustive and mutually exclusive; `payout_partition_verified` defaults to false. Scanning doesn't independently prove this.
- No positive returns, actionable trades, or rapid profits are implied by any record.

## Local setup (Python 3.10+, standard library only)

```bash
cp config.example.json config.json
python -m unittest discover -s tests -v
python -m alpha scan --config config.json --engine kalshi
python -m alpha report --ledger output/opportunities.jsonl --out output/dashboard.html
```

The first scan requires internet access. For Aave and flash AMM, configure an **Ethereum mainnet** HTTPS JSON-RPC endpoint plus real watchlist addresses / V2-compatible pools in `config.json`. Omitting those entries safely disables their actual fetches. The Kalshi example queries open KXHIGHNY markets; if none are open, it records zero observations, not zero opportunities across Kalshi.

To run repeated scans on a controlled host (never faster than one/minute):

```bash
python -m alpha scan --config config.json --interval-seconds 300 --cycles 0
```

Use a systemd service or cron under your control for persistence; this chat does not host a continuous monitor. Watch rate limits, TOS, uptime and operating costs. Do not enable live execution without a separate design and express approval.

## Data

- `output/opportunities.jsonl`: append-only observations, timestamped UTC. Not actual fills or P&L.
- `output/dashboard.html`: standalone HTML dashboard (last 500 observations); open locally in any browser.
- On errors, the CLI reports an error instead of inventing data.

## Next gated milestones

1. Confirm live market-data access from intended host, check response schemas and market-specific fees; benchmark time to data and rate limits.
2. Automatically index relevant markets and retrieve authoritative settlement rules; verify market combinations and full outcome coverage.
3. Add Aave user discovery, collateral/debt detail, parameter lookup and liquidation calculations; do not estimate bonus from health factor alone.
4. Add per-pool fee verification, token decimals, gas oracle, flash-loan premium direct onchain and bundled transaction simulation; test price impact, inclusion and MEV risk.
5. At least a week of timestamped read-only observations and a controlled paper-trading ledger before considering real money.

## Sources

- Kalshi API docs: https://docs.kalshi.com/getting_started/quick_start_market_data
- Kalshi orderbook: https://docs.kalshi.com/api-reference/market/get-market-orderbook
- Kalshi fee schedule: https://kalshi.com/fee-schedule
- Aave Pool V3: https://aave.com/docs/aave-v3/smart-contracts/pool
- Aave flash loans: https://aave.com/docs/aave-v3/guides/flash-loans
- Aave deployed addresses: https://github.com/aave-dao/aave-address-book

## GitHub deployment: zero-secret live data pilot (v0.2)

**Recommended via the connected GitHub app:** Create a **private** repository named `jimmarkunas/automated-alpha` and **add a starter README** so the default `main` branch exists. Then ask ChatGPT to publish this package's source files through the connected GitHub app, replacing the starter README with this one. The connected app can edit files inside an existing repository but cannot create a new repository. Keep `config.json` and `output/` out of Git (both are gitignored). This is a standalone project, not part of LIFE OS.

**Alternative using your own Mac:** If you'll do the entire push from Git CLI, create the repository **without** a starter README, clone or extract this package locally, and follow the commands below. Those git commands are not needed with the connected-app approach.

Two Actions workflows are included:

- `Read-only unit tests`: validates program logic on every push and manual trigger; does not access live exchanges.
- `Read-only market snapshot`: manually triggerable or scheduled at minute 17 each hour. Fetches **public Kalshi data only**, runs the unit tests, produces a standalone HTML dashboard and JSONL observations, and uploads a seven-day-retention run artifact. No API keys are needed. An empty valid series response is recorded as `no_open_markets_in_configured_series`, not a profitable opportunity.

First smoke test: open the repository's **Actions** tab -> **Read-only market snapshot** -> **Run workflow**. Open the finished workflow run and download `alpha-snapshot-*` under **Artifacts**. Open `dashboard.html` locally to view the snapshot. A passing run proves the public API and workflow function; it does **not** establish an executable trade or profit.

**Limitations:** GitHub Actions isn't a low-latency execution environment. Scheduled runs may be delayed or skipped. Each run starts a new snapshot—there is no cross-run persistent history yet. Use a persistent data store on a dedicated host only once the observation pipeline is live-verified. Do not add any Kalshi account keys, wallet seed phrases, or private keys to this pilot. The Aave and flash-AMM modules need an Ethereum RPC URL and manually verified targets and are **not** included in the scheduled workflow.

Alternative: push from a Mac after creating an **empty** repository:

```bash
cd automated-alpha
git init -b main
git add .
git commit -m "Initialize Automated Alpha read-only scanners"
git remote add origin https://github.com/jimmarkunas/automated-alpha.git
git push -u origin main
```

No trading automation or live-money transaction execution exists in this repository. **No production deployment of other projects is performed.**

## Kalshi autonomous discovery — v0.3 (read-only)

`python -m alpha discover --ledger output/discovery.jsonl --pages 2 --max-events 12 --quantity 10`

The new scanner uses `GET /events?status=open&with_nested_markets=true` and
screens the **exchange-provided** `mutually_exclusive=true` flag. For an event
with two distinct, standard, binary markets and normal full-payoff settlement,
two purchased NO positions have a conditional **minimum of one winning leg**,
without assuming the event is an exhaustive YES partition. It prices only
complete, depth-matched NO purchases using real orderbooks, rounding assumed
taker fees conservatively and adding a cash buffer. Indicative positive prices
produce `candidate_rule_review_required` — **not** executable arbitrage or
verified profits. The linked contract rules/full rulebook, special settlement
conditions, fee schedule, and possible non-atomic failure must be reviewed
before ANY trading. Market rule excerpts are screened automatically for known
red flags, not certified as exhaustive.

### Durable history + alerts

The new `discover-kalshi.yml` workflow runs hourly at :37 (subject to Actions
delays), writes a bounded rolling 15,000-observation JSONL and 24-hour alert
deduplication state to the separate `alpha-history` Git branch, and uploads
HTML/JSONL artifacts for 30 days. Only *new* positive screening results generate
GitHub **REVIEW REQUIRED** issues; no orders or authenticated trading calls.
GitHub issue notifications depend on your watch preferences. The `alpha-history`
branch must exist and GitHub Actions must allow `GITHUB_TOKEN` contents and issue
writes. Because repository is public, all research history and issues are
public; NEVER put keys, account identifiers or secret configurations there.

Docs: https://docs.kalshi.com/api-reference/events/get-events and
https://docs.kalshi.com/api-reference/market/get-market-orderbook

## v0.4 — Profitability-validation research gate (NO live trading)

This iteration fixes the discovery sampling bias and adds **bounded, read-only**
DeFi research. On-chain observations are **not flash-loan transaction simulations**.
A positive computed AMM round trip is a theoretical price-impact-aware
opportunity, not a verified executable transaction, profit, or claim that we can
compete with MEV operators.

### Kalshi: selection + size sensitivity

- Rank mutually exclusive event pairs by *indicative asks* (tie-break on
  published liquidity), not alphabetic tickers. Rotate ties across hours.
- Query depth once per selected pair, test up to five whole-unit quantities.
- Do not label metadata-screened rules as independently legally verified.
- Optional command: `python -m alpha discover --pages 2 --max-events 12 --quantities 5,10,25`.

### Base / Arbitrum: paired V2 factory research

`python -m alpha research --engine dex --chain base --config config.research.example.json --ledger output/base.jsonl`

`python -m alpha research --engine dex --chain arbitrum --config config.research.example.json --ledger output/arbitrum.jsonl`

- Reads Uniswap-V2-style `getPair` from the two configured DEX factories
  for a **verified token-address pair**, then pool reserves at a pinned block.
- Tests both round-trip directions and three token0 position sizes with
  constant-product price impact, assumed pool fees, assumed flash premium and
  assumed gas. Verifies on-chain token addresses and ERC-20 decimals.
- Does **not** verify actual pool fee schedules, perform transaction bundles,
  submit transactions, model MEV competition or compute USD profits.
- Base/Arbitrum public RPCs are rate-limited and unsuitable for high-volume
  or latency-sensitive production. The factory and token deployment lists must
  be reverified onchain when running against new chains or changing contracts.

### Aave: recent borrower sampling, not complete liquidation indexing

`python -m alpha research --engine aave --config config.research.example.json --ledger output/aave.jsonl`

- Gets at most 2,000 blocks of **Borrow** event logs from the specified Aave
  V3 Pool address, extracts indexed debt-owner `onBehalfOf`, deduplicates, and
  reads sampled health factors at the same block. Default lookback is 100.
- Recent Borrow logs do not cover borrowers whose debt originated before the
  window, and a low health factor is not a net-positive liquidation trade.
  Per-reserve debt/collateral/bonus and full execution costs remain unmodeled.

### Evidence scoreboard

`python -m alpha.scoreboard --ledgers output/*.jsonl --days 7 --out output/scoreboard.json`

The scoreboard counts observations, types, and indicative net where USD is
actually reported. **Realized profit remains unknown, with zero verified fills.**

`Profitability research (read only)` GitHub Actions runs unit tests and
three separate public-RPC probes (Base, Arbitrum, Ethereum Aave) on a push to
main touching its code and on manual dispatch. They publish research artifacts
without credentials or trade permissions. Public RPC rejection is a legitimate
**FAIL**, not proof there are no opportunities. It is not a scheduled
low-latency trading system. A seven-day research gate requires repeated,
validated runs; one test is insufficient. No money, signing, borrowing,
portfolio data or LIFE OS production integrations are involved.

Sources: [Uniswap v2 deployments](https://developers.uniswap.org/docs/protocols/v2/deployments),
[Aave V3 Pool Borrow event interface](https://github.com/aave-dao/aave-v3-origin/blob/main/src/contracts/interfaces/IPool.sol),
[Base RPC limits](https://basehub.org/api-reference/rpc-overview/),
[Arbitrum RPC](https://docs.arbitrum.io/chain-info).

## v0.5 — Automated spot crypto research (paper only)

This optional new research lane analyzes **Binance.US** public hourly candles for
BTCUSD, ETHUSD, and SOLUSD. It never creates orders, uses accounts, requests API
keys, borrows money or trades with leverage. Paper portfolios are *fictional*:
$1,000 per symbol *per strategy*, rather than your own balances.

### What is actually being compared

- **Momentum:** 12h/48h moving average and price trend, 3% model exit stop.
- **Grid-style reversion:** buy below a 24h average and sell above it or on a
  3.5% model exit stop. This is a *signal-based taker* reversion experiment, NOT
  a maker grid order-book simulation and not a claim of passive grid income.
- Both are **spot, long-only**; max a quarter of cash per entry, no margin.
- Assumes 0.02% taker fee, plus **0.05% unfavorable price slippage per side**.
  Exact live fees, fills, spreads, and price impact may be different.
- Backtests use *completed* one-hour candles for 90 days; signals from the
  previous completed bar; simulated fills at the **following bar open**.
  Previous-bar volume caps trades; future-bar volume is never used for fills.
- First ~60 days are development; the last 30 days are **untouched holdout**.
  Both are run with fixed parameters; a 25%-invested buy-and-hold benchmark is
  reported on holdout. Holdout results are not a prediction.
- Forward paper records use a contemporaneously observed Binance.US best
  ask/bid plus adverse modeled slippage. First run **seeds** positions without
  trading; subsequent new-bar observations can produce fictional fills. Long
  offline gaps **skip** trading rather than backfill imaginary execution.
  Top-of-book quantity must cover the full hypothetical order. Public quote
  API has no timestamp, so an observed quote is not evidence of real execution.
- Historical backtest and forward data are never combined into reported real
  earnings. No live orders, paid feeds, keys, or alerts firing real trades.

### How to run

```bash
python -m unittest discover -s tests -q
python -m alpha.crypto_cli backtest --days 90 --out output/crypto-backtest.json
python -m alpha.crypto_cli forward --state-out output/new-paper-state.json \
  --observations output/crypto-paper-observations.jsonl
python -m alpha.crypto_dashboard --backtest output/crypto-backtest.json \
  --state output/new-paper-state.json --out output/crypto-dashboard.html
```

Run the `Crypto spot paper research (no trading)` GitHub Actions workflow for
one hosted API test. After publication, it runs at minute 13 hourly (GitHub
scheduling is best-effort), archives state to the separate `alpha-crypto-history`
branch, and publishes reports and an HTML dashboard. On an initial run, paper
portfolios are seeded but **no pretend past trades** are created. An API error
fails the job; no manufactured $0 performance or false success is recorded.
The 90-day backtest is regenerated on manually dispatched/push runs, and once
daily at approximately 05:13 UTC on scheduled runs. The historical report is
persisted with the paper state and made available in an Actions artifact.

**Gate for any live trading:** separate user authorization, platform eligibility,
fee/minimum-order verification, wider backtesting, out-of-sample performance,
actual order-book execution model and limits, plus a significant *forward* paper
sample. This version cannot submit trades.

Official sources: [Binance.US API](https://docs.binance.us/),
[Binance.US fees](https://www.binance.us/fees).
