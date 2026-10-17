"""Automated Alpha v1: public-data spot spreads and US funding observations.

READ ONLY: no credentials, SDKs, order endpoints, or wallet interactions.
Every finding is indicative, NEVER an executable or guaranteed profit.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

SPOT_MARKETS = {
    "BTC": {"binance_us": "BTCUSD", "kraken": "XBTUSD", "coinbase_exchange": "BTC-USD"},
    "ETH": {"binance_us": "ETHUSD", "kraken": "ETHUSD", "coinbase_exchange": "ETH-USD"},
    "SOL": {"binance_us": "SOLUSD", "kraken": "SOLUSD", "coinbase_exchange": "SOL-USD"},
}
# Conservative first-tier public fee ASSUMPTIONS, not the user's verified tier.
# Coinbase Exchange order book is a discovery feed, NOT proof of Advanced execution fees.
TAKER_FEES = {
    "binance_us": Decimal("0.0002"), "kraken": Decimal("0.008"),
    "coinbase_exchange": Decimal("0.012"),
}
CAPITAL_LIMIT = Decimal("900")       # Total paper bankroll is below $1,000.
TRADE_NOTIONAL = Decimal("150")      # Gross cash PER indicative leg (not deployable).
SLIPPAGE_EACH = Decimal("0.001")     # 10 bps per leg adverse shock
REBALANCE_RATE = Decimal("0.003")    # 30 bps estimated future inventory rebalance
LATENCY_BUFFER = Decimal("0.001")    # 10 bps two-venue execution uncertainty
MIN_SIGNAL_USD = Decimal("0.50")
MAX_SCAN_SECONDS = 12
BITNOMIAL = "https://bitnomial.com/exchange/api/v1/funding-rates/estimated/BTCUC"
BITNOMIAL_ALTERNATE = "https://bitnomial.com/exchange/api/v1/prod/funding-rates/estimated/BTCUC"
# Base symbols from Bitnomial US product listings. All estimates stay read-only.
FUNDING_CONTRACTS = {"BTCUC": ("BTC", Decimal("0.01")),
                     "ETHUI": ("ETH", Decimal("0.5")),
                     "SOLUS": ("SOL", Decimal("5"))}
ALLOW = {
    "api.binance.us": ("/api/v3/depth",),
    "api.kraken.com": ("/0/public/Depth",),
    "api.exchange.coinbase.com": tuple("/products/" + v["coinbase_exchange"] + "/book" for v in SPOT_MARKETS.values()),
    "bitnomial.com": tuple(prefix + product
                           for prefix in ("/exchange/api/v1/funding-rates/estimated/",
                                          "/exchange/api/v1/prod/funding-rates/estimated/")
                           for product in FUNDING_CONTRACTS),
}
ZERO = Decimal("0")


def dec(x):
    try:
        v = Decimal(str(x))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid decimal") from exc
    if not v.is_finite():
        raise ValueError("nonfinite market datum")
    return v


def money(x):
    return str(dec(x).quantize(Decimal("0.000001")))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def public_get(url, *, params=None, opener=urlopen):
    """Strict HTTPS GET endpoint allowlist; no auth, account, orders or withdrawals."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port or parsed.fragment:
        raise ValueError("unsupported endpoint")
    if parsed.hostname not in ALLOW or parsed.path not in ALLOW[parsed.hostname] or parsed.query:
        raise ValueError("public endpoint allowlist violation")
    query = urlencode(params or {})
    req = Request(url + ("?" + query if query else ""), method="GET",
                  headers={"User-Agent": "AutomatedAlpha-ReadOnly-v1.0", "Accept": "application/json"})
    with opener(req, timeout=8) as response:
        raw = response.read(700001)
        if len(raw) > 700000:
            raise ValueError("overlong public response")
        return json.loads(raw)


def normalize(bids, asks):
    """Require positive, finite prices/sizes; reject duplicate and crossed books."""
    def side(levels, reverse):
        if not isinstance(levels, list) or not levels:
            raise ValueError("empty depth")
        res = []
        seen = set()
        for v in levels:
            if not isinstance(v, (list, tuple)) or len(v) < 2:
                raise ValueError("bad depth row")
            p, q = dec(v[0]), dec(v[1])
            if p <= 0 or q <= 0 or p in seen:
                raise ValueError("invalid/duplicate depth")
            seen.add(p)
            res.append((p, q))
        return sorted(res, key=lambda x: x[0], reverse=reverse)
    bid, ask = side(bids, True), side(asks, False)
    if bid[0][0] >= ask[0][0]:
        raise ValueError("crossed local order book")
    return {"bids": bid, "asks": ask}


def parse_book(venue, payload):
    if venue == "binance_us":
        return normalize(payload["bids"], payload["asks"])
    if venue == "kraken":
        if payload.get("error") != [] or len(payload.get("result", {})) != 1:
            raise ValueError("kraken returned errors or ambiguous pair")
        raw = next(iter(payload["result"].values()))
        return normalize(raw["bids"], raw["asks"])
    if venue == "coinbase_exchange":
        return normalize(payload["bids"], payload["asks"])
    raise ValueError("unsupported venue")


def fetch_spot(coin, venue, *, get=public_get):
    symbol = SPOT_MARKETS[coin][venue]
    if venue == "binance_us":
        endpoint = "https://api.binance.us/api/v3/depth"
        params = {"symbol": symbol, "limit": 20, "symbolStatus": "TRADING"}
    elif venue == "kraken":
        endpoint = "https://api.kraken.com/0/public/Depth"
        params = {"pair": symbol, "count": 20}
    else:
        endpoint = "https://api.exchange.coinbase.com/products/" + symbol + "/book"
        # Level-2 BTC can exceed response safety cap; BBO level 1 is bounded.
        # Reject if top-of-book depth is insufficient; no fabricated deeper fills.
        params = {"level": 1}
    start = time.monotonic()
    book = parse_book(venue, get(endpoint, params=params))
    return {
        "book": book, "read_at_utc": utc_now(),
        "fetch_seconds": round(time.monotonic() - start, 4),
        "venue": venue, "coin": coin, "public_symbol": symbol,
        "usd_settlement_confirmed": False,
        "user_venue_account_verified": False,
    }


def buy_with_budget(book, cash, fee):
    """Simulate removing asks, including buy fee in the fixed cash ceiling."""
    fee, cash = dec(fee), dec(cash)
    if cash <= 0 or fee < 0:
        raise ValueError("bad budget or fee")
    capacity = cash / (1 + fee)
    qty, gross, rem = ZERO, ZERO, capacity
    for price, available in book["asks"]:
        take = min(available, rem / price)
        qty += take
        gross += take * price
        rem -= take * price
        if rem <= Decimal("0.0000000001"):
            break
    if rem > Decimal("0.0000000001"):
        return None
    return qty, gross, gross * fee


def sell_exact(book, qty, fee):
    """Simulate removing bids; no phantom partial execution."""
    qty, fee = dec(qty), dec(fee)
    if qty <= 0 or fee < 0:
        raise ValueError("bad quantity or fee")
    remaining = qty
    gross = ZERO
    for price, available in book["bids"]:
        take = min(available, remaining)
        gross += take * price
        remaining -= take
        if remaining <= Decimal("0.000000000001"):
            break
    if remaining > Decimal("0.000000000001"):
        return None
    return gross, gross * fee


def assess_cross(coin, buy_venue, sell_venue, buy, sell, cash=TRADE_NOTIONAL,
                 *, fetch_gap_seconds=0, slippage_each=SLIPPAGE_EACH,
                 rebalance=REBALANCE_RATE, latency=LATENCY_BUFFER):
    """Fully sized, conservative indicative cash economics. No simultaneous-fill proof."""
    if buy_venue == sell_venue:
        raise ValueError("different venues required")
    cash = dec(cash)
    if not ZERO < cash <= TRADE_NOTIONAL or cash * 2 > CAPITAL_LIMIT:
        raise ValueError("under-$1000 total capital guard")
    fee_buy = TAKER_FEES[buy_venue]
    fee_sell = TAKER_FEES[sell_venue]
    payload = {
        "coin": coin, "buy": buy_venue, "sell": sell_venue,
        "cash_buy_usd": money(cash), "required_prefunding_usd_or_equivalent": money(cash * 2),
        "funding_available_verified": False, "two_leg_atomicity": False,
        "individual_account_eligibility_verified": False,
        "quote_source": "public snapshot; non-atomic and not order commitments",
        "action": "NO_ORDER",
    }
    if fetch_gap_seconds > MAX_SCAN_SECONDS:
        payload.update(status="reject_stale_sequential_snapshot", verified_profit_usd=None)
        return payload
    bought = buy_with_budget(buy["book"], cash, fee_buy)
    if bought is None:
        payload.update(status="reject_insufficient_ask_depth", verified_profit_usd=None)
        return payload
    qty, spend, buy_fee = bought
    sold = sell_exact(sell["book"], qty, fee_sell)
    if sold is None:
        payload.update(status="reject_insufficient_bid_depth", verified_profit_usd=None)
        return payload
    proceeds, sell_fee = sold
    shock = (spend + proceeds) * dec(slippage_each)
    rebalance_usd = cash * dec(rebalance)
    latency_usd = cash * dec(latency)
    net = proceeds - spend - buy_fee - sell_fee - shock - rebalance_usd - latency_usd
    payload.update(
        quantity_coin=str(qty), gross_spread_usd=money(proceeds - spend),
        buy_fee_usd=money(buy_fee), sell_fee_usd=money(sell_fee),
        slippage_buffer_usd=money(shock), rebalance_buffer_usd=money(rebalance_usd),
        latency_buffer_usd=money(latency_usd), indicative_net_usd=money(net),
        verified_profit_usd=None,
        status="indicative_positive_unverified" if net >= MIN_SIGNAL_USD
               else "reject_not_positive_after_buffers",
    )
    return payload


def funding_observation(payload, cash=TRADE_NOTIONAL, *, observed_at=None, spot_reference=None, product="BTCUC"):
    """US Bitnomial PRELIMINARY 8-hour funding estimate, not a future payment."""
    if product not in FUNDING_CONTRACTS:
        raise ValueError("unsupported US futures product")
    coin, contract_units = FUNDING_CONTRACTS[product]
    observed_at = observed_at or datetime.now(timezone.utc)
    rate = dec(payload["funding_rate"])
    a = datetime.fromisoformat(payload["interval_start"].replace("Z", "+00:00"))
    b = datetime.fromisoformat(payload["interval_end"].replace("Z", "+00:00"))
    if not a < b or b - a > __import__("datetime").timedelta(hours=8, seconds=1) or not a <= observed_at < b:
        raise ValueError("funding interval stale or invalid")
    if abs(rate) > Decimal("0.05"):
        raise ValueError("implausible estimate")
    # All estimated funding uses the real minimum contractual underlying size.
    # If spot reference unavailable, show no imaginary trade-size economics.
    min_spot_usd = dec(spot_reference) * contract_units if spot_reference is not None else None
    # Clearinghouse indicates 15% baseline margin, FCM may demand more.
    min_margin_usd = min_spot_usd * Decimal("0.15") if min_spot_usd is not None else None
    min_total = min_spot_usd + min_margin_usd if min_spot_usd is not None else None
    blocked_capital = min_total is not None and min_total > CAPITAL_LIMIT
    # This is ONE 8-hour period, NOT an extrapolated daily guaranteed income.
    income = min_spot_usd * rate if min_spot_usd is not None else None
    return {
        "venue": "Bitnomial US", "product": product, "base_coin": coin, "type": "current_estimated_8h",
        "estimated_rate": str(rate), "interval_start": payload["interval_start"],
        "interval_end": payload["interval_end"], "minimum_contract_notional_usd": money(min_spot_usd) if min_spot_usd is not None else None,
        "estimated_gross_one_interval_usd": money(income) if income is not None else None,
        "net_usd": None, "verified_profit_usd": None,
        "minimum_futures_contract_btc": "0.01" if coin == "BTC" else None,
        "minimum_futures_contract_units": str(contract_units),
        "minimum_spot_hedge_usd": money(min_spot_usd) if min_spot_usd is not None else None,
        "indicative_minimum_futures_margin_15pct_usd": money(min_margin_usd) if min_margin_usd is not None else None,
        "indicative_total_cash_before_costs_usd": money(min_total) if min_total is not None else None,
        "status": "BLOCKED_MINIMUM_CONTRACT_PLUS_SPOT_HEDGE_EXCEEDS_CAPITAL" if blocked_capital
                  else "BLOCKED_NO_FUTURES_BOOK_FEE_CONTRACT_MARGIN_AND_ACCOUNT_ELIGIBILITY",
        "warning": "Future funding not guaranteed; sign can reverse; futures prices, costs, margin and precise matching spot hedge unknown.",
        "action": "NO_ORDER",
    }


def scan(*, spot_fetch=fetch_spot, get=public_get, monotonic=time.monotonic):
    start = monotonic()
    out = {"version": "1.0-read-only", "generated_at_utc": utc_now(),
           "capital_cap_usd": str(CAPITAL_LIMIT), "live_orders": 0,
           "actual_earnings_usd": 0, "trading_authorized": False,
           "spread_scenarios": [], "funding_scenarios": [], "errors": [],
           "funding_public_source": "https://bitnomial.com/exchange/docs/api/rest/funding-rates/",
           "funding_contract_size_source": "https://bitnomial.com/exchange/regulatory/cftc/product-filings/26-036.pdf",
           "eligibility": {"binance_us": "Illinois listed, Texas unsupported; individual and LLC approval unverified",
                           "kraken_us_futures": "US product available, state/identity/product verification required",
                           "coinbase_us_derivatives": "US product exists; customer access and API not verified"}}
    spot_references = {}
    for coin in SPOT_MARKETS:
        books = {}
        times = {}
        for venue in SPOT_MARKETS[coin]:
            try:
                t0 = monotonic()
                books[venue] = spot_fetch(coin, venue)
                times[venue] = (t0, monotonic())
            except (KeyError, TypeError, ValueError, OSError, TimeoutError) as exc:
                out["errors"].append({"coin": coin, "venue": venue, "error": type(exc).__name__,
                                      "description": str(exc)[:160]})
        if books:
            preferred = books.get("binance_us") or books.get("kraken") or next(iter(books.values()))
            spot_references[coin] = preferred["book"]["asks"][0][0]
        for buy in books:
            for sell in books:
                if buy == sell:
                    continue
                gap = max(times[buy][1], times[sell][1]) - min(times[buy][0], times[sell][0])
                out["spread_scenarios"].append(
                    assess_cross(coin, buy, sell, books[buy], books[sell], fetch_gap_seconds=gap))
    for product, (coin, units) in FUNDING_CONTRACTS.items():
        try:
            try:
                endpoint = BITNOMIAL.replace("BTCUC", product)
                funding_data = get(endpoint)
            except OSError:
                endpoint = BITNOMIAL_ALTERNATE.replace("BTCUC", product)
                funding_data = get(endpoint)
            obs = funding_observation(funding_data, spot_reference=spot_references.get(coin), product=product)
            obs["source_url"] = endpoint
            out["funding_scenarios"].append(obs)
        except (KeyError, TypeError, ValueError, OSError, TimeoutError) as exc:
            out["errors"].append({"venue": "bitnomial_us", "product": product,
                                  "error": type(exc).__name__, "description": str(exc)[:160],
                                  "funding_verified": False})
    out["completed_at_utc"] = utc_now()
    out["elapsed_seconds"] = round(monotonic() - start, 3)
    out["positive_indicative_unverified"] = sum(
        s["status"] == "indicative_positive_unverified" for s in out["spread_scenarios"])
    out["realized_profits_usd"] = 0
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="READ ONLY: under $1k cross-venue and US funding research")
    parser.add_argument("--out", default="output/alpha-v1.json")
    args = parser.parse_args(argv)
    report = scan()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"output": str(target), "scenarios": len(report["spread_scenarios"]),
                      "indicative_unverified": report["positive_indicative_unverified"],
                      "funding_observations": len(report["funding_scenarios"]),
                      "error_count": len(report["errors"]), "realized_profit": 0}))
    # Fail if no useful real cross-venue data; include JSON artifact for diagnosis.
    return 0 if report["spread_scenarios"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
