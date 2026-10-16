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
