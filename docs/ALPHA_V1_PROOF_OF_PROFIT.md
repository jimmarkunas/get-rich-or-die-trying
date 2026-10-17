# Automated Alpha v1.0 — Proof-of-Profit (read-only)

## Hard limits
- Zero live orders, no authentication, no accounts connected, no wallet transfers, no trading SDK, no deposits. No private endpoints.
- Hypothetical capital **$900 total**, indicative buy notional **$150**. Two-venue trading needs **cash prefunded on the buy venue AND coin inventory pre-owned on the sell venue**. Not capital-free arbitrage.
- Public order books are sequential/non-atomic; not proof of executable liquidity, simultaneous fill, trade permission or quote freshness.
- Every positive spread remains unverified. No orders, keys, or live capital without separate explicit approval.

## Sources and fees
- Binance.US public USD book BTC/ETH/SOL; first-tier non-Tier-0 spot taker 0.02%. https://www.binance.us/fees
- Kraken public USD order book; conservative tier-1 taker 0.80%. https://www.kraken.com/features/fee-schedule
- Coinbase Exchange public USD book, discovery ONLY. 1.2% placeholder cost is not account-specific Coinbase Advanced pricing. No assumed account eligibility.
- Bitnomial US public BTCUC funding-rate estimated REST endpoint, **8-hour** settlement intervals, not Coinbase hourly futures. https://bitnomial.com/exchange/docs/api/rest/funding-rates/
- Binance.US lists Illinois supported and Texas unsupported, but neither individual nor LLC approval is verified. https://support.binance.us/en/articles/9842798-list-of-supported-and-unsupported-states-and-regions
- Kraken US and Coinbase US futures existence is public; user eligibility, state, fees, precise contract sizing and authenticated data are NOT verified.

## Cross-exchange cost test
- Buy exact base quantity by walking actual asks, within $150 gross cash including venue taker fee.
- Sell that exact quantity into opposite venue bids. Require full available depth.
- Subtract both taker fees, assumed 10bp adverse movement **on each leg**, 30bp inventory-rebalance cost, and 10bp latency buffer.
- Reject stale sequential snapshots spanning over 12 seconds; reject insufficient bids/asks; ignore opportunities under $0.50 after costs.
- Positive hypothetical net does NOT establish trade success; no guarantee books remain when orders arrive.
- Total cash/inventory across both venues must remain below $900, require funded accounts and ability to exit and rebalance.

## US funding-rate engine
- Public Bitnomial **estimated** current 8-hour BTCUC rate, not a guaranteed next payment or guaranteed persistent yield.
- Report gross for ONE 8-hour interval on $150 only. Always leave net profit NULL until futures bid/ask, minimum contract size, full fees, margin/reserves, size-matched spot hedge, and exit cost are verified.
- Rate sign may reverse: positive tends to pay shorts, negative charges shorts. Leverage can liquidate.

## Profit-validation gates (explicit human authorization)
1. Observe real public data at least 72 hours, record latency/failures and repeated after-fee positive spreads.
2. Verify current account-specific fees, eligibility, KYC, Texas LLC vs Illinois residency, balances, contract size, minimum orders and transfer/withdrawal costs.
3. Show executable two-leg costs under realistic latency and size-matched hedging; compute downside under delayed/failed hedge or margin shock.
4. Review live microtrade plan with written maximum loss. Obtain **new explicit user approval** for any actual order, credentials, capital movement or leverage.
5. If gates fail, NO-GO. No fabricated retroactive fills or extrapolated earnings.

## Run
Tests: python -m unittest discover -s tests -v
Scanner: python -m alpha.profit_v1 --out output/alpha-v1.json
Scheduled GitHub research: .github/workflows/alpha-v1-profit.yml
Persistent summary branch: alpha-v1-history / history/scans.jsonl

## Hosted smoke-test findings and repair, 2026-10-17
- Initial hosted GitHub run 39063881530: 14 spread scenarios, 0 positive, Coinbase BTC full L2 depth over safety cap, and Bitnomial first funding URL returned HTTP 404.
- Fixed Coinbase to public Level-1 best bid/ask; insufficient top-book size rejects (never assumes deeper availability).
- Bitnomial endpoint documentation contradicts itself about the /prod prefix. Try documented example path, then /prod on transport error; if both unavailable, record explicit funding-source failure. No overseas-data substitution.
- Bitnomial BTC centi perpetual minimum **0.01 BTC**, confirmed via CFTC filing: https://bitnomial.com/exchange/regulatory/cftc/product-filings/26-036.pdf
- At BTC $80,000, cash spot hedge for 0.01 BTC costs $800. The exchange clearinghouse baseline of 15% (estimate, FCM may require more) brings spot + derivatives margin to **at least ~$920 before fees**, exceeding our $900 simulation cap. This is a blocker even if the rate API works; another, smaller contract could change eligibility but requires separate review.
