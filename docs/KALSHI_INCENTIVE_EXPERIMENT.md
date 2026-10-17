# Automated Alpha — Kalshi liquidity incentives feasibility gate (READ ONLY)

**Purpose:** Identify whether any *visible* order books have active incentive periods and enough two-sided depth that a hypothetical $100 join on either side could reach the program's depth gate. No orders. **The experiment does not forecast or earn a reward.** It cannot replicate random per-second Kalshi snapshots, queue priority, maker fills, member-specific payouts, market-specific eligibility, or trading P&L.

## Documented mechanism

- Public definitions: `GET https://external-api.kalshi.com/trade-api/v2/incentive_programs?status=active&type=liquidity` (paginated via `next_cursor`). Then public `GET /markets/{ticker}/orderbook`.
- Each program has its **own** target size, discount factor, reward pool, and dates; overlapping incentive periods may exist. We do not combine pool totals and do not treat an *event* program reward as a per-market pool.
- Kalshi samples books **every second at random moments**. Both sides must meet target size for that snapshot to count. Relative score, order price, queue/fill risks, period duration and market rules materially affect actual payout. Resting orders CAN fill and lose principal.
- The API docs currently do not explicitly specify units for the integer `period_reward`. The analysis preserves the **raw value** without converting to dollars. Cross-check program pool with the Kalshi market Rewards badge **before** using dollar economics. Any externally reported unit conversion is unverified until confirmed against Kalshi's actual UI for the same market/period.
- Markets in Illinois and account eligibility must be confirmed directly with the exchange and under current law; do not assume sports contracts or their incentive rewards are available. Do not evade restrictions.

Sources: https://docs.kalshi.com/api-reference/incentive-programs/get-incentives ; https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program ; https://help.kalshi.com/en/articles/16076644-liquidity-incentive-programs-where-to-find-them

## Test phases

1. **Discovery:** Four samples a day over 72 hours; public API only, 500 programs/page, max five pages and 16 orderbooks/scan (four fixed top-pool anchors plus up to twelve rotating every six hours), max $100 notional per hypothetical quote. Everything lives in separate `alpha-incentive-history` branch and downloadable GitHub Actions artifacts. Clock cadence is best-effort.
2. **Screen:** Group by exact market, not event. Validate program dates/type and two-sided target depth; price a **hypothetical passive bid joining an existing level**. Report full modeled principal at risk, visible depth and missing facts. **Depth eligibility is not personal order eligibility**. Do not assert earnings based on reward pool amounts.
3. **Decision after 72 hours:** Count scanned programs; how many different markets had visibly adequate two-sided depth in repeated samples; how often depth disappeared; capital required; competition risks; whether program reward units and Illinois/market eligibility were verified. If no consistently favorable books, stop. If some qualify, next step is richer public tick-level sampling and an explicit reward-vs-adverse-selection scenario model—not depositing money or automatic orders.

## Stop / no-go gates

- **Immediate stop** if public incentives API cannot be validated, terms materially change, or exchange/jurisdiction/account restrictions block it.
- **No trial funding** without explicit approval of maximum capital/loss, verified market rules and reward credits, and a market-making risk plan for being filled. A reward estimate based on posted quotes alone is insufficient.
- **No earnings target from this test**; `actual_rewards_earned_usd=0` by construction.

## Run locally

```bash
python -m unittest discover -s tests -q
python -m alpha.incentive_research --pages 3 --page-size 300 --max-books 12 --budget 100 --out output/kalshi-incentives.json
```

This command makes only public GETs. No account login/API keys, private keys, live trading, borrowed funds, or payments.
