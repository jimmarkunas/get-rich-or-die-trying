import io
import unittest
from unittest.mock import patch

from acquisitions.scout import FEEDS, fetch_public_feed, parse_feed, scan

RSS = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>IL Docket</title>
<item><title>In re ABC: Motion for sale of business assets</title><description>Assignment of customer contracts &amp; assets</description><link>https://ecf.ilnb.uscourts.gov/cgi-bin/ShowDoc.pl?foo</link><pubDate>Sun, 18 Oct 2026 12:00:00 GMT</pubDate></item>
<item><title>Proof of claim</title><description>Unrelated</description><link>https://example.org/a</link></item>
<item><title>Foreclosure sale of assets</title><description>Personal property</description></item>
</channel></rss>'''

class FakeResponse:
    def __init__(self, data):
        self.data = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, n): return self.data.read(n)

class ScoutTest(unittest.TestCase):
    def test_only_relevant_entries_no_fabricated_terms(self):
        x = parse_feed(RSS, "ILNB", FEEDS["ILNB"])
        self.assertEqual(len(x), 1)
        self.assertEqual(x[0]["status"], "UNVERIFIED_DOCKET_LEAD")
        self.assertIsNone(x[0]["bid_deadline"])
        self.assertIsNone(x[0]["contracts_assignable"])
        self.assertIsNone(x[0]["verified_cash_flow_usd"])
        self.assertIn("contract", x[0]["keywords"])
    def test_no_pacer_link_following(self):
        calls=[]
        def opener(req, timeout):
            calls.append(req.full_url)
            return FakeResponse(RSS)
        fetch_public_feed(FEEDS["ILNB"], opener=opener)
        self.assertEqual(calls, [FEEDS["ILNB"]])
        with self.assertRaises(ValueError):
            fetch_public_feed("https://pacer.uscourts.gov/", opener=opener)
    def test_invalid_xml_degrades(self):
        with patch("acquisitions.scout.fetch_public_feed", return_value=b"not xml"):
            out = scan({"ILNB": FEEDS["ILNB"]})
        self.assertEqual(out["verified_live_financeable_deals"], 0)
        self.assertIn("ILNB", out["courts_failed"])
    def test_scan_deduplicates_and_fails_closed(self):
        with patch("acquisitions.scout.fetch_public_feed", return_value=RSS):
            out = scan({"ILNB": FEEDS["ILNB"]})
        self.assertEqual(out["potential_docket_leads"], 1)
        self.assertEqual(out["pacer_requests"], 0)
        self.assertEqual(out["fees_incurred_usd"], 0)
        self.assertEqual(out["verified_live_financeable_deals"], 0)

if __name__ == "__main__":
    unittest.main()
