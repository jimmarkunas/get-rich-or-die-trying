"""Deterministic, network-free v1 profit engine safety and accounting checks."""
import json
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import Mock
from alpha.profit_v1 import (
    ALLOW, BITNOMIAL, CAPITAL_LIMIT, SPOT_MARKETS, TRADE_NOTIONAL,
    assess_cross, buy_with_budget, dec, funding_observation,
    normalize, parse_book, public_get, scan, sell_exact,
)


def book(bid="100", ask="101", qty="100"):
    return {"book": normalize([[bid, qty]], [[ask, qty]])}


def funding(rate="0.0001", now=None):
    now = now or datetime.now(timezone.utc)
    begin = now - timedelta(hours=1)
    end = begin + timedelta(hours=8)
    return {"funding_rate": rate, "interval_start": begin.isoformat(),
            "interval_end": end.isoformat()}


class ProfitReadOnlyTests(unittest.TestCase):
    def test_safe_cap(self):
        self.assertEqual(CAPITAL_LIMIT, Decimal("900"))
        self.assertLess(CAPITAL_LIMIT, 1000)
        self.assertLessEqual(TRADE_NOTIONAL * 2, CAPITAL_LIMIT)

    def test_all_markets_fiat_usd_and_whitelisted(self):
        self.assertEqual(set(SPOT_MARKETS), {"BTC", "ETH", "SOL"})
        self.assertIn("bitnomial.com", ALLOW)
        for venue in SPOT_MARKETS["BTC"]:
            self.assertIn(venue, ("kraken", "binance_us", "coinbase_exchange"))

    def test_rejects_nan_and_infinity(self):
        for v in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaises(ValueError):
                dec(v)

    def test_validates_empty_or_crossed(self):
        with self.assertRaises(ValueError):
            normalize([], [["100", "1"]])
        with self.assertRaises(ValueError):
            normalize([["100", "1"]], [["99", "1"]])
        with self.assertRaises(ValueError):
            normalize([["100", "1"], ["100", "2"]], [["101", "1"]])

    def test_parse_binance(self):
        x = parse_book("binance_us", {"bids": [["100", "3"]], "asks": [["101", "4"]]})
        self.assertEqual(x["bids"][0], (Decimal("100"), Decimal("3")))

    def test_parse_kraken(self):
        x = parse_book("kraken", {"error": [], "result": {
            "XXBTZUSD": {"bids": [["100", "3", 1]], "asks": [["101", "4", 1]]}}})
        self.assertEqual(x["asks"][0][0], Decimal("101"))

    def test_kraken_multiple_pairs_refused(self):
        with self.assertRaises(ValueError):
            parse_book("kraken", {"error": [], "result": {"one": {}, "two": {}}})

    def test_parse_coinbase(self):
        x = parse_book("coinbase_exchange", {"bids": [["100", "3", 1]], "asks": [["101", "4", 1]]})
        self.assertEqual(x["bids"][0][0], Decimal("100"))

    def test_no_post_or_private_access(self):
        for uri in (
            "https://api.binance.us/api/v3/order",
            "https://api.kraken.com/0/private/AddOrder",
            "http://api.binance.us/api/v3/depth",
            "https://evil.test/api/v3/depth",
            "https://api.binance.us:8080/api/v3/depth",
            "https://api.binance.us/api/v3/depth?foo=1",
            "https://bitnomial.com/exchange/api/v1/prod/orders",
        ):
            with self.assertRaises(ValueError, msg=uri):
                public_get(uri, opener=Mock(side_effect=AssertionError("network unexpectedly invoked")))

    def test_public_get_is_get_no_auth(self):
        mock_resp = Mock()
        mock_resp.__enter__ = Mock(return_value=mock_resp)
        mock_resp.__exit__ = Mock(return_value=False)
        mock_resp.read.return_value = b'{"bids":[],"asks":[]}'
        opener = Mock(return_value=mock_resp)
        out = public_get("https://api.binance.us/api/v3/depth",
                         params={"symbol": "BTCUSD", "limit": 20}, opener=opener)
        self.assertEqual(out, {"bids": [], "asks": []})
        req = opener.call_args.args[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertNotIn("Authorization", dict(req.header_items()))
        self.assertIn("symbol=BTCUSD", req.full_url)

    def test_depth_buy_partial_refuses(self):
        tiny = normalize([["99", "10"]], [["100", "0.1"]])
        self.assertIsNone(buy_with_budget(tiny, Decimal("150"), Decimal("0.001")))

    def test_depth_sell_partial_refuses(self):
        tiny = normalize([["99", "0.1"]], [["100", "10"]])
        self.assertIsNone(sell_exact(tiny, Decimal("1"), Decimal("0.001")))

    def test_buy_budget_includes_fee(self):
        b = book()
        qty, gross, fee = buy_with_budget(b["book"], 150, Decimal("0.008"))
        self.assertAlmostEqual(float(gross + fee), 150)
        self.assertGreater(qty, 0)

    def test_reject_same_venue_and_cap(self):
        with self.assertRaises(ValueError):
            assess_cross("BTC", "kraken", "kraken", book(), book())
        with self.assertRaises(ValueError):
            assess_cross("BTC", "kraken", "binance_us", book(), book(), cash=500)

    def test_false_spread_rejected_after_fees(self):
        result = assess_cross("BTC", "binance_us", "kraken",
                              book("99", "100"), book("100.5", "101"))
        self.assertEqual(result["status"], "reject_not_positive_after_buffers")
        self.assertLess(Decimal(result["indicative_net_usd"]), 0)
        self.assertIsNone(result["verified_profit_usd"])

    def test_apparent_positive_indicative_but_no_verified_profit(self):
        result = assess_cross("BTC", "binance_us", "kraken",
                              book("99", "100"), book("104", "105"))
        self.assertEqual(result["status"], "indicative_positive_unverified")
        self.assertGreater(Decimal(result["indicative_net_usd"]), 0)
        self.assertIsNone(result["verified_profit_usd"])
        self.assertEqual(result["action"], "NO_ORDER")
        self.assertFalse(result["funding_available_verified"])
        self.assertFalse(result["two_leg_atomicity"])

    def test_stale_sequential_quotes_refused(self):
        result = assess_cross("BTC", "binance_us", "kraken", book("99", "100"),
                              book("105", "106"), fetch_gap_seconds=30)
        self.assertEqual(result["status"], "reject_stale_sequential_snapshot")

    def test_rebalancing_and_slippage_reduce_profit(self):
        low = assess_cross("BTC", "binance_us", "kraken", book("99", "100"), book("104", "105"),
                           slippage_each="0", rebalance="0", latency="0")
        high = assess_cross("BTC", "binance_us", "kraken", book("99", "100"), book("104", "105"))
        self.assertGreater(Decimal(low["indicative_net_usd"]), Decimal(high["indicative_net_usd"]))

    def test_funding_has_no_verified_net(self):
        sample = funding("0.0001")
        x = funding_observation(sample)
        self.assertEqual(x["status"], "BLOCKED_NO_FUTURES_BOOK_FEE_CONTRACT_SIZE_MARGIN_AND_ACCOUNT_ELIGIBILITY")
        self.assertEqual(x["estimated_gross_one_interval_usd"], "0.015000")
        self.assertIsNone(x["net_usd"])
        self.assertIsNone(x["verified_profit_usd"])

    def test_negative_funding_is_a_cost_for_short(self):
        x = funding_observation(funding("-0.0001"))
        self.assertEqual(x["estimated_gross_one_interval_usd"], "-0.015000")

    def test_expired_funding_refused(self):
        now = datetime.now(timezone.utc)
        with self.assertRaises(ValueError):
            funding_observation(funding("0.0001", now-timedelta(days=2)), observed_at=now)

    def test_absurd_rate_refused(self):
        with self.assertRaises(ValueError):
            funding_observation(funding("1.0"))

    def test_scan_success_and_safety(self):
        # Stub real data transport: deterministic out-of-order venue quotes.
        def spot(coin, venue):
            return book("101", "102") if venue == "kraken" else book("99", "100")
        obj = scan(spot_fetch=spot, get=lambda url: funding("0.0002"))
        self.assertEqual(len(obj["spread_scenarios"]), 18)
        self.assertEqual(len(obj["funding_scenarios"]), 1)
        self.assertEqual(obj["actual_earnings_usd"], 0)
        self.assertEqual(obj["live_orders"], 0)
        self.assertFalse(obj["trading_authorized"])
        self.assertTrue(all(x["action"] == "NO_ORDER" for x in obj["spread_scenarios"]))

    def test_partial_failure_keeps_diagnostics(self):
        def spot(coin, venue):
            if venue == "coinbase_exchange":
                raise ValueError("exchange temporarily unavailable")
            return book()
        o = scan(spot_fetch=spot, get=lambda url: (_ for _ in ()).throw(ValueError("gone")))
        self.assertEqual(len(o["spread_scenarios"]), 6)
        self.assertEqual(len(o["funding_scenarios"]), 0)
        self.assertGreaterEqual(len(o["errors"]), 4)
        self.assertEqual(o["live_orders"], 0)


if __name__ == "__main__":
    unittest.main()
