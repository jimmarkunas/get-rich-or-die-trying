# Automated Alpha v0.2 — READ ONLY

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

The first scan requires internet access. For Aave and flash AMM, configure an **Ethereum mainnet** HTTPS JSON-RPC endpoint plus real watchlist addresses / V2-compatible pools in `config.json`. Omitting those entries safely disables their actual fetches. The Kalshi example queries open KXHIGHNY markets; if none are open, it records a `no_open_markets_in_configured_series` heartbeat; this does not imply zero opportunities elsewhere.

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

## GitHub deployment: zero-secret live-data pilot (v0.2)

Repository: https://github.com/jimmarkunas/get-rich-or-die-trying

**Important:** This repository is currently **public**. NEVER commit API keys, wallet private keys, credentials, or personal account details. The supplied `config.example.json` has no secrets; `config.json` and `output/` are excluded from version control.

GitHub Actions workflows:

- **Read-only unit tests** run on pushes and pull requests.
- **Read-only market snapshot** runs after scanner/workflow changes on `main`, at minute 17 of each hour (UTC; scheduling may be delayed), or manually via `Actions → Read-only market snapshot → Run workflow`. It reads public Kalshi markets, reruns unit tests, generates a JSONL observation file plus static HTML report, and uploads them as a seven-day artifact.

**Inspect results:** Open [Actions](https://github.com/jimmarkunas/get-rich-or-die-trying/actions), choose a completed **Read-only market snapshot**, download the `alpha-snapshot-*` artifact under Artifacts, and open `dashboard.html` locally.

**Pilot acceptance:** A successful live run with a valid public API response and dashboard artifact confirms the read-only data pipeline, **not** a profitable trade. Check individual error and classification counts in the logs. A healthy heartbeat is not a candidate trade. Only the Kalshi pilot runs on GitHub Actions; Aave and AMM scanners remain configuration-driven and inactive without a verified RPC and target list.

**Next:** discover settlement-verified event baskets, persist snapshots across runs, validate fee rules and executable depth, then separately instrument DeFi data. Keep any real trade execution behind explicit approval; this project contains no trading sender.
