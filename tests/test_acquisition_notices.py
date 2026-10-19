import datetime as dt
import io
import unittest
from unittest.mock import patch

from acquisitions.notices import (
    NOTICE_FEEDS, parse_notice_feed, deadline_from_text,
    get_free_notice_rss, scan_notice_sources,
)
from acquisitions.pipeline import run

FIXTURE = b'''<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
<channel>
<item><title>PUBLIC NOTICE CHAPTER 11 363 SALE: WidgetCo</title>
<link>https://www.dailydac.com/widgetco-sale/</link>
<description><![CDATA[<p>Bid Deadline for Qualified Bids and Deposits: 4:00 pm October 28, 2026.</p>]]></description>
<content:encoded><![CDATA[<p>Transfer of customer contracts subject to court approval.</p>]]></content:encoded>
<pubDate>Sun, 18 Oct 2026 12:00:00 GMT</pubDate></item>
<item><title>PUBLIC NOTICE PROSPECTIVE CHAPTER 11 363 SALE: Foundry</title>
<link>https://www.dailydac.com/foundry/</link>
<description>Prospective chapter 11 before any case filing; financing under discussion</description></item>
<item><title>PUBLIC NOTICE ARTICLE 9 SALE: Brewery</title>
<link>https://www.dailydac.com/brewery/</link>
<description>Bid deadline October 11, 2026.</description></item>
<item><title>PUBLIC NOTICE CHAPTER 11 SALE: blocked</title>
<link>https://pacer.uscourts.gov/cgi-bin/document</link>
<description>Bid deadline October 30, 2026</description></item>
</channel></rss>'''

class FakeResponse:
    def __init__(self, body):
        self.headers = {"Content-Length": str(len(body))}
        self.f = io.BytesIO(body)
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, n): return self.f.read(n)

class PublicNoticeTests(unittest.TestCase):
    def setUp(self):
        self.today = dt.date(2026, 10, 19)

    def test_real_bid_date_from_label_not_publication_or_auction(self):
        rows = parse_notice_feed(FIXTURE, "TEST", list(NOTICE_FEEDS.values())[0], today=self.today)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["bid_deadline_as_published"], "2026-10-28")
        self.assertEqual(rows[0]["status"], "FUTURE_DATE_REQUIRES_FRESH_VERIFICATION")
        self.assertIn("contract", rows[0]["contract_related_mentions"])
        self.assertIsNone(rows[0]["purchase_price_usd"])
        self.assertFalse(rows[0]["verified_actionable"])
        self.assertEqual(rows[1]["status"], "PROSPECTIVE_NOT_FILED")
        self.assertEqual(rows[2]["status"], "BID_DATE_PAST_AS_PUBLISHED")

    def test_no_deadline_inferred_from_auction(self):
        self.assertEqual(deadline_from_text(
            "The auction is November 5, 2026. Sale hearing December 12, 2026."), (None, None))

    def test_allowlisted_rss_no_paid_links_followed(self):
        requests = []
        def opener(req, timeout):
            requests.append(req.full_url)
            return FakeResponse(FIXTURE)
        self.assertEqual(get_free_notice_rss(list(NOTICE_FEEDS.values())[0], opener=opener), FIXTURE)
        self.assertEqual(len(requests), 1)
        with self.assertRaises(ValueError):
            get_free_notice_rss("https://pacer.uscourts.gov/", opener=opener)
        self.assertEqual(len(requests), 1)

    def test_dedup_and_source_errors_reported(self):
        with patch("acquisitions.notices.get_free_notice_rss", return_value=FIXTURE):
            result = scan_notice_sources(today=self.today)
        self.assertEqual(result["free_sale_notice_matches"], 3)
        self.assertEqual(result["future_bid_dates_unconfirmed"], 1)
        self.assertEqual(result["verified_actionable_deals"], 0)
        with patch("acquisitions.notices.get_free_notice_rss", return_value=b"<bad"):
            result = scan_notice_sources(today=self.today)
        self.assertEqual(len(result["source_errors"]), len(NOTICE_FEEDS))
        self.assertEqual(result["free_sale_notice_matches"], 0)

    def test_news_feed_is_not_a_primary_sale_notice(self):
        news = b'''<rss><channel><item><title>Company Chapter 11 bankruptcy asset sale</title>
<link>https://news.google.com/rss/articles/sample</link>
<description>Sale auction date October 30, 2026.</description></item></channel></rss>'''
        rows = parse_notice_feed(news, "PUBLIC_NEWS_DISCOVERY", NOTICE_FEEDS["PUBLIC_NEWS_DISCOVERY"], today=self.today)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_type"], "PUBLIC_NEWS_DISCOVERY_UNVERIFIED")
        self.assertIsNone(rows[0]["bid_deadline_as_published"])
        self.assertFalse(rows[0]["verified_actionable"])

    def test_combined_report_never_claims_financeability(self):
        with patch("acquisitions.pipeline.scan_courts", return_value={
            "courts_failed": {}, "potential_docket_leads": 0
        }), patch("acquisitions.pipeline.scan_notice_sources", return_value={
            "source_errors": {}, "free_sale_notice_matches": 3, "notice_candidates": []
        }):
            result = run()
        self.assertEqual(result["verified_financeable_acquisitions"], 0)
        self.assertEqual(result["pacer_requests"], 0)
        self.assertEqual(result["automated_bids"], 0)

if __name__ == "__main__":
    unittest.main()
